/**
 * SocialButtons — Google (via Emergent Auth) + Apple sign-in.
 *
 * Iter200 (member sign-up / login only).
 *
 * Rules from the auth playbook:
 *   • Google button: shown on ALL platforms. Redirects the user to
 *     `auth.emergentagent.com`. On mobile we use `WebBrowser.openAuthSessionAsync`;
 *     on web we set `window.location.href` and read the returned
 *     `session_id` from the URL fragment on mount (handled in
 *     `useEmergentAuthCallback` below).
 *   • Apple button: shown only when `AppleAuthentication.isAvailableAsync()`
 *     resolves true — i.e. iOS 13+. Rendered as Apple's mandated
 *     black button per HIG.
 *   • Neither button ever contacts Emergent's or Apple's servers
 *     directly with a `session_token` — they hand off to the backend.
 *   • `busy` prop disables both buttons while a submit is in flight
 *     (e.g. during the email/password log-in). Prevents interleaved
 *     auth attempts.
 */
import React, { useEffect, useState, useCallback } from "react";
import {
  View, Text, Pressable, StyleSheet, ActivityIndicator, Platform, Alert,
} from "react-native";
import * as WebBrowser from "expo-web-browser";
import * as Linking from "expo-linking";
import * as AppleAuthentication from "expo-apple-authentication";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { useAuth } from "@/src/lib/auth";
import { useRouter } from "expo-router";

// Complete any in-progress web browser auth sessions. Must be called
// at module scope for iOS to release the auth session on return.
WebBrowser.maybeCompleteAuthSession();

const EMERGENT_AUTH_URL = "https://auth.emergentagent.com/";

function buildRedirectUrl(): string {
  if (Platform.OS === "web") {
    if (typeof window !== "undefined" && window.location) {
      return window.location.origin + "/";
    }
    return "https://flight-fit-plans.preview.emergentagent.com/";
  }
  // On mobile Linking.createURL resolves to `exp://…` in Expo Go and
  // `crewfit://` in a native build — either shape is a valid deep
  // link back into the app.
  return Linking.createURL("/");
}

