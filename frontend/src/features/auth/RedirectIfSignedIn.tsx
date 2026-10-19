"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { firstAllowedRoute } from "@/lib/permissions";
import { ensureFreshSession } from "@/lib/session";

const PORTAL_ROLES = ["owner", "manager", "receptionist"];

/** The installed app opens at /login (manifest start_url). If a valid session already exists,
 * skip the form and go to the first screen this user may open. The session is verified against
 * the API rather than trusted from localStorage, so a stale flag can't bounce back and forth
 * with the proxy's signed-out redirect. */
export function RedirectIfSignedIn() {
  const router = useRouter();

  useEffect(() => {
    if (localStorage.getItem("isLoggedIn") !== "true") return;
    let cancelled = false;
    void ensureFreshSession().then((me) => {
      if (cancelled || !me || !PORTAL_ROLES.includes(me.role)) return;
      router.replace(firstAllowedRoute(me.permissions ?? []));
    });
    return () => {
      cancelled = true;
    };
  }, [router]);

  return null;
}
