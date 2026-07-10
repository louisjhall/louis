/**
 * Nutrition · Barcode Scanner (Phase 2).
 *
 * Native: full-screen `CameraView` (expo-camera v17) with `onBarcodeScanned`.
 *          Auto-focus + duplicate-scan debounce, then transitions to a Review
 *          card where the client adjusts servings + meal type before saving.
 * Web:    Camera scanning is not reliable in RN-Web, so we render a
 *          manual-entry field for the barcode digits (Playwright / preview UX)
 *          — production users will use the native build.
 *
 * Not-found fallback: the review card shows a "Log manually" CTA that opens
 * /nutrition/log with sensible defaults.
 */
import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, Image, Linking, Platform, Pressable, ScrollView,
  StyleSheet, Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { CameraView, useCameraPermissions } from "expo-camera";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

type Product = {
  source: string; name: string; brand?: string; image_url?: string;
  calories?: number; protein_g?: number; carbs_g?: number; fats_g?: number;
  serving_size_g?: number; serving_size_text?: string; ingredients?: string;
};

const MEALS = [
  { key: "breakfast", label: "BREAKFAST" }, { key: "lunch", label: "LUNCH" }, { key: "dinner", label: "DINNER" },
  { key: "snack", label: "SNACK" }, { key: "pre_flight", label: "PRE-FLIGHT" }, { key: "in_flight", label: "IN-FLIGHT" },
  { key: "post_flight", label: "POST-FLIGHT" }, { key: "post_workout", label: "POST-WORKOUT" },
];

