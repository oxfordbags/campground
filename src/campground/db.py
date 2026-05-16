import pathlib
import sqlite3

DB_PATH = pathlib.Path.home() / ".local" / "share" / "campground" / "library.db"


def open_db(path: pathlib.Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    _init_schema(con)
    return con


def _init_schema(con: sqlite3.Connection):
    con.execute("""
        CREATE TABLE IF NOT EXISTS items (
            sale_item_id       INTEGER PRIMARY KEY,
            title              TEXT    NOT NULL,
            artist             TEXT    NOT NULL,
            item_url           TEXT    NOT NULL,
            download_available INTEGER NOT NULL DEFAULT 1,
            first_seen_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            downloaded_at      TEXT,
            year               TEXT
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_item_url ON items(item_url)")

    # Migrations for DBs created before first_seen_at / downloaded_at were added.
    for col, definition in [
        ("first_seen_at", "TEXT NOT NULL DEFAULT (datetime('now'))"),
        ("downloaded_at",  "TEXT"),
        ("year",           "TEXT"),
    ]:
        try:
            con.execute(f"ALTER TABLE items ADD COLUMN {col} {definition}")
        except sqlite3.OperationalError:
            pass  # column already exists

    con.commit()


def upsert_item(con: sqlite3.Connection, item: dict):
    con.execute(
        """
        INSERT INTO items (sale_item_id, title, artist, item_url, download_available)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(sale_item_id) DO UPDATE SET
            title=excluded.title,
            artist=excluded.artist,
            item_url=excluded.item_url,
            download_available=excluded.download_available
        """,
        (
            item["sale_item_id"],
            item.get("item_title", ""),
            item.get("band_name", ""),
            item.get("item_url", ""),
            int(bool(item.get("download_available", True))),
        ),
    )


def has_item(con: sqlite3.Connection, sale_item_id: int) -> bool:
    row = con.execute(
        "SELECT 1 FROM items WHERE sale_item_id = ?", (sale_item_id,)
    ).fetchone()
    return row is not None


def lookup_by_url(con: sqlite3.Connection, normalised_url: str) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM items WHERE item_url = ?", (normalised_url,)
    ).fetchone()


def search_items(con: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    pattern = f"%{query}%"
    return con.execute(
        """
        SELECT * FROM items
        WHERE title LIKE ? OR artist LIKE ?
        ORDER BY artist, title
        """,
        (pattern, pattern),
    ).fetchall()


def get_all_downloadable_ids(con: sqlite3.Connection) -> set[int]:
    rows = con.execute(
        "SELECT sale_item_id FROM items WHERE download_available = 1"
    ).fetchall()
    return {row[0] for row in rows}


def get_new_item_ids(con: sqlite3.Connection) -> set[int]:
    """IDs of downloadable items added since the last completed download."""
    last = con.execute(
        "SELECT MAX(downloaded_at) FROM items WHERE downloaded_at IS NOT NULL"
    ).fetchone()[0]
    if last is None:
        return get_all_downloadable_ids(con)
    rows = con.execute(
        "SELECT sale_item_id FROM items WHERE download_available = 1 AND first_seen_at > ?",
        (last,),
    ).fetchall()
    return {row[0] for row in rows}


def get_year(con: sqlite3.Connection, sale_item_id: int) -> str | None:
    row = con.execute(
        "SELECT year FROM items WHERE sale_item_id = ?", (sale_item_id,)
    ).fetchone()
    return row["year"] if row else None


def store_year(con: sqlite3.Connection, sale_item_id: int, year: str):
    con.execute(
        "UPDATE items SET year = ? WHERE sale_item_id = ?", (year, sale_item_id)
    )
    con.commit()


def mark_downloaded(con: sqlite3.Connection, sale_item_id: int):
    con.execute(
        "UPDATE items SET downloaded_at = datetime('now') WHERE sale_item_id = ?",
        (sale_item_id,),
    )
    con.commit()
