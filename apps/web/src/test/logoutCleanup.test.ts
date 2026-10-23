/**
 * F-036: logout() removed exactly three keys. The offline chapter copies
 * (IndexedDB), the cached quiz result (sessionStorage) and the app's other
 * persisted user state (lastChapter, low-data flag, teacher default class)
 * survived — so on a shared device the next user inherited the previous
 * child's downloaded chapters, last-open chapter and full last quiz result.
 * The react-query cache must go too, and the wipe must be awaitable so
 * sign-out cannot race it.
 *
 * fontScale is NOT user data: it is a device accessibility preference, the
 * same argument that keeps bgpt_theme and bgpt_lang, so it must survive a
 * sign-out (audit finding — it used to be wiped alongside lastChapter).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { logout, setLogoutCleanup } from "../api";
import { LAST_RESULT_KEY } from "../lib/quizExplain";
import {
  deleteChapter,
  downloadedChapters,
  OFFLINE_DB_NAME,
  saveChapter,
} from "../lib/offlineStore";
import type { ChapterContentOut } from "../types";

const USER_KEYS = [
  "bgpt_token",
  "bgpt_admin_token_backup",
  "bgpt_impersonating",
  "lastChapter",
  "bgpt-lowdata",
  "bgpt_teacher_default_class",
];

function fixture(): ChapterContentOut {
  return {
    subject: "science",
    class_level: 6,
    book: "Science Class 6",
    chapter: "cell",
    sections: [{ section: "What is a cell", text: "Cells are the unit." }],
  };
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
});

afterEach(async () => {
  setLogoutCleanup(null);
  // Drop the IDB stub BEFORE asking the store for its contents (the stub has
  // no open()), then leave the in-memory store empty for the next test.
  vi.unstubAllGlobals();
  for (const rec of await downloadedChapters()) {
    await deleteChapter(rec.subject, rec.chapter, rec.classLevel);
  }
  localStorage.clear();
  sessionStorage.clear();
});

describe("logout clears user data (F-036)", () => {
  it("wipes every user-scoped key, the quiz cache and offline chapters", async () => {
    for (const key of USER_KEYS) localStorage.setItem(key, "user-data");
    localStorage.setItem("bgpt_lang", "en");
    localStorage.setItem("bgpt_theme", "dark");
    localStorage.setItem("fontScale", "1.4");
    sessionStorage.setItem(LAST_RESULT_KEY, JSON.stringify({ score: 92 }));
    await saveChapter("science", "cell", 6, fixture());
    expect(await downloadedChapters()).toHaveLength(1);

    const cacheSpy = vi.fn();
    setLogoutCleanup(cacheSpy);

    await logout();

    for (const key of USER_KEYS) expect(localStorage.getItem(key)).toBeNull();
    expect(sessionStorage.getItem(LAST_RESULT_KEY)).toBeNull();
    expect(await downloadedChapters()).toHaveLength(0);
    // The react-query cache cleaner registered by the app ran, and logout
    // awaited it.
    expect(cacheSpy).toHaveBeenCalledTimes(1);
    // Language, theme and font scale are device preferences, not user data.
    expect(localStorage.getItem("bgpt_lang")).toBe("en");
    expect(localStorage.getItem("bgpt_theme")).toBe("dark");
    expect(localStorage.getItem("fontScale")).toBe("1.4");
  });

  it("requests deletion of the IndexedDB offline database", async () => {
    const deleted: string[] = [];
    vi.stubGlobal("indexedDB", {
      deleteDatabase: (name: string) => {
        deleted.push(name);
        const req = {
          onsuccess: null as (() => void) | null,
          onerror: null as (() => void) | null,
          onblocked: null as (() => void) | null,
        };
        queueMicrotask(() => req.onsuccess?.());
        return req;
      },
    });

    await logout();

    expect(deleted).toEqual([OFFLINE_DB_NAME]);
  });

  it("resolves without touching the keys when nothing was stored", async () => {
    await expect(logout()).resolves.toBeUndefined();
    expect(Object.keys(localStorage)).toHaveLength(0);
  });
});
