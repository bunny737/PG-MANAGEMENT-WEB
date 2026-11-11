import Script from "next/script";
import { getGaMeasurementId } from "@/lib/site-config";

const GA_LOAD_STRATEGY = "lazyOnload" as const;

// Google tag (gtag.js) for the PUBLIC marketing pages only. It is mounted from the (marketing)
// layout, never the root layout, so the signed-in app (tenant data) is not tracked.
// Renders nothing unless GA_MEASUREMENT_ID is set, so dev, CI and staging stay out of the
// property's numbers. Next applies the per-request CSP nonce to <Script> automatically, and
// 'strict-dynamic' lets the nonce'd loader pull in gtag.js (lib/csp.ts).
export function GoogleAnalytics() {
  const id = getGaMeasurementId();
  if (!id) return null;
  return (
    <>
      <Script src={`https://www.googletagmanager.com/gtag/js?id=${id}`} strategy={GA_LOAD_STRATEGY} />
      <Script id="ga-init" strategy={GA_LOAD_STRATEGY}>
        {`window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('js', new Date());
gtag('config', '${id}');`}
      </Script>
    </>
  );
}
