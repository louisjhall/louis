/**
 * Iter 128e — Legacy client profile / admin page is retired.
 *
 * All coach admin actions (Reset Password, Coach Assignment, Archive,
 * Delete, Permanent Delete) now live inside the ClientAdminDrawer
 * opened from the canonical workspace ADMIN button.
 *
 * Every navigation to `/coach/client/{id}` is redirected to the workspace.
 * The old 1900+ line page is no longer required.
 */
import { Redirect, useLocalSearchParams } from "expo-router";

export default function RetiredLegacyClientPage() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const target = id ? `/coach/client/${id}/workspace` : "/(coach)/clients";
  return <Redirect href={target as any} />;
}
