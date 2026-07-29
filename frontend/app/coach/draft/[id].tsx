/**
 * Iter 128d — Legacy Draft editor is retired.
 *
 * Draft review lives inside the canonical client workspace (`Plan` tab →
 * Programme Draft panel). Redirect any bookmark.
 */
import { Redirect, useLocalSearchParams } from "expo-router";

export default function RetiredLegacyDraft() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const target = id ? `/coach/client/${id}/workspace` : "/(coach)/clients";
  return <Redirect href={target as any} />;
}
