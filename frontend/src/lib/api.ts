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
  email?: string | null;
  name: string;
  picture?: string | null;
  gender?: "male" | "female" | "other" | null;
  age?: number | null;
  profile_complete?: boolean;
  terms_version?: string | null;
  terms_accepted_at?: string | null;
  email_verified?: boolean;
  auth_providers?: string[];
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

export type GroupPage = {
  items: ApiGroup[];
  next_cursor: string | null;
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
    // FastAPI can return either a plain string in `detail` or a structured
    // object (e.g. suspension payload: {message, suspended, until, reason}).
    // Prefer a human-readable message when the object exposes one, and
    // stash the raw payload on the Error for callers that need to react
    // (e.g. show a "Sei sospeso fino al …" banner).
    const rawDetail = data && (data.detail ?? data.message);
    let msg: string;
    if (typeof rawDetail === "string") {
      msg = rawDetail;
    } else if (rawDetail && typeof rawDetail === "object" && typeof (rawDetail as any).message === "string") {
      msg = (rawDetail as any).message;
    } else if (rawDetail) {
      msg = JSON.stringify(rawDetail);
    } else {
      msg = res.statusText || `HTTP ${res.status}`;
    }
    const err: any = new Error(msg);
    err.status = res.status;
    err.detail = rawDetail;
    throw err;
  }
  return data as T;
}

export const api = {
  // ---- Auth ----
  me: () => request<ApiUser>("/auth/me"),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),

  // Email + password
  register: (payload: { email: string; password: string; name?: string }) =>
    request<{ session_token: string; user: ApiUser; email_verification_sent: boolean }>(
      "/auth/register",
      { method: "POST", body: payload, auth: false },
    ),
  loginPassword: (payload: { email: string; password: string }) =>
    request<{ session_token: string; user: ApiUser }>("/auth/login", {
      method: "POST",
      body: payload,
      auth: false,
    }),
  requestPasswordReset: (email: string) =>
    request<{ message: string }>("/auth/password/request-reset", {
      method: "POST",
      body: { email },
      auth: false,
    }),
  confirmPasswordReset: (token: string, new_password: string) =>
    request<{ ok: boolean }>("/auth/password/confirm-reset", {
      method: "POST",
      body: { token, new_password },
      auth: false,
    }),
  verifyEmail: (token: string) =>
    request<{ ok: boolean }>("/auth/verify-email", {
      method: "POST",
      body: { token },
      auth: false,
    }),

  // Apple Sign-In: exchanges the identity_token minted by ASAuthorizationController
  // for a Barrio session_token. `email` and `full_name` are only provided by
  // Apple on the very first sign-in.
  appleSignIn: (payload: {
    identity_token: string;
    email?: string | null;
    full_name?: string | null;
  }) =>
    request<{ session_token: string; user: ApiUser }>("/auth/apple", {
      method: "POST",
      body: payload,
      auth: false,
    }),

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
    opts?: { cursor?: string | null; limit?: number },
  ) => {
    const qs = new URLSearchParams();
    if (category && category !== "all") qs.append("category", category);
    if (q) qs.append("q", q);
    if (geo && Number.isFinite(geo.lat) && Number.isFinite(geo.lon) && geo.radiusKm > 0) {
      qs.append("lat", String(geo.lat));
      qs.append("lon", String(geo.lon));
      qs.append("radius_km", String(geo.radiusKm));
    }
    if (opts?.cursor) qs.append("cursor", opts.cursor);
    qs.append("limit", String(Math.min(Math.max(opts?.limit ?? 30, 1), 100)));
    const str = qs.toString();
    return request<GroupPage>(`/groups${str ? `?${str}` : ""}`, { auth: false });
  },
  createGroup: (payload: Partial<ApiGroup>) =>
    request<ApiGroup>("/groups", { method: "POST", body: payload }),
  getGroup: (id: string) =>
    request<ApiGroup>(`/groups/${id}`, { auth: false }),
  joinGroup: (id: string) =>
    request<ApiGroup>(`/groups/${id}/join`, { method: "POST" }),
  leaveGroup: (id: string) =>
    request<ApiGroup>(`/groups/${id}/leave`, { method: "POST" }),
  kickParticipant: (id: string, user_id: string, reason: string = "") =>
    request<ApiGroup>(`/groups/${id}/kick`, {
      method: "POST",
      body: { user_id, reason },
    }),
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
  adminGetUser: (user_id: string) =>
    request<{
      user_id: string;
      email: string | null;
      name: string | null;
      picture: string | null;
      created_at: string | null;
      suspension_active: boolean;
      suspension: { until: string | null; reason: string; at: string } | null;
    }>(`/admin/users/${user_id}`, { admin: true, auth: false }),
  adminSuspendUser: (user_id: string, days: number | null, reason: string = "") =>
    request<{
      ok: boolean;
      user_id: string;
      suspension: { at: string; until: string | null; reason: string; by: string };
    }>(`/admin/users/${user_id}/suspend`, {
      method: "POST",
      body: { days, reason },
      admin: true,
      auth: false,
    }),
  adminUnsuspendUser: (user_id: string) =>
    request<{ ok: boolean; user_id: string }>(
      `/admin/users/${user_id}/unsuspend`,
      { method: "POST", admin: true, auth: false },
    ),
};

