/**
 * BetaMilestonePromptOverlay — Iter202 · Phase 2A.
 *
 * Mounted GLOBALLY in `app/_layout.tsx`. Polls `/beta/next-prompt`
 * whenever the user changes and renders a dismissible modal for the
 * next un-delivered in-app milestone (Day 21 / 25 / 28 / 30).
 *
 * Design rules:
 *   • Renders nothing when: not signed in, no next prompt, or user
 *     is on an auth route (login/signup/reset).
 *   • One dismissal per milestone — persisted server-side so the
 *     modal never comes back until the NEXT milestone.
 *   • CTA always routes to /(client)/membership. Day 25 has a
 *     secondary "Take the 2-minute survey" CTA that opens
 *     /(client)/beta-survey.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, Modal, ActivityIndicator, Platform,
} from "react-native";
import { useRouter, usePathname } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { theme } from "@/src/lib/theme";

type Prompt = {
  milestone?: string;
  title?: string;
  body?: string;
  cta?: string;
  survey_cta?: string;
  tone?: "soft" | "mid" | "strong" | "expired";
  days_remaining?: number;
  founding_still_available?: boolean;
};

const AUTH_EXEMPT = ["/login", "/signup", "/forgot-password", "/reset-password"];

export function BetaMilestonePromptOverlay() {
  const { user } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [busy, setBusy] = useState(false);

  const shouldSkip = !user
    || (user.role && user.role !== "client")
    || AUTH_EXEMPT.some((p) => (pathname || "").includes(p));

  const load = useCallback(async () => {
    if (shouldSkip) { setPrompt(null); return; }
    try {
      const r = await api<Prompt>("/beta/next-prompt");
      setPrompt(r && r.milestone ? r : null);
    } catch { setPrompt(null); }
  }, [shouldSkip]);

  useEffect(() => { void load(); }, [load, user?.id]);

  const dismiss = useCallback(async () => {
    if (!prompt?.milestone) return;
    setBusy(true);
    try {
      await api("/beta/milestone/dismiss", {
        method: "POST", body: { milestone: prompt.milestone },
      });
    } catch { /* best-effort — hide anyway */ }
    setPrompt(null);
    setBusy(false);
  }, [prompt]);

  const gotoMembership = useCallback(async () => {
    await dismiss();
    router.push("/(client)/membership" as any);
  }, [dismiss, router]);

  const gotoSurvey = useCallback(async () => {
    await dismiss();
    router.push("/(client)/beta-survey" as any);
  }, [dismiss, router]);

  if (!prompt || !prompt.milestone) return null;

  const tone = prompt.tone || "soft";
  return (
    <Modal transparent animationType="fade" visible testID="beta-milestone-prompt">
      <View style={styles.backdrop}>
        <View style={[styles.card, TONE_STYLES[tone].card]}>
          <Pressable
            onPress={dismiss}
            style={styles.closeBtn}
            hitSlop={10}
            testID="beta-prompt-dismiss"
          >
            <Ionicons name="close" size={22} color={theme.color.textMuted} />
          </Pressable>

          {prompt.days_remaining != null && tone !== "expired" ? (
            <Text style={[styles.chip, TONE_STYLES[tone].chip]}>
              {prompt.days_remaining} DAY{prompt.days_remaining === 1 ? "" : "S"} REMAINING
            </Text>
          ) : null}

          <Text style={styles.title}>{prompt.title}</Text>
          <Text style={styles.body}>{prompt.body}</Text>

          {prompt.founding_still_available ? (
            <Text style={styles.foundingLine} testID="beta-prompt-founding-line">
              Your Founding Member offer is still available.
            </Text>
          ) : null}

          <View style={styles.ctaRow}>
            {prompt.survey_cta ? (
              <Pressable
                onPress={gotoSurvey}
                disabled={busy}
                style={({ pressed }) => [styles.ctaSecondary, pressed && { opacity: 0.7 }]}
                testID="beta-prompt-survey"
              >
                <Text style={styles.ctaSecondaryText}>{prompt.survey_cta}</Text>
              </Pressable>
            ) : null}
            <Pressable
              onPress={gotoMembership}
              disabled={busy}
              style={({ pressed }) => [styles.ctaPrimary, pressed && { opacity: 0.75 }]}
              testID="beta-prompt-cta"
            >
              {busy ? <ActivityIndicator color="#fff" /> : (
                <Text style={styles.ctaPrimaryText}>{prompt.cta || "View Memberships"}</Text>
              )}
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const TONE_STYLES: Record<string, { card: object; chip: object }> = {
  soft:    { card: { borderColor: theme.color.border }, chip: { color: theme.color.textMuted, borderColor: theme.color.border } },
  mid:     { card: { borderColor: "#f7b955" }, chip: { color: "#f7b955", borderColor: "#f7b955" } },
  strong:  { card: { borderColor: theme.color.brand, borderWidth: 2 }, chip: { color: theme.color.brand, borderColor: theme.color.brand } },
  expired: { card: { borderColor: theme.color.brand, borderWidth: 2 }, chip: { color: theme.color.brand, borderColor: theme.color.brand } },
};

const styles = StyleSheet.create({
  backdrop: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.75)",
    alignItems: "center", justifyContent: "center", padding: 20,
  },
  card: {
    width: "100%", maxWidth: 440,
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.lg, padding: theme.space.xl,
    borderWidth: 1,
    ...(Platform.OS === "web" ? { boxShadow: "0 20px 40px rgba(0,0,0,0.4)" } : { shadowColor: "#000", shadowOpacity: 0.4, shadowRadius: 20, shadowOffset: { width: 0, height: 12 }, elevation: 20 }),
  },
  closeBtn: { position: "absolute", top: 10, right: 10, padding: 6, zIndex: 2 },
  chip: {
    alignSelf: "flex-start",
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, borderWidth: 1,
    fontSize: 10, letterSpacing: 1.4, fontWeight: "800", marginBottom: 10,
  },
  title: { color: theme.color.text, fontSize: 20, fontWeight: "800", lineHeight: 26 },
  body: { color: theme.color.textMuted, fontSize: 14, lineHeight: 20, marginTop: 8 },
  foundingLine: { color: "#f7b955", fontSize: 12, fontWeight: "700", marginTop: 10 },
  ctaRow: { marginTop: theme.space.xl, gap: 8 },
  ctaPrimary: {
    backgroundColor: theme.color.brand,
    paddingVertical: 13, borderRadius: theme.radius.md, alignItems: "center", minHeight: 46,
    justifyContent: "center",
  },
  ctaPrimaryText: { color: "#fff", fontWeight: "800", letterSpacing: 1.4, fontSize: 13 },
  ctaSecondary: {
    paddingVertical: 12, borderRadius: theme.radius.md, alignItems: "center",
    borderWidth: 1, borderColor: theme.color.border,
  },
  ctaSecondaryText: { color: theme.color.text, fontWeight: "700", letterSpacing: 1, fontSize: 12 },
});
