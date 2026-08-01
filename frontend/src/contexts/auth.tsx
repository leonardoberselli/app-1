import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { Platform } from "react-native";
import * as WebBrowser from "expo-web-browser";
import * as Linking from "expo-linking";

import { storage } from "@/src/utils/storage";
import { api, ApiUser } from "@/src/lib/api";

type AuthState = {
  user: ApiUser | null;
  token: string | null;
  loading: boolean;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
};

const TOKEN_KEY = "groupup.session_token";

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<ApiUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const persistToken = useCallback(async (t: string | null) => {
    if (Platform.OS === "web") {
      if (t) await storage.setItem(TOKEN_KEY, t);
      else await storage.removeItem(TOKEN_KEY);
    } else {
      if (t) await storage.secureSet(TOKEN_KEY, t);
      else await storage.secureRemove(TOKEN_KEY);
    }
  }, []);

  const loadToken = useCallback(async (): Promise<string | null> => {
    if (Platform.OS === "web") {
      return (await storage.getItem<string>(TOKEN_KEY, "")) || null;
    }
    return (await storage.secureGet<string>(TOKEN_KEY, "")) || null;
  }, []);

  const processSessionId = useCallback(
    async (sessionId: string) => {
      const res = await api.authSession(sessionId);
      await persistToken(res.session_token);
      setToken(res.session_token);
      setUser(res.user);
    },
    [persistToken],
  );

  const extractSessionId = useCallback((url: string | null): string | null => {
    if (!url) return null;
    try {
      // Match either #session_id=... or ?session_id=...
      const m = url.match(/[#?&]session_id=([^&]+)/);
      return m ? decodeURIComponent(m[1]) : null;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Web: check URL hash/query for session_id first.
        if (Platform.OS === "web" && typeof window !== "undefined") {
          const sid = extractSessionId(window.location.hash) ||
            extractSessionId(window.location.search);
          if (sid) {
            await processSessionId(sid);
            window.history.replaceState(null, "", window.location.pathname);
            if (!cancelled) setLoading(false);
            return;
          }
        } else {
          // Mobile: cold start deep link fallback.
          const initial = await Linking.getInitialURL();
          const sid = extractSessionId(initial);
          if (sid) {
            await processSessionId(sid);
            if (!cancelled) setLoading(false);
            return;
          }
        }

        // Existing stored token?
        const stored = await loadToken();
        if (stored) {
          try {
            const me = await api.me(stored);
            if (!cancelled) {
              setToken(stored);
              setUser(me);
            }
          } catch {
            await persistToken(null);
          }
        }
      } catch (e) {
        console.warn("auth init error", e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [extractSessionId, loadToken, persistToken, processSessionId]);

  // Mobile: hot deep links
  useEffect(() => {
    if (Platform.OS === "web") return;
    const sub = Linking.addEventListener("url", async (event) => {
      const sid = extractSessionId(event.url);
      if (sid) {
        try {
          await processSessionId(sid);
        } catch (e) {
          console.warn("processSessionId hot", e);
        }
      }
    });
    return () => sub.remove();
  }, [extractSessionId, processSessionId]);

  const signIn = useCallback(async () => {
    const redirectUrl =
      Platform.OS === "web" && typeof window !== "undefined"
        ? `${window.location.origin}/`
        : Linking.createURL("auth");
    const authUrl = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;

    if (Platform.OS === "web" && typeof window !== "undefined") {
      window.location.href = authUrl;
      return;
    }
    const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUrl);
    if (result.type === "success" && result.url) {
      const sid = extractSessionId(result.url);
      if (sid) {
        await processSessionId(sid);
      }
    }
  }, [extractSessionId, processSessionId]);

  const signOut = useCallback(async () => {
    try {
      if (token) await api.logout(token);
    } catch {}
    await persistToken(null);
    setToken(null);
    setUser(null);
  }, [persistToken, token]);

  return (
    <AuthContext.Provider value={{ user, token, loading, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
