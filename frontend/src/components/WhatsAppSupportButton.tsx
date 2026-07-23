import { useState } from "react";
import { View, Text, StyleSheet, Pressable, Linking, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

/**
 * Iter 94k — WhatsApp support button.
 *
 * Use for BETA support only:
 *   - Under Louis's welcome message
 *   - Roster upload failed / stuck
 *   - Programme needs review / generation failed
 *   - Workout equipment didn't match / safe fallback
 *   - Hotel setup wrong
 *   - Onboarding help
 *
 * Do NOT put on every screen. Normal coaching stays inside CrewFit.
 */
const WHATSAPP_URL = "https://wa.link/k9x12s";

export type WhatsAppSupportButtonProps = {
  /** Which screen/state is invoking this? For analytics + coach timeline. */
  screen: string;
  /** Optional context ("roster_upload_failed", "workout_fallback", etc.). */
  context?: string;
  /** Related IDs (if any) — passed through for coach timeline correlation. */
  rosterId?: string;
  programmeId?: string;
  workoutId?: string;
  /** Optional label override — defaults to "Message Louis on WhatsApp". */
  label?: string;
  /** Visual variant — filled (primary CTA) vs. outline (secondary). */
  variant?: "filled" | "outline";
  /** Show the "This opens WhatsApp outside the CrewFit app" small caption. */
  showCaption?: boolean;
  /** Wrapper style overrides. */
  style?: any;
  testID?: string;
};

export function WhatsAppSupportButton(props: WhatsAppSupportButtonProps) {
  const {
    screen, context, rosterId, programmeId, workoutId,
    label = "Message Louis on WhatsApp",
    variant = "filled",
    showCaption = true,
    style, testID = "wa-support-btn",
  } = props;

  const [pending, setPending] = useState(false);

  const onPress = async () => {
    if (pending) return;
    setPending(true);
    // Fire-and-forget click log — never let this block the WhatsApp open.
    api("/support/whatsapp-clicked", {
      method: "POST",
      body: { screen, context, roster_id: rosterId, programme_id: programmeId, workout_id: workoutId },
    }).catch(() => { /* silent */ });

    try {
      const supported = await Linking.canOpenURL(WHATSAPP_URL).catch(() => true);
      if (!supported) {
        // Some devices (web / older Androids) return false but still open OK.
        // Fall through and try anyway — Linking.openURL will error if truly not supported.
      }
      await Linking.openURL(WHATSAPP_URL);
    } catch {
      Alert.alert(
        "WhatsApp could not open",
        "You can still message Louis inside CrewFit.",
      );
    } finally {
      setPending(false);
    }
  };

  const isFilled = variant === "filled";

  return (
    <View style={style}>
      <Pressable
        onPress={onPress}
        disabled={pending}
        testID={testID}
        style={[
          styles.btn,
          isFilled ? styles.btnFilled : styles.btnOutline,
          pending && { opacity: 0.6 },
        ]}
      >
        <Ionicons
          name="logo-whatsapp"
          size={16}
          color={isFilled ? "#fff" : "#25D366"}
        />
        <Text style={[styles.btnLabel, isFilled ? styles.btnLabelFilled : styles.btnLabelOutline]}>
          {label}
        </Text>
      </Pressable>
      {showCaption ? (
        <Text style={styles.caption}>
          This opens WhatsApp outside the CrewFit app.
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  btn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderRadius: 10,
  },
  btnFilled: {
    backgroundColor: "#25D366", // Official WhatsApp green
  },
  btnOutline: {
    backgroundColor: "transparent",
    borderWidth: 1,
    borderColor: "#25D366",
  },
  btnLabel: {
    fontWeight: "800",
    fontSize: 13,
    letterSpacing: 0.5,
  },
  btnLabelFilled: {
    color: "#fff",
  },
  btnLabelOutline: {
    color: "#25D366",
  },
  caption: {
    marginTop: 6,
    fontSize: 11,
    color: theme.color.textMuted,
    textAlign: "center",
    fontStyle: "italic",
  },
});
