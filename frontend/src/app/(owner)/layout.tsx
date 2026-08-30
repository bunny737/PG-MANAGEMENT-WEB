import { BottomNav } from "@/components/shared/BottomNav";
import { SideNav } from "@/components/shared/SideNav";
import { AuthProvider } from "@/features/auth/AuthContext";
import { RoleGuard } from "@/features/auth/RoleGuard";

// Owner + Manager portal — shared shell, nav filtered by permission matrix
// (docs/frontend-plan.md §3.2). Receptionist/Resident/Super Admin each have
// their own route group.
const ALLOWED_ROLES = ["owner", "manager"];

export default function OwnerLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthProvider>
      <RoleGuard allowedRoles={ALLOWED_ROLES}>
        <div className="flex min-h-screen">
          <SideNav />
          <div className="flex-1 pb-20 md:pb-0">{children}</div>
          <BottomNav />
        </div>
      </RoleGuard>
    </AuthProvider>
  );
}
