const BASE = process.env.EXPO_PUBLIC_BACKEND_URL;

export type ApiUser = {
  user_id: string;
  email: string;
  name: string;
  picture?: string | null;
  gender?: "male" | "female" | "other" | null;
  age?: number | null;
  profile_complete?: boolean;
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

async function request<T>(
  path: string,
  opts: { method?: string; body?: any; token?: string | null } = {},
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`;
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
  authSession: (session_id: string) =>
    request<{ session_token: string; user: ApiUser }>("/auth/session", {
      method: "POST",
      body: { session_id },
    }),
  signup: (email: string, password: string, name: string) =>
    request<{ message: string }>("/auth/signup", {
      method: "POST",
      body: { email, password, name },
    }),
  login: (email: string, password: string) =>
    request<{ session_token: string; user: ApiUser }>("/auth/login", {
      method: "POST",
      body: { email, password },
    }),
  verifyEmail: (token: string) =>
    request<{ session_token: string; user: ApiUser }>("/auth/verify-email", {
      method: "POST",
      body: { token },
    }),
  requestPasswordReset: (email: string) =>
    request<{ message: string }>("/auth/request-password-reset", {
      method: "POST",
      body: { email },
    }),
  confirmReset: (token: string, new_password: string) =>
    request<{ message: string }>("/auth/confirm-reset", {
      method: "POST",
      body: { token, new_password },
    }),
  appleAuth: (identity_token: string, email?: string, full_name?: string) =>
    request<{ session_token: string; user: ApiUser }>("/auth/apple", {
      method: "POST",
      body: { identity_token, email, full_name },
    }),
  me: (token: string) => request<ApiUser>("/auth/me", { token }),
  updateProfile: (
    token: string,
    payload: { name?: string; picture?: string; gender?: string; age?: number },
  ) => request<ApiUser>("/auth/me", { method: "PATCH", body: payload, token }),
  logout: (token: string) => request<{ ok: boolean }>("/auth/logout", { method: "POST", token }),

  listGroups: (category?: string, q?: string) => {
    const qs = new URLSearchParams();
    if (category && category !== "all") qs.append("category", category);
    if (q) qs.append("q", q);
    const str = qs.toString();
    return request<ApiGroup[]>(`/groups${str ? `?${str}` : ""}`);
  },
  createGroup: (token: string, payload: Partial<ApiGroup>) =>
    request<ApiGroup>("/groups", { method: "POST", body: payload, token }),
  getGroup: (id: string) => request<ApiGroup>(`/groups/${id}`),
  joinGroup: (token: string, id: string) =>
    request<ApiGroup>(`/groups/${id}/join`, { method: "POST", token }),
  leaveGroup: (token: string, id: string) =>
    request<ApiGroup>(`/groups/${id}/leave`, { method: "POST", token }),
  deleteGroup: (token: string, id: string) =>
    request<{ ok: boolean }>(`/groups/${id}`, { method: "DELETE", token }),
  myGroups: (token: string) =>
    request<{ created: ApiGroup[]; joined: ApiGroup[] }>("/groups/mine", { token }),

  getMessages: (token: string, id: string) =>
    request<ApiMessage[]>(`/groups/${id}/messages`, { token }),
  postMessage: (token: string, id: string, text: string) =>
    request<ApiMessage>(`/groups/${id}/messages`, {
      method: "POST",
      body: { text },
      token,
    }),
};
