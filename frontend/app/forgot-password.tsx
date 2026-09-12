import { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack, useRouter } from "expo-router";

import { useAuth } from "@/src/contexts/auth";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function ForgotPasswordScreen() {
  const { requestPasswordReset } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const emailValid = EMAIL_RE.test(email.trim());

  const onSubmit = async () => {
    setErr(null);
    if (!emailValid) {
      setErr("Inserisci un'email valida");
      return;
    }
    setBusy(true);
    try {
      const res = await requestPasswordReset(email);
      if (res.ok) setSent(true);
      else setErr(res.error || "Errore di rete");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <Stack.Screen options={{ title: "Password dimenticata", headerBackTitle: "Indietro" }} />
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1 }}
      >
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <View style={styles.header}>
            <Text style={styles.emoji}>🔑</Text>
            <Text style={styles.title}>Reimposta password</Text>
            <Text style={styles.subtitle}>
              Inserisci l&apos;email del tuo account. Se esiste, ti invieremo un link
              per creare una nuova password.
            </Text>
          </View>

          {sent ? (
            <View style={styles.successBox} testID="forgot-success">
              <Ionicons name="checkmark-circle" size={22} color="#059669" />
              <Text style={styles.successText}>
                Se l&apos;account esiste, riceverai un&apos;email con le istruzioni per il
                reset entro pochi minuti. Controlla anche la cartella spam.
              </Text>
            </View>
          ) : (
            <>
              <View style={styles.field}>
                <Text style={styles.label}>Email</Text>
                <TextInput
                  testID="forgot-email"
                  value={email}
                  onChangeText={setEmail}
                  placeholder="tuonome@email.com"
                  placeholderTextColor="#A3A3A3"
                  autoCapitalize="none"
                  autoComplete="email"
                  autoCorrect={false}
                  keyboardType="email-address"
                  textContentType="emailAddress"
                  style={styles.input}
                />
              </View>

              {err ? (
                <View style={styles.errorBox}>
                  <Ionicons name="alert-circle" size={16} color="#FF4747" />
                  <Text style={styles.errorText}>{err}</Text>
                </View>
              ) : null}

              <TouchableOpacity
                testID="forgot-submit"
                onPress={onSubmit}
                disabled={busy || !emailValid}
                activeOpacity={0.9}
                style={[styles.primaryBtn, (busy || !emailValid) && { opacity: 0.5 }]}
              >
                {busy ? (
                  <ActivityIndicator color="#FFFFFF" />
                ) : (
                  <Text style={styles.primaryBtnText}>Invia link di reset</Text>
                )}
              </TouchableOpacity>
            </>
          )}

          <TouchableOpacity
            onPress={() => router.back()}
            style={{ paddingVertical: 12, alignItems: "center" }}
            activeOpacity={0.7}
          >
            <Text style={styles.backLink}>← Torna al login</Text>
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FDFBF7" },
  scroll: { padding: 20, gap: 20 },
  header: { alignItems: "center", gap: 8, marginTop: 12 },
  emoji: { fontSize: 60 },
  title: { fontSize: 26, fontWeight: "900", color: "#0A0A0A", letterSpacing: -0.5 },
  subtitle: {
    textAlign: "center",
    color: "#525252",
    fontSize: 14,
    fontWeight: "600",
    lineHeight: 20,
    paddingHorizontal: 8,
  },
  field: { gap: 6 },
  label: {
    fontSize: 12,
    fontWeight: "800",
    color: "#525252",
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
  input: {
    backgroundColor: "#FFFFFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    color: "#0A0A0A",
    fontWeight: "600",
  },
  primaryBtn: {
    backgroundColor: "#FF4747",
    borderRadius: 999,
    paddingVertical: 15,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 2,
    borderColor: "#0A0A0A",
  },
  primaryBtnText: { color: "#FFFFFF", fontWeight: "900", fontSize: 16, letterSpacing: 0.3 },
  errorBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "#FEE2E2",
    borderWidth: 2,
    borderColor: "#FF4747",
    borderRadius: 12,
    padding: 12,
  },
  errorText: { color: "#B91C1C", fontWeight: "700", flex: 1, fontSize: 13 },
  successBox: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 10,
    backgroundColor: "#D1FAE5",
    borderWidth: 2,
    borderColor: "#059669",
    borderRadius: 12,
    padding: 14,
  },
  successText: { color: "#065F46", fontWeight: "700", flex: 1, fontSize: 14, lineHeight: 20 },
  backLink: { color: "#0A0A0A", fontWeight: "800", fontSize: 14, textDecorationLine: "underline" },
});
