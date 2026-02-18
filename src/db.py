import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "polycopycat.db"

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS traders (
    address  TEXT PRIMARY KEY,
    label    TEXT DEFAULT '',
    source   TEXT DEFAULT 'manual',
    active   INTEGER DEFAULT 1,
    added_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS activity_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT DEFAULT (datetime('now')),
    event_type TEXT NOT NULL,
    market_id  TEXT DEFAULT '',
    trader     TEXT DEFAULT '',
    outcome    TEXT DEFAULT '',
    size_usd   REAL DEFAULT 0,
    price      REAL DEFAULT 0,
    mode       TEXT DEFAULT 'paper',
    details    TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS positions (
    market_id    TEXT PRIMARY KEY,
    token_id     TEXT DEFAULT '',
    condition_id TEXT DEFAULT '',
    outcome      TEXT DEFAULT '',
    size_usd     REAL DEFAULT 0,
    entry_price  REAL DEFAULT 0,
    trader       TEXT DEFAULT '',
    opened_at    TEXT DEFAULT (datetime('now')),
    mode         TEXT DEFAULT 'paper'
);

CREATE TABLE IF NOT EXISTS onboarding (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    tos_accepted    INTEGER DEFAULT 0,
    tos_accepted_at TEXT,
    setup_complete  INTEGER DEFAULT 0,
    completed_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_activity_log_timestamp ON activity_log(id DESC);
CREATE INDEX IF NOT EXISTS idx_positions_opened_at ON positions(opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_traders_active ON traders(active);
"""


async def init_db(path: Path | None = None) -> None:
    db_path = path or DB_PATH
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA)
        # Ensure onboarding row exists
        await db.execute(
            "INSERT OR IGNORE INTO onboarding (id) VALUES (1)"
        )
        # Migration: add condition_id column if upgrading from older schema
        try:
            await db.execute(
                "ALTER TABLE positions ADD COLUMN condition_id TEXT DEFAULT ''"
            )
        except Exception:
            pass  # column already exists
        await db.commit()


async def get_db(path: Path | None = None) -> aiosqlite.Connection:
    db_path = path or DB_PATH
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    return db


# --- Settings ---

async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else default


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


async def get_all_settings() -> dict[str, str]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}


async def save_settings(settings: dict[str, str]) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        for key, value in settings.items():
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        await db.commit()


# --- Onboarding ---

async def get_onboarding() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM onboarding WHERE id = 1")
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return {"id": 1, "tos_accepted": 0, "tos_accepted_at": None,
                "setup_complete": 0, "completed_at": None}


async def set_tos_accepted() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE onboarding SET tos_accepted = 1, "
            "tos_accepted_at = datetime('now') WHERE id = 1"
        )
        await db.commit()


async def set_setup_complete() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE onboarding SET setup_complete = 1, "
            "completed_at = datetime('now') WHERE id = 1"
        )
        await db.commit()


# --- Traders ---

async def get_traders(active_only: bool = False) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM traders"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY added_at DESC"
        cursor = await db.execute(query)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def add_trader(address: str, label: str = "", source: str = "manual") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO traders (address, label, source) VALUES (?, ?, ?) "
            "ON CONFLICT(address) DO UPDATE SET label = excluded.label, source = excluded.source",
            (address, label, source),
        )
        await db.commit()


async def remove_trader(address: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM traders WHERE address = ?", (address,))
        await db.commit()


async def toggle_trader(address: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE traders SET active = CASE WHEN active = 1 THEN 0 ELSE 1 END "
            "WHERE address = ?",
            (address,),
        )
        await db.commit()


# --- Activity Log ---

async def log_activity(
    event_type: str,
    market_id: str = "",
    trader: str = "",
    outcome: str = "",
    size_usd: float = 0,
    price: float = 0,
    mode: str = "paper",
    details: str = "",
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO activity_log (event_type, market_id, trader, outcome, "
            "size_usd, price, mode, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event_type, market_id, trader, outcome, size_usd, price, mode, details),
        )
        await db.commit()


async def get_activity(limit: int = 50) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# --- Positions ---

async def upsert_position(
    market_id: str,
    token_id: str = "",
    condition_id: str = "",
    outcome: str = "",
    size_usd: float = 0,
    entry_price: float = 0,
    trader: str = "",
    mode: str = "paper",
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO positions (market_id, token_id, condition_id, outcome, "
            "size_usd, entry_price, trader, mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(market_id) DO UPDATE SET "
            "size_usd = excluded.size_usd, entry_price = excluded.entry_price, "
            "condition_id = CASE WHEN excluded.condition_id != '' "
            "THEN excluded.condition_id ELSE positions.condition_id END",
            (market_id, token_id, condition_id, outcome, size_usd, entry_price, trader, mode),
        )
        await db.commit()


async def remove_position(market_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM positions WHERE market_id = ?", (market_id,))
        await db.commit()


async def get_positions() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM positions ORDER BY opened_at DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def clear_positions() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM positions")
        await db.commit()
