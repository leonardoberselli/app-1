import { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  Image,
  ActivityIndicator,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import * as ImagePicker from "expo-image-picker";
import { useRouter, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/contexts/auth";
import { api } from "@/src/lib/api";

type Gender = "male" | "female" | "other";

const GENDERS: { id: Gender; label: string; emoji: string }[] = [
  { id: "male", label: "Uomo", emoji: "👨" },
  { id: "female", label: "Donna", emoji: "👩" },
  { id: "other", label: "Altro", emoji: "🌈" },
];

export default function ProfileEdit() {
  const { user, fbUser, setUser } = useAuth();
  const router = useRouter();
  const params = useLocalSearchParams<{ mode?: string }>();
  const isOnboarding = params.mode === "onboarding";

  const [name, setName] = useState(user?.name || "");
  const [picture, setPicture] = useState<string | null>(user?.picture || null);
  const [gender, setGender] = useState<Gender | null>((user?.gender as Gender) || null);
  const [age, setAge] = useState<string>(user?.age ? String(user.age) : "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pickImage = async () => {
    try {
      // Permissions
      const existing = await ImagePicker.getMediaLibraryPermissionsAsync();
      let status = existing.status;
      if (status !== "granted") {
        if (existing.canAskAgain) {
          const req = await ImagePicker.requestMediaLibraryPermissionsAsync();
          status = req.status;
        }
      }
      if (status !== "granted") {
        Alert.alert(
          "Permesso richiesto",
          "Concedi l'accesso alla galleria dalle impostazioni per scegliere una foto.",
        );
        return;
      }
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        allowsEditing: true,
        aspect: [1, 1],
        quality: 0.6,
        base64: true,
      });
      if (result.canceled) return;
      const asset = result.assets[0];
      // Prefer base64 for mobile storage compat
      if (asset.base64) {
        const mime = asset.mimeType || "image/jpeg";
        setPicture(`data:${mime};base64,${asset.base64}`);
      } else {
        setPicture(asset.uri);
      }
    } catch (e: any) {
      console.warn("pickImage", e);
      setError("Impossibile caricare l'immagine");
    }
  };

  const submit = async () => {
    setError(null);
    if (!name.trim()) return setError("Inserisci il tuo nome");
    if (!gender) return setError("Seleziona il sesso");
    const a = parseInt(age, 10);
    if (isNaN(a) || a < 13 || a > 120) return setError("Inserisci un'età valida (13-120)");
    if (!picture) return setError("Aggiungi una foto profilo");
    if (!fbUser) return setError("Non sei autenticato");
    try {
      setSaving(true);
      const updated = await api.updateProfile({
        name: name.trim(),
        picture,
        gender,
        age: a,
      });
      setUser(updated);
      if (isOnboarding) {
        router.replace("/(tabs)");
      } else {
        router.back();
      }
    } catch (e: any) {
      setError(e?.message || "Errore salvataggio");
    } finally {
      setSaving(false);
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={["top"]} testID="profile-edit-screen">
      <View style={styles.header}>
        {!isOnboarding && (
          <TouchableOpacity
            testID="back-button"
            onPress={() => router.back()}
            style={styles.backBtn}
          >
            <Ionicons name="chevron-back" size={22} color="#0A0A0A" />
          </TouchableOpacity>
        )}
        <View style={{ flex: 1 }}>
          <Text style={styles.kicker}>{isOnboarding ? "BENVENUTO/A" : "IL TUO PROFILO"}</Text>
          <Text style={styles.title}>
            {isOnboarding ? "Completa il profilo" : "Modifica profilo"}
          </Text>
        </View>
      </View>

      <KeyboardAwareScrollView
        style={{ flex: 1 }}
        contentContainerStyle={styles.body}
        bottomOffset={100}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.avatarWrap}>
          <TouchableOpacity
            testID="pick-photo-button"
            activeOpacity={0.85}
            onPress={pickImage}
            style={styles.avatarBtn}
          >
            {picture ? (
              <Image source={{ uri: picture }} style={styles.avatarImg} />
            ) : (
              <View style={styles.avatarPlaceholder}>
                <Ionicons name="camera" size={36} color="#0A0A0A" />
              </View>
            )}
            <View style={styles.avatarBadge}>
              <Ionicons name="add" size={18} color="#0A0A0A" />
            </View>
          </TouchableOpacity>
          <Text style={styles.avatarLabel}>Tocca per cambiare foto</Text>
        </View>

        <Text style={styles.label}>NOME</Text>
        <TextInput
          testID="name-input"
          style={styles.input}
          value={name}
          onChangeText={setName}
          placeholder="Il tuo nome"
          placeholderTextColor="#9A9A9A"
          maxLength={40}
        />

        <Text style={styles.label}>SESSO</Text>
        <View style={styles.genderRow}>
          {GENDERS.map((g) => {
            const active = gender === g.id;
            return (
              <TouchableOpacity
                key={g.id}
                testID={`gender-${g.id}`}
                activeOpacity={0.85}
                onPress={() => setGender(g.id)}
                style={[styles.genderChip, active && styles.genderActive]}
              >
                <Text style={styles.genderEmoji}>{g.emoji}</Text>
                <Text style={[styles.genderText, active && { color: "#FFE600" }]}>
                  {g.label}
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>

        <Text style={styles.label}>ETÀ</Text>
        <TextInput
          testID="age-input"
          style={styles.input}
          value={age}
          onChangeText={(t) => setAge(t.replace(/[^0-9]/g, ""))}
          placeholder="Es. 24"
          placeholderTextColor="#9A9A9A"
          keyboardType="number-pad"
          maxLength={3}
        />

        {error && (
          <Text testID="profile-error" style={styles.error}>
            {error}
          </Text>
        )}

        <TouchableOpacity
          testID="save-profile"
          activeOpacity={0.85}
          onPress={submit}
          disabled={saving}
          style={[styles.cta, saving && { opacity: 0.6 }]}
        >
          {saving ? (
            <ActivityIndicator color="#0A0A0A" />
          ) : (
            <>
              <Ionicons name="checkmark" size={20} color="#0A0A0A" />
              <Text style={styles.ctaText}>
                {isOnboarding ? "Inizia" : "Salva"}
              </Text>
            </>
          )}
        </TouchableOpacity>
      </KeyboardAwareScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FDFBF7" },
  header: {
    paddingHorizontal: 20,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    borderBottomWidth: 2,
    borderBottomColor: "#000",
  },
  backBtn: {
    width: 38,
    height: 38,
    borderRadius: 999,
    borderWidth: 2,
    borderColor: "#0A0A0A",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#FFF",
  },
  kicker: { fontSize: 11, fontWeight: "800", color: "#FF4747", letterSpacing: 1.5 },
  title: { fontSize: 26, fontWeight: "900", color: "#0A0A0A", letterSpacing: -0.5 },
  body: { padding: 20, paddingBottom: 60, gap: 6 },
  avatarWrap: { alignItems: "center", marginBottom: 20 },
  avatarBtn: { position: "relative" },
  avatarImg: {
    width: 128,
    height: 128,
    borderRadius: 64,
    borderWidth: 3,
    borderColor: "#000",
  },
  avatarPlaceholder: {
    width: 128,
    height: 128,
    borderRadius: 64,
    borderWidth: 3,
    borderColor: "#000",
    backgroundColor: "#FFE600",
    alignItems: "center",
    justifyContent: "center",
  },
  avatarBadge: {
    position: "absolute",
    bottom: 4,
    right: 4,
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: "#FF4747",
    borderWidth: 2,
    borderColor: "#000",
    alignItems: "center",
    justifyContent: "center",
  },
  avatarLabel: { marginTop: 10, fontWeight: "700", color: "#525252" },
  label: { fontSize: 12, fontWeight: "900", color: "#0A0A0A", letterSpacing: 1.5, marginTop: 14 },
  input: {
    backgroundColor: "#FFFFFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 14,
    fontSize: 16,
    color: "#0A0A0A",
    fontWeight: "600",
    marginTop: 8,
  },
  genderRow: { flexDirection: "row", gap: 8, marginTop: 8 },
  genderChip: {
    flex: 1,
    paddingVertical: 12,
    paddingHorizontal: 8,
    borderRadius: 16,
    borderWidth: 2,
    borderColor: "#0A0A0A",
    backgroundColor: "#FFF",
    alignItems: "center",
    gap: 4,
  },
  genderActive: { backgroundColor: "#0A0A0A" },
  genderEmoji: { fontSize: 24 },
  genderText: { fontWeight: "900", color: "#0A0A0A" },
  error: { color: "#FF4747", fontWeight: "800", marginTop: 12 },
  cta: {
    marginTop: 24,
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
    fontSize: 16,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: 1,
    textTransform: "uppercase",
  },
});
