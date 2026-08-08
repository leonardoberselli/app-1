import { useState, useEffect, useRef } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/contexts/auth";

export default function VerifyEmail() {
  const {
    fbUser,
    emailVerified,
    resendVerificationEmail,
    reloadVerification,
    signOut,
  } = useAuth();
  const router = useRouter();

  const [resending, setResending] = useState(false);
  const [checking, setChecking] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const pollRef = useRef<any>(null);

  // If already verified (edge case), go home.
  useEffect(() => {
    if (emailVerified) {
      router.replace("/");
    }
  }, [emailVerified, router]);

  // If somehow user got here signed out, bounce to login.
  useEffect(() => {
    if (!fbUser) router.replace("/login");
  }, [fbUser, router]);

  // Auto-poll every 5s to detect verification without user having to tap.
  useEffect(() => {
    pollRef.current = setInterval(async () => {
      const ok = await reloadVerification();
      if (ok) {
        clearInterval(pollRef.current);
        router.replace("/");
      }
    }, 5000);
    return () => clearInterval(pollRef.current);
  }, [reloadVerification, router]);

  // Cooldown timer for resend button.
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setInterval(() => setCooldown((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, [cooldown]);

  const onResend = async () => {
    setError(null);
    setStatus(null);
    try {
      setResending(true);
      await resendVerificationEmail();
      setStatus("Email di verifica inviata di nuovo.");
      setCooldown(30);
    } catch (e: any) {
      setError(e?.message || "Errore nell'invio dell'email");
    } finally {
      setResending(false);
    }
  };

  const onCheck = async () => {
    setError(null);
    setStatus(null);
    try {
      setChecking(true);
      const ok = await reloadVerification();
      if (ok) {
        router.replace("/");
      } else {
        setStatus("Non ancora verificata. Clicca sul link nell'email e riprova.");
      }
    } finally {
      setChecking(false);
    }
  };

  const onSignOut = async () => {
    await signOut();
    router.replace("/login");
  };

  return (
    <SafeAreaView style={styles.container} testID="verify-email-screen" edges={["top", "bottom"]}>
      <View style={styles.center}>
        <View style={styles.emojiWrap}>
          <Text style={{ fontSize: 64 }}>📬</Text>
        </View>
        <Text style={styles.title}>Verifica la tua email</Text>
        <Text style={styles.sub}>
          Ti abbiamo inviato un link a{"\n"}
          <Text style={styles.email}>{fbUser?.email || ""}</Text>
          {"\n\n"}Apri l&apos;email e clicca sul link. Il rilevamento avviene
          automaticamente entro pochi secondi.
        </Text>

        {status && (
          <Text testID="verify-status" style={styles.info}>
            {status}
          </Text>
        )}
        {error && (
          <Text testID="verify-error" style={styles.error}>
            {error}
          </Text>
        )}

        <TouchableOpacity
          testID="verify-check"
          onPress={onCheck}
          disabled={checking}
          style={[styles.primaryBtn, checking && { opacity: 0.6 }]}
          activeOpacity={0.85}
        >
          {checking ? (
            <ActivityIndicator color="#0A0A0A" />
          ) : (
            <>
              <Ionicons name="refresh" size={18} color="#0A0A0A" />
              <Text style={styles.primaryText}>Ho verificato</Text>
            </>
          )}
        </TouchableOpacity>

        <TouchableOpacity
          testID="verify-resend"
          onPress={onResend}
          disabled={resending || cooldown > 0}
          style={[styles.secondaryBtn, (resending || cooldown > 0) && { opacity: 0.6 }]}
          activeOpacity={0.85}
        >
          {resending ? (
            <ActivityIndicator color="#0A0A0A" />
          ) : (
            <>
              <Ionicons name="mail" size={18} color="#0A0A0A" />
              <Text style={styles.secondaryText}>
                {cooldown > 0 ? `Rinvia tra ${cooldown}s` : "Rinvia email di verifica"}
              </Text>
            </>
          )}
        </TouchableOpacity>

        <TouchableOpacity
          testID="verify-signout"
          onPress={onSignOut}
          style={{ marginTop: 20 }}
        >
          <Text style={styles.link}>Usa un altro account</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FDFBF7" },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 32,
    gap: 10,
  },
  emojiWrap: {
    width: 120,
    height: 120,
    borderRadius: 60,
    backgroundColor: "#FFE600",
    borderWidth: 3,
    borderColor: "#000",
    alignItems: "center",
    justifyContent: "center",
  },
  title: {
    fontSize: 26,
    fontWeight: "900",
    color: "#0A0A0A",
    marginTop: 16,
    letterSpacing: -0.5,
    textAlign: "center",
  },
  sub: {
    color: "#525252",
    fontSize: 15,
    lineHeight: 22,
    textAlign: "center",
    marginBottom: 4,
  },
  email: { fontWeight: "900", color: "#0A0A0A" },
  info: {
    color: "#0A0A0A",
    fontWeight: "700",
    fontSize: 13,
    textAlign: "center",
    backgroundColor: "#DFF7CE",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  error: {
    color: "#FFF",
    fontWeight: "800",
    backgroundColor: "#FF4747",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 8,
    textAlign: "center",
  },
  primaryBtn: {
    marginTop: 20,
    backgroundColor: "#FFE600",
    borderWidth: 2,
    borderColor: "#000",
    borderRadius: 999,
    paddingVertical: 14,
    paddingHorizontal: 26,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    minWidth: 220,
    shadowColor: "#000",
    shadowOffset: { width: 4, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
  },
  primaryText: {
    fontWeight: "900",
    color: "#0A0A0A",
    letterSpacing: 0.5,
    fontSize: 14,
    textTransform: "uppercase",
  },
  secondaryBtn: {
    marginTop: 10,
    backgroundColor: "#FFFFFF",
    borderWidth: 2,
    borderColor: "#0A0A0A",
    borderRadius: 999,
    paddingVertical: 12,
    paddingHorizontal: 20,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    minWidth: 220,
  },
  secondaryText: { fontWeight: "800", color: "#0A0A0A", fontSize: 14 },
  link: { color: "#FF4747", fontWeight: "900" },
});
