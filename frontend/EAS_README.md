# EAS build notes — CrewFit

## Versioning rule (READ BEFORE EDITING `eas.json`)

`versionCode` is managed in **`app.json`** under `expo.android.versionCode` (currently `300`).

`eas.json` has `cli.appVersionSource: "local"` and `build.production.autoIncrement: false`. Together these force EAS to read the version from `app.json` rather than bumping it remotely.

### If Play Console rejects with "Version code X already used"

- **DO:** bump `expo.android.versionCode` in `app.json` (e.g. `300` → `301`).
- **DO NOT:** re-enable `autoIncrement`. That will silently start incrementing on EAS's server and desync from `app.json`, leading to the same collision later on.

### Do NOT add a `_comment` field to `eas.json`

The EAS schema doesn't allow custom top-level fields. Adding `"_comment": "..."` at the top of `eas.json` causes the EAS validation step to fail and blocks the entire Publish pipeline (visible in Emergent as a stuck / collapsed deploy panel).

Keep any notes here in this README, not in the JSON itself.
