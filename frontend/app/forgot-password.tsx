import { useState } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  TextInput,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/contexts/auth";

export default function ForgotPassword() {
  const { requestPasswordReset } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async () => {
    setError(null);
    if (!email.trim().includes("@")) return setError("Inserisci un'email valida");
    try {
      setBusy(true);
      await requestPasswordReset(email.trim());
      setDone(true);
    } catch (e: any) {
      setError(e?.message || "Errore");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={["top"]} testID="forgot-screen">
      <View style={styles.header}>
        <TouchableOpacity
          testID="back-button"
          onPress={() => router.back()}
          style={styles.backBtn}
        >
          <Ionicons name="chevron-back" size={22} color="#0A0A0A" />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.kicker}>PASSWORD</Text>
          <Text style={styles.title}>Recupera password</Text>
        </View>
      </View>

      <KeyboardAwareScrollView
        style={{ flex: 1 }}
        contentContainerStyle={styles.body}
        bottomOffset={80}
        keyboardShouldPersistTaps="handled"
      >
        {done ? (
          <View style={styles.doneWrap}>
            <Text style={{ fontSize: 60 }}>📬</Text>
            <Text style={styles.doneTitle}>Controlla la tua email</Text>
            <Text style={styles.doneSub}>
              Se l&apos;email è registrata, riceverai un link per reimpostare la password entro pochi secondi.
            </Text>
            <TouchableOpacity
              testID="back-to-login"
              onPress={() => router.replace("/login")}
              style={styles.primaryBtn}
              activeOpacity={0.85}
            >
              <Text style={styles.primaryText}>Torna al login</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <>
            <Text style={styles.info}>
              Inserisci l&apos;email dell&apos;account, ti manderemo un link per creare una nuova password.
            </Text>
            <Text style={styles.label}>EMAIL</Text>
            <TextInput
              testID="email-input"
              style={styles.input}
              value={email}
              onChangeText={setEmail}
              placeholder="tuaemail@esempio.com"
              placeholderTextColor="#9A9A9A"
              keyboardType="email-address"
              autoCapitalize="none"
              autoCorrect={false}
            />
            {error && (
              <Text testID="forgot-error" style={styles.error}>
                {error}
              </Text>
            )}
            <TouchableOpacity
              testID="forgot-submit"
              activeOpacity={0.85}
              onPress={submit}
              disabled={busy}
              style={[styles.primaryBtn, busy && { opacity: 0.6 }]}
            >
              {busy ? (
                <ActivityIndicator color="#0A0A0A" />
              ) : (
                <>
                  <Ionicons name="send" size={20} color="#0A0A0A" />
                  <Text style={styles.primaryText}>Invia link</Text>
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
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    borderBottomWidth: 2,
    borderBottomColor: "#000",
  },
  backBtn: {
    width: 38,
    height: 38,
    borderRadius: 999,
    borderWidth: 2,
    borderColor: "#0A0A0A",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#FFF",
  },
  kicker: { fontSize: 11, fontWeight: "800", color: "#FF4747", letterSpacing: 1.5 },
  title: { fontSize: 26, fontWeight: "900", color: "#0A0A0A", letterSpacing: -0.5 },
  body: { padding: 20, gap: 6 },
  info: { color: "#525252", fontSize: 15, lineHeight: 22, marginBottom: 10 },
  label: {
    fontSize: 12,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: 1.5,
    marginTop: 8,
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
    marginTop: 10,
  },
  doneSub: {
    color: "#525252",
    fontSize: 15,
    lineHeight: 22,
    textAlign: "center",
    marginBottom: 20,
  },
});
