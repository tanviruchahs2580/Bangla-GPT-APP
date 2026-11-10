/**
 * Server-supplied links are untrusted data, even from our own API.
 *
 * FE-FIX: `SearchBox` navigated straight to `hit.href` from the search
 * response, while `NotificationBell` had always validated its `link` against
 * this allowlist. Two surfaces consuming the same class of field must apply
 * the same trust rule: without it a crafted hit (`javascript:…`, an absolute
 * `https://elsewhere.example/…`, or an unintended route) turns a search result
 * into an open redirect or worse inside an authenticated session. The rule
 * lives here so the next consumer inherits it instead of re-inventing it.
 */
export const UI_PREFIXES = [
  "/student",
  "/parent",
  "/teacher",
  "/admin",
  "/school",
] as const;

/**
 * The path when `href` is an in-app route, otherwise `null`.
 *
 * `startsWith` on a prefix is deliberate: a path like `/student/tutor` passes
 * and a protocol-relative `//evil.example` does not, because it does not start
 * with any prefix. A trailing `/` is treated as the bare prefix so
 * `/student/` does not 404 against the router.
 */
export function uiPathOf(href: string | null | undefined): string | null {
  if (typeof href !== "string") return null;
  const path = href.trim();
  if (!path.startsWith("/")) return null;
  const hit = UI_PREFIXES.find(
    (prefix) => path === prefix || path.startsWith(`${prefix}/`),
  );
  return hit ? path : null;
}
