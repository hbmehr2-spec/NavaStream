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

## Deliberate limits

- An artist archive is evidence that Musics-fa groups songs under that artist; it is not proof of nationality, citizenship, or exclusive authorship.
- A track can be associated with multiple artist archives (collaborations). Do not overwrite its original parsed artist string with the archive heading.
- Foreign-language categories are not a reliable nationality classifier. Turkish, Arabic, Kurdish, and regional language content can also be Iranian. This stage does not auto-exclude tracks or label unknown artists as Iranian/foreign.
- The inspected artist archive pages expose song lists, not a distinct album entity or album track-list structure. Album tables are intentionally not fabricated. Album extraction should be added only after a real album page or album-specific markup is confirmed.
- No production D1 migration or Worker deployment is performed by this PR. Migration `0004` is additive and does not alter Telegram publication rows.

## Crawl controls

- `NAVASTREAM_ARTIST_LIMIT` / `--limit`: maximum number of artist archive pages discovered from the homepage.
- `NAVASTREAM_ARTIST_PAGE_LIMIT` / `--page-limit`: maximum pages per artist archive.
- The crawler deduplicates artist pages by canonical URL and song cards by source URL.
