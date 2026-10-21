/** AUD-G-11 / G-15 / G-22: numeral policy and form error wiring. */
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Field, NumberInput } from "../components/ui";
import {
  formatNumber,
  localeFor,
  parseDigits,
  toAsciiDigits,
  toBengaliDigits,
} from "../lib/digits";
import { setLang } from "../i18n";

describe("digit conversion", () => {
  it("normalises Bengali digits to ASCII and back", () => {
    expect(toAsciiDigits("১২৩৪৫৬৭৮৯০")).toBe("1234567890");
    expect(toBengaliDigits("1234567890")).toBe("১২৩৪৫৬৭৮৯০");
    expect(toAsciiDigits("শ্রেণি ৬")).toBe("শ্রেণি 6");
    expect(toAsciiDigits("plain text")).toBe("plain text");
  });

  it("parses mixed-script input and reports junk honestly", () => {
    expect(parseDigits("১২")).toBe(12);
    expect(parseDigits("10")).toBe(10);
    expect(parseDigits("৩৫")).toBe(35);
    expect(parseDigits("", 7)).toBe(7);
    expect(parseDigits("abc", 7)).toBe(7);
    expect(Number.isNaN(parseDigits("abc"))).toBe(true);
  });
});

describe("locale-driven display", () => {
  it("follows the UI language, not the browser", () => {
    setLang("bn");
    expect(localeFor()).toBe("bn-BD");
    expect(formatNumber(1234)).toMatch(/[০-৯]/);
    setLang("en");
    expect(localeFor()).toBe("en-US");
    expect(formatNumber(1234)).toBe("1,234");
  });
});

describe("NumberInput", () => {
  it("accepts Bengali digits typed on a Bangla keyboard", () => {
    const onValue = vi.fn();
    render(<NumberInput value={6} onValue={onValue} min={1} max={12} />);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "১০" } });
    expect(onValue).toHaveBeenCalledWith(10);
  });

  it("clamps to the range and uses the fallback for junk", () => {
    const onValue = vi.fn();
    render(
      <NumberInput value={5} onValue={onValue} min={3} max={25} fallback={5} />,
    );
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "৯৯" } });
    expect(onValue).toHaveBeenLastCalledWith(25);
    fireEvent.change(input, { target: { value: "" } });
    expect(onValue).toHaveBeenLastCalledWith(5);
  });
});

describe("Field error wiring (AUD-G-11)", () => {
  it("marks the control invalid and points it at the error text", () => {
    render(
      <Field label="শ্রেণি" htmlFor="cls" error="শ্রেণি দিন">
        <input id="cls" />
      </Field>,
    );
    const input = screen.getByLabelText("শ্রেণি");
    expect(input).toHaveAttribute("aria-invalid", "true");
    const describedBy = input.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy!)).toHaveTextContent(
      "শ্রেণি দিন",
    );
  });

  it("describes the hint instead when there is no error", () => {
    render(
      <Field label="নাম" htmlFor="nm" hint="২ অক্ষরের বেশি">
        <input id="nm" />
      </Field>,
    );
    const input = screen.getByLabelText("নাম");
    expect(input).not.toHaveAttribute("aria-invalid");
    const describedBy = input.getAttribute("aria-describedby");
    expect(document.getElementById(describedBy!)).toHaveTextContent(
      "২ অক্ষরের বেশি",
    );
  });
});
