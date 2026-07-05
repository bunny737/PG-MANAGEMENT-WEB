"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { BottomNav } from "@/components/shared/BottomNav";
import { SideNav } from "@/components/shared/SideNav";

export default function OwnerLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [authorized, setAuthorized] = useState(false);

  useEffect(() => {
    const loggedIn = localStorage.getItem("isLoggedIn");
    if (loggedIn !== "true") {
      router.push("/login");
    } else {
      const timer = setTimeout(() => {
        setAuthorized(true);
      }, 0);
      return () => clearTimeout(timer);
    }
  }, [router]);

  if (!authorized) {
    return (
      <div className="flex min-h-screen w-full items-center justify-center bg-surface-page">
        <div className="flex flex-col items-center gap-2">
          <div className="size-8 animate-spin rounded-full border-4 border-accent border-t-transparent" />
          <p className="text-sm text-ink-muted">Checking authentication...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <SideNav />
      <div className="flex-1 pb-20 md:pb-0">{children}</div>
      <BottomNav />
    </div>
  );
}
