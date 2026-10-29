import type { ChapterContentOut } from "../types";

/**
 * per-chapter offline storage.
 *
 * Browsers use IndexedDB; where it is absent (jsdom tests, exotic WebViews)
 * we fall back to an in-memory map so the offline-copy logic stays testable
 * and the UI degrades gracefully instead of throwing.
 *
 * PWA-03: every record is scoped to the user who saved it, carries its byte
 * size, and lives inside a bounded budget (count and bytes) with
 * oldest-first eviction, so a low-storage Android device cannot fill up and a
 * copy of a previous student's chapter is never readable by the next user on
 * a shared device.
 */

export interface OfflineChapter {
  key: string;
  userId: number;
  subject: string;
  chapter: string;
  classLevel: number;
  savedAt: string;
  /** UTF-8 byte length of the serialized content, for the storage budget. */
  bytes: number;
  content: ChapterContentOut;
}

export interface OfflineUsage {
  count: number;
  bytes: number;
  maxCount: number;
  maxBytes: number;
}

/** Key shape: user-scoped, so two students on one device never collide. */
export const chapterKey = (
  userId: number,
  subject: string,
  chapter: string,
  classLevel: number,
) => `${userId}|${subject}|${chapter}|${classLevel}`;

/** IndexedDB database holding downloaded chapters. */
export const OFFLINE_DB_NAME = "bgpt-offline";
const OFFLINE_DB_VERSION = 2;
const STORE = "chapters";

/**
 * Budget: a class-6 chapter serializes to tens of kilobytes, so 20 chapters
 * stay well under 4 MB — comfortable on a 32 GB budget Android while small
 * enough that the copies cannot crowd out the rest of the origin's storage.
 */
export const MAX_OFFLINE_CHAPTERS = 20;
export const MAX_OFFLINE_BYTES = 4_000_000;

/** Device marker: which user's copies the IndexedDB currently holds. */
export const OFFLINE_OWNER_KEY = "bgpt_offline_owner";

/** The copy cannot be stored: the chapter alone exceeds the budget. */
export class OfflineStorageFullError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "OfflineStorageFullError";
  }
}

const memory = new Map<string, OfflineChapter>();

function hasIDB(): boolean {
  return typeof indexedDB !== "undefined";
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(OFFLINE_DB_NAME, OFFLINE_DB_VERSION);
    req.onupgradeneeded = (event) => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: "key" });
      }
      if (event.oldVersion > 0 && event.oldVersion < 2) {
        // Version 1 keys had no user id: attributing those records to
        // whoever logs in next would hand a previous student's chapter to
        // the new user on a shared device, so they are dropped.
        req.transaction?.objectStore(STORE).clear();
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
    const t = db.transaction(STORE, mode);
    const req = run(t.objectStore(STORE));
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

function isQuotaError(err: unknown): boolean {
  return (
    err instanceof DOMException &&
    (err.name === "QuotaExceededError" || err.code === 22)
  );
}

function byteLength(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value)).length;
}

/** A record is only served when its shape survived storage intact. */
function isUsableRecord(value: unknown): value is OfflineChapter {
  if (!value || typeof value !== "object") return false;
  const rec = value as Partial<OfflineChapter>;
  return (
    typeof rec.key === "string" &&
    typeof rec.userId === "number" &&
    typeof rec.subject === "string" &&
    typeof rec.chapter === "string" &&
    typeof rec.classLevel === "number" &&
    typeof rec.savedAt === "string" &&
    typeof rec.bytes === "number" &&
    !!rec.content &&
    Array.isArray(rec.content.sections)
  );
}

async function allRecords(): Promise<OfflineChapter[]> {
  if (hasIDB()) {
    const all = await tx<OfflineChapter[]>("readonly", (s) => s.getAll());
    return all.filter(isUsableRecord);
  }
  return [...memory.values()];
}

async function putRecord(rec: OfflineChapter): Promise<void> {
  if (hasIDB()) {
    await tx<void>("readwrite", (s) => s.put(rec));
  } else {
    memory.set(rec.key, structuredClone(rec));
  }
}

async function deleteKeys(keys: string[]): Promise<void> {
  for (const key of keys) {
    if (hasIDB()) {
      await tx<void>("readwrite", (s) => s.delete(key));
    } else {
      memory.delete(key);
    }
  }
}

/**
 * Oldest-first eviction until the incoming record fits the budget. The record
 * being saved is never an eviction candidate. Throws when the chapter alone
 * is larger than the whole budget — silently dropping it would leave the
 * button saying "saved" with nothing stored.
 */
async function makeRoom(rec: OfflineChapter): Promise<void> {
  if (rec.bytes > MAX_OFFLINE_BYTES) {
    throw new OfflineStorageFullError(
      `chapter needs ${rec.bytes} bytes; budget is ${MAX_OFFLINE_BYTES}`,
    );
  }
  const owned = (await allRecords())
    .filter((r) => r.userId === rec.userId && r.key !== rec.key)
    .sort((a, b) => a.savedAt.localeCompare(b.savedAt));
  let count = owned.length + 1;
  let bytes = owned.reduce((sum, r) => sum + r.bytes, rec.bytes);
  const evicted: string[] = [];
  for (const candidate of owned) {
    if (count <= MAX_OFFLINE_CHAPTERS && bytes <= MAX_OFFLINE_BYTES) break;
    count -= 1;
    bytes -= candidate.bytes;
    evicted.push(candidate.key);
  }
  await deleteKeys(evicted);
}

