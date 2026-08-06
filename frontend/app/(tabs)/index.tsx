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
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/contexts/auth";
import { api, ApiGroup } from "@/src/lib/api";
import { CATEGORIES, CUSTOM_CATEGORY, findCategory } from "@/src/lib/categories";
import { formatDate } from "@/src/lib/date";

const ALL_FILTER = { id: "all", label: "Tutti", emoji: "✨", color: "#0A0A0A" };

export default function HomeScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const [groups, setGroups] = useState<ApiGroup[]>([]);
  const [category, setCategory] = useState<string>("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const list = await api.listGroups(category);
      setGroups(list);
    } catch (e) {
      console.warn("listGroups", e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [category]);

  useEffect(() => {
    setLoading(true);
    load();
  }, [load]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

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
          <View style={styles.ageChip}>
            <Ionicons name="people" size={12} color="#0A0A0A" />
            <Text style={styles.ageChipText}>
              {item.min_age}-{item.max_age} anni
            </Text>
          </View>
        </View>

        <Text style={styles.cardTitle} numberOfLines={2}>
          {item.title}
        </Text>

        <View style={styles.metaRow}>
          <Ionicons name="location-sharp" size={16} color="#525252" />
          <Text style={styles.metaText} numberOfLines={1}>
            {item.location}
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
                Sii il primo a crearne uno! Tocca &quot;Crea&quot; per iniziare.
              </Text>
            </View>
          }
        />
      )}
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
  cardHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
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
});
