// Minimal direct-to-Django API client for local development.
//
// This is a deliberate shortcut, not the target architecture: docs/frontend-plan.md
// §3.1 specifies a Next.js BFF proxy (route handlers under app/api/[...path]) that
// keeps JWTs in httpOnly cookies so the browser never sees them. That hasn't been
// built yet. Until it is, this client calls Django directly from the browser and
// keeps the JWT pair in localStorage — fine for local dev (CORS is dev-only, see
// backend/config/settings/dev.py), but it must be replaced by the BFF proxy before
// this app is exposed beyond a developer's machine.

import { readLocaleCookie, writeLocaleCookie } from "@/i18n/locale";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const ACCESS_TOKEN_KEY = "accessToken";
const REFRESH_TOKEN_KEY = "refreshToken";
/** Permission codes from /auth/me/ — read through `usePermissions()`. */
export const PERMISSIONS_KEY = "userPermissions";
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

function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setTokens(access: string, refresh: string) {
  localStorage.setItem(ACCESS_TOKEN_KEY, access);
  localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
}

export function clearSession() {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem("isLoggedIn");
  localStorage.removeItem("userRole");
  localStorage.removeItem("userName");
  localStorage.removeItem(PERMISSIONS_KEY);
  // Invariant F7: no tenant data survives logout.
  for (const key of Object.keys(sessionStorage)) {
    if (key.startsWith(FEATURE_DRAFT_PREFIX)) sessionStorage.removeItem(key);
  }
}

async function parseErrorBody(res: Response): Promise<ApiErrorBody> {
  try {
    return await res.json();
  } catch {
    return { detail: res.statusText || `HTTP ${res.status}` };
  }
}

async function refreshAccessToken(): Promise<string | null> {
  const refresh = getRefreshToken();
  if (!refresh) return null;
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/auth/token/refresh/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    localStorage.setItem(ACCESS_TOKEN_KEY, data.access);
    return data.access as string;
  } catch {
    return null;
  }
}

interface ApiFetchOptions extends RequestInit {
  /** Skip attaching the Authorization header and the 401-refresh dance (login itself). */
  skipAuth?: boolean;
}

