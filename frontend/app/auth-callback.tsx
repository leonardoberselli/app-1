import { useEffect, useRef, useState } from "react";
import { View, Text, ActivityIndicator, StyleSheet } from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import * as Linking from "expo-linking";

import { useAuth } from "@/src/contexts/auth";

/**
 * Deep-link landing page used ONLY as the OAuth callback target.
 *
 * The auth flow returns to `exp://<host>/--/auth-callback` (or in a
 * standalone build to `groupup://auth-callback`) with the Emergent session_id
 * appended either as `#session_id=` (default for the Emergent auth SPA) or
 * `?session_id=` (some browser/OS combinations rewrite hash → query when
 * bouncing through an intent).
 *
 * We grab it from every possible source and hand it to the AuthContext.
 */
export default function AuthCallbackScreen() {
  const router = useRouter();
  const { checkPendingSession, user, loading } = useAuth();
  const params = useLocalSearchParams<{ session_id?: string | string[] }>();
  const [status, setStatus] = useState<string>("Completo l'accesso in corso…");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    (async () => {
      // 1) Try the expo-router query param first (works if session_id came
      //    as `?session_id=` instead of `#session_id=`).
      let sid: string | null = null;
      const raw = params?.session_id;
      if (typeof raw === "string" && raw.length > 0) sid = raw;
      else if (Array.isArray(raw) && raw[0]) sid = raw[0];

      // 2) Fall back to reading the initial URL directly — this preserves
      //    the URL fragment which expo-router does NOT parse.
      if (!sid) {
        try {
          const url = await Linking.getInitialURL();
          if (url) {
            const m = url.match(/[?#&]session_id=([^&#]+)/);
            if (m) sid = decodeURIComponent(m[1]);
          }
        } catch {}
      }

      console.log("[GroupUp AuthCallback] extracted session_id =", sid);

      if (!sid) {
        // 3) Last resort: hand the URL to the auth context which has its
        //    own capturedUrlRef + getInitialURL fallback.
        const res = await checkPendingSession();
        if (!res.ok) {
          setStatus(res.error || "Accesso non riuscito. Torna alla schermata di login.");
          setTimeout(() => router.replace("/login"), 1500);
          return;
        }
        // On success the effect below will redirect once `user` updates.
        return;
      }

      // We have a session_id — the AuthContext's URL listener will pick it
      // up too, but let's proactively call the exchange to shorten latency.
      // Reuse the checkPendingSession path by manually pushing the URL into
      // Linking (already captured) — simpler: call the raw exchange via
      // context. checkPendingSession already scans capturedUrlRef/initialURL,
      // but here we already have the sid, so we import & call the same
      // helper is not exposed. Simplest: rely on the global listener +
      // checkPendingSession to consume the initial URL.
      const res = await checkPendingSession();
      if (!res.ok) {
        setStatus(res.error || "Accesso non riuscito.");
        setTimeout(() => router.replace("/login"), 1500);
      }
    })();
  }, [params, checkPendingSession, router]);

  // Once the user is populated (either by this screen's exchange or by the
  // AuthContext's global URL listener) → send them onward.
  useEffect(() => {
    if (loading) return;
    if (user) router.replace("/");
  }, [user, loading, router]);

  return (
    <View style={styles.container}>
      <ActivityIndicator size="large" color="#0A0A0A" />
      <Text style={styles.text}>{status}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    gap: 16,
    backgroundColor: "#FDFBF7",
  },
  text: {
    color: "#0A0A0A",
    fontSize: 15,
    fontWeight: "700",
    textAlign: "center",
  },
});
