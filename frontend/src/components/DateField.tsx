import React, { useState } from "react";
import { View, Text, TextInput, Pressable, StyleSheet, Platform, Modal } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";

// Lazy-load datetime picker only on native to avoid web bundle issues.
let DateTimePicker: any = null;
if (Platform.OS !== "web") {
  try {
    DateTimePicker = require("@react-native-community/datetimepicker").default;
  } catch { /* not installed */ }
}

export function DateField({
  value, onChange, placeholder = "YYYY-MM-DD", testID, min, max,
}: {
  value?: string;                       // ISO YYYY-MM-DD
  onChange: (iso: string) => void;
  placeholder?: string;
  testID?: string;
  min?: string;
  max?: string;
}) {
  const [webVal, setWebVal] = useState(value || "");
  const [nativeOpen, setNativeOpen] = useState(false);

  const isoValid = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s);

  // WEB — use a plain HTML <input type="date"> for great UX
  if (Platform.OS === "web") {
    // @ts-expect-error — web-only element
    return (
      <View style={styles.wrap}>
        <input
          type="date"
          value={webVal}
          onChange={(e: any) => { setWebVal(e.target.value); onChange(e.target.value); }}
          min={min}
          max={max}
          data-testid={testID}
          style={{
            appearance: "none",
            backgroundColor: theme.color.surface2,
            color: theme.color.text,
            border: `1px solid ${theme.color.border}`,
            borderRadius: 8,
            padding: 10,
            fontSize: 14,
            fontFamily: "inherit",
            width: "100%",
            colorScheme: "dark",
          }}
        />
      </View>
    );
  }

  // NATIVE — fall back to modal picker or fallback text input
  if (!DateTimePicker) {
    return (
      <TextInput
        value={value}
        onChangeText={(t) => { onChange(t); }}
        placeholder={placeholder}
        placeholderTextColor={theme.color.textDim}
        style={styles.textInput}
        testID={testID}
      />
    );
  }

  const dateObj = value && isoValid(value) ? new Date(value + "T00:00:00") : new Date();

  return (
    <>
      <Pressable
        testID={testID}
        onPress={() => setNativeOpen(true)}
        style={styles.button}
      >
        <Ionicons name="calendar-outline" size={16} color={theme.color.brand} />
        <Text style={[styles.buttonText, !value && { color: theme.color.textDim }]}>
          {value || placeholder}
        </Text>
      </Pressable>
      <Modal transparent visible={nativeOpen} animationType="fade" onRequestClose={() => setNativeOpen(false)}>
        <Pressable style={styles.backdrop} onPress={() => setNativeOpen(false)}>
          <Pressable style={styles.pickerCard} onPress={() => { /* absorb */ }}>
            <DateTimePicker
              value={dateObj}
              mode="date"
              display={Platform.OS === "ios" ? "spinner" : "default"}
              onChange={(_: any, d?: Date) => {
                if (Platform.OS === "android") setNativeOpen(false);
                if (d) onChange(d.toISOString().slice(0, 10));
              }}
              minimumDate={min ? new Date(min + "T00:00:00") : undefined}
              maximumDate={max ? new Date(max + "T00:00:00") : undefined}
            />
            {Platform.OS === "ios" && (
              <Pressable onPress={() => setNativeOpen(false)} style={styles.doneBtn}>
                <Text style={styles.doneText}>DONE</Text>
              </Pressable>
            )}
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  wrap: { width: "100%" },
  textInput: {
    color: theme.color.text, fontSize: 14, padding: 10,
    borderRadius: 8, backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  button: {
    flexDirection: "row", alignItems: "center", gap: 8,
    padding: 10, borderRadius: 8,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  buttonText: { color: theme.color.text, fontSize: 14, fontWeight: "600" },
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.7)", justifyContent: "center", alignItems: "center", padding: 20 },
  pickerCard: {
    backgroundColor: theme.color.surface, borderRadius: 14,
    padding: 12, width: "90%",
    borderWidth: 1, borderColor: theme.color.border,
  },
  doneBtn: {
    marginTop: 10, paddingVertical: 12, borderRadius: 8,
    backgroundColor: theme.color.brand, alignItems: "center",
  },
  doneText: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 2 },
});
