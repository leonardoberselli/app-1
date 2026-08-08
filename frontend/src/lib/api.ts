import { auth } from "./firebase";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL;

export type ApiUser = {
  user_id: string;
  email: string;
  name: string;
  picture?: string | null;
  gender?: "male" | "female" | "other" | null;
  age?: number | null;
  profile_complete?: boolean;
  email_verified?: boolean;
  providers?: string[];
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
  description: string;
  date: string;
  time: string;
  min_participants: number;
  max_participants: number;
  min_age: number;
  max_age: number;
  owner_id: string;
  owner_name: string;
  owner_picture?: string | null;
  participants: Participant[];
  created_at: string;
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

async function getIdToken(force = false): Promise<string | null> {
  const u = auth.currentUser;
  if (!u) return null;
  try {
    return await u.getIdToken(force);
  } catch {
    return null;
  }
}

async function request<T>(
  path: string,
  opts: { method?: string; body?: any; auth?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.auth !== false) {
    const token = await getIdToken();
    if (token) headers.Authorization = `Bearer ${token}`;
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
  updateProfile: (payload: {
    name?: string;
    picture?: string;
    gender?: string;
    age?: number;
  }) => request<ApiUser>("/auth/me", { method: "PATCH", body: payload }),

  // ---- Groups ----
  listGroups: (category?: string, q?: string) => {
    const qs = new URLSearchParams();
    if (category && category !== "all") qs.append("category", category);
    if (q) qs.append("q", q);
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

  // ---- Chat ----
  getMessages: (id: string) => request<ApiMessage[]>(`/groups/${id}/messages`),
  postMessage: (id: string, text: string) =>
    request<ApiMessage>(`/groups/${id}/messages`, {
      method: "POST",
      body: { text },
    }),
};
