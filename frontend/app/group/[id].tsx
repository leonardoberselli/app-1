import { useCallback, useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Image,
  ActivityIndicator,
  TextInput,
  FlatList,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/contexts/auth";
import { api, ApiGroup, ApiMessage } from "@/src/lib/api";
import { findCategory, CUSTOM_CATEGORY } from "@/src/lib/categories";
import { formatDate } from "@/src/lib/date";
import { ReportSheet } from "@/src/components/ReportSheet";

type ReportTarget =
  | { type: "group"; id: string; label?: string }
  | { type: "user"; id: string; label?: string }
  | { type: "message"; id: string; label?: string };

export default function GroupDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user, deviceId } = useAuth();
  const router = useRouter();

  const [group, setGroup] = useState<ApiGroup | null>(null);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [tab, setTab] = useState<"info" | "chat">("info");

  const [messages, setMessages] = useState<ApiMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [reportTarget, setReportTarget] = useState<ReportTarget | null>(null);
  const flatRef = useRef<FlatList<ApiMessage>>(null);

  const loadGroup = useCallback(async () => {
    if (!id) return;
    try {
      const g = await api.getGroup(id);
      setGroup(g);
    } catch (e) {
      console.warn("getGroup", e);
    } finally {
      setLoading(false);
    }
  }, [id]);

  const loadMessages = useCallback(async () => {
    if (!id || !deviceId) return;
    try {
      const ms = await api.getMessages(id);
      setMessages(ms);
      setChatError(null);
    } catch (e: any) {
      setChatError(e?.message || "Errore chat");
    }
  }, [id, deviceId]);

  useEffect(() => {
    loadGroup();
  }, [loadGroup]);

  const isParticipant = !!group?.participants.find((p) => p.user_id === user?.user_id);
  const isOwner = group?.owner_id === user?.user_id;

  useEffect(() => {
    if (tab === "chat" && isParticipant) {
      loadMessages();
      const t = setInterval(loadMessages, 4000);
      return () => clearInterval(t);
    }
  }, [tab, isParticipant, loadMessages]);

  const handleJoin = async () => {
    if (!deviceId || !id) return;
    try {
      setActing(true);
      const g = await api.joinGroup(id);
      setGroup(g);
    } catch (e: any) {
      setChatError(e?.message || "Errore");
    } finally {
      setActing(false);
    }
  };

  const handleLeave = async () => {
    if (!deviceId || !id) return;
    try {
      setActing(true);
      const g = await api.leaveGroup(id);
      setGroup(g);
    } catch (e) {
      console.warn(e);
    } finally {
      setActing(false);
    }
  };

  const handleDelete = async () => {
    if (!deviceId || !id) return;
    try {
      setActing(true);
      await api.deleteGroup(id);
      router.back();
    } catch (e) {
      console.warn(e);
    } finally {
      setActing(false);
    }
  };

  const sendMessage = async () => {
    const text = draft.trim();
    if (!text || !deviceId || !id) return;
    try {
      setSending(true);
      const m = await api.postMessage(id, text);
      setMessages((prev) => [...prev, m]);
      setDraft("");
      setTimeout(() => flatRef.current?.scrollToEnd({ animated: true }), 50);
    } catch (e: any) {
      setChatError(e?.message || "Errore invio");
    } finally {
      setSending(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.center} testID="group-loading">
        <ActivityIndicator size="large" color="#FF4747" />
      </View>
    );
  }

  if (!group) {
    return (
      <SafeAreaView style={styles.center} edges={["top"]}>
        <Text style={styles.emptyTitle}>Gruppo non trovato</Text>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}>
          <Text style={styles.backBtnText}>Indietro</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  const cat = findCategory(group.category) || CUSTOM_CATEGORY;
  const isFull = group.participants.length >= group.max_participants;

  return (
    <SafeAreaView style={styles.container} edges={["top"]} testID="group-screen">
      <View style={styles.topBar}>
        <TouchableOpacity
          testID="back-button"
          onPress={() => router.back()}
          style={styles.iconBtn}
        >
          <Ionicons name="chevron-back" size={22} color="#0A0A0A" />
        </TouchableOpacity>
        <View style={[styles.catPill, { backgroundColor: cat.color }]}>
          <Text style={styles.catPillEmoji}>{cat.emoji}</Text>
          <Text style={styles.catPillText}>{group.category_label}</Text>
        </View>
        {isOwner ? (
          <TouchableOpacity
            testID="delete-group-button"
            onPress={handleDelete}
            disabled={acting}
            style={[styles.iconBtn, { backgroundColor: "#FF4747" }]}
          >
            <Ionicons name="trash" size={18} color="#FFF" />
          </TouchableOpacity>
        ) : (
          <TouchableOpacity
            testID="report-group-button"
            onPress={() =>
              setReportTarget({
                type: "group",
                id: group.group_id,
                label: group.title,
              })
            }
            style={[styles.iconBtn, { backgroundColor: "#FFE600" }]}
          >
            <Ionicons name="flag" size={18} color="#0A0A0A" />
          </TouchableOpacity>
        )}
      </View>

      <View style={styles.safetyBanner} testID="safety-banner">
        <Ionicons name="shield-checkmark" size={18} color="#0A0A0A" />
        <Text style={styles.safetyText}>
          Per la tua sicurezza, ritrovatevi sempre in luoghi pubblici, affollati e ben illuminati.
        </Text>
      </View>

      <View style={styles.segment}>
        <TouchableOpacity
          testID="seg-info"
          onPress={() => setTab("info")}
          style={[styles.segBtn, tab === "info" && styles.segActive]}
        >
          <Text style={[styles.segText, tab === "info" && styles.segTextActive]}>Info</Text>
        </TouchableOpacity>
        <TouchableOpacity
          testID="seg-chat"
          onPress={() => setTab("chat")}
          style={[styles.segBtn, tab === "chat" && styles.segActive]}
        >
          <Text style={[styles.segText, tab === "chat" && styles.segTextActive]}>Chat</Text>
        </TouchableOpacity>
      </View>

      {tab === "info" ? (
        <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 140, gap: 14 }}>
          <Text style={styles.title}>{group.title}</Text>

          <View style={styles.infoCard}>
            <View style={styles.infoRow}>
              <Ionicons name="location-sharp" size={18} color="#FF4747" />
              <Text style={styles.infoText}>
                {[group.location, group.city ? (group.province ? `${group.city} (${group.province})` : group.city) : null]
                  .filter(Boolean)
                  .join(" · ")}
              </Text>
            </View>
            <View style={styles.infoRow}>
              <Ionicons name="calendar" size={18} color="#FF4747" />
              <Text style={styles.infoText}>
                {formatDate(group.date)} · ore {group.time}
              </Text>
            </View>
            <View style={styles.infoRow}>
              <Ionicons name="people" size={18} color="#FF4747" />
              <Text style={styles.infoText}>
                {group.participants.length}/{group.max_participants} (min {group.min_participants})
              </Text>
            </View>
            <View style={styles.infoRow}>
              <Ionicons name="person" size={18} color="#FF4747" />
              <Text style={styles.infoText}>
                Età {group.min_age}-{group.max_age} anni
              </Text>
            </View>
            {!!group.description && (
              <Text style={styles.desc}>{group.description}</Text>
            )}
          </View>

          <Text style={styles.sectionLabel}>PARTECIPANTI</Text>
          <View style={styles.participantsWrap}>
            {group.participants.map((p) => {
              const canView = isParticipant || p.user_id === user?.user_id;
              const Wrapper: any = canView ? TouchableOpacity : View;
              return (
                <Wrapper
                  key={p.user_id}
                  testID={`participant-${p.user_id}`}
                  activeOpacity={canView ? 0.7 : 1}
                  onPress={
                    canView ? () => router.push(`/user/${p.user_id}`) : undefined
                  }
                  style={styles.participant}
                >
                  {p.picture ? (
                    <Image source={{ uri: p.picture }} style={styles.partAvatar} />
                  ) : (
                    <View style={[styles.partAvatar, styles.partFallback]}>
                      <Text style={{ fontWeight: "900" }}>
                        {p.name?.charAt(0).toUpperCase()}
                      </Text>
                    </View>
                  )}
                  <Text style={styles.partName} numberOfLines={1}>
                    {p.user_id === group.owner_id ? "👑 " : ""}
                    {p.name}
                  </Text>
                </Wrapper>
              );
            })}
          </View>
          {!isParticipant && (
            <Text style={styles.hintText}>
              Unisciti al gruppo per vedere il profilo dei partecipanti.
            </Text>
          )}
        </ScrollView>
      ) : (
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : "height"}
          keyboardVerticalOffset={Platform.OS === "ios" ? 0 : 0}
          style={{ flex: 1 }}
        >
          {!isParticipant ? (
            <View style={styles.chatLocked}>
              <Ionicons name="lock-closed" size={36} color="#525252" />
              <Text style={styles.chatLockedTitle}>Chat bloccata</Text>
              <Text style={styles.chatLockedSub}>
                Unisciti al gruppo per vedere i messaggi.
              </Text>
            </View>
          ) : (
            <>
              <FlatList
                ref={flatRef}
                testID="chat-list"
                data={messages}
                keyExtractor={(m) => m.message_id}
                contentContainerStyle={{ padding: 16, gap: 10 }}
                onContentSizeChange={() => flatRef.current?.scrollToEnd({ animated: false })}
                renderItem={({ item }) => {
                  const mine = item.user_id === user?.user_id;
                  const openReport = () => {
                    if (mine) return;
                    setReportTarget({
                      type: "message",
                      id: item.message_id,
                      label: `"${item.text.slice(0, 80)}${item.text.length > 80 ? "…" : ""}" — ${item.user_name}`,
                    });
                  };
                  return (
                    <TouchableOpacity
                      testID={`chat-message-${item.message_id}`}
                      activeOpacity={0.9}
                      onLongPress={openReport}
                      delayLongPress={350}
                      style={[
                        styles.bubble,
                        mine ? styles.bubbleMine : styles.bubbleOther,
                      ]}
                    >
                      {!mine && (
                        <TouchableOpacity
                          testID={`chat-author-${item.user_id}`}
                          onPress={() => router.push(`/user/${item.user_id}`)}
                          activeOpacity={0.7}
                        >
                          <Text style={styles.bubbleAuthor} numberOfLines={1}>
                            {item.user_name}
                          </Text>
                        </TouchableOpacity>
                      )}
                      <Text style={[styles.bubbleText, mine && { color: "#FFFFFF" }]}>
                        {item.text}
                      </Text>
                      {!mine && (
                        <Text style={styles.longPressHint}>
                          Tieni premuto per segnalare
                        </Text>
                      )}
                    </TouchableOpacity>
                  );
                }}
                ListEmptyComponent={
                  <Text style={styles.chatEmpty}>Nessun messaggio. Inizia tu! 💬</Text>
                }
              />
              <View style={styles.inputBar}>
                <TextInput
                  testID="chat-input"
                  style={styles.chatInput}
                  value={draft}
                  onChangeText={setDraft}
                  placeholder="Scrivi un messaggio…"
                  placeholderTextColor="#9A9A9A"
                  maxLength={500}
                />
                <TouchableOpacity
                  testID="chat-send"
                  onPress={sendMessage}
                  disabled={sending || !draft.trim()}
                  activeOpacity={0.85}
                  style={[
                    styles.sendBtn,
                    (sending || !draft.trim()) && { opacity: 0.5 },
                  ]}
                >
                  <Ionicons name="send" size={20} color="#0A0A0A" />
                </TouchableOpacity>
              </View>
            </>
          )}
          {chatError && (
            <Text testID="chat-error" style={styles.errorBanner}>
              {chatError}
            </Text>
          )}
        </KeyboardAvoidingView>
      )}

      {tab === "info" && !isOwner && (
        <View style={styles.bottomCta}>
          {isParticipant ? (
            <TouchableOpacity
              testID="leave-button"
              onPress={handleLeave}
              disabled={acting}
              activeOpacity={0.85}
              style={[styles.cta, { backgroundColor: "#FFF" }]}
            >
              <Ionicons name="exit" size={20} color="#0A0A0A" />
              <Text style={styles.ctaText}>Lascia il gruppo</Text>
            </TouchableOpacity>
          ) : (
            <TouchableOpacity
              testID="join-button"
              onPress={handleJoin}
              disabled={acting || isFull}
              activeOpacity={0.85}
              style={[styles.cta, isFull && { opacity: 0.5 }]}
            >
              <Ionicons name="flame" size={20} color="#0A0A0A" />
              <Text style={styles.ctaText}>
                {isFull ? "Gruppo al completo" : "Unisciti alla partita"}
              </Text>
            </TouchableOpacity>
          )}
        </View>
      )}

      {reportTarget && (
        <ReportSheet
          visible
          onClose={() => setReportTarget(null)}
          targetType={reportTarget.type}
          targetId={reportTarget.id}
          targetLabel={reportTarget.label}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FDFBF7" },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#FDFBF7",
    gap: 12,
  },
  topBar: {
    flexDirection: "row",
    alignItems: "center",
    padding: 14,
    gap: 10,
    borderBottomWidth: 2,
    borderBottomColor: "#000",
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
  catPill: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 2,
    borderColor: "#000",
    gap: 6,
    marginLeft: "auto",
    marginRight: "auto",
  },
  catPillEmoji: { fontSize: 14 },
  catPillText: { fontWeight: "900", color: "#0A0A0A", letterSpacing: 0.5, textTransform: "uppercase" },
  safetyBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginHorizontal: 16,
    marginBottom: 4,
    paddingHorizontal: 14,
    paddingVertical: 12,
    backgroundColor: "#FFE600",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 16,
    shadowColor: "#000",
    shadowOffset: { width: 3, height: 3 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 3,
  },
  safetyText: {
    flex: 1,
    fontWeight: "800",
    color: "#0A0A0A",
    fontSize: 13,
    lineHeight: 17,
  },
  segment: {
    flexDirection: "row",
    margin: 16,
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 999,
    padding: 4,
  },
  segBtn: { flex: 1, paddingVertical: 10, alignItems: "center", borderRadius: 999 },
  segActive: { backgroundColor: "#0A0A0A" },
  segText: { fontWeight: "900", color: "#0A0A0A" },
  segTextActive: { color: "#FFE600" },
  title: { fontSize: 30, fontWeight: "900", color: "#0A0A0A", letterSpacing: -0.8, lineHeight: 32 },
  infoCard: {
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 20,
    padding: 16,
    gap: 10,
    shadowColor: "#000",
    shadowOffset: { width: 4, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
  },
  infoRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  infoText: { fontSize: 15, fontWeight: "700", color: "#0A0A0A", flex: 1 },
  desc: { color: "#525252", marginTop: 6, lineHeight: 22 },
  sectionLabel: { fontSize: 12, fontWeight: "900", color: "#0A0A0A", letterSpacing: 1.5, marginTop: 6 },
  participantsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  hintText: {
    marginTop: 10,
    color: "#8A8A8A",
    fontSize: 12,
    fontWeight: "700",
    fontStyle: "italic",
  },
  participant: {
    width: "30%",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 16,
    padding: 8,
  },
  partAvatar: { width: 48, height: 48, borderRadius: 24, borderWidth: 2, borderColor: "#000" },
  partFallback: { backgroundColor: "#FFE600", alignItems: "center", justifyContent: "center" },
  partName: { fontSize: 12, fontWeight: "800", color: "#0A0A0A", textAlign: "center" },
  bottomCta: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 16,
    paddingHorizontal: 20,
  },
  cta: {
    backgroundColor: "#FFE600",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingVertical: 16,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    shadowColor: "#000",
    shadowOffset: { width: 4, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
  },
  ctaText: { fontWeight: "900", color: "#0A0A0A", letterSpacing: 0.5, textTransform: "uppercase" },
  bubble: { maxWidth: "80%", borderRadius: 18, padding: 10, borderWidth: 2, borderColor: "#000" },
  bubbleMine: { backgroundColor: "#FF4747", alignSelf: "flex-end" },
  bubbleOther: { backgroundColor: "#FFF", alignSelf: "flex-start" },
  bubbleAuthor: { fontSize: 11, fontWeight: "900", color: "#525252", marginBottom: 2 },
  bubbleText: { fontSize: 15, color: "#0A0A0A", fontWeight: "600" },
  longPressHint: {
    fontSize: 10,
    color: "#8A8A8A",
    fontStyle: "italic",
    marginTop: 4,
  },
  chatEmpty: { textAlign: "center", color: "#525252", marginTop: 40 },
  inputBar: {
    flexDirection: "row",
    alignItems: "center",
    padding: 12,
    gap: 8,
    borderTopWidth: 2,
    borderTopColor: "#000",
    backgroundColor: "#FFF",
  },
  chatInput: {
    flex: 1,
    backgroundColor: "#FDFBF7",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 12,
    fontSize: 15,
  },
  sendBtn: {
    width: 46,
    height: 46,
    borderRadius: 23,
    borderWidth: 2,
    borderColor: "#000",
    backgroundColor: "#FFE600",
    alignItems: "center",
    justifyContent: "center",
  },
  chatLocked: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    padding: 30,
  },
  chatLockedTitle: { fontSize: 20, fontWeight: "900", color: "#0A0A0A" },
  chatLockedSub: { color: "#525252", textAlign: "center" },
  errorBanner: {
    backgroundColor: "#FF4747",
    color: "#FFF",
    padding: 10,
    fontWeight: "800",
    textAlign: "center",
  },
  backBtn: {
    paddingVertical: 12,
    paddingHorizontal: 24,
    backgroundColor: "#FFE600",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
  },
  backBtnText: { fontWeight: "900", color: "#0A0A0A" },
  emptyTitle: { fontSize: 22, fontWeight: "900", color: "#0A0A0A" },
});
