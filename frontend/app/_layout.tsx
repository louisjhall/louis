import React, { useEffect, useState } from "react";
import { Stack, useRouter } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { LogBox, Platform, StatusBar, Text as RNText, TextInput as RNTextInput } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import * as Notifications from "expo-notifications";
import * as Linking from "expo-linking";

import { useIconFonts } from "@/src/hooks/use-icon-fonts";
import { useBrandFonts } from "@/src/hooks/use-brand-fonts";
import { bootstrapThemeMode } from "@/src/hooks/use-theme-mode";
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
import { theme } from "@/src/lib/theme";

// One-shot at module load; safe no-op when EXPO_PUBLIC_SENTRY_DSN is unset.
initSentry();

LogBox.ignoreAllLogs(true);
SplashScreen.preventAutoHideAsync();

/* --------------------------------------------------------------------------
 * Iter 151 — Global base font size.
 *
 * RN's default is 14. We raise the baseline for `<Text>` and `<TextInput>`
 * nodes that don't specify their own fontSize (or that pass an object style
 * without a fontSize key merged in via array). This is a best-effort
 * baseline — screens with explicit fontSize in StyleSheet.create() are
 * untouched by design.
 * ------------------------------------------------------------------------ */
const _BASE_TEXT_STYLE = { fontSize: 16 } as const;
(RNText as any).defaultProps = {
  ...((RNText as any).defaultProps || {}),
  allowFontScaling: true,
  style: [_BASE_TEXT_STYLE, ((RNText as any).defaultProps || {}).style].filter(Boolean),
};
(RNTextInput as any).defaultProps = {
  ...((RNTextInput as any).defaultProps || {}),
  allowFontScaling: true,
  style: [_BASE_TEXT_STYLE, ((RNTextInput as any).defaultProps || {}).style].filter(Boolean),
};

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
  // Iter 165c · Brand fonts now surface an `error` too so we can gate the
  // splash-screen dismissal on either "done" state instead of racing the
  // async load.
  const [brandLoaded, brandError] = useBrandFonts();
  const router = useRouter();

  // Iter169 · Read persisted theme mode from AsyncStorage BEFORE the first
  // paint so StyleSheet.create() calls in child components pick up the
  // correct palette. Runs once at boot.
  const [themeBooted, setThemeBooted] = useState(false);
  useEffect(() => {
    bootstrapThemeMode().finally(() => setThemeBooted(true));
  }, []);

  // Iter 95a — silent OTA check (no-ops in web / Expo Go / dev).
  useOtaUpdates();

  // Iter 165c · Splash gate: only hide the native splash once BOTH font
  // loaders have finished. Waiting on icons alone caused a flash of the
  // fallback system font before Creo/Source Sans 3 swapped in — most
  // visible on the CrewFit intro headline and the tab bar labels.
  const fontsReady    = loaded && brandLoaded;
  const fontsErrored  = !!(error || brandError);
  // Iter169 · Also require the theme palette to be resolved before we
  // dismiss the splash screen — first paint must use the correct colours.
  const canRender     = (fontsReady || fontsErrored) && themeBooted;

  useEffect(() => {
    if (canRender) SplashScreen.hideAsync();
  }, [canRender]);

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

  // Iter 165c · Block first render until BOTH font families are known-good
  // (or both known-errored). This mirrors the splash-gate above so the app
  // never mounts before Creo / Source Sans 3 are ready.
  if (!canRender) return null;

  // brandLoaded is intentionally referenced above; keep the marker so
  // future maintainers see it is required, not decorative.
  void brandLoaded;

  return (
    <RootErrorBoundary>
      <GestureHandlerRootView style={{ flex: 1, backgroundColor: theme.color.bg }}>
        <SafeAreaProvider>
          <AuthProvider>
            <AppConfigProvider>
              <PreviewWiring>
                <CrewFitIntroAnimation>
                  <StatusBar barStyle="light-content" backgroundColor={theme.color.bg} />
                  <PreviewBanner />
                  <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: theme.color.bg }, animation: "fade" }} />
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
