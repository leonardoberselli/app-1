import { useEffect, useState } from "react";
import {
  Modal,
  View,
  Text,
  TouchableOpacity,
  TextInput,
  StyleSheet,
  ScrollView,
  ActivityIndicator,
  Alert,
  Platform,
} from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { Ionicons } from "@expo/vector-icons";

import { api, ReportReason, ReportTargetType } from "@/src/lib/api";

type Props = {
  visible: boolean;
  onClose: () => void;
  targetType: ReportTargetType;
  targetId: string;
  /** Optional short label shown as the sheet subtitle, e.g. group title. */
  targetLabel?: string;
  /** Optional callback invoked when the report has been submitted. */
  onSubmitted?: () => void;
};

type ReasonOption = { key: ReportReason; label: string; icon: keyof typeof Ionicons.glyphMap };

const REASONS: ReasonOption[] = [
  { key: "illegal_content", label: "Contenuto illegale", icon: "warning" },
  { key: "sexual_content", label: "Contenuto esplicito", icon: "eye-off" },
  { key: "harassment", label: "Molestie / Bullismo", icon: "sad" },
  { key: "violence", label: "Violenza / Odio", icon: "flame" },
  { key: "scam", label: "Truffa", icon: "cash" },
  { key: "spam", label: "Spam", icon: "trash-bin" },
  { key: "personal_info", label: "Info personali", icon: "id-card" },
  { key: "other", label: "Altro", icon: "help-circle" },
];

const TARGET_TITLE: Record<ReportTargetType, string> = {
  group: "Segnala il gruppo",
  user: "Segnala l'utente",
  message: "Segnala il messaggio",
};

export function ReportSheet({
  visible,
  onClose,
  targetType,
  targetId,
  targetLabel,
  onSubmitted,
}: Props) {
  const [reason, setReason] = useState<ReportReason | null>(null);
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (visible) {
      setReason(null);
      setDescription("");
      setError(null);
      setBusy(false);
    }
  }, [visible]);

  const submit = async () => {
    if (!reason) {
      setError("Seleziona un motivo");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.submitReport({
        target_type: targetType,
        target_id: targetId,
        reason,
        description: description.trim() || undefined,
      });
      onClose();
      onSubmitted?.();
      // Slight delay so the modal is fully unmounted before the alert.
      setTimeout(() => {
        Alert.alert(
          "Segnalazione inviata",
          "Grazie. Il team di moderazione la esaminerà al più presto.",
        );
      }, 250);
    } catch (e: any) {
      setError(e?.message || "Impossibile inviare la segnalazione");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
      testID="report-sheet"
    >
      <View style={styles.overlay}>
        <TouchableOpacity
          style={styles.backdrop}
          activeOpacity={1}
          onPress={onClose}
          testID="report-sheet-backdrop"
        />
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : "height"}
          style={styles.sheetWrap}
        >
          <View style={styles.sheet}>
            <View style={styles.handle} />
            <View style={styles.header}>
              <Ionicons name="flag" size={20} color="#FF4747" />
              <Text style={styles.title}>{TARGET_TITLE[targetType]}</Text>
              <TouchableOpacity onPress={onClose} testID="report-sheet-close">
                <Ionicons name="close" size={24} color="#0A0A0A" />
              </TouchableOpacity>
            </View>
            {targetLabel ? (
              <Text style={styles.subtitle} numberOfLines={2}>
                {targetLabel}
              </Text>
            ) : null}

            <Text style={styles.sectionLabel}>MOTIVO</Text>
            <ScrollView
              style={{ maxHeight: 280 }}
              contentContainerStyle={styles.reasonsWrap}
              showsVerticalScrollIndicator={false}
            >
              {REASONS.map((r) => {
                const active = reason === r.key;
                return (
                  <TouchableOpacity
                    key={r.key}
                    testID={`report-reason-${r.key}`}
                    activeOpacity={0.85}
                    onPress={() => {
                      setReason(r.key);
                      setError(null);
                    }}
                    style={[styles.reasonBtn, active && styles.reasonBtnActive]}
                  >
                    <Ionicons
                      name={r.icon}
                      size={16}
                      color={active ? "#FFE600" : "#0A0A0A"}
                    />
                    <Text
                      style={[
                        styles.reasonText,
                        active && styles.reasonTextActive,
                      ]}
                    >
                      {r.label}
                    </Text>
                  </TouchableOpacity>
                );
              })}
            </ScrollView>

            <Text style={styles.sectionLabel}>DETTAGLI (OPZIONALE)</Text>
            <TextInput
              testID="report-description"
              value={description}
              onChangeText={setDescription}
              placeholder="Aggiungi contesto (max 500 caratteri)"
              placeholderTextColor="#9A9A9A"
              multiline
              maxLength={500}
              style={styles.textArea}
            />

            {error ? <Text style={styles.error}>{error}</Text> : null}

            <TouchableOpacity
              testID="report-submit"
              activeOpacity={0.85}
              onPress={submit}
              disabled={busy}
              style={[styles.submit, busy && { opacity: 0.6 }]}
            >
              {busy ? (
                <ActivityIndicator color="#FFE600" />
              ) : (
                <>
                  <Ionicons name="send" size={18} color="#FFE600" />
                  <Text style={styles.submitText}>Invia segnalazione</Text>
                </>
              )}
            </TouchableOpacity>
          </View>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)" },
  backdrop: { ...StyleSheet.absoluteFillObject },
  sheetWrap: { flex: 1, justifyContent: "flex-end" },
  sheet: {
    backgroundColor: "#FDFBF7",
    borderTopWidth: 2,
    borderColor: "#0A0A0A",
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    padding: 20,
    gap: 12,
    paddingBottom: 32,
  },
  handle: {
    alignSelf: "center",
    width: 44,
    height: 5,
    backgroundColor: "#0A0A0A",
    borderRadius: 999,
    marginBottom: 6,
  },
  header: { flexDirection: "row", alignItems: "center", gap: 10 },
  title: { flex: 1, fontSize: 20, fontWeight: "900", color: "#0A0A0A" },
  subtitle: { color: "#525252", fontWeight: "600", marginTop: -6 },
  sectionLabel: {
    fontSize: 11,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: 1.5,
    marginTop: 4,
  },
  reasonsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  reasonBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  reasonBtnActive: { backgroundColor: "#0A0A0A" },
  reasonText: { fontWeight: "800", color: "#0A0A0A", fontSize: 13 },
  reasonTextActive: { color: "#FFE600" },
  textArea: {
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 16,
    padding: 12,
    minHeight: 80,
    textAlignVertical: "top",
    fontSize: 14,
    color: "#0A0A0A",
  },
  error: { color: "#FF4747", fontWeight: "800" },
  submit: {
    backgroundColor: "#FF4747",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    marginTop: 4,
    shadowColor: "#000",
    shadowOffset: { width: 3, height: 3 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
  },
  submitText: {
    fontWeight: "900",
    color: "#FFE600",
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
});
