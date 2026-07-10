/**
 * Nutrition · Barcode Scanner — Phase-2 placeholder.
 */
import React from "react";
import ComingSoon from "@/src/components/nutrition/ComingSoon";
export default function BarcodeSoon() {
  return (
    <ComingSoon
      title="BARCODE SCANNER"
      icon="barcode-outline"
      subtitle="Phase 2"
      description="Scan any packaged food and Atlas will pull calories, macros, ingredients and serving size straight into your log. We're testing Open Food Facts + Nutritionix providers to give you global coverage."
      bullets={[
        "Instant scan → log",
        "Serving-size adjustment",
        "Save any product as a favourite",
        "Manual fallback when a barcode isn’t recognised",
      ]}
    />
  );
}
