import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # API
    api_url: str = os.getenv("PCC_API_URL", "https://polycopycatbot.com/api/traders")
    api_key: str = os.getenv("PCC_API_KEY", "")

    # Wallet
    private_key: str = os.getenv("PRIVATE_KEY", "")
    funder: str = os.getenv("FUNDER_ADDRESS", "")
    rpc_url: str = os.getenv("RPC_URL", "https://polygon-rpc.com")

    # Trading
    paper_trading: bool = os.getenv("PAPER_TRADING", "true").lower() == "true"
    max_traders: int = int(os.getenv("MAX_TRADERS", "5"))
    poll_interval: int = int(os.getenv("POLL_INTERVAL", "5"))

    # Risk controls
    max_position_usd: float = float(os.getenv("MAX_POSITION_USD", "50"))
    max_concurrent_positions: int = int(os.getenv("MAX_CONCURRENT_POSITIONS", "10"))
    daily_loss_limit_usd: float = float(os.getenv("DAILY_LOSS_LIMIT_USD", "100"))

    # Manual trader addresses (comma-separated, fallback if no API key)
    manual_traders: list[str] = field(default_factory=list)

    def __post_init__(self):
        raw = os.getenv("MANUAL_TRADERS", "")
        if raw:
            self.manual_traders = [a.strip() for a in raw.split(",") if a.strip()]

    def validate(self) -> list[str]:
        errors = []
        if not self.api_key and not self.manual_traders:
            errors.append("Set PCC_API_KEY or MANUAL_TRADERS in .env")
        if not self.paper_trading and not self.private_key:
            errors.append("PRIVATE_KEY required for live trading")
        return errors
