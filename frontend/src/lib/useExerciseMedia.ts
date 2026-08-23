/**
 * useExerciseMedia — shared exercise-media resolver for both the manual
 * play flow and the guided flow. Returns { thumbUrl, hasVideo, content }
 * so both surfaces show IDENTICAL imagery.
 *
 * Iter189q bug fix: guided.tsx previously only read `custom_image_b64` /
 * `coach_image_url` from the legacy V1 `/exercises/content` endpoint,
 * which almost always returns nothing for exercises created via Manual
 * Mode (they only live in V2 `exercises_v2` with an AI-generated
 * `primary_image_id`). Manual mode already fell back to the V2 image
 * stream, so its cards had thumbnails while guided flow showed a black
 * box. This hook centralises the fallback ladder used by manual mode.
 *
 * Resolution ladder (highest priority first):
 *   1. V2 primary_image_id / demo_start_image_id / demo_end_image_id
 *      → `/api/exercise-content/images/{id}/stream?token=...`
 *   2. Legacy V1 `custom_image_b64` (data URI) or `coach_image_url`
 *   3. null (caller renders placeholder)
 */
import { useEffect, useState } from "react";
import { api, API_BASE, getToken } from "@/src/lib/api";

export type ExerciseMedia = {
  content: any | null;
  thumbUrl: string | null;
  hasVideo: boolean;
};

const _cache = new Map<string, ExerciseMedia>();

export function useExerciseMedia(name: string | null | undefined): ExerciseMedia {
  const [state, setState] = useState<ExerciseMedia>(() =>
    name ? _cache.get(name.trim().toLowerCase()) || {
      content: null, thumbUrl: null, hasVideo: false,
    } : { content: null, thumbUrl: null, hasVideo: false },
  );

  useEffect(() => {
    if (!name) return;
    const key = name.trim().toLowerCase();
    if (!key) return;
    let cancel = false;

    // Reset visible state whenever the target exercise changes so the
    // caller doesn't briefly show the previous item's thumb.
    if (_cache.has(key)) {
      setState(_cache.get(key)!);
    } else {
      setState({ content: null, thumbUrl: null, hasVideo: false });
    }

    (async () => {
      // ---- V2 first (Manual-mode created exercises live here) --------
      let ex: any = null;
      try {
        const r = await api<any>(
          `/exercise-content?q=${encodeURIComponent(name)}&limit=5`,
        );
        const list: any[] = r?.exercises || [];
        const wanted = key;
        ex = list.find(
          (e) => String(e?.exercise_name || "").trim().toLowerCase() === wanted,
        ) || list[0] || null;
      } catch { /* silent */ }

      // ---- Legacy V1 as coaching-content backfill --------------------
      let legacy: any = null;
      try {
        const r2 = await api<any>(
          `/exercises/content?name=${encodeURIComponent(name)}`,
        );
        legacy = r2?.exercise || null;
      } catch { /* silent */ }

      if (cancel) return;

      // Merge fields — prefer V2 for coaching content, keep legacy media
      // as a backfill so pre-V2 exercises still display.
      const content: any = {
        name: ex?.exercise_name || legacy?.name || name,
        cues: ex?.coaching_points || legacy?.cues || [],
        instructions: ex?.instructions
          ? (Array.isArray(ex.instructions) ? ex.instructions : [ex.instructions])
          : (legacy?.instructions || []),
        mistakes: ex?.common_mistakes || legacy?.mistakes || [],
        custom_image_b64: legacy?.custom_image_b64 || null,
        coach_image_url: legacy?.coach_image_url || null,
        coach_video_url: ex?.coach_video_url || legacy?.coach_video_url || null,
        video_url: ex?.primary_video_url || legacy?.video_url || null,
        has_video_v2: !!(ex?.content_status?.video || ex?.primary_video_url),
      };

      // Build the thumb URL — V2 stream first, legacy fallback second.
      let thumbUrl: string | null = null;
      const imgId: string | null =
        ex?.primary_image_id || ex?.demo_start_image_id || ex?.demo_end_image_id || null;
      if (imgId) {
        const token = await getToken();
        thumbUrl = `${API_BASE}/exercise-content/images/${imgId}/stream${
          token ? `?token=${encodeURIComponent(token)}` : ""
        }`;
      } else if (content.custom_image_b64 || content.coach_image_url) {
        thumbUrl = content.custom_image_b64 || content.coach_image_url;
      }

      const hasVideo = !!(
        content.coach_video_url || content.video_url || content.has_video_v2
      );
      const next: ExerciseMedia = { content, thumbUrl, hasVideo };
      _cache.set(key, next);
      if (!cancel) setState(next);
    })();

    return () => { cancel = true; };
  }, [name]);

  return state;
}
