import { useState } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ImageBackground,
  ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/contexts/auth";

export default function LoginScreen() {
  const { signIn, user, loading } = useAuth();
  const [signing, setSigning] = useState(false);
  const router = useRouter();

  if (user && !loading) {
    router.replace("/");
  }

  const handleSignIn = async () => {
    try {
      setSigning(true);
      await signIn();
    } catch (e) {
      console.warn("signIn error", e);
    } finally {
      setSigning(false);
    }
  };

  return (
    <View style={styles.container} testID="login-screen">
      <ImageBackground
        source={{
          uri: "https://images.unsplash.com/photo-1511988617509-a57c8a288659?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NTY2ODh8MHwxfHNlYXJjaHwzfHx5b3VuZyUyMHBlb3BsZSUyMGhhdmluZyUyMGZ1bnxlbnwwfHx8fDE3ODA5NDE3MzZ8MA&ixlib=rb-4.1.0&q=85",
        }}
        style={styles.hero}
        resizeMode="cover"
      >
        <View style={styles.heroOverlay} />
        <View style={styles.heroContent}>
          <View style={styles.badge}>
            <Text style={styles.badgeText}>GROUPUP · ITA</Text>
          </View>
        </View>
      </ImageBackground>

      <View style={styles.sheet}>
        <Text style={styles.headline}>Pronti{"\n"}a giocare?</Text>
        <Text style={styles.sub}>
          Crea o unisciti a gruppi per sport, serate e ogni occasione di trovarsi.
        </Text>

        <TouchableOpacity
          testID="google-login-button"
          activeOpacity={0.85}
          style={[styles.googleBtn, signing && { opacity: 0.6 }]}
          onPress={handleSignIn}
          disabled={signing}
        >
          {signing ? (
            <ActivityIndicator color="#0A0A0A" />
          ) : (
            <>
              <Ionicons name="logo-google" size={22} color="#0A0A0A" />
              <Text style={styles.googleBtnText}>Accedi con Google</Text>
            </>
          )}
        </TouchableOpacity>

        <Text style={styles.footer}>
          Continuando accetti i Termini e l&apos;informativa privacy.
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0A0A0A" },
  hero: { flex: 1.2, justifyContent: "flex-start" },
  heroOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0,0,0,0.35)",
  },
  heroContent: { padding: 24, paddingTop: 70 },
  badge: {
    alignSelf: "flex-start",
    backgroundColor: "#FFE600",
    borderWidth: 2,
    borderColor: "#000",
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 999,
  },
  badgeText: {
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: 1.5,
    fontSize: 12,
  },
  sheet: {
    backgroundColor: "#FDFBF7",
    borderTopLeftRadius: 32,
    borderTopRightRadius: 32,
    padding: 28,
    paddingBottom: 40,
    borderTopWidth: 2,
    borderColor: "#000",
    gap: 18,
  },
  headline: {
    fontSize: 44,
    fontWeight: "900",
    color: "#0A0A0A",
    lineHeight: 46,
    letterSpacing: -1.5,
  },
  sub: { color: "#525252", fontSize: 16, lineHeight: 22 },
  googleBtn: {
    backgroundColor: "#FFE600",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingVertical: 18,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    shadowColor: "#000",
    shadowOffset: { width: 4, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 6,
    marginTop: 8,
  },
  googleBtnText: {
    fontSize: 16,
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
  footer: { color: "#8A8A8A", fontSize: 12, textAlign: "center" },
});
