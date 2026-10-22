// API client. Every call goes to this app's own origin (`/api/v1/...`), where the BFF
// proxy (app/api/[...path]/route.ts, docs/frontend-plan.md §3.1) attaches the JWT from an
// httpOnly cookie and forwards to Django. The browser never sees or stores a token; the
// only auth state kept client-side is the non-secret UX hints in localStorage (login flag,
// role, permissions) that lib/session.ts revalidates from /auth/me/.

import { readLocaleCookie, writeLocaleCookie } from "@/i18n/locale";
import { CACHE_SCOPE_HEADER, getCacheScope } from "@/lib/cacheScope";
import { awaitPendingPurge, registerSessionCleanup, runPreLogoutSteps, runSessionCleanups } from "@/lib/sessionPurge";

// Same-origin: the BFF proxy owns the Django origin (INTERNAL_API_URL, server-side only).
const API_BASE_URL = "";

/** Permission codes from /auth/me/ — read through `usePermissions()`. */
export const PERMISSIONS_KEY = "userPermissions";
/** Fired on any 403 so the session layer can refresh permissions right away. */
export const PERMISSION_DENIED_EVENT = "permission-denied";
/** sessionStorage prefix for a feature selection that failed to save after a property was created. */
export const FEATURE_DRAFT_PREFIX = "featureDraft:";

export type ApiErrorBody = Record<string, unknown>;

function extractErrorMessage(status: number, body: ApiErrorBody): string {
  if (typeof body.detail === "string" && body.detail.trim()) return body.detail;
  if (typeof body.message === "string" && body.message.trim()) return body.message;
  if (typeof body.error === "string" && body.error.trim()) return body.error;

  if (Array.isArray(body.non_field_errors) && typeof body.non_field_errors[0] === "string") {
    return body.non_field_errors[0];
  }
  if (typeof body.non_field_errors === "string" && body.non_field_errors.trim()) {
    return body.non_field_errors;
  }

  for (const key of Object.keys(body)) {
    const val = body[key];
    if (Array.isArray(val) && typeof val[0] === "string") {
      return `${key}: ${val[0]}`;
    }
    if (typeof val === "string" && val.trim()) {
      return `${key}: ${val}`;
    }
  }

  return status > 0 ? `Request failed with status ${status}` : "Request failed";
}

export class ApiError extends Error {
  status: number;
  body: ApiErrorBody;

  constructor(status: number, body: ApiErrorBody) {
    super(extractErrorMessage(status, body));
    this.status = status;
    this.body = body;
    this.name = "ApiError";
  }

  /** The backend's machine-readable error code (always upper-case, e.g. `EMAIL_NOT_VERIFIED`).
   * Branch on this, never on `detail` text, which is translated. Field-level validation errors
   * only carry the generic `INVALID`. */
  get code(): string | undefined {
    const code = this.body.code;
    return typeof code === "string" && code ? code.toUpperCase() : undefined;
  }

  /** First message for a given field, if the backend returned a field-level validation error. */
  fieldError(field: string): string | undefined {
    const value = this.body[field];
    if (Array.isArray(value) && typeof value[0] === "string") return value[0];
    if (typeof value === "string") return value;
    return undefined;
  }
}

export function isUUID(str: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(str);
}

// Registered as a purge step (not called from clearSession directly) so it is part of the
// pending purge that login() awaits — a slow logout can then never clear a fresh login's cookies.
// Pre-logout steps (push unsubscribe, capped at a few seconds) run first because they still
// need the session cookie; offline or failing, the logout request is still sent.
registerSessionCleanup(async () => {
  try {
    await runPreLogoutSteps();
    await fetch("/api/auth/logout", { method: "POST", keepalive: true });
  } catch {
    // Offline: local state is already gone; the cookies are replaced by the next login.
  }
});

/**
 * Purges the session (invariant F7 — no tenant data survives logout or an
 * account switch). Permissions/session keys are removed and
 * `session-changed` is dispatched synchronously, before anything is
 * awaited. It then runs the server-side cookie clear (registered above)
 * and awaits every registered cleanup
 * step (query cache, Zustand stores, Cache Storage, IndexedDB — see
 * lib/sessionPurge.ts) through `Promise.allSettled`, so one failing step
 * never skips the rest. Callers should `await` this before navigating
 * away, so the next screen never renders with the old session's cache.
 */
export async function clearSession() {
  localStorage.removeItem("isLoggedIn");
  localStorage.removeItem("userRole");
  localStorage.removeItem("userName");
  localStorage.removeItem("currentUser");
  localStorage.removeItem(PERMISSIONS_KEY);
  for (const key of Object.keys(sessionStorage)) {
    if (key.startsWith(FEATURE_DRAFT_PREFIX)) sessionStorage.removeItem(key);
  }
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("session-changed"));
  }
  await runSessionCleanups();
}

async function parseErrorBody(res: Response): Promise<ApiErrorBody> {
  try {
    return await res.json();
  } catch {
    return { detail: res.statusText || `HTTP ${res.status}` };
  }
}

/** Lets the service worker file this response under the signed-in user's own cache (see lib/cacheScope.ts). */
function tagCacheScope(headers: Headers) {
  const scope = getCacheScope();
  if (scope) headers.set(CACHE_SCOPE_HEADER, scope);
}

interface ApiFetchOptions extends RequestInit {
  /** Skip the "401 means the session is dead" handling (login itself, where 401 is bad credentials). */
  skipAuth?: boolean;
}

export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const isFormData = options.body instanceof FormData;
  const headers = new Headers(options.headers);
  if (!isFormData && options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const currentLocale = typeof window !== "undefined" ? readLocaleCookie() : "en";
  if (!headers.has("Accept-Language")) {
    headers.set("Accept-Language", currentLocale);
  }
  tagCacheScope(headers);
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(0, { detail: "Could not reach the server. Please check your network connection." });
  }

  // The proxy already refreshed the token if it could; a 401 here means the session is over.
  if (res.status === 401 && !options.skipAuth) {
    await clearSession();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError(401, { detail: "Session expired" });
  }

  if (!res.ok) {
    if (res.status === 403 && typeof window !== "undefined") {
      // The Owner may have just changed this user's access: lib/session.ts re-fetches
      // /auth/me/ immediately (bypassing its focus throttle) so gated UI updates now.
      window.dispatchEvent(new Event(PERMISSION_DENIED_EVENT));
    }
    throw new ApiError(res.status, await parseErrorBody(res));
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/**
 * Like `apiFetch`, but also returns the response headers and status —
 * for endpoints a plain JSON body doesn't fully describe, such as
 * `Idempotent-Replayed: true` on a replayed `POST /payments/` or
 * `POST /expenses/`. Shares `apiFetch`'s auth/401-refresh handling by
 * delegating the actual request to a private helper isn't worth the
 * duplication here, so this re-implements the same flow; keep the two in
 * sync if that logic changes.
 */
export async function apiFetchWithMeta<T>(
  path: string,
  options: ApiFetchOptions = {}
): Promise<{ data: T; headers: Headers; status: number }> {
  const isFormData = options.body instanceof FormData;
  const headers = new Headers(options.headers);
  if (!isFormData && options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const currentLocale = typeof window !== "undefined" ? readLocaleCookie() : "en";
  if (!headers.has("Accept-Language")) {
    headers.set("Accept-Language", currentLocale);
  }
  tagCacheScope(headers);
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  } catch {
    throw new ApiError(0, { detail: "Could not reach the server. Please check your network connection." });
  }

  // The proxy already refreshed the token if it could; a 401 here means the session is over.
  if (res.status === 401 && !options.skipAuth) {
    await clearSession();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError(401, { detail: "Session expired" });
  }

  if (!res.ok) {
    if (res.status === 403 && typeof window !== "undefined") {
      window.dispatchEvent(new Event(PERMISSION_DENIED_EVENT));
    }
    throw new ApiError(res.status, await parseErrorBody(res));
  }

  const data = res.status === 204 ? (undefined as T) : ((await res.json()) as T);
  return { data, headers: res.headers, status: res.status };
}

/**
 * Downloads a binary export (CSV/XLSX/PDF) and returns it as a blob plus
 * the filename from `Content-Disposition`, for `/exports/*` and the PDF
 * receipt (`?filetype=pdf`). Callers turn the blob into an anchor-click
 * download or a `navigator.share` call.
 */
export async function apiDownload(
  path: string
): Promise<{ blob: Blob; filename: string }> {
  const headers = new Headers();
  const currentLocale = typeof window !== "undefined" ? readLocaleCookie() : "en";
  headers.set("Accept-Language", currentLocale);
  tagCacheScope(headers);

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { headers });
  } catch {
    throw new ApiError(0, { detail: "Could not reach the server. Please check your network connection." });
  }

  if (res.status === 401) {
    await clearSession();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError(401, { detail: "Session expired" });
  }

  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorBody(res));
  }

  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const filename = match?.[1] ?? "download";
  return { blob: await res.blob(), filename };
}

