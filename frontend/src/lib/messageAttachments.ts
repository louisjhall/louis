/**
 * messageAttachments — API client for the private 1:1 chat attachment
 * flow. Handles multipart upload (voice/image/video), URL resolution, and
 * pre-send deletion so the client can cancel gracefully.
 */
// expo-file-system v19 exposes createUploadTask/downloadAsync/cacheDirectory
// only via the /legacy subpath. The new class-based API doesn't yet cover
// multipart uploads with progress, so we stay on legacy for now.
import * as FileSystem from "expo-file-system/legacy";
import { getToken } from "@/src/lib/api";

export type AttachmentKind = "image" | "video" | "voice";

export type MessageAttachment = {
  id: string;
  message_id: string | null;
  uploaded_by: string;
  type: AttachmentKind;
  mime_type: string;
  file_size: number;
  duration_seconds: number | null;
  storage_key: string;
  thumbnail_key: string | null;
  status: "uploaded" | "failed";
  created_at: string;
  url: string; // relative /api/messages/attachments/{id}/file
};

function backendUrl(): string {
  const raw = (process.env.EXPO_PUBLIC_BACKEND_URL || "").replace(/\/+$/, "");
  return raw;
}

/**
 * Return a fully-qualified URL for an attachment (or thumbnail). Handles
 * both relative (`/api/...`) URLs from the backend and any accidental
 * fully-qualified URLs. Adds ?_=timestamp to bust the RN <Image> cache on
 * retries.
 */
export function attachmentSourceUrl(url: string, token?: string | null): string {
  const base = backendUrl();
  const abs = url.startsWith("http") ? url : `${base}${url}`;
  // We can't add an Authorization header to <Image> on iOS/Android RN, so
  // downloads still go via Authorization on <Video>/<Audio>. For <Image>
  // we rely on the token being sent when we pre-fetch via FileSystem
  // (see cacheAttachment below). For quick display without a cache, we
  // append the token as a query param when the caller passes one — the
  // backend accepts either.
  if (token) return `${abs}?token=${encodeURIComponent(token)}`;
  return abs;
}

/**
 * Upload a local file URI as a message attachment. Returns the created
 * attachment metadata, ready to be referenced in POST /api/messages.
 */
export async function uploadAttachment(params: {
  uri: string;
  kind: AttachmentKind;
  mimeType: string;
  durationSeconds?: number | null;
  onProgress?: (pct: number) => void;
}): Promise<MessageAttachment> {
  const token = await getToken();
  const url = `${backendUrl()}/api/messages/attachments`;

  // expo-file-system exposes uploadAsync which handles multipart streams
  // without loading the whole file into JS memory — crucial for 100 MB
  // videos on device.
  const filename = params.uri.split("/").pop() || `att.${params.kind}`;
  const uploadTask = FileSystem.createUploadTask(
    url,
    params.uri,
    {
      httpMethod: "POST",
      uploadType: FileSystem.FileSystemUploadType.MULTIPART,
      fieldName: "file",
      mimeType: params.mimeType,
      parameters: {
        kind: params.kind,
        duration_seconds: params.durationSeconds != null ? String(params.durationSeconds) : "",
      },
      headers: {
        Authorization: `Bearer ${token || ""}`,
      },
    },
    (progress) => {
      if (params.onProgress && progress.totalBytesExpectedToSend > 0) {
        const pct = Math.round(
          (progress.totalBytesSent / progress.totalBytesExpectedToSend) * 100
        );
        params.onProgress(pct);
      }
    },
  );

  const result = await uploadTask.uploadAsync();
  if (!result) throw new Error("upload cancelled");
  if (result.status < 200 || result.status >= 300) {
    let msg = `Upload failed (${result.status})`;
    try {
      const parsed = JSON.parse(result.body);
      const detail = parsed?.detail?.detail || parsed?.detail || parsed?.error;
      if (typeof detail === "string") msg = detail;
    } catch { /* keep default */ }
    const err: any = new Error(msg);
    err.status = result.status;
    err.filename = filename;
    throw err;
  }
  return JSON.parse(result.body) as MessageAttachment;
}

/**
 * Delete a queued (unsent) attachment. Used when the user removes it from
 * the composer before sending. No-op if the attachment is already bound
 * to a delivered message.
 */
export async function deleteAttachment(id: string): Promise<void> {
  const token = await getToken();
  try {
    await fetch(`${backendUrl()}/api/messages/attachments/${id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token || ""}` },
    });
  } catch {
    // best-effort; the daily-cap cleanup will handle stragglers
  }
}

/**
 * For <Image>/<Video> sources we need a URI that includes auth. Because
 * RN can't set an Authorization header on the network image loader, we
 * cache the file to a local URI first (small helper).
 */
export async function ensureLocalCopyOfAttachment(remoteUrl: string, cacheKey: string): Promise<string> {
  const token = await getToken();
  const abs = remoteUrl.startsWith("http") ? remoteUrl : `${backendUrl()}${remoteUrl}`;
  const target = `${FileSystem.cacheDirectory}msg_att_${cacheKey}`;
  try {
    const info = await FileSystem.getInfoAsync(target);
    if (info.exists) return target;
  } catch { /* fresh download */ }
  const dl = await FileSystem.downloadAsync(abs, target, {
    headers: { Authorization: `Bearer ${token || ""}` },
  });
  return dl.uri;
}
