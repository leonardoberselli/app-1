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
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/contexts/auth";
import { api } from "@/src/lib/api";

/**
 * First-launch onboarding: single-field name capture. We keep it deliberately
 * minimal because the user asked for a zero-friction entry. Photo, gender and
 * age can be added later from the Profile tab.
 */
export default function Onboarding() {
  const { user, setUser } = useAuth();
  const router = useRouter();

  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    const trimmed = name.trim();
    if (trimmed.length < 2) {
      setError("Inserisci un nome (almeno 2 caratteri)");
      return;
    }
    if (trimmed.length > 40) {
      setError("Nome troppo lungo (max 40)");
      return;
    }
    try {
      setSaving(true);
      const updated = await api.updateProfile({ name: trimmed });
      setUser(updated);
      router.replace("/(tabs)");
    } catch (e: any) {
      setError(e?.message || "Errore, riprova");
    } finally {
      setSaving(false);
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]} testID="onboarding-screen">
      <KeyboardAwareScrollView
        style={{ flex: 1 }}
        contentContainerStyle={styles.body}
        bottomOffset={100}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.hero}>
          <Text style={styles.emoji}>👋</Text>
          <Text style={styles.kicker}>BENVENUTO/A SU</Text>
          <Text style={styles.brand}>GroupUp</Text>
          <Text style={styles.subtitle}>
            Come ti chiami? Ci basta un nome per iniziare.
          </Text>
        </View>

        <Text style={styles.label}>NOME</Text>
        <TextInput
          testID="onboarding-name-input"
          style={styles.input}
          value={name}
          onChangeText={setName}
          placeholder="Es. Leonardo"
          placeholderTextColor="#9A9A9A"
          maxLength={40}
          autoFocus
          autoCapitalize="words"
          returnKeyType="go"
          onSubmitEditing={submit}
        />

        {error && (
          <Text testID="onboarding-error" style={styles.error}>
            {error}
          </Text>
        )}

        <TouchableOpacity
          testID="onboarding-submit"
          activeOpacity={0.85}
          onPress={submit}
          disabled={saving || !name.trim()}
          style={[styles.cta, (saving || !name.trim()) && { opacity: 0.5 }]}
        >
          {saving ? (
            <ActivityIndicator color="#0A0A0A" />
          ) : (
            <>
              <Ionicons name="arrow-forward" size={20} color="#0A0A0A" />
              <Text style={styles.ctaText}>Entra</Text>
            </>
          )}
        </TouchableOpacity>

        <Text style={styles.footnote}>
          Nessun account, nessuna password. Potrai completare foto, sesso ed
          età quando vuoi dalla scheda Profilo.
        </Text>
        {user?.user_id ? (
          <Text style={styles.deviceId}>ID dispositivo: {user.user_id.slice(0, 12)}…</Text>
        ) : null}
      </KeyboardAwareScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FDFBF7" },
  body: { padding: 24, paddingBottom: 60, gap: 6 },
  hero: { alignItems: "center", marginTop: 20, marginBottom: 24, gap: 6 },
  emoji: { fontSize: 56 },
  kicker: { fontSize: 12, fontWeight: "800", color: "#FF4747", letterSpacing: 1.5 },
  brand: {
    fontSize: 42,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: -1,
  },
  subtitle: {
    textAlign: "center",
    color: "#525252",
    fontSize: 15,
    fontWeight: "600",
    lineHeight: 22,
    paddingHorizontal: 10,
    marginTop: 4,
  },
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
    paddingVertical: 16,
    fontSize: 18,
    color: "#0A0A0A",
    fontWeight: "700",
    marginTop: 8,
  },
  error: { color: "#FF4747", fontWeight: "800", marginTop: 12 },
  cta: {
    marginTop: 24,
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
  ctaText: {
    fontSize: 16,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: 1,
    textTransform: "uppercase",
  },
  footnote: {
    marginTop: 20,
    textAlign: "center",
    color: "#8A8A8A",
    fontSize: 13,
    fontWeight: "600",
    lineHeight: 18,
  },
  deviceId: {
    marginTop: 12,
    textAlign: "center",
    color: "#B0B0B0",
    fontSize: 11,
    fontFamily: "monospace",
  },
});
