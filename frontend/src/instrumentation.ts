import { assertLaunchReady } from "@/lib/site-config.validation";

// Startup gate: a production server with placeholder company identity or a
// half-configured app link refuses to boot instead of publishing broken legal /
// contact pages. Staging deploys opt out with SITE_ENV=staging.
export function register() {
  if (process.env.NEXT_RUNTIME === "nodejs" && process.env.NODE_ENV === "production") {
    assertLaunchReady(process.env);
  }
}
