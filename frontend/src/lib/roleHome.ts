/**
 * Where each role lands after login, and where a route-group guard sends a
 * user who doesn't belong there. Route groups (the `(owner)`, `(resident)`
 * folders under app/) never appear in the URL, so these are real paths.
 *
 * `/reception` and `/admin` are provisional single-page placeholders for
 * this slice (FE-01a) — the real Receptionist portal IA is FE-12 scope and
 * the Super Admin portal is FE-13 scope. `/dashboard` and `/home` match the
 * route map in docs/frontend-plan.md §3.2.
 */
export function roleHome(role: string): string {
  switch (role) {
    case "owner":
    case "manager":
      return "/dashboard";
    case "receptionist":
      return "/reception";
    case "resident":
      return "/home";
    case "super_admin":
      return "/admin";
    default:
      return "/login";
  }
}