// ============================== Chat WebSocket ==============================
//
// Long-lived socket that streams new messages for a group in real time.
// Falls back gracefully: callers can subscribe to lifecycle callbacks and
// implement HTTP polling if the socket refuses to connect.

export type ChatSocketHandlers = {
  onMessage: (msg: ApiMessage) => void;
  onOpen?: () => void;
  onClose?: (code: number, reason: string) => void;
  onError?: (err: unknown) => void;
};

export type ChatSocketHandle = {
  close: () => void;
  send: (data: any) => void;
  readyState: () => number;
};

/**
 * Open a WebSocket to /api/ws/groups/{group_id}. Returns a small handle
 * that lets the caller close it or send keep-alive pings. The connection
 * is single-shot — if you need automatic reconnection, wrap this in your
 * own retry loop (see `group/[id].tsx`).
 */
export function openChatSocket(
  groupId: string,
  token: string,
  handlers: ChatSocketHandlers,
): ChatSocketHandle {
  if (!BASE) {
    // Nothing we can do without a base URL — mimic the "closed" state so
    // the caller falls back to polling.
    handlers.onClose?.(4000, "missing-base");
    return {
      close: () => {},
      send: () => {},
      readyState: () => 3,
    };
  }
  // http(s) → ws(s)
  const wsBase = BASE.replace(/^http/i, "ws");
  const url = `${wsBase}/api/ws/groups/${encodeURIComponent(groupId)}?token=${encodeURIComponent(token)}`;
  const socket = new WebSocket(url);

  socket.onopen = () => {
    handlers.onOpen?.();
  };
  socket.onmessage = (ev) => {
    try {
      const data = typeof ev.data === "string" ? JSON.parse(ev.data) : null;
      if (!data || typeof data !== "object") return;
      if (data.type === "message" && data.data) {
        handlers.onMessage(data.data as ApiMessage);
      }
      // "connected" / "pong" / "error" are consumed silently — callers can
      // rely on onOpen/onClose for lifecycle.
    } catch {
      // Ignore malformed frames.
    }
  };
  socket.onerror = (err) => {
    handlers.onError?.(err);
  };
  socket.onclose = (ev) => {
    handlers.onClose?.(ev.code || 1006, ev.reason || "");
  };

  return {
    close: () => {
      try {
        socket.close();
      } catch {
        /* noop */
      }
    },
    send: (data: any) => {
      try {
        socket.send(typeof data === "string" ? data : JSON.stringify(data));
      } catch {
        /* noop */
      }
    },
    readyState: () => socket.readyState,
  };
}
