/**
 * FE-01: configurable production API proxy.
 *
 * The Vercel SPA forwards `/api/*` here; the handler relays the request to
 * the real API origin read from the `API_ORIGIN` environment variable. The
 * old vercel.json baked an ephemeral `trycloudflare.com` quick-tunnel host
 * into the deploy, so every tunnel rotation broke production for everyone;
 * with this proxy the origin is deployment configuration (set it once in
 * the Vercel project settings) instead of code.
 *
 * The `/api` prefix is stripped before forwarding, mirroring the vite dev
 * proxy (`vite.config.ts`), so both environments call the API the same way.
 * Unconfigured deployments answer with an explicit 503 instead of a dead
 * tunnel — an honest failure the status page can show.
 */

export interface ProxyEnv {
  API_ORIGIN?: string;
}

/** Hop-by-hop and derived headers must never be forwarded. */
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

export function resolveApiOrigin(env: ProxyEnv): string | null {
  const raw = (env.API_ORIGIN ?? "").trim().replace(/\/+$/, "");
  if (!raw) {
    return null;
  }
  if (!/^https?:\/\//i.test(raw)) {
    // A scheme-less origin would silently produce invalid request URLs.
    return null;
  }
  return raw;
}

export function apiTargetUrl(requestUrl: string, origin: string): string {
  const url = new URL(requestUrl);
  const incoming = `${url.pathname.replace(/^\/api/, "") || "/"}${url.search}`;
  return `${origin}${incoming}`;
}

function forwardHeaders(headers: Headers): Headers {
  const out = new Headers();
  headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase()) && key.toLowerCase() !== "host") {
      out.set(key, value);
    }
  });
  return out;
}

export async function handleApiProxy(request: Request, env: ProxyEnv): Promise<Response> {
  const origin = resolveApiOrigin(env);
  if (origin === null) {
    return new Response(
      JSON.stringify({
        code: "api_origin_unconfigured",
        message: "API_ORIGIN is not set for this deployment; the API origin is configured in the hosting project settings.",
      }),
      { status: 503, headers: { "content-type": "application/json" } },
    );
  }

  const target = apiTargetUrl(request.url, origin);
  const body =
    request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer();

  const upstream = await fetch(target, {
    method: request.method,
    headers: forwardHeaders(request.headers),
    body,
    redirect: "manual",
  });

  const responseHeaders = forwardHeaders(upstream.headers);
  // The body is surfaced through a fresh Response (and possibly decoded by
  // the runtime), so framing headers from the upstream would lie.
  responseHeaders.delete("content-length");
  responseHeaders.delete("content-encoding");

  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}
