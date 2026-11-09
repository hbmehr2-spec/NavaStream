import argparse
import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.database import DB_PATH


TRACK_COLUMNS = (
    "id", "title", "artist", "source_url", "audio_url", "artwork_url",
    "external_id", "release_date", "validation_status", "validation_note",
    "artist_source", "artist_confidence", "catalog_scope", "scope_confidence",
    "scope_evidence", "source_categories_json", "mood_tags_json",
    "genre_tags_json", "language_tags_json", "region_tags_json",
    "trend_tags_json", "version_type",
)


def table_exists(connection, table_name):
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def existing_columns(connection, table_name):
    return {
        row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")
    }


def is_track_review_candidate(track):
    return (
        track.get("catalog_scope", "uncertain") == "uncertain"
        or not track.get("artist")
        or track.get("artist_confidence") == "low"
        or track.get("validation_status") in ("needs_review", "mismatch")
    )


def _json_list(value):
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _csv_value(value):
    if isinstance(value, list):
        return " | ".join(str(item) for item in value)
    return "" if value is None else value


def fetch_track_rows(connection):
    if not table_exists(connection, "tracks"):
        return []
    columns = existing_columns(connection, "tracks")
    selected = [column for column in TRACK_COLUMNS if column in columns]
    if "id" not in selected:
        return []
    query = f"SELECT {', '.join(selected)} FROM tracks ORDER BY id"
    connection.row_factory = sqlite3.Row
    rows = []
    for raw in connection.execute(query):
        item = dict(raw)
        for field in (
            "source_categories_json", "mood_tags_json", "genre_tags_json",
            "language_tags_json", "region_tags_json", "trend_tags_json",
        ):
            item[field.removesuffix("_json")] = _json_list(item.get(field))
        if is_track_review_candidate(item):
            rows.append(item)
    return rows


def fetch_artist_rows(connection):
    if not table_exists(connection, "catalog_artists"):
        return []
    columns = existing_columns(connection, "catalog_artists")
    wanted = (
        "id", "name", "source_url", "description", "artwork_url",
        "catalog_scope", "scope_confidence", "scope_evidence",
    )
    selected = [column for column in wanted if column in columns]
    if "id" not in selected:
        return []
    connection.row_factory = sqlite3.Row
    query = f"SELECT {', '.join(selected)} FROM catalog_artists ORDER BY name"
    return [
        dict(row) for row in connection.execute(query)
        if row["catalog_scope"] == "uncertain"
    ] if "catalog_scope" in selected else [
        dict(row) for row in connection.execute(query)
    ]


def fetch_unlinked_track_rows(connection):
    if not table_exists(connection, 'tracks') or not table_exists(connection, 'catalog_track_artists'):
        return []
    columns = existing_columns(connection, 'tracks')
    wanted = ('id', 'title', 'artist', 'source_url', 'audio_url', 'catalog_scope', 'artist_confidence')
    selected = [column for column in wanted if column in columns]
    if 'id' not in selected:
        return []
    query = 'SELECT ' + ', '.join('t.' + column for column in selected) + ' FROM tracks AS t LEFT JOIN catalog_track_artists AS cta ON cta.track_id = t.id WHERE cta.track_id IS NULL ORDER BY t.id'
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(query)]

def fetch_orphan_artist_rows(connection):
    if not table_exists(connection, 'catalog_artists') or not table_exists(connection, 'catalog_track_artists'):
        return []
    columns = existing_columns(connection, 'catalog_artists')
    wanted = ('id', 'name', 'source_url', 'catalog_scope', 'scope_confidence')
    selected = [column for column in wanted if column in columns]
    if 'id' not in selected:
        return []
    query = 'SELECT ' + ', '.join('a.' + column for column in selected) + ' FROM catalog_artists AS a LEFT JOIN catalog_track_artists AS cta ON cta.artist_id = a.id WHERE cta.artist_id IS NULL ORDER BY a.name'
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(query)]

def fetch_orphan_album_rows(connection):
    if not table_exists(connection, 'catalog_albums') or not table_exists(connection, 'catalog_artist_albums'):
        return []
    columns = existing_columns(connection, 'catalog_albums')
    wanted = ('id', 'name', 'source_url', 'release_date', 'artwork_url')
    selected = [column for column in wanted if column in columns]
    if 'id' not in selected:
        return []
    query = 'SELECT ' + ', '.join('a.' + column for column in selected) + ' FROM catalog_albums AS a LEFT JOIN catalog_artist_albums AS caa ON caa.album_id = a.id WHERE caa.album_id IS NULL ORDER BY a.name'
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(query)]

