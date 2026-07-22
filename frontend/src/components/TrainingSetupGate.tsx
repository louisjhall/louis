/**
 * TrainingSetupGate.tsx — Task 1.3
 *
 * On app boot (and on auth changes), checks whether the logged-in client
 * still has any missing essential fields. If so, redirects them to
 * `/training-setup`. Coach accounts are exempt.
 *
 * Guards against redirect loops:
 *   - Skips if the user is already on `/training-setup`
 *   - Skips on the auth screens (/login, /signup, /welcome)
 *   - Skips if not authenticated
 *   - Skips for coaches
 *   - Skips while in preview mode as a new_client (they haven't finished
 *     signup yet — coach knows they're testing)
 */
import { useEffect, useRef } from "react";
import { useRouter, usePathname } from "expo-router";
import { useAuth } from "@/src/lib/auth";
import { api } from "@/src/lib/api";
import { usePreview } from "@/src/lib/preview";

const EXEMPT_PREFIXES = [
  "/training-setup",
  "/login",
  "/signup",
  "/welcome",
  "/legal",
  "/beta-disclaimer",
];

export function TrainingSetupGate() {
  const { user } = useAuth();
  const { preview } = usePreview();
  const router = useRouter();
  const pathname = usePathname();
  const checkedRef = useRef<string | null>(null);   // guard against re-checking same user

  useEffect(() => {
    // No user, or coach → do nothing
    if (!user) return;
    if (user.role === "coach") return;
    // Skip on exempt routes
    if (EXEMPT_PREFIXES.some((p) => pathname.startsWith(p))) return;
    // Skip if we've already checked this user in this app session
    if (checkedRef.current === user.id) return;
    // Skip if the coach is previewing a fresh new_client — they'll drive it manually
    if (preview.active && preview.mode === "new_client") return;

    let cancelled = false;
    (async () => {
      try {
        const r = await api<{ complete: boolean; missing_fields: string[] }>("/profile/setup-status");
        if (cancelled) return;
        checkedRef.current = user.id;
        if (!r.complete) {
          router.replace("/training-setup");
        }
      } catch {
        // Silent — a failed check shouldn't block the app
      }
    })();

    return () => { cancelled = true; };
  }, [user, preview.active, preview.mode, pathname, router]);

  return null;
}
