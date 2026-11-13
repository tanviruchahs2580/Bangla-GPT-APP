/**
 * X-02: the canonical return-path policy for bounces to /login.
 *
 * Before this module there were three producers of "/login" redirects with
 * two different contracts: AuthContext's 401 bounce carried ?next= (the
 * destination survived), while RequireAuth's token-missing and
 * session-refused navigations went to bare /login (the destination died
 * with the redirect race). One helper now serves every producer, so a quiz
 * finish or a mid-edit note survives an expired session regardless of which
 * redirect wins the boot race.
 *
 * Open-redirect hardening mirrors the original safeNextPath contract: only
 * same-origin relative paths are ever preserved — an absolute URL, a
 * protocol-relative one (//…), or a backslash variant (/\…) fails the check
 * and falls back to the plain login path. An open redirect on a government
 * login page is a phishing primitive.
 */

/** True for a same-origin relative path; false for anything else. */
function isInternalPath(path: string): boolean {
  return (
    path.startsWith("/") && !path.startsWith("//") && !path.startsWith("/\\")
  );
}

/**
 * The redirect target for a bounce to the login page: `/login?next=<here>`
 * with the current pathname and query preserved, or plain `/login` when
 * there is no deep link worth restoring (root, or already on /login).
 */
export function loginReturnPath(): string {
  const here = `${window.location.pathname}${window.location.search}`;
  // "/" has nothing to preserve — the router sends it to the role home
  // anyway — and a next=/login target would loop.
  if (!isInternalPath(here) || here.startsWith("/login") || here === "/") {
    return "/login";
  }
  return `/login?next=${encodeURIComponent(here)}`;
}

/**
 * The ?next= destination read back from a `/login?next=…` URL after
 * re-login. Same-origin relative paths only — null means "no safe
 * destination, go to the role home".
 */
export function safeNextPath(search: string): string | null {
  try {
    const next = new URLSearchParams(search).get("next");
    if (!next || !isInternalPath(next)) return null;
    return next;
  } catch {
    return null;
  }
}
