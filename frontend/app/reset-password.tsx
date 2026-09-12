import { useMemo, useState } from "react";
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
import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import { useAuth } from "@/src/contexts/auth";

const PASSWORD_RE = /^(?=.*[A-Za-z])(?=.*\d).{8,128}$/;

export default function ResetPasswordScreen() {
  const { confirmPasswordReset } = useAuth();
  const router = useRouter();
  const { token } = useLocalSearchParams<{ token?: string }>();

  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const pwValid = useMemo(() => PASSWORD_RE.test(pw), [pw]);
  const match = pw.length > 0 && pw === confirm;

  const onSubmit = async () => {
    setErr(null);
    if (!token || typeof token !== "string") {
      setErr("Link di reset non valido. Richiedine uno nuovo.");
      return;
    }
    if (!pwValid) {
      setErr("Password: minimo 8 caratteri con almeno una lettera e un numero");
      return;
    }
    if (!match) {
      setErr("Le password non coincidono");
      return;
    }
    setBusy(true);
    try {
      const res = await confirmPasswordReset(token, pw);
      if (res.ok) {
        setDone(true);
      } else {
        setErr(res.error || "Errore reset password");
      }
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
        <Stack.Screen options={{ title: "Password reimpostata" }} />
        <View style={styles.doneWrap}>
          <Text style={styles.emoji}>✅</Text>
          <Text style={styles.title}>Password reimpostata!</Text>
          <Text style={styles.subtitle}>
            La tua password è stata aggiornata. Adesso puoi accedere con la
            nuova password.
          </Text>
          <TouchableOpacity
            testID="reset-back-to-login"
            onPress={() => router.replace("/login")}
            activeOpacity={0.9}
            style={styles.primaryBtn}
          >
            <Text style={styles.primaryBtnText}>Vai al login</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <Stack.Screen options={{ title: "Reimposta password", headerBackTitle: "Indietro" }} />
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1 }}
      >
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <View style={styles.header}>
            <Text style={styles.emoji}>🔐</Text>
            <Text style={styles.title}>Nuova password</Text>
            <Text style={styles.subtitle}>
              Scegli una nuova password per il tuo account Barrio.
            </Text>
          </View>

          <View style={styles.field}>
            <Text style={styles.label}>Nuova password</Text>
            <View style={styles.pwRow}>
              <TextInput
                testID="reset-password-input"
                value={pw}
                onChangeText={setPw}
                placeholder="Minimo 8 caratteri"
                placeholderTextColor="#A3A3A3"
                autoCapitalize="none"
                autoCorrect={false}
                secureTextEntry={!showPw}
                textContentType="newPassword"
                style={[styles.input, { flex: 1 }]}
              />
              <TouchableOpacity
                onPress={() => setShowPw((v) => !v)}
                style={styles.pwEye}
                activeOpacity={0.7}
              >
                <Ionicons name={showPw ? "eye-off" : "eye"} size={20} color="#525252" />
              </TouchableOpacity>
            </View>
          </View>

          <View style={styles.field}>
            <Text style={styles.label}>Conferma password</Text>
            <TextInput
              testID="reset-confirm-input"
              value={confirm}
              onChangeText={setConfirm}
              placeholder="Ripeti la password"
              placeholderTextColor="#A3A3A3"
              autoCapitalize="none"
              autoCorrect={false}
              secureTextEntry={!showPw}
              textContentType="newPassword"
              style={styles.input}
            />
            {confirm.length > 0 && !match ? (
              <Text style={styles.fieldError}>Le password non coincidono</Text>
            ) : null}
          </View>

          {err ? (
            <View style={styles.errorBox}>
              <Ionicons name="alert-circle" size={16} color="#FF4747" />
              <Text style={styles.errorText}>{err}</Text>
            </View>
          ) : null}

          <TouchableOpacity
            testID="reset-submit"
            onPress={onSubmit}
            disabled={busy || !pwValid || !match}
            activeOpacity={0.9}
            style={[styles.primaryBtn, (busy || !pwValid || !match) && { opacity: 0.5 }]}
          >
            {busy ? (
              <ActivityIndicator color="#FFFFFF" />
            ) : (
              <Text style={styles.primaryBtnText}>Aggiorna password</Text>
            )}
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FDFBF7" },
  scroll: { padding: 20, gap: 18 },
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
  pwRow: { flexDirection: "row", alignItems: "stretch", gap: 8 },
  pwEye: {
    width: 44,
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#FFFFFF",
  },
  fieldError: { color: "#B91C1C", fontSize: 12, fontWeight: "700" },
  primaryBtn: {
    backgroundColor: "#FF4747",
    borderRadius: 999,
    paddingVertical: 15,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    marginTop: 12,
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
  doneWrap: {
    flex: 1,
    padding: 24,
    justifyContent: "center",
    alignItems: "center",
    gap: 12,
  },
});
