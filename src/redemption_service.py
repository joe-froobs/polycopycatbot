"""Auto-claim service for resolved Polymarket positions via Builder Relayer API.

Uses the official py-builder-relayer-client to submit Gnosis Safe transactions
through the Polymarket Relayer for gasless redemption. Includes daily quota
tracking, on-chain resolution checking, and wallet discovery for orphaned positions.
"""

import asyncio
import re
import time
from datetime import datetime, timezone

from eth_abi import encode
from web3 import Web3

from src.config import Config

# Conditional imports — relayer client may not be installed
try:
    from py_builder_relayer_client.client import RelayClient
    from py_builder_relayer_client.models import SafeTransaction, OperationType
    from py_builder_signing_sdk.config import BuilderConfig as BuilderSigningConfig
    from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds

    class _FunderRelayClient(RelayClient):
        """RelayClient subclass that uses the funder address as the proxy wallet.

        The standard SDK derives the proxy wallet from the EOA via CREATE2,
        but Polymarket accounts use a funder address created through a different
        factory. This subclass overrides get_expected_safe() to return the actual
        funder address from config.
        """

        def __init__(self, *args, funder_address: str = "", **kwargs):
            super().__init__(*args, **kwargs)
            self._funder_address = funder_address

        def get_expected_safe(self):
            return self._funder_address

    RELAYER_AVAILABLE = True
except ImportError:
    RELAYER_AVAILABLE = False

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

# Polymarket contract addresses (Polygon)
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
PARENT_COLLECTION_ID = bytes(32)  # 0x0...0 for root collection

# Builder Relayer API
RELAYER_URL = "https://relayer-v2.polymarket.com"
REDEEM_SELECTOR = bytes.fromhex("01b7037c")  # redeemPositions selector
POLYGON_CHAIN_ID = 137

# Quota management — relayer allows ~100 tx/day, leave buffer
DAILY_TX_LIMIT = 80
MIN_REDEEM_INTERVAL = 30.0  # seconds between redemptions

# Discovery sweep limits
DISCOVERY_MAX_PER_SWEEP = 5
RPC_DELAY = 1.5  # seconds between on-chain checks