export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}, _isRetry = false): Promise<T> {
  const isFormData = options.body instanceof FormData;
  const headers = new Headers(options.headers);
  if (!isFormData && options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const currentLocale = typeof window !== "undefined" ? readLocaleCookie() : "en";
  if (!headers.has("Accept-Language")) {
    headers.set("Accept-Language", currentLocale);
  }
  if (!options.skipAuth) {
    const token = getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(0, { detail: "Could not reach the server. Please check your network connection." });
  }

  if (res.status === 401 && !options.skipAuth && !_isRetry) {
    const newToken = await refreshAccessToken();
    if (newToken) return apiFetch<T>(path, options, true);
    clearSession();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError(401, { detail: "Session expired" });
  }

  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorBody(res));
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function login(email: string, password: string) {
  const tokens = await apiFetch<{ access: string; refresh: string }>("/api/v1/auth/login/", {
    method: "POST",
    body: JSON.stringify({ email, password }),
    skipAuth: true,
  });
  setTokens(tokens.access, tokens.refresh);

  const me = await apiFetch<CurrentUser>("/api/v1/auth/me/");
  localStorage.setItem("isLoggedIn", "true");
  localStorage.setItem("userRole", me.role);
  localStorage.setItem(PERMISSIONS_KEY, JSON.stringify(me.permissions ?? []));
  localStorage.setItem("userName", `${me.first_name ?? ''} ${me.last_name ?? ''}`.trim());
  const effectiveLang = me.language_code || me.tenant?.default_language || "en";
  writeLocaleCookie(effectiveLang);
  return me;
}

export interface PropertyImage {
  id: string;
  image: string;
  order: number;
}

export interface PropertyPayload {
  name: string;
  property_type: string;
  address_line: string;
  city: string;
  state: string;
  country?: string;
  contact_number: string;
  contact_email?: string;
}

export interface Property extends PropertyPayload {
  id: string;
  status: string;
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

const MOCK_PROPERTIES_MAP: Record<string, Property> = {
  skyline: {
    id: "skyline",
    name: "Skyline Tower",
    property_type: "pg",
    address_line: "12, Outer Ring Road, Bellandur",
    city: "Bengaluru",
    state: "Karnataka",
    contact_number: "9876543210",
    status: "active",
    buildings_count: 1,
    floors_count: 12,
    rooms_count: 288,
    beds_count: 576,
    occupancy_percent: 92,
    images: [],
  },
  sunset: {
    id: "sunset",
    name: "Sunset Apartments Complex",
    property_type: "apartment",
    address_line: "Block B, Sunset Hills",
    city: "Mumbai",
    state: "Maharashtra",
    contact_number: "9876543210",
    status: "active",
    buildings_count: 1,
    floors_count: 5,
    rooms_count: 60,
    beds_count: 120,
    occupancy_percent: 88,
    images: [],
  },
};

export function listProperties() {
  return apiFetch<Property[] | { results: Property[] }>("/api/v1/properties/").then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function getProperty(id: string) {
  if (!isUUID(id)) {
    const mock = MOCK_PROPERTIES_MAP[id];
    if (mock) return Promise.resolve(mock);
    return Promise.reject(new ApiError(404, { detail: "Property not found" }));
  }
  return apiFetch<Property>(`/api/v1/properties/${id}/`);
}

export function createProperty(payload: PropertyPayload) {
  return apiFetch<Property>("/api/v1/properties/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateProperty(id: string, payload: Partial<PropertyPayload>) {
  if (!isUUID(id)) {
    const mock = MOCK_PROPERTIES_MAP[id];
    if (mock) return Promise.resolve({ ...mock, ...payload });
    return Promise.reject(new ApiError(404, { detail: "Property not found" }));
  }
  return apiFetch<Property>(`/api/v1/properties/${id}/`, {
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
  if (!isUUID(propertyId)) {
    const mock = MOCK_PROPERTIES_MAP[propertyId];
    if (mock) {
      return Promise.resolve([
        {
          id: `bldg-${propertyId}`,
          property: propertyId,
          name: "Main Tower",
          order: 1,
          floors_count: mock.floors_count,
          rooms_count: mock.rooms_count,
          occupancy_percent: mock.occupancy_percent,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ]);
    }
    return Promise.resolve([]);
  }
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
  if (!isUUID(buildingId)) return Promise.resolve([]);
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

export interface Bed {
  id: string;
  room: string;
  bed_number: string;
  rack_rate_with_food_override: string | null;
  rack_rate_without_food_override: string | null;
  effective_rate_with_food: string;
  effective_rate_without_food: string;
  status: "available" | "occupied" | "reserved" | "maintenance";
  current_occupant?: {
    id: string;
    first_name: string;
    last_name: string;
    full_name: string;
    email: string;
    phone: string;
    status: string;
    joining_date: string | null;
    rent: string;
    initials: string;
  } | null;
  history?: Array<{
    resident: string;
    term: string;
    moveIn: string;
    moveOut: string;
    rate: string;
    initials: string;
  }>;
  created_at: string;
  updated_at: string;
}

export function listRooms(floorId: string) {
  if (!isUUID(floorId)) return Promise.resolve([]);
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
  if (!isUUID(roomId)) return Promise.resolve([]);
  return apiFetch<Bed[] | { results: Bed[] }>(`/api/v1/beds/?room=${roomId}`).then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function createBed(payload: { room: string; bed_number: string }) {
  return apiFetch<Bed>("/api/v1/beds/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
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
  pan_number: string;
  passport_number: string;
  employee_id: string;
  student_id: string;
  unit?: string;
  block?: string;
  move_in_date?: string;
  joining_date?: string;
  rent?: string;
  deposit?: string;
  rent_type?: string;
  invoices?: Array<{
    id: string;
    invoice_number?: string;
    billing_period_start?: string;
    billing_period_end?: string;
    total_amount?: string;
    status: string;
    payment_mode?: string;
  }>;
  complaints?: Complaint[];
  created_at: string;
  updated_at: string;
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

export function listResidents(propertyId?: string, status?: string) {
  if (propertyId && !isUUID(propertyId)) return Promise.resolve([]);
  let url = "/api/v1/residents/";
  const params = new URLSearchParams();
  if (propertyId) params.append("property", propertyId);
  if (status && status !== "all") params.append("status", status);
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
  email: string;
  role: string;
  is_active: boolean;
}

export function listStaff() {
  return apiFetch<StaffUser[] | { results: StaffUser[] }>("/api/v1/staff/").then((data) =>
    Array.isArray(data) ? data : data.results
  );
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

export function listComplaints(filters?: { resident?: string; status?: string; category?: string; priority?: string }) {
  if (filters?.resident && !isUUID(filters.resident)) return Promise.resolve([]);
  let url = "/api/v1/complaints/";
  const params = new URLSearchParams();
  if (filters) {
    if (filters.resident) params.append("resident", filters.resident);
    if (filters.status && filters.status !== "all") params.append("status", filters.status);
    if (filters.category && filters.category !== "all") params.append("category", filters.category);
    if (filters.priority && filters.priority !== "all") params.append("priority", filters.priority);
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

export interface Invoice {
  id: string;
  resident: string;
  period_start: string;
  period_end: string;
  billing_mode: string;
  issue_date: string;
  due_date: string;
  status: "draft" | "issued" | "paid" | "partially_paid" | "void";
  total: string;
  amount_paid: string;
  balance_due: string;
  is_overdue: boolean;
  created_at: string;
}

export interface Payment {
  id: string;
  invoice: string;
  payment_date: string;
  payment_mode: string;
  amount: string;
  reference_number?: string;
  created_at: string;
}

export function listInvoices() {
  return apiFetch<Invoice[] | { results: Invoice[] }>("/api/v1/invoices/").then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function listPayments() {
  return apiFetch<Payment[] | { results: Payment[] }>("/api/v1/payments/").then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function listAdmissions() {
  return apiFetch<Admission[] | { results: Admission[] }>("/api/v1/admissions/").then((data) =>
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
  return apiFetch<FeatureCatalogItem[] | { results: FeatureCatalogItem[] }>("/api/v1/feature-catalog/").then(
    (data) => (Array.isArray(data) ? data : data.results)
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
