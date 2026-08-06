import { useState, useEffect } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  TextInput,
  ActivityIndicator,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/contexts/auth";

export default function LoginScreen() {
  const { signIn, signInWithEmail, signInWithApple, user, loading } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<"" | "google" | "apple" | "email">("");
  const [error, setError] = useState<string | null>(null);
  const [appleAvailable, setAppleAvailable] = useState(false);
  const router = useRouter();

  useEffect(() => {
    if (Platform.OS !== "ios") return;
    (async () => {
      try {
        const mod = await import("expo-apple-authentication");
        const av = await mod.isAvailableAsync();
        setAppleAvailable(av);
      } catch {
        setAppleAvailable(false);
      }
    })();
  }, []);

  if (user && !loading) {
    router.replace("/");
  }

  const handleGoogle = async () => {
    setError(null);
    try {
      setBusy("google");
      await signIn();
    } catch (e: any) {
      setError(e?.message || "Errore login");
    } finally {
      setBusy("");
    }
  };

  const handleApple = async () => {
    setError(null);
    try {
      setBusy("apple");
      await signInWithApple();
    } catch (e: any) {
      if (e?.code === "ERR_REQUEST_CANCELED") return;
      setError(e?.message || "Errore Apple");
    } finally {
      setBusy("");
    }
  };

  const handleEmailLogin = async () => {
    setError(null);
    if (!email.trim() || !password) {
      setError("Inserisci email e password");
      return;
    }
    try {
      setBusy("email");
      await signInWithEmail(email.trim(), password);
    } catch (e: any) {
      setError(e?.message || "Errore login");
    } finally {
      setBusy("");
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]} testID="login-screen">
      <KeyboardAwareScrollView
        style={{ flex: 1 }}
        contentContainerStyle={styles.scroll}
        bottomOffset={40}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.hero}>
          <View style={styles.badge}>
            <Text style={styles.badgeText}>GROUPUP · ITA</Text>
          </View>
          <Text style={styles.headline}>Pronti{"\n"}a giocare?</Text>
          <Text style={styles.sub}>
            Crea o unisciti a gruppi per sport, serate e ogni occasione di trovarsi.
          </Text>
        </View>

        <View style={styles.card}>
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
          <Text style={styles.label}>PASSWORD</Text>
          <TextInput
            testID="password-input"
            style={styles.input}
            value={password}
            onChangeText={setPassword}
            placeholder="La tua password"
            placeholderTextColor="#9A9A9A"
            secureTextEntry
          />

          <TouchableOpacity
            testID="forgot-link"
            onPress={() => router.push("/forgot-password")}
            style={{ alignSelf: "flex-end", marginTop: 6 }}
          >
            <Text style={styles.link}>Password dimenticata?</Text>
          </TouchableOpacity>

          {error && (
            <Text testID="login-error" style={styles.error}>
              {error}
            </Text>
          )}

          <TouchableOpacity
            testID="email-login-button"
            activeOpacity={0.85}
            onPress={handleEmailLogin}
            disabled={busy !== ""}
            style={[styles.primaryBtn, busy === "email" && { opacity: 0.6 }]}
          >
            {busy === "email" ? (
              <ActivityIndicator color="#0A0A0A" />
            ) : (
              <>
                <Ionicons name="log-in" size={20} color="#0A0A0A" />
                <Text style={styles.primaryText}>Accedi</Text>
              </>
            )}
          </TouchableOpacity>

          <TouchableOpacity
            testID="register-link"
            onPress={() => router.push("/register")}
            style={styles.registerLink}
          >
            <Text style={styles.registerText}>
              Non hai un account? <Text style={styles.link}>Registrati</Text>
            </Text>
          </TouchableOpacity>

          <View style={styles.dividerRow}>
            <View style={styles.dividerLine} />
            <Text style={styles.dividerText}>OPPURE</Text>
            <View style={styles.dividerLine} />
          </View>

          <TouchableOpacity
            testID="google-login-button"
            activeOpacity={0.85}
            style={[styles.googleBtn, busy === "google" && { opacity: 0.6 }]}
            onPress={handleGoogle}
            disabled={busy !== ""}
          >
            {busy === "google" ? (
              <ActivityIndicator color="#0A0A0A" />
            ) : (
              <>
                <Ionicons name="logo-google" size={20} color="#0A0A0A" />
                <Text style={styles.googleBtnText}>Continua con Google</Text>
              </>
            )}
          </TouchableOpacity>

          {Platform.OS === "ios" && appleAvailable && (
            <TouchableOpacity
              testID="apple-login-button"
              activeOpacity={0.85}
              style={[styles.appleBtn, busy === "apple" && { opacity: 0.6 }]}
              onPress={handleApple}
              disabled={busy !== ""}
            >
              {busy === "apple" ? (
                <ActivityIndicator color="#FFF" />
              ) : (
                <>
                  <Ionicons name="logo-apple" size={20} color="#FFF" />
                  <Text style={styles.appleBtnText}>Continua con Apple</Text>
                </>
              )}
            </TouchableOpacity>
          )}
        </View>

        <Text style={styles.footer}>
          Continuando accetti i Termini e l&apos;informativa privacy.
        </Text>
      </KeyboardAwareScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0A0A0A" },
  scroll: { flexGrow: 1, backgroundColor: "#0A0A0A" },
  hero: {
    padding: 24,
    paddingTop: 24,
    paddingBottom: 30,
    gap: 12,
  },
  badge: {
    alignSelf: "flex-start",
    backgroundColor: "#FFE600",
    borderWidth: 2,
    borderColor: "#000",
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 999,
  },
  badgeText: {
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: 1.5,
    fontSize: 12,
  },
  headline: {
    fontSize: 40,
    fontWeight: "900",
    color: "#FFF",
    lineHeight: 42,
    letterSpacing: -1.5,
  },
  sub: { color: "#B4B4B4", fontSize: 15, lineHeight: 21 },
  card: {
    backgroundColor: "#FDFBF7",
    borderTopLeftRadius: 32,
    borderTopRightRadius: 32,
    padding: 24,
    paddingBottom: 30,
    gap: 8,
    minHeight: 500,
  },
  label: {
    fontSize: 11,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: 1.5,
    marginTop: 10,
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
    marginTop: 6,
  },
  link: { color: "#FF4747", fontWeight: "900" },
  error: { color: "#FF4747", fontWeight: "800", marginTop: 8 },
  primaryBtn: {
    marginTop: 16,
    backgroundColor: "#FFE600",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingVertical: 16,
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
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
  registerLink: { alignSelf: "center", marginTop: 14 },
  registerText: { color: "#525252", fontWeight: "600" },
  dividerRow: {
    flexDirection: "row",
    alignItems: "center",
    marginVertical: 18,
    gap: 10,
  },
  dividerLine: { flex: 1, height: 2, backgroundColor: "#0A0A0A" },
  dividerText: { fontWeight: "900", color: "#0A0A0A", letterSpacing: 1 },
  googleBtn: {
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
  },
  googleBtnText: {
    fontSize: 15,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: 0.5,
  },
  appleBtn: {
    marginTop: 10,
    backgroundColor: "#000",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
  },
  appleBtnText: {
    fontSize: 15,
    fontWeight: "900",
    color: "#FFF",
    letterSpacing: 0.5,
  },
  footer: {
    color: "#B4B4B4",
    fontSize: 12,
    textAlign: "center",
    padding: 20,
  },
});
