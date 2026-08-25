import AsyncStorage from "@react-native-async-storage/async-storage";

import { sessionStore } from "@/src/lib/session-store";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL;

export type PublicUser = {
  user_id: string;
  name: string;
  picture?: string | null;
  gender?: "male" | "female" | "other" | null;
  age?: number | null;
  created_at: string;
};

export type ApiUser = {
  user_id: string;
  name: string;
  picture?: string | null;
  gender?: "male" | "female" | "other" | null;
  age?: number | null;
  profile_complete?: boolean;
  terms_version?: string | null;
  terms_accepted_at?: string | null;
  created_at: string;
};

export type Participant = {
  user_id: string;
  name: string;
  picture?: string | null;
};

export type ApiGroup = {
  group_id: string;
  title: string;
  category: string;
  category_label: string;
  location: string;
  city?: string | null;
  province?: string | null;
  lat?: number | null;
  lon?: number | null;
  description: string;
  date: string;
  time: string;
  min_participants: number;
  max_participants: number;
  min_age: number;
  max_age: number;
  gender_filter?: "male" | "female" | "any";
  owner_id: string;
  owner_name: string;
  owner_picture?: string | null;
  participants: Participant[];
  created_at: string;
};

export type CitySuggestion = {
  name: string;
  province: string;
  region: string;
  lat: number;
  lon: number;
  display: string;
};

export type ApiMessage = {
  message_id: string;
  group_id: string;
  user_id: string;
  user_name: string;
  user_picture?: string | null;
  text: string;
  created_at: string;
};

export type ReportTargetType = "group" | "user" | "message";
export type ReportReason =
  | "illegal_content"
  | "sexual_content"
  | "harassment"
  | "scam"
  | "spam"
  | "violence"
  | "personal_info"
  | "other";

export type ApiReport = {
  report_id: string;
  target_type: ReportTargetType;
  target_id: string;
  reason: ReportReason;
  description: string;
  reporter_id: string;
  reporter_name: string;
  status: "pending" | "reviewed" | "dismissed";
  created_at: string;
};

export type AdminReport = ApiReport & {
  target_snapshot?: Record<string, any> | null;
  target_exists: boolean;
};

export type AdminStats = {
  pending: number;
  reviewed: number;
  dismissed: number;
  users: number;
  groups: number;
};

const ADMIN_SECRET_KEY = "@groupup/admin_secret";

async function getAdminSecret(): Promise<string | null> {
  try {
    return await AsyncStorage.getItem(ADMIN_SECRET_KEY);
  } catch {
    return null;
  }
}

async function getSessionToken(): Promise<string | null> {
  // auth.tsx exposes the current token synchronously via globalThis for perf.
  const cached = (globalThis as any).__GROUPUP_SESSION_TOKEN__;
  if (typeof cached === "string" && cached.length > 0) return cached;
  return sessionStore.get();
}

