/**
 * coachProfile.ts — single source of truth for the client-facing identity
 * of CrewFit's head coach. Every screen that shows "the coach" to a client
 * must pull from this config so we can swap the photo or update the tagline
 * from one place.
 *
 * This is deliberately client-side + hard-coded for V1. Once we support
 * multiple coaches server-side, replace the resolver with an API call to
 * `/api/coach/profile/main` (route already added).
 */

export type CoachIdentity = {
  /** Full legal / listing name. */
  fullName: string;
  /** Short display name shown in chat bubbles + greetings. */
  displayName: string;
  /** Two-letter initials shown when the avatar image can't load. */
  initials: string;
  /** Title clients see. Keep it warm and specific, not "Admin". */
  title: string;
  /** Longer subtitle for the message screen header. */
  tagline: string;
  /** Public, permanent HTTPS URL to a portrait crop. */
  avatarUrl: string;
  /** Coach email — used for lookup + support links. */
  email: string;
};

export const LOUIS: CoachIdentity = {
  fullName: "Louis Hall",
  displayName: "Louis",
  initials: "LH",
  title: "CrewFit Coach",
  tagline: "Founder & Aviation Performance Coach",
  avatarUrl:
    "https://customer-assets.emergentagent.com/job_flight-fit-plans/artifacts/q32k4b7w_Screenshot%202026-07-12%20153226.png",
  email: "louis@crewfit.net",
};

/**
 * Identify whether the currently logged-in coach is Louis himself. Any
 * @crewfit.net or matching-email account is treated as Louis; any other
 * coach account (e.g. seeded coach@crewfit.com legacy or a future second
 * coach) shows their real name and initials instead.
 */
export function isLouis(user: { email?: string | null; name?: string | null } | null | undefined) {
  if (!user) return false;
  const e = (user.email || "").toLowerCase();
  return e === LOUIS.email || e.endsWith("@crewfit.net");
}
