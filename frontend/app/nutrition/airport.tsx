import React from "react";
import ComingSoon from "@/src/components/nutrition/ComingSoon";
export default function AirportSoon() {
  return (
    <ComingSoon
      title="AIRPORT SURVIVAL"
      icon="business"
      subtitle="Phase 4"
      description="Best move / OK move / avoid when possible — a fast, practical airport playbook that respects your time, hunger and next duty."
      bullets={[
        "Protein-led best options",
        "Snack backup plan",
        "Hydration reminder",
        "Time-available filter",
      ]}
    />
  );
}
