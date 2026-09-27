# XAUUSD Scalper V1 — Demo/Paper

This build is deliberately **paper-only**. It reads OANDA Practice data and generates setups, but `/paper-order` never calls the broker order endpoint.

## Strategy
- M5: EMA20 vs EMA50 directional filter
- M1: recent liquidity sweep + candle reclaim
- ATR-based stop distance
- TP = 1.2R
- spread filter
- daily trade-count limit
- bot kill switch

This is a starter rule engine, not a claim of profitability. XAUUSD spreads, volatility and contract specifications vary by broker.

## Run locally
1. Install Python 3.10+.
2. Copy `.env.example` to `.env`.
3. Create an OANDA Practice account and API token.
4. Put the account ID and token in `.env`.
5. Start:
   `pip install -r requirements.txt`
   `uvicorn app:app --host 0.0.0.0 --port 8000`
6. Open `http://127.0.0.1:8000/docs`.
7. Serve the frontend separately or put it behind the same cloud service.

## OANDA
OANDA documents `https://api-fxpractice.oanda.com` as the Practice REST environment for testing. The API supports real-time prices, historical candles, and trading operations. Keep the token secret.

Before setting `OANDA_INSTRUMENT`, call `/instruments` and choose the Gold instrument actually available in your Practice account.

## Production architecture
GitHub Pages = dashboard only.
Cloud backend = strategy + broker connection.
Broker token = backend environment secret.

Do not put OANDA_TOKEN in GitHub Pages JavaScript or commit `.env`.
