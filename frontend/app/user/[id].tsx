import { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Image,
  ActivityIndicator,
  TouchableOpacity,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api, PublicUser } from "@/src/lib/api";
import { useAuth } from "@/src/contexts/auth";

/**
 * Public profile view of another user. Accessible from group participant
 * lists and chat message authors. The backend enforces that the caller must
 * share at least one group with the target — otherwise it returns 403.
 */
export default function UserProfile() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user: me } = useAuth();

  const [profile, setProfile] = useState<PublicUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!id) return;
      try {
        const p = await api.getUser(id);
        if (!cancelled) setProfile(p);
      } catch (e: any) {
        if (!cancelled) setError(e?.message || "Errore");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const genderLabel = (g?: string | null) => {
    if (g === "male") return "Uomo";
    if (g === "female") return "Donna";
    if (g === "other") return "Altro";
    return null;
  };

  const isMe = profile?.user_id === me?.user_id;

  return (
    <SafeAreaView style={styles.container} edges={["top"]} testID="user-profile-screen">
      <View style={styles.header}>
        <TouchableOpacity
          testID="user-back"
          onPress={() => router.back()}
          style={styles.backBtn}
          activeOpacity={0.85}
        >
          <Ionicons name="chevron-back" size={26} color="#0A0A0A" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>PROFILO</Text>
        <View style={{ width: 42 }} />
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#FF4747" />
        </View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.emoji}>🔒</Text>
          <Text style={styles.errorTitle}>Profilo non visibile</Text>
          <Text style={styles.errorBody}>{error}</Text>
        </View>
      ) : profile ? (
        <ScrollView contentContainerStyle={styles.body}>
          <View style={styles.avatarWrap}>
            {profile.picture ? (
              <Image source={{ uri: profile.picture }} style={styles.avatar} />
            ) : (
              <View style={[styles.avatar, styles.avatarFallback]}>
                <Text style={styles.avatarInitial}>
                  {profile.name?.charAt(0).toUpperCase() || "?"}
                </Text>
              </View>
            )}
          </View>

          <Text testID="user-name" style={styles.name}>
            {profile.name}
            {isMe ? "  (tu)" : ""}
          </Text>

          <View style={styles.chipsRow}>
            {profile.age != null && (
              <View style={styles.chip}>
                <Ionicons name="calendar-outline" size={14} color="#0A0A0A" />
                <Text style={styles.chipText}>{profile.age} anni</Text>
              </View>
            )}
            {!!genderLabel(profile.gender) && (
              <View style={styles.chip}>
                <Ionicons name="person-outline" size={14} color="#0A0A0A" />
                <Text style={styles.chipText}>{genderLabel(profile.gender)}</Text>
              </View>
            )}
          </View>

          {profile.age == null && !genderLabel(profile.gender) && (
            <Text style={styles.emptyInfo}>
              Questo utente non ha ancora completato il profilo.
            </Text>
          )}

          <View style={styles.card}>
            <Ionicons name="shield-checkmark" size={18} color="#0A0A0A" />
            <Text style={styles.cardText}>
              Visibile perché siete membri dello stesso gruppo.
            </Text>
          </View>
        </ScrollView>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FDFBF7" },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: "#EDE7DA",
  },
  backBtn: {
    width: 42,
    height: 42,
    alignItems: "center",
    justifyContent: "center",
  },
  headerTitle: {
    fontWeight: "900",
    letterSpacing: 1.5,
    color: "#0A0A0A",
    fontSize: 13,
  },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 32,
    gap: 12,
  },
  emoji: { fontSize: 56 },
  errorTitle: {
    fontSize: 20,
    fontWeight: "900",
    color: "#0A0A0A",
    marginTop: 4,
  },
  errorBody: {
    fontSize: 14,
    color: "#525252",
    textAlign: "center",
    fontWeight: "600",
    lineHeight: 20,
  },
  body: { padding: 24, alignItems: "center", gap: 12 },
  avatarWrap: { marginTop: 8 },
  avatar: {
    width: 128,
    height: 128,
    borderRadius: 64,
    borderWidth: 3,
    borderColor: "#0A0A0A",
    backgroundColor: "#EDE7DA",
  },
  avatarFallback: { alignItems: "center", justifyContent: "center" },
  avatarInitial: {
    fontSize: 48,
    fontWeight: "900",
    color: "#0A0A0A",
  },
  name: {
    fontSize: 28,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: -0.5,
    marginTop: 4,
    textAlign: "center",
  },
  chipsRow: {
    flexDirection: "row",
    gap: 8,
    flexWrap: "wrap",
    justifyContent: "center",
    marginTop: 8,
  },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: "#FFF",
  },
  chipText: {
    fontWeight: "800",
    color: "#0A0A0A",
    fontSize: 13,
  },
  emptyInfo: {
    marginTop: 12,
    color: "#8A8A8A",
    fontSize: 13,
    fontWeight: "600",
    textAlign: "center",
    lineHeight: 18,
  },
  card: {
    marginTop: 24,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: "#FFE600",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
    shadowColor: "#000",
    shadowOffset: { width: 3, height: 3 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 3,
  },
  cardText: {
    flex: 1,
    fontSize: 13,
    fontWeight: "700",
    color: "#0A0A0A",
    lineHeight: 18,
  },
});
