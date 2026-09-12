/** UX-001: automated accessibility gate (axe-core, WCAG 2.1 A/AA).

color-contrast is excluded: jsdom cannot compute real styles, so that rule
is verified by the documented manual pass instead (see final audit report).
Serious + critical violations on the public landing page fail the suite.
 */

import axe from "axe-core";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import WelcomePage from "../pages/WelcomePage";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(() => Promise.resolve({})),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  apiBase: "/api",
}));

vi.mock("../api", () => apiMock);

describe("WelcomePage accessibility", () => {
  it("has no serious or critical axe violations", async () => {
    const { container } = render(
      <MemoryRouter>
        <WelcomePage />
      </MemoryRouter>,
    );
    const results = await axe.run(container, {
      runOnly: ["wcag2a", "wcag2aa", "best-practice"],
      rules: { "color-contrast": { enabled: false } },
    });
    const blocking = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(blocking.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  }, 30000);
});
