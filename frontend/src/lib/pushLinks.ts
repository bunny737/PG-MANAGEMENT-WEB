// Maps a push notification's `data.reference` (docs/push-notifications-integration.md §4:
// `invoice:<uuid>`, `payment:<uuid>`, `tenant_trial:<uuid>:<days>`) to the screen it opens.
// Pure and import-free: shared by the service worker (notification tap) and the page
// (foreground toast).

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function pushTargetUrl(reference: string | null | undefined): string {
  const [kind, id] = (reference ?? "").split(":");
  if (kind === "invoice" && UUID.test(id ?? "")) return `/billing/invoices/${id}`;
  if (kind === "payment" && UUID.test(id ?? "")) return `/billing/payments/${id}`;
  // Plan & Billing lives under Settings.
  if (kind === "tenant_trial") return "/settings";
  return "/dashboard";
}
