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

function trackPayload(row) {
  return {
    id: String(row.id),
    title: row.title || "عنوان نامشخص",
    artist: row.artist || "هنرمند نامشخص",
    audioUrl: row.audio_url,
    artworkUrl: row.artwork_url,
    durationSeconds: row.duration_seconds,
    publishedAt: row.published_at,
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
        const result = await env.DB.prepare(
          "SELECT COUNT(*) AS published_tracks, MAX(published_at) AS latest_publication FROM tracks WHERE telegram_message_id IS NOT NULL AND audio_url LIKE 'https://%'"
        ).first();

        return json({
          ok: true,
          service: "navastream-api",
          publishedTracks: result?.published_tracks || 0,
          latestPublication: result?.latest_publication || null,
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
            "SELECT id, title, artist, audio_url, artwork_url, duration_seconds, published_at FROM tracks WHERE telegram_message_id IS NOT NULL AND audio_url LIKE 'https://%' AND (title LIKE ? OR artist LIKE ?) ORDER BY COALESCE(published_at, created_at) DESC, id DESC LIMIT ? OFFSET ?"
          ).bind(`%${query}%`, `%${query}%`, limit + 1, offset);
        } else {
          statement = env.DB.prepare(
            "SELECT id, title, artist, audio_url, artwork_url, duration_seconds, published_at FROM tracks WHERE telegram_message_id IS NOT NULL AND audio_url LIKE 'https://%' ORDER BY COALESCE(published_at, created_at) DESC, id DESC LIMIT ? OFFSET ?"
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
          "SELECT id, title, artist, audio_url, artwork_url, duration_seconds, published_at FROM tracks WHERE id = ? AND telegram_message_id IS NOT NULL AND audio_url LIKE 'https://%' LIMIT 1"
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
