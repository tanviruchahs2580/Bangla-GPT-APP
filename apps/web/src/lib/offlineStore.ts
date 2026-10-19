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
  await writeWithQuotaRecovery(() =>
    hasIDB()
      ? tx<void>("readwrite", (s) => s.put(rec))
      : // Map.set returns the map; the recovery helper expects Promise<void>.
        Promise.resolve<void>(void memory.set(rec.key, structuredClone(rec))),
  );
  return rec;
}

/** Copies kept when a full device forces a prune (newest first). */
export const OFFLINE_KEEP_ON_QUOTA = 5;

/**
 * A chapter could not be stored because the device is out of room.
 *
 * AUD-G-17: this used to be indistinguishable from success — IndexedDB
 * rejects the write, the caller swallowed it, and the reader saw "ডাউনলোড
 * হয়েছে" for a chapter that was never stored. The UI turns this into an
 * explicit message.
 */
export class OfflineQuotaError extends Error {
  constructor(message = "offline storage quota exceeded") {
    super(message);
    this.name = "OfflineQuotaError";
  }
}

/** True for the quota rejections browsers actually throw. */
export function isQuotaExceeded(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  const name = (err as { name?: string }).name ?? "";
  const code = (err as { code?: number }).code;
  const message = String((err as { message?: string }).message ?? "");
  return (
    name === "QuotaExceededError" ||
    name === "NS_ERROR_DOM_QUOTA_REACHED" ||
    code === 22 ||
    /quota|storage is full/i.test(message)
  );
}

/** What the browser says is left, or null when it will not say. */
export async function storageEstimate(): Promise<{
  usage: number;
  quota: number;
} | null> {
  try {
    const estimate = await navigator.storage?.estimate?.();
    if (!estimate?.quota) return null;
    return { usage: estimate.usage ?? 0, quota: estimate.quota };
  } catch {
    return null;
  }
}

/** Drop the oldest copies, keeping the newest `keep`. */
export async function pruneOldestChapters(keep: number): Promise<number> {
  const all = await downloadedChapters();
  if (all.length <= keep) return 0;
  const oldest = [...all]
    .sort((a, b) => a.savedAt.localeCompare(b.savedAt))
    .slice(0, all.length - keep);
  for (const rec of oldest) {
    await deleteChapter(rec.subject, rec.chapter, rec.classLevel);
  }
  return oldest.length;
}

/**
 * Run a write; if storage is full, free the oldest copies and try once more.
 * Exported so the recovery path is testable without filling a real disk.
 */
export async function writeWithQuotaRecovery<T>(
  write: () => Promise<T>,
  keep: number = OFFLINE_KEEP_ON_QUOTA,
): Promise<T> {
  try {
    return await write();
  } catch (err) {
    if (!isQuotaExceeded(err)) throw err;
    const freed = await pruneOldestChapters(keep);
    if (freed === 0) throw new OfflineQuotaError();
    try {
      return await write();
    } catch (retryErr) {
      throw isQuotaExceeded(retryErr) ? new OfflineQuotaError() : retryErr;
    }
  }
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
