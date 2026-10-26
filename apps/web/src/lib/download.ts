/**
 * Hand a blob to the browser as a download, or open it in a new tab.
 *
 * Auth on this API is header-based, so callers fetch the bytes through the
 * shared client and pass the resulting blob here; a bare `<a href>` to the
 * endpoint would 401.
 *
 * Three call sites grew their own version of this and all three had the same
 * two defects:
 *
 * * the anchor was never attached to the document. A detached anchor's
 *   programmatic click is not followed by every engine;
 * * the object URL was revoked synchronously, on the line after `click()`.
 *   The browser resolves the download asynchronously, so revoking it
 *   immediately can cancel the transfer and the user sees a click that
 *   produced no file — Firefox is the classic case, and it is a race, which
 *   is why it survives testing.
 *
 * The revoke is therefore deferred well past the point the browser has taken
 * the stream. 30 s is a bounded leak of one blob reference (a few MB at most)
 * in exchange for a download that actually lands.
 */
const REVOKE_DELAY_MS = 30_000;

export function downloadBlob(
  blob: Blob,
  filename: string,
  options?: { openInTab?: boolean },
): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  if (options?.openInTab) {
    a.target = "_blank";
    a.rel = "noopener";
  } else {
    a.download = filename;
  }
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
}
