import React from "react";
import ComingSoon from "@/src/components/nutrition/ComingSoon";
export default function DecideSoon() {
  return (
    <ComingSoon
      title="ATLAS MEAL DECISION"
      icon="help-circle"
      subtitle="Phase 4"
      description="One tap, one clear decision. Tell Atlas your situation — airport, hotel buffet, layover, night flight, only snacks, about to train, just landed — and get a protein-first plan that matches your goal, roster and remaining targets."
      bullets={[
        "Instant meal call",
        "Goal-aware",
        "Roster + time-zone aware",
        "Protein-first, no shaming",
      ]}
    />
  );
}
