import time
import httpx


DATA_API_BASE = "https://data-api.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"


class Position:
    def __init__(
        self,
        market_id: str,
        token_id: str,
        outcome: str,
        size: float,
        price: float,
        trader: str,
    ):
        self.market_id = market_id
        self.token_id = token_id
        self.outcome = outcome
        self.size = size
        self.price = price
        self.trader = trader

    def __repr__(self):
        return (
            f"Position({self.trader[:8]}.. {self.outcome} "
            f"${self.size:.2f} @ {self.price:.3f} on {self.market_id[:12]}..)"
        )


class WalletMonitor:
    def __init__(self):
        self.client = httpx.Client(timeout=30)
        # trader_address -> {market_id -> Position}
        self.known_positions: dict[str, dict[str, Position]] = {}
        # Cache market_id -> {token_id, condition_id} from Gamma API
        self._market_cache: dict[str, dict] = {}

    def fetch_positions(self, address: str) -> dict[str, Position]:
        """Fetch current positions for a trader wallet from Polymarket Data API."""
        try:
            resp = self.client.get(
                f"{DATA_API_BASE}/positions",
                params={"user": address},
            )
            if resp.status_code != 200:
                return {}

            data = resp.json()
            if not isinstance(data, list):
                return {}

            positions = {}
            for p in data:
                size = float(p.get("size", 0) or p.get("amount", 0) or 0)
                if size <= 0:
                    continue

                market_id = p.get("market") or p.get("conditionId") or p.get("market_id", "")
                if not market_id:
                    continue

                outcome = p.get("outcome", "")
                price = float(p.get("avgPrice", 0) or p.get("entry_price", 0) or 0)
                token_id = p.get("asset", "") or p.get("tokenId", "")

                positions[market_id] = Position(
                    market_id=market_id,
                    token_id=token_id,
                    outcome=outcome,
                    size=size,
                    price=price,
                    trader=address,
                )

            return positions
        except Exception as e:
            print(f"[Monitor] Error fetching positions for {address[:8]}...: {e}")
            return {}

    def resolve_market(self, market_id: str) -> dict | None:
        """Look up market details from Gamma API for token_id resolution."""
        if market_id in self._market_cache:
            return self._market_cache[market_id]

        try:
            resp = self.client.get(
                f"{GAMMA_API_BASE}/markets",
                params={"id": market_id},
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            if isinstance(data, list) and data:
                market = data[0]
            elif isinstance(data, dict):
                market = data
            else:
                return None

            info = {
                "condition_id": market.get("conditionId", market_id),
                "question": market.get("question", ""),
                "tokens": market.get("clobTokenIds", []),
                "outcomes": market.get("outcomes", []),
            }
            self._market_cache[market_id] = info
            return info
        except Exception as e:
            print(f"[Monitor] Error resolving market {market_id[:12]}...: {e}")
            return None

    def detect_changes(
        self, addresses: list[str]
    ) -> tuple[list[Position], list[Position], list[Position]]:
        """
        Poll all trader wallets and detect changes.
        Returns (new_positions, closed_positions, adjusted_positions).
        """
        new_positions = []
        closed_positions = []
        adjusted_positions = []

        for addr in addresses:
            current = self.fetch_positions(addr)
            previous = self.known_positions.get(addr, {})

            # New positions
            for mid, pos in current.items():
                if mid not in previous:
                    new_positions.append(pos)
                elif abs(pos.size - previous[mid].size) > 0.01:
                    adjusted_positions.append(pos)

            # Closed positions
            for mid, pos in previous.items():
                if mid not in current:
                    closed_positions.append(pos)

            self.known_positions[addr] = current

            # Small delay between wallets to avoid hammering the API
            time.sleep(0.2)

        return new_positions, closed_positions, adjusted_positions

    def close(self):
        self.client.close()
