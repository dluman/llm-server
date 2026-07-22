// Browser headers to apply to the upstream Zen request. The DO proxy strips
// user-agent/accept/etc. before forwarding to the Worker (curl_cffi manages
// them), so we re-inject a realistic Chrome profile here to avoid looking
// like a headless/datacenter request when the Worker subrequests Zen.
const DEFAULT_BROWSER_HEADERS = {
  "user-agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
  accept: "application/json, text/plain, */*",
  "accept-language": "en-US,en;q=0.9",
  "sec-ch-ua":
    '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
  "sec-ch-ua-mobile": "?0",
  "sec-ch-ua-platform": '"Windows"',
  "sec-fetch-dest": "empty",
  "sec-fetch-mode": "cors",
  "sec-fetch-site": "cross-site",
};

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
      // Drop the relay auth token and hop-by-hop headers so Cloudflare
      // generates correct values for the upstream request.
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

    // Fill in browser headers the client/DO proxy did not forward.
    for (const [key, value] of Object.entries(DEFAULT_BROWSER_HEADERS)) {
      if (!upstreamHeaders.has(key)) {
        upstreamHeaders.set(key, value);
      }
    }

    const upstreamRequest = new Request(upstreamUrl.toString(), {
      method: request.method,
      headers: upstreamHeaders,
      body: request.body,
    });

    const upstreamResponse = await fetch(upstreamRequest);
    console.log(
      "Upstream:",
      request.method,
      upstreamUrl.pathname,
      "->",
      upstreamResponse.status
    );

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: upstreamResponse.headers,
    });
  },
};
