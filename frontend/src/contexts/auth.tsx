import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useRef,
} from "react";
import { Platform } from "react-native";
import {
  User as FirebaseUser,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  sendEmailVerification,
  sendPasswordResetEmail,
  signOut as fbSignOut,
  updateProfile as fbUpdateProfile,
  GoogleAuthProvider,
  OAuthProvider,
  signInWithCredential,
  signInWithPopup,
  reload,
} from "firebase/auth";

import { auth, GOOGLE_WEB_CLIENT_ID, GOOGLE_IOS_CLIENT_ID } from "@/src/lib/firebase";
import { api, ApiUser } from "@/src/lib/api";

type AuthContextValue = {
  fbUser: FirebaseUser | null;
  user: ApiUser | null;
  loading: boolean;
  emailVerified: boolean;
  needsEmailVerification: boolean;

  signInWithEmail: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, name: string) => Promise<void>;
  signInWithGoogle: () => Promise<void>;
  signInWithApple: () => Promise<void>;
  requestPasswordReset: (email: string) => Promise<void>;
  resendVerificationEmail: () => Promise<void>;
  reloadVerification: () => Promise<boolean>;
  signOut: () => Promise<void>;
  refreshMe: () => Promise<void>;
  setUser: (u: ApiUser | null) => void;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