def fetch_album_count(connection):
    if not table_exists(connection, "catalog_albums"):
        return 0
    return connection.execute("SELECT COUNT(*) FROM catalog_albums").fetchone()[0]


def write_csv(path, rows, columns):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def generate_report(database_path=DB_PATH, output_dir=Path("reports/catalog-review")):
    database_path = Path(database_path)
    if not database_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {database_path}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True, timeout=15)
    try:
        tracks = fetch_track_rows(connection)
        artists = fetch_artist_rows(connection)
        album_count = fetch_album_count(connection)
        unlinked_tracks = fetch_unlinked_track_rows(connection)
        orphan_artists = fetch_orphan_artist_rows(connection)
        orphan_albums = fetch_orphan_album_rows(connection)
        all_tracks = connection.execute(
            "SELECT COUNT(*) FROM tracks"
        ).fetchone()[0] if table_exists(connection, "tracks") else 0
        scope_counts = {}
        if table_exists(connection, "tracks") and "catalog_scope" in existing_columns(connection, "tracks"):
            scope_counts = {
                row[0] or "uncertain": row[1]
                for row in connection.execute(
                    "SELECT catalog_scope, COUNT(*) FROM tracks GROUP BY catalog_scope"
                )
            }
    finally:
        connection.close()

    track_path = output_dir / f"tracks-review-{stamp}.csv"
    artist_path = output_dir / f"artists-review-{stamp}.csv"
    summary_path = output_dir / f"summary-{stamp}.json"
    unlinked_path = output_dir / f"unlinked-tracks-{stamp}.csv"
    orphan_artists_path = output_dir / f"orphan-artists-{stamp}.csv"
    orphan_albums_path = output_dir / f"orphan-albums-{stamp}.csv"

    track_fields = list(TRACK_COLUMNS) + [
        "source_categories", "mood_tags", "genre_tags", "language_tags",
        "region_tags", "trend_tags",
    ]
    artist_fields = [
        "id", "name", "source_url", "description", "artwork_url",
        "catalog_scope", "scope_confidence", "scope_evidence",
    ]
    write_csv(track_path, tracks, track_fields)
    write_csv(artist_path, artists, artist_fields)
    write_csv(unlinked_path, unlinked_tracks, ['id', 'title', 'artist', 'source_url', 'audio_url', 'catalog_scope', 'artist_confidence'])
    write_csv(orphan_artists_path, orphan_artists, ['id', 'name', 'source_url', 'catalog_scope', 'scope_confidence'])
    write_csv(orphan_albums_path, orphan_albums, ['id', 'name', 'source_url', 'release_date', 'artwork_url'])

    summary = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "database": str(database_path.resolve()),
        "track_total": all_tracks,
        "track_review_candidates": len(tracks),
        "artist_review_candidates": len(artists),
        "album_total": album_count,
        "tracks_without_artist_link": len(unlinked_tracks),
        "artists_without_track_link": len(orphan_artists),
        "albums_without_artist_link": len(orphan_albums),
        "track_scope_counts": scope_counts,
        "policy": (
            "Uncertain records are exported for manual review. This report does not "
            "change, delete, classify, or upload any catalog data."
        ),
        "files": {
            "tracks_csv": str(track_path),
            "artists_csv": str(artist_path),
            "unlinked_tracks_csv": str(unlinked_path),
            "orphan_artists_csv": str(orphan_artists_path),
            "orphan_albums_csv": str(orphan_albums_path),
        },
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary, (track_path, artist_path, unlinked_path, orphan_artists_path, orphan_albums_path, summary_path)


def main():
    parser = argparse.ArgumentParser(
        description="Export uncertain NavaStream catalog records for manual review."
    )
    parser.add_argument("--database", type=Path, default=DB_PATH)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("reports/catalog-review")
    )
    args = parser.parse_args()

    summary, paths = generate_report(args.database, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Created:")
    for path in paths:
        print(f"- {path}")


if __name__ == "__main__":
    main()
