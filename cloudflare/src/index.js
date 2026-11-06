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
      "access-control-allow-methods": "GET, OPTIONS",
      "access-control-allow-headers": "Content-Type",
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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\\/+$/, "") || "/";

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET, OPTIONS",
          "access-control-allow-headers": "Content-Type",
          "access-control-max-age": "86400",
        },
      });
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

      const match = path.match(/^\\/v1\\/tracks\\/(\\d+)$/);
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
