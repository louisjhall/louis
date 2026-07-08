import { Redirect } from "expo-router";
import { ActivityIndicator, View } from "react-native";
import { useAuth } from "@/src/lib/auth";
import { theme } from "@/src/lib/theme";

export default function Index() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: theme.color.surface, alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }
  if (!user) return <Redirect href="/(auth)/login" />;
  if (!user.onboarded && user.role === "client") return <Redirect href="/assessment" />;
  if (user.role === "coach") return <Redirect href="/(coach)/clients" />;
  return <Redirect href="/(client)/home" />;
}