/** POSTs credentials to one of the login route handlers, which store the token pair in
 * httpOnly cookies and return only the /auth/me/ payload, then records the session hints. */
async function completeLogin(routePath: string, credentials: Record<string, string>) {
  await awaitPendingPurge();
  const me = await apiFetch<CurrentUser>(routePath, {
    method: "POST",
    body: JSON.stringify(credentials),
    skipAuth: true,
  });
  localStorage.setItem("isLoggedIn", "true");
  localStorage.setItem("userRole", me.role);
  localStorage.setItem(PERMISSIONS_KEY, JSON.stringify(me.permissions ?? []));
  localStorage.setItem("userName", `${me.first_name ?? ''} ${me.last_name ?? ''}`.trim());
  localStorage.setItem("currentUser", JSON.stringify(me));
  const effectiveLang = me.language_code || me.tenant?.default_language || "en";
  writeLocaleCookie(effectiveLang);
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("session-changed"));
  }
  return me;
}

export function login(email: string, password: string) {
  return completeLogin("/api/auth/login", { email, password });
}

export function loginPhone(phone: string, password: string) {
  return completeLogin("/api/auth/login-phone", { phone, password });
}

/** Asks Django to email a sign-in code. The reply is the same whether or not the address can
 * sign in with a code, so success here never means "registered". Issues no tokens, so it goes
 * through the generic proxy. */
export async function requestEmailOtp(email: string) {
  await apiFetch<{ detail: string }>("/api/v1/auth/otp/email/request/", {
    method: "POST",
    body: JSON.stringify({ email }),
    skipAuth: true,
  });
}

export function loginEmailOtp(email: string, code: string) {
  return completeLogin("/api/auth/login-email-otp", { email, code });
}

export interface SignupPayload {
  business_name: string;
  first_name: string;
  last_name: string;
  email: string;
  phone: string | null;
  password: string;
  language_code: string;
}

/** Creates the tenant + Owner and emails a verification link. Issues no tokens (the owner signs
 * in after verifying), so it goes through the generic proxy. */
export async function signup(payload: SignupPayload) {
  await apiFetch<{ detail: string }>("/api/v1/auth/signup/", {
    method: "POST",
    body: JSON.stringify(payload),
    skipAuth: true,
  });
}

/** Confirms the address from an emailed link. Never signs the user in. Any 400 means the link is
 * invalid or expired. */
export async function verifyEmail(token: string) {
  await apiFetch<{ detail: string }>("/api/v1/auth/verify-email/", {
    method: "POST",
    body: JSON.stringify({ token }),
    skipAuth: true,
  });
}

/** Asks for a new verification link. The reply is the same whether or not the address is
 * registered or already verified, so success never means "registered". */
export async function resendVerification(email: string) {
  await apiFetch<{ detail: string }>("/api/v1/auth/resend-verification/", {
    method: "POST",
    body: JSON.stringify({ email }),
    skipAuth: true,
  });
}

/** Asks for a password-reset link. The reply is the same whether or not the address is
 * registered, so success never means "registered". */
export async function requestPasswordReset(email: string) {
  await apiFetch<{ detail: string }>("/api/v1/auth/password-reset/", {
    method: "POST",
    body: JSON.stringify({ email }),
    skipAuth: true,
  });
}

/** Sets a new password from an emailed link (`uid` + `token`; also how staff invites set their
 * first password). Never signs the user in. A 400 with a `token` field means the link is dead. */
export async function confirmPasswordReset(payload: { uid: string; token: string; new_password: string }) {
  await apiFetch<{ detail: string }>("/api/v1/auth/password-reset/confirm/", {
    method: "POST",
    body: JSON.stringify(payload),
    skipAuth: true,
  });
}

/** Changes the signed-in user's password. Django ends every session when it changes, so the
 * route handler installs the replacement token pair in the httpOnly cookies; the caller stays
 * signed in and never sees a token. */
