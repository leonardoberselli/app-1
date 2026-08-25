import { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  FlatList,
  RefreshControl,
  Image,
  ActivityIndicator,
  Modal,
  Linking,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/contexts/auth";
import { useLocationPrefs } from "@/src/contexts/location";
import { api, ApiGroup, CitySuggestion } from "@/src/lib/api";
import { CATEGORIES, CUSTOM_CATEGORY, findCategory } from "@/src/lib/categories";
import { formatDate } from "@/src/lib/date";
import { CityAutocomplete } from "@/src/components/CityAutocomplete";

const ALL_FILTER = { id: "all", label: "Tutti", emoji: "✨", color: "#0A0A0A" };

export default function HomeScreen() {
  const { user } = useAuth();
  const {
    prefs,
    permission,
    canAskAgain,
    requestGps,
    setManualLocation,
  } = useLocationPrefs();
  const router = useRouter();
  const [groups, setGroups] = useState<ApiGroup[]>([]);
  const [category, setCategory] = useState<string>("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [promptOpen, setPromptOpen] = useState(false);
  const [manualCity, setManualCity] = useState("");
  const [manualPick, setManualPick] = useState<CitySuggestion | null>(null);
  const [promptStep, setPromptStep] = useState<"choose" | "manual">("choose");
  const [manualError, setManualError] = useState<string | null>(null);
  const [manualBusy, setManualBusy] = useState(false);

  const hasCoords = prefs.lat != null && prefs.lon != null;
  const geoFilter =
    hasCoords && prefs.radiusKm > 0
      ? { lat: prefs.lat as number, lon: prefs.lon as number, radiusKm: prefs.radiusKm }
      : null;

  const load = useCallback(async () => {
    try {
      const list = await api.listGroups(category, undefined, geoFilter);
      setGroups(list);
    } catch (e) {
      console.warn("listGroups", e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category, geoFilter?.lat, geoFilter?.lon, geoFilter?.radiusKm]);

  useEffect(() => {
    setLoading(true);
    load();
  }, [load]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  // First-launch permission prompt: show it once when the user has no
  // location set and hasn't been asked yet.
  useEffect(() => {
    if (!user) return;
    if (prefs.askedOnce) return;
    if (hasCoords) return;
    setPromptStep("choose");
    setPromptOpen(true);
  }, [user, prefs.askedOnce, hasCoords]);

  const onGrantGps = async () => {
    if (permission !== "granted" && !canAskAgain) {
      // OS won't ask again -> guide user to settings
      Alert.alert(
        "Permessi negati",
        "Attiva la posizione dalle impostazioni di sistema, oppure inserisci una città di riferimento.",
        [
          { text: "Impostazioni", onPress: () => Linking.openSettings() },
          { text: "Città manuale", onPress: () => setPromptStep("manual") },
          { text: "Chiudi", style: "cancel" },
        ],
      );
      return;
    }
    const ok = await requestGps();
    if (ok) {
      setPromptOpen(false);
    } else {
      setPromptStep("manual");
    }
  };

  const submitManual = async () => {
    if (!manualCity.trim()) {
      setManualError("Inserisci una città");
      return;
    }
    if (!manualPick) {
      setManualError("Seleziona una città dai suggerimenti");
      return;
    }
    setManualBusy(true);
    setManualError(null);
    const res = await setManualLocation(manualPick.name, {
      lat: manualPick.lat,
      lon: manualPick.lon,
      province: manualPick.province,
    });
    setManualBusy(false);
    if (!res.ok) {
      setManualError(res.error || "Città non trovata");
      return;
    }
    setPromptOpen(false);
    setManualCity("");
    setManualPick(null);
  };

  const onRefresh = () => {
    setRefreshing(true);
    load();
  };

  const renderCard = ({ item }: { item: ApiGroup }) => {
    const cat = findCategory(item.category) || CUSTOM_CATEGORY;
    const filled = item.participants.length;
    const total = item.max_participants;
    const pct = Math.min(100, Math.round((filled / total) * 100));
    return (
      <TouchableOpacity
        testID={`group-card-${item.group_id}`}
        activeOpacity={0.9}
        onPress={() => router.push(`/group/${item.group_id}`)}
        style={styles.card}
      >
        <View style={styles.cardHeader}>
          <View style={[styles.catPill, { backgroundColor: cat.color }]}>
            <Text style={styles.catPillEmoji}>{cat.emoji}</Text>
            <Text style={styles.catPillText}>{item.category_label}</Text>
          </View>
          <View style={styles.headerBadges}>
            {item.gender_filter === "male" ? (
              <View style={[styles.genderBadge, { backgroundColor: "#DBEAFE" }]}>
                <Text style={styles.genderBadgeText}>👨 Solo uomini</Text>
              </View>
            ) : item.gender_filter === "female" ? (
              <View style={[styles.genderBadge, { backgroundColor: "#FCE7F3" }]}>
                <Text style={styles.genderBadgeText}>👩 Solo donne</Text>
              </View>
            ) : null}
            <View style={styles.ageChip}>
              <Ionicons name="people" size={12} color="#0A0A0A" />
              <Text style={styles.ageChipText}>
                {item.min_age}-{item.max_age} anni
              </Text>
            </View>
          </View>
        </View>

        <Text style={styles.cardTitle} numberOfLines={2}>
          {item.title}
        </Text>

        <View style={styles.metaRow}>
          <Ionicons name="location-sharp" size={16} color="#525252" />
          <Text style={styles.metaText} numberOfLines={1}>
            {[item.location, item.city ? (item.province ? `${item.city} (${item.province})` : item.city) : null]
              .filter(Boolean)
              .join(" · ")}
          </Text>
        </View>

        <View style={styles.metaRow}>
          <Ionicons name="calendar" size={16} color="#525252" />
          <Text style={styles.metaText}>
            {formatDate(item.date)} · {item.time}
          </Text>
        </View>

        <View style={styles.progressContainer}>
          <View style={styles.progressBar}>
            <View
              style={[
                styles.progressFill,
                { width: `${pct}%`, backgroundColor: cat.color },
              ]}
            />
          </View>
          <Text style={styles.progressText}>
            {filled}/{total}
          </Text>
        </View>
      </TouchableOpacity>
    );
  };

  const filters = [ALL_FILTER, ...CATEGORIES];

  return (
    <SafeAreaView style={styles.container} edges={["top"]} testID="home-screen">
      <View style={styles.stickyHeader}>
        <View style={styles.header}>
          <View>
            <Text style={styles.kicker}>BENTORNATO/A</Text>
            <Text style={styles.headerTitle}>
              Ciao, {(user?.name || "").split(" ")[0]} 👋
            </Text>
          </View>
          {user?.picture ? (
            <Image source={{ uri: user.picture }} style={styles.avatar} />
          ) : (
            <View style={[styles.avatar, styles.avatarFallback]}>
              <Text style={styles.avatarText}>
                {(user?.name || "?").charAt(0).toUpperCase()}
              </Text>
            </View>
          )}
        </View>

        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chipsRow}
          style={styles.chipsScroll}
        >
          {filters.map((c) => {
            const active = category === c.id;
            return (
              <TouchableOpacity
                key={c.id}
                testID={`filter-chip-${c.id}`}
                onPress={() => setCategory(c.id)}
                activeOpacity={0.8}
                style={[
                  styles.chip,
                  active && styles.chipActive,
                ]}
              >
                <Text style={styles.chipEmoji}>{c.emoji}</Text>
                <Text
                  style={[
                    styles.chipText,
                    active && styles.chipTextActive,
                  ]}
                >
                  {c.label}
                </Text>
              </TouchableOpacity>
            );
          })}
        </ScrollView>

        <TouchableOpacity
          testID="distance-banner"
          activeOpacity={0.85}
          onPress={() => router.push("/(tabs)/profile")}
          style={styles.distanceBanner}
        >
          <Ionicons
            name={hasCoords ? "locate" : "location-outline"}
            size={16}
            color="#0A0A0A"
          />
          <Text style={styles.distanceBannerText} numberOfLines={1}>
            {hasCoords
              ? `Entro ${prefs.radiusKm} km${prefs.source === "manual" && prefs.manualCity ? ` da ${prefs.manualCity}` : " da te"}`
              : "Attiva la posizione per filtrare per distanza"}
          </Text>
          <Ionicons name="chevron-forward" size={16} color="#0A0A0A" />
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={styles.loadingWrap}>
          <ActivityIndicator size="large" color="#FF4747" />
        </View>
      ) : (
        <FlatList
          testID="groups-list"
          data={groups}
          keyExtractor={(g) => g.group_id}
          renderItem={renderCard}
          contentContainerStyle={styles.listContent}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#FF4747" />
          }
          ListEmptyComponent={
            <View style={styles.emptyWrap}>
              <Text style={styles.emptyEmoji}>🎯</Text>
              <Text style={styles.emptyTitle}>Nessun gruppo</Text>
              <Text style={styles.emptySub}>
                {hasCoords
                  ? `Nessun gruppo entro ${prefs.radiusKm} km. Aumenta la distanza dal profilo o crea tu il primo!`
                  : "Sii il primo a crearne uno! Tocca \"Crea\" per iniziare."}
              </Text>
            </View>
          }
        />
      )}

      <Modal
        visible={promptOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setPromptOpen(false)}
      >
        <View style={styles.backdrop}>
          <View style={styles.sheet} testID="location-prompt">
            <Text style={styles.sheetEmoji}>📍</Text>
            <Text style={styles.sheetTitle}>Trova gruppi vicino a te</Text>
            <Text style={styles.sheetSub}>
              {promptStep === "choose"
                ? "Ci serve la tua posizione per mostrarti solo i gruppi entro pochi km. Puoi anche scegliere una città di riferimento."
                : "Inserisci la città da cui vuoi vedere i gruppi (potrai cambiarla dal profilo)."}
            </Text>

            {promptStep === "choose" ? (
              <>
                <TouchableOpacity
                  testID="location-grant-btn"
                  activeOpacity={0.85}
                  onPress={onGrantGps}
                  style={styles.primaryBtn}
                >
                  <Ionicons name="locate" size={18} color="#0A0A0A" />
                  <Text style={styles.primaryBtnText}>Usa la mia posizione</Text>
                </TouchableOpacity>

                <TouchableOpacity
                  testID="location-manual-btn"
                  activeOpacity={0.85}
                  onPress={() => setPromptStep("manual")}
                  style={styles.secondaryBtn}
                >
                  <Ionicons name="location-outline" size={18} color="#0A0A0A" />
                  <Text style={styles.secondaryBtnText}>Inserisci una città</Text>
                </TouchableOpacity>

                <TouchableOpacity
                  activeOpacity={0.7}
                  onPress={() => setPromptOpen(false)}
                  style={styles.skipBtn}
                >
                  <Text style={styles.skipBtnText}>Salta, mostra tutti</Text>
                </TouchableOpacity>
              </>
            ) : (
              <>
                <View style={{ width: "100%" }}>
                  <CityAutocomplete
                    testID="location-manual-city"
                    value={manualCity}
                    onChangeText={(t) => {
                      setManualCity(t);
                      setManualPick(null);
                    }}
                    onSelect={(c) => {
                      setManualCity(c.name);
                      setManualPick(c);
                    }}
                    autoFocus
                    placeholder="Es. Milano"
                  />
                </View>
                {manualError ? (
                  <Text testID="location-manual-error" style={styles.manualError}>
                    {manualError}
                  </Text>
                ) : null}

                <TouchableOpacity
                  testID="location-manual-submit"
                  activeOpacity={0.85}
                  onPress={submitManual}
                  disabled={manualBusy}
                  style={[styles.primaryBtn, manualBusy && { opacity: 0.6 }]}
                >
                  {manualBusy ? (
                    <ActivityIndicator color="#0A0A0A" />
                  ) : (
                    <>
                      <Ionicons name="checkmark" size={18} color="#0A0A0A" />
                      <Text style={styles.primaryBtnText}>Conferma</Text>
                    </>
                  )}
                </TouchableOpacity>
                <TouchableOpacity
                  activeOpacity={0.7}
                  onPress={() => setPromptStep("choose")}
                  style={styles.skipBtn}
                >
                  <Text style={styles.skipBtnText}>Indietro</Text>
                </TouchableOpacity>
              </>
            )}
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FDFBF7" },
  stickyHeader: {
    backgroundColor: "#FDFBF7",
    paddingBottom: 8,
    borderBottomWidth: 2,
    borderBottomColor: "#000",
  },
  header: {
    paddingHorizontal: 20,
    paddingVertical: 16,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  kicker: {
    fontSize: 11,
    fontWeight: "800",
    color: "#FF4747",
    letterSpacing: 1.5,
    marginBottom: 2,
  },
  headerTitle: {
    fontSize: 28,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: -0.5,
  },
  avatar: { width: 48, height: 48, borderRadius: 24, borderWidth: 2, borderColor: "#000" },
  avatarFallback: { backgroundColor: "#FFE600", alignItems: "center", justifyContent: "center" },
  avatarText: { fontWeight: "900", fontSize: 18 },
  chipsScroll: { height: 56 },
  chipsRow: {
    paddingHorizontal: 16,
    gap: 10,
    alignItems: "center",
    height: 56,
  },
  chip: {
    flexShrink: 0,
    height: 36,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 14,
    backgroundColor: "#FFFFFF",
    borderRadius: 999,
    borderWidth: 2,
    borderColor: "#0A0A0A",
    gap: 6,
  },
  chipActive: { backgroundColor: "#0A0A0A" },
  chipEmoji: { fontSize: 14 },
  chipText: { fontWeight: "800", fontSize: 13, color: "#0A0A0A" },
  chipTextActive: { color: "#FFFFFF" },
  listContent: { padding: 16, paddingBottom: 80, gap: 14 },
  card: {
    backgroundColor: "#FFFFFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 24,
    padding: 18,
    shadowColor: "#000",
    shadowOffset: { width: 4, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
    gap: 10,
  },
  cardHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 6 },
  catPill: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 2,
    borderColor: "#000",
    gap: 6,
  },
  catPillEmoji: { fontSize: 14 },
  catPillText: { fontWeight: "900", fontSize: 12, color: "#0A0A0A", textTransform: "uppercase" },
  ageChip: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#FFE600",
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 999,
    borderWidth: 2,
    borderColor: "#000",
    gap: 4,
  },
  ageChipText: { fontWeight: "800", fontSize: 11, color: "#0A0A0A" },
  headerBadges: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    flexShrink: 0,
  },
  genderBadge: {
    borderWidth: 1.5,
    borderColor: "#0A0A0A",
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  genderBadgeText: { fontWeight: "800", fontSize: 10, color: "#0A0A0A" },
  cardTitle: { fontSize: 22, fontWeight: "900", color: "#0A0A0A", letterSpacing: -0.5 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  metaText: { color: "#525252", fontSize: 14, fontWeight: "600", flex: 1 },
  progressContainer: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 4 },
  progressBar: {
    flex: 1,
    height: 12,
    backgroundColor: "#F1F1F1",
    borderRadius: 999,
    borderWidth: 2,
    borderColor: "#000",
    overflow: "hidden",
  },
  progressFill: { height: "100%" },
  progressText: { fontWeight: "900", fontSize: 14, color: "#0A0A0A" },
  loadingWrap: { flex: 1, alignItems: "center", justifyContent: "center" },
  emptyWrap: { alignItems: "center", paddingVertical: 60, gap: 8 },
  emptyEmoji: { fontSize: 48 },
  emptyTitle: { fontSize: 22, fontWeight: "900", color: "#0A0A0A" },
  emptySub: { color: "#525252", fontSize: 14, textAlign: "center", paddingHorizontal: 40 },
  distanceBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginHorizontal: 16,
    marginTop: 4,
    backgroundColor: "#FFE600",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  distanceBannerText: {
    flex: 1,
    fontWeight: "800",
    color: "#0A0A0A",
    fontSize: 13,
  },
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: "#FDFBF7",
    borderTopWidth: 2,
    borderColor: "#000",
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    padding: 24,
    paddingBottom: 36,
    gap: 12,
    alignItems: "center",
  },
  sheetEmoji: { fontSize: 48 },
  sheetTitle: {
    fontSize: 22,
    fontWeight: "900",
    color: "#0A0A0A",
    textAlign: "center",
  },
  sheetSub: {
    fontSize: 14,
    color: "#525252",
    textAlign: "center",
    fontWeight: "600",
    marginBottom: 8,
  },
  primaryBtn: {
    width: "100%",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: "#FFE600",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingVertical: 16,
    shadowColor: "#000",
    shadowOffset: { width: 3, height: 3 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 3,
  },
  primaryBtnText: {
    fontWeight: "900",
    color: "#0A0A0A",
    fontSize: 15,
    letterSpacing: 0.5,
  },
  secondaryBtn: {
    width: "100%",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingVertical: 14,
  },
  secondaryBtnText: {
    fontWeight: "900",
    color: "#0A0A0A",
    fontSize: 14,
  },
  skipBtn: { paddingVertical: 8 },
  skipBtnText: { color: "#525252", fontWeight: "700", textDecorationLine: "underline" },
  manualError: { color: "#FF4747", fontWeight: "800", textAlign: "center" },
});
