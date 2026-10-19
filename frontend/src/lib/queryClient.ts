import { QueryClient } from "@tanstack/react-query";
import { registerSessionCleanup } from "@/lib/sessionPurge";

// One client for the whole app, created once per browser tab. Defaults err
// on the side of a fresh fetch — money and status screens must never show
// a stale cached figure without the caller explicitly opting into a longer
// staleTime for a given query.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: true,
      // Without this React Query never even attempts a fetch while the browser reports
      // offline, so the service worker's cached GETs (the app's read-only offline mode)
      // would never be reached. Retries still pause until the connection is back.
      networkMode: "offlineFirst",
    },
    mutations: {
      retry: 0,
      // The default ("online") PAUSES a mutation made offline and silently REPLAYS it on
      // reconnect — an implicit offline queue for payments and invoices, which the plan
      // forbids (frontend-plan.md §5.1, "Offline writes: none in MVP"). "always" sends it
      // now and lets it fail fast with the normal network error instead.
      networkMode: "always",
    },
  },
});

// Invariant F7: a session purge (logout, cross-role rejection, forced
// re-login) must clear every cached query, not just localStorage.
registerSessionCleanup(async () => {
  await queryClient.cancelQueries();
  queryClient.clear();
});
