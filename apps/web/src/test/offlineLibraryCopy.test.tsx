/**
 * Offline-library copy: no machine values in Bangla sentences.
 *
 * FE-FIX (raw machine copy): the card printed the API's subject enum
 * ("science") and Latin binary units ("১২.৪ MiB") — the subject now goes
 * through the same `tSubject` mapping as every other subject label, and the
 * unit NAME is localized while the unit itself stays binary (a storage figure
 * must not read as network speed). The number goes through the interpolation
 * boundary, so it carries the language's digits.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OfflineLibrary } from "../components/OfflineLibrary";
import { formatBytes } from "../lib/fileSize";
import { setLang, t } from "../i18n";

const storeMock = vi.hoisted(() => ({
  downloadedChapters: vi.fn(),
  offlineUsage: vi.fn(),
  deleteChapter: vi.fn(),
}));

vi.mock("../lib/offlineStore", () => storeMock);

const REC = {
  key: "1:science:কোষ:6",
  userId: 1,
  subject: "science",
  chapter: "কোষ",
  classLevel: 6,
  bytes: 1_258_291, // 1.2 MiB
  savedAt: 1,
};

beforeEach(() => {
  vi.clearAllMocks();
  setLang("bn");
  storeMock.downloadedChapters.mockResolvedValue([REC]);
  storeMock.offlineUsage.mockResolvedValue({ bytes: 1_258_291, chapters: 1 });
  storeMock.deleteChapter.mockResolvedValue(undefined);
});

describe("offline library copy", () => {
  it("localizes the subject and the size unit, with Bangla digits", async () => {
    render(<OfflineLibrary userId={1} onOpen={() => {}} />);

    const row = await screen.findByText(/বিজ্ঞান/);
    expect(row.textContent).toContain(t("subjectScience"));
    expect(row.textContent).toContain(formatBytes(REC.bytes));
    // Bangla digits, and the unit spelled in Bangla rather than "MiB".
    expect(row.textContent).toContain("১.২");
    expect(row.textContent).not.toContain("MiB");
    expect(row.textContent).not.toContain("science");
  });

  it("keeps the unit binary and the digits Latin under en", async () => {
    setLang("en");
    render(<OfflineLibrary userId={1} onOpen={() => {}} />);
    const row = await screen.findByText(/Science/);
    expect(row.textContent).toContain("1.2 MiB");
  });
});
