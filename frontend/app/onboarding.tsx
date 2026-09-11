import { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  Modal,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/contexts/auth";
import { api } from "@/src/lib/api";
import { TERMS_TEXT, TERMS_VERSION, TERMS_MIN_AGE } from "@/src/lib/terms";

/**
 * First-launch onboarding: captures the user's display name and age, and
 * forces acceptance of the terms/liability disclaimer (see /src/lib/terms.ts).
 * The age gate blocks registrations below {@link TERMS_MIN_AGE}.
 */
export default function Onboarding() {
  const { user, setUser, refreshMe } = useAuth();
  const router = useRouter();

  const [name, setName] = useState(user?.name || "");
  const [age, setAge] = useState<string>(
    user?.age != null ? String(user.age) : "",
  );
  const [acceptedTerms, setAcceptedTerms] = useState(
    user?.terms_version === TERMS_VERSION,
  );
  const [termsOpen, setTermsOpen] = useState(false);
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
    const parsedAge = parseInt(age, 10);
    if (isNaN(parsedAge)) {
      setError("Inserisci la tua età");
      return;
    }
    if (parsedAge < TERMS_MIN_AGE) {
      setError(
        `Per usare Barrio devi avere almeno ${TERMS_MIN_AGE} anni.`,
      );
      return;
    }
    if (parsedAge > 120) {
      setError("Età non valida");
      return;
    }
    if (!acceptedTerms) {
      setError("Devi accettare il regolamento per continuare.");
      return;
    }
    try {
      setSaving(true);
      // 1) record legal acceptance (server stores version + timestamp)
      await api.acceptTerms(TERMS_VERSION);
      // 2) then save profile (name + age)
      const updated = await api.updateProfile({
        name: trimmed,
        age: parsedAge,
      });
      // Re-fetch from server so terms_version/accepted_at are reflected
      await refreshMe();
      setUser(updated);
      router.replace("/(tabs)");
    } catch (e: any) {
      setError(e?.message || "Errore, riprova");
    } finally {
      setSaving(false);
    }
  };

  const isAdultInput = parseInt(age, 10) >= 18;
  const isValidAge = parseInt(age, 10) >= TERMS_MIN_AGE;

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
          <Text style={styles.brand}>Barrio</Text>
          <Text style={styles.subtitle}>
            Come ti chiami e quanti anni hai? Ci servono solo questi due dati
            per iniziare.
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
          returnKeyType="next"
        />

        <Text style={styles.label}>ETÀ</Text>
        <TextInput
          testID="onboarding-age-input"
          style={styles.input}
          value={age}
          onChangeText={(t) => setAge(t.replace(/[^0-9]/g, ""))}
          placeholder="Es. 24"
          placeholderTextColor="#9A9A9A"
          keyboardType="number-pad"
          maxLength={3}
          returnKeyType="done"
        />
        {isValidAge && (
          <View style={styles.ageBadge}>
            <Ionicons
              name={isAdultInput ? "person" : "school"}
              size={14}
              color={isAdultInput ? "#0A0A0A" : "#FF4747"}
            />
            <Text style={styles.ageBadgeText}>
              {isAdultInput
                ? "Vedrai solo gruppi per maggiorenni (18+)"
                : "Vedrai solo gruppi per minorenni (14-17)"}
            </Text>
          </View>
        )}

        <Text style={styles.label}>REGOLAMENTO E RESPONSABILITÀ</Text>
        <TouchableOpacity
          testID="onboarding-terms-checkbox"
          activeOpacity={0.85}
          onPress={() => setAcceptedTerms((v) => !v)}
          style={[
            styles.termsRow,
            acceptedTerms && { borderColor: "#10B981", backgroundColor: "#ECFDF5" },
          ]}
        >
          <View
            style={[
              styles.checkbox,
              acceptedTerms && { backgroundColor: "#10B981", borderColor: "#10B981" },
            ]}
          >
            {acceptedTerms ? (
              <Ionicons name="checkmark" size={16} color="#FFF" />
            ) : null}
          </View>
          <Text style={styles.termsText}>
            {"Ho letto e "}
            <Text style={styles.termsBold}>accetto integralmente</Text>
            {" il regolamento e la limitazione di responsabilità di Barrio, e "}
            <Text style={styles.termsBold}>manlevo il proprietario</Text>
            {" da ogni responsabilità legata all’uso dell’app (foto caricate, geolocalizzazione, chat, incontri di persona)."}
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          testID="onboarding-terms-read"
          onPress={() => setTermsOpen(true)}
          activeOpacity={0.7}
          style={styles.readMoreBtn}
        >
          <Ionicons name="document-text-outline" size={16} color="#0A0A0A" />
          <Text style={styles.readMoreText}>Leggi il regolamento completo</Text>
        </TouchableOpacity>

        {error && (
          <Text testID="onboarding-error" style={styles.error}>
            {error}
          </Text>
        )}

        <TouchableOpacity
          testID="onboarding-submit"
          activeOpacity={0.85}
          onPress={submit}
          disabled={
            saving || !name.trim() || !age || !acceptedTerms
          }
          style={[
            styles.cta,
            (saving || !name.trim() || !age || !acceptedTerms) && {
              opacity: 0.5,
            },
          ]}
        >
          {saving ? (
            <ActivityIndicator color="#0A0A0A" />
          ) : (
            <>
              <Ionicons name="arrow-forward" size={20} color="#0A0A0A" />
              <Text style={styles.ctaText}>Accetto e continuo</Text>
            </>
          )}
        </TouchableOpacity>

        <Text style={styles.footnote}>
          Il tuo account \u00e8 collegato a Google. Potrai completare foto e sesso
          quando vuoi dalla scheda Profilo.
        </Text>
        {user?.user_id ? (
          <Text style={styles.deviceId}>ID: {user.user_id.slice(0, 12)}\u2026</Text>
        ) : null}
      </KeyboardAwareScrollView>

      <Modal
        visible={termsOpen}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setTermsOpen(false)}
      >
        <SafeAreaView style={styles.modalContainer} edges={["top", "bottom"]}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Regolamento Barrio</Text>
            <TouchableOpacity
              testID="terms-close"
              onPress={() => setTermsOpen(false)}
              style={styles.modalClose}
            >
              <Ionicons name="close" size={24} color="#0A0A0A" />
            </TouchableOpacity>
          </View>
          <ScrollView
            style={{ flex: 1 }}
            contentContainerStyle={{ padding: 20, paddingBottom: 40 }}
          >
            <Text style={styles.termsBody}>{TERMS_TEXT}</Text>
          </ScrollView>
          <View style={styles.modalFooter}>
            <TouchableOpacity
              testID="terms-accept-from-modal"
              activeOpacity={0.85}
              onPress={() => {
                setAcceptedTerms(true);
                setTermsOpen(false);
              }}
              style={styles.modalAcceptBtn}
            >
              <Ionicons name="checkmark" size={18} color="#FFE600" />
              <Text style={styles.modalAcceptText}>Accetto</Text>
            </TouchableOpacity>
          </View>
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FDFBF7" },
  body: { padding: 24, paddingBottom: 60, gap: 6 },
  hero: { alignItems: "center", marginTop: 12, marginBottom: 20, gap: 6 },
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
    marginTop: 14,
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
  ageBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#FFFBEB",
    borderWidth: 1,
    borderColor: "#FDE68A",
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 8,
    marginTop: 8,
  },
  ageBadgeText: { color: "#0A0A0A", fontWeight: "700", fontSize: 12 },
  termsRow: {
    flexDirection: "row",
    gap: 12,
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 16,
    padding: 12,
    marginTop: 8,
    backgroundColor: "#FFFFFF",
  },
  checkbox: {
    width: 26,
    height: 26,
    borderRadius: 6,
    borderWidth: 2,
    borderColor: "#0A0A0A",
    backgroundColor: "#FFF",
    alignItems: "center",
    justifyContent: "center",
    marginTop: 2,
  },
  termsText: { flex: 1, color: "#0A0A0A", fontSize: 13, lineHeight: 18, fontWeight: "600" },
  termsBold: { fontWeight: "900" },
  readMoreBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    alignSelf: "flex-start",
    marginTop: 8,
    paddingVertical: 4,
  },
  readMoreText: {
    color: "#0A0A0A",
    fontWeight: "800",
    textDecorationLine: "underline",
    fontSize: 13,
  },
  error: { color: "#FF4747", fontWeight: "800", marginTop: 12 },
  cta: {
    marginTop: 20,
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
    fontSize: 15,
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
  modalClose: { padding: 4 },
  termsBody: {
    fontSize: 13,
    lineHeight: 20,
    color: "#0A0A0A",
    fontFamily: "System",
  },
  modalFooter: {
    padding: 16,
    borderTopWidth: 2,
    borderTopColor: "#0A0A0A",
    backgroundColor: "#FFF",
  },
  modalAcceptBtn: {
    backgroundColor: "#0A0A0A",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingVertical: 16,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  modalAcceptText: {
    fontWeight: "900",
    color: "#FFE600",
    letterSpacing: 1,
    textTransform: "uppercase",
    fontSize: 14,
  },
});
