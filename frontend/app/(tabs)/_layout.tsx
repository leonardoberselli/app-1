import { Tabs, Redirect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/src/contexts/auth";

export default function TabsLayout() {
  const { user, loading } = useAuth();
  const insets = useSafeAreaInsets();

  if (loading) return null;
  if (!user || !user.name || !user.name.trim()) return <Redirect href="/onboarding" />;

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: "#FF4747",
        tabBarInactiveTintColor: "#9A9A9A",
        tabBarLabelStyle: {
          fontWeight: "800",
          letterSpacing: 0.5,
          fontSize: 11,
          textTransform: "uppercase",
        },
        tabBarStyle: {
          backgroundColor: "#FFFFFF",
          borderTopWidth: 2,
          borderTopColor: "#000",
          height: 60 + insets.bottom,
          paddingTop: 6,
          paddingBottom: insets.bottom + 4,
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "Esplora",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="compass" size={size} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="create"
        options={{
          title: "Crea",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="add-circle" size={size + 4} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: "Profilo",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="person-circle" size={size} color={color} />
          ),
        }}
      />
    </Tabs>
  );
}