export default function BarcodeScanner() {
  const router = useRouter();
  const [permission, requestPermission] = useCameraPermissions();
  const [phase, setPhase] = useState<"scanning" | "loading" | "review" | "not_found" | "manual">(
    Platform.OS === "web" ? "manual" : "scanning",
  );
  const [product, setProduct] = useState<Product | null>(null);
  const [barcode, setBarcode] = useState<string>("");
  const [manualCode, setManualCode] = useState<string>("");
  const [servings, setServings] = useState<number>(1);
  const [mealType, setMealType] = useState<string>("snack");
  const [saveFav, setSaveFav] = useState(false);
  const [saving, setSaving] = useState(false);
  const lastScanRef = useRef<string>("");
  const lastScanTsRef = useRef<number>(0);

  // Request permission on mount (native only)
  useEffect(() => {
    if (Platform.OS === "web") return;
    if (!permission) return;
    if (permission.status === "undetermined") {
      requestPermission();
    }
  }, [permission, requestPermission]);

  const handleScanned = async (data: string) => {
    if (phase !== "scanning") return;
    // debounce identical / rapid scans
    const now = Date.now();
    if (data === lastScanRef.current && now - lastScanTsRef.current < 3000) return;
    lastScanRef.current = data; lastScanTsRef.current = now;
    doLookup(data);
  };

  const doLookup = async (code: string) => {
    setBarcode(code);
    setPhase("loading");
    try {
      const r = await api<{ found: boolean; product: Product | null; source?: string }>(
        `/nutrition/barcode/lookup?code=${encodeURIComponent(code)}`,
      );
      if (r.found && r.product) {
        setProduct(r.product);
        setPhase("review");
      } else {
        setProduct(null);
        setPhase("not_found");
      }
    } catch (e: any) {
      toast(e?.message || "Lookup failed", "error");
      setPhase(Platform.OS === "web" ? "manual" : "scanning");
    }
  };

  const scanAgain = () => {
    lastScanRef.current = ""; lastScanTsRef.current = 0;
    setProduct(null); setBarcode(""); setServings(1); setSaveFav(false);
    setPhase(Platform.OS === "web" ? "manual" : "scanning");
  };

  const save = async () => {
    if (!product) return;
    setSaving(true);
    try {
      await api("/nutrition/logs/from-barcode", {
        method: "POST",
        body: {
          barcode, servings, meal_type: mealType,
          save_as_favourite: saveFav,
        },
      });
      toast(`Logged · ${product.name}`, "success");
      router.back();
    } catch (e: any) { toast(e?.message || "Save failed", "error"); }
    finally { setSaving(false); }
  };

  const submitManual = () => {
    const code = manualCode.trim();
    if (!/^\d{6,14}$/.test(code)) { toast("Barcode should be 6–14 digits", "error"); return; }
    doLookup(code);
  };

  /* ---------------- render branches ---------------- */

  if (Platform.OS !== "web" && permission && permission.status !== "granted") {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <Header onBack={() => router.back()} />
        <View style={styles.centerPad}>
          <Ionicons name="camera-outline" size={44} color={theme.color.brand} />
          <Text style={styles.permTitle}>Camera Access</Text>
          <Text style={styles.permMsg}>
            Point the camera at a food package barcode and Atlas will log it in one tap — calories, macros, brand, and serving size.
          </Text>
          {permission.canAskAgain !== false ? (
            <Pressable onPress={requestPermission} style={styles.primaryBtn}>
              <Text style={styles.primaryBtnT}>ALLOW CAMERA</Text>
            </Pressable>
          ) : (
            <Pressable onPress={() => Linking.openSettings()} style={styles.primaryBtn}>
              <Text style={styles.primaryBtnT}>OPEN SETTINGS</Text>
            </Pressable>
          )}
          <Pressable onPress={() => setPhase("manual")} style={styles.secondaryBtn}>
            <Text style={styles.secondaryBtnT}>ENTER BARCODE MANUALLY</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={phase === "scanning" ? [] : ["top"]}>
      {phase === "scanning" ? (
        <View style={styles.camWrap}>
          <CameraView
            style={StyleSheet.absoluteFill}
            facing="back"
            barcodeScannerSettings={{
              barcodeTypes: ["ean13", "ean8", "upc_a", "upc_e", "code128", "code39", "qr"],
            }}
            onBarcodeScanned={({ data }) => handleScanned(String(data))}
          />
          {/* Overlay */}
          <View style={styles.overlayHeader}>
            <Pressable onPress={() => router.back()} style={styles.overlayBtn} hitSlop={12}>
              <Ionicons name="chevron-back" size={24} color="#fff" />
            </Pressable>
            <Text style={styles.overlayT}>SCAN BARCODE</Text>
            <Pressable onPress={() => setPhase("manual")} style={styles.overlayBtn} hitSlop={12}>
              <Ionicons name="keypad-outline" size={20} color="#fff" />
            </Pressable>
          </View>
          <View style={styles.scanFrameWrap} pointerEvents="none">
            <View style={styles.scanFrame}>
              <View style={[styles.corner, styles.cornerTL]} />
              <View style={[styles.corner, styles.cornerTR]} />
              <View style={[styles.corner, styles.cornerBL]} />
              <View style={[styles.corner, styles.cornerBR]} />
            </View>
            <Text style={styles.hintT}>Line up the barcode inside the frame</Text>
          </View>
        </View>
      ) : phase === "loading" ? (
        <>
          <Header onBack={() => router.back()} />
          <View style={styles.centerPad}>
            <ActivityIndicator color={theme.color.brand} size="large" />
            <Text style={styles.loadingT}>Looking up {barcode}…</Text>
          </View>
        </>
      ) : phase === "review" && product ? (
        <>
          <Header onBack={scanAgain} title="REVIEW & LOG" />
          <ScrollView contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: 100 }}>
            <View style={styles.productCard}>
              {product.image_url ? (
                <Image source={{ uri: product.image_url }} style={styles.productImg} />
              ) : (
                <View style={[styles.productImg, styles.productImgFallback]}>
                  <Ionicons name="cube" size={30} color={theme.color.textDim} />
                </View>
              )}
              <View style={{ flex: 1 }}>
                <Text style={styles.productName} numberOfLines={2}>{product.name}</Text>
                {product.brand ? <Text style={styles.productBrand}>{product.brand}</Text> : null}
                <Text style={styles.productServing}>
                  {product.serving_size_text || (product.serving_size_g ? `${product.serving_size_g}g` : "per serving")}
                </Text>
                <View style={styles.sourceBadge}>
                  <Ionicons name="checkmark-circle" size={10} color={theme.color.green} />
                  <Text style={styles.sourceT}>{product.source.replace(/_/g, " ").toUpperCase()}</Text>
                </View>
              </View>
            </View>

            <View style={styles.macroCard}>
              <MacroCol label="KCAL" value={Math.round((product.calories || 0) * servings)} />
              <MacroCol label="PROTEIN" value={`${Math.round((product.protein_g || 0) * servings)}g`} />
              <MacroCol label="CARBS" value={`${Math.round((product.carbs_g || 0) * servings)}g`} />
              <MacroCol label="FATS" value={`${Math.round((product.fats_g || 0) * servings)}g`} />
            </View>

            <Text style={styles.label}>SERVINGS</Text>
            <View style={styles.servingsRow}>
              <Pressable onPress={() => setServings((v) => Math.max(0.25, +(v - 0.25).toFixed(2)))}
                style={styles.svBtn}>
                <Ionicons name="remove" size={20} color="#fff" />
              </Pressable>
              <View style={styles.svVal}><Text style={styles.svValT}>{servings.toFixed(2).replace(/\.?0+$/, "")}x</Text></View>
              <Pressable onPress={() => setServings((v) => Math.min(20, +(v + 0.25).toFixed(2)))}
                style={styles.svBtn}>
                <Ionicons name="add" size={20} color="#fff" />
              </Pressable>
              <View style={styles.svQuick}>
                {[0.5, 1, 1.5, 2].map((n) => (
                  <Pressable key={n} onPress={() => setServings(n)}
                    style={[styles.svQuickBtn, servings === n && styles.svQuickBtnOn]}>
                    <Text style={[styles.svQuickT, servings === n && styles.svQuickTOn]}>{n}x</Text>
                  </Pressable>
                ))}
              </View>
            </View>

            <Text style={styles.label}>MEAL TYPE</Text>
            <View style={styles.chipRow}>
              {MEALS.map((m) => (
                <Pressable key={m.key} onPress={() => setMealType(m.key)}
                  style={[styles.chip, mealType === m.key && styles.chipOn]}>
                  <Text style={[styles.chipT, mealType === m.key && styles.chipTOn]}>{m.label}</Text>
                </Pressable>
              ))}
            </View>

            <Pressable onPress={() => setSaveFav((v) => !v)} style={styles.favRow}>
              <Ionicons name={saveFav ? "checkmark-circle" : "ellipse-outline"}
                size={18} color={saveFav ? theme.color.brand : theme.color.textMuted} />
              <Text style={styles.favT}>SAVE AS FAVOURITE</Text>
            </Pressable>
          </ScrollView>

          <View style={styles.footer}>
            <Pressable onPress={scanAgain} style={[styles.footerBtn, styles.footerBtnGhost]}>
              <Text style={styles.footerBtnGhostT}>SCAN AGAIN</Text>
            </Pressable>
            <Pressable onPress={save} disabled={saving}
              style={[styles.footerBtn, styles.footerBtnPri, saving && { opacity: 0.5 }]}>
              {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.footerBtnT}>LOG MEAL</Text>}
            </Pressable>
          </View>
        </>
      ) : phase === "not_found" ? (
        <>
          <Header onBack={scanAgain} title="NOT FOUND" />
          <View style={styles.centerPad}>
            <Ionicons name="alert-circle" size={44} color={theme.color.amber} />
            <Text style={styles.permTitle}>Product Not Found</Text>
            <Text style={styles.permMsg}>
              We couldn&apos;t find <Text style={{ color: theme.color.text, fontWeight: "900" }}>{barcode}</Text> in our food database. You can log it manually and save it as a favourite so scanning it later works instantly.
            </Text>
            <Pressable onPress={() => router.replace(`/nutrition/log?barcode=${encodeURIComponent(barcode)}` as any)}
              style={styles.primaryBtn}>
              <Text style={styles.primaryBtnT}>LOG MANUALLY</Text>
            </Pressable>
            <Pressable onPress={scanAgain} style={styles.secondaryBtn}>
              <Text style={styles.secondaryBtnT}>SCAN ANOTHER</Text>
            </Pressable>
          </View>
        </>
      ) : (
        // Manual entry (also default on web)
        <>
          <Header onBack={() => router.back()} title="ENTER BARCODE" />
          <View style={{ flex: 1, padding: 20, gap: 16 }}>
            <Text style={styles.label}>BARCODE DIGITS</Text>
            <TextInput
              value={manualCode}
              onChangeText={(v) => setManualCode(v.replace(/[^0-9]/g, ""))}
              placeholder="e.g. 5449000000996"
              placeholderTextColor={theme.color.textDim}
              style={styles.manualInput}
              keyboardType="number-pad"
              autoFocus
              maxLength={14}
              testID="manual-barcode-input"
            />
            <Text style={styles.hint}>6–14 digits · UPC-A, EAN-13, EAN-8, Code-128 supported.</Text>
            <Pressable onPress={submitManual} disabled={!manualCode} style={[styles.primaryBtn, !manualCode && { opacity: 0.5 }]} testID="manual-barcode-submit">
              <Text style={styles.primaryBtnT}>LOOK UP</Text>
            </Pressable>
            {Platform.OS !== "web" ? (
              <Pressable onPress={() => setPhase("scanning")} style={styles.secondaryBtn}>
                <Ionicons name="camera" size={14} color={theme.color.textMuted} />
                <Text style={styles.secondaryBtnT}>OR USE CAMERA</Text>
              </Pressable>
            ) : (
              <Text style={styles.webNote}>
                Camera scanning is available on the native iOS / Android build. In the web preview, enter the barcode manually.
              </Text>
            )}
          </View>
        </>
      )}
    </SafeAreaView>
  );
}

