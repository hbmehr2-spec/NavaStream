const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "public, max-age=60",
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      ...JSON_HEADERS,
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET, POST, OPTIONS",
      "access-control-allow-headers": "Content-Type, Authorization",
    },
  });
}

function parseJsonArray(value) {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function trackPayload(row) {
  return {
    id: String(row.id),
    title: row.title || "عنوان نامشخص",
    artist: row.artist || "هنرمند نامشخص",
    audioUrl: row.audio_url,
    artworkUrl: row.artwork_url,
    durationSeconds: row.duration_seconds,
    publishedAt: row.published_at,
    sourceCategories: parseJsonArray(row.source_categories_json),
    moodTags: parseJsonArray(row.mood_tags_json),
    genreTags: parseJsonArray(row.genre_tags_json),
    languageTags: parseJsonArray(row.language_tags_json),
    regionTags: parseJsonArray(row.region_tags_json),
    trendTags: parseJsonArray(row.trend_tags_json),
    versionType: row.version_type || null,
    artistSource: row.artist_source || null,
    artistConfidence: row.artist_confidence || null,
    catalogScope: row.catalog_scope || "uncertain",
    scopeConfidence: row.scope_confidence || "low",
    scopeEvidence: row.scope_evidence || "no_verified_origin_evidence",
  };
}

async function equalSecret(candidate, expected) {
  const encoder = new TextEncoder();
  const [left, right] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(candidate)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  const a = new Uint8Array(left);
  const b = new Uint8Array(right);
  let difference = 0;
  for (let i = 0; i < a.length; i += 1) difference |= a[i] ^ b[i];
  return difference === 0;
}

function validHttpsUrl(value, nullable = false) {
  if (nullable && (value === null || value === undefined || value === "")) {
    return true;
  }
  if (typeof value !== "string" || value.length > 2048) return false;
  try {
    return new URL(value).protocol === "https:";
  } catch {
    return false;
  }
}

function validateTrack(track) {
  if (!track || typeof track !== "object" || Array.isArray(track)) return false;
  if (!Number.isSafeInteger(track.id) || track.id < 1) return false;
  if (!Number.isSafeInteger(track.telegram_message_id) || track.telegram_message_id < 1) return false;
  if (typeof track.title !== "string" || !track.title.trim() || track.title.length > 500) return false;
  if (track.artist !== null && track.artist !== undefined &&
      (typeof track.artist !== "string" || track.artist.length > 500)) return false;
  if (!validHttpsUrl(track.audio_url)) return false;
  if (!validHttpsUrl(track.artwork_url, true)) return false;
  if (track.duration_seconds !== null && track.duration_seconds !== undefined &&
      (!Number.isSafeInteger(track.duration_seconds) || track.duration_seconds < 0)) return false;
  if (track.published_at !== null && track.published_at !== undefined &&
      (typeof track.published_at !== "string" || track.published_at.length > 64)) return false;
  return true;
}

function validateCatalogTrack(track) {
  if (!track || typeof track !== "object" || Array.isArray(track)) return false;
  if (typeof track.title !== "string" || !track.title.trim() || track.title.length > 500) return false;
  if (track.artist !== null && track.artist !== undefined &&
      (typeof track.artist !== "string" || track.artist.length > 500)) return false;
  if (!validHttpsUrl(track.audio_url)) return false;
  if (!validHttpsUrl(track.artwork_url, true)) return false;
  if (!validHttpsUrl(track.source_url)) return false;
  if (track.external_id !== null && track.external_id !== undefined &&
      (typeof track.external_id !== "string" || track.external_id.length > 100)) return false;
  if (track.release_date !== null && track.release_date !== undefined &&
      (typeof track.release_date !== "string" || track.release_date.length > 64)) return false;

  const jsonFields = [
    "source_categories_json",
    "mood_tags_json",
    "genre_tags_json",
    "language_tags_json",
    "region_tags_json",
    "trend_tags_json",
  ];
  for (const field of jsonFields) {
    const value = track[field] ?? "[]";
    if (typeof value !== "string" || value.length > 8000) return false;
    try {
      const parsed = JSON.parse(value);
      if (!Array.isArray(parsed) || parsed.length > 100 ||
          !parsed.every((item) => typeof item === "string" && item.length <= 100)) {
        return false;
      }
    } catch {
      return false;
    }
  }

  for (const [field, maxLength] of [
    ["version_type", 50],
    ["artist_source", 50],
    ["artist_confidence", 20],
    ["catalog_scope", 20],
    ["scope_confidence", 20],
    ["scope_evidence", 100],
  ]) {
    const value = track[field];
    if (value !== null && value !== undefined &&
        (typeof value !== "string" || value.length > maxLength)) return false;
  }

  if (!["iranian", "foreign", "uncertain"].includes(track.catalog_scope || "uncertain")) return false;
  if (!["high", "medium", "low"].includes(track.scope_confidence || "low")) return false;
  return ["matched", "mismatch", "needs_review", "excluded"].includes(
    track.validation_status || "needs_review"
  );
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET, POST, OPTIONS",
          "access-control-allow-headers": "Content-Type, Authorization",
          "access-control-max-age": "86400",
        },
      });
    }

    if (path === "/internal/catalog-import") {
      if (request.method !== "POST") {
        return json({ error: "Method not allowed." }, 405);
      }

      const expectedSecret = env.NAVASTREAM_INGEST_SECRET;
      if (!expectedSecret || expectedSecret.length < 32) {
        return json({ error: "Catalog import endpoint is not configured." }, 503);
      }

      const authorization = request.headers.get("authorization") || "";
      const candidate = authorization.startsWith("Bearer ")
        ? authorization.slice(7)
        : "";
      if (!candidate || !(await equalSecret(candidate, expectedSecret))) {
        return json({ error: "Unauthorized." }, 401);
      }

      const contentLength = Number(request.headers.get("content-length") || "0");
      if (contentLength > 262144) {
        return json({ error: "Payload too large." }, 413);
      }

      let payload;
      try {
        const body = await request.text();
        if (new TextEncoder().encode(body).length > 262144) {
          return json({ error: "Payload too large." }, 413);
        }
        payload = JSON.parse(body);
      } catch {
        return json({ error: "Invalid JSON." }, 400);
      }

      if (!payload || !Array.isArray(payload.tracks) ||
          payload.tracks.length < 1 || payload.tracks.length > 100) {
        return json({ error: "tracks must contain between 1 and 100 items." }, 400);
      }
      if (!payload.tracks.every(validateCatalogTrack)) {
        return json({ error: "One or more catalog tracks contain invalid fields." }, 400);
      }

      try {
        const statements = payload.tracks.map((track) =>
          env.DB.prepare(
            "INSERT INTO catalog_tracks (title, artist, audio_url, artwork_url, source_url, external_id, release_date, validation_status, source_categories_json, mood_tags_json, genre_tags_json, language_tags_json, region_tags_json, trend_tags_json, version_type, artist_source, artist_confidence, catalog_scope, scope_confidence, scope_evidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(source_url) DO UPDATE SET title = excluded.title, artist = excluded.artist, audio_url = excluded.audio_url, artwork_url = excluded.artwork_url, external_id = excluded.external_id, release_date = excluded.release_date, validation_status = excluded.validation_status, source_categories_json = excluded.source_categories_json, mood_tags_json = excluded.mood_tags_json, genre_tags_json = excluded.genre_tags_json, language_tags_json = excluded.language_tags_json, region_tags_json = excluded.region_tags_json, trend_tags_json = excluded.trend_tags_json, version_type = excluded.version_type, artist_source = excluded.artist_source, artist_confidence = excluded.artist_confidence, catalog_scope = excluded.catalog_scope, scope_confidence = excluded.scope_confidence, scope_evidence = excluded.scope_evidence"
          ).bind(
            track.title.trim(),
            track.artist || null,
            track.audio_url,
            track.artwork_url || null,
            track.source_url,
            track.external_id || null,
            track.release_date || null,
            track.validation_status || "needs_review",
            track.source_categories_json || "[]",
            track.mood_tags_json || "[]",
            track.genre_tags_json || "[]",
            track.language_tags_json || "[]",
            track.region_tags_json || "[]",
            track.trend_tags_json || "[]",
            track.version_type || null,
            track.artist_source || null,
            track.artist_confidence || null,
            track.catalog_scope || "uncertain",
            track.scope_confidence || "low",
            track.scope_evidence || "no_verified_origin_evidence",
          )
        );

        await env.DB.batch(statements);
        const result = await env.DB.prepare(
          "SELECT COUNT(*) AS total FROM catalog_tracks WHERE audio_url LIKE 'https://%'"
        ).first();

        return json({
          ok: true,
          imported: payload.tracks.length,
          catalogTracks: result?.total || 0,
        });
      } catch (error) {
        console.error("NavaStream catalog import failed:", error);
        return json({ error: "Catalog import failed. No success was reported." }, 500);
      }
    }

    if (path === "/internal/artist-import") {
      if (request.method !== "POST") return json({ error: "Method not allowed." }, 405);
      const expectedSecret = env.NAVASTREAM_INGEST_SECRET;
      if (!expectedSecret || expectedSecret.length < 32) {
        return json({ error: "Artist import endpoint is not configured." }, 503);
      }
      const authorization = request.headers.get("authorization") || "";
      const candidate = authorization.startsWith("Bearer ") ? authorization.slice(7) : "";
      if (!candidate || !(await equalSecret(candidate, expectedSecret))) {
        return json({ error: "Unauthorized." }, 401);
      }
      let payload;
      try {
        const body = await request.text();
        if (new TextEncoder().encode(body).length > 262144) return json({ error: "Payload too large." }, 413);
        payload = JSON.parse(body);
      } catch {
        return json({ error: "Invalid JSON." }, 400);
      }
      if (!payload || !Array.isArray(payload.artists) ||
          payload.artists.length < 1 || payload.artists.length > 50) {
        return json({ error: "artists must contain between 1 and 50 items." }, 400);
      }
      const valid = payload.artists.every((artist) =>
        artist && typeof artist.name === "string" && artist.name.trim().length > 0 &&
        artist.name.length <= 300 && validHttpsUrl(artist.source_url) &&
        (artist.description == null || (typeof artist.description === "string" && artist.description.length <= 4000)) &&
        (artist.artwork_url == null || validHttpsUrl(artist.artwork_url, true)) &&
        Array.isArray(artist.track_source_urls) && artist.track_source_urls.length <= 500 &&
        artist.track_source_urls.every((value) => validHttpsUrl(value))
      );
      if (!valid) return json({ error: "One or more artist records are invalid." }, 400);
      try {
        let linkedTracks = 0;
        for (const artist of payload.artists) {
          await env.DB.prepare(
            "INSERT INTO catalog_artists (name, source_url, description, artwork_url, catalog_scope, scope_confidence, scope_evidence, last_crawled_at) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(source_url) DO UPDATE SET name = excluded.name, description = COALESCE(excluded.description, catalog_artists.description), artwork_url = COALESCE(excluded.artwork_url, catalog_artists.artwork_url), catalog_scope = excluded.catalog_scope, scope_confidence = excluded.scope_confidence, scope_evidence = excluded.scope_evidence, last_crawled_at = CURRENT_TIMESTAMP"
          ).bind(artist.name.trim(), artist.source_url, artist.description || null, artist.artwork_url || null, artist.catalog_scope || "uncertain", artist.scope_confidence || "low", artist.scope_evidence || "no_verified_origin_evidence").run();
          const saved = await env.DB.prepare(
            "SELECT id FROM catalog_artists WHERE source_url = ? LIMIT 1"
          ).bind(artist.source_url).first();
          if (!saved) continue;
          const uniqueUrls = [...new Set(artist.track_source_urls)];
          for (let start = 0; start < uniqueUrls.length; start += 80) {
            const chunk = uniqueUrls.slice(start, start + 80);
            if (!chunk.length) continue;
            const placeholders = chunk.map(() => "?").join(", ");
            const result = await env.DB.prepare(
              `INSERT OR IGNORE INTO catalog_track_artists (artist_id, track_id, source_url)
               SELECT ?, id, source_url FROM catalog_tracks
               WHERE source_url IN (${placeholders})`
            ).bind(saved.id, ...chunk).run();
            linkedTracks += result.meta?.changes || 0;
          }
        }
        const count = await env.DB.prepare("SELECT COUNT(*) AS total FROM catalog_artists").first();
        return json({ ok: true, imported: payload.artists.length, linkedTracks, artistsTotal: count?.total || 0 });
      } catch (error) {
        console.error("NavaStream artist import failed:", error);
        return json({ error: "Artist import failed." }, 500);
      }
    }

    if (path === "/internal/album-import") {
      if (request.method !== "POST") return json({ error: "Method not allowed." }, 405);
      const expectedSecret = env.NAVASTREAM_INGEST_SECRET;
      if (!expectedSecret || expectedSecret.length < 32) return json({ error: "Album import endpoint is not configured." }, 503);
      const authorization = request.headers.get("authorization") || "";
      const candidate = authorization.startsWith("Bearer ") ? authorization.slice(7) : "";
      if (!candidate || !(await equalSecret(candidate, expectedSecret))) return json({ error: "Unauthorized." }, 401);
      let payload;
      try {
        const body = await request.text();
        if (new TextEncoder().encode(body).length > 262144) return json({ error: "Payload too large." }, 413);
        payload = JSON.parse(body);
      } catch {
        return json({ error: "Invalid JSON." }, 400);
      }
      if (!payload || !Array.isArray(payload.albums) || payload.albums.length < 1 || payload.albums.length > 50) {
        return json({ error: "albums must contain between 1 and 50 items." }, 400);
      }
      const valid = payload.albums.every((album) =>
        album && typeof album.name === "string" && album.name.trim().length > 0 &&
        album.name.length <= 300 && validHttpsUrl(album.source_url) &&
        (album.release_date == null || (typeof album.release_date === "string" && album.release_date.length <= 64)) &&
        (album.artwork_url == null || validHttpsUrl(album.artwork_url, true)) &&
        Array.isArray(album.artist_source_urls) && album.artist_source_urls.length <= 20 &&
        album.artist_source_urls.every((value) => validHttpsUrl(value))
      );
      if (!valid) return json({ error: "One or more album records are invalid." }, 400);
      try {
        for (const album of payload.albums) {
          await env.DB.prepare(
            "INSERT INTO catalog_albums (name, source_url, release_date, artwork_url) VALUES (?, ?, ?, ?) ON CONFLICT(source_url) DO UPDATE SET name = excluded.name, release_date = COALESCE(excluded.release_date, catalog_albums.release_date), artwork_url = COALESCE(excluded.artwork_url, catalog_albums.artwork_url)"
          ).bind(album.name.trim(), album.source_url, album.release_date || null, album.artwork_url || null).run();
          const savedAlbum = await env.DB.prepare(
            "SELECT id FROM catalog_albums WHERE source_url = ? LIMIT 1"
          ).bind(album.source_url).first();
          if (!savedAlbum) continue;
          for (const artistUrl of [...new Set(album.artist_source_urls)]) {
            const artist = await env.DB.prepare(
              "SELECT id FROM catalog_artists WHERE source_url = ? LIMIT 1"
            ).bind(artistUrl).first();
            if (!artist) continue;
            await env.DB.prepare(
              "INSERT OR IGNORE INTO catalog_artist_albums (artist_id, album_id, source_url) VALUES (?, ?, ?)"
            ).bind(artist.id, savedAlbum.id, album.source_url).run();
          }
        }
        const count = await env.DB.prepare("SELECT COUNT(*) AS total FROM catalog_albums").first();
        return json({ ok: true, imported: payload.albums.length, albumsTotal: count?.total || 0 });
      } catch (error) {
        console.error("NavaStream album import failed:", error);
        return json({ error: "Album import failed." }, 500);
      }
    }

    if (path === "/internal/import") {
      if (request.method !== "POST") {
        return json({ error: "Method not allowed." }, 405);
      }

      const expectedSecret = env.NAVASTREAM_INGEST_SECRET;
      if (!expectedSecret || expectedSecret.length < 32) {
        return json({ error: "Import endpoint is not configured." }, 503);
      }

      const authorization = request.headers.get("authorization") || "";
      const candidate = authorization.startsWith("Bearer ")
        ? authorization.slice(7)
        : "";
      if (!candidate || !(await equalSecret(candidate, expectedSecret))) {
        return json({ error: "Unauthorized." }, 401);
      }

      const contentLength = Number(request.headers.get("content-length") || "0");
      if (contentLength > 262144) {
        return json({ error: "Payload too large." }, 413);
      }

      let payload;
      try {
        const body = await request.text();
        if (new TextEncoder().encode(body).length > 262144) {
          return json({ error: "Payload too large." }, 413);
        }
        payload = JSON.parse(body);
      } catch {
        return json({ error: "Invalid JSON." }, 400);
      }

      if (!payload || !Array.isArray(payload.tracks) ||
          payload.tracks.length < 1 || payload.tracks.length > 100) {
        return json({ error: "tracks must contain between 1 and 100 items." }, 400);
      }
      if (!payload.tracks.every(validateTrack)) {
        return json({ error: "One or more tracks contain invalid fields." }, 400);
      }

      try {
        const statements = payload.tracks.map((track) =>
          env.DB.prepare(
            "INSERT INTO tracks (id, title, artist, audio_url, artwork_url, duration_seconds, published_at, telegram_message_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET title = excluded.title, artist = excluded.artist, audio_url = excluded.audio_url, artwork_url = excluded.artwork_url, duration_seconds = excluded.duration_seconds, published_at = excluded.published_at, telegram_message_id = excluded.telegram_message_id"
          ).bind(
            track.id,
            track.title.trim(),
            track.artist || null,
            track.audio_url,
            track.artwork_url || null,
            track.duration_seconds ?? null,
            track.published_at || null,
            track.telegram_message_id,
          )
        );

        await env.DB.batch(statements);
        const result = await env.DB.prepare(
          "SELECT COUNT(*) AS total FROM tracks WHERE telegram_message_id IS NOT NULL AND audio_url LIKE 'https://%'"
        ).first();

        return json({
          ok: true,
          imported: payload.tracks.length,
          publishedTracks: result?.total || 0,
        });
      } catch (error) {
        console.error("NavaStream import failed:", error);
        return json({ error: "Import failed. No success was reported." }, 500);
      }
    }

    if (request.method !== "GET") {
      return json({ error: "Method not allowed." }, 405);
    }

    try {
      if (path === "/health") {
        const [publishedResult, catalogResult] = await Promise.all([
          env.DB.prepare(
            "SELECT COUNT(*) AS total, MAX(published_at) AS latest_publication FROM tracks WHERE telegram_message_id IS NOT NULL AND audio_url LIKE 'https://%'"
          ).first(),
          env.DB.prepare(
            "SELECT COUNT(*) AS total FROM catalog_tracks WHERE audio_url LIKE 'https://%'"
          ).first(),
        ]);

        return json({
          ok: true,
          service: "navastream-api",
          publishedTracks: publishedResult?.total || 0,
          catalogTracks: catalogResult?.total || 0,
          latestPublication: publishedResult?.latest_publication || null,
        });
      }

      if (path === "/v1/artists") {
        const query = (url.searchParams.get("q") || "").trim().slice(0, 120);
        const limit = Math.min(100, Math.max(1, Number.parseInt(url.searchParams.get("limit") || "30", 10) || 30));
        const offset = Math.max(0, Number.parseInt(url.searchParams.get("cursor") || "0", 10) || 0);
        const statement = query
          ? env.DB.prepare("SELECT a.id, a.name, a.source_url, a.description, a.artwork_url, a.catalog_scope, a.scope_confidence, a.scope_evidence, COUNT(ta.track_id) AS track_count FROM catalog_artists a LEFT JOIN catalog_track_artists ta ON ta.artist_id = a.id WHERE a.name LIKE ? GROUP BY a.id ORDER BY a.name COLLATE NOCASE LIMIT ? OFFSET ?").bind(`%${query}%`, limit + 1, offset)
          : env.DB.prepare("SELECT a.id, a.name, a.source_url, a.description, a.artwork_url, COUNT(ta.track_id) AS track_count FROM catalog_artists a LEFT JOIN catalog_track_artists ta ON ta.artist_id = a.id GROUP BY a.id ORDER BY a.name COLLATE NOCASE LIMIT ? OFFSET ?").bind(limit + 1, offset);
        const result = await statement.all();
        const rows = result.results || [];
        const hasMore = rows.length > limit;
        return json({
          items: rows.slice(0, limit).map((row) => ({
            id: String(row.id), name: row.name, sourceUrl: row.source_url,
            description: row.description, artworkUrl: row.artwork_url,
            catalogScope: row.catalog_scope || "uncertain",
            scopeConfidence: row.scope_confidence || "low",
            scopeEvidence: row.scope_evidence || "no_verified_origin_evidence",
            trackCount: row.track_count || 0,
          })),
          nextCursor: hasMore ? String(offset + limit) : null,
        });
      }

      const artistMatch = path.match(/^\/v1\/artists\/(\d+)$/);
      if (artistMatch) {
        const artist = await env.DB.prepare(
          "SELECT id, name, source_url, description, artwork_url, catalog_scope, scope_confidence, scope_evidence FROM catalog_artists WHERE id = ? LIMIT 1"
        ).bind(Number(artistMatch[1])).first();
        if (!artist) return json({ error: "Artist not found." }, 404);
        const tracks = await env.DB.prepare(
          "SELECT t.id, t.title, t.artist, t.audio_url, t.artwork_url, t.published_at, t.source_categories_json, t.mood_tags_json, t.genre_tags_json, t.language_tags_json, t.region_tags_json, t.trend_tags_json, t.version_type, t.artist_source, t.artist_confidence FROM catalog_track_artists ta JOIN catalog_tracks t ON t.id = ta.track_id WHERE ta.artist_id = ? AND t.audio_url LIKE 'https://%' AND t.validation_status != 'excluded' ORDER BY t.id DESC"
        ).bind(artist.id).all();
        return json({
          id: String(artist.id), name: artist.name, sourceUrl: artist.source_url,
          description: artist.description, artworkUrl: artist.artwork_url,
          catalogScope: artist.catalog_scope || "uncertain",
          scopeConfidence: artist.scope_confidence || "low",
          scopeEvidence: artist.scope_evidence || "no_verified_origin_evidence",
          tracks: (tracks.results || []).map(trackPayload),
        });
      }

      if (path === "/v1/albums") {
        const query = (url.searchParams.get("q") || "").trim().slice(0, 120);
        const limit = Math.min(100, Math.max(1, Number.parseInt(url.searchParams.get("limit") || "30", 10) || 30));
        const offset = Math.max(0, Number.parseInt(url.searchParams.get("cursor") || "0", 10) || 0);
        const statement = query
          ? env.DB.prepare("SELECT a.id, a.name, a.source_url, a.release_date, a.artwork_url, COUNT(aa.artist_id) AS artist_count FROM catalog_albums a LEFT JOIN catalog_artist_albums aa ON aa.album_id = a.id WHERE a.name LIKE ? GROUP BY a.id ORDER BY a.id DESC LIMIT ? OFFSET ?").bind(`%${query}%`, limit + 1, offset)
          : env.DB.prepare("SELECT a.id, a.name, a.source_url, a.release_date, a.artwork_url, COUNT(aa.artist_id) AS artist_count FROM catalog_albums a LEFT JOIN catalog_artist_albums aa ON aa.album_id = a.id GROUP BY a.id ORDER BY a.id DESC LIMIT ? OFFSET ?").bind(limit + 1, offset);
        const result = await statement.all();
        const rows = result.results || [];
        const hasMore = rows.length > limit;
        return json({
          items: rows.slice(0, limit).map((row) => ({
            id: String(row.id), name: row.name, sourceUrl: row.source_url,
            releaseDate: row.release_date, artworkUrl: row.artwork_url,
            artistCount: row.artist_count || 0,
          })),
          nextCursor: hasMore ? String(offset + limit) : null,
        });
      }

      const albumMatch = path.match(/^\/v1\/albums\/(\d+)$/);
      if (albumMatch) {
        const album = await env.DB.prepare(
          "SELECT id, name, source_url, release_date, artwork_url FROM catalog_albums WHERE id = ? LIMIT 1"
        ).bind(Number(albumMatch[1])).first();
        if (!album) return json({ error: "Album not found." }, 404);
        const artists = await env.DB.prepare(
          "SELECT a.id, a.name, a.source_url FROM catalog_artist_albums aa JOIN catalog_artists a ON a.id = aa.artist_id WHERE aa.album_id = ? ORDER BY a.name COLLATE NOCASE"
        ).bind(album.id).all();
        return json({
          id: String(album.id), name: album.name, sourceUrl: album.source_url,
          releaseDate: album.release_date, artworkUrl: album.artwork_url,
          artists: artists.results || [],
          tracks: [],
          trackListStatus: "not_provided_by_source",
        });
      }

      if (path === "/v1/tracks") {
        const query = (url.searchParams.get("q") || "").trim().slice(0, 120);
        const limit = Math.min(100, Math.max(1, Number.parseInt(url.searchParams.get("limit") || "30", 10) || 30));
        const rawCursor = url.searchParams.get("cursor") || "0";
        const offset = Number.parseInt(rawCursor, 10);

        if (!Number.isSafeInteger(offset) || offset < 0) {
          return json({ error: "Invalid cursor." }, 400);
        }

        let statement;
        if (query) {
          statement = env.DB.prepare(
            "SELECT id, title, artist, audio_url, artwork_url, NULL AS duration_seconds, published_at, source_categories_json, mood_tags_json, genre_tags_json, language_tags_json, region_tags_json, trend_tags_json, version_type, artist_source, artist_confidence FROM catalog_tracks WHERE audio_url LIKE 'https://%' AND validation_status != 'excluded' AND (title LIKE ? OR artist LIKE ?) ORDER BY id DESC LIMIT ? OFFSET ?"
          ).bind(`%${query}%`, `%${query}%`, limit + 1, offset);
        } else {
          statement = env.DB.prepare(
            "SELECT id, title, artist, audio_url, artwork_url, NULL AS duration_seconds, published_at, source_categories_json, mood_tags_json, genre_tags_json, language_tags_json, region_tags_json, trend_tags_json, version_type, artist_source, artist_confidence FROM catalog_tracks WHERE audio_url LIKE 'https://%' AND validation_status != 'excluded' ORDER BY id DESC LIMIT ? OFFSET ?"
          ).bind(limit + 1, offset);
        }

        const result = await statement.all();
        const rows = result.results || [];
        const hasMore = rows.length > limit;

        return json({
          items: rows.slice(0, limit).map(trackPayload),
          nextCursor: hasMore ? String(offset + limit) : null,
        });
      }

      const match = path.match(/^\/v1\/tracks\/(\d+)$/);
      if (match) {
        const row = await env.DB.prepare(
          "SELECT id, title, artist, audio_url, artwork_url, NULL AS duration_seconds, published_at, source_categories_json, mood_tags_json, genre_tags_json, language_tags_json, region_tags_json, trend_tags_json, version_type, artist_source, artist_confidence FROM catalog_tracks WHERE id = ? AND audio_url LIKE 'https://%' AND validation_status != 'excluded' LIMIT 1"
        ).bind(Number(match[1])).first();

        if (!row) return json({ error: "Track not found." }, 404);
        return json(trackPayload(row));
      }

      return json({ error: "Not found." }, 404);
    } catch (error) {
      console.error("NavaStream API error:", error);
      return json({ error: "Service temporarily unavailable." }, 503);
    }
  },
};
