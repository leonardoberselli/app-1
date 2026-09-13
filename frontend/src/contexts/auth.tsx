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
import * as AppleAuthentication from "expo-apple-authentication";

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
  // Google (Emergent Managed).
  signIn: () => Promise<{ ok: boolean; error?: string }>;
  checkPendingSession: () => Promise<{ ok: boolean; error?: string }>;
  // Email + password.
  signUpWithPassword: (
    email: string,
    password: string,
    name?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  signInWithPassword: (
    email: string,
    password: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  requestPasswordReset: (email: string) => Promise<{ ok: boolean; error?: string }>;
  confirmPasswordReset: (
    token: string,
    newPassword: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  verifyEmail: (token: string) => Promise<{ ok: boolean; error?: string }>;
  // Apple.
  appleAvailable: boolean;
  signInWithApple: () => Promise<{ ok: boolean; error?: string }>;
  // Session lifecycle.
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
  const [appleAvailable, setAppleAvailable] = useState(false);

  // Captures deep-link URLs that arrive while the auth-session is open.
  // On Android, openAuthSessionAsync frequently returns `dismiss` with no URL
  // even after a successful login, so we must keep this fallback.
  const capturedUrlRef = useRef<string | null>(null);

  // Apple Sign-In is iOS-only (iOS 13+); guard so the button never appears
  // on Android/web where the native module is a no-op.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (Platform.OS !== "ios") return;
      try {
        const ok = await AppleAuthentication.isAvailableAsync();
        if (!cancelled) setAppleAvailable(!!ok);
      } catch {
        if (!cancelled) setAppleAvailable(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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
      console.log("[Barrio Auth] redirectUrl =", redirectUrl);
      console.log("[Barrio Auth] authUrl =", authUrl);
      (globalThis as any).__GROUPUP_LAST_REDIRECT_URL__ = redirectUrl;
      (globalThis as any).__GROUPUP_LAST_AUTH_URL__ = authUrl;

      capturedUrlRef.current = null;
      const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUrl, {
        // iOS: private session so login is not tied to Safari cookies.
        preferEphemeralSession: true,
      });
      console.log("[Barrio Auth] openAuthSessionAsync result =", JSON.stringify(result));

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
      console.log("[Barrio Auth] callback url =", url);

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

  // ---------- Email + password ----------
  // All three flows share the same "adopt a fresh session_token" mechanic
  // so the auth state is single-sourced from the users collection.
  const adoptSession = useCallback(async (token: string, u?: ApiUser) => {
    await sessionStore.set(token);
    (globalThis as any).__GROUPUP_SESSION_TOKEN__ = token;
    if (u) setUser(u);
    else await refreshMe();
  }, [refreshMe]);

  const signUpWithPassword = useCallback(
    async (email: string, password: string, name?: string) => {
      setAuthError(null);
      setSigningIn(true);
      try {
        const data = await api.register({
          email: email.trim().toLowerCase(),
          password,
          name: name?.trim() || undefined,
        });
        await adoptSession(data.session_token, data.user);
        return { ok: true } as const;
      } catch (e: any) {
        const msg = e?.message || "Errore di registrazione";
        setAuthError(msg);
        return { ok: false, error: msg } as const;
      } finally {
        setSigningIn(false);
      }
    },
    [adoptSession],
  );

  const signInWithPassword = useCallback(
    async (email: string, password: string) => {
      setAuthError(null);
      setSigningIn(true);
      try {
        const data = await api.loginPassword({
          email: email.trim().toLowerCase(),
          password,
        });
        await adoptSession(data.session_token, data.user);
        return { ok: true } as const;
      } catch (e: any) {
        const msg = e?.message || "Errore di accesso";
        setAuthError(msg);
        return { ok: false, error: msg } as const;
      } finally {
        setSigningIn(false);
      }
    },
    [adoptSession],
  );

  const requestPasswordReset = useCallback(async (email: string) => {
    try {
      await api.requestPasswordReset(email.trim().toLowerCase());
      return { ok: true } as const;
    } catch (e: any) {
      // The backend deliberately returns 200 whether or not the email exists,
      // so any error we see here is a real network/server fault.
      return { ok: false, error: e?.message || "Errore di rete" } as const;
    }
  }, []);

  const confirmPasswordReset = useCallback(
    async (token: string, newPassword: string) => {
      try {
        await api.confirmPasswordReset(token, newPassword);
        // Reset invalidates all sessions server-side; make sure we don't
        // keep a stale token in secure store.
        await sessionStore.clear();
        (globalThis as any).__GROUPUP_SESSION_TOKEN__ = null;
        setUser(null);
        return { ok: true } as const;
      } catch (e: any) {
        return { ok: false, error: e?.message || "Errore reset password" } as const;
      }
    },
    [],
  );

  const verifyEmail = useCallback(async (token: string) => {
    try {
      await api.verifyEmail(token);
      // If the user is currently logged in, refresh /me so email_verified flips true.
      try {
        await refreshMe();
      } catch {}
      return { ok: true } as const;
    } catch (e: any) {
      return { ok: false, error: e?.message || "Token non valido o scaduto" } as const;
    }
  }, [refreshMe]);

  // ---------- Apple Sign-In ----------
  const signInWithApple = useCallback(async () => {
    setAuthError(null);
    if (Platform.OS !== "ios") {
      return { ok: false, error: "Apple Sign-In è disponibile solo su iOS" } as const;
    }
    setSigningIn(true);
    try {
      // Double-check availability at the last moment. Some iOS
      // configurations (e.g. running on an iPad without Apple ID configured)
      // will throw here instead of returning `false`.
      try {
        const ok = await AppleAuthentication.isAvailableAsync();
        if (!ok) {
          return {
            ok: false,
            error:
              "Apple Sign-In non è disponibile su questo dispositivo. Verifica di aver effettuato l'accesso ad un Apple ID nelle impostazioni iOS.",
          } as const;
        }
      } catch {
        // ignore — the actual signInAsync call below will surface any
        // deeper issue with a specific error code.
      }
      const credential = await AppleAuthentication.signInAsync({
        requestedScopes: [
          AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
          AppleAuthentication.AppleAuthenticationScope.EMAIL,
        ],
      });
      const identity = credential.identityToken;
      if (!identity) {
        return { ok: false, error: "Apple non ha restituito il token di identità" } as const;
      }
      const fullName = [credential.fullName?.givenName, credential.fullName?.familyName]
        .filter(Boolean)
        .join(" ")
        .trim();
      const data = await api.appleSignIn({
        identity_token: identity,
        email: credential.email ?? null,
        full_name: fullName || null,
      });
      await adoptSession(data.session_token, data.user);
      return { ok: true } as const;
    } catch (e: any) {
      // Cancelled by the user — treat as a silent no-op instead of an error.
      if (e?.code === "ERR_REQUEST_CANCELED" || e?.code === "ERR_CANCELED") {
        return { ok: false } as const;
      }
      // Map common Apple / backend errors to human-readable messages.
      let msg = e?.message || "Errore Apple Sign-In";
      if (e?.code === "ERR_REQUEST_NOT_HANDLED") {
        msg =
          "iOS non ha completato la richiesta ad Apple. Riprova tra qualche secondo o verifica la tua connessione.";
      } else if (e?.code === "ERR_REQUEST_FAILED") {
        msg = "Richiesta Apple fallita. Riprova.";
      } else if (e?.code === "ERR_INVALID_RESPONSE") {
        msg = "Risposta Apple non valida. Riprova o usa Google/email.";
      } else if (/Identity token Apple non valido/i.test(msg)) {
        msg =
          "Il token Apple non è stato accettato dal server. Se stai usando Expo Go, prova con una build reale (TestFlight).";
      }
      console.warn("signInWithApple failed", e?.code, e?.message);
      setAuthError(msg);
      return { ok: false, error: msg } as const;
    } finally {
      setSigningIn(false);
    }
  }, [adoptSession]);

  const value: AuthContextValue = {
    user,
    loading,
    signingIn,
    authError,
    deviceId: user?.user_id ?? null,
    fbUser: user?.user_id ? { uid: user.user_id } : null,
    emailVerified: user?.email_verified !== false,
    needsEmailVerification: user != null && user.email_verified === false,
    signIn,
    checkPendingSession,
    signUpWithPassword,
    signInWithPassword,
    requestPasswordReset,
    confirmPasswordReset,
    verifyEmail,
    appleAvailable,
    signInWithApple,
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
