/**
 * Pure permission check against the `permissions[]` list the backend returns
 * from `GET /api/v1/auth/me/` (see `apps/core/roles.py::permissions_for`).
 *
 * Kept framework-free (no React) so it's trivial to unit test in isolation
 * and so it can't accidentally grow a role-name special case — every check
 * goes through the permission matrix, never a hardcoded role list
 * (invariant F8, docs/frontend-plan.md).
 */
export function hasPermission(permissions: string[], permission: string): boolean {
  return permissions.includes(permission);
}
