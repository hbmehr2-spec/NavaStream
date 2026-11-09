import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

from app.database import DB_PATH


# These are local catalog/queue tables only. The source registry is preserved.
RESET_TABLES = (
    "catalog_track_artists",
    "catalog_artist_albums",
    "catalog_albums",
    "catalog_artists",
    "processing_queue",
    "tracks",
)


def backup_database(database: Path) -> Path:
    if not database.exists():
        raise FileNotFoundError(f"Database not found: {database}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = database.with_name(f"{database.stem}-before-rebuild-{stamp}{database.suffix}")
    source = sqlite3.connect(str(database))
    destination = sqlite3.connect(str(backup))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return backup


def reset_local_catalog(database: Path = DB_PATH) -> dict:
    backup = backup_database(database)
    connection = sqlite3.connect(str(database))
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        cleared = []
        connection.execute("BEGIN IMMEDIATE")
        for table in RESET_TABLES:
            if table in existing:
                # Table names come only from the fixed allowlist above.
                connection.execute(f'DELETE FROM "{table}"')
                cleared.append(table)
        if "sqlite_sequence" in existing:
            for table in cleared:
                connection.execute(
                    "DELETE FROM sqlite_sequence WHERE name = ?", (table,)
                )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    return {
        "database": str(database.resolve()),
        "backup": str(backup.resolve()),
        "cleared_tables": cleared,
        "preserved": ["sources", "database schema", "configuration outside this database"],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Back up and clear only the local NavaStream catalog and processing queue."
    )
    parser.add_argument("--database", type=Path, default=DB_PATH)
    args = parser.parse_args()

    result = reset_local_catalog(args.database)
    print("Local catalog reset completed.")
    print(f"Backup: {result['backup']}")
    print("Cleared: " + ", ".join(result["cleared_tables"]))
    print("Preserved: " + ", ".join(result["preserved"]))


if __name__ == "__main__":
    main()
