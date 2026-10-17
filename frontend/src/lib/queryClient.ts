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
    },
    mutations: {
      retry: 0,
    },
  },
});

// Invariant F7: a session purge (logout, cross-role rejection, forced
// re-login) must clear every cached query, not just localStorage.
registerSessionCleanup(async () => {
  await queryClient.cancelQueries();
  queryClient.clear();
});
