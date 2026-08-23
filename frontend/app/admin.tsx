import { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api, AdminReport, AdminStats, ReportReason } from "@/src/lib/api";

type StatusFilter = "pending" | "reviewed" | "dismissed" | "all";

const REASON_LABEL: Record<ReportReason, string> = {
  illegal_content: "Contenuto illegale",
  sexual_content: "Contenuto esplicito",
  harassment: "Molestie",
  scam: "Truffa",
  spam: "Spam",
  violence: "Violenza",
  personal_info: "Info personali",
  other: "Altro",
};

const TARGET_LABEL: Record<AdminReport["target_type"], string> = {
  group: "Gruppo",
  user: "Utente",
  message: "Messaggio",
};

const TARGET_ICON: Record<AdminReport["target_type"], keyof typeof Ionicons.glyphMap> = {
  group: "people",
  user: "person",
  message: "chatbubble",
};

const FILTERS: { key: StatusFilter; label: string }[] = [
  { key: "pending", label: "Aperte" },
  { key: "reviewed", label: "Gestite" },
  { key: "dismissed", label: "Ignorate" },
  { key: "all", label: "Tutte" },
];

export default function AdminScreen() {
  const router = useRouter();
  const [filter, setFilter] = useState<StatusFilter>("pending");
  const [reports, setReports] = useState<AdminReport[]>([]);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [rs, st] = await Promise.all([
        api.adminListReports(filter),
        api.adminStats(),
      ]);
      setReports(rs);
      setStats(st);
      setError(null);
    } catch (e: any) {
      setError(e?.message || "Errore");
      // If unauthorized, kick back
      if (String(e?.message || "").toLowerCase().includes("segreto")) {
        Alert.alert(
          "Accesso negato",
          "Il segreto admin non è valido o è scaduto.",
          [{ text: "OK", onPress: () => router.replace("/(tabs)/profile") }],
        );
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [filter, router]);

  useEffect(() => {
    setLoading(true);
    load();
  }, [load]);

  const onRefresh = () => {
    setRefreshing(true);
    load();
  };

  const doUpdate = async (
    id: string,
    status: "pending" | "reviewed" | "dismissed",
  ) => {
    try {
      setBusyId(id);
      await api.adminUpdateReport(id, status);
      await load();
    } catch (e: any) {
      Alert.alert("Errore", e?.message || "Aggiornamento fallito");
    } finally {
      setBusyId(null);
    }
  };

  const confirmDelete = (r: AdminReport) => {
    if (!r.target_exists) {
      Alert.alert(
        "Elemento già rimosso",
        "L'elemento segnalato non esiste più. Vuoi marcare come gestita?",
        [
          { text: "Annulla", style: "cancel" },
          {
            text: "Sì",
            onPress: () => doUpdate(r.report_id, "reviewed"),
          },
        ],
      );
      return;
    }
    const kind =
      r.target_type === "group"
        ? "gruppo"
        : r.target_type === "user"
        ? "utente e tutti i suoi contenuti"
        : "messaggio";
    Alert.alert(
      "Conferma eliminazione",
      `Elimina definitivamente questo ${kind}? L'azione è irreversibile.`,
      [
        { text: "Annulla", style: "cancel" },
        {
          text: "Elimina",
          style: "destructive",
          onPress: async () => {
            try {
              setBusyId(r.report_id);
              if (r.target_type === "group") {
                await api.adminDeleteGroup(r.target_id);
              } else if (r.target_type === "user") {
                await api.adminDeleteUser(r.target_id);
              } else {
                await api.adminDeleteMessage(r.target_id);
              }
              await load();
            } catch (e: any) {
              Alert.alert("Errore", e?.message || "Eliminazione fallita");
            } finally {
              setBusyId(null);
            }
          },
        },
      ],
    );
  };

  const logout = async () => {
    Alert.alert(
      "Esci dalla modalità admin",
      "Vuoi bloccare nuovamente il pannello admin su questo dispositivo?",
      [
        { text: "Annulla", style: "cancel" },
        {
          text: "Esci",
          style: "destructive",
          onPress: async () => {
            await api.adminClearSecret();
            router.replace("/(tabs)/profile");
          },
        },
      ],
    );
  };

  const renderSnapshot = (r: AdminReport) => {
    const s = r.target_snapshot || {};
    if (r.target_type === "group") {
      return (
        <View>
          <Text style={styles.snapshotTitle} numberOfLines={2}>
            {s.title || "(senza titolo)"}
          </Text>
          <Text style={styles.snapshotMeta}>
            {s.category_label}
            {s.city ? ` · ${s.city}${s.province ? ` (${s.province})` : ""}` : ""}
          </Text>
          <Text style={styles.snapshotMeta}>
            Autore: {s.owner_name} · {s.participants_count || 0} partecipanti
          </Text>
          {s.description ? (
            <Text style={styles.snapshotText} numberOfLines={3}>
              {s.description}
            </Text>
          ) : null}
        </View>
      );
    }
    if (r.target_type === "user") {
      return (
        <View>
          <Text style={styles.snapshotTitle}>{s.name || "(senza nome)"}</Text>
          <Text style={styles.snapshotMeta}>
            {s.gender ? `${s.gender}` : ""}
            {s.age != null ? ` · ${s.age} anni` : ""}
          </Text>
          <Text style={styles.snapshotMeta} numberOfLines={1}>
            ID: {r.target_id.slice(0, 24)}…
          </Text>
        </View>
      );
    }
    if (r.target_type === "message") {
      return (
        <View>
          <Text style={styles.snapshotTitle} numberOfLines={4}>
            {`“${s.text || ""}”`}
          </Text>
          <Text style={styles.snapshotMeta}>
            {`di ${s.user_name}${s.group_title ? ` — in “${s.group_title}”` : ""}`}
          </Text>
        </View>
      );
    }
    return null;
  };

  return (
    <SafeAreaView style={styles.container} edges={["top"]} testID="admin-screen">
      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => router.back()}
          style={styles.iconBtn}
          testID="admin-back"
        >
          <Ionicons name="chevron-back" size={22} color="#0A0A0A" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>MODERAZIONE</Text>
        <TouchableOpacity
          onPress={logout}
          style={[styles.iconBtn, { backgroundColor: "#FF4747" }]}
          testID="admin-logout"
        >
          <Ionicons name="lock-closed" size={18} color="#FFF" />
        </TouchableOpacity>
      </View>

      {stats && (
        <View style={styles.statsRow}>
          <StatCard label="Aperte" value={stats.pending} color="#FF4747" />
          <StatCard label="Gestite" value={stats.reviewed} color="#10B981" />
          <StatCard label="Gruppi" value={stats.groups} color="#FFE600" />
          <StatCard label="Utenti" value={stats.users} color="#0A0A0A" />
        </View>
      )}

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.filtersRow}
      >
        {FILTERS.map((f) => (
          <TouchableOpacity
            key={f.key}
            testID={`filter-${f.key}`}
            onPress={() => setFilter(f.key)}
            style={[styles.filterBtn, filter === f.key && styles.filterBtnActive]}
            activeOpacity={0.85}
          >
            <Text
              style={[
                styles.filterText,
                filter === f.key && styles.filterTextActive,
              ]}
            >
              {f.label}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color="#FF4747" size="large" />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#FF4747" />
          }
        >
          {error && !loading ? (
            <View style={styles.errorCard}>
              <Ionicons name="alert-circle" size={20} color="#FF4747" />
              <Text style={styles.errorText}>{error}</Text>
            </View>
          ) : null}
          {reports.length === 0 ? (
            <View style={styles.empty}>
              <Text style={styles.emptyEmoji}>✅</Text>
              <Text style={styles.emptyTitle}>Nessuna segnalazione</Text>
              <Text style={styles.emptySub}>
                {"Non c’è niente da rivedere in questa categoria."}
              </Text>
            </View>
          ) : (
            reports.map((r) => (
              <View
                key={r.report_id}
                testID={`report-item-${r.report_id}`}
                style={styles.card}
              >
                <View style={styles.cardHeader}>
                  <View
                    style={[
                      styles.badge,
                      r.target_type === "group"
                        ? { backgroundColor: "#FFE600" }
                        : r.target_type === "user"
                        ? { backgroundColor: "#FF4747" }
                        : { backgroundColor: "#0A0A0A" },
                    ]}
                  >
                    <Ionicons
                      name={TARGET_ICON[r.target_type]}
                      size={14}
                      color={r.target_type === "message" ? "#FFE600" : "#0A0A0A"}
                    />
                    <Text
                      style={[
                        styles.badgeText,
                        r.target_type === "message" && { color: "#FFE600" },
                      ]}
                    >
                      {TARGET_LABEL[r.target_type]}
                    </Text>
                  </View>
                  <View style={styles.reasonPill}>
                    <Text style={styles.reasonPillText}>
                      {REASON_LABEL[r.reason]}
                    </Text>
                  </View>
                  <View
                    style={[
                      styles.statusPill,
                      r.status === "pending"
                        ? { backgroundColor: "#FFEDD5", borderColor: "#F97316" }
                        : r.status === "reviewed"
                        ? { backgroundColor: "#D1FAE5", borderColor: "#10B981" }
                        : { backgroundColor: "#F3F4F6", borderColor: "#525252" },
                    ]}
                  >
                    <Text style={styles.statusPillText}>{r.status}</Text>
                  </View>
                </View>

                <View style={styles.snapshotBox}>
                  {r.target_exists ? (
                    renderSnapshot(r)
                  ) : (
                    <Text style={styles.snapshotMissing}>
                      {"⚠️ L’elemento segnalato non esiste più (già rimosso)."}
                    </Text>
                  )}
                </View>

                {r.description ? (
                  <Text style={styles.reporterNote} numberOfLines={4}>
                    {`Nota di ${r.reporter_name}: “${r.description}”`}
                  </Text>
                ) : (
                  <Text style={styles.reporterNoteEmpty}>
                    {`Segnalato da ${r.reporter_name}`}
                  </Text>
                )}

                <View style={styles.actions}>
                  {r.status !== "reviewed" && (
                    <TouchableOpacity
                      testID={`action-review-${r.report_id}`}
                      disabled={busyId === r.report_id}
                      onPress={() => doUpdate(r.report_id, "reviewed")}
                      style={[styles.actionBtn, styles.actionReview]}
                      activeOpacity={0.85}
                    >
                      <Ionicons name="checkmark" size={16} color="#FFF" />
                      <Text style={styles.actionText}>Gestita</Text>
                    </TouchableOpacity>
                  )}
                  {r.status !== "dismissed" && (
                    <TouchableOpacity
                      testID={`action-dismiss-${r.report_id}`}
                      disabled={busyId === r.report_id}
                      onPress={() => doUpdate(r.report_id, "dismissed")}
                      style={[styles.actionBtn, styles.actionDismiss]}
                      activeOpacity={0.85}
                    >
                      <Ionicons name="remove" size={16} color="#0A0A0A" />
                      <Text style={[styles.actionText, { color: "#0A0A0A" }]}>
                        Ignora
                      </Text>
                    </TouchableOpacity>
                  )}
                  <TouchableOpacity
                    testID={`action-delete-${r.report_id}`}
                    disabled={busyId === r.report_id}
                    onPress={() => confirmDelete(r)}
                    style={[styles.actionBtn, styles.actionDelete]}
                    activeOpacity={0.85}
                  >
                    {busyId === r.report_id ? (
                      <ActivityIndicator color="#FFE600" size="small" />
                    ) : (
                      <>
                        <Ionicons name="trash" size={16} color="#FFE600" />
                        <Text style={[styles.actionText, { color: "#FFE600" }]}>
                          Elimina
                        </Text>
                      </>
                    )}
                  </TouchableOpacity>
                </View>
              </View>
            ))
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  return (
    <View style={styles.statCard}>
      <View style={[styles.statDot, { backgroundColor: color }]} />
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FDFBF7" },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: 14,
    borderBottomWidth: 2,
    borderBottomColor: "#000",
    gap: 10,
  },
  headerTitle: {
    fontWeight: "900",
    letterSpacing: 1.5,
    color: "#0A0A0A",
    fontSize: 14,
  },
  iconBtn: {
    width: 38,
    height: 38,
    borderRadius: 999,
    borderWidth: 2,
    borderColor: "#0A0A0A",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#FFF",
  },
  statsRow: {
    flexDirection: "row",
    gap: 8,
    paddingHorizontal: 14,
    paddingTop: 14,
  },
  statCard: {
    flex: 1,
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 14,
    paddingVertical: 10,
    paddingHorizontal: 6,
    alignItems: "center",
  },
  statDot: { width: 10, height: 10, borderRadius: 5, marginBottom: 4 },
  statValue: { fontSize: 20, fontWeight: "900", color: "#0A0A0A" },
  statLabel: {
    fontSize: 10,
    fontWeight: "800",
    color: "#525252",
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
  filtersRow: {
    flexDirection: "row",
    gap: 8,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  filterBtn: {
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 8,
    backgroundColor: "#FFF",
  },
  filterBtnActive: { backgroundColor: "#0A0A0A" },
  filterText: { fontWeight: "900", color: "#0A0A0A" },
  filterTextActive: { color: "#FFE600" },
  list: { padding: 14, paddingBottom: 40, gap: 12 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  empty: { alignItems: "center", paddingVertical: 60, gap: 6 },
  emptyEmoji: { fontSize: 48 },
  emptyTitle: { fontSize: 18, fontWeight: "900", color: "#0A0A0A" },
  emptySub: { color: "#525252", textAlign: "center", paddingHorizontal: 20 },
  card: {
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 20,
    padding: 14,
    gap: 10,
    shadowColor: "#000",
    shadowOffset: { width: 3, height: 3 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 3,
  },
  cardHeader: { flexDirection: "row", flexWrap: "wrap", gap: 6, alignItems: "center" },
  badge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  badgeText: { fontWeight: "900", fontSize: 11, color: "#0A0A0A", letterSpacing: 0.5 },
  reasonPill: {
    borderWidth: 2,
    borderColor: "#FF4747",
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
    backgroundColor: "#FEE2E2",
  },
  reasonPillText: { fontWeight: "800", color: "#B91C1C", fontSize: 11 },
  statusPill: {
    borderWidth: 2,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
    marginLeft: "auto",
  },
  statusPillText: { fontWeight: "800", color: "#0A0A0A", fontSize: 10, textTransform: "uppercase" },
  snapshotBox: {
    backgroundColor: "#FDFBF7",
    borderWidth: 1,
    borderColor: "#E5E5E5",
    borderRadius: 12,
    padding: 10,
    gap: 4,
  },
  snapshotTitle: { fontWeight: "900", fontSize: 14, color: "#0A0A0A" },
  snapshotMeta: { color: "#525252", fontWeight: "600", fontSize: 12 },
  snapshotText: { color: "#0A0A0A", fontSize: 13, marginTop: 4, lineHeight: 18 },
  snapshotMissing: { color: "#8A8A8A", fontStyle: "italic", fontSize: 13 },
  reporterNote: {
    color: "#0A0A0A",
    fontStyle: "italic",
    fontSize: 12,
    backgroundColor: "#FFFBEB",
    padding: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#FDE68A",
  },
  reporterNoteEmpty: { color: "#8A8A8A", fontSize: 12, fontStyle: "italic" },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  actionBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  actionReview: { backgroundColor: "#10B981" },
  actionDismiss: { backgroundColor: "#FFE600" },
  actionDelete: { backgroundColor: "#0A0A0A" },
  actionText: { fontWeight: "900", color: "#FFF", fontSize: 12, letterSpacing: 0.3 },
  errorCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "#FEE2E2",
    borderWidth: 2,
    borderColor: "#FF4747",
    borderRadius: 12,
    padding: 12,
  },
  errorText: { color: "#B91C1C", fontWeight: "800", flex: 1 },
});
