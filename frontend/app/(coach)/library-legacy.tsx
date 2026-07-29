/**
 * Iter 128d — Legacy Library (V1) is retired.
 *
 * Coaches now use only the unified Exercise Library at /(coach)/library.
 * Any bookmark/deep link to /(coach)/library-legacy is redirected here.
 */
import { Redirect } from "expo-router";

export default function RetiredLibraryLegacy() {
  return <Redirect href="/(coach)/library" />;
}
