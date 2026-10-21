/**
 * Copy-to-clipboard for the chat answer action (AUD-G-10).
 *
 * `navigator.clipboard` needs a secure context, so a page served over plain
 * HTTP on a LAN address (a school showing the app locally) does not have it.
 * The legacy `execCommand("copy")` path covers that case; when both fail the
 * caller is told the copy did not happen instead of the button silently doing
 * nothing.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Permission denied or insecure context: fall through to the legacy path.
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "-1000px";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand?.("copy") ?? false;
    area.remove();
    return ok;
  } catch {
    return false;
  }
}
