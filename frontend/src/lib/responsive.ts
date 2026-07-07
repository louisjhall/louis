import { Platform, useWindowDimensions } from "react-native";

/**
 * Returns true when the app is running on a wide web viewport (>=1024px).
 * Used to switch the coach experience to a desktop sidebar layout.
 */
export function useIsDesktop(): boolean {
  const { width } = useWindowDimensions();
  return Platform.OS === "web" && width >= 1024;
}

export function useIsWide(): boolean {
  const { width } = useWindowDimensions();
  return Platform.OS === "web" && width >= 768;
}
