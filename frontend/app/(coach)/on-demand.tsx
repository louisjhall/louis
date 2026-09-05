/**
 * Coach · On Demand — Stage 1 management screen.
 *
 * Foundation-only:
 *   • List all On Demand items with filters (type + published state).
 *   • Create / edit / delete items across the three content types
 *     (workout · video · audio).
 *   • Manage the shared category + tag taxonomy.
 *   • Toggle publish state per item.
 *
 * No member-facing browse UI, no premium gating, no analytics — those
 * land in Stage 2. Everything here writes through the new
 * `/api/on-demand/*` endpoints; nothing shares state with the existing
 * workout / programme / library screens.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, Pressable, TextInput, ScrollView, StyleSheet,
  ActivityIndicator, Modal, Alert, Image, Switch, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import * as DocumentPicker from "expo-document-picker";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";
import { useBottomSafePad } from "@/src/lib/useBottomSafePad";
import { confirm as uxConfirm } from "@/src/lib/ux";
import { BulkImportOnDemandModal } from "@/src/components/BulkImportOnDemandModal";

/* ---------------------------------------------------------------------- */
/* Types                                                                   */
/* ---------------------------------------------------------------------- */

type ContentType = "workout" | "video" | "audio";

type Category = { id: string; name: string; slug: string };
type Tag      = { id: string; name: string; slug: string };

type Item = {
  id: string;
  title: string;
  description?: string;
  content_type: ContentType;
  category_id: string | null;
  tag_ids: string[];
  duration_seconds: number | null;
  thumbnail_storage_key?: string | null;
  media_storage_key?: string | null;
  media_mime?: string | null;
  media_size_bytes?: number | null;
  published: boolean;
  created_at: string;
  updated_at: string;
};

type MediaPayload = { file_b64: string; file_mime?: string; file_name?: string };

type EditorState = {
  mode: "create" | "edit";
  item?: Item;
  title: string;
  description: string;
  content_type: ContentType;
  category_id: string | null;
  tag_ids: string[];
  duration_seconds: string;      // string in the input, coerced on save
  published: boolean;
  thumbnail?: MediaPayload;
  thumbnailPreviewUri?: string;
  media?: MediaPayload;
  mediaFileLabel?: string;       // "workout.mp4 (12 KB)" or filename — video/audio only now
  workout_json?: any;
  workoutJsonText?: string;      // raw paste buffer (workout content only)
  workoutJsonError?: string | null;
  workoutJsonAutoNote?: string | null;   // "Auto-populated title, duration, category" etc.
};

/* ---------------------------------------------------------------------- */
/* Screen                                                                  */
/* ---------------------------------------------------------------------- */

