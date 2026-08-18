/**
 * Coach non-grouped routes layout — wraps every `/coach/*` screen in the
 * DesktopShell sidebar when the app is running on a wide web viewport.
 *
 * Iter184 · Previously, deep-links into `/coach/admin/auto-media`,
 * `/coach/exercise-content`, `/coach/demand-queue`, `/coach/teleprompter/*`
 * and similar routes rendered *without* the coach sidebar because they
 * live outside the `(coach)` route group. Coaches on desktop lost the
 * primary nav mid-flow and had no way to jump back to Home / Library
 * without hitting Back. This layout mirrors `(coach)/_layout.tsx` and
 * restores that continuity for every route directly under `/coach/`.
 *
 * On mobile the layout is a straight passthrough — screens keep their
 * own SafeAreaView / header rendering and the mobile tab bar (owned by
 * the `(coach)` group) remains the primary nav.
 */
import React from "react";
import { Slot } from "expo-router";
import { useIsDesktop } from "@/src/lib/responsive";
import { DesktopShell } from "@/src/desktop/DesktopShell";

export default function CoachAdminLayout() {
  const isDesktop = useIsDesktop();
  if (isDesktop) {
    return (
      <DesktopShell>
        <Slot />
      </DesktopShell>
    );
  }
  return <Slot />;
}
