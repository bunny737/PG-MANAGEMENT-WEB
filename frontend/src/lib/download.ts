import { isIos, isStandalone } from "@/lib/pwa";

/** Saves a blob from `apiDownload` as a file — the browser-download half of every PDF
 * receipt / CSV/XLSX export.
 *
 * In an installed iOS app a blob anchor click either does nothing or opens the file with no way
 * back, so there it goes through the share sheet (Save to Files, Print, Mail, …) instead. iOS
 * only allows that shortly after a tap, so if the share is refused the anchor path is the
 * fallback. Never rejects: a cancelled share sheet is not an error. */
export async function triggerDownload({ blob, filename }: { blob: Blob; filename: string }) {
  if (isIos() && isStandalone() && typeof navigator.share === "function") {
    const file = new File([blob], filename, { type: blob.type });
    if (navigator.canShare?.({ files: [file] })) {
      try {
        await navigator.share({ files: [file] });
        return;
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        // NotAllowedError (tap too long ago) and friends: fall through to the anchor.
      }
    }
  }

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