export default function CoachOnDemandScreen() {
  const bottomPad = useBottomSafePad();

  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState<Item[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);

  const [filterType, setFilterType] = useState<"all" | ContentType>("all");
  const [filterPublished, setFilterPublished] = useState<"all" | "published" | "draft">("all");

  const [editor, setEditor] = useState<EditorState | null>(null);
  const [taxonomyOpen, setTaxonomyOpen] = useState(false);
  const [bulkImportOpen, setBulkImportOpen] = useState(false);
  // Iter193 · Currently-pinned featured item (or null when nothing pinned).
  const [featuredId, setFeaturedId] = useState<string | null>(null);
  // Iter200 · Presigned R2 thumbnail URLs, resolved lazily per visible row.
  // Keyed by item id. Never fetched for items that don't carry a
  // `thumbnail_storage_key`, so the ItemRow falls back to its icon glyph
  // for video/audio uploads (which are still icon-only by design).
  const [thumbUrls, setThumbUrls] = useState<Record<string, string>>({});

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [it, cats, tgs, feat] = await Promise.all([
        api<{ items: Item[] }>("/on-demand/coach/items"),
        api<{ categories: Category[] }>("/on-demand/categories"),
        api<{ tags: Tag[] }>("/on-demand/tags"),
        api<{ item: any }>("/on-demand/featured").catch(() => ({ item: null })),
      ]);
      setItems(it.items || []);
      setCategories(cats.categories || []);
      setTags(tgs.tags || []);
      setFeaturedId(feat?.item?.id || null);
    } catch (e: any) {
      Alert.alert("Failed to load", e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  /** Pin or unpin an item as this week's featured card. Only one item can be
      featured at a time — pinning a new one replaces the previous. */
  const toggleFeatured = useCallback(async (it: Item) => {
    const nextId = featuredId === it.id ? null : it.id;
    // Optimistic — flip immediately so the star updates without a round-trip.
    setFeaturedId(nextId);
    try {
      await api("/on-demand/coach/featured", { method: "PUT", body: { item_id: nextId } });
    } catch (e: any) {
      // Roll back on failure.
      setFeaturedId(featuredId);
      Alert.alert("Featured update failed", e?.message || String(e));
    }
  }, [featuredId]);

  const filtered = useMemo(() => items.filter((i) => {
    if (filterType !== "all" && i.content_type !== filterType) return false;
    if (filterPublished === "published" && !i.published) return false;
    if (filterPublished === "draft" && i.published) return false;
    return true;
  }), [items, filterType, filterPublished]);

  // Iter200 · Lazily fetch a presigned R2 URL for every filtered item that
  // has a `thumbnail_storage_key` but hasn't been resolved yet. We don't
  // block the render on this — the row keeps its icon fallback until the
  // URL arrives. Failures are swallowed per-row (network hiccup on ONE
  // signed URL shouldn't wipe out the whole list).
  useEffect(() => {
    const missing = filtered.filter(
      (it) => it.thumbnail_storage_key && !thumbUrls[it.id],
    );
    if (missing.length === 0) return;
    let cancelled = false;
    (async () => {
      const next: Record<string, string> = {};
      for (const it of missing) {
        try {
          const r = await api<{ url: string }>(`/on-demand/items/${it.id}/thumbnail-url`);
          if (r?.url) next[it.id] = r.url;
        } catch { /* per-row failure — keep icon fallback */ }
      }
      if (!cancelled && Object.keys(next).length > 0) {
        setThumbUrls((prev) => ({ ...prev, ...next }));
      }
    })();
    return () => { cancelled = true; };
  }, [filtered, thumbUrls]);

  /* --- Editor open helpers --- */
  const openCreate = () => setEditor({
    mode: "create",
    title: "",
    description: "",
    content_type: "workout",
    category_id: null,
    tag_ids: [],
    duration_seconds: "",
    published: false,
  });

  const openEdit = async (id: string) => {
    try {
      const r = await api<{ item: any }>(`/on-demand/coach/items/${id}`);
      const it = r.item as Item & { workout_json?: any };
      setEditor({
        mode: "edit",
        item: it,
        title: it.title,
        description: it.description || "",
        content_type: it.content_type,
        category_id: it.category_id || null,
        tag_ids: it.tag_ids || [],
        duration_seconds: it.duration_seconds != null ? String(it.duration_seconds) : "",
        published: it.published,
        workout_json: it.workout_json,
        // For workouts: seed the paste area with the current JSON so the coach
        // can edit it in-place. For video/audio: keep the "media (loaded)"
        // label so they know a file is already attached.
        workoutJsonText: it.content_type === "workout" && it.workout_json
          ? safeStringify(it.workout_json)
          : undefined,
        workoutJsonError: null,
        workoutJsonAutoNote: null,
        mediaFileLabel: it.content_type === "workout"
          ? undefined
          : (it.media_storage_key ? "media (loaded)" : undefined),
      });
    } catch (e: any) {
      Alert.alert("Failed to open", e?.message || String(e));
    }
  };

  const togglePublish = async (it: Item) => {
    try {
      await api(`/on-demand/coach/items/${it.id}/publish`, {
        method: "POST",
        body: { published: !it.published },
      });
      setItems((rows) => rows.map((r) => r.id === it.id ? { ...r, published: !it.published } : r));
    } catch (e: any) {
      Alert.alert("Publish failed", e?.message || String(e));
    }
  };

  const deleteItem = (it: Item) => {
    // Iter200 · Use the cross-platform `confirm()` helper — React-Native-Web
    // 0.21's `Alert.alert(title, msg, buttons)` renders no buttons on WEB,
    // so the destructive callback never fired and the bin button appeared
    // to do nothing on the coach dashboard (which runs on web via
    // DesktopShell). `confirm()` falls back to a real modal / native alert.
    (async () => {
      const ok = await uxConfirm({
        title: "Delete item?",
        message: `"${it.title}" will be removed permanently.`,
        confirmLabel: "Delete",
        cancelLabel: "Cancel",
        destructive: true,
      });
      if (!ok) return;
      try {
        await api(`/on-demand/coach/items/${it.id}`, { method: "DELETE" });
        setItems((rows) => rows.filter((r) => r.id !== it.id));
      } catch (e: any) {
        Alert.alert("Delete failed", e?.message || String(e));
      }
    })();
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>ON DEMAND</Text>
          <Text style={styles.subtitle}>Coach content library · Stage 1</Text>
        </View>
        <Pressable
          onPress={() => setTaxonomyOpen(true)}
          style={styles.headerBtn}
          testID="od-manage-taxonomy"
        >
          <Ionicons name="pricetags-outline" size={16} color={theme.color.text} />
          <Text style={styles.headerBtnText}>TAXONOMY</Text>
        </Pressable>
        <Pressable
          onPress={() => setBulkImportOpen(true)}
          style={styles.headerBtn}
          testID="od-bulk-import-open"
        >
          <Ionicons name="cloud-upload-outline" size={16} color={theme.color.text} />
          <Text style={styles.headerBtnText}>BULK IMPORT</Text>
        </Pressable>
        <Pressable
          onPress={openCreate}
          style={[styles.headerBtn, styles.headerBtnPrimary]}
          testID="od-create-item"
        >
          <Ionicons name="add" size={18} color="#fff" />
          <Text style={[styles.headerBtnText, { color: "#fff" }]}>NEW</Text>
        </Pressable>
      </View>

      {/* Filters */}
      <View style={styles.filterRow}>
        <FilterChip
          label="ALL"           active={filterType === "all"}      onPress={() => setFilterType("all")} />
        <FilterChip
          label="WORKOUTS"      active={filterType === "workout"}  onPress={() => setFilterType("workout")} />
        <FilterChip
          label="VIDEOS"        active={filterType === "video"}    onPress={() => setFilterType("video")} />
        <FilterChip
          label="AUDIO"         active={filterType === "audio"}    onPress={() => setFilterType("audio")} />
        <View style={{ flex: 1 }} />
        <FilterChip
          label={filterPublished === "all" ? "STATE: ALL"
               : filterPublished === "published" ? "PUBLISHED" : "DRAFTS"}
          active
          onPress={() => setFilterPublished((s) =>
            s === "all" ? "published" : s === "published" ? "draft" : "all"
          )}
        />
      </View>

      {loading ? (
        <View style={styles.centerFill}>
          <ActivityIndicator color={theme.color.brand} />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={{ paddingBottom: bottomPad + 24, paddingHorizontal: 16, paddingTop: 8 }}
        >
          {filtered.length === 0 ? (
            <View style={styles.emptyBox} testID="od-empty">
              <Ionicons name="albums-outline" size={38} color={theme.color.brand} />
              <Text style={styles.emptyTitle}>No items yet</Text>
              <Text style={styles.emptyBody}>
                Tap NEW to add your first workout, video or audio piece.
                Nothing is visible to clients until you publish it.
              </Text>
            </View>
          ) : (
            filtered.map((it) => (
              <ItemRow
                key={it.id}
                item={it}
                categoryName={categories.find((c) => c.id === it.category_id)?.name || null}
                isFeatured={featuredId === it.id}
                thumbUrl={thumbUrls[it.id]}
                onEdit={() => openEdit(it.id)}
                onPublish={() => togglePublish(it)}
                onFeature={() => toggleFeatured(it)}
                onDelete={() => deleteItem(it)}
              />
            ))
          )}
        </ScrollView>
      )}

      {editor ? (
        <ItemEditorModal
          state={editor}
          categories={categories}
          tags={tags}
          onClose={() => setEditor(null)}
          onSaved={() => { setEditor(null); reload(); }}
        />
      ) : null}

      {taxonomyOpen ? (
        <TaxonomyModal
          categories={categories}
          tags={tags}
          onClose={() => { setTaxonomyOpen(false); reload(); }}
        />
      ) : null}

      {bulkImportOpen ? (
        <BulkImportOnDemandModal
          onClose={() => setBulkImportOpen(false)}
          onImported={() => { setBulkImportOpen(false); reload(); }}
        />
      ) : null}
    </SafeAreaView>
  );
}

/* ---------------------------------------------------------------------- */
/* Item row                                                                */
/* ---------------------------------------------------------------------- */

function ItemRow({
  item, categoryName, isFeatured, thumbUrl, onEdit, onPublish, onFeature, onDelete,
}: {
  item: Item;
  categoryName: string | null;
  isFeatured: boolean;
  thumbUrl?: string;
  onEdit: () => void;
  onPublish: () => void;
  onFeature: () => void;
  onDelete: () => void;
}) {
  const icon: any = item.content_type === "workout" ? "barbell-outline"
                  : item.content_type === "video"   ? "videocam-outline"
                  : "headset-outline";
  const durMin = item.duration_seconds ? Math.round(item.duration_seconds / 60) : null;
  return (
    <View style={styles.row} testID={`od-item-${item.id}`}>
      <View style={styles.rowIconBox}>
        {thumbUrl ? (
          <Image
            source={{ uri: thumbUrl }}
            style={styles.rowThumb}
            testID={`od-thumb-${item.id}`}
          />
        ) : (
          <Ionicons name={icon} size={22} color={theme.color.brand} />
        )}
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.rowTitle} numberOfLines={2}>{item.title}</Text>
        <View style={styles.rowMetaLine}>
          <Text style={styles.rowMeta}>{item.content_type.toUpperCase()}</Text>
          {categoryName ? <Text style={styles.rowMeta}> · {categoryName}</Text> : null}
          {durMin != null ? <Text style={styles.rowMeta}> · {durMin} min</Text> : null}
          {isFeatured ? <Text style={[styles.rowMeta, { color: theme.color.brand, fontWeight: "800" }]}> · ★ FEATURED</Text> : null}
        </View>
      </View>
      <Pressable onPress={onPublish} style={[styles.pubPill, item.published ? styles.pubPillOn : styles.pubPillOff]}>
        <Text style={[styles.pubPillText, item.published ? { color: "#fff" } : { color: theme.color.textDim }]}>
          {item.published ? "LIVE" : "DRAFT"}
        </Text>
      </Pressable>
      <Pressable
        onPress={onFeature}
        hitSlop={8}
        style={styles.iconBtn}
        testID={`od-feature-${item.id}`}
        accessibilityLabel={isFeatured ? "Unpin from Today" : "Pin to Today"}
      >
        <Ionicons
          name={isFeatured ? "star" : "star-outline"}
          size={20}
          color={isFeatured ? theme.color.brand : theme.color.text}
        />
      </Pressable>
      <Pressable onPress={onEdit} hitSlop={8} style={styles.iconBtn} testID={`od-edit-${item.id}`}>
        <Ionicons name="create-outline" size={20} color={theme.color.text} />
      </Pressable>
      <Pressable onPress={onDelete} hitSlop={8} style={styles.iconBtn} testID={`od-delete-${item.id}`}>
        <Ionicons name="trash-outline" size={20} color={theme.color.brand} />
      </Pressable>
    </View>
  );
}

