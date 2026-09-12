import { useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  Image,
  Modal,
  ScrollView,
  Platform,
  TextInput,
  KeyboardAvoidingView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import * as AppleAuthentication from "expo-apple-authentication";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/contexts/auth";
import { TERMS_TEXT, TERMS_VERSION, TERMS_MIN_AGE } from "@/src/lib/terms";

const GOOGLE_ICON = "https://developers.google.com/identity/images/g-logo.png";

// Same validator as the backend: min 8 chars, at least 1 letter + 1 digit.
const PASSWORD_RE = /^(?=.*[A-Za-z])(?=.*\d).{8,128}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Mode = "login" | "signup";

export default function LoginScreen() {
  const {
    signIn,
    checkPendingSession,
    signingIn,
    authError,
    signInWithPassword,
    signUpWithPassword,
    appleAvailable,
    signInWithApple,
  } = useAuth();
  const router = useRouter();

  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [name, setName] = useState("");
  const [showPw, setShowPw] = useState(false);

  const [localError, setLocalError] = useState<string | null>(null);
  const [termsOpen, setTermsOpen] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);

  const err = localError || authError;
  const showRecovery = Platform.OS !== "web" && attempted && !!err;

  const emailValid = useMemo(() => EMAIL_RE.test(email.trim()), [email]);
  const pwValid = useMemo(() => PASSWORD_RE.test(password), [password]);
  const confirmOk = useMemo(
    () => mode === "login" || password === confirmPassword,
    [mode, password, confirmPassword],
  );
  const canSubmit =
    !busy &&
    !signingIn &&
    emailValid &&
    pwValid &&
    confirmOk &&
    (mode === "login" || name.trim().length >= 2);

  const onGoogle = async () => {
    setLocalError(null);
    setAttempted(true);
    const res = await signIn();
    if (!res.ok) setLocalError(res.error || null);
  };

  const onCheckPending = async () => {
    setLocalError(null);
    setChecking(true);
    try {
      const res = await checkPendingSession();
      if (!res.ok) setLocalError(res.error || null);
    } finally {
      setChecking(false);
    }
  };

  const onApple = async () => {
    setLocalError(null);
    const res = await signInWithApple();
    if (!res.ok) {
      if (res.error) setLocalError(res.error);
      return;
    }
    router.replace("/");
  };

  const onSubmitEmail = async () => {
    setLocalError(null);
    if (!emailValid) {
      setLocalError("Inserisci un indirizzo email valido");
      return;
    }
    if (!pwValid) {
      setLocalError("Password: minimo 8 caratteri con almeno una lettera e un numero");
      return;
    }
    if (mode === "signup" && !confirmOk) {
      setLocalError("Le password non coincidono");
      return;
    }
    setBusy(true);
    try {
      const res =
        mode === "login"
          ? await signInWithPassword(email, password)
          : await signUpWithPassword(email, password, name);
      if (!res.ok) {
        setLocalError(res.error || null);
      } else {
        // Auth context updated `user`, but this screen doesn't unmount on
        // its own — bounce to the root so app/index.tsx routes to onboarding
        // or the tabs based on the new user state.
        router.replace("/");
      }
    } finally {
      setBusy(false);
    }
  };

  const toggleMode = () => {
    setMode((m) => (m === "login" ? "signup" : "login"));
    setLocalError(null);
    setConfirmPassword("");
  };

  const busyForButton = busy || signingIn;

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]} testID="login-screen">
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1 }}
      >
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.hero}>
            <Text style={styles.emoji}>👥</Text>
            <Text style={styles.kicker}>BENVENUTO/A SU</Text>
            <Text style={styles.brand}>Barrio</Text>
            <Text style={styles.subtitle}>
              Crea o unisciti a gruppi di attività vicino a te.
            </Text>
          </View>

          {/* Login / Signup segmented toggle */}
          <View style={styles.tabs}>
            <TouchableOpacity
              testID="tab-login"
              style={[styles.tab, mode === "login" && styles.tabActive]}
              onPress={() => setMode("login")}
              activeOpacity={0.85}
            >
              <Text style={[styles.tabText, mode === "login" && styles.tabTextActive]}>
                Accedi
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              testID="tab-signup"
              style={[styles.tab, mode === "signup" && styles.tabActive]}
              onPress={() => setMode("signup")}
              activeOpacity={0.85}
            >
              <Text style={[styles.tabText, mode === "signup" && styles.tabTextActive]}>
                Registrati
              </Text>
            </TouchableOpacity>
          </View>

          {/* Email/password form */}
          <View style={styles.form}>
            {mode === "signup" ? (
              <View style={styles.field}>
                <Text style={styles.label}>Nome</Text>
                <TextInput
                  testID="signup-name"
                  value={name}
                  onChangeText={setName}
                  placeholder="Come ti chiami?"
                  placeholderTextColor="#A3A3A3"
                  autoCapitalize="words"
                  maxLength={40}
                  style={styles.input}
                />
              </View>
            ) : null}

            <View style={styles.field}>
              <Text style={styles.label}>Email</Text>
              <TextInput
                testID="email-input"
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

            <View style={styles.field}>
              <Text style={styles.label}>Password</Text>
              <View style={styles.pwRow}>
                <TextInput
                  testID="password-input"
                  value={password}
                  onChangeText={setPassword}
                  placeholder="Minimo 8 caratteri"
                  placeholderTextColor="#A3A3A3"
                  autoCapitalize="none"
                  autoCorrect={false}
                  secureTextEntry={!showPw}
                  textContentType={mode === "signup" ? "newPassword" : "password"}
                  style={[styles.input, { flex: 1 }]}
                />
                <TouchableOpacity
                  onPress={() => setShowPw((v) => !v)}
                  style={styles.pwEye}
                  activeOpacity={0.7}
                  testID="toggle-password-visibility"
                >
                  <Ionicons name={showPw ? "eye-off" : "eye"} size={20} color="#525252" />
                </TouchableOpacity>
              </View>
            </View>

            {mode === "signup" ? (
              <View style={styles.field}>
                <Text style={styles.label}>Conferma password</Text>
                <TextInput
                  testID="confirm-password-input"
                  value={confirmPassword}
                  onChangeText={setConfirmPassword}
                  placeholder="Ripeti la password"
                  placeholderTextColor="#A3A3A3"
                  autoCapitalize="none"
                  autoCorrect={false}
                  secureTextEntry={!showPw}
                  textContentType="newPassword"
                  style={styles.input}
                />
                {confirmPassword.length > 0 && !confirmOk ? (
                  <Text style={styles.fieldError}>Le password non coincidono</Text>
                ) : null}
              </View>
            ) : null}

            {mode === "login" ? (
              <TouchableOpacity
                testID="forgot-password-link"
                onPress={() => router.push("/forgot-password")}
                activeOpacity={0.7}
                style={styles.forgot}
              >
                <Text style={styles.forgotText}>Password dimenticata?</Text>
              </TouchableOpacity>
            ) : null}

            <TouchableOpacity
              testID="submit-email"
              onPress={onSubmitEmail}
              disabled={!canSubmit}
              activeOpacity={0.9}
              style={[styles.primaryBtn, !canSubmit && { opacity: 0.5 }]}
            >
              {busyForButton ? (
                <ActivityIndicator color="#FFFFFF" />
              ) : (
                <Text style={styles.primaryBtnText}>
                  {mode === "login" ? "Accedi" : "Crea account"}
                </Text>
              )}
            </TouchableOpacity>
          </View>

          <View style={styles.divider}>
            <View style={styles.dividerLine} />
            <Text style={styles.dividerText}>oppure</Text>
            <View style={styles.dividerLine} />
          </View>

          {/* Apple Sign-In (iOS only) */}
          {appleAvailable ? (
            <AppleAuthentication.AppleAuthenticationButton
              testID="apple-signin-button"
              buttonType={
                mode === "signup"
                  ? AppleAuthentication.AppleAuthenticationButtonType.SIGN_UP
                  : AppleAuthentication.AppleAuthenticationButtonType.SIGN_IN
              }
              buttonStyle={AppleAuthentication.AppleAuthenticationButtonStyle.BLACK}
              cornerRadius={999}
              style={styles.appleBtn}
              onPress={onApple}
            />
          ) : null}

          <TouchableOpacity
            testID="google-signin-button"
            activeOpacity={0.85}
            onPress={onGoogle}
            disabled={signingIn}
            style={[styles.googleBtn, signingIn && { opacity: 0.6 }]}
          >
            {signingIn ? (
              <ActivityIndicator color="#0A0A0A" />
            ) : (
              <>
                <Image source={{ uri: GOOGLE_ICON }} style={styles.googleIcon} />
                <Text style={styles.googleText}>
                  {mode === "signup" ? "Registrati con Google" : "Accedi con Google"}
                </Text>
              </>
            )}
          </TouchableOpacity>

          {err ? (
            <View style={styles.errorBox} testID="login-error">
              <Ionicons name="alert-circle" size={16} color="#FF4747" />
              <Text style={styles.errorText}>{err}</Text>
            </View>
          ) : null}

          {showRecovery ? (
            <TouchableOpacity
              testID="check-pending-session-button"
              activeOpacity={0.85}
              onPress={onCheckPending}
              disabled={checking}
              style={[styles.recoveryBtn, checking && { opacity: 0.6 }]}
            >
              {checking ? (
                <ActivityIndicator color="#0A0A0A" />
              ) : (
                <>
                  <Ionicons name="refresh-circle" size={18} color="#0A0A0A" />
                  <Text style={styles.recoveryText}>Ho già fatto login, verifica</Text>
                </>
              )}
            </TouchableOpacity>
          ) : null}

          <TouchableOpacity onPress={toggleMode} style={{ paddingVertical: 8 }} activeOpacity={0.7}>
            <Text style={styles.switchText}>
              {mode === "login"
                ? "Non hai un account? "
                : "Hai già un account? "}
              <Text style={styles.switchLink}>
                {mode === "login" ? "Registrati" : "Accedi"}
              </Text>
            </Text>
          </TouchableOpacity>

          <Text style={styles.disclaimer}>
            Per iscriverti devi avere almeno {TERMS_MIN_AGE} anni. Continuando
            accetti di leggere il{" "}
            <Text style={styles.disclaimerLink} onPress={() => setTermsOpen(true)}>
              regolamento e la limitazione di responsabilità
            </Text>
            .
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>

      <Modal
        visible={termsOpen}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setTermsOpen(false)}
      >
        <SafeAreaView style={styles.modalContainer} edges={["top", "bottom"]}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Regolamento Barrio</Text>
            <TouchableOpacity onPress={() => setTermsOpen(false)} style={{ padding: 4 }}>
              <Ionicons name="close" size={24} color="#0A0A0A" />
            </TouchableOpacity>
          </View>
          <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 40 }}>
            <Text style={styles.termsMeta}>Versione {TERMS_VERSION}</Text>
            <Text style={styles.termsBody}>{TERMS_TEXT}</Text>
          </ScrollView>
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FDFBF7" },
  scroll: { padding: 20, paddingBottom: 40, gap: 18 },
  hero: { alignItems: "center", gap: 6 },
  emoji: { fontSize: 60 },
  kicker: { fontSize: 12, fontWeight: "800", color: "#FF4747", letterSpacing: 1.5 },
  brand: { fontSize: 44, fontWeight: "900", color: "#0A0A0A", letterSpacing: -1.5 },
  subtitle: {
    textAlign: "center",
    color: "#525252",
    fontSize: 14,
    fontWeight: "600",
    lineHeight: 20,
    paddingHorizontal: 8,
  },
  tabs: {
    flexDirection: "row",
    backgroundColor: "#F1EBE0",
    borderRadius: 999,
    padding: 4,
    gap: 4,
  },
  tab: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 999,
    alignItems: "center",
  },
  tabActive: {
    backgroundColor: "#0A0A0A",
  },
  tabText: { fontSize: 14, fontWeight: "800", color: "#525252" },
  tabTextActive: { color: "#FFFFFF" },
  form: { gap: 12 },
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
  forgot: { alignSelf: "flex-end", paddingVertical: 4 },
  forgotText: { color: "#0A0A0A", fontWeight: "800", fontSize: 13, textDecorationLine: "underline" },
  primaryBtn: {
    backgroundColor: "#FF4747",
    borderRadius: 999,
    paddingVertical: 15,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 4,
    borderWidth: 2,
    borderColor: "#0A0A0A",
  },
  primaryBtnText: { color: "#FFFFFF", fontWeight: "900", fontSize: 16, letterSpacing: 0.3 },
  divider: { flexDirection: "row", alignItems: "center", gap: 12, marginVertical: 4 },
  dividerLine: { flex: 1, height: 2, backgroundColor: "#0A0A0A" },
  dividerText: { fontSize: 12, fontWeight: "800", color: "#525252" },
  appleBtn: { height: 50, width: "100%" },
  googleBtn: {
    backgroundColor: "#FFFFFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 999,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
  },
  googleIcon: { width: 22, height: 22 },
  googleText: { fontWeight: "900", color: "#0A0A0A", fontSize: 15, letterSpacing: 0.3 },
  errorBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#FEE2E2",
    borderWidth: 2,
    borderColor: "#FF4747",
    borderRadius: 12,
    padding: 10,
  },
  errorText: { color: "#B91C1C", fontWeight: "700", flex: 1, fontSize: 13 },
  recoveryBtn: {
    backgroundColor: "#FFE99A",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 999,
    paddingVertical: 12,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  recoveryText: { fontWeight: "800", color: "#0A0A0A", fontSize: 14 },
  switchText: { textAlign: "center", color: "#525252", fontWeight: "600", fontSize: 14 },
  switchLink: { color: "#0A0A0A", fontWeight: "900", textDecorationLine: "underline" },
  disclaimer: {
    textAlign: "center",
    color: "#8A8A8A",
    fontSize: 12,
    lineHeight: 18,
    fontWeight: "600",
    paddingHorizontal: 12,
  },
  disclaimerLink: {
    color: "#0A0A0A",
    fontWeight: "900",
    textDecorationLine: "underline",
  },
  modalContainer: { flex: 1, backgroundColor: "#FDFBF7" },
  modalHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: 16,
    borderBottomWidth: 2,
    borderBottomColor: "#0A0A0A",
  },
  modalTitle: { fontSize: 18, fontWeight: "900", color: "#0A0A0A" },
  termsMeta: {
    fontSize: 12,
    color: "#525252",
    fontWeight: "700",
    marginBottom: 12,
    fontStyle: "italic",
  },
  termsBody: { fontSize: 13, lineHeight: 20, color: "#0A0A0A" },
});
