import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import { api } from "./api";

// Register the push token — DOES NOT ASK for permission. Only proceeds if
// the OS-level permission is already granted (i.e. the user opted-in via the
// Notification Preferences card). This keeps the app quiet on first launch,
// per the "ask after onboarding" rule.
export async function registerForPush(userId: string) {
  if (Platform.OS === "web") return;
  try {
    const { status } = await Notifications.getPermissionsAsync();
    if (status !== "granted") return;
    const tokenResp = await Notifications.getDevicePushTokenAsync();
    await api("/register-push", {
      method: "POST",
      body: { user_id: userId, platform: Platform.OS, device_token: tokenResp.data },
    });
  } catch (e) {
    console.log("push register skipped:", e);
  }
}

// Prompt-and-register: explicit user action.
// Returns the resulting permission status.
export async function promptAndRegisterPush(userId: string): Promise<"granted" | "denied" | "not_requested"> {
  if (Platform.OS === "web") return "not_requested";
  try {
    const { status } = await Notifications.requestPermissionsAsync();
    if (status !== "granted") {
      await api("/notifications/permission", { method: "POST", body: { status: "denied", platform: Platform.OS } }).catch(() => null);
      return "denied";
    }
    try {
      const tokenResp = await Notifications.getDevicePushTokenAsync();
      await api("/register-push", {
        method: "POST",
        body: { user_id: userId, platform: Platform.OS, device_token: tokenResp.data },
      });
    } catch { /* token failures are non-fatal */ }
    await api("/notifications/permission", { method: "POST", body: { status: "granted", platform: Platform.OS } }).catch(() => null);
    return "granted";
  } catch {
    return "denied";
  }
}

// Iter 123 — Unregister THIS device's token from the given user on logout so
// notifications never leak to another user who signs into the same device.
// Never throws — logout must proceed even if the push service is unreachable.
export async function unregisterForPush(userId: string): Promise<void> {
  if (Platform.OS === "web") return;
  try {
    const { status } = await Notifications.getPermissionsAsync();
    if (status !== "granted") return;
    let deviceToken: string | undefined;
    try {
      const t = await Notifications.getDevicePushTokenAsync();
      deviceToken = t?.data;
    } catch {
      return; // no token to unregister
    }
    if (!deviceToken) return;
    await api("/unregister-push", {
      method: "POST",
      body: { user_id: userId, platform: Platform.OS, device_token: deviceToken },
    });
  } catch (e) {
    console.log("push unregister skipped:", e);
  }
}

