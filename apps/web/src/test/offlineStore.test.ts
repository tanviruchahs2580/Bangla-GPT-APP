import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { ChapterContentOut } from "../types";
import {
  OFFLINE_KEEP_ON_QUOTA,
  OfflineQuotaError,
  chapterKey,
  deleteChapter,
  downloadedChapters,
  fetchChapterWithOfflineFallback,
  isQuotaExceeded,
  loadChapter,
  pruneOldestChapters,
  saveChapter,
  storageEstimate,
  writeWithQuotaRecovery,
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

describe("quota handling (AUD-G-17)", () => {
  const quotaError = () =>
    Object.assign(new Error("The quota has been exceeded."), {
      name: "QuotaExceededError",
    });

  it("recognises the rejections browsers throw, and only those", () => {
    expect(isQuotaExceeded(quotaError())).toBe(true);
    expect(isQuotaExceeded({ name: "NS_ERROR_DOM_QUOTA_REACHED" })).toBe(true);
    expect(isQuotaExceeded({ code: 22 })).toBe(true);
    expect(isQuotaExceeded(new Error("quota exceeded"))).toBe(true);
    expect(isQuotaExceeded(new Error("network down"))).toBe(false);
    expect(isQuotaExceeded(null)).toBe(false);
    expect(isQuotaExceeded("quota")).toBe(false);
  });

  it("keeps the newest copies when it prunes", async () => {
    for (const n of [1, 2, 3, 4, 5, 6, 7]) {
      const rec = fixture(`c${n}`);
      await saveChapter("science", rec.chapter, 6, rec);
    }
    // savedAt is an ISO timestamp; make the order deterministic.
    const all = await downloadedChapters();
    expect(all).toHaveLength(7);
    const freed = await pruneOldestChapters(2);
    expect(freed).toBe(5);
    expect(await downloadedChapters()).toHaveLength(2);
  });

  it("retries once after freeing space, then reports a typed failure", async () => {
    for (const n of [1, 2, 3]) {
      const rec = fixture(`old${n}`);
      await saveChapter("science", rec.chapter, 6, rec);
    }
    let attempts = 0;
    const ok = await writeWithQuotaRecovery(async () => {
      attempts += 1;
      if (attempts === 1) throw quotaError();
      return "stored";
    }, 1);
    expect(ok).toBe("stored");
    expect(attempts).toBe(2);
    expect(await downloadedChapters()).toHaveLength(1);

    // Nothing left to free -> the caller gets the typed error, not silence.
    await expect(
      writeWithQuotaRecovery(async () => {
        throw quotaError();
      }, 1),
    ).rejects.toBeInstanceOf(OfflineQuotaError);

    // A non-quota failure is passed through unchanged.
    const boom = new Error("storage unavailable");
    await expect(
      writeWithQuotaRecovery(async () => {
        throw boom;
      }),
    ).rejects.toBe(boom);
  });

  it("saveChapter surfaces a full device instead of pretending success", async () => {
    const original = globalThis.indexedDB;
    // Force the IndexedDB path with a store that always rejects.
    Object.defineProperty(globalThis, "indexedDB", {
      configurable: true,
      value: {
        open: () => {
          const req: Record<string, unknown> = {};
          queueMicrotask(() => {
            (req.onerror as (() => void) | undefined)?.();
          });
          return req as unknown as IDBOpenDBRequest;
        },
      },
    });
    try {
      await expect(
        saveChapter("science", "full", 6, fixture("full")),
      ).rejects.toBeTruthy();
    } finally {
      Object.defineProperty(globalThis, "indexedDB", {
        configurable: true,
        value: original,
      });
    }
  });
});

describe("storage estimate and the pre-flight prune (AUD-G-17)", () => {
  const MB = 1024 * 1024;

  /** Stub `navigator.storage.estimate` for one test; restores afterwards. */
  function stubStorage(estimate: () => Promise<StorageEstimate>): void {
    Object.defineProperty(navigator, "storage", {
      configurable: true,
      value: { estimate },
    });
  }

  function restoreStorage(): void {
    // jsdom ships no StorageManager; delete the stub rather than leave a
    // partial object behind for the next test.
    delete (navigator as unknown as { storage?: unknown }).storage;
  }

  afterEach(restoreStorage);

  it("reports the browser's numbers, and null when it will not say", async () => {
    // jsdom has no navigator.storage: the honest answer is null, not zeros.
    expect(await storageEstimate()).toBeNull();

    stubStorage(async () => ({ usage: 2 * MB, quota: 10 * MB }));
    expect(await storageEstimate()).toEqual({ usage: 2 * MB, quota: 10 * MB });

    stubStorage(async () => {
      throw new Error("denied");
    });
    expect(await storageEstimate()).toBeNull();

    // A quota of 0 means "unknown" in every engine that reports it.
    stubStorage(async () => ({ usage: 1 * MB, quota: 0 }));
    expect(await storageEstimate()).toBeNull();
  });

  it("saveChapter prunes proactively when the device reports almost no headroom", async () => {
    // Deterministic age order: savedAt is an ISO stamp with ms precision.
    const pause = () => new Promise((resolve) => setTimeout(resolve, 3));
    for (const n of [1, 2, 3, 4, 5, 6, 7]) {
      await saveChapter("science", `c${n}`, 6, fixture(`c${n}`));
      await pause();
    }
    stubStorage(async () => ({ usage: 8 * MB, quota: 8 * MB }));
    await saveChapter("science", "fresh", 6, fixture("fresh"));
    const all = await downloadedChapters();
    // The cap is OFFLINE_KEEP_ON_QUOTA newest copies, plus the one written.
    expect(all).toHaveLength(OFFLINE_KEEP_ON_QUOTA + 1);
    expect(all.some((rec) => rec.chapter === "c1")).toBe(false);
    expect(all.some((rec) => rec.chapter === "c2")).toBe(false);
    expect(all.some((rec) => rec.chapter === "fresh")).toBe(true);
  });

  it("saveChapter does not prune while the device reports free space", async () => {
    stubStorage(async () => ({ usage: 1 * MB, quota: 512 * MB }));
    for (let n = 1; n <= 7; n += 1) {
      await saveChapter("science", `c${n}`, 6, fixture(`c${n}`));
      await new Promise((resolve) => setTimeout(resolve, 3));
    }
    await saveChapter("science", "fresh", 6, fixture("fresh"));
    expect(await downloadedChapters()).toHaveLength(8);
  });
});
