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
import { View, Text, Pressable, StyleSheet, useWindowDimensions, Platform } from "react-native";
import { BottomTabBarProps } from "@react-navigation/bottom-tabs";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Animated, {
  useSharedValue, useAnimatedStyle, withSpring, withTiming,
} from "react-native-reanimated";
import { theme } from "@/src/lib/theme";

type IconName = React.ComponentProps<typeof MaterialCommunityIcons>["name"];

const TAB_META: Record<string, { label: string; icon: IconName; iconActive?: IconName }> = {
  home:      { label: "TODAY",     icon: "lightning-bolt-outline",   iconActive: "lightning-bolt"          },
  calendar:  { label: "CALENDAR",  icon: "calendar-blank-outline",   iconActive: "calendar-blank"          },
  nutrition: { label: "NUTRITION", icon: "silverware-fork-knife",    iconActive: "silverware-fork-knife"   },
  messages:  { label: "MESSAGES",  icon: "message-text-outline",     iconActive: "message-text"            },
  profile:   { label: "PROFILE",   icon: "account-circle-outline",   iconActive: "account-circle"          },
};

export function PremiumTabBar({ state, descriptors, navigation }: BottomTabBarProps) {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const compact = width < 380; // small iPhones: tighten labels

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
              focused={isFocused}
              compact={compact}
              onPress={onPress}
              onLongPress={onLongPress}
              accessibilityLabel={options.tabBarAccessibilityLabel ?? meta.label}
            />
          );
        })}
      </View>
    </View>
  );
}

function TabButton({
  label, icon, focused, compact, onPress, onLongPress, accessibilityLabel,
}: {
  label: string;
  icon: IconName;
  focused: boolean;
  compact: boolean;
  onPress: () => void;
  onLongPress: () => void;
  accessibilityLabel: string;
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

  return (
    <Pressable
      onPress={onPress}
      onLongPress={onLongPress}
      onPressIn={() => { scale.value = withSpring(0.92, { damping: 18, stiffness: 260 }); }}
      onPressOut={() => { scale.value = withSpring(1, { damping: 18, stiffness: 260 }); }}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ selected: focused }}
      testID={`tab-${label.toLowerCase()}`}
      style={styles.tabPressable}
      hitSlop={{ top: 6, bottom: 6, left: 4, right: 4 }}
    >
      <Animated.View style={[styles.pill, animPillStyle]} />
      <Animated.View style={[styles.inner, animContentStyle]}>
        <MaterialCommunityIcons
          name={icon}
          size={focused ? 23 : 22}
          color={focused ? theme.color.brand : theme.color.textDim}
        />
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
    fontSize: 10,
    letterSpacing: 1.2,
    marginTop: 2,
    includeFontPadding: false,
  },
  labelCompact: {
    fontSize: 9,
    letterSpacing: 0.9,
  },
  labelActive: {
    color: theme.color.text,
  },
  labelInactive: {
    color: theme.color.textDim,
  },
});
