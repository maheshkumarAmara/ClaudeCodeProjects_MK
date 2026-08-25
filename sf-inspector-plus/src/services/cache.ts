import { openDB, type IDBPDatabase } from 'idb';

interface CacheEntry {
  key: string;
  data: unknown;
  orgId: string;
  timestamp: number;
  ttlMs: number;
}

const DB_NAME = 'sf-inspector-plus-cache';
const STORE_NAME = 'responses';
const DB_VERSION = 1;

let dbPromise: Promise<IDBPDatabase> | null = null;

function getDb(): Promise<IDBPDatabase> {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          const store = db.createObjectStore(STORE_NAME, { keyPath: 'key' });
          store.createIndex('orgId', 'orgId');
          store.createIndex('timestamp', 'timestamp');
        }
      },
    });
  }
  return dbPromise;
}

export async function getCached<T>(key: string, orgId: string): Promise<T | null> {
  const db = await getDb();
  const entry = await db.get(STORE_NAME, `${orgId}:${key}`);
  if (!entry) return null;

  const cacheEntry = entry as CacheEntry;
  if (Date.now() - cacheEntry.timestamp > cacheEntry.ttlMs) {
    await db.delete(STORE_NAME, `${orgId}:${key}`);
    return null;
  }

  return cacheEntry.data as T;
}

export async function setCache<T>(
  key: string,
  orgId: string,
  data: T,
  ttlMs: number
): Promise<void> {
  const db = await getDb();
  const entry: CacheEntry = {
    key: `${orgId}:${key}`,
    data,
    orgId,
    timestamp: Date.now(),
    ttlMs,
  };
  await db.put(STORE_NAME, entry);
}

export async function clearCache(orgId?: string): Promise<void> {
  const db = await getDb();
  if (orgId) {
    const keys = await db.getAllKeysFromIndex(STORE_NAME, 'orgId', orgId);
    const tx = db.transaction(STORE_NAME, 'readwrite');
    for (const key of keys) {
      tx.store.delete(key);
    }
    await tx.done;
  } else {
    await db.clear(STORE_NAME);
  }
}

export const CACHE_TTL = {
  OBJECT_DESCRIBE: 30 * 60 * 1000,
  GLOBAL_DESCRIBE: 60 * 60 * 1000,
  PROFILE_DATA: 15 * 60 * 1000,
  LAYOUT_DATA: 30 * 60 * 1000,
} as const;
