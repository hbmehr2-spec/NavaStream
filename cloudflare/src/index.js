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
  ]) {
    const value = track[field];
    if (value !== null && value !== undefined &&
        (typeof value !== "string" || value.length > maxLength)) return false;
  }

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
            "INSERT INTO catalog_tracks (title, artist, audio_url, artwork_url, source_url, external_id, release_date, validation_status, source_categories_json, mood_tags_json, genre_tags_json, language_tags_json, region_tags_json, trend_tags_json, version_type, artist_source, artist_confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(source_url) DO UPDATE SET title = excluded.title, artist = excluded.artist, audio_url = excluded.audio_url, artwork_url = excluded.artwork_url, external_id = excluded.external_id, release_date = excluded.release_date, validation_status = excluded.validation_status, source_categories_json = excluded.source_categories_json, mood_tags_json = excluded.mood_tags_json, genre_tags_json = excluded.genre_tags_json, language_tags_json = excluded.language_tags_json, region_tags_json = excluded.region_tags_json, trend_tags_json = excluded.trend_tags_json, version_type = excluded.version_type, artist_source = excluded.artist_source, artist_confidence = excluded.artist_confidence"
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
