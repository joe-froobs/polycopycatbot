from src.config import Config
from src.wallet_monitor import Position


class TradeExecutor:
    def __init__(self, config: Config):
        self.config = config
        self.open_positions: dict[str, float] = {}  # market_id -> size_usd
        self.daily_pnl: float = 0.0

    @property
    def total_exposure(self) -> float:
        return sum(self.open_positions.values())

    def calculate_size(self, trader_position: Position) -> float:
        """Calculate position size proportional to trader's size, capped by risk limits."""
        # Scale down: assume trader has ~10x our capital
        raw_size = trader_position.size / 10.0
        size = min(raw_size, self.config.max_position_usd)

        # Check concurrent position limit
        if len(self.open_positions) >= self.config.max_concurrent_positions:
            print(f"[Executor] Max concurrent positions ({self.config.max_concurrent_positions}) reached, skipping")
            return 0

        # Check daily loss limit
        if self.daily_pnl <= -self.config.daily_loss_limit_usd:
            print(f"[Executor] Daily loss limit (${self.config.daily_loss_limit_usd}) reached, skipping")
            return 0

        return round(size, 2)

    def open_position(self, position: Position):
        """Open a position (paper or live)."""
        size = self.calculate_size(position)
        if size <= 0:
            return

        if self.config.paper_trading:
            print(
                f"[PAPER] BUY ${size:.2f} on {position.outcome} "
                f"(market {position.market_id[:12]}.. copying {position.trader[:8]}..)"
            )
            self.open_positions[position.market_id] = size
        else:
            self._execute_live_buy(position, size)

    def close_position(self, position: Position):
        """Close a position (paper or live)."""
        if position.market_id not in self.open_positions:
            return

        size = self.open_positions.pop(position.market_id, 0)

        if self.config.paper_trading:
            print(
                f"[PAPER] SELL ${size:.2f} on {position.outcome} "
                f"(market {position.market_id[:12]}.. copying {position.trader[:8]}..)"
            )
        else:
            self._execute_live_sell(position, size)

    def adjust_position(self, position: Position):
        """Adjust an existing position."""
        new_size = self.calculate_size(position)
        old_size = self.open_positions.get(position.market_id, 0)

        if new_size <= 0:
            return

        if self.config.paper_trading:
            diff = new_size - old_size
            action = "INCREASE" if diff > 0 else "DECREASE"
            print(
                f"[PAPER] {action} ${abs(diff):.2f} on {position.outcome} "
                f"(market {position.market_id[:12]}.. now ${new_size:.2f})"
            )
            self.open_positions[position.market_id] = new_size
        else:
            self._execute_live_adjust(position, old_size, new_size)

    def _execute_live_buy(self, position: Position, size: float):
        """Execute a live buy via py-clob-client. Placeholder for MVP."""
        # TODO: Implement with py-clob-client
        # from py_clob_client.client import ClobClient
        # client = ClobClient(host, key=self.config.private_key, chain_id=137)
        print(f"[LIVE] Would BUY ${size:.2f} on {position.market_id[:12]}.. (not yet implemented)")
        self.open_positions[position.market_id] = size

    def _execute_live_sell(self, position: Position, size: float):
        """Execute a live sell. Placeholder for MVP."""
        print(f"[LIVE] Would SELL ${size:.2f} on {position.market_id[:12]}.. (not yet implemented)")

    def _execute_live_adjust(self, position: Position, old_size: float, new_size: float):
        """Adjust a live position. Placeholder for MVP."""
        print(f"[LIVE] Would ADJUST {position.market_id[:12]}.. from ${old_size:.2f} to ${new_size:.2f} (not yet implemented)")
        self.open_positions[position.market_id] = new_size

    def reset_daily_pnl(self):
        self.daily_pnl = 0.0
