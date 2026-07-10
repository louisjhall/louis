import React from "react";
import ComingSoon from "@/src/components/nutrition/ComingSoon";
export default function TimingSoon() {
  return (
    <ComingSoon
      title="MEAL TIMING"
      icon="time"
      subtitle="Phase 4"
      description="Time-zone aware coaching for when to eat, when to keep meals lighter, caffeine cut-off, and post-flight recovery meal — built from your roster and planned sleep window."
      bullets={[
        "Home vs current time zone",
        "Duty-aware caffeine cut-off",
        "Post-flight recovery timing",
        "Lighter pre-sleep meals",
      ]}
    />
  );
}
