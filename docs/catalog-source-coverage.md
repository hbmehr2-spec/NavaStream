# NavaStream catalog source coverage: Musics-fa

## Verified page structures

- The homepage exposes a visible **Singer List** whose links use the `/artists/<slug>/` path.
- A singer archive page has a heading identifying the singer, descriptive text, repeated song cards using `article.mf_pst`, and pagination links.
- Song cards link to individual `/download-song/<id>/` pages. Some cards link to more than one singer archive, so the normalized relation is many-to-many rather than a single artist string.
- The homepage also exposes mood/language/category archives such as sad, birthday, Kurdish, romantic, Turkish, mobile ringtone, bandari, Arabic, Spanish, Korean, Russian, Hindi, Brazilian, and children’s music.

## What this implementation stores

- A normalized artist entity keyed by its canonical Musics-fa archive URL.
- Artist name, source URL, page description, artwork when present, and crawl timestamp.
- Many-to-many links between local catalog tracks and artist entities, based on song cards found on each artist archive.
- Cloudflare D1 equivalents and read endpoints:
  - `GET /v1/artists`
  - `GET /v1/artists/{id}`
- Artist pages are crawled separately from the general newest-tracks pagination. The manual catalog workflow accepts a maximum artist count and imports the track catalog before artist relationships.
- Track listing API supports an optional `scope=iranian|foreign|uncertain` filter; the default returns all scope classes and does not silently hide unverified records.

## Deliberate limits

- An artist archive is evidence that Musics-fa groups songs under that artist; it is not proof of nationality, citizenship, or exclusive authorship.
- A track can be associated with multiple artist archives (collaborations). Do not overwrite its original parsed artist string with the archive heading.
- Foreign-language categories are not a reliable nationality classifier. Turkish, Arabic, Kurdish, and regional language content can also be Iranian. Track and artist records now carry `catalog_scope`, `scope_confidence`, and `scope_evidence`. Only exact matches against a small curated foreign-artist allowlist are marked `foreign` with high confidence; every other record remains `uncertain`. No artist or track is automatically labelled Iranian, and no uncertain record is excluded.
- Artist archives can contain explicit album cards, identifiable from Persian «دانلود آلبوم» and English «Download New Album BY» metadata. The crawler stores album name, source URL, release date, artwork when present, and artist relationships as normalized entities. It excludes those cards from the ordinary track list. The inspected cards do not establish a separate album track-list structure, so the API explicitly reports that a track list was not provided rather than inventing one.
- Migrations `0004`–`0006` are additive and do not alter Telegram publication rows. No production D1 migration or Worker deployment is performed by this PR.

## Crawl controls

- `NAVASTREAM_ARTIST_LIMIT` / `--limit`: maximum number of artist archive pages discovered from the homepage.
- `NAVASTREAM_ARTIST_PAGE_LIMIT` / `--page-limit`: maximum pages per artist archive.
- The crawler deduplicates artist pages by canonical URL and song cards by source URL.

## Manual review export

After crawling tracks and artist archives into the local SQLite database, run:

```bash
PYTHONPATH=. python scripts/catalog_review_report.py
```

The command creates timestamped CSV files for tracks and artists that still need review, plus a JSON summary, under `reports/catalog-review/`. Use `--output-dir` to choose another destination. The database is opened read-only; this report does not change local records, call the API, upload data, or infer Iranian origin. Track candidates include uncertain origin, missing/low-confidence artist identity, and audio-metadata mismatches. Artist rows are included when their origin scope is uncertain.



## Relationship integrity audit

The read-only catalog review report also exports tracks with no normalized artist relation, artist entities with no linked catalog track, and album entities with no linked artist. These are audit candidates only. An absent relation is not proof of bad source data; collaborations and incomplete crawls can explain it. The report never creates or deletes relationships. The JSON summary includes counts for each category.


## Local catalog rebuild

To start over on the phone without touching the Cloudflare server, run:

```bash
PYTHONPATH=. python scripts/reset_local_catalog.py
```

The script first creates a timestamped SQLite backup using SQLite's online backup API. It then clears local tracks, processing queue, normalized artists/albums, and their relationship tables. It preserves the source registry and schema. The backup contains the previous local catalog and queue and can be restored if needed.

For the complete local rebuild in one command, use `PYTHONPATH=. python -m scripts.rebuild_local_catalog`. It backs up and clears the local catalog, crawls the main Musics-fa listing (default target 5,000 tracks), then crawls up to 2,000 artist archives with up to 100 pages each. It does not modify Cloudflare. Review the crawl totals before running the three Cloudflare sync scripts.
