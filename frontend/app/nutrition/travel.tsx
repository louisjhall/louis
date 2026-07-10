/**
 * Nutrition · Travel Food Guidance — Phase-4 placeholder.
 */
import React from "react";
import ComingSoon from "@/src/components/nutrition/ComingSoon";
export default function TravelSoon() {
  return (
    <ComingSoon
      title="TRAVEL FOOD"
      icon="airplane"
      subtitle="Phase 4"
      description="Personalised food strategy for every leg of your roster. Airport, hotel breakfast, hotel buffet, crew meal, long-haul, night flight, layover — all tailored to your goal and today’s duty."
      bullets={[
        "Airport food strategy",
        "Hotel buffet playbook",
        "Long-haul + night-flight timing",
        "Fat-loss on layovers",
        "Muscle-gain while travelling",
      ]}
    />
  );
}
