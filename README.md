# Poly Copy Cat Bot

Free, open-source copy trading bot for [Polymarket](https://polymarket.com). Monitors the top-performing trader wallets and mirrors their positions on your wallet.

**Paper trading is on by default.** The bot logs what it would trade without risking real money until you opt in.

## Quick Start

```bash
git clone https://github.com/joe-froobs/polycopycatbot.git
cd polycopycatbot
pip3 install -r requirements.txt
python3 -m src.main
```

The bot opens a local dashboard at **http://localhost:8532** and walks you through setup:

1. Accept terms of service
2. Enter your API key or paste trader wallet addresses
3. Configure risk settings (paper trading is on by default)
4. Launch the bot

All configuration is stored locally in a SQLite database. No `.env` editing required.

### Headless Mode (CLI only)

If you prefer the original CLI experience without the web dashboard:

```bash
cp .env.example .env
# Edit .env with your settings
python3 -m src.main --headless
```

## Getting an API Key

The bot fetches ranked trader data from the [Poly Copy Cat](https://polycopycatbot.com) leaderboard API.

1. Sign up at [polycopycatbot.com](https://polycopycatbot.com)
2. Subscribe ($49/mo)
3. Go to Dashboard > API Keys
4. Generate a key and copy it
5. Enter it during setup (or add to `.env` as `PCC_API_KEY` for headless mode)

## Manual Wallet Addresses

Don't want to subscribe? You can manually specify trader wallet addresses instead. Paste them during setup, or for headless mode:

```
MANUAL_TRADERS=0xabc123...,0xdef456...,0x789ghi...
```

Find good traders on the [Polymarket leaderboard](https://polymarket.com/leaderboard) and paste their wallet addresses.

## Dashboard Features

- **Onboarding Wizard** -- Guided 4-step setup, no config files to edit
- **Bot Control** -- Start/stop the bot from the browser
- **Live Positions** -- See open positions with auto-refresh
- **Activity Log** -- Track all trades, starts, stops, and errors
- **Trader Management** -- Add/remove/toggle trader addresses
- **Settings** -- Edit risk controls and API keys with instant apply

## Configuration

All settings can be configured through the web dashboard. For headless mode, use `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `PCC_API_KEY` | (none) | Your Poly Copy Cat API key |
| `MANUAL_TRADERS` | (none) | Comma-separated wallet addresses (fallback) |
| `PAPER_TRADING` | `true` | Set to `false` for live trading |
| `PRIVATE_KEY` | (none) | Your wallet private key (live trading only) |
| `FUNDER_ADDRESS` | (none) | Your Polymarket proxy wallet address (live trading only) |
| `RPC_URL` | `https://polygon-rpc.com` | Polygon RPC endpoint |
| `MAX_TRADERS` | `5` | How many top traders to copy (1-20) |
| `POLL_INTERVAL` | `5` | Seconds between polls |
| `MAX_POSITION_USD` | `50` | Max USD per position |
| `MAX_CONCURRENT_POSITIONS` | `10` | Max open positions at once |
| `DAILY_LOSS_LIMIT_USD` | `100` | Stop trading after this much loss in a day |

## Paper Trading

Paper trading is enabled by default. The bot will:

- Fetch trader rankings from the API (or use manual addresses)
- Monitor trader wallets for position changes
- Log what trades it *would* make, with exact sizes
- Track simulated P&L

When you're comfortable, switch to live trading in the dashboard settings (or set `PAPER_TRADING=false` in `.env`). You'll need your `PRIVATE_KEY` and `FUNDER_ADDRESS` for live trading. Your funder address is the Polymarket proxy wallet linked to your account.

## Risk Controls

- **Max position size**: Caps any single position at `MAX_POSITION_USD`
- **Max concurrent positions**: Won't open more than `MAX_CONCURRENT_POSITIONS` at once
- **Daily loss limit**: Stops opening new positions after `DAILY_LOSS_LIMIT_USD` in losses
- **Proportional sizing**: Position sizes scale with trader's size (assumes trader has ~10x your capital)

## How It Works

1. Fetches top trader addresses from the Poly Copy Cat API
2. Polls each trader's Polymarket positions every few seconds
3. Detects new, adjusted, and closed positions
4. Mirrors those changes on your wallet (or logs them in paper mode)
5. All activity is logged to a local SQLite database and visible in the dashboard

## Requirements

- Python 3.11+
- A Polygon wallet with USDC (for live trading)
- A Poly Copy Cat API key (or manual trader addresses)

## Disclaimer

This software is for educational purposes only. It is not financial advice. Trading on prediction markets involves risk of loss. Use at your own risk.

- Past performance of copied traders does not guarantee future results
- The bot may execute trades that result in losses
- You are solely responsible for your trading decisions
- The authors are not liable for any financial losses

## License

MIT
