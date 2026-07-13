import { useEffect, useState } from 'react';

export type ThemeMode = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'matts-v2-theme';
const LEGACY_CHAT_UI_STATE_KEY = 'matts-v2-chat-ui-state';

function normalizeThemeMode(value: unknown): ThemeMode | null {
  return value === 'dark' || value === 'light' ? value : null;
}

function legacyChatTheme(): ThemeMode | null {
  try {
    const parsed = JSON.parse(window.sessionStorage.getItem(LEGACY_CHAT_UI_STATE_KEY) || '{}');
    const row = parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : {};
    return normalizeThemeMode(row.theme);
  } catch {
    return null;
  }
}

export function resolveInitialThemeMode(): ThemeMode {
  if (typeof window === 'undefined') return 'light';
  try {
    const stored = normalizeThemeMode(window.localStorage.getItem(THEME_STORAGE_KEY));
    if (stored) return stored;
  } catch {
    // Storage can be unavailable in restricted browsers; fall through to media/legacy detection.
  }
  const legacy = legacyChatTheme();
  if (legacy) return legacy;
  try {
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) return 'dark';
  } catch {
    // matchMedia can be unavailable in older embedded browsers.
  }
  return 'light';
}

export function currentThemeMode(): ThemeMode {
  if (typeof document === 'undefined') return 'light';
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
}

export function applyThemeMode(mode: ThemeMode): void {
  if (typeof document === 'undefined') return;
  document.documentElement.dataset.theme = mode;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, mode);
  } catch {
    // The theme still applies for this session when storage is unavailable.
  }
}

export function useThemeMode(): ThemeMode {
  const [mode, setMode] = useState<ThemeMode>(currentThemeMode);
  useEffect(() => {
    const root = document.documentElement;
    const observer = new MutationObserver(() => setMode(currentThemeMode()));
    observer.observe(root, { attributes: true, attributeFilter: ['data-theme'] });
    setMode(currentThemeMode());
    return () => observer.disconnect();
  }, []);
  return mode;
}
