import type { ChapterContentOut } from "../types";

/**
 * S1.13: per-chapter offline storage.
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

function hasIDB(): boolean {
  return typeof indexedDB !== "undefined";
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("bgpt-offline", 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains("chapters")) {
        req.result.createObjectStore("chapters", { keyPath: "key" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
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
      reject(req.error);
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

/** Network first, saved offline copy second (S1.13 PASS: offline readable). */
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
