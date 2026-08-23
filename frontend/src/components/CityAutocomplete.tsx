import { useCallback, useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  Keyboard,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api, CitySuggestion } from "@/src/lib/api";

type Props = {
  /** Currently displayed city name (controlled). */
  value: string;
  /** Fired for every keystroke. Parent should just update its `value`. */
  onChangeText: (text: string) => void;
  /** Fired when the user picks a suggestion from the dropdown. */
  onSelect: (city: CitySuggestion) => void;
  placeholder?: string;
  testID?: string;
  /** When true, suggestions are shown below the input; caller decides layout. */
  autoFocus?: boolean;
};

const DEBOUNCE_MS = 350;

/** Reusable city-autocomplete with debounced Nominatim (via /api/cities/suggest).
 *  Shows the province next to each result: "Correggio (Reggio nell'Emilia)". */
export function CityAutocomplete({
  value,
  onChangeText,
  onSelect,
  placeholder,
  testID,
  autoFocus,
}: Props) {
  const [items, setItems] = useState<CitySuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const seqRef = useRef(0);

  // Whether the current value corresponds to a picked suggestion. When true,
  // we do NOT trigger another fetch (avoids reopening the dropdown after a
  // pick).
  const pickedRef = useRef(false);

  const fetchNow = useCallback(async (q: string) => {
    const mySeq = ++seqRef.current;
    setLoading(true);
    try {
      const res = await api.suggestCities(q);
      if (mySeq !== seqRef.current) return; // stale
      setItems(res);
      setOpen(true);
    } catch {
      if (mySeq !== seqRef.current) return;
      setItems([]);
      setOpen(true);
    } finally {
      if (mySeq === seqRef.current) setLoading(false);
    }
  }, []);

  const handleChange = (t: string) => {
    onChangeText(t);
    pickedRef.current = false;
    if (timer.current) clearTimeout(timer.current);
    const q = t.trim();
    if (q.length < 2) {
      setItems([]);
      setOpen(false);
      setLoading(false);
      return;
    }
    setLoading(true);
    timer.current = setTimeout(() => fetchNow(q), DEBOUNCE_MS);
  };

  const pick = (c: CitySuggestion) => {
    pickedRef.current = true;
    if (timer.current) clearTimeout(timer.current);
    seqRef.current++;
    setOpen(false);
    setItems([]);
    setLoading(false);
    onSelect(c);
    Keyboard.dismiss();
  };

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  return (
    <View>
      <View style={styles.inputWrap}>
        <TextInput
          testID={testID}
          style={styles.input}
          value={value}
          onChangeText={handleChange}
          placeholder={placeholder || "Es. Milano"}
          placeholderTextColor="#9A9A9A"
          autoCapitalize="words"
          autoCorrect={false}
          autoFocus={autoFocus}
          maxLength={60}
          onFocus={() => {
            if (!pickedRef.current && items.length) setOpen(true);
          }}
        />
        {loading && (
          <ActivityIndicator style={styles.spinner} color="#0A0A0A" />
        )}
      </View>

      {open && items.length > 0 && (
        <View style={styles.dropdown} testID={testID ? `${testID}-dropdown` : undefined}>
          {items.map((it, idx) => (
            <TouchableOpacity
              key={`${it.name}-${it.province}-${idx}`}
              testID={testID ? `${testID}-item-${idx}` : undefined}
              activeOpacity={0.7}
              onPress={() => pick(it)}
              style={[styles.item, idx === items.length - 1 && { borderBottomWidth: 0 }]}
            >
              <Ionicons name="location" size={16} color="#FF4747" />
              <View style={{ flex: 1 }}>
                <Text style={styles.itemName}>{it.name}</Text>
                {(it.province || it.region) ? (
                  <Text style={styles.itemMeta} numberOfLines={1}>
                    {[it.province, it.region].filter(Boolean).join(" · ")}
                  </Text>
                ) : null}
              </View>
            </TouchableOpacity>
          ))}
        </View>
      )}

      {open && !loading && items.length === 0 && value.trim().length >= 2 && (
        <View style={styles.dropdown}>
          <Text style={styles.emptyText} testID={testID ? `${testID}-empty` : undefined}>
            Nessuna città trovata
          </Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  inputWrap: { position: "relative" },
  input: {
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 14,
    fontSize: 15,
    fontWeight: "600",
    color: "#0A0A0A",
    paddingRight: 40,
  },
  spinner: {
    position: "absolute",
    right: 14,
    top: 0,
    bottom: 0,
  },
  dropdown: {
    marginTop: 6,
    backgroundColor: "#FFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 16,
    overflow: "hidden",
    shadowColor: "#000",
    shadowOffset: { width: 3, height: 3 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 3,
  },
  item: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: "#EEE",
  },
  itemName: { fontWeight: "800", color: "#0A0A0A", fontSize: 15 },
  itemMeta: { fontWeight: "600", color: "#525252", fontSize: 12, marginTop: 2 },
  emptyText: {
    paddingHorizontal: 14,
    paddingVertical: 14,
    color: "#525252",
    fontWeight: "600",
    fontSize: 13,
  },
});
