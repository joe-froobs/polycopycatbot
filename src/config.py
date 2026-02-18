import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

# Maps DB setting keys to Config field names and types
_SETTING_MAP = {
    "api_url": ("api_url", str),
    "api_key": ("api_key", str),
    "private_key": ("private_key", str),
    "funder": ("funder", str),
    "rpc_url": ("rpc_url", str),
    "paper_trading": ("paper_trading", "bool"),
    "max_traders": ("max_traders", int),
    "poll_interval": ("poll_interval", int),
    "account_balance_usd": ("account_balance_usd", float),
    "trader_capital_estimate": ("trader_capital_estimate", float),
    "max_position_pct": ("max_position_pct", float),
    "daily_loss_limit_pct": ("daily_loss_limit_pct", float),
    "max_position_usd": ("max_position_usd", float),
    "max_concurrent_positions": ("max_concurrent_positions", int),
    "daily_loss_limit_usd": ("daily_loss_limit_usd", float),
    "capital_ratio": ("capital_ratio", float),
    "builder_api_key": ("builder_api_key", str),
    "builder_api_secret": ("builder_api_secret", str),
    "builder_api_passphrase": ("builder_api_passphrase", str),
}


@dataclass
class Config:
    # API
    api_url: str = os.getenv("PCC_API_URL", "https://polycopycat.com/api/traders")
    api_key: str = os.getenv("PCC_API_KEY", "")

    # Wallet
    private_key: str = os.getenv("PRIVATE_KEY", "")
    funder: str = os.getenv("FUNDER_ADDRESS", "")
    rpc_url: str = os.getenv("RPC_URL", "https://polygon-rpc.com")

    # Trading
    paper_trading: bool = os.getenv("PAPER_TRADING", "true").lower() == "true"
    max_traders: int = int(os.getenv("MAX_TRADERS", "5"))
    poll_interval: int = int(os.getenv("POLL_INTERVAL", "5"))

    # Capital & sizing (percentage-based when account_balance is set)
    account_balance_usd: float = float(os.getenv("ACCOUNT_BALANCE_USD", "0"))
    trader_capital_estimate: float = float(os.getenv("TRADER_CAPITAL_ESTIMATE", "100000"))
    max_position_pct: float = float(os.getenv("MAX_POSITION_PCT", "0.05"))
    daily_loss_limit_pct: float = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.10"))

    # Risk controls (fixed-dollar fallbacks when account_balance is 0)
    max_position_usd: float = float(os.getenv("MAX_POSITION_USD", "50"))
    max_concurrent_positions: int = int(os.getenv("MAX_CONCURRENT_POSITIONS", "10"))
    daily_loss_limit_usd: float = float(os.getenv("DAILY_LOSS_LIMIT_USD", "100"))
    capital_ratio: float = float(os.getenv("CAPITAL_RATIO", "10.0"))

    # Builder Relayer credentials (required for auto-claim)
    builder_api_key: str = os.getenv("BUILDER_API_KEY", "")
    builder_api_secret: str = os.getenv("BUILDER_API_SECRET", "")
    builder_api_passphrase: str = os.getenv("BUILDER_API_PASSPHRASE", "")

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
        if self.poll_interval < 1:
            errors.append("poll_interval must be >= 1")
        if self.max_position_usd <= 0:
            errors.append("max_position_usd must be > 0")
        if self.max_concurrent_positions < 1:
            errors.append("max_concurrent_positions must be >= 1")
        if self.daily_loss_limit_usd <= 0:
            errors.append("daily_loss_limit_usd must be > 0")
        if self.max_traders < 1 or self.max_traders > 20:
            errors.append("max_traders must be between 1 and 20")
        if self.capital_ratio < 1.0:
            errors.append("capital_ratio must be >= 1.0")
        if self.account_balance_usd < 0:
            errors.append("account_balance_usd must be >= 0")
        if self.trader_capital_estimate < 1000:
            errors.append("trader_capital_estimate must be >= 1000")
        if self.max_position_pct <= 0 or self.max_position_pct > 1.0:
            errors.append("max_position_pct must be between 0 and 1")
        if self.daily_loss_limit_pct <= 0 or self.daily_loss_limit_pct > 1.0:
            errors.append("daily_loss_limit_pct must be between 0 and 1")
        return errors

    @classmethod
    async def from_db(cls) -> "Config":
        """Load config from SQLite, falling back to .env / defaults."""
        from src.db import get_all_settings
        settings = await get_all_settings()

        config = cls()  # starts from .env / defaults

        for db_key, (field_name, typ) in _SETTING_MAP.items():
            if db_key in settings:
                raw = settings[db_key]
                if typ == "bool":
                    setattr(config, field_name, raw.lower() in ("true", "1", "yes"))
                elif typ is int:
                    try:
                        setattr(config, field_name, int(raw))
                    except (ValueError, TypeError):
                        pass  # keep default
                elif typ is float:
                    try:
                        setattr(config, field_name, float(raw))
                    except (ValueError, TypeError):
                        pass  # keep default
                else:
                    setattr(config, field_name, raw)

        return config

    async def save_to_db(self) -> None:
        """Persist current config to SQLite settings table."""
        from src.db import save_settings
        settings = {}
        for db_key, (field_name, typ) in _SETTING_MAP.items():
            val = getattr(self, field_name)
            if typ == "bool":
                settings[db_key] = "true" if val else "false"
            else:
                settings[db_key] = str(val)
        await save_settings(settings)
