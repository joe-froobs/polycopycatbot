import asyncio
from datetime import datetime

from src.config import Config
from src.api_client import ApiClient
from src.wallet_monitor import WalletMonitor
from src.trade_executor import TradeExecutor
from src import db


class BotRunner:
    def __init__(self):
        self.config: Config | None = None
        self.api: ApiClient | None = None
        self.monitor: WalletMonitor | None = None
        self.executor: TradeExecutor | None = None
        self.addresses: list[str] = []
        self._task: asyncio.Task | None = None
        self._running = False
        self.started_at: datetime | None = None
        self.last_error: str = ""
        self.poll_count: int = 0

    @property
    def status(self) -> str:
        if self._running and self._task and not self._task.done():
            return "running"
        return "stopped"

    @property
    def mode(self) -> str:
        if self.config:
            return "paper" if self.config.paper_trading else "live"
        return "paper"

    async def start(self) -> str:
        if self.status == "running":
            return "already running"

        self.config = await Config.from_db()

        # Load active traders from DB
        traders = await db.get_traders(active_only=True)
        self.addresses = [t["address"] for t in traders]

        if not self.addresses and not self.config.api_key:
            return "No traders configured. Add trader addresses or an API key first."

        self.api = ApiClient(self.config)
        self.monitor = WalletMonitor()
        self.executor = TradeExecutor(self.config)

        # If we have an API key but no manual traders in DB, fetch from API
        if not self.addresses and self.config.api_key:
            try:
                fetched = await asyncio.to_thread(self.api.get_trader_addresses)
                self.addresses = fetched
                for addr in fetched:
                    await db.add_trader(addr, source="api")
            except Exception as e:
                return f"Failed to fetch traders from API: {e}"

        if not self.addresses:
            return "No trader addresses found."

        self._running = True
        self.started_at = datetime.now()
        self.last_error = ""
        self.poll_count = 0

        await db.log_activity(
            event_type="bot_start",
            mode=self.mode,
            details=f"Monitoring {len(self.addresses)} traders",
        )

        self._task = asyncio.create_task(self._run_loop())
        return "started"

    async def stop(self) -> str:
        if self.status != "running":
            return "not running"

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        await db.log_activity(event_type="bot_stop", mode=self.mode)

        if self.api:
            self.api.close()
        if self.monitor:
            self.monitor.close()

        self.started_at = None
        return "stopped"

    async def _run_loop(self):
        # Initial baseline scan
        try:
            await asyncio.to_thread(self.monitor.detect_changes, self.addresses)
        except Exception as e:
            self.last_error = str(e)
            await db.log_activity(event_type="error", details=f"Baseline scan failed: {e}")

        while self._running:
            try:
                await asyncio.sleep(self.config.poll_interval)
                self.poll_count += 1

                new, closed, adjusted = await asyncio.to_thread(
                    self.monitor.detect_changes, self.addresses
                )

                for pos in new:
                    self.executor.open_position(pos)
                    await db.log_activity(
                        event_type="trade_open",
                        market_id=pos.market_id,
                        trader=pos.trader,
                        outcome=pos.outcome,
                        size_usd=self.executor.open_positions.get(pos.market_id, 0),
                        price=pos.price,
                        mode=self.mode,
                    )
                    await db.upsert_position(
                        market_id=pos.market_id,
                        token_id=pos.token_id,
                        outcome=pos.outcome,
                        size_usd=self.executor.open_positions.get(pos.market_id, 0),
                        entry_price=pos.price,
                        trader=pos.trader,
                        mode=self.mode,
                    )

                for pos in closed:
                    self.executor.close_position(pos)
                    await db.log_activity(
                        event_type="trade_close",
                        market_id=pos.market_id,
                        trader=pos.trader,
                        outcome=pos.outcome,
                        mode=self.mode,
                    )
                    await db.remove_position(pos.market_id)

                for pos in adjusted:
                    self.executor.adjust_position(pos)
                    await db.log_activity(
                        event_type="trade_adjust",
                        market_id=pos.market_id,
                        trader=pos.trader,
                        outcome=pos.outcome,
                        size_usd=self.executor.open_positions.get(pos.market_id, 0),
                        price=pos.price,
                        mode=self.mode,
                    )
                    await db.upsert_position(
                        market_id=pos.market_id,
                        token_id=pos.token_id,
                        outcome=pos.outcome,
                        size_usd=self.executor.open_positions.get(pos.market_id, 0),
                        entry_price=pos.price,
                        trader=pos.trader,
                        mode=self.mode,
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.last_error = str(e)
                await db.log_activity(event_type="error", details=str(e))
                await asyncio.sleep(5)

    async def get_stats(self) -> dict:
        positions = await db.get_positions()
        total_exposure = sum(p["size_usd"] for p in positions)
        return {
            "status": self.status,
            "mode": self.mode,
            "open_count": len(positions),
            "exposure": round(total_exposure, 2),
            "daily_pnl": round(self.executor.daily_pnl, 2) if self.executor else 0,
            "traders_monitored": len(self.addresses),
            "poll_count": self.poll_count,
            "last_error": self.last_error,
        }
