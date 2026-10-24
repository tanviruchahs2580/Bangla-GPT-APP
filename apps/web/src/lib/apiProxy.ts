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

//: Time-to-first-byte budget for the upstream call. Headers on a healthy
//: FastAPI origin arrive immediately, so this only fires on a hung or
//: black-holed origin. It is deliberately separate from the body deadline:
//: SSE answers legitimately stream for minutes.
export const UPSTREAM_CONNECT_TIMEOUT_MS = 20_000;
//: Whole-body deadline for NON-streaming responses. Without it a JSON
//: request against an origin that accepts the socket and then goes silent
//: kept the edge invocation (and its billing) alive long after the client's
//: own 20 s timeout had already failed the request. SSE bodies are exempt —
//: the client enforces a stall deadline and a disconnect cancels them.
export const UPSTREAM_TOTAL_TIMEOUT_MS = 60_000;

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

/**
 * Client-supplied forwarding headers must never be relayed either. The API
 * reads the LAST X-Forwarded-For entry as the caller identity when
 * TRUST_PROXY_HEADERS=true; the bundled Caddy overwrites the header, but a
 * Vercel deployment pointing at an origin behind an APPENDING proxy would
 * otherwise let any caller prepend a chosen IP and rotate its rate-limit
 * identity. Stripping here makes the edge the header's only legitimate
 * source (Vercel injects the real client IP downstream of us).
 */
const CLIENT_SUPPLIED_FORWARDING = new Set([
  "x-forwarded-for",
  "x-forwarded-host",
  "x-forwarded-proto",
  "x-real-ip",
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
    const name = key.toLowerCase();
    if (
      !HOP_BY_HOP.has(name) &&
      !CLIENT_SUPPLIED_FORWARDING.has(name) &&
      name !== "host"
    ) {
      out.set(key, value);
    }
  });
  return out;
}

export async function handleApiProxy(
  request: Request,
  env: ProxyEnv,
): Promise<Response> {
  const origin = resolveApiOrigin(env);
  if (origin === null) {
    return new Response(
      JSON.stringify({
        code: "api_origin_unconfigured",
        message:
          "API_ORIGIN is not set for this deployment; the API origin is configured in the hosting project settings.",
      }),
      { status: 503, headers: { "content-type": "application/json" } },
    );
  }

  const target = apiTargetUrl(request.url, origin);
  const body =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.arrayBuffer();

  // Two-phase deadline on the upstream call. The controller's signal also
  // covers the response BODY, so the same timer that bounds time-to-first-
  // byte is re-armed as the whole-body budget once headers arrive (and is
  // cleared when a streaming body finishes), which is what stops a silent
  // origin from pinning an edge invocation after the client gave up.
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const arm = (ms: number) => {
    if (timer !== undefined) clearTimeout(timer);
    timer = setTimeout(() => controller.abort(), ms);
  };
  const disarm = () => {
    if (timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
    }
  };

  let upstream: Response;
  arm(UPSTREAM_CONNECT_TIMEOUT_MS);
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers: forwardHeaders(request.headers),
      body,
      redirect: "manual",
      signal: controller.signal,
    });
  } catch (cause) {
    disarm();
    // The configured origin is unreachable: a stopped container, an expired
    // tunnel, a DNS failure. Without this the rejection escapes the handler
    // and Vercel answers with a bare 500 that names neither the cause nor the
    // host, so a total API outage looks identical to a bug in the app. The
    // unconfigured case above already fails honestly; this is the same
    // treatment for the case that actually happens in production. A deadline
    // that fired gets its own code so the UI can say "try again" instead of
    // implying the origin is down.
    const timedOut = controller.signal.aborted;
    console.error(
      JSON.stringify({
        event: timedOut ? "api_origin_timeout" : "api_origin_unreachable",
        origin,
        path: new URL(request.url).pathname,
        method: request.method,
        cause: cause instanceof Error ? cause.message : String(cause),
      }),
    );
    return new Response(
      JSON.stringify({
        code: timedOut ? "api_origin_timeout" : "api_origin_unreachable",
        message: timedOut
          ? `The API origin accepted the connection but did not respond within ${UPSTREAM_CONNECT_TIMEOUT_MS / 1000}s.`
          : "The API origin is configured but did not respond. This is an upstream outage, not a client error.",
      }),
      { status: 502, headers: { "content-type": "application/json" } },
    );
  }

  const responseHeaders = forwardHeaders(upstream.headers);
  // The body is surfaced through a fresh Response (and possibly decoded by
  // the runtime), so framing headers from the upstream would lie.
  responseHeaders.delete("content-length");
  responseHeaders.delete("content-encoding");

  const contentType = responseHeaders.get("content-type") ?? "";
  const isEventStream = contentType.includes("text/event-stream");
  let responseBody = upstream.body;
  if (responseBody === null) {
    disarm();
  } else if (isEventStream) {
    // SSE is intentionally NOT bounded as a whole: a long generation is a
    // legitimate answer, the client enforces its own stall deadline, and a
    // client disconnect cancels this stream (and with it the upstream
    // fetch). The timer is cleared here and never re-armed for SSE.
    disarm();
  } else {
    arm(UPSTREAM_TOTAL_TIMEOUT_MS);
    responseBody = responseBody.pipeThrough(
      new TransformStream<Uint8Array, Uint8Array>({
        flush: () => disarm(),
      }),
    );
  }

  return new Response(responseBody, {
    status: upstream.status,
    headers: responseHeaders,
  });
}
