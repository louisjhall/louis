/**
 * sentry.ts — Optional Sentry wiring.
 *
 * If EXPO_PUBLIC_SENTRY_DSN is set in the env file, we init Sentry on
 * startup. If it's blank, we no-op silently so dev builds and preview
 * sessions never phone home.
 *
 * We deliberately DO NOT collect user email, IP addresses, or breadcrumbs
 * that could contain client PII. Only exception messages + stack traces.
 */
import { Platform } from "react-native";
import Constants from "expo-constants";

let initialised = false;

export function initSentry() {
  if (initialised) return;
  const dsn = process.env.EXPO_PUBLIC_SENTRY_DSN
            || (Constants.expoConfig?.extra as any)?.sentryDsn;
  if (!dsn) return; // no-op when not configured
  try {
     
    const Sentry = require("@sentry/react-native");
    Sentry.init({
      dsn,
      enableInExpoDevelopment: false,
      debug: false,
      tracesSampleRate: 0,   // performance monitoring off for beta
      sendDefaultPii: false, // no IPs, no cookies
      beforeSend(event: any) {
        // Strip any user identifiers just in case.
        if (event.user) {
          event.user = { id: event.user.id }; // keep only opaque id
        }
        return event;
      },
      environment: process.env.EXPO_PUBLIC_SENTRY_ENV || "beta",
    });
    initialised = true;
    if (__DEV__) console.log("Sentry initialised on", Platform.OS);
  } catch (e) {
    if (__DEV__) console.warn("Sentry init failed:", e);
  }
}

export function captureError(err: unknown) {
  if (!initialised) return;
  try {
     
    const Sentry = require("@sentry/react-native");
    Sentry.captureException(err);
  } catch {}
}
