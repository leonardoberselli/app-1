import { useEffect } from "react";
import { View, ActivityIndicator, StyleSheet } from "react-native";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/contexts/auth";

export default function Index() {
  const { fbUser, user, loading, needsEmailVerification } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    // Not signed into Firebase at all -> go to Login.
    if (!fbUser) {
      router.replace("/login");
      return;
    }
    // Signed in but email/password provider not verified yet.
    if (needsEmailVerification) {
      router.replace("/verify-email");
      return;
    }
    // Signed in & verified but backend profile not loaded yet -> wait.
    if (!user) return;
    // Onboarding: complete profile (gender/age/picture).
    if (!user.profile_complete) {
      router.replace("/profile-edit?mode=onboarding");
      return;
    }
    router.replace("/(tabs)");
  }, [loading, fbUser, user, needsEmailVerification, router]);

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
  },
});
