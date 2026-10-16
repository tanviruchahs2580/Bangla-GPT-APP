import { describe, expect, it, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { getLang, setLang, t } from "../i18n";
import { PublicLanguageToggle } from "../components/PublicLanguageToggle";

// I18N-12: an anonymous visitor had no way to change the interface language,
// because the only control lived in the signed-in shell. This pins the
// behaviour of the control that now ships on the public pages.
describe("public language toggle", () => {
  beforeEach(() => {
    setLang("bn");
    document.documentElement.setAttribute("lang", "bn");
  });

  afterEach(() => {
    cleanup();
    setLang("bn");
  });

  it("switches the copy and the document language on every click", async () => {
    render(<PublicLanguageToggle />);
    const button = screen.getByRole("button", { name: t("language") });

    expect(document.documentElement.getAttribute("lang")).toBe("bn");
    await userEvent.click(button);
    expect(getLang()).toBe("en");
    expect(document.documentElement.getAttribute("lang")).toBe("en");

    await userEvent.click(button);
    expect(getLang()).toBe("bn");
    expect(document.documentElement.getAttribute("lang")).toBe("bn");
  });
});
