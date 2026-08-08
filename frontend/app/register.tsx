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

export default function RegisterScreen() {
  const { signUp } = useAuth();
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async () => {
    setError(null);
    if (!name.trim()) return setError("Inserisci il tuo nome");
    if (!email.trim().includes("@")) return setError("Email non valida");
    if (password.length < 6) return setError("La password deve essere di almeno 6 caratteri");
    if (password !== password2) return setError("Le password non coincidono");
    try {
      setSubmitting(true);
      await signUp(email.trim(), password, name.trim());
      setDone(true);
    } catch (e: any) {
      setError(e?.message || "Errore registrazione");
    } finally {
      setSubmitting(false);
    }
  };

  if (done) {
    return (
      <SafeAreaView style={styles.container} edges={["top", "bottom"]} testID="register-done">
        <View style={styles.doneWrap}>
          <View style={styles.doneEmoji}>
            <Text style={{ fontSize: 60 }}>📬</Text>
          </View>
          <Text style={styles.doneTitle}>Controlla l&apos;email!</Text>
          <Text style={styles.doneSub}>
            Ti abbiamo inviato un link a{"\n"}
            <Text style={{ fontWeight: "900", color: "#0A0A0A" }}>{email}</Text>
            {"\n"}per verificare l&apos;account.
          </Text>
          <TouchableOpacity
            testID="go-verify"
            onPress={() => router.replace("/verify-email")}
            style={styles.primaryBtn}
            activeOpacity={0.85}
          >
            <Text style={styles.primaryText}>Continua</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={["top"]} testID="register-screen">
      <View style={styles.header}>
        <TouchableOpacity
          testID="back-button"
          onPress={() => router.back()}
          style={styles.backBtn}
        >
          <Ionicons name="chevron-back" size={22} color="#0A0A0A" />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.kicker}>CREA ACCOUNT</Text>
          <Text style={styles.title}>Registrati</Text>
        </View>
      </View>

      <KeyboardAwareScrollView
        style={{ flex: 1 }}
        contentContainerStyle={styles.body}
        bottomOffset={80}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={styles.label}>NOME</Text>
        <TextInput
          testID="name-input"
          style={styles.input}
          value={name}
          onChangeText={setName}
          placeholder="Il tuo nome"
          placeholderTextColor="#9A9A9A"
          maxLength={40}
        />

        <Text style={styles.label}>EMAIL</Text>
        <TextInput
          testID="register-email-input"
          style={styles.input}
          value={email}
          onChangeText={setEmail}
          placeholder="tuaemail@esempio.com"
          placeholderTextColor="#9A9A9A"
          keyboardType="email-address"
          autoCapitalize="none"
          autoCorrect={false}
        />

        <Text style={styles.label}>PASSWORD</Text>
        <TextInput
          testID="register-password-input"
          style={styles.input}
          value={password}
          onChangeText={setPassword}
          placeholder="Almeno 6 caratteri"
          placeholderTextColor="#9A9A9A"
          secureTextEntry
        />

        <Text style={styles.label}>CONFERMA PASSWORD</Text>
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
          <Text testID="register-error" style={styles.error}>
            {error}
          </Text>
        )}

        <TouchableOpacity
          testID="register-submit"
          activeOpacity={0.85}
          onPress={submit}
          disabled={submitting}
          style={[styles.primaryBtn, submitting && { opacity: 0.6 }]}
        >
          {submitting ? (
            <ActivityIndicator color="#0A0A0A" />
          ) : (
            <>
              <Ionicons name="rocket" size={20} color="#0A0A0A" />
              <Text style={styles.primaryText}>Crea account</Text>
            </>
          )}
        </TouchableOpacity>

        <Text style={styles.footer}>
          Riceverai una mail per verificare l&apos;email.
        </Text>
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
  body: { padding: 20, paddingBottom: 60, gap: 6 },
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
  footer: {
    color: "#8A8A8A",
    fontSize: 12,
    textAlign: "center",
    marginTop: 14,
  },
  doneWrap: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 32,
    gap: 14,
  },
  doneEmoji: {
    width: 120,
    height: 120,
    borderRadius: 60,
    backgroundColor: "#FFE600",
    borderWidth: 3,
    borderColor: "#000",
    alignItems: "center",
    justifyContent: "center",
  },
  doneTitle: {
    fontSize: 28,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: -0.5,
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
