/**
 * Iter 128d — Legacy Overview (V1 Home) is retired.
 *
 * The Coach Dashboard is now a single product; V1/V2 concepts should not be
 * visible in coach UX. Any bookmark or lingering deep link to `/(coach)/overview`
 * lands here and gets redirected to the canonical Home.
 *
 * The previous 285-line V1 dashboard was archived in git history as of iter 128c.
 */
import { Redirect } from "expo-router";

export default function RetiredOverviewV1() {
  return <Redirect href="/(coach)/v2-home" />;
}
