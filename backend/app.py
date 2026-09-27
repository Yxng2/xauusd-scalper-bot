import os, asyncio, math, statistics
from datetime import datetime, timezone
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
BASE=os.getenv("OANDA_BASE_URL","https://api-fxpractice.oanda.com")
ACCOUNT=os.getenv("OANDA_ACCOUNT_ID","")
TOKEN=os.getenv("OANDA_TOKEN","")
INSTRUMENT=os.getenv("OANDA_INSTRUMENT","XAU_USD")
RISK=float(os.getenv("RISK_PERCENT","0.25"))
MAX_DAILY_LOSS=float(os.getenv("MAX_DAILY_LOSS_PERCENT","2"))
MAX_TRADES=int(os.getenv("MAX_TRADES_PER_DAY","10"))
MAX_SPREAD=float(os.getenv("MAX_SPREAD","0.80"))
RR=float(os.getenv("RR","1.20"))
POLL=int(os.getenv("POLL_SECONDS","5"))

app=FastAPI(title="XAUUSD Scalper V1")
state={"enabled":False,"trades":[],"last_signal":None,"daily_pnl":0.0,"daily_trades":0}

def headers():
    return {"Authorization":f"Bearer {TOKEN}","Content-Type":"application/json"}

async def api_get(path, params=None):
    if not ACCOUNT or not TOKEN: raise HTTPException(500,"Set OANDA_ACCOUNT_ID and OANDA_TOKEN in .env")
    async with httpx.AsyncClient(timeout=15) as c:
        r=await c.get(BASE+path,headers=headers(),params=params)
        if r.status_code>=400: raise HTTPException(r.status_code,r.text)
        return r.json()

async def api_post(path, payload):
    if not ACCOUNT or not TOKEN: raise HTTPException(500,"Set OANDA_ACCOUNT_ID and OANDA_TOKEN in .env")
    async with httpx.AsyncClient(timeout=15) as c:
        r=await c.post(BASE+path,headers=headers(),json=payload)
        if r.status_code>=400: raise HTTPException(r.status_code,r.text)
        return r.json()

@app.get("/health")
async def health():
    return {"ok":True,"mode":"DEMO/PRACTICE","instrument":INSTRUMENT,"enabled":state["enabled"]}

@app.get("/account")
async def account():
    return await api_get(f"/v3/accounts/{ACCOUNT}")

@app.get("/instruments")
async def instruments():
    data=await api_get(f"/v3/accounts/{ACCOUNT}/instruments")
    return [x for x in data.get("instruments",[]) if "XAU" in x["name"].upper() or "GOLD" in x["name"].upper()]

@app.get("/prices")
async def prices():
    return await api_get(f"/v3/accounts/{ACCOUNT}/pricing",{"instruments":INSTRUMENT})

@app.get("/candles/{granularity}")
async def candles(granularity:str="M1"):
    if granularity not in {"M1","M5"}: raise HTTPException(400,"Use M1 or M5")
    return await api_get(f"/v3/instruments/{INSTRUMENT}/candles",{"granularity":granularity,"count":200,"price":"M"})

def closes(data):
    return [float(c["mid"]["c"]) for c in data["candles"] if c.get("complete")]

def ema(values, n):
    if len(values)<n: return None
    k=2/(n+1); e=sum(values[:n])/n
    for v in values[n:]: e=v*k+e*(1-k)
    return e

def atr(data,n=14):
    cs=[c for c in data["candles"] if c.get("complete")]
    if len(cs)<n+1:return None
    trs=[]
    prev=float(cs[0]["mid"]["c"])
    for c in cs[1:]:
        h=float(c["mid"]["h"]);l=float(c["mid"]["l"])
        trs.append(max(h-l,abs(h-prev),abs(l-prev)))
        prev=float(c["mid"]["c"])
    return sum(trs[-n:])/n

def strategy(m1,m5, bid, ask):
    c1=[c for c in m1["candles"] if c.get("complete")]
    c5=[c for c in m5["candles"] if c.get("complete")]
    if len(c1)<30 or len(c5)<60:return None
    x5=[float(c["mid"]["c"]) for c in c5]
    fast=ema(x5,20); slow=ema(x5,50)
    if not fast or not slow:return None
    bias="BUY" if fast>slow else "SELL"
    recent=c1[-4:]
    # Simple liquidity-sweep + reclaim confirmation:
    prev=c1[-2]; last=c1[-1]
    ph=max(float(c["mid"]["h"]) for c in c1[-8:-2])
    pl=min(float(c["mid"]["l"]) for c in c1[-8:-2])
    lh,ll=float(last["mid"]["h"]),float(last["mid"]["l"])
    lc=float(last["mid"]["c"])
    if bias=="BUY" and ll<pl and lc>float(last["mid"]["o"]):
        side="BUY"; extreme=ll
    elif bias=="SELL" and lh>ph and lc<float(last["mid"]["o"]):
        side="SELL"; extreme=lh
    else:return None
    a=atr(m1)
    if not a:return None
    spread=ask-bid
    if spread>MAX_SPREAD:return None
    # Stop is based on sweep extreme with an ATR floor.
    sl_dist=max(abs(lc-extreme)+0.05,a*0.65)
    entry=ask if side=="BUY" else bid
    sl=entry-sl_dist if side=="BUY" else entry+sl_dist
    tp=entry+sl_dist*RR if side=="BUY" else entry-sl_dist*RR
    return {"side":side,"entry":entry,"sl":sl,"tp":tp,"spread":spread,"atr":a,"bias":bias}

@app.post("/scan")
async def scan():
    p=await prices()
    price=p["prices"][0]
    bid=float(price["bids"][0]["price"]);ask=float(price["asks"][0]["price"])
    m1=await api_get(f"/v3/instruments/{INSTRUMENT}/candles",{"granularity":"M1","count":200,"price":"M"})
    m5=await api_get(f"/v3/instruments/{INSTRUMENT}/candles",{"granularity":"M5","count":200,"price":"M"})
    sig=strategy(m1,m5,bid,ask)
    state["last_signal"]=sig
    return {"price":{"bid":bid,"ask":ask},"signal":sig}

class BotToggle(BaseModel):
    enabled: bool

@app.post("/bot")
async def bot(toggle:BotToggle):
    state["enabled"]=toggle.enabled
    return {"enabled":state["enabled"],"mode":"PRACTICE"}

@app.get("/state")
async def get_state():
    return state

@app.post("/paper-order")
async def paper_order():
    result=await scan()
    sig=result["signal"]
    if not sig:return {"opened":False,"reason":"No valid setup"}
    if state["daily_trades"]>=MAX_TRADES:return {"opened":False,"reason":"Daily trade limit reached"}
    state["daily_trades"]+=1
    # Deliberately paper only: no order endpoint is called.
    trade={**sig,"time":datetime.now(timezone.utc).isoformat(),"status":"PAPER"}
    state["trades"].insert(0,trade)
    return {"opened":True,"trade":trade}

@app.on_event("startup")
async def startup():
    async def loop():
        while True:
            await asyncio.sleep(POLL)
            if state["enabled"]:
                try:
                    await scan()
                except Exception as e:
                    state["last_error"]=str(e)
    asyncio.create_task(loop())
