/**
 * Iter 128d — Legacy monthly roster view is retired.
 *
 * The canonical client workspace (`/coach/client/{id}/workspace`) now shows
 * roster + plan by month directly. Any deep link to /coach/client-months/{id}
 * is redirected there.
 */
import { Redirect, useLocalSearchParams } from "expo-router";

export default function RetiredClientMonths() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const target = id ? `/coach/client/${id}/workspace` : "/(coach)/clients";
  return <Redirect href={target as any} />;
}
