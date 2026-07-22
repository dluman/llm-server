export default {
  async fetch(request, env, ctx) {
    const token = request.headers.get("X-Relay-Token");
    if (!token || token !== env.RELAY_TOKEN) {
      return new Response("Unauthorized", { status: 401 });
    }

    const url = new URL(request.url);
    const upstreamUrl = new URL(
      url.pathname + url.search,
      "https://opencode.ai/zen"
    );

    const upstreamHeaders = new Headers();
    for (const [key, value] of request.headers) {
      const lower = key.toLowerCase();
      // Drop the relay auth token and hop-by-hop headers so curl/Cloudflare
      // generate correct values for the upstream request.
      if (
        lower === "x-relay-token" ||
        lower === "host" ||
        lower === "connection" ||
        lower === "keep-alive" ||
        lower === "content-length" ||
        lower === "transfer-encoding"
      ) {
        continue;
      }
      upstreamHeaders.set(key, value);
    }

    const upstreamRequest = new Request(upstreamUrl.toString(), {
      method: request.method,
      headers: upstreamHeaders,
      body: request.body,
    });

    const upstreamResponse = await fetch(upstreamRequest);

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: upstreamResponse.headers,
    });
  },
};
