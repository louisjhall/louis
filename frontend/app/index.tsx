import { Redirect } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useAuth } from "@/src/lib/auth";
import { theme } from "@/src/lib/theme";

export default function Index() {
  const { user, loading } = useAuth();
  const [welcomed, setWelcomed] = useState<boolean | null>(null);

  useEffect(() => {
    AsyncStorage.getItem("atlas_welcomed")
      .then((v) => setWelcomed(v === "1"))
      .catch(() => setWelcomed(true));
  }, []);

  if (loading || welcomed === null) {
    return (
      <View style={{ flex: 1, backgroundColor: theme.color.surface, alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }
  // First launch: introduce Atlas before the login screen
  if (!welcomed && !user) return <Redirect href="/welcome" />;
  if (!user) return <Redirect href="/(auth)/login" />;
  if (!user.onboarded && user.role === "client") return <Redirect href="/assessment" />;
  if (user.role === "coach") return <Redirect href="/(coach)/clients" />;
  return <Redirect href="/(client)/home" />;
}
