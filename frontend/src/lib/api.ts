// Minimal direct-to-Django API client for local development.
//
// This is a deliberate shortcut, not the target architecture: docs/frontend-plan.md
// §3.1 specifies a Next.js BFF proxy (route handlers under app/api/[...path]) that
// keeps JWTs in httpOnly cookies so the browser never sees them. That hasn't been
// built yet. Until it is, this client calls Django directly from the browser and
// keeps the JWT pair in localStorage — fine for local dev (CORS is dev-only, see
// backend/config/settings/dev.py), but it must be replaced by the BFF proxy before
// this app is exposed beyond a developer's machine.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const ACCESS_TOKEN_KEY = "accessToken";
const REFRESH_TOKEN_KEY = "refreshToken";

export type ApiErrorBody = Record<string, unknown>;

export class ApiError extends Error {
  status: number;
  body: ApiErrorBody;

  constructor(status: number, body: ApiErrorBody) {
    super(typeof body.detail === "string" ? body.detail : "Request failed");
    this.status = status;
    this.body = body;
  }

  /** First message for a given field, if the backend returned a field-level validation error. */
  fieldError(field: string): string | undefined {
    const value = this.body[field];
    if (Array.isArray(value) && typeof value[0] === "string") return value[0];
    if (typeof value === "string") return value;
    return undefined;
  }
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
}

async function parseErrorBody(res: Response): Promise<ApiErrorBody> {
  try {
    return await res.json();
  } catch {
    return { detail: res.statusText };
  }
}

async function refreshAccessToken(): Promise<string | null> {
  const refresh = getRefreshToken();
  if (!refresh) return null;
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/token/refresh/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });
  if (!res.ok) return null;
  const data = await res.json();
  localStorage.setItem(ACCESS_TOKEN_KEY, data.access);
  return data.access as string;
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
  if (!options.skipAuth) {
    const token = getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });

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

interface MeResponse {
  first_name: string;
  last_name: string;
  role: string;
}

export async function login(email: string, password: string) {
  const tokens = await apiFetch<{ access: string; refresh: string }>("/api/v1/auth/login/", {
    method: "POST",
    body: JSON.stringify({ email, password }),
    skipAuth: true,
  });
  setTokens(tokens.access, tokens.refresh);

  const me = await apiFetch<MeResponse>("/api/v1/auth/me/");
  localStorage.setItem("isLoggedIn", "true");
  localStorage.setItem("userRole", me.role);
  localStorage.setItem("userName", `${me.first_name} ${me.last_name}`.trim());
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

export function listProperties() {
  return apiFetch<Property[] | { results: Property[] }>("/api/v1/properties/").then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function getProperty(id: string) {
  return apiFetch<Property>(`/api/v1/properties/${id}/`);
}

export function createProperty(payload: PropertyPayload) {
  return apiFetch<Property>("/api/v1/properties/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateProperty(id: string, payload: Partial<PropertyPayload>) {
  return apiFetch<Property>(`/api/v1/properties/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function uploadPropertyImage(propertyId: string, file: File) {
  const formData = new FormData();
  formData.append("image", file);
  return apiFetch<PropertyImage>(`/api/v1/properties/${propertyId}/images/`, {
    method: "POST",
    body: formData,
  });
}

export function deletePropertyImage(propertyId: string, imageId: string) {
  return apiFetch<void>(`/api/v1/properties/${propertyId}/images/${imageId}/`, {
    method: "DELETE",
  });
}

export function listBuildings(propertyId: string) {
  return apiFetch<Building[] | { results: Building[] }>(`/api/v1/buildings/?property=${propertyId}`).then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function getBuilding(buildingId: string) {
  return apiFetch<Building>(`/api/v1/buildings/${buildingId}/`);
}

export function createBuilding(payload: { property: string; name: string; order?: number; number_of_floors?: number }) {
  return apiFetch<Building>("/api/v1/buildings/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteBuilding(buildingId: string) {
  return apiFetch<void>(`/api/v1/buildings/${buildingId}/`, {
    method: "DELETE",
  });
}

export function listFloors(buildingId: string) {
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
  return apiFetch<void>(`/api/v1/floors/${floorId}/`, {
    method: "DELETE",
  });
}

export function getFloor(floorId: string) {
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
  return apiFetch<Room[] | { results: Room[] }>(`/api/v1/rooms/?floor=${floorId}`).then((data) =>
    Array.isArray(data) ? data : data.results
  );
}

export function getRoom(roomId: string) {
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
  return apiFetch<void>(`/api/v1/rooms/${roomId}/`, {
    method: "DELETE",
  });
}

export function listBeds(roomId: string) {
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
  return apiFetch<Bed>(`/api/v1/beds/${bedId}/`);
}

export function updateBed(bedId: string, payload: Partial<Bed>) {
  return apiFetch<Bed>(`/api/v1/beds/${bedId}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}
