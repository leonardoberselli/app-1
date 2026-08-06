import { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ActivityIndicator,
  TouchableOpacity,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/contexts/auth";
import { api } from "@/src/lib/api";

export default function VerifyEmail() {
  const { token } = useLocalSearchParams<{ token?: string }>();
  const { applySession } = useAuth();
  const router = useRouter();
  const [state, setState] = useState<"loading" | "ok" | "error">("loading");
  const [error, setError] = useState<string>("Link non valido");

  useEffect(() => {
    if (!token) {
      setState("error");
      setError("Manca il token di verifica");
      return;
    }
    (async () => {
      try {
        const res = await api.verifyEmail(token);
        await applySession(res.session_token, res.user);
        setState("ok");
        setTimeout(() => router.replace("/"), 1200);
      } catch (e: any) {
        setError(e?.message || "Verifica fallita");
        setState("error");
      }
    })();
  }, [token, applySession, router]);

  return (
    <SafeAreaView style={styles.container} testID="verify-email-screen">
      <View style={styles.center}>
        {state === "loading" && (
          <>
            <ActivityIndicator size="large" color="#FF4747" />
            <Text style={styles.title}>Verifica in corso…</Text>
          </>
        )}
        {state === "ok" && (
          <>
            <Text style={{ fontSize: 60 }}>✅</Text>
            <Text style={styles.title}>Email verificata!</Text>
            <Text style={styles.sub}>Ti stiamo portando dentro l&apos;app…</Text>
          </>
        )}
        {state === "error" && (
          <>
            <Text style={{ fontSize: 60 }}>⚠️</Text>
            <Text style={styles.title}>Errore</Text>
            <Text style={styles.sub}>{error}</Text>
            <TouchableOpacity
              testID="back-login"
              onPress={() => router.replace("/login")}
              style={styles.btn}
              activeOpacity={0.85}
            >
              <Ionicons name="log-in" size={18} color="#0A0A0A" />
              <Text style={styles.btnText}>Vai al login</Text>
            </TouchableOpacity>
          </>
        )}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FDFBF7" },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 32,
    gap: 14,
  },
  title: { fontSize: 24, fontWeight: "900", color: "#0A0A0A", marginTop: 6 },
  sub: { color: "#525252", fontSize: 15, textAlign: "center", lineHeight: 22 },
  btn: {
    marginTop: 20,
    backgroundColor: "#FFE600",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingHorizontal: 24,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  btnText: { fontWeight: "900", color: "#0A0A0A", letterSpacing: 0.5 },
});
