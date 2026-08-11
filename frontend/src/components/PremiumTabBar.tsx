/**
 * PremiumTabBar — Bespoke bottom navigation for the client app.
 *
 * Design goals:
 * - Aviation cockpit feel: dark matte panel, hairline top border, precise
 *   line icons in a single family, subtle red control-accent on active.
 * - Active tab uses a soft pill background (brandTint) with the brand red
 *   as border + icon fill. Small scale on press. No jitter.
 * - Inactive tabs are dim but readable — never truncated because we use
 *   short 3–7 char labels and shrink font-size below 380px wide viewports.
 * - Safe-area aware (bottom inset), works on iPhone, Android, gesture bars.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet, useWindowDimensions, Platform, AppState } from "react-native";
import { BottomTabBarProps } from "@react-navigation/bottom-tabs";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Animated, {
  useSharedValue, useAnimatedStyle, withSpring, withTiming,
} from "react-native-reanimated";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";
import { BaseIcon } from "@/src/components/BaseIcon";

type IconName = React.ComponentProps<typeof MaterialCommunityIcons>["name"];

// Iter 122 — client bottom navigation swaps MESSAGES → BASE (Aviation
// crew community). Messages moves to the floating <CoachChatBubble />.
const TAB_META: Record<string, { label: string; icon: IconName; iconActive?: IconName; custom?: "base" }> = {
  home:      { label: "TODAY",     icon: "lightning-bolt-outline",   iconActive: "lightning-bolt"          },
  calendar:  { label: "CALENDAR",  icon: "calendar-blank-outline",   iconActive: "calendar-blank"          },
  nutrition: { label: "NUTRITION", icon: "silverware-fork-knife",    iconActive: "silverware-fork-knife"   },
  base:      { label: "BASE",      icon: "account-group-outline",    iconActive: "account-group",   custom: "base" },
  profile:   { label: "PROFILE",   icon: "account-circle-outline",   iconActive: "account-circle"          },
};

// Iter 82 — unread badge (relocated to floating CoachChatBubble in Iter 122).
// Kept as a hook here for backward compatibility but no tab consumes it now.
function useUnreadMessages() {
  const [count, setCount] = React.useState(0);
  const load = React.useCallback(async () => {
    try {
      const r = await api<{ count: number }>("/messages-unread/count");
      setCount(Number(r?.count || 0));
    } catch {
      /* offline / logged out — silent */
    }
  }, []);
  React.useEffect(() => {
    load();
    const iv = setInterval(load, 30_000);
    const sub = AppState.addEventListener("change", (s) => { if (s === "active") load(); });
    return () => { clearInterval(iv); sub.remove(); };
  }, [load]);
  return count;
}
void useUnreadMessages;  // preserved for future re-use

// Iter 165 · Crew Base unread hook — drives a small red dot on the BASE tab.
// Polls `/crew-base/unread-count` every 30s and on app foreground. The
// endpoint already exists and tracks unread posts against the user's
// `crew_base_seen` record; here we only need a boolean "should we glow?"
// so we coerce the count into a dot state.
function useCrewBaseUnread(): boolean {
  const [hasNew, setHasNew] = React.useState(false);
  const load = React.useCallback(async () => {
    try {
      const r = await api<{ count: number }>("/crew-base/unread-count");
      setHasNew(Number(r?.count || 0) > 0);
    } catch {
      /* silent — endpoint may be absent on older backends */
    }
  }, []);
  React.useEffect(() => {
    load();
    const iv = setInterval(load, 30_000);
    const sub = AppState.addEventListener("change", (s) => { if (s === "active") load(); });
    return () => { clearInterval(iv); sub.remove(); };
  }, [load]);
  return hasNew;
}

export function PremiumTabBar({ state, descriptors, navigation }: BottomTabBarProps) {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const compact = width < 380; // small iPhones: tighten labels
  // Iter 165 · Poll Crew Base unread once here and pass a flag to the BASE tab.
  const baseHasNew = useCrewBaseUnread();

  return (
    <View style={[styles.wrap, { paddingBottom: Math.max(insets.bottom, 10) }]}>
      {/* Hairline top border with a subtle red glow. Kept 1px so it stays elegant. */}
      <View style={styles.hairline} />

      <View style={styles.row}>
        {state.routes.map((route, index) => {
          const meta = TAB_META[route.name];
          if (!meta) return null;
          const isFocused = state.index === index;
          const { options } = descriptors[route.key];

          const onPress = () => {
            const event = navigation.emit({ type: "tabPress", target: route.key, canPreventDefault: true });
            if (!isFocused && !event.defaultPrevented) {
              navigation.navigate(route.name as never);
            }
          };
          const onLongPress = () => {
            navigation.emit({ type: "tabLongPress", target: route.key });
          };

          return (
            <TabButton
              key={route.key}
              label={meta.label}
              icon={isFocused ? (meta.iconActive || meta.icon) : meta.icon}
              custom={meta.custom}
              focused={isFocused}
              compact={compact}
              onPress={onPress}
              onLongPress={onLongPress}
              accessibilityLabel={options.tabBarAccessibilityLabel ?? meta.label}
              badgeCount={0}
              showDot={route.name === "base" && baseHasNew}
              testID={`tab-${route.name}`}
            />
          );
        })}
      </View>
    </View>
  );
}

