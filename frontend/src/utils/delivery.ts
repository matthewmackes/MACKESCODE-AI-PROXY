export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Plain-HTTP remote browser sessions can block clipboard access.
    }
  }
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', 'true');
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand('copy');
  document.body.removeChild(textarea);
}

export function timestampSlug(): string {
  return new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
}

export function downloadTextFile(filename: string, text: string, type: string): void {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export type BriefDeliveryLabels = {
  copied: string;
  copyFailed: string;
  downloaded: string;
};

export function briefDeliveryActions(
  text: string,
  filenamePrefix: string,
  onStatus: (status: string) => void,
  labels: BriefDeliveryLabels,
  enabled = true,
): { copyBrief: () => Promise<void>; downloadBrief: () => void } {
  const copyBrief = async () => {
    if (!enabled || !text) return;
    try {
      await copyText(text);
      onStatus(labels.copied);
    } catch {
      onStatus(labels.copyFailed);
    }
  };
  const downloadBrief = () => {
    if (!enabled || !text) return;
    downloadTextFile(`${filenamePrefix}-${timestampSlug()}.md`, text, 'text/markdown;charset=utf-8');
    onStatus(labels.downloaded);
  };
  return { copyBrief, downloadBrief };
}
