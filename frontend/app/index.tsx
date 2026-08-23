import { useEffect } from "react";
import { View, Text, ActivityIndicator, StyleSheet, TouchableOpacity } from "react-native";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/contexts/auth";

/**
 * Entry route. No login screen — the auth context auto-generates a device
 * UUID and identifies the user against the backend. On first launch (empty
 * name) we redirect to a light onboarding that asks only the name. Once the
 * name exists we go straight to the tabs.
 */
export default function Index() {
  const { user, loading, authError, refreshMe } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!user) return;
    // Send back to onboarding when either identity (name) or age gate is
    // missing; the app is 14+ only, so we require the age up front.
    if (!user.name || !user.name.trim() || user.age == null) {
      router.replace("/onboarding");
    } else {
      router.replace("/(tabs)");
    }
  }, [loading, user, router]);

  if (authError) {
    return (
      <View style={styles.container} testID="auth-error-screen">
        <Text style={styles.emoji}>⚠️</Text>
        <Text style={styles.title}>Problema di connessione</Text>
        <Text style={styles.body}>{authError}</Text>
        <TouchableOpacity
          style={styles.retry}
          activeOpacity={0.85}
          onPress={() => refreshMe()}
          testID="retry-button"
        >
          <Text style={styles.retryText}>Riprova</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.container} testID="splash-screen">
      <ActivityIndicator size="large" color="#FF4747" />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#FDFBF7",
    padding: 32,
    gap: 12,
  },
  emoji: { fontSize: 60 },
  title: {
    fontSize: 22,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: -0.5,
    textAlign: "center",
  },
  body: {
    color: "#525252",
    fontSize: 15,
    lineHeight: 22,
    textAlign: "center",
    fontWeight: "600",
  },
  retry: {
    marginTop: 16,
    backgroundColor: "#FFE600",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingHorizontal: 22,
    paddingVertical: 12,
  },
  retryText: {
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: 1,
    textTransform: "uppercase",
  },
});