export async function changePassword(currentPassword: string, newPassword: string) {
  await apiFetch<{ ok: boolean }>("/api/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

export interface PropertyImage {
  id: string;
  image: string;
  order: number;
}

export interface PropertyPayload {
  name: string;
  property_type: string;
  gender_preference?: string;
  address_line: string;
  city: string;
  state: string;
  pincode?: string;
  country?: string;
  contact_number: string;
  contact_email?: string;
  latitude?: number | null;
  longitude?: number | null;
}

export interface Property extends PropertyPayload {
  id: string;
  status: string;
  gender_preference?: string;
  pincode?: string;
  latitude?: number | null;
  longitude?: number | null;
  buildings_count: number;
  floors_count: number;
  rooms_count: number;
  beds_count: number;
  occupancy_percent: number;
  images: PropertyImage[];
}

export interface Building {
  id: string;
  property: string;
  name: string;
  order: number;
  floors_count: number;
  rooms_count: number;
  occupancy_percent: number;
  created_at: string;
  updated_at: string;
}

export interface Floor {
  id: string;
  building: string;
  name: string;
  order: number;
  rooms_count: number;
  occupancy_percent: number;
  created_at: string;
  updated_at: string;
}

export function listProperties() {
  return apiFetch<Property[] | { results: Property[] }>("/api/v1/properties/").then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function getProperty(id: string) {
  if (!isUUID(id)) return Promise.reject(new ApiError(404, { detail: "Property not found" }));
  return apiFetch<Property>(`/api/v1/properties/${id}/`);
}

export function createProperty(payload: PropertyPayload) {
  return apiFetch<Property>("/api/v1/properties/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateProperty(id: string, payload: Partial<PropertyPayload>) {
  if (!isUUID(id)) return Promise.reject(new ApiError(404, { detail: "Property not found" }));
  return apiFetch<Property>(`/api/v1/properties/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export interface PropertySettings {
  id: string;
  room_transfer_rent_timing: "next_billing_cycle" | "immediate";
  late_payment_penalty_type: "none" | "fixed" | "percentage";
  /** Decimal string (₹ for fixed, % for percentage); null when no penalty is set. */
  penalty_value: string | null;
  penalty_grace_days: number;
  penalty_applies_to: "full_invoice" | "outstanding_balance";
  penalty_compounding: "one_time" | "monthly";
  created_at: string;
  updated_at: string;
}

export type PropertySettingsPayload = Partial<Omit<PropertySettings, "id" | "created_at" | "updated_at">>;

export function getPropertySettings(propertyId: string) {
  if (!isUUID(propertyId)) return Promise.reject(new ApiError(404, { detail: "Property not found" }));
  return apiFetch<PropertySettings>(`/api/v1/properties/${propertyId}/settings/`);
}

export function updatePropertySettings(propertyId: string, payload: PropertySettingsPayload) {
  if (!isUUID(propertyId)) return Promise.reject(new ApiError(404, { detail: "Property not found" }));
  return apiFetch<PropertySettings>(`/api/v1/properties/${propertyId}/settings/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function uploadPropertyImage(propertyId: string, file: File) {
  if (!isUUID(propertyId)) return Promise.reject(new ApiError(400, { detail: "Invalid property ID" }));
  const formData = new FormData();
  formData.append("image", file);
  return apiFetch<PropertyImage>(`/api/v1/properties/${propertyId}/images/`, {
    method: "POST",
    body: formData,
  });
}

export function deletePropertyImage(propertyId: string, imageId: string) {
  if (!isUUID(propertyId) || !isUUID(imageId)) return Promise.reject(new ApiError(400, { detail: "Invalid ID" }));
  return apiFetch<void>(`/api/v1/properties/${propertyId}/images/${imageId}/`, {
    method: "DELETE",
  });
}

export function listBuildings(propertyId: string) {
  if (!isUUID(propertyId)) return Promise.reject(new ApiError(404, { detail: "Property not found" }));
  return apiFetch<Building[] | { results: Building[] }>(`/api/v1/buildings/?property=${propertyId}`).then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function getBuilding(buildingId: string) {
  if (!isUUID(buildingId)) return Promise.reject(new ApiError(404, { detail: "Building not found" }));
  return apiFetch<Building>(`/api/v1/buildings/${buildingId}/`);
}

export function createBuilding(payload: { property: string; name: string; order?: number; number_of_floors?: number }) {
  return apiFetch<Building>("/api/v1/buildings/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteBuilding(buildingId: string) {
  if (!isUUID(buildingId)) return Promise.reject(new ApiError(404, { detail: "Building not found" }));
  return apiFetch<void>(`/api/v1/buildings/${buildingId}/`, {
    method: "DELETE",
  });
}

export function listFloors(buildingId: string) {
  if (!isUUID(buildingId)) return Promise.reject(new ApiError(404, { detail: "Building not found" }));
  return apiFetch<Floor[] | { results: Floor[] }>(`/api/v1/floors/?building=${buildingId}`).then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function createFloor(payload: { building: string; name: string; order?: number }) {
  return apiFetch<Floor>("/api/v1/floors/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteFloor(floorId: string) {
  if (!isUUID(floorId)) return Promise.reject(new ApiError(404, { detail: "Floor not found" }));
  return apiFetch<void>(`/api/v1/floors/${floorId}/`, {
    method: "DELETE",
  });
}

export function getFloor(floorId: string) {
  if (!isUUID(floorId)) return Promise.reject(new ApiError(404, { detail: "Floor not found" }));
  return apiFetch<Floor>(`/api/v1/floors/${floorId}/`);
}

export interface Room {
  id: string;
  floor: string;
  room_number: string;
  sharing_type: number;
  category: "ac" | "non_ac";
  rack_rate_with_food: string;
  rack_rate_without_food: string;
  status: "available" | "occupied" | "reserved" | "maintenance";
  current_occupancy: number;
  bed_capacity: number;
  beds?: Bed[];
  created_at: string;
  updated_at: string;
}

export type BedAvailability = "available" | "occupied" | "reserved" | "maintenance";

export interface Bed {
  id: string;
  room: string;
  bed_number: string;
  rack_rate_with_food_override: string | null;
  rack_rate_without_food_override: string | null;
  effective_rate_with_food: string;
  effective_rate_without_food: string;
  status: BedAvailability;
  /** D9/F8 — the only statuses a plain PATCH may move this bed to right
   * now; the client never infers this itself. Empty for `occupied`. */
  allowed_transitions: BedAvailability[];
  reserved_for?: string | null;
  reserved_until?: string | null;
  current_occupant?: {
    id: string;
    first_name: string;
    last_name: string;
    full_name: string;
    email: string;
    phone: string;
    status: string;
    joining_date: string | null;
    rent?: string;
    initials: string;
  } | null;
  history?: Array<{
    resident: string;
    term: string;
    moveIn: string;
    moveOut: string;
    rate?: string;
    initials: string;
  }>;
  created_at: string;
  updated_at: string;
}

export function listRooms(floorId: string) {
  if (!isUUID(floorId)) return Promise.reject(new ApiError(404, { detail: "Floor not found" }));
  return apiFetch<Room[] | { results: Room[] }>(`/api/v1/rooms/?floor=${floorId}`).then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function getRoom(roomId: string) {
  if (!isUUID(roomId)) return Promise.reject(new ApiError(404, { detail: "Room not found" }));
  return apiFetch<Room>(`/api/v1/rooms/${roomId}/`);
}

export interface CreateRoomPayload {
  floor: string;
  room_number: string;
  sharing_type: number;
  category: "ac" | "non_ac";
  rack_rate_with_food: string;
  rack_rate_without_food: string;
  /** Create the room's beds in the same transaction (all-or-nothing against the plan bed limit). */
  auto_create_beds?: boolean;
}

export function createRoom(payload: CreateRoomPayload) {
  return apiFetch<Room>("/api/v1/rooms/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteRoom(roomId: string) {
  if (!isUUID(roomId)) return Promise.reject(new ApiError(404, { detail: "Room not found" }));
  return apiFetch<void>(`/api/v1/rooms/${roomId}/`, {
    method: "DELETE",
  });
}

export function listBeds(roomId: string) {
  if (!isUUID(roomId)) return Promise.reject(new ApiError(404, { detail: "Room not found" }));
  return apiFetch<Bed[] | { results: Bed[] }>(`/api/v1/beds/?room=${roomId}`).then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function getBed(bedId: string) {
  if (!isUUID(bedId)) return Promise.reject(new ApiError(404, { detail: "Bed not found" }));
  return apiFetch<Bed>(`/api/v1/beds/${bedId}/`);
}

export function updateBed(bedId: string, payload: Partial<Bed>) {
  if (!isUUID(bedId)) return Promise.reject(new ApiError(404, { detail: "Bed not found" }));
  return apiFetch<Bed>(`/api/v1/beds/${bedId}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteBed(bedId: string) {
  return apiFetch<void>(`/api/v1/beds/${bedId}/`, { method: "DELETE" });
}

// --- Property layout (D2; apps/properties/layout.py) ---

export interface LayoutBedCounts {
  total: number;
  occupied: number;
  reserved: number;
  maintenance: number;
  available: number;
  occupancy_rate: number | null;
}

export interface LayoutResident {
  id: string;
  name: string;
  phone: string;
  status: string;
  on_notice: boolean;
  notice_date: string | null;
  expected_vacate_date: string | null;
  is_temporary: boolean;
}

export type LayoutPaymentStatus = "paid" | "upcoming" | "due" | "overdue" | "no_invoice";

export interface LayoutPayment {
  status: LayoutPaymentStatus;
  period_balance: string;
  overdue_balance: string;
}

export interface LayoutBed {
  id: string;
  bed_number: string;
  availability: BedAvailability;
  allowed_transitions: BedAvailability[];
  reserved_for: { id: string; name: string | null } | null;
  reserved_until: string | null;
  rack_rate_with_food: string;
  rack_rate_without_food: string;
  resident: LayoutResident | null;
  payment: LayoutPayment | null;
}

export interface LayoutRoom {
  id: string;
  room_number: string;
  sharing_type: number;
  category: string;
  status: string;
  rack_rate_with_food: string;
  rack_rate_without_food: string;
  counts: LayoutBedCounts;
  beds: LayoutBed[];
}

export interface LayoutFloor {
  id: string;
  name: string;
  order: number;
  counts: LayoutBedCounts;
  rooms: LayoutRoom[];
}

export interface LayoutBuilding {
  id: string;
  name: string;
  order: number;
  counts: LayoutBedCounts;
  floors: LayoutFloor[];
}

export interface LayoutFinance {
  outstanding_total: string;
  overdue_total: string;
  open_invoice_count: number;
  residents_with_balance_count: number;
  occupied_beds_with_balance_count: number;
}

export interface PropertyLayout {
  property: { id: string; name: string };
  period: string;
  as_of: string;
  due_soon_days: number;
  counts: LayoutBedCounts;
  finance: LayoutFinance | null;
  buildings: LayoutBuilding[];
  redacted: string[];
}

export function getPropertyLayout(propertyId: string, period?: string) {
  return apiFetch<PropertyLayout>(`/api/v1/properties/${propertyId}/layout/${buildQuery({ period })}`);
}

/** D6 (GET /residents/{id}/, detail only) — apps/residents/finance.py. */
export interface ResidentFinanceCurrentPeriodInvoice {
  id: string;
  period_start: string;
  period_end: string;
  total: string;
  paid: string;
  balance: string;
  due_date: string;
  status: InvoiceStatus;
  is_overdue: boolean;
}

export interface ResidentFinance {
  current_period: {
    period: string;
    invoices: ResidentFinanceCurrentPeriodInvoice[];
    total: string;
    paid: string;
    balance: string;
    status: "no_invoice" | "paid" | "partially_paid" | "unpaid" | "overdue";
    has_draft: boolean;
  };
  outstanding_total: string;
  overdue_total: string;
  prior_outstanding: string;
  last_payment_date: string | null;
}

export interface Resident {
  id: string;
  property: string;
  status: "inquiry" | "reserved" | "active" | "notice_period" | "vacated" | "absconded" | "blacklisted" | "inactive";
  first_name: string;
  last_name: string;
  gender: string;
  date_of_birth: string | null;
  phone: string;
  email: string;
  permanent_address: string;
  current_address: string;
  emergency_contact_name: string;
  emergency_contact_relation: string;
  emergency_contact_phone: string;
  aadhaar_number: string;
  /** Absolute URL of the uploaded file, or null. */
  aadhaar_document?: string | null;
  pan_number: string;
  pan_document?: string | null;
  passport_number: string;
  employee_id: string;
  student_id: string;
  /** "Room {n}" / "Not Allocated" — a display string, not a raw room number. */
  unit?: string;
  /** The building name, or "" when unallocated. */
  block?: string;
  move_in_date?: string;
  /** Present only with view_finance. */
  contracted_rent?: string | null;
  /** Present only with view_finance. */
  billing_mode?: string | null;
  food_preference?: string | null;
  joining_date?: string | null;
  /** Present only with view_finance or manage_deposits. */
  security_deposit_amount?: string | null;
  advance_amount?: string | null;
  advance_refundable?: boolean | null;
  room_number?: string | null;
  bed_number?: string | null;
  created_at: string;
  updated_at: string;
  /** Detail only (GET /residents/{id}/): present with view_finance, else
   * null and "finance" is listed in `redacted`. */
  finance?: ResidentFinance | null;
  redacted?: string[];
}

export interface Admission {
  id: string;
  resident: string;
  bed: string;
  joining_date: string;
  billing_mode: "monthly" | "weekly" | "daily";
  expected_stay_duration: string;
  contracted_sharing_type: number;
  contracted_room_category: string;
  food_preference: "with_food" | "without_food";
  contracted_rent: string;
  advance_amount: string;
  advance_collected_date: string | null;
  advance_mode: string;
  created_at: string;
  updated_at: string;
}

export function listResidents(propertyId?: string, status?: string, search?: string) {
  if (propertyId && !isUUID(propertyId)) return Promise.reject(new ApiError(404, { detail: "Property not found" }));
  let url = "/api/v1/residents/";
  const params = new URLSearchParams();
  if (propertyId) params.append("property", propertyId);
  if (status && status !== "all") params.append("status", status);
  if (search) params.append("search", search);
  const q = params.toString();
  if (q) url += `?${q}`;

  return apiFetch<Resident[] | { results: Resident[] }>(url).then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function getResident(residentId: string) {
  if (!isUUID(residentId)) return Promise.reject(new ApiError(404, { detail: "Resident not found" }));
  return apiFetch<Resident>(`/api/v1/residents/${residentId}/`);
}

export interface CreateResidentPayload {
  property: string;
  first_name: string;
  last_name?: string;
  gender?: string;
  date_of_birth?: string | null;
  phone: string;
  email?: string;
  permanent_address?: string;
  current_address?: string;
  emergency_contact_name?: string;
  emergency_contact_relation?: string;
  emergency_contact_phone?: string;
  aadhaar_number?: string;
  pan_number?: string;
  passport_number?: string;
  employee_id?: string;
  student_id?: string;
}

export function createResident(payload: CreateResidentPayload) {
  return apiFetch<Resident>("/api/v1/residents/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateResident(residentId: string, payload: Partial<CreateResidentPayload>) {
  return apiFetch<Resident>(`/api/v1/residents/${residentId}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export interface CreateTransferPayload {
  resident: string;
  new_bed: string;
  /** YYYY-MM-DD */
  transfer_date: string;
  is_temporary: boolean;
  reason?: string;
  /** Permanent transfers only; omitted → the server uses the new bed's rack rate. */
  new_rent?: string;
  expected_move_date?: string | null;
  temporary_note?: string;
}

export interface Transfer {
  id: string;
  resident: string;
  previous_bed: string;
  new_bed: string;
  is_temporary: boolean;
  reason: string;
  transfer_date: string;
  previous_rent: string;
  new_rent: string;
  rent_effective_date: string;
  created_at: string;
}

export function createTransfer(payload: CreateTransferPayload) {
  return apiFetch<Transfer>("/api/v1/transfers/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export type ResidentDocumentField = "aadhaar_document" | "pan_document";

/** Uploads (or replaces) one KYC file on the resident, as multipart. */
export function uploadResidentDocument(residentId: string, field: ResidentDocumentField, file: File) {
  const form = new FormData();
  form.append(field, file);
  return apiFetch<Resident>(`/api/v1/residents/${residentId}/`, { method: "PATCH", body: form });
}

export function updateResidentStatus(residentId: string, status: string) {
  return apiFetch<Resident>(`/api/v1/residents/${residentId}/status/`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export interface CreateAdmissionPayload {
  resident: string;
  bed: string;
  joining_date: string;
  billing_mode: "monthly" | "weekly" | "daily";
  expected_stay_duration?: string;
  food_preference: "with_food" | "without_food";
  advance_amount: string;
  advance_collected_date?: string | null;
  advance_mode?: string;
}

export function createAdmission(payload: CreateAdmissionPayload) {
  return apiFetch<Admission>("/api/v1/admissions/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export interface StaffUser {
  id: string;
  first_name: string;
  last_name: string;
  email: string | null;
  phone: string;
  role: string;
  is_active: boolean;
  email_verified?: boolean;
  created_at?: string;
}

export interface CreateStaffPayload {
  first_name: string;
  last_name?: string;
  email?: string | null;
  phone: string;
  role: "manager" | "receptionist";
  password?: string;
}

export interface UpdateStaffPayload {
  first_name?: string;
  last_name?: string;
  phone?: string;
  role?: "manager" | "receptionist";
  is_active?: boolean;
}

export function listStaff() {
  return apiFetch<StaffUser[] | { results: StaffUser[] }>("/api/v1/staff/").then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function createStaff(payload: CreateStaffPayload) {
  return apiFetch<StaffUser>("/api/v1/staff/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateStaff(staffId: string, payload: UpdateStaffPayload) {
  return apiFetch<StaffUser>(`/api/v1/staff/${staffId}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function setStaffPassword(staffId: string, password: string) {
  return apiFetch<{ detail: string }>(`/api/v1/staff/${staffId}/set-password/`, {
    method: "POST",
    body: JSON.stringify({ password }),
  });
}

export function getStaff(staffId: string) {
  return apiFetch<StaffUser>(`/api/v1/staff/${staffId}/`);
}

/** off < view < full. Each module supports only some of these (see `levels`). */
export type ModuleLevel = "off" | "view" | "full";

export interface ModuleAccessEntry {
  key: string;
  /** Levels this module supports, lowest first; always starts with "off". */
  levels: ModuleLevel[];
  level: ModuleLevel;
  default_level: ModuleLevel;
}

export interface StaffModuleAccess {
  role: "manager" | "receptionist";
  customized: boolean;
  modules: ModuleAccessEntry[];
}

export function getStaffModuleAccess(staffId: string) {
  return apiFetch<StaffModuleAccess>(`/api/v1/staff/${staffId}/module-access/`);
}

/** Complete replacement: every module key must be present. `role` is the role the
 * screen rendered — the server answers 409 ROLE_CHANGED if it has changed since. */
export function saveStaffModuleAccess(
  staffId: string,
  role: StaffModuleAccess["role"],
  levels: Record<string, ModuleLevel>
) {
  return apiFetch<StaffModuleAccess>(`/api/v1/staff/${staffId}/module-access/`, {
    method: "PUT",
    body: JSON.stringify({ role, levels }),
  });
}

export function resetStaffModuleAccess(staffId: string) {
  return apiFetch<StaffModuleAccess>(`/api/v1/staff/${staffId}/module-access/`, {
    method: "DELETE",
  });
}

export interface PropertyStaffAssignment {
  id: string;
  staff: string;
  staff_name: string;
  property: string;
  property_name: string;
  created_at: string;
}

/** Which properties a Manager/Receptionist can access. Owners always see every
 * property implicitly and are never assigned — see backend/apps/properties/models.py
 * PropertyStaffAssignment. */
export function listPropertyAssignments(filters?: { staff?: string; property?: string }) {
  const params = new URLSearchParams();
  if (filters?.staff) params.set("staff", filters.staff);
  if (filters?.property) params.set("property", filters.property);
  const query = params.toString();
  return apiFetch<PropertyStaffAssignment[] | { results: PropertyStaffAssignment[] }>(
    `/api/v1/staff-property-assignments/${query ? `?${query}` : ""}`
  ).then((data) => (Array.isArray(data) ? data : data.results));
}

export function assignStaffToProperty(staffId: string, propertyId: string) {
  return apiFetch<PropertyStaffAssignment>("/api/v1/staff-property-assignments/", {
    method: "POST",
    body: JSON.stringify({ staff: staffId, property: propertyId }),
  });
}

export function unassignStaffFromProperty(assignmentId: string) {
  return apiFetch<void>(`/api/v1/staff-property-assignments/${assignmentId}/`, {
    method: "DELETE",
  });
}

export interface ComplaintComment {
  id: string;
  complaint: string;
  author: string | null;
  author_details?: {
    id: string;
    first_name: string;
    last_name: string;
    email: string;
    role: string;
  } | null;
  body: string;
  created_at: string;
}

export interface Complaint {
  id: string;
  resident: string; // ID of resident
  resident_name?: string; // Resolved name helper
  resident_room?: string; // Resolved room helper
  resident_details?: {
    id: string;
    first_name: string;
    last_name: string;
    unit: string;
    block: string;
  };
  category: "electrical" | "plumbing" | "internet_wifi" | "housekeeping" | "security" | "furniture" | "other";
  priority: "low" | "medium" | "high" | "urgent";
  status: "open" | "assigned" | "in_progress" | "resolved" | "closed";
  description: string;
  attachment: string | null;
  assigned_to: string | null; // User ID
  assigned_to_details?: {
    id: string;
    first_name: string;
    last_name: string;
    email: string;
  } | null;
  raised_by: string | null; // User ID
  raised_by_details?: {
    id: string;
    first_name: string;
    last_name: string;
    email: string;
  } | null;
  comments: ComplaintComment[];
  created_at: string;
  updated_at: string;
}

export function listComplaints(filters?: { resident?: string; status?: string; category?: string; priority?: string; property?: string }) {
  if (filters?.resident && !isUUID(filters.resident)) return Promise.reject(new ApiError(404, { detail: "Resident not found" }));
  let url = "/api/v1/complaints/";
  const params = new URLSearchParams();
  if (filters) {
    if (filters.resident) params.append("resident", filters.resident);
    if (filters.status && filters.status !== "all") params.append("status", filters.status);
    if (filters.category && filters.category !== "all") params.append("category", filters.category);
    if (filters.priority && filters.priority !== "all") params.append("priority", filters.priority);
    if (filters.property) params.append("property", filters.property);
  }
  const q = params.toString();
  if (q) url += `?${q}`;

  return apiFetch<Complaint[] | { results: Complaint[] }>(url).then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function getComplaint(complaintId: string) {
  if (!isUUID(complaintId)) return Promise.reject(new ApiError(404, { detail: "Complaint not found" }));
  return apiFetch<Complaint>(`/api/v1/complaints/${complaintId}/`);
}

export function createComplaint(formData: FormData) {
  // Uses FormData directly for file uploads
  return apiFetch<Complaint>("/api/v1/complaints/", {
    method: "POST",
    body: formData, // Skip JSON stringify for multipart uploads
  });
}

export function assignComplaint(complaintId: string, assignedToId: string) {
  return apiFetch<Complaint>(`/api/v1/complaints/${complaintId}/assign/`, {
    method: "POST",
    body: JSON.stringify({ assigned_to: assignedToId }),
  });
}

export function updateComplaintStatus(complaintId: string, status: string) {
  return apiFetch<Complaint>(`/api/v1/complaints/${complaintId}/status/`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export function listComplaintComments(complaintId: string) {
  return apiFetch<ComplaintComment[]>(`/api/v1/complaints/${complaintId}/comments/`);
}

export function createComplaintComment(complaintId: string, body: string) {
  return apiFetch<ComplaintComment>(`/api/v1/complaints/${complaintId}/comments/`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
}

export interface TenantDetails {
  id: string;
  name: string;
  status: string;
  default_language: string;
  trial_ends_at?: string;
  /** 1-12 (default 4, April) — drives analytics' YTD window (D0/D1). */
  fiscal_year_start_month: number;
}

export interface CurrentUser {
  id: string;
  email: string;
  first_name?: string;
  last_name?: string;
  phone?: string;
  role: string;
  language_code: string;
  email_verified: boolean;
  tenant?: TenantDetails;
  tenant_id?: string;
  permissions?: string[];
  /** Launch gate for new Aadhaar/PAN uploads. Absent (an older cached profile) means off. */
  kyc_uploads_enabled?: boolean;
}

export function getCurrentUser() {
  return apiFetch<CurrentUser>("/api/v1/auth/me/");
}

export function updateMe(payload: { first_name?: string; last_name?: string; phone?: string; language_code?: string }) {
  return apiFetch<CurrentUser>("/api/v1/auth/me/", {
    method: "PATCH",
    body: JSON.stringify(payload),
  }).then((user) => {
    if (payload.language_code) {
      writeLocaleCookie(payload.language_code);
    }
    return user;
  });
}

export function updateTenantDefaultLanguage(default_language: string) {
  return apiFetch<TenantDetails>("/api/v1/tenants/current/", {
    method: "PATCH",
    body: JSON.stringify({ default_language }),
  });
}

export function getCurrentTenant() {
  return apiFetch<TenantDetails>("/api/v1/tenants/current/");
}

export function updateTenantFiscalYearStart(fiscal_year_start_month: number) {
  return apiFetch<TenantDetails>("/api/v1/tenants/current/", {
    method: "PATCH",
    body: JSON.stringify({ fiscal_year_start_month }),
  });
}

// --- Billing (UX roadmap D3/D4/D6/D7; see docs/ux-roadmap-backend.md) ---

export type InvoiceStatus = "draft" | "issued" | "partially_paid" | "paid";
export type PaymentMode = "upi" | "cash" | "bank_transfer" | "card" | "cheque";
export type LineType =
  | "accommodation"
  | "food"
  | "electricity"
  | "water"
  | "laundry"
  | "addon"
  | "additional"
  | "discount";

export interface InvoiceLineItem {
  id: string;
  line_type: LineType;
  label: string;
  amount: string;
  order: number;
}

/** Every finance list row (invoices, payments, discounts) carries these so
 * it renders without a second lookup (ResidentContextMixin on the backend). */
interface ResidentContext {
  resident: string;
  resident_name: string;
  property: string;
  property_name: string;
  room_number: string | null;
  bed_number: string | null;
}

export interface Invoice extends ResidentContext {
  id: string;
  period_start: string;
  period_end: string;
  billing_mode: string;
  issue_date: string | null;
  due_date: string;
  status: InvoiceStatus;
  notes: string;
  created_by: string | null;
  line_items: InvoiceLineItem[];
  total: string;
  amount_paid: string;
  balance_due: string;
  /** min(amount_paid, total) — sums to analytics' period_collected under ?period= (D0). */
  capped_allocated: string;
  is_overdue: boolean;
  created_at: string;
  updated_at: string;
}

export interface Payment extends ResidentContext {
  id: string;
  receipt_number: string | null;
  invoice: string;
  invoice_period_start: string;
  invoice_period_end: string;
  amount: string;
  payment_date: string;
  payment_mode: PaymentMode;
  reference: string;
  recorded_by: string | null;
  recorded_by_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface InvoiceFilters {
  property?: string;
  resident?: string;
  /** Comma list of draft/issued/partially_paid/paid, or the alias "outstanding"/"overdue" alone. */
  status?: string;
  /** YYYY-MM */
  period?: string;
  billing_mode?: string;
  search?: string;
  [key: string]: string | undefined;
}

function buildQuery(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) search.append(key, value);
  }
  const q = search.toString();
  return q ? `?${q}` : "";
}

export function listInvoicesFiltered(filters: InvoiceFilters = {}) {
  const url = `/api/v1/invoices/${buildQuery(filters)}`;
  return apiFetch<Invoice[] | { results: Invoice[] }>(url).then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

/** Back-compat alias: the dashboard's existing unfiltered call. */
export function listInvoices() {
  return listInvoicesFiltered();
}

export function getInvoice(id: string) {
  return apiFetch<Invoice>(`/api/v1/invoices/${id}/`);
}

export interface InvoiceGeneratePayload {
  resident: string;
  period_start: string;
  period_end: string;
  due_date: string;
  billing_mode?: string;
}

export function generateInvoice(payload: InvoiceGeneratePayload) {
  return apiFetch<Invoice>("/api/v1/invoices/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export interface InvoiceBulkGeneratePayload {
  property: string;
  period_start: string;
  period_end: string;
  due_date: string;
}

export function bulkGenerateInvoices(payload: InvoiceBulkGeneratePayload) {
  return apiFetch<{ created: number; invoices: Invoice[] }>("/api/v1/invoices/bulk-generate/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateInvoiceDraft(id: string, payload: { due_date?: string; notes?: string }) {
  return apiFetch<Invoice>(`/api/v1/invoices/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteInvoiceDraft(id: string) {
  return apiFetch<void>(`/api/v1/invoices/${id}/`, { method: "DELETE" });
}

export function issueInvoice(id: string) {
  return apiFetch<Invoice>(`/api/v1/invoices/${id}/issue/`, { method: "POST" });
}

export function addInvoiceLineItem(
  invoiceId: string,
  payload: { line_type: LineType; label: string; amount: string; order?: number }
) {
  return apiFetch<Invoice>(`/api/v1/invoices/${invoiceId}/line-items/`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateInvoiceLineItem(
  invoiceId: string,
  lineId: string,
  payload: Partial<{ line_type: LineType; label: string; amount: string; order: number }>
) {
  return apiFetch<Invoice>(`/api/v1/invoices/${invoiceId}/line-items/${lineId}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteInvoiceLineItem(invoiceId: string, lineId: string) {
  return apiFetch<Invoice>(`/api/v1/invoices/${invoiceId}/line-items/${lineId}/`, { method: "DELETE" });
}

export interface PaymentFilters {
  property?: string;
  resident?: string;
  invoice?: string;
  payment_mode?: string;
  /** YYYY-MM */
  month?: string;
  from?: string;
  to?: string;
  search?: string;
  [key: string]: string | undefined;
}

export function listPaymentsFiltered(filters: PaymentFilters = {}) {
  const url = `/api/v1/payments/${buildQuery(filters)}`;
  return apiFetch<Payment[] | { results: Payment[] }>(url).then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

/** Back-compat alias: the dashboard's existing unfiltered call. */
export function listPayments() {
  return listPaymentsFiltered();
}

export interface PaymentCreatePayload {
  invoice: string;
  amount: string;
  payment_date: string;
  payment_mode: PaymentMode;
  reference?: string;
}

/** Records a payment with the given Idempotency-Key. Returns the payment
 * plus whether this call replayed an earlier one with the same key (D3) —
 * both a 201 and a 200 replay resolve here; only OVERPAYMENT/
 * IDEMPOTENCY_KEY_REUSED (409) and validation errors throw. */
export async function createPayment(payload: PaymentCreatePayload, idempotencyKey: string) {
  const { data, headers } = await apiFetchWithMeta<Payment>("/api/v1/payments/", {
    method: "POST",
    body: JSON.stringify(payload),
    headers: { "Idempotency-Key": idempotencyKey },
  });
  return { payment: data, replayed: headers.get("Idempotent-Replayed") === "true" };
}

export function deletePayment(id: string) {
  return apiFetch<void>(`/api/v1/payments/${id}/`, { method: "DELETE" });
}

export interface Receipt {
  receipt_for: string;
  receipt_number: string | null;
  resident: string;
  resident_id: string;
  property: string;
  property_name: string;
  room_number: string | null;
  bed_number: string | null;
  invoice: string;
  period_start: string;
  period_end: string;
  amount: string;
  payment_date: string;
  payment_mode: PaymentMode;
  reference: string;
  recorded_by: string | null;
  recorded_by_name: string | null;
  created_at: string;
  invoice_total: string;
  invoice_paid: string;
  invoice_balance_due: string;
  invoice_status: InvoiceStatus;
}

export function getReceipt(paymentId: string) {
  return apiFetch<Receipt>(`/api/v1/payments/${paymentId}/receipt/`);
}

export function downloadReceiptPdf(paymentId: string) {
  return apiDownload(`/api/v1/payments/${paymentId}/receipt/?filetype=pdf`);
}

export interface CashMovementRow {
  type: "payment";
  id: string;
  date: string;
  amount: string;
  receipt_number: string | null;
  payment_mode: PaymentMode;
  invoice: string;
  resident: string;
  resident_name: string;
  property: string;
  property_name: string;
}

export interface CashMovements {
  from: string;
  to: string;
  gross_receipts: string;
  refunds_paid: string;
  total: string;
  count: number;
  results: CashMovementRow[];
}

export function getCashMovements(filters: { property?: string; month?: string; from?: string; to?: string } = {}) {
  return apiFetch<CashMovements>(`/api/v1/cash-movements/${buildQuery(filters)}`);
}

export type DiscountType = "fixed" | "percentage";
export type DiscountReason = "loyalty" | "referral" | "corporate" | "negotiated" | "seasonal" | "other";

export interface Discount extends ResidentContext {
  id: string;
  discount_type: DiscountType;
  discount_value: string;
  reason: DiscountReason;
  note: string;
  valid_from: string;
  valid_until: string | null;
  approved_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface DiscountFilters {
  property?: string;
  resident?: string;
  reason?: string;
  discount_type?: string;
  [key: string]: string | undefined;
}

export function listDiscountsFiltered(filters: DiscountFilters = {}) {
  const url = `/api/v1/discounts/${buildQuery(filters)}`;
  return apiFetch<Discount[] | { results: Discount[] }>(url).then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export interface DiscountCreatePayload {
  resident: string;
  discount_type: DiscountType;
  discount_value: string;
  reason: DiscountReason;
  note?: string;
  valid_from: string;
  valid_until?: string;
}

export function createDiscount(payload: DiscountCreatePayload) {
  return apiFetch<Discount>("/api/v1/discounts/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateDiscount(id: string, payload: Partial<DiscountCreatePayload>) {
  return apiFetch<Discount>(`/api/v1/discounts/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

/** Discounts have no delete endpoint — "end" one by setting valid_until. */
export function endDiscount(id: string, validUntil: string) {
  return updateDiscount(id, { valid_until: validUntil });
}

export function listAdmissions(filters?: { property?: string }) {
  return apiFetch<Admission[] | { results: Admission[] }>(`/api/v1/admissions/${buildQuery({ property: filters?.property })}`).then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function listAllRooms() {
  return apiFetch<Room[] | { results: Room[] }>("/api/v1/rooms/").then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function listAllBeds() {
  return apiFetch<Bed[] | { results: Bed[] }>("/api/v1/beds/").then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

// --- Analytics (D0/D1; apps/reporting/analytics.py) ---

export interface AnalyticsOccupancy {
  total: number;
  occupied: number;
  reserved: number;
  maintenance: number;
  available: number;
  occupancy_rate: number | null;
}

export interface AnalyticsFinance {
  gross_receipts: string;
  refunds_paid: string;
  cash_collected: string;
  period_invoiced: string;
  period_collected: string;
  collection_rate: number | null;
  outstanding_total: string;
  period_outstanding: string;
  overdue_total: string;
  open_invoice_count: number;
  residents_with_balance_count: number;
  occupied_beds_with_balance_count: number;
  deposits_held: string;
  ytd_cash_collected: string;
}

export interface AnalyticsExpenses {
  expenses_paid: string;
  ytd_expenses_paid: string;
}

export interface AnalyticsCashFlow {
  net_cash_flow: string;
  ytd_net_cash_flow: string;
}

export interface AnalyticsSummary {
  month: string;
  property: string | null;
  timezones: string[];
  balances_as_of: string;
  ytd: { start: string; end: string };
  occupancy: AnalyticsOccupancy;
  finance: AnalyticsFinance | null;
  expenses: AnalyticsExpenses | null;
  cash_flow: AnalyticsCashFlow | null;
  redacted: string[];
}

export function getAnalyticsSummary(filters: { property?: string; month?: string } = {}) {
  return apiFetch<AnalyticsSummary>(`/api/v1/analytics/summary/${buildQuery(filters)}`);
}

export interface AnalyticsTrendPoint {
  month: string;
  finance: Pick<AnalyticsFinance, "gross_receipts" | "refunds_paid" | "cash_collected" | "period_invoiced" | "period_collected" | "collection_rate"> | null;
  expenses: AnalyticsExpenses | null;
  cash_flow: AnalyticsCashFlow | null;
}

export interface AnalyticsTrend {
  end: string;
  months: number;
  property: string | null;
  timezones: string[];
  series: AnalyticsTrendPoint[];
  redacted: string[];
}

export function getAnalyticsTrend(filters: { property?: string; end?: string; months?: string } = {}) {
  return apiFetch<AnalyticsTrend>(`/api/v1/analytics/trend/${buildQuery(filters)}`);
}

// --- Expenses (D5, Module 20) ---

export type ExpenseMode = "upi" | "cash" | "bank_transfer" | "card" | "cheque" | "other";

export interface ExpenseCategory {
  id: string;
  code: string;
  name: string;
  label: string;
  is_system: boolean;
  is_archived: boolean;
  order: number;
  created_at: string;
}

export interface Expense {
  id: string;
  property: string;
  property_name: string;
  category: string;
  category_name: string;
  category_code: string | null;
  amount: string;
  date: string;
  payment_mode: ExpenseMode;
  note: string;
  has_attachment: boolean;
  attachment_content_type: string;
  created_by: string | null;
  created_by_name: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  /** Idempotent replay (D5) — not a server field; set by createExpense(). */
  replayed?: boolean;
}

export interface ExpenseFilters {
  property?: string;
  category?: string;
  payment_mode?: string;
  search?: string;
  /** YYYY-MM */
  month?: string;
  from?: string;
  to?: string;
  [key: string]: string | undefined;
}

export function listExpensesFiltered(filters: ExpenseFilters = {}) {
  const url = `/api/v1/expenses/${buildQuery(filters)}`;
  return apiFetch<Expense[] | { results: Expense[] }>(url).then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function listExpenseCategories() {
  return apiFetch<ExpenseCategory[] | { results: ExpenseCategory[] }>(
    "/api/v1/expense-categories/?include_archived=true"
  ).then((data) => (Array.isArray(data) ? data : data.results));
}

export function createExpenseCategory(name: string) {
  return apiFetch<ExpenseCategory>("/api/v1/expense-categories/", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function archiveExpenseCategory(id: string) {
  return apiFetch<ExpenseCategory>(`/api/v1/expense-categories/${id}/`, {
    method: "PATCH",
    body: JSON.stringify({ is_archived: true }),
  });
}

export interface ExpenseCreatePayload {
  property: string;
  category: string;
  amount: string;
  date: string;
  payment_mode: ExpenseMode;
  note?: string;
  attachment?: File;
}

function expenseFormData(payload: ExpenseCreatePayload | Partial<ExpenseCreatePayload>): FormData {
  const form = new FormData();
  for (const [key, value] of Object.entries(payload)) {
    if (value === undefined) continue;
    form.append(key, value instanceof File ? value : String(value));
  }
  return form;
}

/** Records an expense with the given Idempotency-Key. Returns the expense
 * plus whether this call replayed an earlier one with the same key (D5). */
export async function createExpense(payload: ExpenseCreatePayload, idempotencyKey: string) {
  const { data, headers } = await apiFetchWithMeta<Expense>("/api/v1/expenses/", {
    method: "POST",
    body: expenseFormData(payload),
    headers: { "Idempotency-Key": idempotencyKey },
  });
  return { expense: data, replayed: headers.get("Idempotent-Replayed") === "true" };
}

export function updateExpense(id: string, payload: Partial<Omit<ExpenseCreatePayload, "attachment">>) {
  return apiFetch<Expense>(`/api/v1/expenses/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteExpense(id: string) {
  return apiFetch<void>(`/api/v1/expenses/${id}/`, { method: "DELETE" });
}

export interface ExpenseAttachment {
  url: string;
  content_type: string;
  expires_in: number;
}

export function getExpenseAttachment(id: string) {
  return apiFetch<ExpenseAttachment>(`/api/v1/expenses/${id}/attachment/`);
}

export function replaceExpenseAttachment(id: string, file: File) {
  const form = new FormData();
  form.append("attachment", file);
  return apiFetch<Expense>(`/api/v1/expenses/${id}/attachment/`, { method: "PUT", body: form });
}

export function removeExpenseAttachment(id: string) {
  return apiFetch<Expense>(`/api/v1/expenses/${id}/attachment/`, { method: "DELETE" });
}

export interface ExpenseCategoryTotal {
  category: string;
  name: string;
  code: string | null;
  total: string;
  count: number;
}

export interface ExpenseSummary {
  month: string;
  property: string | null;
  total: string;
  count: number;
  by_category: ExpenseCategoryTotal[];
}

export function getExpenseSummary(filters: { property?: string; month?: string } = {}) {
  return apiFetch<ExpenseSummary>(`/api/v1/expenses/summary/${buildQuery(filters)}`);
}

// --- Exports (D7, Module 17) ---

export type ExportFiletype = "csv" | "xlsx" | "pdf";

export function exportResidents(filetype: ExportFiletype, property?: string) {
  return apiDownload(`/api/v1/exports/residents/${buildQuery({ filetype, property })}`);
}

export function exportPayments(filetype: ExportFiletype, month?: string, property?: string) {
  return apiDownload(`/api/v1/exports/payments/${buildQuery({ filetype, month, property })}`);
}

export function exportOutstandingDues(filetype: ExportFiletype, period?: string, property?: string) {
  return apiDownload(`/api/v1/exports/outstanding-dues/${buildQuery({ filetype, period, property })}`);
}

export function exportOccupancy(filetype: ExportFiletype, property?: string) {
  return apiDownload(`/api/v1/exports/occupancy/${buildQuery({ filetype, property })}`);
}

export function exportExpenses(filetype: ExportFiletype, month?: string, property?: string) {
  return apiDownload(`/api/v1/exports/expenses/${buildQuery({ filetype, month, property })}`);
}

export function exportCashFlowStatement(filetype: ExportFiletype, month?: string, property?: string) {
  return apiDownload(`/api/v1/exports/pnl/${buildQuery({ filetype, month, property })}`);
}

// --- PG features (Module 18) ---

export interface FeatureCatalogItem {
  id: string;
  code: string;
  category: string;
  category_label: string;
  label: string;
  display_order: number;
  is_popular: boolean;
  is_active: boolean;
}

export interface TenantFeature {
  id: string;
  label: string;
  is_active: boolean;
}

export interface PropertyFeature {
  id: string;
  source: "property" | "building";
  building: string | null;
  feature_type: "catalog" | "custom";
  code: string | null;
  tenant_feature: string | null;
  label: string;
  category: string;
  category_label: string;
  is_paid: boolean;
  is_active: boolean;
}

export interface PropertyFeaturesState {
  property: string;
  building: string | null;
  items: PropertyFeature[];
  /** Building scope only: inherited features this building does not offer. */
  excluded: PropertyFeature[];
  /** Facts already known from the room setup — shown read-only, never edited here. */
  derived: { sharing_types: number[]; room_categories: string[] };
}

/** One feature in a save payload: a platform `code` or one of the tenant's own features. */
export interface FeatureRef {
  code?: string;
  tenant_feature?: string;
  is_paid?: boolean;
}

export function listFeatureCatalog() {
  return apiFetch<FeatureCatalogItem[] | { results: FeatureCatalogItem[] }>("/api/v1/feature-catalog/").then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function listTenantFeatures() {
  return apiFetch<TenantFeature[] | { results: TenantFeature[] }>("/api/v1/tenant-features/").then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

/** Idempotent: returns the existing feature when one with the same name already exists. */
export function createTenantFeature(label: string) {
  return apiFetch<TenantFeature>("/api/v1/tenant-features/", {
    method: "POST",
    body: JSON.stringify({ label }),
  });
}

export function listPropertyFeatures(propertyId: string, buildingId?: string | null) {
  if (!isUUID(propertyId)) return Promise.reject(new ApiError(404, { detail: "Property not found" }));
  const query = buildingId ? `?building=${buildingId}` : "";
  return apiFetch<PropertyFeaturesState>(`/api/v1/properties/${propertyId}/features/${query}`);
}

/** Replaces the whole feature set at one scope (the PG, or one building). */
export function replacePropertyFeatures(
  propertyId: string,
  payload: { building: string | null; items: FeatureRef[]; excluded?: FeatureRef[] }
) {
  if (!isUUID(propertyId)) return Promise.reject(new ApiError(404, { detail: "Property not found" }));
  return apiFetch<PropertyFeaturesState>(`/api/v1/properties/${propertyId}/features/`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export interface Visitor {
  id: string;
  resident: string;
  visitor_name: string;
  mobile_number: string;
  purpose: string;
  entry_time: string;
  exit_time: string | null;
  is_checked_in: boolean;
  logged_by?: string;
  checked_out_by?: string | null;
  approved_by?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface VisitorPayload {
  resident: string;
  visitor_name: string;
  mobile_number: string;
  purpose: string;
  entry_time?: string;
}

export function listVisitors(filters?: { resident?: string; mobile_number?: string }) {
  const params = new URLSearchParams();
  if (filters?.resident) params.append("resident", filters.resident);
  if (filters?.mobile_number) params.append("mobile_number", filters.mobile_number);
  const q = params.toString();
  return apiFetch<Visitor[] | { results: Visitor[] }>(`/api/v1/visitors/${q ? `?${q}` : ""}`).then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function createVisitor(payload: VisitorPayload) {
  return apiFetch<Visitor>("/api/v1/visitors/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function checkOutVisitor(id: string, exit_time?: string) {
  return apiFetch<Visitor>(`/api/v1/visitors/${id}/check-out/`, {
    method: "POST",
    body: JSON.stringify(exit_time ? { exit_time } : {}),
  });
}


// ---- Plans & subscription (Module 13) --------------------------------------

export interface PlanBedTier {
  id: string;
  /** Upper bound of this price step; null is the open-ended top step. */
  up_to_beds: number | null;
  rate_per_bed: string;
}

export interface Plan {
  id: string;
  name: string;
  pricing_type: "flat_monthly" | "per_bed_monthly";
  /** null means unlimited. */
  max_beds: number | null;
  max_properties: number | null;
  max_residents_per_property: number | null;
  /** null for per-bed plans, which price through bed_tiers. */
  price_per_month: string | null;
  bed_tiers: PlanBedTier[];
  is_trial_plan: boolean;
  is_active: boolean;
}

export interface Subscription {
  id: string;
  tenant: string;
  /** null while on trial with no plan chosen yet. */
  plan: Plan | null;
  /** A plan chosen but not yet paid for; `plan` and every limit stay as they were until it is. */
  pending_plan: Plan | null;
  pending_razorpay_subscription_id: string;
  tenant_status: "trial" | "active" | "payment_failed" | "suspended" | "cancelled";
  trial_ends_at: string | null;
  razorpay_subscription_id: string;
  /** Public Razorpay key id; blank when payments aren't configured. */
  razorpay_key_id: string;
  current_period_end: string | null;
  bed_count: number;
  /** Effective limits: plan, override or the trial plan's, null = unlimited. */
  max_beds: number | null;
  max_properties: number | null;
  properties_used: number;
}

export function listPlans() {
  return apiFetch<Plan[] | { results: Plan[] }>("/api/v1/plans/").then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function getSubscription(tenantId: string) {
  return apiFetch<Subscription>(`/api/v1/subscriptions/${tenantId}/`);
}

export function selectPlan(tenantId: string, planId: string) {
  return apiFetch<Subscription>(`/api/v1/subscriptions/${tenantId}/select-plan/`, {
    method: "POST",
    body: JSON.stringify({ plan: planId }),
  });
}
