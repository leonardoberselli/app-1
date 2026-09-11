import { useState } from "react";
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
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/contexts/auth";
import { TERMS_TEXT, TERMS_VERSION, TERMS_MIN_AGE } from "@/src/lib/terms";

const GOOGLE_ICON =
  "https://developers.google.com/identity/images/g-logo.png";

export default function LoginScreen() {
  const { signIn, checkPendingSession, signingIn, authError } = useAuth();
  const [localError, setLocalError] = useState<string | null>(null);
  const [termsOpen, setTermsOpen] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [checking, setChecking] = useState(false);

  const onGoogle = async () => {
    setLocalError(null);
    setAttempted(true);
    const res = await signIn();
    if (!res.ok) setLocalError(res.error || null);
    // On success the /index redirect effect will pick up the user and route
    // them to /onboarding (first login) or /(tabs) (returning user).
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

  const err = localError || authError;
  const showRecovery = Platform.OS !== "web" && attempted && !!err;

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]} testID="login-screen">
      <View style={styles.body}>
        <View style={styles.hero}>
          <Text style={styles.emoji}>👥</Text>
          <Text style={styles.kicker}>BENVENUTO/A SU</Text>
          <Text style={styles.brand}>Barrio</Text>
          <Text style={styles.subtitle}>
            Crea o unisciti a gruppi di attività vicino a te.
            {"\n"}Accedi con Google per iniziare.
          </Text>
        </View>

        <View style={styles.features}>
          <View style={styles.featureRow}>
            <Ionicons name="location" size={20} color="#FF4747" />
            <Text style={styles.featureText}>Gruppi vicino a te</Text>
          </View>
          <View style={styles.featureRow}>
            <Ionicons name="chatbubbles" size={20} color="#FF4747" />
            <Text style={styles.featureText}>Chat integrata</Text>
          </View>
          <View style={styles.featureRow}>
            <Ionicons name="shield-checkmark" size={20} color="#FF4747" />
            <Text style={styles.featureText}>Solo maggiorenni con maggiorenni, minorenni con minorenni</Text>
          </View>
        </View>

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
              <Text style={styles.googleText}>Accedi con Google</Text>
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

        <Text style={styles.disclaimer}>
          Per iscriverti devi avere almeno {TERMS_MIN_AGE} anni. Continuando
          accetti di leggere il{" "}
          <Text style={styles.disclaimerLink} onPress={() => setTermsOpen(true)}>
            regolamento e la limitazione di responsabilità
          </Text>
          .
        </Text>
      </View>

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
  body: { flex: 1, padding: 24, justifyContent: "center", gap: 24 },
  hero: { alignItems: "center", gap: 8 },
  emoji: { fontSize: 72 },
  kicker: { fontSize: 12, fontWeight: "800", color: "#FF4747", letterSpacing: 1.5 },
  brand: { fontSize: 48, fontWeight: "900", color: "#0A0A0A", letterSpacing: -1.5 },
  subtitle: {
    textAlign: "center",
    color: "#525252",
    fontSize: 15,
    fontWeight: "600",
    lineHeight: 22,
    paddingHorizontal: 8,
    marginTop: 6,
  },
  features: {
    gap: 10,
    backgroundColor: "#FFFFFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 20,
    padding: 18,
    shadowColor: "#000",
    shadowOffset: { width: 4, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
  },
  featureRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  featureText: { color: "#0A0A0A", fontSize: 14, fontWeight: "700", flex: 1 },
  googleBtn: {
    backgroundColor: "#FFFFFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 999,
    paddingVertical: 16,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    shadowColor: "#000",
    shadowOffset: { width: 4, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
  },
  googleIcon: { width: 22, height: 22 },
  googleText: { fontWeight: "900", color: "#0A0A0A", fontSize: 16, letterSpacing: 0.3 },
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
    shadowColor: "#000",
    shadowOffset: { width: 3, height: 3 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 3,
  },
  recoveryText: { fontWeight: "800", color: "#0A0A0A", fontSize: 14 },
  disclaimer: {
    textAlign: "center",
    color: "#8A8A8A",
    fontSize: 12,
    lineHeight: 18,
    fontWeight: "600",
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