// Turn Firebase auth error codes into friendly Italian messages.
function toItalianError(code?: string, fallback = "Errore di autenticazione"): string {
  const map: Record<string, string> = {
    "auth/invalid-email": "Email non valida",
    "auth/user-disabled": "Account disabilitato",
    "auth/user-not-found": "Nessun account trovato con questa email",
    "auth/wrong-password": "Password errata",
    "auth/invalid-credential": "Email o password non validi",
    "auth/invalid-login-credentials": "Email o password non validi",
    "auth/email-already-in-use": "Email già registrata",
    "auth/weak-password": "La password deve avere almeno 6 caratteri",
    "auth/network-request-failed": "Nessuna connessione a Internet",
    "auth/too-many-requests": "Troppi tentativi, riprova più tardi",
    "auth/popup-closed-by-user": "Accesso annullato",
    "auth/cancelled-popup-request": "Accesso annullato",
    "auth/operation-not-allowed": "Provider non abilitato in Firebase Console",
  };
  return (code && map[code]) || fallback;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [fbUser, setFbUser] = useState<FirebaseUser | null>(null);
  const [user, setUser] = useState<ApiUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [emailVerified, setEmailVerified] = useState(false);
  const initializedRef = useRef(false);

  const refreshMe = useCallback(async () => {
    try {
      const me = await api.me();
      setUser(me);
    } catch (e) {
      // Token may have expired; sign out.
      console.warn("refreshMe failed", e);
    }
  }, []);

  // Firebase auth state listener
  useEffect(() => {
    const unsub = onAuthStateChanged(auth, async (u) => {
      setFbUser(u);
      if (!u) {
        setUser(null);
        setEmailVerified(false);
        setLoading(false);
        initializedRef.current = true;
        return;
      }
      // Determine verification: email/password requires flag, social providers auto-verify.
      const providers = u.providerData.map((p) => p.providerId);
      const isSocial = providers.some((p) => p !== "password");
      const verified = u.emailVerified || isSocial;
      setEmailVerified(verified);

      if (verified) {
        // Fetch (or auto-create) backend profile.
        try {
          const me = await api.me();
          setUser(me);
        } catch (e) {
          console.warn("api.me() failed after auth", e);
          setUser(null);
        }
      } else {
        setUser(null);
      }
      setLoading(false);
      initializedRef.current = true;
    });
    return () => unsub();
  }, []);

  // ---- Email/Password ----
  const signInWithEmail = useCallback(async (email: string, password: string) => {
    try {
      await signInWithEmailAndPassword(auth, email.trim(), password);
    } catch (e: any) {
      throw new Error(toItalianError(e?.code, e?.message));
    }
  }, []);

  const signUp = useCallback(
    async (email: string, password: string, name: string) => {
      try {
        const cred = await createUserWithEmailAndPassword(auth, email.trim(), password);
        if (name.trim()) {
          await fbUpdateProfile(cred.user, { displayName: name.trim() });
        }
        await sendEmailVerification(cred.user);
      } catch (e: any) {
        throw new Error(toItalianError(e?.code, e?.message));
      }
    },
    [],
  );

  const requestPasswordReset = useCallback(async (email: string) => {
    try {
      await sendPasswordResetEmail(auth, email.trim());
    } catch (e: any) {
      throw new Error(toItalianError(e?.code, e?.message));
    }
  }, []);

  const resendVerificationEmail = useCallback(async () => {
    if (!auth.currentUser) throw new Error("Utente non autenticato");
    try {
      await sendEmailVerification(auth.currentUser);
    } catch (e: any) {
      throw new Error(toItalianError(e?.code, e?.message));
    }
  }, []);

  const reloadVerification = useCallback(async () => {
    if (!auth.currentUser) return false;
    try {
      await reload(auth.currentUser);
      const ok = !!auth.currentUser.emailVerified;
      setEmailVerified(ok);
      if (ok) {
        try {
          const me = await api.me();
          setUser(me);
        } catch {}
      }
      return ok;
    } catch {
      return false;
    }
  }, []);

  // ---- Google ----
  const signInWithGoogle = useCallback(async () => {
    try {
      if (Platform.OS === "web") {
        const provider = new GoogleAuthProvider();
        await signInWithPopup(auth, provider);
        return;
      }
      // Native: @react-native-google-signin
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const { GoogleSignin, statusCodes } = require("@react-native-google-signin/google-signin");
      GoogleSignin.configure({
        webClientId: GOOGLE_WEB_CLIENT_ID,
        iosClientId: GOOGLE_IOS_CLIENT_ID,
        offlineAccess: false,
      });
      await GoogleSignin.hasPlayServices({ showPlayServicesUpdateDialog: true });
      const info = await GoogleSignin.signIn();
      // The library returns { data: { idToken, ... } } in v13+, or flat in older.
      const idToken =
        (info && info.data && info.data.idToken) ||
        (info && (info as any).idToken) ||
        null;
      if (!idToken) throw new Error("Google non ha fornito un token");
      const credential = GoogleAuthProvider.credential(idToken);
      await signInWithCredential(auth, credential);
      // Silence unused var
      void statusCodes;
    } catch (e: any) {
      if (e?.code === "SIGN_IN_CANCELLED" || e?.code === "-5") return;
      throw new Error(toItalianError(e?.code, e?.message || "Errore accesso Google"));
    }
  }, []);

  // ---- Apple ----
  const signInWithApple = useCallback(async () => {
    if (Platform.OS !== "ios") {
      throw new Error("Apple Sign-In è disponibile solo su iOS");
    }
    try {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const AppleAuthentication = require("expo-apple-authentication");
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const Crypto = require("expo-crypto");
      // Generate a nonce to bind the token, then hash it for Apple.
      const rawNonce = Math.random().toString(36).slice(2) + Date.now().toString(36);
      const hashedNonce = await Crypto.digestStringAsync(
        Crypto.CryptoDigestAlgorithm.SHA256,
        rawNonce,
      );
      const credential = await AppleAuthentication.signInAsync({
        requestedScopes: [
          AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
          AppleAuthentication.AppleAuthenticationScope.EMAIL,
        ],
        nonce: hashedNonce,
      });
      if (!credential.identityToken) {
        throw new Error("Apple non ha fornito un token");
      }
      const provider = new OAuthProvider("apple.com");
      const authCred = provider.credential({
        idToken: credential.identityToken,
        rawNonce,
      });
      const result = await signInWithCredential(auth, authCred);
      // First-time only: Apple returns fullName. Persist it into Firebase profile.
      const fullName = credential.fullName;
      const display = fullName
        ? [fullName.givenName, fullName.familyName].filter(Boolean).join(" ")
        : "";
      if (display && result.user && !result.user.displayName) {
        await fbUpdateProfile(result.user, { displayName: display });
      }
    } catch (e: any) {
      if (e?.code === "ERR_REQUEST_CANCELED" || e?.code === "ERR_CANCELED") return;
      throw new Error(toItalianError(e?.code, e?.message || "Errore accesso Apple"));
    }
  }, []);

  const signOut = useCallback(async () => {
    try {
      // If Google native session exists, sign out from that too.
      if (Platform.OS !== "web") {
        try {
          // eslint-disable-next-line @typescript-eslint/no-var-requires
          const { GoogleSignin } = require("@react-native-google-signin/google-signin");
          const isSignedIn = await GoogleSignin.getCurrentUser();
          if (isSignedIn) await GoogleSignin.signOut();
        } catch {}
      }
      await fbSignOut(auth);
    } catch (e) {
      console.warn("signOut error", e);
    }
  }, []);

  const needsEmailVerification = !!fbUser && !emailVerified;

  return (
    <AuthContext.Provider
      value={{
        fbUser,
        user,
        loading,
        emailVerified,
        needsEmailVerification,
        signInWithEmail,
        signUp,
        signInWithGoogle,
        signInWithApple,
        requestPasswordReset,
        resendVerificationEmail,
        reloadVerification,
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
