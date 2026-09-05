/**
 * On-Demand thumbnail asset map — Iter200 bulk-import.
 *
 * Metro / Expo can only bundle `require()` calls with LITERAL paths, so
 * we generate 103 static requires here (one per workout slot). The
 * import script writes `thumbnail_filename` = `w-001.jpg` .. `w-103.jpg`
 * on each on-demand item; the client looks up the bundled asset by that
 * filename via `resolveThumbnail`.
 *
 * To swap in real artwork: drop the JPG (same filename) into
 * `frontend/assets/on-demand-thumbnails/` — Metro rebuilds automatically.
 *
 * Bumped from 100 → 103 to cover the 103-workout FINAL import.
 */
import type { ImageSourcePropType } from "react-native";

const map: Record<string, ImageSourcePropType> = {
  "w-001.jpg": require("../../assets/on-demand-thumbnails/w-001.jpg"),
  "w-002.jpg": require("../../assets/on-demand-thumbnails/w-002.jpg"),
  "w-003.jpg": require("../../assets/on-demand-thumbnails/w-003.jpg"),
  "w-004.jpg": require("../../assets/on-demand-thumbnails/w-004.jpg"),
  "w-005.jpg": require("../../assets/on-demand-thumbnails/w-005.jpg"),
  "w-006.jpg": require("../../assets/on-demand-thumbnails/w-006.jpg"),
  "w-007.jpg": require("../../assets/on-demand-thumbnails/w-007.jpg"),
  "w-008.jpg": require("../../assets/on-demand-thumbnails/w-008.jpg"),
  "w-009.jpg": require("../../assets/on-demand-thumbnails/w-009.jpg"),
  "w-010.jpg": require("../../assets/on-demand-thumbnails/w-010.jpg"),
  "w-011.jpg": require("../../assets/on-demand-thumbnails/w-011.jpg"),
  "w-012.jpg": require("../../assets/on-demand-thumbnails/w-012.jpg"),
  "w-013.jpg": require("../../assets/on-demand-thumbnails/w-013.jpg"),
  "w-014.jpg": require("../../assets/on-demand-thumbnails/w-014.jpg"),
  "w-015.jpg": require("../../assets/on-demand-thumbnails/w-015.jpg"),
  "w-016.jpg": require("../../assets/on-demand-thumbnails/w-016.jpg"),
  "w-017.jpg": require("../../assets/on-demand-thumbnails/w-017.jpg"),
  "w-018.jpg": require("../../assets/on-demand-thumbnails/w-018.jpg"),
  "w-019.jpg": require("../../assets/on-demand-thumbnails/w-019.jpg"),
  "w-020.jpg": require("../../assets/on-demand-thumbnails/w-020.jpg"),
  "w-021.jpg": require("../../assets/on-demand-thumbnails/w-021.jpg"),
  "w-022.jpg": require("../../assets/on-demand-thumbnails/w-022.jpg"),
  "w-023.jpg": require("../../assets/on-demand-thumbnails/w-023.jpg"),
  "w-024.jpg": require("../../assets/on-demand-thumbnails/w-024.jpg"),
  "w-025.jpg": require("../../assets/on-demand-thumbnails/w-025.jpg"),
  "w-026.jpg": require("../../assets/on-demand-thumbnails/w-026.jpg"),
  "w-027.jpg": require("../../assets/on-demand-thumbnails/w-027.jpg"),
  "w-028.jpg": require("../../assets/on-demand-thumbnails/w-028.jpg"),
  "w-029.jpg": require("../../assets/on-demand-thumbnails/w-029.jpg"),
  "w-030.jpg": require("../../assets/on-demand-thumbnails/w-030.jpg"),
  "w-031.jpg": require("../../assets/on-demand-thumbnails/w-031.jpg"),
  "w-032.jpg": require("../../assets/on-demand-thumbnails/w-032.jpg"),
  "w-033.jpg": require("../../assets/on-demand-thumbnails/w-033.jpg"),
  "w-034.jpg": require("../../assets/on-demand-thumbnails/w-034.jpg"),
  "w-035.jpg": require("../../assets/on-demand-thumbnails/w-035.jpg"),
  "w-036.jpg": require("../../assets/on-demand-thumbnails/w-036.jpg"),
  "w-037.jpg": require("../../assets/on-demand-thumbnails/w-037.jpg"),
  "w-038.jpg": require("../../assets/on-demand-thumbnails/w-038.jpg"),
  "w-039.jpg": require("../../assets/on-demand-thumbnails/w-039.jpg"),
  "w-040.jpg": require("../../assets/on-demand-thumbnails/w-040.jpg"),
  "w-041.jpg": require("../../assets/on-demand-thumbnails/w-041.jpg"),
  "w-042.jpg": require("../../assets/on-demand-thumbnails/w-042.jpg"),
  "w-043.jpg": require("../../assets/on-demand-thumbnails/w-043.jpg"),
  "w-044.jpg": require("../../assets/on-demand-thumbnails/w-044.jpg"),
  "w-045.jpg": require("../../assets/on-demand-thumbnails/w-045.jpg"),
  "w-046.jpg": require("../../assets/on-demand-thumbnails/w-046.jpg"),
  "w-047.jpg": require("../../assets/on-demand-thumbnails/w-047.jpg"),
  "w-048.jpg": require("../../assets/on-demand-thumbnails/w-048.jpg"),
  "w-049.jpg": require("../../assets/on-demand-thumbnails/w-049.jpg"),
  "w-050.jpg": require("../../assets/on-demand-thumbnails/w-050.jpg"),
  "w-051.jpg": require("../../assets/on-demand-thumbnails/w-051.jpg"),
  "w-052.jpg": require("../../assets/on-demand-thumbnails/w-052.jpg"),
  "w-053.jpg": require("../../assets/on-demand-thumbnails/w-053.jpg"),
  "w-054.jpg": require("../../assets/on-demand-thumbnails/w-054.jpg"),
  "w-055.jpg": require("../../assets/on-demand-thumbnails/w-055.jpg"),
  "w-056.jpg": require("../../assets/on-demand-thumbnails/w-056.jpg"),
  "w-057.jpg": require("../../assets/on-demand-thumbnails/w-057.jpg"),
  "w-058.jpg": require("../../assets/on-demand-thumbnails/w-058.jpg"),
  "w-059.jpg": require("../../assets/on-demand-thumbnails/w-059.jpg"),
  "w-060.jpg": require("../../assets/on-demand-thumbnails/w-060.jpg"),
  "w-061.jpg": require("../../assets/on-demand-thumbnails/w-061.jpg"),
  "w-062.jpg": require("../../assets/on-demand-thumbnails/w-062.jpg"),
  "w-063.jpg": require("../../assets/on-demand-thumbnails/w-063.jpg"),
  "w-064.jpg": require("../../assets/on-demand-thumbnails/w-064.jpg"),
  "w-065.jpg": require("../../assets/on-demand-thumbnails/w-065.jpg"),
  "w-066.jpg": require("../../assets/on-demand-thumbnails/w-066.jpg"),
  "w-067.jpg": require("../../assets/on-demand-thumbnails/w-067.jpg"),
  "w-068.jpg": require("../../assets/on-demand-thumbnails/w-068.jpg"),
  "w-069.jpg": require("../../assets/on-demand-thumbnails/w-069.jpg"),
  "w-070.jpg": require("../../assets/on-demand-thumbnails/w-070.jpg"),
  "w-071.jpg": require("../../assets/on-demand-thumbnails/w-071.jpg"),
  "w-072.jpg": require("../../assets/on-demand-thumbnails/w-072.jpg"),
  "w-073.jpg": require("../../assets/on-demand-thumbnails/w-073.jpg"),
  "w-074.jpg": require("../../assets/on-demand-thumbnails/w-074.jpg"),
  "w-075.jpg": require("../../assets/on-demand-thumbnails/w-075.jpg"),
  "w-076.jpg": require("../../assets/on-demand-thumbnails/w-076.jpg"),
  "w-077.jpg": require("../../assets/on-demand-thumbnails/w-077.jpg"),
  "w-078.jpg": require("../../assets/on-demand-thumbnails/w-078.jpg"),
  "w-079.jpg": require("../../assets/on-demand-thumbnails/w-079.jpg"),
  "w-080.jpg": require("../../assets/on-demand-thumbnails/w-080.jpg"),
  "w-081.jpg": require("../../assets/on-demand-thumbnails/w-081.jpg"),
  "w-082.jpg": require("../../assets/on-demand-thumbnails/w-082.jpg"),
  "w-083.jpg": require("../../assets/on-demand-thumbnails/w-083.jpg"),
  "w-084.jpg": require("../../assets/on-demand-thumbnails/w-084.jpg"),
  "w-085.jpg": require("../../assets/on-demand-thumbnails/w-085.jpg"),
  "w-086.jpg": require("../../assets/on-demand-thumbnails/w-086.jpg"),
  "w-087.jpg": require("../../assets/on-demand-thumbnails/w-087.jpg"),
  "w-088.jpg": require("../../assets/on-demand-thumbnails/w-088.jpg"),
  "w-089.jpg": require("../../assets/on-demand-thumbnails/w-089.jpg"),
  "w-090.jpg": require("../../assets/on-demand-thumbnails/w-090.jpg"),
  "w-091.jpg": require("../../assets/on-demand-thumbnails/w-091.jpg"),
  "w-092.jpg": require("../../assets/on-demand-thumbnails/w-092.jpg"),
  "w-093.jpg": require("../../assets/on-demand-thumbnails/w-093.jpg"),
  "w-094.jpg": require("../../assets/on-demand-thumbnails/w-094.jpg"),
  "w-095.jpg": require("../../assets/on-demand-thumbnails/w-095.jpg"),
  "w-096.jpg": require("../../assets/on-demand-thumbnails/w-096.jpg"),
  "w-097.jpg": require("../../assets/on-demand-thumbnails/w-097.jpg"),
  "w-098.jpg": require("../../assets/on-demand-thumbnails/w-098.jpg"),
  "w-099.jpg": require("../../assets/on-demand-thumbnails/w-099.jpg"),
  "w-100.jpg": require("../../assets/on-demand-thumbnails/w-100.jpg"),
  "w-101.jpg": require("../../assets/on-demand-thumbnails/w-101.jpg"),
  "w-102.jpg": require("../../assets/on-demand-thumbnails/w-102.jpg"),
  "w-103.jpg": require("../../assets/on-demand-thumbnails/w-103.jpg"),
};

export function resolveThumbnail(filename?: string | null): ImageSourcePropType | null {
  if (!filename) return null;
  return map[filename] || null;
}

export const THUMBNAIL_COUNT = 103;

