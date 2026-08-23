/**
 * useBottomSafePad — returns the paddingBottom value to give a ScrollView
 * or bottom-anchored button so its content isn't clipped by the Android
 * system navigation bar (gesture pill or 3-button nav).
 *
 * On iOS this returns just `base` (the caller's original hard-coded
 * padding, e.g. 140) — the parent SafeAreaView with `edges=["bottom"]`
 * or the modal presentation already handles home-indicator inset.
 *
 * On Android, we add `insets.bottom + 16` on top of `base`. Android's
 * system nav bar doesn't cause SafeAreaView to auto-inset scrollable
 * content by default, and hard-coded pixel paddings never account for
 * the varying nav bar heights across devices.
 *
 * Iter189r · single source of truth after auditing 23 screens that
 * were previously clipping the last row / button on Android.
 *
 * Usage:
 *   const bottomPad = useBottomSafePad(120);
 *   <ScrollView contentContainerStyle={{ paddingBottom: bottomPad }} …>
 */
import { Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

export function useBottomSafePad(base: number = 24): number {
  const insets = useSafeAreaInsets();
  if (Platform.OS === "android") {
    return base + insets.bottom + 16;
  }
  return base;
}