async function request<T>(
  path: string,
  opts: { method?: string; body?: any; auth?: boolean; admin?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.auth !== false) {
    const token = await getSessionToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  if (opts.admin) {
    const secret = await getAdminSecret();
    if (secret) headers["X-Admin-Secret"] = secret;
  }
  const res = await fetch(`${BASE}/api${path}`, {
    method: opts.method || "GET",
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = (data && (data.detail || data.message)) || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data as T;
}

export const api = {
  // ---- Auth ----
  me: () => request<ApiUser>("/auth/me"),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  updateProfile: (payload: {
    name?: string;
    picture?: string;
    gender?: string;
    age?: number;
  }) => request<ApiUser>("/auth/me", { method: "PATCH", body: payload }),
  deleteAccount: () =>
    request<{ ok: boolean; deleted_groups: string[] }>("/auth/me", {
      method: "DELETE",
    }),
  acceptTerms: (version: string) =>
    request<ApiUser>("/auth/accept-terms", {
      method: "POST",
      body: { version },
    }),
  getUser: (id: string) => request<PublicUser>(`/users/${id}`),

  // ---- Groups ----
  listGroups: (
    category?: string,
    q?: string,
    geo?: { lat: number; lon: number; radiusKm: number } | null,
  ) => {
    const qs = new URLSearchParams();
    if (category && category !== "all") qs.append("category", category);
    if (q) qs.append("q", q);
    if (geo && Number.isFinite(geo.lat) && Number.isFinite(geo.lon) && geo.radiusKm > 0) {
      qs.append("lat", String(geo.lat));
      qs.append("lon", String(geo.lon));
      qs.append("radius_km", String(geo.radiusKm));
    }
    const str = qs.toString();
    return request<ApiGroup[]>(`/groups${str ? `?${str}` : ""}`, { auth: false });
  },
  createGroup: (payload: Partial<ApiGroup>) =>
    request<ApiGroup>("/groups", { method: "POST", body: payload }),
  getGroup: (id: string) =>
    request<ApiGroup>(`/groups/${id}`, { auth: false }),
  joinGroup: (id: string) =>
    request<ApiGroup>(`/groups/${id}/join`, { method: "POST" }),
  leaveGroup: (id: string) =>
    request<ApiGroup>(`/groups/${id}/leave`, { method: "POST" }),
  deleteGroup: (id: string) =>
    request<{ ok: boolean }>(`/groups/${id}`, { method: "DELETE" }),
  myGroups: () =>
    request<{ created: ApiGroup[]; joined: ApiGroup[] }>("/groups/mine"),

  // ---- Geocoding ----
  geocode: (city: string, street: string = "") => {
    const qs = new URLSearchParams({ city });
    if (street) qs.append("street", street);
    return request<{ lat: number; lon: number }>(`/geocode?${qs.toString()}`, {
      auth: false,
    });
  },
  suggestCities: (q: string, limit: number = 6) => {
    const qs = new URLSearchParams({ q, limit: String(limit) });
    return request<CitySuggestion[]>(`/cities/suggest?${qs.toString()}`, {
      auth: false,
    });
  },

  // ---- Chat ----
  getMessages: (id: string) => request<ApiMessage[]>(`/groups/${id}/messages`),
  postMessage: (id: string, text: string) =>
    request<ApiMessage>(`/groups/${id}/messages`, {
      method: "POST",
      body: { text },
    }),

  // ---- Reports ----
  submitReport: (payload: {
    target_type: ReportTargetType;
    target_id: string;
    reason: ReportReason;
    description?: string;
  }) => request<ApiReport>("/reports", { method: "POST", body: payload }),
  myReports: () => request<ApiReport[]>("/reports/mine"),

  // ---- Admin ----
  adminSetSecret: async (secret: string) => {
    await AsyncStorage.setItem(ADMIN_SECRET_KEY, secret);
  },
  adminClearSecret: async () => {
    await AsyncStorage.removeItem(ADMIN_SECRET_KEY);
  },
  adminHasSecret: async () => {
    const s = await getAdminSecret();
    return !!s;
  },
  adminVerify: () =>
    request<{ ok: boolean }>("/admin/verify", { admin: true, auth: false }),
  adminStats: () =>
    request<AdminStats>("/admin/stats", { admin: true, auth: false }),
  adminListReports: (status: "pending" | "reviewed" | "dismissed" | "all" = "pending") =>
    request<AdminReport[]>(`/admin/reports?status=${status}`, {
      admin: true,
      auth: false,
    }),
  adminUpdateReport: (
    report_id: string,
    status: "pending" | "reviewed" | "dismissed",
  ) =>
    request<ApiReport>(`/admin/reports/${report_id}`, {
      method: "PATCH",
      body: { status },
      admin: true,
      auth: false,
    }),
  adminDeleteGroup: (group_id: string) =>
    request<{ ok: boolean }>(`/admin/groups/${group_id}`, {
      method: "DELETE",
      admin: true,
      auth: false,
    }),
  adminDeleteMessage: (message_id: string) =>
    request<{ ok: boolean }>(`/admin/messages/${message_id}`, {
      method: "DELETE",
      admin: true,
      auth: false,
    }),
  adminDeleteUser: (user_id: string) =>
    request<{ ok: boolean; deleted_groups: string[] }>(
      `/admin/users/${user_id}`,
      { method: "DELETE", admin: true, auth: false },
    ),
};
