import { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Image,
  ActivityIndicator,
  RefreshControl,
  Linking,
  Alert,
  Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import Slider from "@react-native-community/slider";

import { useAuth } from "@/src/contexts/auth";
import { useLocationPrefs } from "@/src/contexts/location";
import { api, ApiGroup, CitySuggestion } from "@/src/lib/api";
import { findCategory, CUSTOM_CATEGORY } from "@/src/lib/categories";
import { formatDate } from "@/src/lib/date";
import { CityAutocomplete } from "@/src/components/CityAutocomplete";
import { AdminUnlock } from "@/src/components/AdminUnlock";
import { TERMS_TEXT, TERMS_VERSION } from "@/src/lib/terms";

type Tab = "created" | "joined";

export default function ProfileScreen() {
  const { user, deviceId, signOut } = useAuth();
  const {
    prefs,
    permission,
    canAskAgain,
    setRadiusKm,
    requestGps,
    setManualLocation,
    clearLocation,
  } = useLocationPrefs();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("created");
  const [created, setCreated] = useState<ApiGroup[]>([]);
  const [joined, setJoined] = useState<ApiGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [termsOpen, setTermsOpen] = useState(false);
  const [manualCity, setManualCity] = useState(prefs.manualCity);
  const [manualPick, setManualPick] = useState<CitySuggestion | null>(null);
  const [manualBusy, setManualBusy] = useState(false);
  const [manualError, setManualError] = useState<string | null>(null);
  const [sliderValue, setSliderValue] = useState(prefs.radiusKm);

  // Sync slider when prefs load asynchronously from AsyncStorage.
  useEffect(() => {
    setSliderValue(prefs.radiusKm);
  }, [prefs.radiusKm]);

  useEffect(() => {
    setManualCity(prefs.manualCity);
  }, [prefs.manualCity]);

  const load = useCallback(async () => {
    if (!deviceId) return;
    try {
      const data = await api.myGroups();
      setCreated(data.created);
      setJoined(data.joined);
    } catch (e) {
      console.warn("myGroups", e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [deviceId]);

  useFocusEffect(
    useCallback(() => {
      setLoading(true);
      load();
    }, [load]),
  );

  const onRefresh = () => {
    setRefreshing(true);
    load();
  };

  const list = tab === "created" ? created : joined;

  const renderItem = (g: ApiGroup) => {
    const cat = findCategory(g.category) || CUSTOM_CATEGORY;
    return (
      <TouchableOpacity
        key={g.group_id}
        testID={`my-group-${g.group_id}`}
        activeOpacity={0.85}
        onPress={() => router.push(`/group/${g.group_id}`)}
        style={styles.item}
      >
        <View style={[styles.itemIcon, { backgroundColor: cat.color }]}>
          <Text style={{ fontSize: 22 }}>{cat.emoji}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.itemTitle} numberOfLines={1}>
            {g.title}
          </Text>
          <Text style={styles.itemMeta}>
            {formatDate(g.date)} · {g.time} · {g.participants.length}/{g.max_participants}
          </Text>
        </View>
        <Ionicons name="chevron-forward" size={20} color="#0A0A0A" />
      </TouchableOpacity>
    );
  };

  return (
    <SafeAreaView style={styles.container} edges={["top"]} testID="profile-screen">
      <ScrollView
        contentContainerStyle={{ padding: 20, paddingBottom: 60 }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#FF4747" />
        }
      >
        <View style={styles.profileCard}>
          {user?.picture ? (
            <Image source={{ uri: user.picture }} style={styles.bigAvatar} />
          ) : (
            <View style={[styles.bigAvatar, styles.avatarFallback]}>
              <Text style={{ fontSize: 36, fontWeight: "900" }}>
                {(user?.name || "?").charAt(0).toUpperCase()}
              </Text>
            </View>
          )}
          <Text style={styles.name}>{user?.name || "Anonimo"}</Text>
          {user?.user_id ? (
            <Text style={styles.email} numberOfLines={1}>
              ID: {user.user_id.slice(0, 14)}…
            </Text>
          ) : null}

          <View style={styles.metaRow}>
            {user?.gender && (
              <View style={styles.metaPill}>
                <Text style={styles.metaPillText}>
                  {user.gender === "male" ? "👨 Uomo" : user.gender === "female" ? "👩 Donna" : "🌈 Altro"}
                </Text>
              </View>
            )}
            {user?.age != null && (
              <View style={styles.metaPill}>
                <Text style={styles.metaPillText}>🎂 {user.age} anni</Text>
              </View>
            )}
          </View>

          <TouchableOpacity
            testID="edit-profile-button"
            activeOpacity={0.85}
            onPress={() => router.push("/profile-edit")}
            style={styles.editBtn}
          >
            <Ionicons name="create" size={16} color="#0A0A0A" />
            <Text style={styles.editBtnText}>Modifica profilo</Text>
          </TouchableOpacity>
        </View>

        {/* ============================== Distance filter ============================== */}
        <View style={styles.section} testID="distance-section">
          <View style={styles.sectionHeader}>
            <Ionicons name="locate" size={18} color="#0A0A0A" />
            <Text style={styles.sectionTitle}>Distanza gruppi</Text>
          </View>

          <View style={styles.sliderRow}>
            <Text style={styles.sliderLabel}>1 km</Text>
            <Slider
              testID="distance-slider"
              style={{ flex: 1, height: 40 }}
              minimumValue={1}
              maximumValue={100}
              step={1}
              value={sliderValue}
              minimumTrackTintColor="#FF4747"
              maximumTrackTintColor="#D4D4D4"
              thumbTintColor="#0A0A0A"
              onValueChange={(v) => setSliderValue(Math.round(v))}
              onSlidingComplete={(v) => setRadiusKm(Math.round(v))}
            />
            <Text style={styles.sliderLabel}>100 km</Text>
          </View>
          <View style={styles.radiusBadgeWrap}>
            <View style={styles.radiusBadge}>
              <Text style={styles.radiusBadgeText} testID="distance-value">
                {Math.round(sliderValue)} km
              </Text>
            </View>
          </View>

          <View style={styles.locationStatus}>
            {prefs.lat != null && prefs.lon != null ? (
              <>
                <Ionicons
                  name={prefs.source === "gps" ? "location" : "pin"}
                  size={16}
                  color="#10B981"
                />
                <Text style={styles.locationStatusText} numberOfLines={1}>
                  {prefs.source === "gps"
                    ? "GPS attivo"
                    : `Riferimento: ${prefs.manualCity || "città"}${prefs.manualProvince ? ` (${prefs.manualProvince})` : ""}`}
                </Text>
              </>
            ) : (
              <>
                <Ionicons name="alert-circle" size={16} color="#FF4747" />
                <Text style={styles.locationStatusText}>
                  Posizione non impostata (filtro disattivato)
                </Text>
              </>
            )}
          </View>

          <View style={styles.locationActions}>
            <TouchableOpacity
              testID="use-gps-btn"
              activeOpacity={0.85}
              onPress={async () => {
                if (permission !== "granted" && !canAskAgain) {
                  Alert.alert(
                    "Permessi disattivati",
                    "Abilita la posizione dalle impostazioni di sistema.",
                    [
                      { text: "Apri impostazioni", onPress: () => Linking.openSettings() },
                      { text: "Annulla", style: "cancel" },
                    ],
                  );
                  return;
                }
                const ok = await requestGps();
                if (!ok) {
                  Alert.alert(
                    "Permesso negato",
                    "Non hai concesso l'accesso alla posizione. Puoi impostare una città di riferimento.",
                  );
                }
              }}
              style={styles.locBtn}
            >
              <Ionicons name="locate" size={16} color="#0A0A0A" />
              <Text style={styles.locBtnText}>Usa GPS</Text>
            </TouchableOpacity>

            <TouchableOpacity
              testID="use-city-btn"
              activeOpacity={0.85}
              onPress={() => {
                setManualCity(prefs.manualCity);
                setManualError(null);
                setManualOpen((v) => !v);
              }}
              style={styles.locBtn}
            >
              <Ionicons name="location-outline" size={16} color="#0A0A0A" />
              <Text style={styles.locBtnText}>Città</Text>
            </TouchableOpacity>

            {(prefs.lat != null || prefs.lon != null) && (
              <TouchableOpacity
                testID="clear-loc-btn"
                activeOpacity={0.85}
                onPress={clearLocation}
                style={[styles.locBtn, { backgroundColor: "#FFF" }]}
              >
                <Ionicons name="close-circle" size={16} color="#FF4747" />
                <Text style={styles.locBtnText}>Rimuovi</Text>
              </TouchableOpacity>
            )}
          </View>

          {manualOpen && (
            <View style={{ gap: 8, marginTop: 12 }}>
              <CityAutocomplete
                testID="manual-city-input"
                value={manualCity}
                onChangeText={(t) => {
                  setManualCity(t);
                  setManualPick(null);
                }}
                onSelect={(c) => {
                  setManualCity(c.name);
                  setManualPick(c);
                }}
                placeholder="Es. Milano"
              />
              {manualError ? (
                <Text style={styles.error} testID="manual-error">
                  {manualError}
                </Text>
              ) : null}
              <TouchableOpacity
                testID="manual-city-submit"
                activeOpacity={0.85}
                onPress={async () => {
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
                  setManualOpen(false);
                  setManualPick(null);
                }}
                disabled={manualBusy}
                style={[styles.locConfirmBtn, manualBusy && { opacity: 0.6 }]}
              >
                {manualBusy ? (
                  <ActivityIndicator color="#0A0A0A" />
                ) : (
                  <Text style={styles.locConfirmBtnText}>Conferma città</Text>
                )}
              </TouchableOpacity>
            </View>
          )}
        </View>

        <View style={styles.tabs}>
          <TouchableOpacity
            testID="tab-created"
            onPress={() => setTab("created")}
            activeOpacity={0.85}
            style={[styles.tab, tab === "created" && styles.tabActive]}
          >
            <Text style={[styles.tabText, tab === "created" && styles.tabTextActive]}>
              Creati ({created.length})
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            testID="tab-joined"
            onPress={() => setTab("joined")}
            activeOpacity={0.85}
            style={[styles.tab, tab === "joined" && styles.tabActive]}
          >
            <Text style={[styles.tabText, tab === "joined" && styles.tabTextActive]}>
              Partecipati ({joined.length})
            </Text>
          </TouchableOpacity>
        </View>

        {loading ? (
          <ActivityIndicator color="#FF4747" style={{ marginTop: 30 }} />
        ) : list.length === 0 ? (
          <View style={styles.empty}>
            <Text style={styles.emptyEmoji}>🌟</Text>
            <Text style={styles.emptyTitle}>
              {tab === "created" ? "Nessun gruppo creato" : "Nessun gruppo seguito"}
            </Text>
            <Text style={styles.emptySub}>
              {tab === "created"
                ? "Crea il tuo primo gruppo dal tab Crea."
                : "Trova un gruppo nella Esplora e uniscit!"}
            </Text>
          </View>
        ) : (
          <View style={{ gap: 10, marginTop: 14 }}>{list.map(renderItem)}</View>
        )}

        <TouchableOpacity
          testID="terms-button"
          activeOpacity={0.85}
          onPress={() => setTermsOpen(true)}
          style={styles.termsLink}
        >
          <Ionicons name="document-text-outline" size={18} color="#0A0A0A" />
          <Text style={styles.termsLinkText}>Regolamento e responsabilità</Text>
          <Ionicons name="chevron-forward" size={18} color="#0A0A0A" />
        </TouchableOpacity>

        <TouchableOpacity
          testID="reset-button"
          activeOpacity={0.85}
          onPress={async () => {
            await signOut();
            router.replace("/");
          }}
          style={styles.logout}
        >
          <Ionicons name="refresh" size={20} color="#0A0A0A" />
          <Text style={styles.logoutText}>Reimposta account</Text>
        </TouchableOpacity>

        <TouchableOpacity
          testID="delete-account-button"
          activeOpacity={0.85}
          onPress={() => {
            Alert.alert(
              "Eliminare l'account?",
              "Questa azione è irreversibile. Verranno eliminati definitivamente:\n\n• Il tuo profilo\n• Tutti i gruppi che hai creato (con le relative chat)\n• I tuoi messaggi\n• Le tue segnalazioni\n\nContinuare?",
              [
                { text: "Annulla", style: "cancel" },
                {
                  text: "Elimina",
                  style: "destructive",
                  onPress: () => {
                    Alert.alert(
                      "Sei sicuro?",
                      "Ultima conferma: i dati eliminati non potranno essere recuperati.",
                      [
                        { text: "Annulla", style: "cancel" },
                        {
                          text: "Sì, elimina definitivamente",
                          style: "destructive",
                          onPress: async () => {
                            try {
                              await api.deleteAccount();
                              await signOut();
                              router.replace("/");
                            } catch (e: any) {
                              Alert.alert(
                                "Errore",
                                e?.message || "Impossibile eliminare l'account",
                              );
                            }
                          },
                        },
                      ],
                    );
                  },
                },
              ],
            );
          }}
          style={styles.deleteAccount}
        >
          <Ionicons name="trash" size={20} color="#FFE600" />
          <Text style={styles.deleteAccountText}>Elimina account</Text>
        </TouchableOpacity>

        <AdminUnlock />
      </ScrollView>

      <Modal
        visible={termsOpen}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setTermsOpen(false)}
      >
        <SafeAreaView style={{ flex: 1, backgroundColor: "#FDFBF7" }} edges={["top", "bottom"]}>
          <View style={styles.termsModalHeader}>
            <Text style={styles.termsModalTitle}>Regolamento GroupUp</Text>
            <TouchableOpacity onPress={() => setTermsOpen(false)} style={{ padding: 4 }}>
              <Ionicons name="close" size={24} color="#0A0A0A" />
            </TouchableOpacity>
          </View>
          <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 40 }}>
            <Text style={styles.termsMeta}>
              Versione {TERMS_VERSION}
              {user?.terms_accepted_at
                ? ` · Accettato il ${new Date(user.terms_accepted_at).toLocaleDateString("it-IT")}`
                : ""}
            </Text>
            <Text style={styles.termsBodyText}>{TERMS_TEXT}</Text>
          </ScrollView>
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FDFBF7" },
  profileCard: {
    backgroundColor: "#FFFFFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 24,
    padding: 24,
    alignItems: "center",
    gap: 8,
    shadowColor: "#000",
    shadowOffset: { width: 4, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
  },
  bigAvatar: { width: 100, height: 100, borderRadius: 50, borderWidth: 3, borderColor: "#000" },
  avatarFallback: { backgroundColor: "#FFE600", alignItems: "center", justifyContent: "center" },
  name: { fontSize: 24, fontWeight: "900", color: "#0A0A0A" },
  email: { fontSize: 14, color: "#525252", fontWeight: "600" },
  metaRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 8, justifyContent: "center" },
  metaPill: {
    backgroundColor: "#FFE600",
    borderWidth: 2,
    borderColor: "#000",
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
  },
  metaPillText: { fontWeight: "800", color: "#0A0A0A" },
  editBtn: {
    marginTop: 12,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 999,
  },
  editBtnText: { fontWeight: "900", color: "#0A0A0A", letterSpacing: 0.5 },
  tabs: {
    flexDirection: "row",
    marginTop: 20,
    gap: 8,
  },
  tab: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 16,
    borderWidth: 2,
    borderColor: "#0A0A0A",
    alignItems: "center",
    backgroundColor: "#FFF",
  },
  tabActive: { backgroundColor: "#0A0A0A" },
  tabText: { fontWeight: "900", color: "#0A0A0A", letterSpacing: 0.5 },
  tabTextActive: { color: "#FFE600" },
  item: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 16,
    padding: 12,
    gap: 12,
  },
  itemIcon: {
    width: 50,
    height: 50,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: "#000",
    alignItems: "center",
    justifyContent: "center",
  },
  itemTitle: { fontSize: 16, fontWeight: "900", color: "#0A0A0A" },
  itemMeta: { color: "#525252", fontWeight: "600", marginTop: 2 },
  empty: { alignItems: "center", paddingVertical: 40, gap: 6 },
  emptyEmoji: { fontSize: 44 },
  emptyTitle: { fontSize: 18, fontWeight: "900", color: "#0A0A0A" },
  emptySub: { color: "#525252", textAlign: "center", paddingHorizontal: 30 },
  logout: {
    marginTop: 30,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: "#FF4747",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingVertical: 16,
    shadowColor: "#000",
    shadowOffset: { width: 4, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
  },
  logoutText: { fontWeight: "900", color: "#0A0A0A", textTransform: "uppercase", letterSpacing: 1 },
  deleteAccount: {
    marginTop: 12,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: "#0A0A0A",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingVertical: 16,
    shadowColor: "#000",
    shadowOffset: { width: 4, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
  },
  deleteAccountText: {
    fontWeight: "900",
    color: "#FFE600",
    textTransform: "uppercase",
    letterSpacing: 1,
  },
  termsLink: {
    marginTop: 20,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 16,
    paddingVertical: 14,
    paddingHorizontal: 14,
  },
  termsLinkText: {
    flex: 1,
    fontWeight: "800",
    color: "#0A0A0A",
    fontSize: 14,
  },
  termsModalHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: 16,
    borderBottomWidth: 2,
    borderBottomColor: "#0A0A0A",
  },
  termsModalTitle: { fontSize: 18, fontWeight: "900", color: "#0A0A0A" },
  termsMeta: {
    fontSize: 12,
    color: "#525252",
    fontWeight: "700",
    marginBottom: 12,
    fontStyle: "italic",
  },
  termsBodyText: {
    fontSize: 13,
    lineHeight: 20,
    color: "#0A0A0A",
  },
  section: {
    marginTop: 20,
    backgroundColor: "#FFFFFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 24,
    padding: 18,
    gap: 10,
    shadowColor: "#000",
    shadowOffset: { width: 4, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
  },
  sectionHeader: { flexDirection: "row", alignItems: "center", gap: 8 },
  sectionTitle: { fontSize: 16, fontWeight: "900", color: "#0A0A0A", letterSpacing: 0.3 },
  sliderRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  sliderLabel: { fontSize: 11, fontWeight: "800", color: "#525252" },
  radiusBadgeWrap: { alignItems: "center" },
  radiusBadge: {
    backgroundColor: "#FFE600",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 4,
  },
  radiusBadgeText: { fontWeight: "900", color: "#0A0A0A", fontSize: 14 },
  locationStatus: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 6,
  },
  locationStatusText: { fontWeight: "700", color: "#0A0A0A", fontSize: 13, flex: 1 },
  locationActions: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 4,
  },
  locBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderWidth: 2,
    borderColor: "#0A0A0A",
    backgroundColor: "#FFE600",
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  locBtnText: { fontWeight: "900", color: "#0A0A0A", fontSize: 13 },
  cityInput: {
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    fontWeight: "600",
    color: "#0A0A0A",
  },
  locConfirmBtn: {
    backgroundColor: "#0A0A0A",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingVertical: 14,
    alignItems: "center",
  },
  locConfirmBtnText: { fontWeight: "900", color: "#FFE600", letterSpacing: 0.5 },
  error: { color: "#FF4747", fontWeight: "800" },
});
