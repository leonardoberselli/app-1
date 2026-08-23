import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

// SecureStore rejects keys containing '@', '/', spaces, etc. — use a plain slug.
const KEY = "groupup_session_token";

/**
 * Cross-platform storage for the Emergent session_token.
 *
 * - Mobile: expo-secure-store (encrypted Keychain / EncryptedSharedPreferences)
 * - Web: localStorage (SecureStore is a no-op on web; per Emergent guidance
 *   we accept localStorage there and never fall back to AsyncStorage).
 */
export const sessionStore = {
  async get(): Promise<string | null> {
    if (Platform.OS === "web") {
      try {
        if (typeof globalThis !== "undefined" && (globalThis as any).localStorage) {
          return (globalThis as any).localStorage.getItem(KEY);
        }
      } catch {}
      return null;
    }
    try {
      return await SecureStore.getItemAsync(KEY);
    } catch (e) {
      console.warn("sessionStore.get failed", e);
      return null;
    }
  },

  async set(token: string): Promise<void> {
    if (Platform.OS === "web") {
      try {
        (globalThis as any).localStorage?.setItem(KEY, token);
      } catch {}
      return;
    }
    try {
      await SecureStore.setItemAsync(KEY, token);
    } catch (e) {
      console.warn("sessionStore.set failed", e);
    }
  },

  async clear(): Promise<void> {
    if (Platform.OS === "web") {
      try {
        (globalThis as any).localStorage?.removeItem(KEY);
      } catch {}
      return;
    }
    try {
      await SecureStore.deleteItemAsync(KEY);
    } catch (e) {
      console.warn("sessionStore.clear failed", e);
    }
  },
};
