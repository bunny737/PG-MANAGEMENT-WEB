// Liveness for Cloud Run probes and the uptime check (docs/deployment.md). Takes precedence over
// the BFF catch-all; touches nothing upstream, so a Django outage never restarts this service.
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "ok" }, { headers: { "cache-control": "no-store" } });
}
