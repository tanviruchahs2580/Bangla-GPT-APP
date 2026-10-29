import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChapterContentOut } from "../types";
import {
  chapterKey,
  clearOfflineChapters,
  deleteChapter,
  downloadedChapters,
  fetchChapterWithOfflineFallback,
  loadChapter,
  MAX_OFFLINE_CHAPTERS,
  OFFLINE_OWNER_KEY,
  saveChapter,
  syncOfflineOwner,
} from "../lib/offlineStore";

// jsdom has no indexedDB, so these exercise the in-memory fallback path —
// the same contract the IndexedDB path implements.

const USER = 11;
const OTHER = 22;

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
  await clearOfflineChapters();
  localStorage.clear();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("chapterKey", () => {
  it("scopes the key to the user who saved the copy", () => {
    expect(chapterKey(USER, "science", "cell", 6)).toBe("11|science|cell|6");
    expect(chapterKey(USER, "science", "cell", 6)).not.toBe(
      chapterKey(OTHER, "science", "cell", 6),
    );
  });
});

describe("save/load/delete", () => {
  it("round-trips a chapter and reports saved state", async () => {
    expect(await loadChapter(USER, "science", "cell", 6)).toBeNull();
    const content = fixture();
    await saveChapter(USER, "science", "cell", 6, content);
    const rec = await loadChapter(USER, "science", "cell", 6);
    expect(rec).not.toBeNull();
    expect(rec?.content).toEqual(content);
    expect(rec?.bytes).toBeGreaterThan(0);
    expect(await downloadedChapters(USER)).toHaveLength(1);
    await deleteChapter(USER, "science", "cell", 6);
    expect(await loadChapter(USER, "science", "cell", 6)).toBeNull();
  });

  it("keeps copies for different class levels apart", async () => {
    await saveChapter(USER, "science", "cell", 6, fixture());
    await saveChapter(USER, "science", "cell", 9, fixture());
    expect(await downloadedChapters(USER)).toHaveLength(2);
    const nine = await loadChapter(USER, "science", "cell", 9);
    expect(nine?.classLevel).toBe(9);
  });

  it("never serves one user's copy to another (shared device)", async () => {
    await saveChapter(USER, "science", "cell", 6, fixture());
    expect(await loadChapter(OTHER, "science", "cell", 6)).toBeNull();
    expect(await downloadedChapters(OTHER)).toHaveLength(0);
    expect(await downloadedChapters(USER)).toHaveLength(1);
  });
});

describe("storage budget", () => {
  it("evicts the oldest copies when the count budget is exceeded", async () => {
    for (let i = 0; i < MAX_OFFLINE_CHAPTERS; i++) {
      await saveChapter(USER, "science", `chapter-${i}`, 6, fixture());
      vi.advanceTimersByTime(60_000);
    }
    const oldest = await loadChapter(USER, "science", "chapter-0", 6);
    expect(
      oldest,
      "oldest copy exists before the budget is hit",
    ).not.toBeNull();
    await saveChapter(USER, "science", "chapter-new", 6, fixture());
    expect(await downloadedChapters(USER)).toHaveLength(MAX_OFFLINE_CHAPTERS);
    expect(await loadChapter(USER, "science", "chapter-0", 6)).toBeNull();
    expect(await loadChapter(USER, "science", "chapter-new", 6)).not.toBeNull();
  });

  it("counts another user's copies against nothing of its own", async () => {
    for (let i = 0; i < MAX_OFFLINE_CHAPTERS; i++) {
      await saveChapter(OTHER, "science", `chapter-${i}`, 6, fixture());
    }
    await saveChapter(USER, "science", "mine", 6, fixture());
    expect(await downloadedChapters(USER)).toHaveLength(1);
    expect(await downloadedChapters(OTHER)).toHaveLength(MAX_OFFLINE_CHAPTERS);
  });
});

describe("syncOfflineOwner", () => {
  it("drops a previous user's copies when the device changes hands", async () => {
    await saveChapter(USER, "science", "cell", 6, fixture());
    expect(localStorage.getItem(OFFLINE_OWNER_KEY)).toBe(String(USER));
    await syncOfflineOwner(OTHER);
    expect(await downloadedChapters(OTHER)).toHaveLength(0);
    expect(await downloadedChapters(USER)).toHaveLength(0);
    expect(localStorage.getItem(OFFLINE_OWNER_KEY)).toBe(String(OTHER));
  });

  it("keeps the same user's copies across sessions", async () => {
    await saveChapter(USER, "science", "cell", 6, fixture());
    await syncOfflineOwner(USER);
    expect(await loadChapter(USER, "science", "cell", 6)).not.toBeNull();
  });
});

describe("fetchChapterWithOfflineFallback", () => {
  it("prefers the network when online", async () => {
    const live = fixture("live");
    await saveChapter(USER, "science", "live", 6, fixture("stale"));
    const res = await fetchChapterWithOfflineFallback(
      USER,
      "science",
      "live",
      6,
      async () => live,
    );
    expect(res).toEqual({ content: live, offline: false });
  });

  it("falls back to the saved copy when the network fails", async () => {
    const saved = fixture("leaf");
    await saveChapter(USER, "science", "leaf", 6, saved);
    const boom = new Error("offline");
    const res = await fetchChapterWithOfflineFallback(
      USER,
      "science",
      "leaf",
      6,
      async () => {
        throw boom;
      },
    );
    expect(res).toEqual({ content: saved, offline: true });
  });

  it("does not fall back to a copy another user saved", async () => {
    await saveChapter(OTHER, "science", "leaf", 6, fixture("leaf"));
    const boom = new Error("offline");
    await expect(
      fetchChapterWithOfflineFallback(USER, "science", "leaf", 6, async () => {
        throw boom;
      }),
    ).rejects.toBe(boom);
  });

  it("rethrows when offline and nothing was saved", async () => {
    const boom = new Error("offline");
    await expect(
      fetchChapterWithOfflineFallback(USER, "science", "never", 6, async () => {
        throw boom;
      }),
    ).rejects.toBe(boom);
  });
});
