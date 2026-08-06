import { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Image,
  ActivityIndicator,
  RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/contexts/auth";
import { api, ApiGroup } from "@/src/lib/api";
import { findCategory, CUSTOM_CATEGORY } from "@/src/lib/categories";

type Tab = "created" | "joined";

export default function ProfileScreen() {
  const { user, token, signOut } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("created");
  const [created, setCreated] = useState<ApiGroup[]>([]);
  const [joined, setJoined] = useState<ApiGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const data = await api.myGroups(token);
      setCreated(data.created);
      setJoined(data.joined);
    } catch (e) {
      console.warn("myGroups", e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token]);

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
            {g.date} · {g.time} · {g.participants.length}/{g.max_participants}
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
          <Text style={styles.name}>{user?.name}</Text>
          <Text style={styles.email}>{user?.email}</Text>

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
          testID="logout-button"
          activeOpacity={0.85}
          onPress={async () => {
            await signOut();
            router.replace("/login");
          }}
          style={styles.logout}
        >
          <Ionicons name="log-out" size={20} color="#0A0A0A" />
          <Text style={styles.logoutText}>Esci</Text>
        </TouchableOpacity>
      </ScrollView>
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
});
