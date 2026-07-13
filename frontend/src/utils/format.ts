export function numberValue(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function money(value: unknown): string {
  const amount = numberValue(value, 0);
  const places = amount > 0 && amount < 0.01 ? 4 : 2;
  return `$${amount.toFixed(places)}`;
}

export function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function listValue(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((row) => row && typeof row === 'object') as Array<Record<string, unknown>> : [];
}

export function timestampLabel(value: unknown): string {
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds > 0 ? new Date(seconds * 1000).toLocaleString() : 'n/a';
}

export function readableStatus(value: string | undefined): string {
  return String(value || 'unknown').replace(/_/g, ' ');
}
