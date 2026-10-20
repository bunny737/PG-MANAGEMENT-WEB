/** Any of these opens the property bed grid (GET /properties/{id}/layout/); mirrors LAYOUT_ENTRY_PERMISSIONS
 * in backend apps/properties/views.py. Used for the property detail page, Vacancies and the dashboard shortcut.
 *
 * Kept out of lib/permissions.ts on purpose: that file is a client module, and a server component (the
 * Vacancies route) importing a plain value from a client module receives a client reference, not the array. */
export const LAYOUT_ENTRY_PERMISSIONS = [
  "view_property_features",
  "manage_rooms_beds",
  "manage_admissions",
  "manage_allocations",
] as const;
