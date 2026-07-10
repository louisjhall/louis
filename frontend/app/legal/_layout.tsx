import { Stack } from "expo-router";
import React from "react";
import { theme } from "../../src/lib/theme";

export default function LegalLayout() {
  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: theme.color.surface },
        headerTintColor: theme.color.text,
        headerTitleStyle: { color: theme.color.text, fontFamily: theme.font.display },
        contentStyle: { backgroundColor: theme.color.surface },
      }}
    />
  );
}
