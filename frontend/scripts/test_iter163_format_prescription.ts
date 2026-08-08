/**
 * Iter 163 · Unit tests for formatPrescription — Bulletproof Formatting.
 *
 * Run with: `npx tsx scripts/test_iter163_format_prescription.ts`
 * (or: cd /app/frontend && node --loader ts-node/esm scripts/…)
 *
 * These are pure-function assertions with no React or DOM dependencies —
 * they exercise the exact formatter that ships in the Manual + Guided
 * workout screens.
 */
import {
  formatPrescription,
  parsePrescriptionRaw,
  inferPrescription,
} from "../src/lib/formatPrescription";

let failures = 0;
function eq(got: string, want: string, label: string) {
  if (got === want) {
    console.log(`  ✅  ${label}: "${got}"`);
  } else {
    failures += 1;
    console.log(`  ❌  ${label}: expected "${want}", got "${got}"`);
  }
}

console.log("[A] formatPrescription structured fields");
eq(formatPrescription({ sets: 1, volume: 30, unit: "min" }), "1 x 30 Minutes", "1 x 30 Minutes");
eq(formatPrescription({ sets: 3, volume: 12, unit: "reps" }), "3 x 12 Reps", "3 x 12 Reps");
eq(formatPrescription({ sets: 4, volume: 8, unit: "each side" }), "4 x 8 Each Side", "4 x 8 Each Side");
eq(formatPrescription({ sets: 1, volume: 45, unit: "sec" }), "1 x 45 Seconds", "1 x 45 Seconds");
eq(formatPrescription({ sets: 3, volume: 5, unit: "km" }), "3 x 5 km", "3 x 5 km");
eq(formatPrescription({ sets: 1, volume: 1, unit: "min" }), "1 x 1 Minute", "singular minute");
eq(formatPrescription({ sets: 1, volume: 1, unit: "reps" }), "1 x 1 Rep", "singular rep");
eq(formatPrescription({ sets: 1, volume: 1, unit: "sec" }), "1 x 1 Second", "singular second");

console.log("\n[B] Legacy raw string parsing");
const p1 = parsePrescriptionRaw("3 x 12");
console.log("  parseRaw('3 x 12') =>", p1);
eq(p1?.sets === 3 && p1?.volume === "12" && p1?.unit === "reps" ? "ok" : "bad", "ok", "'3 x 12'");
const p2 = parsePrescriptionRaw("1 × 30 min");
console.log("  parseRaw('1 × 30 min') =>", p2);
eq(p2?.sets === 1 && p2?.volume === "30" && p2?.unit === "min" ? "ok" : "bad", "ok", "'1 × 30 min'");
const p3 = parsePrescriptionRaw("45 seconds");
eq(p3?.sets === 1 && p3?.volume === "45" && p3?.unit === "sec" ? "ok" : "bad", "ok", "'45 seconds'");
const p4 = parsePrescriptionRaw("5km run");
eq(p4?.sets === 1 && p4?.volume === "5" && p4?.unit === "km" ? "ok" : "bad", "ok", "'5km run'");

console.log("\n[C] inferPrescription from legacy ExRow shapes");
eq(formatPrescription(inferPrescription({ sets: 3, reps: 12 })), "3 x 12 Reps", "sets+reps → 3 x 12 Reps");
eq(formatPrescription(inferPrescription({ sets: 1, duration_sec: 1800 })), "1 x 30 Minutes", "1800s → 1 x 30 Minutes");
eq(formatPrescription(inferPrescription({ sets: 1, duration_sec: 45 })), "1 x 45 Seconds", "45s → 1 x 45 Seconds");
eq(formatPrescription(inferPrescription({ sets: 1, distance_km: 5 })), "1 x 5 km", "distance 5km");
eq(formatPrescription(inferPrescription({ sets: 4, reps: "8/side" })), "4 x 8 Each Side", "reps='8/side' → each side");
eq(formatPrescription(inferPrescription({ sets: 1, volume: 30, unit: "min" })), "1 x 30 Minutes", "explicit structured overrides");

console.log("\n[D] Edge cases");
eq(formatPrescription({ sets: 0, volume: 12, unit: "reps" }), "1 x 12 Reps", "sets=0 clamps to 1");
eq(formatPrescription({ volume: 30, unit: "min" }), "1 x 30 Minutes", "sets undefined → 1");
eq(formatPrescription({ sets: 3, volume: "", unit: "reps" }), "", "empty volume → empty string");
eq(formatPrescription({ raw: null as any }), "", "null raw → empty");

if (failures === 0) {
  console.log("\n✅  All formatPrescription assertions passed.");
} else {
  console.log(`\n❌  ${failures} assertion(s) failed.`);
  process.exit(1);
}
