# Polymarket BTC Trading Bot

Automated 5-minute BTC prediction market trading bot for Polymarket with X (Twitter) sentiment analysis, technical indicators, and a real-time dashboard.

## Features

- **5-Minute Trading Cycles** - Scans Polymarket BTC markets every 5 minutes
- **X Sentiment Analysis** - Fetches and scores recent BTC tweets for bullish/bearish signals
- **Technical Analysis** - RSI, MACD, Bollinger Bands, EMA crossovers, momentum
- **Signal Fusion** - Combines technical + sentiment signals with configurable weights
- **Paper Trading Mode** - Works without API keys for testing
- **Real-time Dashboard** - React frontend with live data polling
- **TradingView Charts** - Embedded BTC charts with indicators
- **P/L Tracking** - Full trade history, win rate, cumulative P/L charts
- **VPS Ready** - Docker Compose deployment for any VPS

## Architecture

```
├── backend/                # Python FastAPI
│   ├── app/
│   │   ├── api/           # REST endpoints
│   │   ├── core/          # Config, database
│   │   ├── models/        # SQLAlchemy models
│   │   ├── services/      # Polymarket client, X sentiment, trading engine
│   │   └── strategies/    # Signal generators (RSI, MACD, BB, etc.)
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/              # React dashboard
│   ├── src/
│   │   ├── components/    # TradingView, P/L chart, signals, trades
│   │   ├── hooks/         # Polling hooks
│   │   └── services/      # API client
│   └── Dockerfile
├── docker-compose.yml     # VPS deployment
└── scripts/               # Deploy & run scripts
```

## Quick Start

### 1. Clone & Configure

```bash
git clone <repo-url>
cd Bot-cluade
cp .env.example .env
# Edit .env with your API keys
```

### 2. Deploy on VPS (Docker)

```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

### 3. Local Development

```bash
chmod +x scripts/run_local.sh
./scripts/run_local.sh
```

## Configuration (.env)

| Variable | Description |
|----------|-------------|
| `POLYMARKET_API_KEY` | Polymarket CLOB API key |
| `POLYMARKET_SECRET` | Polymarket API secret |
| `POLYMARKET_PASSPHRASE` | Polymarket passphrase |
| `POLYMARKET_FUNDER` | Your wallet address |
| `X_BEARER_TOKEN` | X/Twitter API v2 bearer token |
| `BOT_INTERVAL_SECONDS` | Trading interval (default: 300 = 5 min) |
| `MAX_POSITION_SIZE` | Max position size in USD |
| `RISK_PER_TRADE` | Risk percentage per trade (0.02 = 2%) |
| `STOP_LOSS_PCT` | Stop loss percentage |
| `TAKE_PROFIT_PCT` | Take profit percentage |

**Paper Trading**: Leave `POLYMARKET_API_KEY` empty to run in paper trading mode (no real orders).

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/bot/start` | POST | Start the trading bot |
| `/api/bot/stop` | POST | Stop the trading bot |
| `/api/bot/status` | GET | Bot status + last signal |
| `/api/bot/run-once` | POST | Run single trading cycle |
| `/api/markets` | GET | List BTC markets |
| `/api/sentiment` | GET | Current X sentiment |
| `/api/portfolio` | GET | Portfolio summary + P/L |
| `/api/trades` | GET | Trade history |
| `/api/settings` | GET | Current configuration |
| `/health` | GET | Health check |

## Trading Strategy

The bot combines two signal sources:

1. **Technical Analysis (60% weight)**
   - RSI (oversold < 30, overbought > 70)
   - MACD crossovers
   - Bollinger Band position
   - EMA 5/20 crossover
   - Price momentum

2. **X Sentiment (40% weight)**
   - Keyword-based scoring of recent BTC tweets
   - Engagement-weighted (likes, retweets)
   - Bullish/bearish word matching

Trades execute when:
- Combined signal direction is BUY or SELL (not HOLD)
- Confidence > 20%
- Position size scaled by signal strength

## Dashboard Pages

- **Dashboard** - Stats cards, P/L chart, signal panel, sentiment, trades table
- **Chart** - Full TradingView BTC chart with RSI, MACD, Bollinger Bands
- **Markets** - Live Polymarket BTC markets with prices and volume
- **Settings** - Configuration view and raw bot status

## VPS Deployment Notes

- Recommended: 1 vCPU, 1GB RAM minimum
- Uses SQLite (file-based) - no external database needed
- Data persists in `./data/` volume
- Logs in `bot.log`
- Auto-restarts on crash via Docker `unless-stopped` policy