/* ---------------------------------------------------------------------- */
/* Filter chip                                                             */
/* ---------------------------------------------------------------------- */

function FilterChip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      style={[styles.chip, active && styles.chipActive]}
      testID={`od-filter-${label.toLowerCase().replace(/[^a-z]+/g, "-")}`}
    >
      <Text style={[styles.chipText, active && styles.chipTextActive]}>{label}</Text>
    </Pressable>
  );
}

/* ---------------------------------------------------------------------- */
/* Editor modal                                                            */
/* ---------------------------------------------------------------------- */

function ItemEditorModal({
  state: initial, categories, tags, onClose, onSaved,
}: {
  state: EditorState;
  categories: Category[];
  tags: Tag[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const bottomPad = useBottomSafePad();
  const [state, setState] = useState<EditorState>(initial);
  const [saving, setSaving] = useState(false);

  const setField = <K extends keyof EditorState>(k: K, v: EditorState[K]) => setState((s) => ({ ...s, [k]: v }));

  const pickThumbnail = async () => {
    try {
      const res = await DocumentPicker.getDocumentAsync({ type: "image/*", copyToCacheDirectory: true });
      if (res.canceled) return;
      const a = res.assets[0];
      // Iter195 · Cross-platform base64 read. `FileSystem.readAsStringAsync`
      // on WEB (where the coach dashboard runs in production via
      // DesktopShell) does not reliably read the blob URIs that
      // `DocumentPicker` returns — it silently produces an empty string,
      // so we were uploading 0-byte thumbnails to R2. The
      // fetch → blob → FileReader.readAsDataURL pattern works on native
      // AND web (see CrewBaseComposer / videos.tsx for the same helper).
      const b64 = await fileUriToBase64(a.uri);
      if (!b64) {
        Alert.alert("Pick failed", "Could not read the selected image. Please try a different file.");
        return;
      }
      const mime = a.mimeType || "image/jpeg";
      setField("thumbnail", { file_b64: b64, file_mime: mime, file_name: a.name });
      setField("thumbnailPreviewUri", a.uri);
    } catch (e: any) {
      Alert.alert("Pick failed", e?.message || String(e));
    }
  };

  const pickMedia = async () => {
    // Iter192 · Workout content is now paste-only (see `handleWorkoutJsonPaste`
    // below). This function only handles video / audio.
    const isVideo = state.content_type === "video";
    const type = isVideo ? "video/*" : "audio/*";
    try {
      const res = await DocumentPicker.getDocumentAsync({ type, copyToCacheDirectory: true });
      if (res.canceled) return;
      const a = res.assets[0];
      // Iter200 · Use the same web-safe helper as pickThumbnail — plain
      // `FileSystem.readAsStringAsync` on WEB silently returns empty for
      // the blob URIs DocumentPicker hands back, so we were uploading
      // 0-byte media files to R2. `fileUriToBase64` uses the
      // fetch → blob → FileReader.readAsDataURL pattern that works on
      // both native and web.
      const b64 = await fileUriToBase64(a.uri);
      if (!b64) {
        Alert.alert(
          "Pick failed",
          `Could not read the selected ${isVideo ? "video" : "audio"} file. Please try a different file.`,
        );
        return;
      }
      setField("media", { file_b64: b64, file_mime: a.mimeType || (isVideo ? "video/mp4" : "audio/mpeg"), file_name: a.name });
      setField("mediaFileLabel", `${a.name} (${prettySize(a.size)})`);
    } catch (e: any) {
      Alert.alert("Pick failed", e?.message || String(e));
    }
  };

  /**
   * Handle the coach pasting/typing workout JSON into the textarea.
   *
   * Behaviour (matches the "same way workout JSON is handled elsewhere"
   * requirement — see `/app/(coach)/coach/client/[id]/import.tsx`):
   *
   *  • Always update the text buffer so what the coach sees is what they
   *    typed — no reformatting.
   *  • Empty text → clear the parsed payload + errors + auto-note.
   *  • Try `JSON.parse`. If it fails, keep the last valid `workout_json`
   *    intact (they may still save it) but surface the parse error inline.
   *  • On successful parse, unwrap the envelope shape (`{ workouts: [w0, ...] }`)
   *    and pull field candidates out of the FIRST workout — same convention
   *    the programme-import flow uses.
   *  • Auto-populate `title`, `description`, `duration_seconds`, and
   *    `category_id` (by fuzzy-matching workout_type/category against the
   *    coach's own category list). Every populated field can still be
   *    edited manually afterwards.
   */
  const handleWorkoutJsonPaste = (raw: string) => {
    setState((s) => {
      const next: EditorState = { ...s, workoutJsonText: raw };
      const trimmed = raw.trim();
      if (!trimmed) {
        next.workout_json = undefined;
        next.workoutJsonError = null;
        next.workoutJsonAutoNote = null;
        return next;
      }
      let parsed: any;
      try {
        parsed = JSON.parse(trimmed);
      } catch (e: any) {
        next.workoutJsonError = `Invalid JSON — ${e?.message || String(e)}`;
        return next;
      }
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        next.workoutJsonError = "Expected a JSON object at the top level.";
        return next;
      }
      next.workout_json = parsed;
      next.workoutJsonError = null;

      const extracted = extractWorkoutJsonFields(parsed);
      const notes: string[] = [];

      if (typeof extracted.title === "string" && extracted.title.trim()) {
        next.title = extracted.title.trim();
        notes.push("title");
      }
      if (typeof extracted.description === "string" && extracted.description.trim()) {
        next.description = extracted.description.trim();
        notes.push("description");
      }
      if (typeof extracted.duration_seconds === "number" && extracted.duration_seconds >= 0) {
        next.duration_seconds = String(Math.round(extracted.duration_seconds));
        notes.push("duration");
      }
      if (extracted.category_hint) {
        const hint = extracted.category_hint.trim().toLowerCase();
        const match = categories.find(
          (c) => c.name.toLowerCase() === hint || c.slug === hint,
        );
        if (match) {
          next.category_id = match.id;
          notes.push("category");
        }
      }

      next.workoutJsonAutoNote = notes.length
        ? `Auto-populated: ${notes.join(", ")}. Override any field as needed.`
        : null;
      return next;
    });
  };

  const toggleTag = (tagId: string) => {
    setField("tag_ids", state.tag_ids.includes(tagId)
      ? state.tag_ids.filter((t) => t !== tagId)
      : [...state.tag_ids, tagId]);
  };

  const save = async () => {
    if (!state.title.trim()) { Alert.alert("Title required"); return; }
    if (state.mode === "create") {
      if (state.content_type === "workout" && !state.workout_json) {
        Alert.alert("Workout JSON required", "Paste a valid workout JSON in the text box below.");
        return;
      }
      if (state.content_type !== "workout" && !state.media?.file_b64) {
        Alert.alert(`${state.content_type === "video" ? "Video" : "Audio"} file required`);
        return;
      }
    }
    if (state.content_type === "workout" && state.workoutJsonError) {
      Alert.alert("Fix JSON first", state.workoutJsonError);
      return;
    }
    setSaving(true);
    try {
      const payload: any = {
        title: state.title.trim(),
        description: state.description.trim(),
        content_type: state.content_type,
        category_id: state.category_id,
        tag_ids: state.tag_ids,
        duration_seconds: state.duration_seconds ? Number(state.duration_seconds) : null,
        published: state.published,
      };
      if (state.thumbnail) payload.thumbnail = state.thumbnail;
      if (state.media) payload.media = state.media;
      if (state.workout_json) payload.workout_json = state.workout_json;

      if (state.mode === "create") {
        await api("/on-demand/coach/items", { method: "POST", body: payload });
      } else if (state.item) {
        // Editing: content_type is immutable server-side; don't send it back.
        delete payload.content_type;
        await api(`/on-demand/coach/items/${state.item.id}`, { method: "PATCH", body: payload });
      }
      onSaved();
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || String(e));
    } finally {
      setSaving(false);
    }
  };

  const typeLocked = state.mode === "edit";

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.modalScrim}>
        <View style={styles.modalCard}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>{state.mode === "create" ? "New item" : "Edit item"}</Text>
            <Pressable onPress={onClose} hitSlop={10} testID="od-editor-close">
              <Ionicons name="close" size={24} color={theme.color.text} />
            </Pressable>
          </View>

          <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: bottomPad + 100 }}>
            {/* Content type */}
            <Text style={styles.label}>CONTENT TYPE</Text>
            <View style={styles.segRow}>
              {(["workout", "video", "audio"] as ContentType[]).map((t) => (
                <Pressable
                  key={t}
                  disabled={typeLocked}
                  onPress={() => setField("content_type", t)}
                  style={[
                    styles.segBtn,
                    state.content_type === t && styles.segBtnActive,
                    typeLocked && { opacity: 0.5 },
                  ]}
                  testID={`od-type-${t}`}
                >
                  <Text style={[styles.segText, state.content_type === t && styles.segTextActive]}>
                    {t.toUpperCase()}
                  </Text>
                </Pressable>
              ))}
            </View>
            {typeLocked ? (
              <Text style={styles.hint}>Content type is fixed after creation.</Text>
            ) : null}

            {/* Title / description */}
            <Text style={styles.label}>TITLE</Text>
            <TextInput
              style={styles.input}
              value={state.title}
              onChangeText={(v) => setField("title", v)}
              placeholder="e.g. Layover Hotel Mobility"
              placeholderTextColor={theme.color.textDim}
              testID="od-editor-title"
            />

            <Text style={styles.label}>DESCRIPTION</Text>
            <TextInput
              style={[styles.input, styles.textarea]}
              value={state.description}
              onChangeText={(v) => setField("description", v)}
              multiline
              numberOfLines={4}
              placeholder="Short blurb clients will see on the card"
              placeholderTextColor={theme.color.textDim}
              testID="od-editor-desc"
            />

            {/* Category */}
            <Text style={styles.label}>CATEGORY</Text>
            <View style={styles.chipsWrap}>
              <Pressable
                onPress={() => setField("category_id", null)}
                style={[styles.chip, state.category_id === null && styles.chipActive]}
              >
                <Text style={[styles.chipText, state.category_id === null && styles.chipTextActive]}>NONE</Text>
              </Pressable>
              {categories.map((c) => (
                <Pressable
                  key={c.id}
                  onPress={() => setField("category_id", c.id)}
                  style={[styles.chip, state.category_id === c.id && styles.chipActive]}
                >
                  <Text style={[styles.chipText, state.category_id === c.id && styles.chipTextActive]}>
                    {c.name}
                  </Text>
                </Pressable>
              ))}
              {categories.length === 0 ? (
                <Text style={styles.hint}>No categories yet — add some in TAXONOMY.</Text>
              ) : null}
            </View>

            {/* Tags */}
            <Text style={styles.label}>TAGS</Text>
            <View style={styles.chipsWrap}>
              {tags.map((t) => {
                const active = state.tag_ids.includes(t.id);
                return (
                  <Pressable
                    key={t.id}
                    onPress={() => toggleTag(t.id)}
                    style={[styles.chip, active && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, active && styles.chipTextActive]}>{t.name}</Text>
                  </Pressable>
                );
              })}
              {tags.length === 0 ? (
                <Text style={styles.hint}>No tags yet — add some in TAXONOMY.</Text>
              ) : null}
            </View>

            {/* Duration */}
            <Text style={styles.label}>DURATION (SECONDS)</Text>
            <TextInput
              style={styles.input}
              value={state.duration_seconds}
              onChangeText={(v) => setField("duration_seconds", v.replace(/[^0-9]/g, ""))}
              placeholder="Optional — e.g. 900 for 15 min"
              placeholderTextColor={theme.color.textDim}
              keyboardType="number-pad"
              testID="od-editor-duration"
            />

            {/* Thumbnail */}
            <Text style={styles.label}>THUMBNAIL</Text>
            <Pressable onPress={pickThumbnail} style={styles.pickerBtn} testID="od-editor-pick-thumb">
              {state.thumbnailPreviewUri ? (
                <Image source={{ uri: state.thumbnailPreviewUri }} style={styles.thumbPreview} />
              ) : (
                <>
                  <Ionicons name="image-outline" size={20} color={theme.color.brand} />
                  <Text style={styles.pickerBtnText}>Choose image</Text>
                </>
              )}
            </Pressable>

            {/* Media / workout JSON */}
            {state.content_type === "workout" ? (
              <>
                <Text style={styles.label}>WORKOUT JSON</Text>
                <TextInput
                  style={[styles.input, styles.jsonArea]}
                  value={state.workoutJsonText || ""}
                  onChangeText={handleWorkoutJsonPaste}
                  multiline
                  autoCapitalize="none"
                  autoCorrect={false}
                  spellCheck={false}
                  placeholder='Paste your workout JSON here, e.g. {"title":"Layover Mobility","duration_min":15,...}'
                  placeholderTextColor={theme.color.textDim}
                  testID="od-editor-workout-json"
                />
                {state.workoutJsonError ? (
                  <Text style={[styles.hint, { color: theme.color.brand }]}>{state.workoutJsonError}</Text>
                ) : state.workoutJsonAutoNote ? (
                  <Text style={[styles.hint, { color: theme.color.brand }]}>{state.workoutJsonAutoNote}</Text>
                ) : (
                  <Text style={styles.hint}>
                    Title, description, duration and category will be auto-filled from the JSON. You can override any field before saving.
                  </Text>
                )}
              </>
            ) : (
              <>
                <Text style={styles.label}>
                  {state.content_type === "video" ? "VIDEO FILE" : "AUDIO FILE"}
                </Text>
                <Pressable onPress={pickMedia} style={styles.pickerBtn} testID="od-editor-pick-media">
                  <Ionicons
                    name={state.content_type === "video" ? "videocam-outline" : "headset-outline"}
                    size={20} color={theme.color.brand}
                  />
                  <Text style={styles.pickerBtnText}>{state.mediaFileLabel || "Choose file"}</Text>
                </Pressable>
                {state.mode === "edit" && !state.media ? (
                  <Text style={styles.hint}>Leave blank to keep the existing file.</Text>
                ) : null}
              </>
            )}

            {/* Publish switch */}
            <View style={styles.pubRow}>
              <Text style={styles.label}>PUBLISHED</Text>
              <Switch
                value={state.published}
                onValueChange={(v) => setField("published", v)}
                testID="od-editor-publish-toggle"
              />
            </View>
          </ScrollView>

          <View style={[styles.modalFooter, { paddingBottom: bottomPad + 12 }]}>
            <Pressable onPress={onClose} style={styles.footerBtn} disabled={saving}>
              <Text style={styles.footerBtnText}>CANCEL</Text>
            </Pressable>
            <Pressable
              onPress={save}
              style={[styles.footerBtn, styles.footerBtnPrimary]}
              disabled={saving}
              testID="od-editor-save"
            >
              {saving ? <ActivityIndicator color="#fff" />
                      : <Text style={[styles.footerBtnText, { color: "#fff" }]}>SAVE</Text>}
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

