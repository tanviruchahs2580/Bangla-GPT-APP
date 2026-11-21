/**
 * Numeral policy (i18n.ts header, docs/glossary-bn.md): a bare count is a
 * quantity and renders in the active language's digits. The shared Stat
 * primitive printed whatever it was handed, so the teacher dashboard showed
 * Latin "0" tiles inside Bangla copy (Font A fidelity sweep, 2026-11-20).
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Stat } from "../components/ui";
import { setLang } from "../i18n";

afterEach(() => {
  cleanup();
  setLang("bn");
});

describe("Stat follows the numeral policy", () => {
  it("renders a count in Bangla digits under Bangla", () => {
    setLang("bn");
    render(<Stat value={120} label="শিক্ষার্থী" />);
    expect(screen.getByText("১২০")).toBeTruthy();
  });

  it("renders Latin digits under English", () => {
    setLang("en");
    render(<Stat value={120} label="Students" />);
    expect(screen.getByText("120")).toBeTruthy();
  });

  it("passes a non-numeric value through untouched", () => {
    setLang("bn");
    render(<Stat value="—" label="খসড়া" />);
    expect(screen.getByText("—")).toBeTruthy();
  });
});