function TabButton({
  label, icon, custom, focused, compact, onPress, onLongPress, accessibilityLabel,
  badgeCount = 0, showDot = false, testID,
}: {
  label: string;
  icon: IconName;
  custom?: "base";
  focused: boolean;
  compact: boolean;
  onPress: () => void;
  onLongPress: () => void;
  accessibilityLabel: string;
  badgeCount?: number;
  showDot?: boolean;
  testID?: string;
}) {
  const scale = useSharedValue(1);
  const opacity = useSharedValue(focused ? 1 : 0);

  React.useEffect(() => {
    opacity.value = withTiming(focused ? 1 : 0, { duration: 220 });
  }, [focused, opacity]);

  const animPillStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
    transform: [{ scale: 0.94 + opacity.value * 0.06 }],
  }));
  const animContentStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  const badgeCount_ = badgeCount || 0;

  return (
    <Pressable
      onPress={onPress}
      onLongPress={onLongPress}
      onPressIn={() => { scale.value = withSpring(0.92, { damping: 18, stiffness: 260 }); }}
      onPressOut={() => { scale.value = withSpring(1, { damping: 18, stiffness: 260 }); }}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ selected: focused }}
      testID={testID || `tab-${label.toLowerCase()}`}
      style={styles.tabPressable}
      hitSlop={{ top: 6, bottom: 6, left: 4, right: 4 }}
    >
      <Animated.View style={[styles.pill, animPillStyle]} />
      <Animated.View style={[styles.inner, animContentStyle]}>
        <View>
          {custom === "base" ? (
            <BaseIcon
              size={focused ? 23 : 22}
              color={focused ? theme.color.brand : theme.color.textDim}
              filled={focused}
            />
          ) : (
            <MaterialCommunityIcons
              name={icon}
              size={focused ? 23 : 22}
              color={focused ? theme.color.brand : theme.color.textDim}
            />
          )}
          {badgeCount_ > 0 ? (
            <View style={styles.badge} testID={`tab-badge-${label.toLowerCase()}`}>
              <Text style={styles.badgeText}>
                {badgeCount_ > 99 ? "99+" : badgeCount_}
              </Text>
            </View>
          ) : showDot ? (
            // Iter 165 · Small red dot indicator (Crew Base new posts).
            // Positioned top-right of the icon, sits above the label.
            <View style={styles.dot} testID={`tab-dot-${label.toLowerCase()}`} />
          ) : null}
        </View>
        <Text
          numberOfLines={1}
          allowFontScaling={false}
          style={[
            styles.label,
            compact && styles.labelCompact,
            focused ? styles.labelActive : styles.labelInactive,
          ]}
        >
          {label}
        </Text>
      </Animated.View>
    </Pressable>
  );
}

const BAR_HEIGHT_CONTENT = 54;   // Icon+label block. Total = this + safe-area inset.

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: "#08080B",     // slightly deeper than surface2 for panel feel
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.color.borderStrong,
    // Subtle upward glow on iOS — invisible on Android but harmless.
    ...Platform.select({
      ios: {
        shadowColor: theme.color.brand,
        shadowOpacity: 0.18,
        shadowOffset: { width: 0, height: -3 },
        shadowRadius: 12,
      },
      default: {},
    }),
  },
  hairline: {
    position: "absolute",
    left: "22%",
    right: "22%",
    top: -1,
    height: 1,
    backgroundColor: theme.color.brand,
    opacity: 0.25,
  },
  row: {
    flexDirection: "row",
    height: BAR_HEIGHT_CONTENT,
    paddingHorizontal: 6,
    paddingTop: 4,
  },
  tabPressable: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    position: "relative",
    paddingHorizontal: 2,
    // Ensure a proper 44pt-min touch target even inside the compact bar.
    minHeight: 44,
  },
  pill: {
    position: "absolute",
    top: 0,
    left: 8,
    right: 8,
    bottom: 0,
    borderRadius: 14,
    backgroundColor: theme.color.brandTint,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.brand,
  },
  inner: {
    alignItems: "center",
    justifyContent: "center",
    gap: 3,
  },
  label: {
    fontFamily: theme.font.textSemi ?? theme.font.text,
    fontSize: 11,
    letterSpacing: 1.2,
    marginTop: 2,
    includeFontPadding: false,
  },
  labelCompact: {
    fontSize: 11,
    letterSpacing: 0.9,
  },
  labelActive: {
    color: theme.color.text,
  },
  labelInactive: {
    color: theme.color.textDim,
  },
  // Iter 82 — unread messages badge (top-right of icon)
  badge: {
    position: "absolute",
    top: -6,
    right: -10,
    minWidth: 16,
    height: 16,
    paddingHorizontal: 4,
    borderRadius: 8,
    backgroundColor: theme.color.brand,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1.5,
    borderColor: "#08080B",
  },
  badgeText: {
    color: "#fff",
    fontSize: 11,
    fontWeight: "800",
    lineHeight: 12,
    includeFontPadding: false,
  },
  // Iter 165 · Small red dot indicator — used by the BASE tab when the
  // Crew Base has new posts the client hasn't seen yet. Deliberately
  // dot-only (no count) so it stays understated on the nav bar.
  dot: {
    position: "absolute",
    top: -3,
    right: -5,
    width: 9,
    height: 9,
    borderRadius: 4.5,
    backgroundColor: theme.color.brand,
    borderWidth: 1.5,
    borderColor: "#08080B",
  },
});
