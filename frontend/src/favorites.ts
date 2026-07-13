import { useEffect, useState } from 'react';

const FAVORITES_STORAGE_KEY = 'matts-v2-model-favorites';
const LEGACY_CHAT_UI_STATE_KEY = 'matts-v2-chat-ui-state';
const FAVORITES_LIMIT = 48;

type FavoritesListener = (ids: string[]) => void;

const listeners = new Set<FavoritesListener>();
let favoriteIds: string[] | null = null;

function normalizeIds(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  return value
    .filter((id): id is string => typeof id === 'string' && Boolean(id) && !seen.has(id) && Boolean(seen.add(id)))
    .slice(0, FAVORITES_LIMIT);
}

function legacyChatFavorites(): string[] {
  try {
    const parsed = JSON.parse(window.sessionStorage.getItem(LEGACY_CHAT_UI_STATE_KEY) || '{}');
    const row = parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : {};
    return normalizeIds(row.favorites);
  } catch {
    return [];
  }
}

function loadFavorites(): string[] {
  if (favoriteIds) return favoriteIds;
  if (typeof window === 'undefined') return [];
  let stored: string[] | null = null;
  try {
    const raw = window.localStorage.getItem(FAVORITES_STORAGE_KEY);
    if (raw !== null) stored = normalizeIds(JSON.parse(raw));
  } catch {
    stored = null;
  }
  favoriteIds = stored ?? legacyChatFavorites();
  if (stored === null && favoriteIds.length) persist(favoriteIds);
  return favoriteIds;
}

function persist(ids: string[]): void {
  try {
    window.localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify(ids));
  } catch {
    // Favorites still work for this session when storage is unavailable.
  }
}

function setFavorites(ids: string[]): void {
  favoriteIds = normalizeIds(ids);
  persist(favoriteIds);
  listeners.forEach((listener) => listener(favoriteIds as string[]));
}

export function modelFavoriteIds(): string[] {
  return loadFavorites();
}

export function isModelFavorite(id: string): boolean {
  return loadFavorites().includes(id);
}

export function toggleModelFavorite(id: string): string[] {
  const current = loadFavorites();
  const next = current.includes(id) ? current.filter((item) => item !== id) : [id, ...current];
  setFavorites(next);
  return next;
}

export function useModelFavorites(): { favorites: string[]; toggleFavorite: (id: string) => void } {
  const [favorites, setLocal] = useState<string[]>(loadFavorites);
  useEffect(() => {
    const listener: FavoritesListener = (ids) => setLocal(ids);
    listeners.add(listener);
    const onStorage = (event: StorageEvent) => {
      if (event.key !== FAVORITES_STORAGE_KEY) return;
      favoriteIds = null;
      setLocal(loadFavorites());
    };
    window.addEventListener('storage', onStorage);
    return () => {
      listeners.delete(listener);
      window.removeEventListener('storage', onStorage);
    };
  }, []);
  return { favorites, toggleFavorite: (id: string) => void toggleModelFavorite(id) };
}
