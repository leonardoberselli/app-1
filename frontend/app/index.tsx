import { useEffect } from "react";
import { View, ActivityIndicator, StyleSheet } from "react-native";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/contexts/auth";

export default function Index() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
    } else if (!user.profile_complete) {
      router.replace("/profile-edit?mode=onboarding");
    } else {
      router.replace("/(tabs)");
    }
  }, [loading, user, router]);

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
