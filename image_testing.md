# Image Integration Testing Playbook

## TEST AGENT PROMPT – IMAGE INTEGRATION RULES

Follow these rules exactly when testing any endpoint that accepts an image.

### Image Handling Rules
- Always use **base64-encoded** images for all tests and requests.
- Accepted formats: **JPEG, PNG, WEBP** only.
- Do not use SVG, BMP, HEIC, or other formats.
- Do not upload blank, solid-color, or uniform-variance images.
- Every image must contain **real visual features** — objects, edges, textures, or shadows.
- If the image is not PNG/JPEG/WEBP, transcode to PNG or JPEG before upload.
  - After transformation, re-detect and update the MIME type.
- If the image is animated (GIF, APNG, WEBP animation), extract the **first frame only**.
- Resize large images to reasonable bounds (avoid oversized payloads).

### Test images to use for Nutrition Photo Scan
Any real photo of a plated meal will do. Test the following flows:
1. A recognisable meal (e.g., chicken + rice + broccoli) — expect items detected, kcal ≥ 200.
2. A hotel buffet plate (multiple items on one plate) — with `mode:"hotel_buffet"` flag.
3. A pastry / high-fat food — Atlas tip should mention protein or timing.
4. Confirm response is always framed as an **estimate** ("Atlas has estimated…").