class RedemptionService:
    """Handles auto-claiming of resolved conditional tokens via Builder Relayer."""

    def __init__(self, config: Config):
        self.config = config
        self._relay_client = None
        self._w3 = None

        # Quota tracking
        self._daily_tx_count: int = 0
        self._daily_tx_date: str = ""
        self._quota_reset_at: float = 0.0
        self._last_redeem_time: float = 0.0

        # Already-redeemed condition IDs (avoid retrying in same session)
        self._redeemed_conditions: set[str] = set()

    @property
    def is_configured(self) -> bool:
        """Check if builder credentials are set for auto-claim."""
        return (
            RELAYER_AVAILABLE
            and bool(self.config.builder_api_key)
            and bool(self.config.builder_api_secret)
            and bool(self.config.builder_api_passphrase)
            and bool(self.config.private_key)
            and bool(self.config.funder)
        )

    def _get_relay_client(self):
        if self._relay_client is None:
            creds = BuilderApiKeyCreds(
                key=self.config.builder_api_key,
                secret=self.config.builder_api_secret,
                passphrase=self.config.builder_api_passphrase,
            )
            builder_config = BuilderSigningConfig(local_builder_creds=creds)
            self._relay_client = _FunderRelayClient(
                relayer_url=RELAYER_URL,
                chain_id=POLYGON_CHAIN_ID,
                private_key=self.config.private_key,
                builder_config=builder_config,
                funder_address=self.config.funder,
            )
        return self._relay_client

    def _get_web3(self):
        if self._w3 is None:
            self._w3 = Web3(Web3.HTTPProvider(self.config.rpc_url))
        return self._w3

    # ------------------------------------------------------------------
    # Quota management
    # ------------------------------------------------------------------

    def _check_quota(self) -> tuple[bool, str]:
        now = time.monotonic()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if today != self._daily_tx_date:
            self._daily_tx_count = 0
            self._daily_tx_date = today
            self._quota_reset_at = 0.0

        if self._quota_reset_at > 0 and now < self._quota_reset_at:
            remaining = round(self._quota_reset_at - now)
            return False, f"Quota exhausted, resets in {remaining}s"

        if self._daily_tx_count >= DAILY_TX_LIMIT:
            return False, f"Daily limit ({self._daily_tx_count}/{DAILY_TX_LIMIT})"

        elapsed = now - self._last_redeem_time
        if elapsed < MIN_REDEEM_INTERVAL:
            wait = round(MIN_REDEEM_INTERVAL - elapsed)
            return False, f"Rate limit: wait {wait}s"

        return True, "OK"

    def _record_tx(self):
        self._daily_tx_count += 1
        self._last_redeem_time = time.monotonic()

    def _handle_429(self, error_msg: str):
        match = re.search(r"resets in (\d+) seconds", error_msg)
        if match:
            self._quota_reset_at = time.monotonic() + int(match.group(1))
            print(f"[AutoClaim] Quota exhausted, resets in {match.group(1)}s")
        else:
            self._quota_reset_at = time.monotonic() + 3600
            print("[AutoClaim] Rate limited, cooling down for 1 hour")

    # ------------------------------------------------------------------
    # Calldata encoding
    # ------------------------------------------------------------------

    def _encode_redeem_calldata(self, condition_id: str) -> str:
        cid_bytes = bytes.fromhex(condition_id.removeprefix("0x"))
        encoded = encode(
            ["address", "bytes32", "bytes32", "uint256[]"],
            [USDC_ADDRESS, PARENT_COLLECTION_ID, cid_bytes, [1, 2]],
        )
        return "0x" + (REDEEM_SELECTOR + encoded).hex()

    # ------------------------------------------------------------------
    # On-chain resolution check (read-only, no gas needed)
    # ------------------------------------------------------------------

    async def check_resolved(self, condition_id: str) -> list[int] | None:
        """Check if a condition has resolved on-chain.

        Returns list of payout numerators if resolved, None if unresolved.
        """
        try:
            w3 = self._get_web3()
            cid_bytes = bytes.fromhex(condition_id.removeprefix("0x"))
            ctf = Web3.to_checksum_address(CTF_ADDRESS)

            # Check payoutDenominator
            selector = w3.keccak(text="payoutDenominator(bytes32)")[:4]
            call_data = selector + encode(["bytes32"], [cid_bytes])
            result = await asyncio.to_thread(
                w3.eth.call, {"to": ctf, "data": "0x" + call_data.hex()}
            )
            denom = int.from_bytes(result, "big")

            if denom == 0:
                return None

            # Get payout numerators for each outcome
            numerators = []
            num_selector = w3.keccak(text="payoutNumerators(bytes32,uint256)")[:4]
            for i in range(2):
                call_data = num_selector + encode(["bytes32", "uint256"], [cid_bytes, i])
                result = await asyncio.to_thread(
                    w3.eth.call, {"to": ctf, "data": "0x" + call_data.hex()}
                )
                numerators.append(int.from_bytes(result, "big"))

            return numerators

        except Exception as e:
            print(f"[AutoClaim] Resolution check failed for {condition_id[:16]}...: {e}")
            return None

    # ------------------------------------------------------------------
    # Redemption
    # ------------------------------------------------------------------

    async def batch_redeem(self, condition_ids: list[str]) -> dict:
        """Batch-redeem multiple resolved conditions in a single relayer transaction.

        Uses Gnosis Safe multiSend to combine all redemptions into one tx,
        consuming only 1 daily quota slot regardless of how many conditions.
        """
        if not self.is_configured:
            return {"success": False, "error": "Builder credentials not configured"}

        # Filter out already-redeemed
        to_redeem = [
            cid for cid in condition_ids
            if cid not in self._redeemed_conditions
        ]
        if not to_redeem:
            return {"success": True, "redeemed": [], "note": "All already redeemed"}

        allowed, reason = self._check_quota()
        if not allowed:
            return {"success": False, "error": f"Quota: {reason}"}

        try:
            client = self._get_relay_client()

            # Build one SafeTransaction per condition, all in one batch
            safe_txns = []
            for cid in to_redeem:
                calldata = self._encode_redeem_calldata(cid)
                safe_txns.append(SafeTransaction(
                    to=CTF_ADDRESS,
                    operation=OperationType.Call,
                    data=calldata,
                    value="0",
                ))

            print(f"[AutoClaim] Submitting batch of {len(safe_txns)} redemptions...")

            result = await asyncio.to_thread(
                client.execute, safe_txns,
                f"Batch redeem {len(safe_txns)} positions",
            )

            # Only 1 quota slot for the entire batch
            self._record_tx()
            for cid in to_redeem:
                self._redeemed_conditions.add(cid)

            tx_id = result.transaction_id
            tx_hash = result.transaction_hash

            print(f"[AutoClaim] Batch submitted: {len(to_redeem)} conditions, tx={tx_hash}")

            # Poll for confirmation
            final = await asyncio.to_thread(
                client.poll_until_state,
                tx_id,
                ["STATE_CONFIRMED", "STATE_MINED"],
                "STATE_FAILED",
                10,    # max_polls
                3000,  # poll_frequency_ms
            )

            if final and final.get("state") in ("STATE_CONFIRMED", "STATE_MINED"):
                confirmed_hash = final.get("transactionHash", tx_hash)
                print(f"[AutoClaim] Batch confirmed: hash={confirmed_hash}")
                return {"success": True, "tx_hash": confirmed_hash, "redeemed": to_redeem}

            if final and final.get("state") == "STATE_FAILED":
                return {"success": False, "error": "Batch transaction failed on-chain"}

            # Submitted but couldn't confirm — count as success
            return {"success": True, "tx_hash": tx_hash, "redeemed": to_redeem}

        except Exception as e:
            error_msg = str(e)
            print(f"[AutoClaim] Batch error: {error_msg}")
            if "429" in error_msg or "rate" in error_msg.lower():
                self._handle_429(error_msg)
            return {"success": False, "error": error_msg}

    # ------------------------------------------------------------------
    # Wallet discovery sweep: find and redeem orphaned positions
    # ------------------------------------------------------------------

    async def discover_and_redeem_orphans(
        self, known_condition_ids: set[str]
    ) -> list[str]:
        """Scan the funder wallet for positions not tracked in the DB.

        Queries the Polymarket data API, checks on-chain resolution, and
        redeems any resolved orphans (up to limit per sweep for quota safety).
        """
        if not HTTPX_AVAILABLE or not self.is_configured or not self.config.funder:
            return []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://data-api.polymarket.com/positions",
                    params={
                        "user": self.config.funder,
                        "sizeThreshold": "0.1",
                        "limit": "200",
                    },
                )
                resp.raise_for_status()
                positions = resp.json()
        except Exception as e:
            print(f"[AutoClaim] Discovery fetch failed: {e}")
            return []

        # Find orphan condition IDs
        orphan_cids = []
        for p in positions:
            cid = p.get("conditionId", "")
            size = float(p.get("size", 0))
            if (
                cid
                and size > 0.5
                and cid not in known_condition_ids
                and cid not in self._redeemed_conditions
            ):
                orphan_cids.append(cid)

        if not orphan_cids:
            return []

        # Deduplicate and cap how many we check per sweep
        orphan_cids = list(dict.fromkeys(orphan_cids))[:DISCOVERY_MAX_PER_SWEEP]
        print(f"[AutoClaim] Found {len(orphan_cids)} orphan positions to check")

        # Check which orphans are resolved on-chain
        resolved_orphans = []
        for cid in orphan_cids:
            numerators = await self.check_resolved(cid)
            if numerators is not None:
                resolved_orphans.append(cid)
            await asyncio.sleep(RPC_DELAY)

        if not resolved_orphans:
            return []

        # Batch-redeem all resolved orphans in one tx
        result = await self.batch_redeem(resolved_orphans)
        redeemed = result.get("redeemed", []) if result.get("success") else []

        if redeemed:
            print(f"[AutoClaim] Orphan sweep: batch redeemed {len(redeemed)} in 1 tx")

        return redeemed
