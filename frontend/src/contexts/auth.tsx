import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { Platform } from "react-native";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";

import { api, ApiUser } from "@/src/lib/api";
import { sessionStore } from "@/src/lib/session-store";

// Required by expo-auth-session / openAuthSessionAsync on web so the popup
// closes correctly on cold redirect. Safe to call at module scope.
WebBrowser.maybeCompleteAuthSession();

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL;
const EMERGENT_AUTH_URL = "https://auth.emergentagent.com/";
// Guards against exchanging the same session_id more than once (deep-link
// listener + openAuthSessionAsync result can both fire for the same link).
const _exchanged = new Set<string>();

function extractSessionId(rawUrl: string | null | undefined): string | null {
  if (!rawUrl) return null;
  // Emergent returns session_id in the URL FRAGMENT (hash). Linking.parse()
  // reads only the query string, so we must match the raw URL directly and
  // scan both `#session_id=` and `?session_id=`.
  const m = rawUrl.match(/[?#&]session_id=([^&#]+)/);
  if (!m) return null;
  try {
    return decodeURIComponent(m[1]);
  } catch {
    return m[1];
  }
}

type AuthContextValue = {
  user: ApiUser | null;
  loading: boolean;
  signingIn: boolean;
  authError: string | null;
  /**
   * Compat aliases kept so older screens (profile, create, group/[id],
   * profile-edit) keep working: they use `deviceId` purely as a readiness
   * flag. It now returns the authenticated user_id when logged in.
   */
  deviceId: string | null;
  fbUser: { uid: string } | null;
  emailVerified: boolean;
  needsEmailVerification: boolean;
  signIn: () => Promise<{ ok: boolean; error?: string }>;
  checkPendingSession: () => Promise<{ ok: boolean; error?: string }>;
  signOut: () => Promise<void>;
  refreshMe: () => Promise<void>;
  setUser: (u: ApiUser | null) => void;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<ApiUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [signingIn, setSigningIn] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  // Captures deep-link URLs that arrive while the auth-session is open.
  // On Android, openAuthSessionAsync frequently returns `dismiss` with no URL
  // even after a successful login, so we must keep this fallback.
  const capturedUrlRef = useRef<string | null>(null);

  const refreshMe = useCallback(async () => {
    try {
      const me = await api.me();
      setUser(me);
    } catch (e: any) {
      console.warn("refreshMe failed", e?.message || e);
      // 401 → session expired/revoked → drop it locally.
      if (typeof e?.message === "string" && /session|token/i.test(e.message)) {
        await sessionStore.clear();
        (globalThis as any).__GROUPUP_SESSION_TOKEN__ = null;
        setUser(null);
      }
    }
  }, []);

  const applySession = useCallback(
    async (session_id: string): Promise<{ ok: boolean; error?: string }> => {
      if (_exchanged.has(session_id)) return { ok: true };
      _exchanged.add(session_id);
      try {
        const resp = await fetch(`${BASE}/api/auth/session`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id }),
        });
        const text = await resp.text();
        const data = text ? JSON.parse(text) : null;
        if (!resp.ok) {
          const detail = (data && (data.detail || data.message)) || resp.statusText;
          return { ok: false, error: typeof detail === "string" ? detail : "Errore autenticazione" };
        }
        const token: string = data?.session_token;
        if (!token) return { ok: false, error: "Risposta autenticazione incompleta" };
        await sessionStore.set(token);
        (globalThis as any).__GROUPUP_SESSION_TOKEN__ = token;
        if (data?.user) setUser(data.user as ApiUser);
        return { ok: true };
      } catch (e: any) {
        return { ok: false, error: e?.message || "Errore di rete" };
      }
    },
    [],
  );

  // ---------- Web-only: strip session_id from the URL after exchange ----------
  const cleanWebUrl = useCallback(() => {
    if (Platform.OS !== "web") return;
    try {
      const w: any = globalThis as any;
      const url = new URL(w.location.href);
      // hash cleanup
      if (url.hash && url.hash.includes("session_id")) {
        const params = new URLSearchParams(url.hash.startsWith("#") ? url.hash.slice(1) : url.hash);
        params.delete("session_id");
        const rest = params.toString();
        url.hash = rest ? `#${rest}` : "";
      }
      if (url.searchParams.has("session_id")) {
        url.searchParams.delete("session_id");
      }
      w.history.replaceState(w.history.state, "", url.toString());
    } catch {}
  }, []);

  // ---------- Bootstrap: check for pending session_id, then existing token ----------
  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        // 1) Web cold start: session_id may be in window.location.
        if (Platform.OS === "web") {
          try {
            const w: any = globalThis as any;
            const href: string | undefined = w?.location?.href;
            const sid = extractSessionId(href);
            if (sid) {
              const res = await applySession(sid);
              cleanWebUrl();
              if (!cancelled && !res.ok) setAuthError(res.error || null);
            }
          } catch {}
        }

        // 2) Mobile cold start: check initial URL for a pending session_id.
        if (Platform.OS !== "web") {
          try {
            const initial = await Linking.getInitialURL();
            const sid = extractSessionId(initial);
            if (sid) {
              const res = await applySession(sid);
              if (!cancelled && !res.ok) setAuthError(res.error || null);
            }
          } catch {}
        }

        // 3) Existing session_token? Validate with /me.
        const token = await sessionStore.get();
        if (token) {
          (globalThis as any).__GROUPUP_SESSION_TOKEN__ = token;
          try {
            const me = await api.me();
            if (!cancelled) setUser(me);
          } catch (e: any) {
            // 401 → clear it silently, user will land on /login
            await sessionStore.clear();
            (globalThis as any).__GROUPUP_SESSION_TOKEN__ = null;
            if (!cancelled && e?.message && !/session|token|401/i.test(e.message)) {
              setAuthError(e.message);
            }
          }
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    // Mobile: listen for hot deep-links (relaunch via URL) while app is alive.
    let sub: { remove: () => void } | null = null;
    if (Platform.OS !== "web") {
      sub = Linking.addEventListener("url", (event) => {
        capturedUrlRef.current = event.url;
        const sid = extractSessionId(event.url);
        if (sid) {
          applySession(sid).then((res) => {
            if (!res.ok) setAuthError(res.error || null);
          });
        }
      });
    }

    return () => {
      cancelled = true;
      sub?.remove();
    };
  }, [applySession, cleanWebUrl]);

  // ---------- signIn: opens the Google auth flow ----------
  const signIn = useCallback(async (): Promise<{ ok: boolean; error?: string }> => {
    setAuthError(null);
    setSigningIn(true);
    try {
      if (Platform.OS === "web") {
        const w: any = globalThis as any;
        const redirectUrl = `${w.location.origin}/`;
        w.location.href = `${EMERGENT_AUTH_URL}?redirect=${encodeURIComponent(redirectUrl)}`;
        // Navigation replaces the whole page — nothing else to do here.
        return { ok: true };
      }

      // ---- Mobile ----
      // Use a specific path so the deep-link back is unambiguous and easier
      // for the OS to route back to Expo Go / the standalone build.
      const redirectUrl = Linking.createURL("auth-callback");
      const authUrl = `${EMERGENT_AUTH_URL}?redirect=${encodeURIComponent(redirectUrl)}`;
      console.log("[GroupUp Auth] redirectUrl =", redirectUrl);
      console.log("[GroupUp Auth] authUrl =", authUrl);
      (globalThis as any).__GROUPUP_LAST_REDIRECT_URL__ = redirectUrl;
      (globalThis as any).__GROUPUP_LAST_AUTH_URL__ = authUrl;

      capturedUrlRef.current = null;
      const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUrl, {
        // iOS: private session so login is not tied to Safari cookies.
        preferEphemeralSession: true,
      });
      console.log("[GroupUp Auth] openAuthSessionAsync result =", JSON.stringify(result));

      // Try each source in order: result.url → deep-link listener → getInitialURL.
      // On Android the deep link is often delivered *after* the promise
      // resolves with dismiss, so give the listener a beat to fire.
      let url: string | null = null;
      if (result.type === "success" && (result as any).url) {
        url = (result as any).url;
      }
      if (!url) {
        await new Promise((r) => setTimeout(r, 400));
      }
      if (!url && capturedUrlRef.current) url = capturedUrlRef.current;
      if (!url) {
        try {
          url = await Linking.getInitialURL();
        } catch {}
      }
      console.log("[GroupUp Auth] callback url =", url);

      const sid = extractSessionId(url);
      if (!sid) {
        const dismissed = result.type === "dismiss" || result.type === "cancel";
        const msg = dismissed
          ? "Accesso non completato. Se hai fatto login Google, torna qui e premi \"Ho già fatto login\"."
          : "Login non completato: l'app non è riuscita a ricevere la risposta di Google. Riprova.";
        return { ok: false, error: msg };
      }

      const res = await applySession(sid);
      if (!res.ok) setAuthError(res.error || null);
      return res;
    } catch (e: any) {
      const msg = e?.message || "Impossibile aprire il login";
      setAuthError(msg);
      return { ok: false, error: msg };
    } finally {
      setSigningIn(false);
    }
  }, [applySession]);

  // ---------- checkPendingSession ----------
  // Recovery for the Expo Go / Custom Tabs corner case where the deep link
  // fires but the promise resolves with dismiss/no url. After the user
  // manually returns to the app, this call retries all three sources.
  const checkPendingSession = useCallback(async (): Promise<{ ok: boolean; error?: string }> => {
    setAuthError(null);
    try {
      let url: string | null = null;
      if (capturedUrlRef.current) url = capturedUrlRef.current;
      if (!url) {
        try {
          url = await Linking.getInitialURL();
        } catch {}
      }
      if (Platform.OS === "web" && !url) {
        try {
          const w: any = globalThis as any;
          url = w?.location?.href || null;
        } catch {}
      }
      const sid = extractSessionId(url);
      if (!sid) return { ok: false, error: "Nessuna sessione in sospeso. Prova a rifare login." };
      const res = await applySession(sid);
      if (!res.ok) setAuthError(res.error || null);
      return res;
    } catch (e: any) {
      const msg = e?.message || "Errore imprevisto";
      setAuthError(msg);
      return { ok: false, error: msg };
    }
  }, [applySession]);

  // ---------- signOut ----------
  const signOut = useCallback(async () => {
    try {
      try {
        await api.logout();
      } catch {
        // ignore — best effort server revoke
      }
      await sessionStore.clear();
      (globalThis as any).__GROUPUP_SESSION_TOKEN__ = null;
      setUser(null);
      setAuthError(null);
    } catch (e) {
      console.warn("signOut failed", e);
    }
  }, []);

  const value: AuthContextValue = {
    user,
    loading,
    signingIn,
    authError,
    deviceId: user?.user_id ?? null,
    fbUser: user?.user_id ? { uid: user.user_id } : null,
    emailVerified: true,
    needsEmailVerification: false,
    signIn,
    checkPendingSession,
    signOut,
    refreshMe,
    setUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
