import { AuthProvider } from "@/features/auth/AuthContext";
import { RoleGuard } from "@/features/auth/RoleGuard";

// Super Admin portal. Minimal shell for FE-01a — the real portal (tenants,
// plan-limit config, platform metrics, overrides, docs/frontend-plan.md §3.2)
// is FE-13 scope.
const ALLOWED_ROLES = ["super_admin"];

export default function SuperAdminLayout({
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