/* ---------------------------------------------------------------------- */
/* Taxonomy modal — create/rename/delete categories + tags                 */
/* ---------------------------------------------------------------------- */

function TaxonomyModal({
  categories, tags, onClose,
}: { categories: Category[]; tags: Tag[]; onClose: () => void }) {
  const bottomPad = useBottomSafePad();
  const [cats, setCats] = useState(categories);
  const [tgs, setTgs] = useState(tags);
  const [newCat, setNewCat] = useState("");
  const [newTag, setNewTag] = useState("");
  const [busy, setBusy] = useState(false);

  const addCategory = async () => {
    if (!newCat.trim()) return;
    setBusy(true);
    try {
      const r = await api<{ category: Category }>("/on-demand/coach/categories", {
        method: "POST", body: { name: newCat.trim() },
      });
      if (!cats.find((c) => c.id === r.category.id)) setCats((s) => [...s, r.category]);
      setNewCat("");
    } catch (e: any) {
      Alert.alert("Add failed", e?.message || String(e));
    } finally { setBusy(false); }
  };

  const deleteCategory = (c: Category) => {
    Alert.alert("Delete category?", `"${c.name}" will be detached from all items.`, [
      { text: "Cancel", style: "cancel" },
      { text: "Delete", style: "destructive", onPress: async () => {
        try {
          await api(`/on-demand/coach/categories/${c.id}`, { method: "DELETE" });
          setCats((s) => s.filter((x) => x.id !== c.id));
        } catch (e: any) { Alert.alert("Delete failed", e?.message || String(e)); }
      }},
    ]);
  };

  const addTag = async () => {
    if (!newTag.trim()) return;
    setBusy(true);
    try {
      const r = await api<{ tag: Tag }>("/on-demand/coach/tags", {
        method: "POST", body: { name: newTag.trim() },
      });
      if (!tgs.find((t) => t.id === r.tag.id)) setTgs((s) => [...s, r.tag]);
      setNewTag("");
    } catch (e: any) {
      Alert.alert("Add failed", e?.message || String(e));
    } finally { setBusy(false); }
  };

  const deleteTag = (t: Tag) => {
    Alert.alert("Delete tag?", `"${t.name}" will be removed from all items.`, [
      { text: "Cancel", style: "cancel" },
      { text: "Delete", style: "destructive", onPress: async () => {
        try {
          await api(`/on-demand/coach/tags/${t.id}`, { method: "DELETE" });
          setTgs((s) => s.filter((x) => x.id !== t.id));
        } catch (e: any) { Alert.alert("Delete failed", e?.message || String(e)); }
      }},
    ]);
  };

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.modalScrim}>
        <View style={styles.modalCard}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Manage taxonomy</Text>
            <Pressable onPress={onClose} hitSlop={10} testID="od-taxonomy-close">
              <Ionicons name="close" size={24} color={theme.color.text} />
            </Pressable>
          </View>

          <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: bottomPad + 24 }}>
            {/* Categories */}
            <Text style={styles.sectionHeader}>CATEGORIES</Text>
            <View style={styles.addRow}>
              <TextInput
                style={[styles.input, { flex: 1, marginRight: 8 }]}
                value={newCat}
                onChangeText={setNewCat}
                placeholder="New category name"
                placeholderTextColor={theme.color.textDim}
                testID="od-tax-new-cat"
              />
              <Pressable onPress={addCategory} disabled={busy} style={styles.miniPrimary} testID="od-tax-add-cat">
                <Text style={{ color: "#fff", fontWeight: "800", letterSpacing: 1 }}>ADD</Text>
              </Pressable>
            </View>
            {cats.map((c) => (
              <View key={c.id} style={styles.taxRow}>
                <Text style={styles.taxRowName}>{c.name}</Text>
                <Pressable onPress={() => deleteCategory(c)} hitSlop={8} testID={`od-tax-del-cat-${c.id}`}>
                  <Ionicons name="trash-outline" size={18} color={theme.color.brand} />
                </Pressable>
              </View>
            ))}
            {cats.length === 0 ? <Text style={styles.hint}>No categories yet.</Text> : null}

            {/* Tags */}
            <Text style={[styles.sectionHeader, { marginTop: 22 }]}>TAGS</Text>
            <View style={styles.addRow}>
              <TextInput
                style={[styles.input, { flex: 1, marginRight: 8 }]}
                value={newTag}
                onChangeText={setNewTag}
                placeholder="New tag name"
                placeholderTextColor={theme.color.textDim}
                testID="od-tax-new-tag"
              />
              <Pressable onPress={addTag} disabled={busy} style={styles.miniPrimary} testID="od-tax-add-tag">
                <Text style={{ color: "#fff", fontWeight: "800", letterSpacing: 1 }}>ADD</Text>
              </Pressable>
            </View>
            {tgs.map((t) => (
              <View key={t.id} style={styles.taxRow}>
                <Text style={styles.taxRowName}>{t.name}</Text>
                <Pressable onPress={() => deleteTag(t)} hitSlop={8} testID={`od-tax-del-tag-${t.id}`}>
                  <Ionicons name="trash-outline" size={18} color={theme.color.brand} />
                </Pressable>
              </View>
            ))}
            {tgs.length === 0 ? <Text style={styles.hint}>No tags yet.</Text> : null}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

