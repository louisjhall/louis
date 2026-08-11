/**
 * Iter 95m — App-root Error Boundary
 *
 * Wraps every screen so a single render error does not blank the app for
 * an App Store reviewer. Renders a graceful "Something's off" screen with
 * a Try Again button and forwards the error to Sentry (already initialised
 * in _layout.tsx) so we can debug post-release.
 *
 * Deliberately zero-dependency (no libs, no navigation) so it stays alive
 * even if the crash was in a shared provider.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet, ScrollView, Platform } from "react-native";
import * as Sentry from "@sentry/react-native";

type Props = { children: React.ReactNode };
type State = { hasError: boolean; error: Error | null; count: number };

export class RootErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false, error: null, count: 0 };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Best-effort report — Sentry is initialised at module load in _layout.tsx.
    try {
      Sentry.captureException(error, { extra: { componentStack: info?.componentStack } });
    } catch {
      /* Sentry not wired — never crash the boundary itself */
    }
    if (__DEV__) {
      // Surface in dev to help debugging.
      console.warn("[RootErrorBoundary]", error, info?.componentStack);
    }
  }

  handleRetry = () => {
    this.setState((s) => ({ hasError: false, error: null, count: s.count + 1 }));
  };

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <View style={styles.root}>
        <ScrollView contentContainerStyle={styles.body} bounces={false}>
          <Text style={styles.eyebrow}>CREWFIT</Text>
          <Text style={styles.title}>Something&apos;s off.</Text>
          <Text style={styles.sub}>
            The app hit an unexpected error. Nothing you did — this one&apos;s on us.
            Tap the button below to reload the screen. If it keeps happening,
            drop Louis a note at louis@crewfit.net and we&apos;ll sort it fast.
          </Text>
          <Pressable
            onPress={this.handleRetry}
            style={styles.btn}
            testID="root-error-retry"
          >
            <Text style={styles.btnT}>TRY AGAIN</Text>
          </Pressable>
          {__DEV__ && this.state.error ? (
            <View style={styles.debug}>
              <Text style={styles.debugHead}>DEV DETAILS</Text>
              <Text style={styles.debugT}>{String(this.state.error?.message || this.state.error)}</Text>
            </View>
          ) : null}
        </ScrollView>
      </View>
    );
  }
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: "#000",
    paddingTop: Platform.OS === "ios" ? 60 : 40,
  },
  body: {
    paddingHorizontal: 28,
    paddingVertical: 40,
    minHeight: "100%",
  },
  eyebrow: {
    color: "#e13049",
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 3,
    marginBottom: 18,
  },
  title: {
    color: "#fff",
    fontSize: 30,
    fontWeight: "900",
    letterSpacing: -0.5,
    marginBottom: 14,
  },
  sub: {
    color: "rgba(255,255,255,0.7)",
    fontSize: 15,
    lineHeight: 22,
    marginBottom: 28,
  },
  btn: {
    alignSelf: "flex-start",
    backgroundColor: "#e13049",
    paddingHorizontal: 22,
    paddingVertical: 14,
    borderRadius: 12,
  },
  btnT: {
    color: "#fff",
    fontSize: 13,
    fontWeight: "900",
    letterSpacing: 1.5,
  },
  debug: {
    marginTop: 40,
    padding: 14,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.12)",
    backgroundColor: "rgba(255,255,255,0.03)",
  },
  debugHead: {
    color: "rgba(255,255,255,0.5)",
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 2,
    marginBottom: 6,
  },
  debugT: {
    color: "rgba(255,255,255,0.85)",
    fontFamily: Platform.OS === "ios" ? "Courier" : "monospace",
    fontSize: 11,
  },
});