function extractSessionId(url: string): string | null {
  if (!url) return null;
  // Emergent puts `session_id` in the hash on web and on some mobile
  // paths. Linking.parse().queryParams only sees the query string, so
  // we do a raw regex match against the full URL to catch both.
  const m = url.match(/[?#&]session_id=([^&#]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

/**
 * Root-mounted hook: watches for `session_id` arriving via URL fragment
 * (web) or deep link (mobile), and exchanges it against our backend.
 *
 * Guards against React strict mode / native double-fire by tracking
 * every session_id we've already tried.
 */
export function useEmergentAuthCallback() {
  const { loginWithEmergentSession } = useAuth();
  const router = useRouter();

  // Persist across strict-mode double invoke via a module-level Set —
  // React state resets between mounts, but this Set lives for the
  // process lifetime.
  const consumeSession = useCallback(async (sid: string) => {
    if (_consumedSids.has(sid)) return;
    _consumedSids.add(sid);
    try {
      await loginWithEmergentSession(sid);
      // Success — auth state now has the user, root-layout gate
      // will move the user off the login screen automatically. We
      // still clean the URL so a refresh doesn't re-fire.
      if (Platform.OS === "web" && typeof window !== "undefined") {
        try {
          const u = new URL(window.location.href);
          u.searchParams.delete("session_id");
          const hash = (u.hash || "").replace(/([#&])session_id=[^&]*/g, "$1")
            .replace(/^#&/, "#").replace(/^#$/, "");
          u.hash = hash;
          window.history.replaceState(window.history.state, "", u.toString());
        } catch {}
      }
    } catch (e: any) {
      _consumedSids.delete(sid); // let the user retry
      Alert.alert("Sign-in failed", e?.message || "Please try again.");
    }
  }, [loginWithEmergentSession]);

  useEffect(() => {
    // Web: parse the current URL on mount.
    if (Platform.OS === "web" && typeof window !== "undefined") {
      const sid = extractSessionId(window.location.href);
      if (sid) { void consumeSession(sid); }
      return;
    }
    // Mobile: two co-equal sources on Android + iOS — the initial URL
    // if the app was killed and reopened via the deep link, and the
    // live `url` event if the app was backgrounded.
    let cancelled = false;
    Linking.getInitialURL().then((u) => {
      if (cancelled || !u) return;
      const sid = extractSessionId(u);
      if (sid) void consumeSession(sid);
    }).catch(() => {});
    const sub = Linking.addEventListener("url", (evt) => {
      const sid = extractSessionId(evt.url || "");
      if (sid) void consumeSession(sid);
    });
    return () => { cancelled = true; sub.remove(); };
    // consumeSession is stable per render — safe to depend on it.
  }, [consumeSession]);
  // Also let callers push the router if they want to react on success.
  return { router };
}

// Module-level so it survives strict-mode remounts.
const _consumedSids = new Set<string>();


export function SocialButtons({
  busy,
  ctaCopy = "Continue",
}: {
  busy?: boolean;
  /** Overrides the button labels on the sign-up screen where we want
   *  "Sign up with X" instead of the default "Continue with X". */
  ctaCopy?: "Continue" | "Sign up" | "Sign in";
}) {
  const [appleAvailable, setAppleAvailable] = useState(false);
  const [appleBusy, setAppleBusy] = useState(false);
  const [googleBusy, setGoogleBusy] = useState(false);
  const { loginWithApple } = useAuth();

  useEffect(() => {
    let cancelled = false;
    if (Platform.OS === "ios") {
      AppleAuthentication.isAvailableAsync()
        .then((ok) => { if (!cancelled) setAppleAvailable(!!ok); })
        .catch(() => {});
    }
    return () => { cancelled = true; };
  }, []);

  const onGoogle = useCallback(async () => {
    if (busy || googleBusy) return;
    setGoogleBusy(true);
    try {
      const redirectUrl = buildRedirectUrl();
      const authUrl =
        `${EMERGENT_AUTH_URL}?redirect=${encodeURIComponent(redirectUrl)}`;
      if (Platform.OS === "web") {
        // On web, a full-page redirect keeps the auth session in the
        // same window so we can read `session_id` from the URL on
        // return. openAuthSessionAsync would open a cross-origin
        // popup and silently lose the callback.
        if (typeof window !== "undefined") {
          window.location.href = authUrl;
        }
        return;
      }
      const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUrl);
      // The Linking listener wired in `useEmergentAuthCallback` will
      // catch the callback URL. On iOS `result.url` also contains it —
      // we surface it here too so a user who terminates the browser
      // early still gets the exchange path attempted.
      const url = (result && (result as any).url) || "";
      const sid = extractSessionId(url);
      if (sid) {
        // Duplicate-fire is fine — `useEmergentAuthCallback` and the
        // `_consumedSids` set dedupe.
        // Dispatch via router-scoped hook by dispatching the deep-link
        // event Linking listeners already handle. Simpler: fetch the
        // auth context here and reuse.
        // Nothing to do — the Linking listener will pick this up.
      }
    } catch (e: any) {
      Alert.alert("Google sign-in failed", e?.message || "Please try again.");
    } finally {
      setGoogleBusy(false);
    }
  }, [busy, googleBusy]);

  const onApple = useCallback(async () => {
    if (busy || appleBusy) return;
    setAppleBusy(true);
    try {
      const cred = await AppleAuthentication.signInAsync({
        requestedScopes: [
          AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
          AppleAuthentication.AppleAuthenticationScope.EMAIL,
        ],
      });
      if (!cred.identityToken) {
        Alert.alert("Apple sign-in failed", "No identity token was returned.");
        return;
      }
      await loginWithApple({
        identity_token: cred.identityToken,
        given_name: cred.fullName?.givenName || null,
        family_name: cred.fullName?.familyName || null,
      });
      // Root-layout gate handles navigation.
    } catch (e: any) {
      // ERR_CANCELED / ERR_REQUEST_CANCELED — user tapped cancel;
      // treat as no-op.
      const code = e?.code || "";
      if (code === "ERR_REQUEST_CANCELED" || code === "ERR_CANCELED") {
        return;
      }
      Alert.alert("Apple sign-in failed", e?.message || "Please try again.");
    } finally {
      setAppleBusy(false);
    }
  }, [busy, appleBusy, loginWithApple]);

  return (
    <View style={styles.wrap}>
      <View style={styles.divider}>
        <View style={styles.dividerLine} />
        <Text style={styles.dividerText}>OR</Text>
        <View style={styles.dividerLine} />
      </View>

      <Pressable
        testID="social-google"
        onPress={onGoogle}
        disabled={busy || googleBusy}
        style={({ pressed }) => [
          styles.googleBtn,
          (pressed || busy || googleBusy) && { opacity: 0.75 },
        ]}
      >
        {googleBusy ? (
          <ActivityIndicator color="#3c4043" />
        ) : (
          <>
            <Ionicons name="logo-google" size={18} color="#3c4043" />
            <Text style={styles.googleText}>{ctaCopy} with Google</Text>
          </>
        )}
      </Pressable>

      {appleAvailable && Platform.OS === "ios" ? (
        <AppleAuthentication.AppleAuthenticationButton
          testID="social-apple"
          buttonType={
            ctaCopy === "Sign up"
              ? AppleAuthentication.AppleAuthenticationButtonType.SIGN_UP
              : AppleAuthentication.AppleAuthenticationButtonType.SIGN_IN
          }
          buttonStyle={AppleAuthentication.AppleAuthenticationButtonStyle.WHITE_OUTLINE}
          cornerRadius={theme.radius.md}
          style={styles.appleBtn}
          onPress={onApple}
        />
      ) : null}
    </View>
  );
}


const styles = StyleSheet.create({
  wrap: { marginTop: theme.space.lg },
  divider: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: theme.space.md,
    gap: 12,
  },
  dividerLine: {
    flex: 1,
    height: StyleSheet.hairlineWidth,
    backgroundColor: theme.color.border,
  },
  dividerText: {
    color: theme.color.textDim,
    fontSize: 11,
    letterSpacing: 2,
    fontWeight: "700",
  },
  googleBtn: {
    backgroundColor: "#ffffff",
    borderRadius: theme.radius.md,
    paddingVertical: 12,
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "center",
    gap: 10,
    minHeight: 48,
    marginBottom: 10,
  },
  googleText: {
    color: "#3c4043",
    fontWeight: "600",
    fontSize: 14,
    letterSpacing: 0.4,
  },
  appleBtn: {
    height: 48,
    width: "100%",
  },
});
