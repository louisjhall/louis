/**
 * Cross-platform Confirm + Toast helpers.
 *
 * React-Native-Web (0.21) does NOT implement `Alert.alert(title, msg, buttons)`
 * with buttons — the buttons never render, so any Alert-based confirmation
 * silently fails on the web preview. This util replaces it with a real Modal
 * on web and falls back to native `Alert.alert` on iOS / Android.
 *
 * Usage:
 *   import { confirm, toast, ToastHost } from "@/src/lib/ux";
 *   const ok = await confirm({ title, message, destructive: true });
 *   if (ok) doThing();
 *   toast("Saved");
 *   // Mount <ToastHost /> once at the root or per-screen.
 */
import React, { useEffect, useRef, useState } from "react";
import {
  Alert, Animated, Modal, Platform, Pressable, StyleSheet, Text, View,
} from "react-native";
import { theme } from "./theme";

/* -------------------------------------------------------------------------- */
/*  confirm()                                                                 */
/* -------------------------------------------------------------------------- */

type ConfirmOpts = {
  title: string; message?: string;
  confirmLabel?: string; cancelLabel?: string;
  destructive?: boolean;
};

let _confirmSetter: null | ((v: ConfirmOpts & { resolve: (b: boolean) => void } | null) => void) = null;

export function confirm(opts: ConfirmOpts): Promise<boolean> {
  return new Promise((resolve) => {
    if (Platform.OS === "web" && _confirmSetter) {
      _confirmSetter({ ...opts, resolve });
      return;
    }
    if (Platform.OS === "web") {
      // eslint-disable-next-line no-alert
      resolve(typeof window !== "undefined" && window.confirm ? window.confirm(opts.title + (opts.message ? "\n\n" + opts.message : "")) : true);
      return;
    }
    Alert.alert(
      opts.title,
      opts.message,
      [
        { text: opts.cancelLabel || "Cancel", style: "cancel", onPress: () => resolve(false) },
        { text: opts.confirmLabel || "OK", style: opts.destructive ? "destructive" : "default", onPress: () => resolve(true) },
      ],
      { cancelable: true, onDismiss: () => resolve(false) },
    );
  });
}

/* -------------------------------------------------------------------------- */
/*  toast()                                                                   */
/* -------------------------------------------------------------------------- */

type ToastKind = "info" | "success" | "error";
let _toastSetter: null | ((v: { message: string; kind: ToastKind } | null) => void) = null;

export function toast(message: string, kind: ToastKind = "info"): void {
  if (_toastSetter) { _toastSetter({ message, kind }); return; }
  if (Platform.OS !== "web") Alert.alert(kind === "error" ? "Failed" : "", message);
  // If no host mounted on web we silently drop — but a host is mounted globally in _layout.
}

/* -------------------------------------------------------------------------- */
/*  ToastHost — mount once (in root _layout.tsx)                              */
/* -------------------------------------------------------------------------- */

export function ToastHost() {
  const [confirmState, setConfirmState] = useState<(ConfirmOpts & { resolve: (b: boolean) => void }) | null>(null);
  const [t, setT] = useState<{ message: string; kind: ToastKind } | null>(null);
  const opacity = useRef(new Animated.Value(0)).current;
  const hideTimer = useRef<any>(null);

  useEffect(() => { _confirmSetter = setConfirmState; _toastSetter = setT; return () => { _confirmSetter = null; _toastSetter = null; }; }, []);

  useEffect(() => {
    if (!t) return;
    Animated.timing(opacity, { toValue: 1, duration: 180, useNativeDriver: true }).start();
    clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => {
      Animated.timing(opacity, { toValue: 0, duration: 220, useNativeDriver: true }).start(() => setT(null));
    }, 2600);
    return () => clearTimeout(hideTimer.current);
  }, [t, opacity]);

  return (
    <>
      {/* Confirm dialog */}
      <Modal visible={!!confirmState} transparent animationType="fade" onRequestClose={() => confirmState?.resolve(false)}>
        <View style={s.confirmBackdrop}>
          <View style={s.confirmCard}>
            <Text style={s.confirmTitle}>{confirmState?.title}</Text>
            {confirmState?.message ? <Text style={s.confirmMsg}>{confirmState.message}</Text> : null}
            <View style={s.confirmBtnRow}>
              <Pressable onPress={() => { confirmState?.resolve(false); setConfirmState(null); }} style={[s.cBtn, s.cBtnGhost]}>
                <Text style={s.cBtnGhostT}>{confirmState?.cancelLabel || "CANCEL"}</Text>
              </Pressable>
              <Pressable onPress={() => { confirmState?.resolve(true); setConfirmState(null); }}
                style={[s.cBtn, confirmState?.destructive ? s.cBtnDanger : s.cBtnPri]}>
                <Text style={s.cBtnT}>{confirmState?.confirmLabel || "OK"}</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Toast */}
      {t ? (
        <Animated.View pointerEvents="none" style={[s.toastWrap, { opacity }]}>
          <View style={[s.toast, kindStyle(t.kind)]}>
            <Text style={s.toastT}>{t.message}</Text>
          </View>
        </Animated.View>
      ) : null}
    </>
  );
}

function kindStyle(k: ToastKind) {
  if (k === "success") return { borderColor: theme.color.green, backgroundColor: "rgba(16,185,129,0.12)" };
  if (k === "error") return { borderColor: "#c94a4a", backgroundColor: "rgba(201,74,74,0.12)" };
  return { borderColor: theme.color.brand, backgroundColor: "rgba(163,24,46,0.12)" };
}

const s = StyleSheet.create({
  confirmBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.75)", alignItems: "center", justifyContent: "center", padding: 20 },
  confirmCard: { width: "100%", maxWidth: 380, backgroundColor: theme.color.surface2, borderRadius: 16, padding: 20, borderWidth: 1, borderColor: theme.color.border },
  confirmTitle: { color: theme.color.text, fontSize: 16, fontWeight: "900", letterSpacing: 0.5, fontFamily: theme.font.display },
  confirmMsg: { color: theme.color.textMuted, fontSize: 13, marginTop: 8, lineHeight: 19, fontFamily: theme.font.text },
  confirmBtnRow: { flexDirection: "row", gap: 10, marginTop: 20 },
  cBtn: { flex: 1, paddingVertical: 12, borderRadius: 8, alignItems: "center" },
  cBtnGhost: { backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border },
  cBtnGhostT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  cBtnPri: { backgroundColor: theme.color.brand },
  cBtnDanger: { backgroundColor: "#c94a4a" },
  cBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1 },

  toastWrap: { position: "absolute", left: 0, right: 0, bottom: 40, alignItems: "center", zIndex: 9999 },
  toast: { paddingHorizontal: 18, paddingVertical: 12, borderRadius: 10, borderWidth: 1, maxWidth: 360, backgroundColor: theme.color.surface2 },
  toastT: { color: theme.color.text, fontSize: 13, fontFamily: theme.font.textSemi },
});
