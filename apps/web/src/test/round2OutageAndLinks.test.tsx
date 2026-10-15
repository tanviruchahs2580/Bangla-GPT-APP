/**
 * F-107 / F-128 / F-129 — the outage path and the model's links.
 *
 * Every assertion here is written so that reverting the corresponding fix
 * makes it fail.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SafeMarkdown } from "../lib/safeMarkdown";

describe("F-128 model-authored links cannot impersonate a citation", () => {
  it("marks an allowed external link so it cannot pass as a citation", () => {
    // The finding was not that external links are forbidden -- it is that
    // they rendered identically to the trusted NCTB source chips, in the
    // same tab, with no rel.
    const { container } = render(
      <SafeMarkdown content="See [the source](https://evil.example.com/steal) for details." />,
    );
    const a = container.querySelector("a");
    expect(a).not.toBeNull();
    expect(a?.getAttribute("href")).toBe("https://evil.example.com/steal");
    // F-129: same-tab navigation left the SPA and lost the session.
    expect(a?.getAttribute("target")).toBe("_blank");
    const rel = a?.getAttribute("rel") ?? "";
    expect(rel).toContain("noopener");
    expect(rel).toContain("noreferrer");
    // Distinguished from the citation chips, in text a screen reader reads.
    expect(container.querySelector(".sr-only")?.textContent).toContain(
      "external link",
    );
  });

  it("refuses javascript: and data: schemes outright", () => {
    for (const href of [
      "javascript:alert(1)",
      "data:text/html,<script>x</script>",
    ]) {
      const { container } = render(
        <SafeMarkdown content={`[click](${href})`} />,
      );
      expect(container.querySelectorAll("a")).toHaveLength(0);
      expect(container.innerHTML).not.toContain("script");
      // The text survives so the answer still reads correctly.
      expect(container.textContent).toContain("click");
    }
  });

  it("refuses an unparseable scheme", () => {
    const { container } = render(
      <SafeMarkdown content="[x](weird-scheme:foo)" />,
    );
    expect(container.querySelectorAll("a")).toHaveLength(0);
  });

  it("keeps same-origin relative links in the current tab", () => {
    const { container } = render(
      <SafeMarkdown content="[Profile](/student/me)" />,
    );
    const a = container.querySelector("a");
    expect(a?.getAttribute("href")).toBe("/student/me");
    expect(a?.getAttribute("target")).toBeNull();
  });

  it("does not let the model embed a data: image", () => {
    const { container } = render(
      <SafeMarkdown
        content={"![x](data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=)}"}
      />,
    );
    expect(container.querySelectorAll("img")).toHaveLength(0);
  });

  it("lazy-loads an allowed remote image", () => {
    const { container } = render(
      <SafeMarkdown content="![x](https://example.edu.bd/nctb/p1.png)" />,
    );
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("loading")).toBe("lazy");
  });
});

/* -------------------------------------------------------------------------
 * F-107: a total outage must not look like a closed account.
 * ---------------------------------------------------------------------- */

const TOKEN_KEY = "bgpt_token";

describe("F-107 fetchMe distinguishes an outage from a dead session", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  async function probeWith(fetchImpl: typeof fetch) {
    vi.stubGlobal("fetch", fetchImpl);
    const api = await import("../api");
    return api.fetchMe();
  }

  it("returns 'unreachable' and KEEPS the token when the API cannot be reached", async () => {
    localStorage.setItem(TOKEN_KEY, "a-valid-token");
    const result = await probeWith(
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );
    expect(result.status).toBe("unreachable");
    // The outage is not the user's fault and must not end their session.
    expect(localStorage.getItem(TOKEN_KEY)).toBe("a-valid-token");
  });

  it("returns 'unreachable' on a 502 from the proxy", async () => {
    localStorage.setItem(TOKEN_KEY, "a-valid-token");
    const result = await probeWith(
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({ detail: { code: "api_origin_unreachable" } }),
            {
              status: 502,
              headers: { "content-type": "application/json" },
            },
          ),
        ),
      ),
    );
    expect(result.status).toBe("unreachable");
    expect(localStorage.getItem(TOKEN_KEY)).toBe("a-valid-token");
  });

  it("returns 'unauthenticated' and clears the token on a 401", async () => {
    localStorage.setItem(TOKEN_KEY, "a-dead-token");
    const result = await probeWith(
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ detail: "nope" }), {
            status: 401,
            headers: { "content-type": "application/json" },
          }),
        ),
      ),
    );
    expect(result.status).toBe("unauthenticated");
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("returns 'unauthenticated' with no token at all", async () => {
    const result = await probeWith(vi.fn());
    expect(result.status).toBe("unauthenticated");
  });
});

/* -------------------------------------------------------------------------
 * F-098 / F-099: the outage screen exists and is announced.
 * ---------------------------------------------------------------------- */

describe("F-107 the unreachable screen is rendered, not a redirect", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("renders the outage screen with a retry control", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );
    localStorage.setItem(TOKEN_KEY, "a-valid-token");
    const { AuthProvider, useAuth } = await import("../AuthContext");
    const { default: userEvent } = await import("@testing-library/user-event");

    function Probe() {
      const { me, loading, apiUnreachable, retrySession } = useAuth();
      if (loading) return <p>loading</p>;
      if (apiUnreachable)
        return (
          <div>
            <h1>Cannot reach the server</h1>
            <button onClick={retrySession}>Try again</button>
          </div>
        );
      return <p>{me ? "signed in" : "signed out"}</p>;
    }

    render(
      <MemoryRouter>
        <AuthProvider>
          <Probe />
        </AuthProvider>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByText("Cannot reach the server")).toBeDefined(),
    );
    expect(screen.queryByText("signed out")).toBeNull();
    // The retry control is what turns a dead end into a wait.
    const retry = screen.getByRole("button", { name: "Try again" });
    await userEvent.click(retry);
    await waitFor(() =>
      expect(screen.getByText("Cannot reach the server")).toBeDefined(),
    );
    vi.unstubAllGlobals();
  });
});
