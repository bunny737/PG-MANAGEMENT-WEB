import { AuthProvider } from "@/features/auth/AuthContext";
import { RoleGuard } from "@/features/auth/RoleGuard";

// Receptionist portal. Minimal shell for FE-01a — the real portal (visitors
// log + read-only resident lookup, docs/frontend-plan.md §3.2) is FE-12 scope.
const ALLOWED_ROLES = ["receptionist"];

export default function ReceptionLayout({
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
