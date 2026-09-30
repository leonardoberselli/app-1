import { useEffect, useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import { useAuth } from "@/src/contexts/auth";

type State = "loading" | "success" | "error";

export default function VerifyEmailScreen() {
  const { verifyEmail, user } = useAuth();
  const router = useRouter();
  const { token } = useLocalSearchParams<{ token?: string }>();
  const [state, setState] = useState<State>("loading");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      if (!token || typeof token !== "string") {
        setErr("Link di verifica non valido o mancante");
        setState("error");
        return;
      }
      const res = await verifyEmail(token);
      if (res.ok) {
        setState("success");
      } else {
        setErr(res.error || "Token non valido o scaduto");
        setState("error");
      }
    })();
    // Intentionally run once on mount; token is a route param.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <Stack.Screen options={{ title: "Verifica email" }} />
      <View style={styles.wrap}>
        {state === "loading" ? (
          <>
            <ActivityIndicator size="large" color="#FF4747" />
            <Text style={styles.title}>Sto verificando la tua email…</Text>
          </>
        ) : state === "success" ? (
          <>
            <Text style={styles.emoji}>🎉</Text>
            <Text style={styles.title}>Email verificata!</Text>
            <Text style={styles.subtitle}>
              Grazie {user?.name || ""}, il tuo account Barrio 24 è ora
              completamente attivo.
            </Text>
            <TouchableOpacity
              testID="verify-continue"
              onPress={() => router.replace(user ? "/" : "/login")}
              activeOpacity={0.9}
              style={styles.primaryBtn}
            >
              <Text style={styles.primaryBtnText}>Continua</Text>
            </TouchableOpacity>
          </>
        ) : (
          <>
            <Ionicons name="alert-circle" size={64} color="#FF4747" />
            <Text style={styles.title}>Verifica fallita</Text>
            <Text style={styles.subtitle}>{err}</Text>
            <Text style={styles.subtitle}>
              Prova a richiedere un nuovo link di verifica dal tuo profilo.
            </Text>
            <TouchableOpacity
              onPress={() => router.replace(user ? "/" : "/login")}
              activeOpacity={0.9}
              style={styles.primaryBtn}
            >
              <Text style={styles.primaryBtnText}>Torna all&apos;app</Text>
            </TouchableOpacity>
          </>
        )}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FDFBF7" },
  wrap: {
    flex: 1,
    padding: 32,
    justifyContent: "center",
    alignItems: "center",
    gap: 16,
  },
  emoji: { fontSize: 72 },
  title: {
    fontSize: 26,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: -0.5,
    textAlign: "center",
  },
  subtitle: {
    textAlign: "center",
    color: "#525252",
    fontSize: 15,
    fontWeight: "600",
    lineHeight: 22,
  },
  primaryBtn: {
    backgroundColor: "#FF4747",
    borderRadius: 999,
    paddingVertical: 15,
    paddingHorizontal: 40,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    marginTop: 8,
  },
  primaryBtnText: { color: "#FFFFFF", fontWeight: "900", fontSize: 16, letterSpacing: 0.3 },
});
