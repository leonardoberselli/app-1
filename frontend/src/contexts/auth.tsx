import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
} from "react";
import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { api, ApiUser } from "@/src/lib/api";

const DEVICE_ID_KEY = "@groupup/device_id";

function makeId(): string {
  // 32 char hex device id (enough uniqueness for our needs)
  const bytes = new Uint8Array(16);
  if (typeof globalThis.crypto !== "undefined" && globalThis.crypto.getRandomValues) {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
  }
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function loadDeviceId(): Promise<string> {
  try {
    let id = await AsyncStorage.getItem(DEVICE_ID_KEY);
    if (id && id.length >= 16) return id;
    id = "dev_" + makeId();
    await AsyncStorage.setItem(DEVICE_ID_KEY, id);
    return id;
  } catch {
    // If storage fails, at least run this session with a random id
    return "dev_" + makeId();
  }
}

type AuthContextValue = {
  // for backward compat with old screens
  fbUser: { uid: string } | null;
  user: ApiUser | null;
  loading: boolean;
  authError: string | null;
  emailVerified: boolean;
  needsEmailVerification: boolean;
  deviceId: string | null;
  signOut: () => Promise<void>;
  refreshMe: () => Promise<void>;
  setUser: (u: ApiUser | null) => void;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

/**
 * Auth-less mode: on first launch we generate a random device ID and store it
 * locally. It is sent as a Bearer token on every API call. The backend uses
 * this ID as the user identifier — no login required, users just open the app
 * and are in. The user can edit their name/avatar/gender/age in the profile.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [user, setUser] = useState<ApiUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);

  const refreshMe = useCallback(async () => {
    try {
      const me = await api.me();
      setUser(me);
    } catch (e) {
      console.warn("refreshMe failed", e);
    }
  }, []);

  useEffect(() => {
    (async () => {
      const id = await loadDeviceId();
      // expose the id globally so api.ts can read it synchronously
      (globalThis as any).__GROUPUP_DEVICE_ID__ = id;
      setDeviceId(id);
      try {
        const me = await api.me();
        setUser(me);
      } catch (e: any) {
        console.warn("api.me failed", e);
        setAuthError(e?.message || "Errore di connessione");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const signOut = useCallback(async () => {
    // "Reset device" — new random ID, backend will auto-create a new user.
    try {
      await AsyncStorage.removeItem(DEVICE_ID_KEY);
      const id = await loadDeviceId();
      (globalThis as any).__GROUPUP_DEVICE_ID__ = id;
      setDeviceId(id);
      try {
        const me = await api.me();
        setUser(me);
      } catch {}
    } catch (e) {
      console.warn("signOut failed", e);
    }
    // Suppress "unused" warning on web-only branch
    void Platform.OS;
  }, []);

  return (
    <AuthContext.Provider
      value={{
        fbUser: deviceId ? { uid: deviceId } : null,
        user,
        loading,
        authError,
        emailVerified: true,
        needsEmailVerification: false,
        deviceId,
        signOut,
        refreshMe,
        setUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
