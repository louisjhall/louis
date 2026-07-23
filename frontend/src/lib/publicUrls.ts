/**
 * Public URLs for CrewFit — single source of truth.
 *
 * Anything shown publicly to a user (or shipped to App Store Connect /
 * Play Console metadata) should reference these constants so we don't
 * drift between screens.
 *
 * Rules:
 *  - Do NOT hard-code these URLs anywhere else.
 *  - If Louis changes a domain, update this file only.
 *  - The in-app `/legal/*` screens are the authoritative offline copy;
 *    these HTTPS URLs are the public mirror App Store review will hit.
 */

export const PUBLIC_URLS = {
  privacy:  "https://crewfit.net/privacy",
  support:  "https://crewfit.net/support",
  terms:    "https://crewfit.net/terms",
  website:  "https://crewfit.net",
  whatsapp: "https://wa.link/k9x12s",
  supportEmail: "louis@crewfit.net",
} as const;

export type PublicUrlKey = keyof typeof PUBLIC_URLS;
