import time
from datetime import date
from typing import Callable

from src.config import Config
from src.wallet_monitor import Position


class TradeExecutor:
    def __init__(self, config: Config, on_activity: Callable | None = None):
        self.config = config
        self.open_positions: dict[str, dict] = {}  # market_id -> {"size": float, "entry_price": float}
        self.daily_pnl: float = 0.0
        self._last_reset_date: date = date.today()
        self._clob_client = None
        self._on_activity = on_activity

    def _get_clob_client(self):
        """Lazy-initialize py-clob-client for live trading."""
        if self._clob_client is not None:
            return self._clob_client

        from py_clob_client.client import ClobClient

        self._clob_client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=137,
            key=self.config.private_key,
            signature_type=1,  # Poly proxy wallet
            funder=self.config.funder,
        )
        self._clob_client.set_api_creds(self._clob_client.derive_api_key())
        print("[Executor] CLOB client initialized")
        return self._clob_client

    @property
    def total_exposure(self) -> float:
        return sum(p["size"] for p in self.open_positions.values())

    def calculate_size(self, trader_position: Position) -> float:
        """Calculate position size proportional to trader's size, capped by risk limits."""
        # Auto-reset daily P&L at start of new day
        today = date.today()
        if today != self._last_reset_date:
            self.reset_daily_pnl()
            self._last_reset_date = today

        # Scale down by capital ratio
        raw_size = trader_position.size / self.config.capital_ratio

        # Dynamic max: percentage of account balance if set, else static cap
        if self.config.account_balance_usd > 0:
            max_size = self.config.account_balance_usd * self.config.max_position_pct
        else:
            max_size = self.config.max_position_usd
        size = min(raw_size, max_size)

        # Enforce minimum $1 position
        if size < 1.0:
            return 0

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
                f"@ {position.price:.3f} "
                f"(market {position.market_id[:12]}.. copying {position.trader[:8]}..)"
            )
            self.open_positions[position.market_id] = {"size": size, "entry_price": position.price}
        else:
            self._execute_live_buy(position, size)

    def close_position(self, position: Position):
        """Close a position (paper or live)."""
        if position.market_id not in self.open_positions:
            return

        pos_data = self.open_positions.pop(position.market_id, {})
        size = pos_data.get("size", 0)
        entry_price = pos_data.get("entry_price", 0)

        # Calculate P&L
        if entry_price > 0:
            pnl = size * (position.price / entry_price - 1)
            self.daily_pnl += pnl

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
        pos_data = self.open_positions.get(position.market_id, {})
        old_size = pos_data.get("size", 0)

        if new_size <= 0:
            return

        if self.config.paper_trading:
            diff = new_size - old_size
            action = "INCREASE" if diff > 0 else "DECREASE"
            print(
                f"[PAPER] {action} ${abs(diff):.2f} on {position.outcome} "
                f"(market {position.market_id[:12]}.. now ${new_size:.2f})"
            )
            self.open_positions[position.market_id] = {"size": new_size, "entry_price": position.price}
        else:
            self._execute_live_adjust(position, old_size, new_size)

    def _execute_live_buy(self, position: Position, size: float):
        """Execute a live buy via py-clob-client."""
        try:
            from py_clob_client.clob_types import OrderArgs

            client = self._get_clob_client()
            token_id = position.token_id
            if not token_id:
                print(f"[LIVE] No token_id for {position.market_id[:12]}.. skipping")
                return

            # Clamp price to Polymarket limits
            price = max(0.01, min(0.99, position.price))

            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side="BUY",
            )

            signed_order = client.create_order(order_args)
            response = client.post_order(signed_order)

            status = (response.get("status") or "").lower()
            order_id = response.get("orderID", "?")

            if status in ("filled", "matched", "live"):
                print(f"[LIVE] BUY ${size:.2f} on {position.outcome} -- order {order_id} {status}")
                self.open_positions[position.market_id] = {"size": size, "entry_price": position.price}
            else:
                print(f"[LIVE] BUY order {order_id} status: {status}")

        except Exception as e:
            print(f"[LIVE] BUY failed for {position.market_id[:12]}..: {e}")

    def _execute_live_sell(self, position: Position, size: float):
        """Execute a live sell via py-clob-client."""
        try:
            from py_clob_client.clob_types import OrderArgs

            client = self._get_clob_client()
            token_id = position.token_id
            if not token_id:
                print(f"[LIVE] No token_id for {position.market_id[:12]}.. skipping")
                return

            price = max(0.01, min(0.99, position.price))

            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side="SELL",
            )

            signed_order = client.create_order(order_args)
            response = client.post_order(signed_order)

            status = (response.get("status") or "").lower()
            order_id = response.get("orderID", "?")
            print(f"[LIVE] SELL ${size:.2f} on {position.outcome} -- order {order_id} {status}")

        except Exception as e:
            print(f"[LIVE] SELL failed for {position.market_id[:12]}..: {e}")

    def _execute_live_adjust(self, position: Position, old_size: float, new_size: float):
        """Adjust a live position by placing a delta order."""
        diff = new_size - old_size
        if abs(diff) < 1.0:
            return

        adjusted = Position(
            market_id=position.market_id,
            token_id=position.token_id,
            outcome=position.outcome,
            size=abs(diff),
            price=position.price,
            trader=position.trader,
        )

        if diff > 0:
            self._execute_live_buy(adjusted, abs(diff))
        else:
            self._execute_live_sell(adjusted, abs(diff))

        self.open_positions[position.market_id] = {"size": new_size, "entry_price": position.price}

    def reset_daily_pnl(self):
        self.daily_pnl = 0.0
