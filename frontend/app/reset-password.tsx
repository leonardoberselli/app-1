import { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/lib/api";

export default function ResetPassword() {
  const { token } = useLocalSearchParams<{ token?: string }>();
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async () => {
    setError(null);
    if (!token) return setError("Token mancante");
    if (password.length < 8) return setError("Almeno 8 caratteri");
    if (password !== password2) return setError("Le password non coincidono");
    try {
      setBusy(true);
      await api.confirmReset(token, password);
      setDone(true);
    } catch (e: any) {
      setError(e?.message || "Errore");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={["top"]} testID="reset-screen">
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.kicker}>REIMPOSTA PASSWORD</Text>
          <Text style={styles.title}>Nuova password</Text>
        </View>
      </View>
      <KeyboardAwareScrollView
        style={{ flex: 1 }}
        contentContainerStyle={styles.body}
        bottomOffset={80}
      >
        {done ? (
          <View style={styles.doneWrap}>
            <Text style={{ fontSize: 60 }}>🎉</Text>
            <Text style={styles.doneTitle}>Password aggiornata</Text>
            <Text style={styles.sub}>Ora puoi accedere con la nuova password.</Text>
            <TouchableOpacity
              testID="back-login"
              onPress={() => router.replace("/login")}
              style={styles.primaryBtn}
              activeOpacity={0.85}
            >
              <Text style={styles.primaryText}>Vai al login</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <>
            <Text style={styles.label}>NUOVA PASSWORD</Text>
            <TextInput
              testID="password-input"
              style={styles.input}
              value={password}
              onChangeText={setPassword}
              placeholder="Almeno 8 caratteri"
              placeholderTextColor="#9A9A9A"
              secureTextEntry
            />
            <Text style={styles.label}>CONFERMA</Text>
            <TextInput
              testID="password2-input"
              style={styles.input}
              value={password2}
              onChangeText={setPassword2}
              placeholder="Ripeti password"
              placeholderTextColor="#9A9A9A"
              secureTextEntry
            />
            {error && (
              <Text testID="reset-error" style={styles.error}>
                {error}
              </Text>
            )}
            <TouchableOpacity
              testID="reset-submit"
              activeOpacity={0.85}
              onPress={submit}
              disabled={busy}
              style={[styles.primaryBtn, busy && { opacity: 0.6 }]}
            >
              {busy ? (
                <ActivityIndicator color="#0A0A0A" />
              ) : (
                <>
                  <Ionicons name="checkmark" size={20} color="#0A0A0A" />
                  <Text style={styles.primaryText}>Aggiorna</Text>
                </>
              )}
            </TouchableOpacity>
          </>
        )}
      </KeyboardAwareScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FDFBF7" },
  header: {
    paddingHorizontal: 20,
    paddingVertical: 18,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: 2,
    borderBottomColor: "#000",
  },
  kicker: { fontSize: 11, fontWeight: "800", color: "#FF4747", letterSpacing: 1.5 },
  title: { fontSize: 26, fontWeight: "900", color: "#0A0A0A", letterSpacing: -0.5 },
  body: { padding: 20, gap: 6 },
  label: {
    fontSize: 12,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: 1.5,
    marginTop: 14,
  },
  input: {
    backgroundColor: "#FFFFFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 14,
    fontSize: 16,
    color: "#0A0A0A",
    fontWeight: "600",
    marginTop: 8,
  },
  error: { color: "#FF4747", fontWeight: "800", marginTop: 12 },
  primaryBtn: {
    marginTop: 22,
    backgroundColor: "#FFE600",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingVertical: 18,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    shadowColor: "#000",
    shadowOffset: { width: 4, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
  },
  primaryText: {
    fontSize: 16,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: 1,
    textTransform: "uppercase",
  },
  doneWrap: { alignItems: "center", padding: 20, gap: 12 },
  doneTitle: {
    fontSize: 24,
    fontWeight: "900",
    color: "#0A0A0A",
    marginTop: 6,
  },
  sub: {
    color: "#525252",
    fontSize: 15,
    lineHeight: 22,
    textAlign: "center",
    marginBottom: 20,
  },
});
