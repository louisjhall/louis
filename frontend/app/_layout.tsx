import React, { useEffect } from "react";
import { Stack, useRouter } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { LogBox, Platform, StatusBar } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import * as Notifications from "expo-notifications";
import * as Linking from "expo-linking";

import { useIconFonts } from "@/src/hooks/use-icon-fonts";
import { useBrandFonts } from "@/src/hooks/use-brand-fonts";
import { useOtaUpdates } from "@/src/hooks/use-ota-updates";
import { AuthProvider, useAuth } from "@/src/lib/auth";
import { ToastHost } from "@/src/lib/ux";
import { PreviewProvider } from "@/src/lib/preview";
import { AppConfigProvider } from "@/src/lib/appConfig";
import { PreviewBanner } from "@/src/components/PreviewBanner";
import { BetaDisclaimerGate } from "@/src/components/BetaDisclaimerGate";
import { TrainingSetupGate } from "@/src/components/TrainingSetupGate";
import { RootErrorBoundary } from "@/src/components/RootErrorBoundary";
import { CrewFitIntroAnimation } from "@/src/components/CrewFitIntroAnimation";
import { initSentry } from "@/src/lib/sentry";

// One-shot at module load; safe no-op when EXPO_PUBLIC_SENTRY_DSN is unset.
initSentry();

LogBox.ignoreAllLogs(true);
SplashScreen.preventAutoHideAsync();

// Push: foreground handler (module scope, native only)
if (Platform.OS !== "web") {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowAlert: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
  });
}
// Android channel (module scope)
if (Platform.OS === "android") {
  Notifications.setNotificationChannelAsync("default", {
    name: "Default",
    importance: Notifications.AndroidImportance.MAX,
    sound: "default",
  });
}

export default function RootLayout() {
  const [loaded, error] = useIconFonts();
  const [brandLoaded] = useBrandFonts();
  const router = useRouter();

  // Iter 95a — silent OTA check (no-ops in web / Expo Go / dev).
  useOtaUpdates();

  useEffect(() => {
    if (loaded || error) SplashScreen.hideAsync();
  }, [loaded, error]);

  useEffect(() => {
    if (Platform.OS === "web") return;
    const tapSub = Notifications.addNotificationResponseReceivedListener((response) => {
      const data = (response.notification.request.content.data || {}) as any;
      const url = data.deeplink || data.action_url;
      if (!url) return;
      if (typeof url === "string" && url.startsWith("http")) Linking.openURL(url);
      else if (typeof url === "string") router.push(url as any);
    });
    Notifications.getLastNotificationResponseAsync().then((response) => {
      if (!response) return;
      const data = (response.notification.request.content.data || {}) as any;
      const url = data.deeplink || data.action_url;
      if (typeof url === "string" && url.length > 0) {
        if (url.startsWith("http")) Linking.openURL(url);
        else router.push(url as any);
      }
    });
    return () => { tapSub.remove(); };
  }, [router]);

  if (!loaded && !error) return null;

  return (
    <RootErrorBoundary>
      <GestureHandlerRootView style={{ flex: 1, backgroundColor: "#000000" }}>
        <SafeAreaProvider>
          <AuthProvider>
            <AppConfigProvider>
              <PreviewWiring>
                <CrewFitIntroAnimation>
                  <StatusBar barStyle="light-content" backgroundColor="#000000" />
                  <PreviewBanner />
                  <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: "#000000" }, animation: "fade" }} />
                  <BetaDisclaimerGate />
                  <TrainingSetupGate />
                  <ToastHost />
                </CrewFitIntroAnimation>
              </PreviewWiring>
            </AppConfigProvider>
          </AuthProvider>
        </SafeAreaProvider>
      </GestureHandlerRootView>
    </RootErrorBoundary>
  );
}

// Bridges PreviewProvider with AuthProvider: refresh the auth context
// whenever the coach swaps token (into or out of preview) so the app
// re-routes correctly.
function PreviewWiring({ children }: { children: React.ReactNode }) {
  const { refresh } = useAuth();
  return <PreviewProvider onSwap={refresh}>{children}</PreviewProvider>;
}
