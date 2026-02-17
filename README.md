# Poly Copy Cat Bot

Free, open-source copy trading bot for [Polymarket](https://polymarket.com). Monitors the top-performing trader wallets and mirrors their positions on your wallet.

**Paper trading is on by default.** The bot logs what it would trade without risking real money until you opt in.

## Quick Start

```bash
git clone https://github.com/joe-froobs/poly-copy-cat-bot.git
cd poly-copy-cat-bot
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your settings
python -m src.main
```

## Getting an API Key

The bot fetches ranked trader data from the [Poly Copy Cat](https://polycopycatbot.com) leaderboard API.

1. Sign up at [polycopycatbot.com](https://polycopycatbot.com)
2. Subscribe ($49/mo)
3. Go to Dashboard > API Keys
4. Generate a key and copy it
5. Add it to your `.env` file as `PCC_API_KEY`

## Manual Wallet Addresses

Don't want to subscribe? You can manually specify trader wallet addresses instead:

```
MANUAL_TRADERS=0xabc123...,0xdef456...,0x789ghi...
```

Find good traders on the [Polymarket leaderboard](https://polymarket.com/leaderboard) and paste their wallet addresses.

## Configuration

All settings are in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `PCC_API_KEY` | (none) | Your Poly Copy Cat API key |
| `MANUAL_TRADERS` | (none) | Comma-separated wallet addresses (fallback) |
| `PAPER_TRADING` | `true` | Set to `false` for live trading |
| `PRIVATE_KEY` | (none) | Your wallet private key (live trading only) |
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

When you're comfortable, set `PAPER_TRADING=false` and add your `PRIVATE_KEY` to go live.

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

The bot is stateless -- positions are tracked in memory during runtime. If you restart, it re-establishes a baseline on the first scan and only trades on subsequent changes.

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
