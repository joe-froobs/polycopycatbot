import asyncio
from datetime import datetime

from src.config import Config
from src.api_client import ApiClient
from src.wallet_monitor import WalletMonitor
from src.trade_executor import TradeExecutor
from src.redemption_service import RedemptionService
from src import db

# How often to run the claim sweep (in poll cycles)
CLAIM_SWEEP_INTERVAL = 360  # ~30 min at 5s poll interval


class BotRunner:
    def __init__(self):
        self.config: Config | None = None
        self.api: ApiClient | None = None
        self.monitor: WalletMonitor | None = None
        self.executor: TradeExecutor | None = None
        self.redeemer: RedemptionService | None = None
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
        self.redeemer = RedemptionService(self.config)

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

        refresh_interval = 720  # ~hourly at 5s poll interval

        while self._running:
            try:
                await asyncio.sleep(self.config.poll_interval)
                self.poll_count += 1

                # Periodic trader refresh from API
                if (self.poll_count % refresh_interval == 0
                        and self.config.api_key and self.api):
                    try:
                        fetched = await asyncio.to_thread(self.api.get_trader_addresses)
                        if fetched:
                            self.addresses = fetched
                            for addr in fetched:
                                await db.add_trader(addr, source="api")
                    except Exception as e:
                        await db.log_activity(
                            event_type="error",
                            details=f"Trader refresh failed: {e}",
                        )

                new, closed, adjusted = await asyncio.to_thread(
                    self.monitor.detect_changes, self.addresses
                )

                for pos in new:
                    self.executor.open_position(pos)
                    pos_data = self.executor.open_positions.get(pos.market_id, {})
                    size_usd = pos_data.get("size", 0) if isinstance(pos_data, dict) else 0
                    # Resolve condition_id for auto-claim (from API response or Gamma lookup)
                    cid = pos.condition_id
                    if not cid:
                        info = self.monitor.resolve_market(pos.market_id)
                        if info:
                            cid = info.get("condition_id", "")
                    await db.log_activity(
                        event_type="trade_open",
                        market_id=pos.market_id,
                        trader=pos.trader,
                        outcome=pos.outcome,
                        size_usd=size_usd,
                        price=pos.price,
                        mode=self.mode,
                    )
                    await db.upsert_position(
                        market_id=pos.market_id,
                        token_id=pos.token_id,
                        condition_id=cid,
                        outcome=pos.outcome,
                        size_usd=size_usd,
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
                    pos_data = self.executor.open_positions.get(pos.market_id, {})
                    size_usd = pos_data.get("size", 0) if isinstance(pos_data, dict) else 0
                    cid = pos.condition_id
                    if not cid:
                        info = self.monitor.resolve_market(pos.market_id)
                        if info:
                            cid = info.get("condition_id", "")
                    await db.log_activity(
                        event_type="trade_adjust",
                        market_id=pos.market_id,
                        trader=pos.trader,
                        outcome=pos.outcome,
                        size_usd=size_usd,
                        price=pos.price,
                        mode=self.mode,
                    )
                    await db.upsert_position(
                        market_id=pos.market_id,
                        token_id=pos.token_id,
                        condition_id=cid,
                        outcome=pos.outcome,
                        size_usd=size_usd,
                        entry_price=pos.price,
                        trader=pos.trader,
                        mode=self.mode,
                    )

                # --- Auto-claim sweep every ~30 min ---
                if (
                    self.redeemer
                    and self.redeemer.is_configured
                    and self.poll_count % CLAIM_SWEEP_INTERVAL == 0
                    and self.poll_count > 0
                ):
                    await self._claim_sweep()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.last_error = str(e)
                await db.log_activity(event_type="error", details=str(e))
                await asyncio.sleep(5)

    async def _claim_sweep(self):
        """Single sweep: check all positions + orphans for resolution, batch-redeem.

        Runs every ~30 min. Collects unique condition_ids, checks each on-chain,
        then submits all resolved conditions in one batched relayer transaction.
        """
        try:
            positions = await db.get_positions()

            # Deduplicate: multiple positions may share a condition_id
            cid_to_positions: dict[str, list[dict]] = {}
            for pos in positions:
                cid = pos.get("condition_id", "")
                if cid and cid not in self.redeemer._redeemed_conditions:
                    cid_to_positions.setdefault(cid, []).append(pos)

            # Check each unique condition_id on-chain
            resolved_cids: list[str] = []
            checked = 0
            for cid in cid_to_positions:
                numerators = await self.redeemer.check_resolved(cid)
                checked += 1
                if numerators is not None:
                    resolved_cids.append(cid)
                await asyncio.sleep(2.0)  # gentle on the RPC

            if resolved_cids:
                print(f"[AutoClaim] {len(resolved_cids)} resolved out of {checked} checked")

            # Batch-redeem all resolved conditions in one relayer tx
            if resolved_cids:
                result = await self.redeemer.batch_redeem(resolved_cids)
                if result.get("success"):
                    tx_hash = result.get("tx_hash", "")
                    for cid in result.get("redeemed", resolved_cids):
                        for pos in cid_to_positions.get(cid, []):
                            await db.log_activity(
                                event_type="auto_claim",
                                market_id=pos["market_id"],
                                outcome=pos.get("outcome", ""),
                                size_usd=pos.get("size_usd", 0),
                                mode=self.mode,
                                details=f"Batch claimed tx={tx_hash}",
                            )
                            await db.remove_position(pos["market_id"])
                            self.executor.open_positions.pop(pos["market_id"], None)
                    print(
                        f"[AutoClaim] Batch redeemed {len(result.get('redeemed', resolved_cids))} "
                        f"conditions in 1 tx"
                    )

            # Discovery: check for orphaned wallet positions not in DB
            known_cids = set(cid_to_positions.keys()) | self.redeemer._redeemed_conditions
            orphan_redeemed = await self.redeemer.discover_and_redeem_orphans(known_cids)
            for cid in orphan_redeemed:
                await db.log_activity(
                    event_type="auto_claim",
                    details=f"Orphan claimed: {cid[:16]}...",
                    mode=self.mode,
                )

        except Exception as e:
            print(f"[AutoClaim] Sweep error: {e}")

    async def get_stats(self) -> dict:
        positions = await db.get_positions()
        total_exposure = sum(p["size_usd"] for p in positions)
        auto_claim = "off"
        if self.redeemer and self.redeemer.is_configured:
            auto_claim = "on"
        return {
            "status": self.status,
            "mode": self.mode,
            "open_count": len(positions),
            "exposure": round(total_exposure, 2),
            "daily_pnl": round(self.executor.daily_pnl, 2) if self.executor else 0,
            "traders_monitored": len(self.addresses),
            "poll_count": self.poll_count,
            "last_error": self.last_error,
            "auto_claim": auto_claim,
        }
