/**
 * Vercel Edge Function: catch-all proxy for /api/* (FE-01).
 *
 * Forwards every /api/* request to the API origin configured via the
 * API_ORIGIN project environment variable. The heavy lifting (origin
 * resolution, prefix stripping, header hygiene, honest 503 when
 * unconfigured) lives in src/lib/apiProxy.ts so it is unit-tested by
 * vitest like the rest of the frontend.
 *
 * Edge runtime keeps SSE (/tutor/conversations/*/messages/stream) flowing
 * as a real stream instead of buffering the whole answer.
 */
import { handleApiProxy } from "../src/lib/apiProxy";

export const config = { runtime: "edge" };

export default async function handler(request: Request): Promise<Response> {
  return handleApiProxy(request, { API_ORIGIN: process.env.API_ORIGIN });
}
