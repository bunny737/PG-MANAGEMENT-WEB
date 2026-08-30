import { AuthProvider } from "@/features/auth/AuthContext";
import { RoleGuard } from "@/features/auth/RoleGuard";

// Resident portal (primary PWA install target). Minimal shell for FE-01a —
// the real portal (home, invoices, receipts, complaints, visitors, notices,
// docs/frontend-plan.md §3.2) is FE-R1 scope.
const ALLOWED_ROLES = ["resident"];

export default function ResidentLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthProvider>
      <RoleGuard allowedRoles={ALLOWED_ROLES}>{children}</RoleGuard>
    </AuthProvider>
  );
}
