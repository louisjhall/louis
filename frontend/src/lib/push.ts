import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import { api } from "./api";

export async function registerForPush(userId: string) {
  if (Platform.OS === "web") return;
  try {
    const { status } = await Notifications.requestPermissionsAsync();
    if (status !== "granted") return;
    const tokenResp = await Notifications.getDevicePushTokenAsync();
    await api("/register-push", {
      method: "POST",
      body: { user_id: userId, platform: Platform.OS, device_token: tokenResp.data },
    });
  } catch (e) {
    // non-blocking: dev builds or Expo Go will not have push
    console.log("push register skipped:", e);
  }
}
