import { beforeEach, describe, expect, it } from "vitest";
import type { ChapterContentOut } from "../types";
import {
  chapterKey,
  deleteChapter,
  downloadedChapters,
  fetchChapterWithOfflineFallback,
  loadChapter,
  saveChapter,
} from "../lib/offlineStore";

// jsdom has no indexedDB, so these exercise the in-memory fallback path —
// the same contract the IndexedDB path implements.

function fixture(chapter = "cell"): ChapterContentOut {
  return {
    subject: "science",
    class_level: 6,
    book: "Science Class 6",
    chapter,
    sections: [
      { section: "What is a cell", text: "Cells are the basic unit of life." },
    ],
  };
}

beforeEach(async () => {
  for (const rec of await downloadedChapters()) {
    await deleteChapter(rec.subject, rec.chapter, rec.classLevel);
  }
});

describe("chapterKey", () => {
  it("joins subject, chapter and class with pipes", () => {
    expect(chapterKey("science", "cell", 6)).toBe("science|cell|6");
  });
});

describe("save/load/delete", () => {
  it("round-trips a chapter and reports saved state", async () => {
    expect(await loadChapter("science", "cell", 6)).toBeNull();
    const content = fixture();
    await saveChapter("science", "cell", 6, content);
    const rec = await loadChapter("science", "cell", 6);
    expect(rec).not.toBeNull();
    expect(rec?.content).toEqual(content);
    expect(await downloadedChapters()).toHaveLength(1);
    await deleteChapter("science", "cell", 6);
    expect(await loadChapter("science", "cell", 6)).toBeNull();
  });

  it("keeps copies for different class levels apart", async () => {
    await saveChapter("science", "cell", 6, fixture());
    await saveChapter("science", "cell", 9, fixture());
    expect(await downloadedChapters()).toHaveLength(2);
    const nine = await loadChapter("science", "cell", 9);
    expect(nine?.classLevel).toBe(9);
  });
});

describe("fetchChapterWithOfflineFallback", () => {
  it("prefers the network when online", async () => {
    const live = fixture("live");
    await saveChapter("science", "live", 6, fixture("stale"));
    const res = await fetchChapterWithOfflineFallback(
      "science",
      "live",
      6,
      async () => live,
    );
    expect(res).toEqual({ content: live, offline: false });
  });

  it("falls back to the saved copy when the network fails", async () => {
    const saved = fixture("leaf");
    await saveChapter("science", "leaf", 6, saved);
    const boom = new Error("offline");
    const res = await fetchChapterWithOfflineFallback(
      "science",
      "leaf",
      6,
      async () => {
        throw boom;
      },
    );
    expect(res).toEqual({ content: saved, offline: true });
  });

  it("rethrows when offline and nothing was saved", async () => {
    const boom = new Error("offline");
    await expect(
      fetchChapterWithOfflineFallback("science", "never", 6, async () => {
        throw boom;
      }),
    ).rejects.toBe(boom);
  });
});