export async function saveChapter(
  userId: number,
  subject: string,
  chapter: string,
  classLevel: number,
  content: ChapterContentOut,
): Promise<OfflineChapter> {
  const rec: OfflineChapter = {
    key: chapterKey(userId, subject, chapter, classLevel),
    userId,
    subject,
    chapter,
    classLevel,
    savedAt: new Date().toISOString(),
    bytes: byteLength(content),
    content,
  };
  await makeRoom(rec);
  try {
    await putRecord(rec);
  } catch (err) {
    // The browser can hold a quota of its own below our budget; free the
    // oldest copies once and retry before giving up.
    if (!isQuotaError(err)) throw err;
    const owned = (await allRecords())
      .filter((r) => r.userId === userId && r.key !== rec.key)
      .sort((a, b) => a.savedAt.localeCompare(b.savedAt));
    await deleteKeys(
      owned
        .slice(0, Math.max(1, Math.ceil(owned.length / 2)))
        .map((r) => r.key),
    );
    await putRecord(rec);
  }
  try {
    localStorage.setItem(OFFLINE_OWNER_KEY, String(userId));
  } catch {
    /* the marker is an optimisation; a missing one only means no prune */
  }
  return rec;
}

export async function loadChapter(
  userId: number,
  subject: string,
  chapter: string,
  classLevel: number,
): Promise<OfflineChapter | null> {
  const key = chapterKey(userId, subject, chapter, classLevel);
  if (hasIDB()) {
    const rec = await tx<OfflineChapter | undefined>("readonly", (s) =>
      s.get(key),
    );
    if (rec && !isUsableRecord(rec)) {
      // A corrupted copy must not be served; dropping it lets the next save
      // succeed and the network path take over meanwhile.
      await deleteKeys([key]);
      return null;
    }
    return rec ?? null;
  }
  return memory.get(key) ?? null;
}

/** Newest first: the manage-downloads list shows the most recent on top. */
export async function downloadedChapters(
  userId?: number,
): Promise<OfflineChapter[]> {
  const all = await allRecords();
  return all
    .filter((r) => userId === undefined || r.userId === userId)
    .sort((a, b) => b.savedAt.localeCompare(a.savedAt));
}

export async function offlineUsage(userId: number): Promise<OfflineUsage> {
  const owned = await downloadedChapters(userId);
  return {
    count: owned.length,
    bytes: owned.reduce((sum, r) => sum + r.bytes, 0),
    maxCount: MAX_OFFLINE_CHAPTERS,
    maxBytes: MAX_OFFLINE_BYTES,
  };
}

export async function deleteChapter(
  userId: number,
  subject: string,
  chapter: string,
  classLevel: number,
): Promise<void> {
  await deleteKeys([chapterKey(userId, subject, chapter, classLevel)]);
}

/**
 * Drop every saved chapter of every user — the in-memory fallback and the
 * IndexedDB database (F-036: downloaded chapters are user data and must not
 * outlive logout on a shared device). Best-effort and awaitable: resolves once
 * the database deletion request settles, so sign-out can wait for it.
 */
export async function clearOfflineChapters(): Promise<void> {
  memory.clear();
  try {
    localStorage.removeItem(OFFLINE_OWNER_KEY);
  } catch {
    /* storage unavailable: the wipe below is what matters */
  }
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

/**
 * Called once per signed-in session (AuthContext): when the device marker
 * says the stored copies belong to someone else, they are deleted before the
 * new user can open the reader. This covers the crash / undetected-logout
 * path that clearOfflineChapters() cannot see.
 */
export async function syncOfflineOwner(userId: number): Promise<void> {
  try {
    const marker = localStorage.getItem(OFFLINE_OWNER_KEY);
    if (marker === String(userId)) return;
    if (marker !== null) {
      const foreign = (await allRecords()).filter((r) => r.userId !== userId);
      await deleteKeys(foreign.map((r) => r.key));
    }
    localStorage.setItem(OFFLINE_OWNER_KEY, String(userId));
  } catch {
    /* best-effort: a failed prune must not block the session */
  }
}

/** Network first, saved offline copy second (PASS: offline readable). */
export async function fetchChapterWithOfflineFallback(
  userId: number,
  subject: string,
  chapter: string,
  classLevel: number,
  fetchOnline: () => Promise<ChapterContentOut>,
): Promise<{ content: ChapterContentOut; offline: boolean }> {
  try {
    return { content: await fetchOnline(), offline: false };
  } catch (err) {
    const rec = await loadChapter(userId, subject, chapter, classLevel);
    if (rec) return { content: rec.content, offline: true };
    throw err;
  }
}
