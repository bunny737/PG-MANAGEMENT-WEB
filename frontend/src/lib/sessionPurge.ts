"use client";

/**
 * Session purge coordinator (invariant F7 — no tenant data survives logout
 * or an account switch). `clearSession()` in lib/api.ts is the public
 * entrypoint and removes tokens/permissions synchronously *before*
 * anything here is awaited, so no request already in flight can
 * authenticate as the old user once a purge starts. This module holds:
 *
 *   - a registry other modules add their own step to (the query client
 *     clears its cache, each Zustand store resets itself to its initial
 *     state — see their own files for the `registerSessionCleanup` call)
 *   - the two browser-storage sweeps every purge always runs (Cache
 *     Storage, IndexedDB), guarded for environments/browsers without them
 *
 * Every step runs through `Promise.allSettled`, so one rejecting step
 * (e.g. a stuck IndexedDB delete) never skips the rest. Concurrent purges
 * share one in-flight promise; `awaitPendingPurge()` lets `login()`/
 * `loginPhone()` wait for a purge already running (e.g. one started by a
 * 401 that raced the login request) before storing the new tokens, so it
 * can never be undone by a purge that was already on its way.
 */

type CleanupFn = () => void | Promise<void>;

const cleanups = new Set<CleanupFn>();
let pending: Promise<void> | null = null;

/** Registers a cleanup step `clearSession()` runs on every purge. Returns
 * an unregister function (mainly useful for tests). */
export function registerSessionCleanup(fn: CleanupFn): () => void {
  cleanups.add(fn);
  return () => cleanups.delete(fn);
}

/** Resolves once a purge already in flight finishes; resolves immediately
 * if none is running. */
export function awaitPendingPurge(): Promise<void> {
  return pending ?? Promise.resolve();
}

// Caches the service worker (app/sw.ts) fills with build output only — no tenant data — so a
// purge keeps them and the app shell still opens offline afterwards. Everything else (the
// per-user api-* caches, page documents, anything unknown) is deleted.
const TENANT_FREE_CACHE_PREFIXES = ["serwist-precache", "next-static", "app-images"];

async function clearCacheStorage() {
  if (typeof caches === "undefined") return;
  const keys = await caches.keys();
  const doomed = keys.filter((key) => !TENANT_FREE_CACHE_PREFIXES.some((prefix) => key.startsWith(prefix)));
  await Promise.allSettled(doomed.map((key) => caches.delete(key)));
}

function deleteIndexedDb(name: string): Promise<void> {
  return new Promise((resolve) => {
    try {
      const request = indexedDB.deleteDatabase(name);
      request.onsuccess = () => resolve();
      request.onerror = () => resolve(); // best-effort: a locked db is not fatal
      request.onblocked = () => resolve();
    } catch {
      resolve();
    }
  });
}

// Add a name here whenever a feature starts its own IndexedDB database —
// the Safari (pre-2023) fallback below has no databases() to discover them.
const KNOWN_INDEXEDDB_NAMES: string[] = [];

async function clearIndexedDb() {
  if (typeof indexedDB === "undefined") return;
  if (typeof indexedDB.databases === "function") {
    const databases = await indexedDB.databases();
    const names = databases.map((db) => db.name).filter((name): name is string => Boolean(name));
    await Promise.allSettled(names.map(deleteIndexedDb));
    return;
  }
  await Promise.allSettled(KNOWN_INDEXEDDB_NAMES.map(deleteIndexedDb));
}

/** Runs every registered step plus the two built-in browser-storage
 * sweeps. Called by `clearSession()` (lib/api.ts) — use that instead of
 * this directly, since it also clears tokens/permissions first. */
export function runSessionCleanups(): Promise<void> {
  if (pending) return pending;
  const steps: CleanupFn[] = [...cleanups, clearCacheStorage, clearIndexedDb];
  pending = Promise.allSettled(steps.map((fn) => fn()))
    .then((results) => {
      for (const result of results) {
        if (result.status === "rejected") {
          // Best-effort cleanup: log and move on rather than leaving the
          // caller stuck or other steps skipped.
          console.error("[sessionPurge] a cleanup step failed:", result.reason);
        }
      }
    })
    .finally(() => {
      pending = null;
    });
  return pending;
}
