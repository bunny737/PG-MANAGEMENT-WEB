// Invariant F7 for the service worker's API cache. The worker can't read the httpOnly auth
// cookies, so the page tags every API request with a non-secret tenant+user scope and the
// worker keeps one cache per scope (and caches nothing for untagged requests). A purge that
// is missed — offline logout, a crashed tab — then still can't show user A's data to user B.
//
// Imported by both the page (lib/api.ts) and the worker (app/sw.ts): keep it free of
// anything that touches `window` at import time.

export const CACHE_SCOPE_HEADER = "X-Cache-Scope";

/** `tenant_user` for the signed-in user, or null when there is no session to scope to. */
export function getCacheScope(): string | null {
  if (typeof localStorage === "undefined") return null;
  try {
    const raw = localStorage.getItem("currentUser");
    if (!raw) return null;
    const me = JSON.parse(raw) as { id?: string; tenant_id?: string; tenant?: { id?: string } };
    const tenant = me.tenant_id ?? me.tenant?.id;
    return me.id ? `${tenant ?? "platform"}_${me.id}` : null;
  } catch {
    return null;
  }
}
