import time

import httpx
from src.config import Config


class ApiClient:
    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.Client(timeout=30)

    def fetch_traders(self) -> list[dict]:
        """Fetch ranked traders from the Poly Copy Cat API."""
        if not self.config.api_key:
            return []

        max_retries = 3
        backoff = 2  # seconds

        for attempt in range(max_retries):
            resp = self.client.get(
                self.config.api_url,
                headers={"Authorization": f"Bearer {self.config.api_key}"},
            )

            if resp.status_code == 401:
                print("[API] Invalid API key. Check PCC_API_KEY in .env")
                return []

            if resp.status_code == 429 or resp.status_code >= 500:
                wait = backoff * (2 ** attempt)
                print(f"[API] Status {resp.status_code}, retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue

            if resp.status_code != 200:
                print(f"[API] Unexpected status {resp.status_code}")
                return []

            traders = resp.json()
            if not isinstance(traders, list):
                print("[API] Unexpected response format")
                return []

            return traders[: self.config.max_traders]

        print("[API] All retries exhausted")
        return []

    def get_trader_addresses(self) -> list[str]:
        """Get trader addresses from API or manual config."""
        if self.config.manual_traders:
            print(f"[API] Using {len(self.config.manual_traders)} manual trader addresses")
            return self.config.manual_traders[: self.config.max_traders]

        traders = self.fetch_traders()
        if not traders:
            return []

        addresses = [t["address"] for t in traders if t.get("address")]
        print(f"[API] Fetched {len(addresses)} trader addresses from leaderboard")
        return addresses

    def close(self):
        self.client.close()
