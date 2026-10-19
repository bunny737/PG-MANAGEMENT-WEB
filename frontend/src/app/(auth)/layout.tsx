import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "PropManager - Sign In",
  description: "Access your PG properties, residents, and financials.",
};

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-dvh w-full flex-col bg-surface-page antialiased">
      {children}
    </div>
  );
}