/* -------------------- Sub-components -------------------- */

function Header({ onBack, title = "SCAN BARCODE" }: { onBack: () => void; title?: string }) {
  return (
    <View style={styles.header}>
      <Pressable onPress={onBack} hitSlop={12}>
        <Ionicons name="chevron-back" size={24} color={theme.color.text} />
      </Pressable>
      <Text style={styles.headerT}>{title}</Text>
      <View style={{ width: 24 }} />
    </View>
  );
}

function MacroCol({ label, value }: { label: string; value: any }) {
  return (
    <View style={{ flex: 1, alignItems: "center" }}>
      <Text style={styles.macroK}>{label}</Text>
      <Text style={styles.macroV}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  centerPad: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 12 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.text, fontSize: 14, letterSpacing: 3, fontWeight: "900", fontFamily: theme.font.display },

  // Camera overlay
  camWrap: { flex: 1, backgroundColor: "#000" },
  overlayHeader: { position: "absolute", top: 40, left: 0, right: 0, padding: 16, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  overlayBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: "rgba(0,0,0,0.5)", alignItems: "center", justifyContent: "center" },
  overlayT: { color: "#fff", fontSize: 13, letterSpacing: 3, fontWeight: "900", fontFamily: theme.font.display },
  scanFrameWrap: { flex: 1, alignItems: "center", justifyContent: "center" },
  scanFrame: { width: 260, height: 160, position: "relative" },
  corner: { position: "absolute", width: 28, height: 28, borderColor: theme.color.brand },
  cornerTL: { top: 0, left: 0, borderTopWidth: 3, borderLeftWidth: 3 },
  cornerTR: { top: 0, right: 0, borderTopWidth: 3, borderRightWidth: 3 },
  cornerBL: { bottom: 0, left: 0, borderBottomWidth: 3, borderLeftWidth: 3 },
  cornerBR: { bottom: 0, right: 0, borderBottomWidth: 3, borderRightWidth: 3 },
  hintT: { color: "#fff", fontSize: 12, marginTop: 20, letterSpacing: 1, backgroundColor: "rgba(0,0,0,0.5)", paddingHorizontal: 12, paddingVertical: 6, borderRadius: 20 },

  loadingT: { color: theme.color.text, fontSize: 13, marginTop: 12 },

  // Permission screen
  permTitle: { color: theme.color.text, fontSize: 18, fontWeight: "900", letterSpacing: 0.5, fontFamily: theme.font.display, marginTop: 8 },
  permMsg: { color: theme.color.textMuted, fontSize: 13, textAlign: "center", lineHeight: 20, fontFamily: theme.font.text, marginBottom: 8 },
  primaryBtn: { paddingHorizontal: 24, paddingVertical: 14, borderRadius: 10, backgroundColor: theme.color.brand, marginTop: 8 },
  primaryBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
  secondaryBtn: { paddingHorizontal: 18, paddingVertical: 12, borderRadius: 8, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, marginTop: 4, flexDirection: "row", alignItems: "center", gap: 6 },
  secondaryBtnT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1 },

  // Product review
  productCard: { flexDirection: "row", gap: 12, padding: 12, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  productImg: { width: 74, height: 74, borderRadius: 10, backgroundColor: theme.color.surface3 },
  productImgFallback: { alignItems: "center", justifyContent: "center" },
  productName: { color: theme.color.text, fontSize: 15, fontWeight: "900", fontFamily: theme.font.display },
  productBrand: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 0.5, marginTop: 2, fontWeight: "700" },
  productServing: { color: theme.color.textDim, fontSize: 11, marginTop: 4, fontStyle: "italic" },
  sourceBadge: { flexDirection: "row", alignItems: "center", gap: 3, marginTop: 5, alignSelf: "flex-start", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, backgroundColor: theme.color.surface3 },
  sourceT: { color: theme.color.green, fontSize: 8, letterSpacing: 0.8, fontWeight: "900" },

  macroCard: { flexDirection: "row", padding: 12, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  macroK: { color: theme.color.textMuted, fontSize: 9, letterSpacing: 1.5, fontWeight: "900" },
  macroV: { color: theme.color.text, fontSize: 17, fontWeight: "900", marginTop: 4, fontFamily: theme.font.display },

  label: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, fontWeight: "900", marginTop: 6, fontFamily: theme.font.textSemi },
  servingsRow: { flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" },
  svBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center" },
  svVal: { minWidth: 60, paddingHorizontal: 14, paddingVertical: 10, borderRadius: 8, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, alignItems: "center" },
  svValT: { color: theme.color.text, fontSize: 15, fontWeight: "900", fontFamily: theme.font.display },
  svQuick: { flexDirection: "row", gap: 4, flex: 1, justifyContent: "flex-end" },
  svQuickBtn: { paddingHorizontal: 8, paddingVertical: 6, borderRadius: 6, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  svQuickBtnOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  svQuickT: { color: theme.color.textMuted, fontSize: 10, fontWeight: "900" },
  svQuickTOn: { color: "#fff" },

  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 20, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  chipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.textMuted, fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  chipTOn: { color: "#fff" },

  favRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 10 },
  favT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },

  footer: { flexDirection: "row", gap: 8, padding: 14, borderTopWidth: 1, borderTopColor: theme.color.divider, backgroundColor: theme.color.surface },
  footerBtn: { flex: 1, paddingVertical: 14, borderRadius: 8, alignItems: "center" },
  footerBtnGhost: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  footerBtnGhostT: { color: theme.color.textMuted, fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
  footerBtnPri: { backgroundColor: theme.color.brand },
  footerBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },

  // Manual entry
  manualInput: { color: theme.color.text, backgroundColor: theme.color.surface2, borderRadius: 10, paddingHorizontal: 16, paddingVertical: 16, fontSize: 22, borderWidth: 1, borderColor: theme.color.border, fontFamily: theme.font.display, letterSpacing: 2, textAlign: "center" },
  hint: { color: theme.color.textDim, fontSize: 11, textAlign: "center", fontStyle: "italic" },
  webNote: { color: theme.color.textDim, fontSize: 11, textAlign: "center", fontStyle: "italic", marginTop: 10, lineHeight: 17 },
});
