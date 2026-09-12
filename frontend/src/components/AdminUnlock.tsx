import { useEffect, useState } from "react";
import {
  Modal,
  View,
  Text,
  TouchableOpacity,
  TextInput,
  StyleSheet,
  ActivityIndicator,
  Platform,
} from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/lib/api";

/**
 * Admin unlock UI shown inside the Profile screen. If a valid secret is
 * already stored we show a direct entry button; otherwise we present a
 * one-time modal to enter and verify the secret.
 */
export function AdminUnlock() {
  const router = useRouter();
  const [hasSecret, setHasSecret] = useState(false);
  const [checking, setChecking] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const has = await api.adminHasSecret();
      setHasSecret(has);
      setChecking(false);
    })();
  }, []);

  const openPanel = async () => {
    // Re-verify before navigating in case the secret was revoked server-side.
    try {
      setBusy(true);
      await api.adminVerify();
      setBusy(false);
      router.push("/admin");
    } catch (e: any) {
      setBusy(false);
      await api.adminClearSecret();
      setHasSecret(false);
      setError(e?.message || "Segreto non valido");
      setModalOpen(true);
    }
  };

  const submitSecret = async () => {
    const s = secret.trim();
    if (!s) {
      setError("Inserisci il segreto admin");
      return;
    }
    setBusy(true);
    setError(null);
    await api.adminSetSecret(s);
    try {
      await api.adminVerify();
      setHasSecret(true);
      setModalOpen(false);
      setSecret("");
      router.push("/admin");
    } catch (e: any) {
      await api.adminClearSecret();
      setError(e?.message || "Segreto non valido");
    } finally {
      setBusy(false);
    }
  };

  if (checking) return null;

  return (
    <>
      <TouchableOpacity
        testID="admin-unlock-btn"
        onPress={hasSecret ? openPanel : () => setModalOpen(true)}
        activeOpacity={0.85}
        style={styles.entry}
      >
        <Ionicons
          name={hasSecret ? "shield-checkmark" : "shield-outline"}
          size={18}
          color={hasSecret ? "#10B981" : "#0A0A0A"}
        />
        <View style={{ flex: 1 }}>
          <Text style={styles.entryTitle}>
            {hasSecret ? "Pannello moderazione" : "Sei il proprietario?"}
          </Text>
          <Text style={styles.entrySub}>
            {hasSecret
              ? "Gestisci segnalazioni, gruppi e utenti."
              : "Sblocca il pannello admin con la password."}
          </Text>
        </View>
        {busy ? (
          <ActivityIndicator color="#0A0A0A" />
        ) : (
          <Ionicons name="chevron-forward" size={20} color="#0A0A0A" />
        )}
      </TouchableOpacity>

      <Modal
        visible={modalOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setModalOpen(false)}
      >
        <View style={styles.overlay}>
          <TouchableOpacity
            style={styles.backdrop}
            activeOpacity={1}
            onPress={() => setModalOpen(false)}
          />
          <KeyboardAvoidingView
            behavior={Platform.OS === "ios" ? "padding" : "height"}
            style={styles.centerBox}
          >
            <View style={styles.card}>
              <View style={styles.headerRow}>
                <Ionicons name="lock-closed" size={20} color="#0A0A0A" />
                <Text style={styles.cardTitle}>Accesso admin</Text>
                <TouchableOpacity onPress={() => setModalOpen(false)}>
                  <Ionicons name="close" size={22} color="#0A0A0A" />
                </TouchableOpacity>
              </View>
              <Text style={styles.help}>
                Inserisci il segreto amministratore per gestire segnalazioni,
                eliminare gruppi o bannare utenti.
              </Text>
              <TextInput
                testID="admin-secret-input"
                value={secret}
                onChangeText={setSecret}
                autoCapitalize="none"
                autoCorrect={false}
                secureTextEntry
                placeholder="Segreto admin"
                placeholderTextColor="#9A9A9A"
                style={styles.input}
              />
              {error ? <Text style={styles.error}>{error}</Text> : null}
              <TouchableOpacity
                testID="admin-secret-submit"
                onPress={submitSecret}
                disabled={busy}
                activeOpacity={0.85}
                style={[styles.submit, busy && { opacity: 0.6 }]}
              >
                {busy ? (
                  <ActivityIndicator color="#FFE600" />
                ) : (
                  <>
                    <Ionicons name="key" size={16} color="#FFE600" />
                    <Text style={styles.submitText}>Sblocca</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>
          </KeyboardAvoidingView>
        </View>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  entry: {
    marginTop: 16,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 16,
    padding: 14,
  },
  entryTitle: { fontWeight: "900", color: "#0A0A0A", fontSize: 14 },
  entrySub: { color: "#525252", fontSize: 12, marginTop: 2, fontWeight: "600" },
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)" },
  backdrop: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  centerBox: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  card: {
    width: "100%",
    maxWidth: 420,
    backgroundColor: "#FDFBF7",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 24,
    padding: 20,
    gap: 12,
    shadowColor: "#000",
    shadowOffset: { width: 4, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
  },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  cardTitle: { flex: 1, fontWeight: "900", color: "#0A0A0A", fontSize: 18 },
  help: { color: "#525252", fontSize: 13, lineHeight: 18 },
  input: {
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    color: "#0A0A0A",
  },
  error: { color: "#FF4747", fontWeight: "800" },
  submit: {
    backgroundColor: "#0A0A0A",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  submitText: {
    fontWeight: "900",
    color: "#FFE600",
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
});
