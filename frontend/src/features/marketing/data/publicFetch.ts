import type { ZodType } from "zod";
import { getServerApiBase } from "@/lib/site-config";

export type PublicData<T> =
  | { status: "ok"; data: T }
  // The live request failed; `data` is the last response that did validate.
  | { status: "stale"; data: T }
  | { status: "unavailable" };

const TIMEOUT_MS = 3000;
const REVALIDATE_SECONDS = 300;

// Last response that passed validation, per path. In-process only: it survives
// a backend outage for as long as this server runs, which is the whole promise —
// we never invent data, and we never show data that did not come from the API.
const lastGood = new Map<string, unknown>();

export async function fetchPublic<T>(path: string, schema: ZodType<T>): Promise<PublicData<T>> {
  try {
    const response = await fetch(`${getServerApiBase()}${path}`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(TIMEOUT_MS),
      next: { revalidate: REVALIDATE_SECONDS },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const parsed = schema.parse(await response.json());
    lastGood.set(path, parsed);
    return { status: "ok", data: parsed };
  } catch {
    if (lastGood.has(path)) return { status: "stale", data: lastGood.get(path) as T };
    return { status: "unavailable" };
  }
}

/** Test hook. */
export function resetPublicFetchCache(): void {
  lastGood.clear();
}