/* ---------------------------------------------------------------------- */
/* Helpers                                                                 */
/* ---------------------------------------------------------------------- */

function prettySize(bytes?: number | null) {
  if (!bytes || bytes <= 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Read a file URI (from DocumentPicker) into a pure base64 string.
 *
 * `FileSystem.readAsStringAsync` on WEB does NOT support the blob URIs
 * that DocumentPicker returns — it silently resolves to an empty
 * string, producing a 0-byte upload. The `fetch → blob → FileReader`
 * flow works on both native AND web because native runtime handlers
 * accept `file://` and `content://` URIs in `fetch`, and web accepts
 * `blob:` URIs. Mirrors the helper in `CrewBaseComposer.tsx`.
 */
async function fileUriToBase64(uri: string): Promise<string> {
  const res = await fetch(uri);
  const blob = await res.blob();
  return await new Promise<string>((resolve, reject) => {
    const r = new FileReader();
    r.onerror = () => reject(new Error("failed to read file"));
    r.onload = () => {
      const dataUri = String(r.result || "");
      const comma = dataUri.indexOf(",");
      resolve(comma >= 0 ? dataUri.slice(comma + 1) : dataUri);
    };
    r.readAsDataURL(blob);
  });
}

/**
 * Pretty-print a workout JSON object for the paste area. Falls back to a
 * raw string if the input somehow isn't serialisable.
 */
function safeStringify(obj: any): string {
  try { return JSON.stringify(obj, null, 2); }
  catch { return String(obj ?? ""); }
}

/**
 * Pull the fields we know about out of a workout JSON payload. Handles
 * two shapes seen across the app:
 *
 *   1. Envelope shape from the programme importer:
 *          { "$schema": "...", "meta": {...}, "workouts": [ {...}, ... ] }
 *      → we take `workouts[0]` as the source workout.
 *   2. A single workout object:
 *          { "title": "...", "duration_min": 15, "workout_type": "...", ... }
 *
 * Returned fields:
 *   • title            — from `.title`
 *   • description      — from `.description` or `.coach_notes`
 *   • duration_seconds — from `.duration_seconds` OR `.duration_sec` OR
 *                        `.duration_min * 60` OR `.duration * 60` (only if
 *                        the raw `.duration` looks like minutes, i.e. < 300)
 *   • category_hint    — from `.category` OR `.workout_type` (fuzzy-match
 *                        against the coach's category list by the caller)
 */
function extractWorkoutJsonFields(obj: any): {
  title?: string;
  description?: string;
  duration_seconds?: number;
  category_hint?: string;
} {
  if (!obj || typeof obj !== "object") return {};
  const wk = Array.isArray(obj?.workouts) && obj.workouts.length > 0 ? obj.workouts[0] : obj;
  if (!wk || typeof wk !== "object") return {};

  const out: {
    title?: string;
    description?: string;
    duration_seconds?: number;
    category_hint?: string;
  } = {};

  if (typeof wk.title === "string") out.title = wk.title;
  if (typeof wk.description === "string") out.description = wk.description;
  else if (typeof wk.coach_notes === "string") out.description = wk.coach_notes;

  if (typeof wk.duration_seconds === "number") out.duration_seconds = wk.duration_seconds;
  else if (typeof wk.duration_sec === "number") out.duration_seconds = wk.duration_sec;
  else if (typeof wk.duration_min === "number") out.duration_seconds = wk.duration_min * 60;
  else if (typeof wk.duration === "number" && wk.duration > 0 && wk.duration < 300) {
    // Ambiguous `duration` — treat < 300 as minutes to match the rest of
    // the app's parsing convention (durations of "25" meaning 25 min).
    out.duration_seconds = wk.duration * 60;
  } else if (typeof wk.duration === "number") {
    out.duration_seconds = wk.duration;
  }

  if (typeof wk.category === "string" && wk.category.trim()) {
    out.category_hint = wk.category;
  } else if (typeof wk.workout_type === "string" && wk.workout_type.trim()) {
    out.category_hint = wk.workout_type;
  }
  return out;
}

/* ---------------------------------------------------------------------- */
/* Styles                                                                  */
/* ---------------------------------------------------------------------- */

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.color.border,
    gap: 8,
  },
  title: {
    color: theme.color.text,
    fontSize: 20,
    fontWeight: "800",
    letterSpacing: 1.5,
  },
  subtitle: {
    color: theme.color.textDim,
    fontSize: 11,
    letterSpacing: 1,
    marginTop: 2,
  },
  headerBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 10,
    backgroundColor: theme.color.surface2,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
  },
  headerBtnPrimary: {
    backgroundColor: theme.color.brand,
    borderColor: theme.color.brand,
  },
  headerBtnText: {
    color: theme.color.text,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 1,
  },
  filterRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 12,
    paddingVertical: 10,
    gap: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.color.border,
  },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  chipActive: {
    backgroundColor: theme.color.brand,
    borderColor: theme.color.brand,
  },
  chipText: {
    color: theme.color.text,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.8,
  },
  chipTextActive: { color: "#fff" },
  centerFill: { flex: 1, alignItems: "center", justifyContent: "center" },
  row: {
    flexDirection: "row",
    alignItems: "center",
    padding: 12,
    marginBottom: 10,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
    gap: 10,
  },
  rowIconBox: {
    width: 40,
    height: 40,
    borderRadius: 10,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: theme.color.brandTint,
    borderWidth: 1,
    borderColor: theme.color.brand,
    overflow: "hidden",
  },
  rowThumb: {
    // Fill the icon box completely — border/radius come from the parent.
    width: "100%",
    height: "100%",
  },
  rowTitle: { color: theme.color.text, fontSize: 15, fontWeight: "700" },
  rowMetaLine: { flexDirection: "row", marginTop: 2, flexWrap: "wrap" },
  rowMeta: {
    color: theme.color.textDim,
    fontSize: 11,
    letterSpacing: 0.5,
  },
  pubPill: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 8,
    borderWidth: StyleSheet.hairlineWidth,
  },
  pubPillOn: {
    backgroundColor: theme.color.brand,
    borderColor: theme.color.brand,
  },
  pubPillOff: {
    backgroundColor: theme.color.surface,
    borderColor: theme.color.border,
  },
  pubPillText: { fontSize: 10, fontWeight: "800", letterSpacing: 0.8 },
  iconBtn: { padding: 6 },
  emptyBox: {
    alignItems: "center",
    padding: 32,
    marginTop: 32,
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  emptyTitle: { color: theme.color.text, fontSize: 18, fontWeight: "800", marginTop: 10 },
  emptyBody: { color: theme.color.text, fontSize: 13, lineHeight: 20, marginTop: 8, textAlign: "center", opacity: 0.85 },

  // Modal
  modalScrim: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    justifyContent: "flex-end",
  },
  modalCard: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    maxHeight: "94%",
    // On Android + web, ensure the modal doesn't overflow off-screen.
    ...Platform.select({ web: { maxHeight: "94vh" as any }, default: {} }),
  },
  modalHeader: {
    flexDirection: "row",
    alignItems: "center",
    padding: 16,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.color.border,
  },
  modalTitle: { flex: 1, color: theme.color.text, fontSize: 18, fontWeight: "800", letterSpacing: 0.5 },

  label: {
    color: theme.color.textDim,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 1,
    marginTop: 14,
    marginBottom: 6,
  },
  hint: {
    color: theme.color.textDim,
    fontSize: 12,
    marginTop: 4,
  },
  input: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: theme.color.text,
    backgroundColor: theme.color.surface2,
    fontSize: 15,
  },
  textarea: { minHeight: 88, textAlignVertical: "top" },
  jsonArea: {
    minHeight: 180,
    textAlignVertical: "top",
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
    fontSize: 12,
    lineHeight: 18,
  },
  segRow: { flexDirection: "row", gap: 8 },
  segBtn: {
    flex: 1,
    paddingVertical: 10,
    alignItems: "center",
    borderRadius: 10,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  segBtnActive: {
    backgroundColor: theme.color.brand,
    borderColor: theme.color.brand,
  },
  segText: { color: theme.color.text, fontSize: 12, fontWeight: "800", letterSpacing: 1 },
  segTextActive: { color: "#fff" },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  pickerBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 12,
    borderRadius: 10,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  pickerBtnText: { color: theme.color.text, fontSize: 14, fontWeight: "600" },
  thumbPreview: { width: 60, height: 60, borderRadius: 8 },
  pubRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 20,
  },
  modalFooter: {
    flexDirection: "row",
    padding: 12,
    gap: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.color.border,
    backgroundColor: theme.color.surface,
  },
  footerBtn: {
    flex: 1,
    paddingVertical: 14,
    alignItems: "center",
    borderRadius: 12,
    backgroundColor: theme.color.surface2,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
  },
  footerBtnPrimary: {
    backgroundColor: theme.color.brand,
    borderColor: theme.color.brand,
  },
  footerBtnText: { color: theme.color.text, fontSize: 13, fontWeight: "800", letterSpacing: 1 },

  // Taxonomy
  sectionHeader: {
    color: theme.color.text,
    fontSize: 13,
    fontWeight: "800",
    letterSpacing: 1.4,
    marginBottom: 8,
  },
  addRow: { flexDirection: "row", alignItems: "center" },
  miniPrimary: {
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: 10,
    backgroundColor: theme.color.brand,
  },
  taxRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.color.border,
  },
  taxRowName: { color: theme.color.text, fontSize: 14 },
});
