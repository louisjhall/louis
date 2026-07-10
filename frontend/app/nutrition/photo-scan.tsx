/**
 * Nutrition · Photo Scan — Phase-3 placeholder.
 */
import React from "react";
import ComingSoon from "@/src/components/nutrition/ComingSoon";
export default function PhotoSoon() {
  return (
    <ComingSoon
      title="PHOTO MEAL SCAN"
      icon="camera"
      subtitle="Phase 3"
      description="Snap a photo and Atlas will estimate the meal — items, portions, calories, macros — with a confidence rating. Always presented as an estimate, always editable before you save."
      bullets={[
        "Detects items and portions",
        "Estimates calories + macros",
        "Editable before save",
        "Coaching tip on the plate",
        "Hotel-buffet plate mode",
      ]}
      disclaimer="Atlas photo estimates are coaching guidance, not a lab test. Always adjust anything that looks wrong."
    />
  );
}
