/** Saves a blob from `apiDownload` as a file via a throwaway anchor click —
 * the browser-download half of every PDF receipt / CSV/XLSX export. */
export function triggerDownload({ blob, filename }: { blob: Blob; filename: string }) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
