export async function readResponsePayload(response: Response): Promise<unknown> {
  const text = await response.text().catch(() => '');
  if (!text) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function messageFromValue(value: unknown): string | undefined {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed || undefined;
  }
  if (value && typeof value === 'object') {
    const row = value as Record<string, unknown>;
    if (typeof row.message === 'string' && row.message.trim()) return row.message;
    if (typeof row.error === 'string' && row.error.trim()) return row.error;
  }
  return undefined;
}

function suggestedFixFromValue(value: unknown): string | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const row = value as Record<string, unknown>;
  const details = row.details;
  if (details && typeof details === 'object') {
    const fix = (details as Record<string, unknown>).suggested_fix;
    if (typeof fix === 'string' && fix.trim()) return fix.trim();
  }
  return undefined;
}

function appendSuggestedFix(message: string | undefined, fix: string | undefined): string | undefined {
  if (!message) return fix;
  if (!fix || message.includes(fix)) return message;
  return `${message.replace(/[.\s]+$/, '')}. ${fix}`;
}

export function errorMessageFromPayload(payload: unknown, status: number, fallbackPrefix = 'v2 request failed'): string {
  if (payload && typeof payload === 'object') {
    const row = payload as Record<string, unknown>;
    const suggestedFix = suggestedFixFromValue(row);
    const detailMessage = messageFromValue(row.detail);
    if (detailMessage) return appendSuggestedFix(detailMessage, suggestedFix) || detailMessage;
    const topLevelMessage = messageFromValue(row.message);
    if (topLevelMessage) return appendSuggestedFix(topLevelMessage, suggestedFix) || topLevelMessage;
    const topLevelError = messageFromValue(row.error);
    if (topLevelError) return appendSuggestedFix(topLevelError, suggestedFix) || topLevelError;
  }
  const payloadMessage = messageFromValue(payload);
  if (payloadMessage) return payloadMessage;
  return `${fallbackPrefix}: ${status}`;
}

export async function responseJsonOrThrow<T>(response: Response, fallbackPrefix = 'v2 request failed'): Promise<T> {
  const payload = await readResponsePayload(response);
  if (!response.ok) {
    throw new Error(errorMessageFromPayload(payload, response.status, fallbackPrefix));
  }
  return payload as T;
}
