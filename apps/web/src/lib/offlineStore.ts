import type { ChapterContentOut } from "../types";

/**
 * per-chapter offline storage.
 *
 * Browsers use IndexedDB; where it is absent (jsdom tests, exotic WebViews)
 * we fall back to an in-memory map so the offline-copy logic stays testable
 * and the UI degrades gracefully instead of throwing.
 */

export interface OfflineChapter {
  key: string;
  subject: string;
  chapter: string;
  classLevel: number;
  savedAt: string;
  content: ChapterContentOut;
}

export const chapterKey = (
  subject: string,
  chapter: string,
  classLevel: number,
) => `${subject}|${chapter}|${classLevel}`;

const memory = new Map<string, OfflineChapter>();

/** IndexedDB database holding downloaded chapters. */
export const OFFLINE_DB_NAME = "bgpt-offline";

function hasIDB(): boolean {
  return typeof indexedDB !== "undefined";
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(OFFLINE_DB_NAME, 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains("chapters")) {
        req.result.createObjectStore("chapters", { keyPath: "key" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () =>
      reject(
        req.error instanceof Error
          ? req.error
          : new Error(`IndexedDB request failed: ${String(req.error)}`),
      );
  });
}

async function tx<T>(
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore) => IDBRequest,
): Promise<T> {
  const db = await openDb();
  return new Promise<T>((resolve, reject) => {
    const t = db.transaction("chapters", mode);
    const req = run(t.objectStore("chapters"));
    req.onsuccess = () => {
      resolve(req.result as T);
      db.close();
    };
    req.onerror = () => {
      reject(
        req.error instanceof Error
          ? req.error
          : new Error(`IndexedDB transaction failed: ${String(req.error)}`),
      );
      db.close();
    };
  });
}

export async function saveChapter(
  subject: string,
  chapter: string,
  classLevel: number,
  content: ChapterContentOut,
): Promise<OfflineChapter> {
  const rec: OfflineChapter = {
    key: chapterKey(subject, chapter, classLevel),
    subject,
    chapter,
    classLevel,
    savedAt: new Date().toISOString(),
    content,
  };
  if (hasIDB()) {
    await tx<void>("readwrite", (s) => s.put(rec));
  } else {
    memory.set(rec.key, structuredClone(rec));
  }
  return rec;
}

export async function loadChapter(
  subject: string,
  chapter: string,
  classLevel: number,
): Promise<OfflineChapter | null> {
  const key = chapterKey(subject, chapter, classLevel);
  if (hasIDB()) {
    const rec = await tx<OfflineChapter | undefined>("readonly", (s) =>
      s.get(key),
    );
    return rec ?? null;
  }
  return memory.get(key) ?? null;
}

export async function downloadedChapters(): Promise<OfflineChapter[]> {
  if (hasIDB()) {
    const all = await tx<OfflineChapter[]>("readonly", (s) => s.getAll());
    return all;
  }
  return [...memory.values()];
}

export async function deleteChapter(
  subject: string,
  chapter: string,
  classLevel: number,
): Promise<void> {
  const key = chapterKey(subject, chapter, classLevel);
  if (hasIDB()) {
    await tx<void>("readwrite", (s) => s.delete(key));
  } else {
    memory.delete(key);
  }
}

/**
 * Drop every saved chapter — the in-memory fallback and the IndexedDB
 * database (F-036: downloaded chapters are user data and must not outlive
 * logout on a shared device). Best-effort and awaitable: resolves once the
 * database deletion request settles, so sign-out can wait for it.
 */
export async function clearOfflineChapters(): Promise<void> {
  memory.clear();
  if (!hasIDB()) return;
  await new Promise<void>((resolve) => {
    const req = indexedDB.deleteDatabase(OFFLINE_DB_NAME);
    req.onsuccess = () => resolve();
    // A blocked or failed delete cannot be retried usefully here; the in-memory
    // copy is gone and the next save re-creates a clean database.
    req.onerror = () => resolve();
    req.onblocked = () => resolve();
  });
}

/** Network first, saved offline copy second (PASS: offline readable). */
export async function fetchChapterWithOfflineFallback(
  subject: string,
  chapter: string,
  classLevel: number,
  fetchOnline: () => Promise<ChapterContentOut>,
): Promise<{ content: ChapterContentOut; offline: boolean }> {
  try {
    return { content: await fetchOnline(), offline: false };
  } catch (err) {
    const rec = await loadChapter(subject, chapter, classLevel);
    if (rec) return { content: rec.content, offline: true };
    throw err;
  }
}
