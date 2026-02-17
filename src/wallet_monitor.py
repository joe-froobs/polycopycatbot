import time
import httpx


POLYMARKET_API = "https://data-api.polymarket.com"


class Position:
    def __init__(self, market_id: str, outcome: str, size: float, trader: str):
        self.market_id = market_id
        self.outcome = outcome
        self.size = size
        self.trader = trader

    def __repr__(self):
        return f"Position({self.trader[:8]}.. {self.outcome} ${self.size:.2f} on {self.market_id[:12]}..)"


class WalletMonitor:
    def __init__(self):
        self.client = httpx.Client(timeout=30)
        # trader_address -> {market_id -> Position}
        self.known_positions: dict[str, dict[str, Position]] = {}

    def fetch_positions(self, address: str) -> dict[str, Position]:
        """Fetch current positions for a trader wallet."""
        try:
            resp = self.client.get(
                f"{POLYMARKET_API}/v1/positions",
                params={"user": address},
            )
            if resp.status_code != 200:
                return {}

            data = resp.json()
            if not isinstance(data, list):
                return {}

            positions = {}
            for p in data:
                size = float(p.get("size", 0))
                if size <= 0:
                    continue
                market_id = p.get("market", "")
                outcome = p.get("outcome", "")
                positions[market_id] = Position(market_id, outcome, size, address)

            return positions
        except Exception as e:
            print(f"[Monitor] Error fetching positions for {address[:8]}...: {e}")
            return {}

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
