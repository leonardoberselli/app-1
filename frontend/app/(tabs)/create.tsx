import { useState, useMemo } from "react";
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ScrollView,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/contexts/auth";
import { api } from "@/src/lib/api";
import { CATEGORIES } from "@/src/lib/categories";

const HOURS = [
  "08:00", "09:00", "10:00", "11:00", "12:00", "13:00",
  "14:00", "15:00", "16:00", "17:00", "18:00", "19:00",
  "20:00", "21:00", "22:00", "23:00",
];

function nextDays(n: number) {
  const days: { iso: string; label: string; day: string }[] = [];
  const today = new Date();
  const dayNames = ["DOM", "LUN", "MAR", "MER", "GIO", "VEN", "SAB"];
  for (let i = 0; i < n; i++) {
    const d = new Date(today);
    d.setDate(today.getDate() + i);
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    days.push({
      iso: `${yyyy}-${mm}-${dd}`,
      label: dd + "/" + mm,
      day: dayNames[d.getDay()],
    });
  }
  return days;
}

export default function CreateScreen() {
  const { token } = useAuth();
  const router = useRouter();
  const dayOptions = useMemo(() => nextDays(14), []);

  const [title, setTitle] = useState("");
  const [categoryId, setCategoryId] = useState<string>("");
  const [customCategory, setCustomCategory] = useState("");
  const [location, setLocation] = useState("");
  const [description, setDescription] = useState("");
  const [date, setDate] = useState(dayOptions[0].iso);
  const [time, setTime] = useState("18:00");
  const [minPart, setMinPart] = useState("2");
  const [maxPart, setMaxPart] = useState("8");
  const [minAge, setMinAge] = useState("18");
  const [maxAge, setMaxAge] = useState("40");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isCustom = categoryId === "custom";
  const selectedCat = CATEGORIES.find((c) => c.id === categoryId);

  const reset = () => {
    setTitle("");
    setCategoryId("");
    setCustomCategory("");
    setLocation("");
    setDescription("");
    setMinPart("2");
    setMaxPart("8");
    setMinAge("18");
    setMaxAge("40");
    setDate(dayOptions[0].iso);
    setTime("18:00");
  };

  const submit = async () => {
    setError(null);
    if (!title.trim()) return setError("Inserisci un titolo");
    if (!categoryId) return setError("Seleziona una categoria");
    if (isCustom && !customCategory.trim()) return setError("Inserisci la categoria custom");
    if (!location.trim()) return setError("Inserisci un luogo");
    const minP = parseInt(minPart, 10);
    const maxP = parseInt(maxPart, 10);
    const minA = parseInt(minAge, 10);
    const maxA = parseInt(maxAge, 10);
    if (isNaN(minP) || isNaN(maxP) || minP < 1 || maxP < minP)
      return setError("Numero partecipanti non valido");
    if (isNaN(minA) || isNaN(maxA) || minA < 0 || maxA < minA)
      return setError("Età non valida");
    if (!token) return setError("Devi accedere");

    try {
      setSubmitting(true);
      const cat = isCustom ? "custom" : categoryId;
      const catLabel = isCustom ? customCategory.trim() : (selectedCat?.label || "");
      const group = await api.createGroup(token, {
        title: title.trim(),
        category: cat,
        category_label: catLabel,
        location: location.trim(),
        description: description.trim(),
        date,
        time,
        min_participants: minP,
        max_participants: maxP,
        min_age: minA,
        max_age: maxA,
      } as any);
      reset();
      router.push(`/group/${group.group_id}`);
    } catch (e: any) {
      setError(e?.message || "Errore");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={["top"]} testID="create-screen">
      <View style={styles.headerBlock}>
        <Text style={styles.kicker}>NUOVO GRUPPO</Text>
        <Text style={styles.headerTitle}>Crea il tuo gruppo!</Text>
      </View>

      <KeyboardAwareScrollView
        style={{ flex: 1 }}
        contentContainerStyle={styles.scrollContent}
        bottomOffset={80}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={styles.label}>TITOLO</Text>
        <TextInput
          testID="title-input"
          style={styles.input}
          value={title}
          onChangeText={setTitle}
          placeholder="Partita di basket al parco"
          placeholderTextColor="#9A9A9A"
          maxLength={80}
        />

        <Text style={styles.label}>CATEGORIA</Text>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.catRow}
        >
          {CATEGORIES.map((c) => {
            const active = categoryId === c.id;
            return (
              <TouchableOpacity
                key={c.id}
                testID={`category-${c.id}`}
                activeOpacity={0.85}
                onPress={() => setCategoryId(c.id)}
                style={[
                  styles.catChip,
                  active && { backgroundColor: c.color, borderColor: "#000" },
                ]}
              >
                <Text style={styles.catEmoji}>{c.emoji}</Text>
                <Text style={[styles.catText, active && styles.catTextActive]}>{c.label}</Text>
              </TouchableOpacity>
            );
          })}
          <TouchableOpacity
            testID="category-custom"
            activeOpacity={0.85}
            onPress={() => setCategoryId("custom")}
            style={[
              styles.catChip,
              isCustom && { backgroundColor: "#FF4747", borderColor: "#000" },
            ]}
          >
            <Text style={styles.catEmoji}>✨</Text>
            <Text style={[styles.catText, isCustom && styles.catTextActive]}>Custom</Text>
          </TouchableOpacity>
        </ScrollView>

        {isCustom && (
          <TextInput
            testID="custom-category-input"
            style={[styles.input, { marginTop: 8 }]}
            value={customCategory}
            onChangeText={setCustomCategory}
            placeholder="Es. Scacchi, Boardgame…"
            placeholderTextColor="#9A9A9A"
            maxLength={30}
          />
        )}

        <Text style={styles.label}>LUOGO</Text>
        <TextInput
          testID="location-input"
          style={styles.input}
          value={location}
          onChangeText={setLocation}
          placeholder="Es. Parco Sempione, Milano"
          placeholderTextColor="#9A9A9A"
          maxLength={100}
        />

        <Text style={styles.label}>QUANDO</Text>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.catRow}
        >
          {dayOptions.map((d) => {
            const active = date === d.iso;
            return (
              <TouchableOpacity
                key={d.iso}
                testID={`day-${d.iso}`}
                activeOpacity={0.85}
                onPress={() => setDate(d.iso)}
                style={[styles.dayChip, active && styles.dayChipActive]}
              >
                <Text style={[styles.dayName, active && { color: "#FFE600" }]}>{d.day}</Text>
                <Text style={[styles.dayLabel, active && { color: "#FFF" }]}>{d.label}</Text>
              </TouchableOpacity>
            );
          })}
        </ScrollView>

        <Text style={styles.subLabel}>Orario</Text>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.catRow}
        >
          {HOURS.map((h) => {
            const active = time === h;
            return (
              <TouchableOpacity
                key={h}
                testID={`hour-${h}`}
                activeOpacity={0.85}
                onPress={() => setTime(h)}
                style={[styles.hourChip, active && styles.hourChipActive]}
              >
                <Text style={[styles.hourText, active && { color: "#FFF" }]}>{h}</Text>
              </TouchableOpacity>
            );
          })}
        </ScrollView>

        <Text style={styles.label}>PARTECIPANTI</Text>
        <View style={styles.row}>
          <View style={styles.halfBox}>
            <Text style={styles.smallLabel}>Min</Text>
            <TextInput
              testID="min-participants-input"
              style={styles.numberInput}
              keyboardType="number-pad"
              value={minPart}
              onChangeText={setMinPart}
              maxLength={3}
            />
          </View>
          <View style={styles.halfBox}>
            <Text style={styles.smallLabel}>Max</Text>
            <TextInput
              testID="max-participants-input"
              style={styles.numberInput}
              keyboardType="number-pad"
              value={maxPart}
              onChangeText={setMaxPart}
              maxLength={3}
            />
          </View>
        </View>

        <Text style={styles.label}>FASCIA D&apos;ETÀ</Text>
        <View style={styles.row}>
          <View style={styles.halfBox}>
            <Text style={styles.smallLabel}>Da</Text>
            <TextInput
              testID="min-age-input"
              style={styles.numberInput}
              keyboardType="number-pad"
              value={minAge}
              onChangeText={setMinAge}
              maxLength={3}
            />
          </View>
          <View style={styles.halfBox}>
            <Text style={styles.smallLabel}>A</Text>
            <TextInput
              testID="max-age-input"
              style={styles.numberInput}
              keyboardType="number-pad"
              value={maxAge}
              onChangeText={setMaxAge}
              maxLength={3}
            />
          </View>
        </View>

        <Text style={styles.label}>DESCRIZIONE (opzionale)</Text>
        <TextInput
          testID="description-input"
          style={[styles.input, { minHeight: 90, textAlignVertical: "top" }]}
          value={description}
          onChangeText={setDescription}
          placeholder="Porta scarpe da ginnastica, ci si vede al campo 2…"
          placeholderTextColor="#9A9A9A"
          multiline
          maxLength={400}
        />

        {error && (
          <Text testID="create-error" style={styles.error}>
            {error}
          </Text>
        )}

        <TouchableOpacity
          testID="create-submit"
          activeOpacity={0.85}
          onPress={submit}
          disabled={submitting}
          style={[styles.cta, submitting && { opacity: 0.6 }]}
        >
          {submitting ? (
            <ActivityIndicator color="#0A0A0A" />
          ) : (
            <>
              <Ionicons name="rocket" size={20} color="#0A0A0A" />
              <Text style={styles.ctaText}>Crea Gruppo</Text>
            </>
          )}
        </TouchableOpacity>
      </KeyboardAwareScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FDFBF7" },
  headerBlock: {
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderBottomWidth: 2,
    borderBottomColor: "#000",
  },
  kicker: { fontSize: 11, fontWeight: "800", color: "#FF4747", letterSpacing: 1.5 },
  headerTitle: {
    fontSize: 28,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: -0.5,
    marginTop: 2,
  },
  scrollContent: { padding: 20, paddingBottom: 40, gap: 8 },
  label: {
    fontSize: 12,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: 1.5,
    marginTop: 14,
  },
  subLabel: {
    fontSize: 12,
    fontWeight: "800",
    color: "#525252",
    letterSpacing: 1,
    marginTop: 12,
    marginBottom: 4,
  },
  smallLabel: { fontSize: 11, fontWeight: "800", color: "#525252", letterSpacing: 1 },
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
  catRow: { gap: 8, paddingVertical: 8, paddingRight: 16 },
  catChip: {
    flexShrink: 0,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 999,
    borderWidth: 2,
    borderColor: "#0A0A0A",
    backgroundColor: "#FFF",
    gap: 6,
  },
  catEmoji: { fontSize: 16 },
  catText: { fontWeight: "800", color: "#0A0A0A" },
  catTextActive: { color: "#0A0A0A" },
  dayChip: {
    flexShrink: 0,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 16,
    borderWidth: 2,
    borderColor: "#0A0A0A",
    backgroundColor: "#FFF",
    alignItems: "center",
    minWidth: 64,
  },
  dayChipActive: { backgroundColor: "#0A0A0A" },
  dayName: { fontSize: 11, fontWeight: "900", color: "#525252", letterSpacing: 1 },
  dayLabel: { fontSize: 16, fontWeight: "900", color: "#0A0A0A", marginTop: 2 },
  hourChip: {
    flexShrink: 0,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 999,
    borderWidth: 2,
    borderColor: "#0A0A0A",
    backgroundColor: "#FFF",
  },
  hourChipActive: { backgroundColor: "#FF4747" },
  hourText: { fontWeight: "900", color: "#0A0A0A" },
  row: { flexDirection: "row", gap: 12, marginTop: 8 },
  halfBox: { flex: 1 },
  numberInput: {
    backgroundColor: "#FFFFFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 14,
    fontSize: 22,
    fontWeight: "900",
    color: "#0A0A0A",
    marginTop: 4,
    textAlign: "center",
  },
  error: { color: "#FF4747", fontWeight: "800", marginTop: 12 },
  cta: {
    marginTop: 22,
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
