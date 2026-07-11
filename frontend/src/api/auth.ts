const CONSOLE_TOKEN_STORAGE_KEY = 'matts-v2-console-token';
let cachedConsoleToken = '';

function tokenFromSearch(search: string): string {
  if (!search) return '';
  return new URLSearchParams(search.startsWith('?') ? search : `?${search}`).get('token') || '';
}

function tokenFromHash(hash: string): string {
  if (!hash) return '';
  const trimmed = hash.replace(/^#/, '');
  const queryIndex = trimmed.indexOf('?');
  if (queryIndex >= 0) {
    return tokenFromSearch(trimmed.slice(queryIndex + 1));
  }
  return tokenFromSearch(trimmed);
}

function storedConsoleToken(): string {
  if (cachedConsoleToken) return cachedConsoleToken;
  try {
    const token = window.sessionStorage.getItem(CONSOLE_TOKEN_STORAGE_KEY) || '';
    if (token) {
      cachedConsoleToken = token;
      return token;
    }
  } catch {
    // Private or locked-down remote browsers can disable sessionStorage.
  }
  try {
    const token = window.localStorage.getItem(CONSOLE_TOKEN_STORAGE_KEY) || '';
    if (token) cachedConsoleToken = token;
    return token;
  } catch {
    return '';
  }
}

export function rememberConsoleToken(token: string): void {
  const cleaned = token.trim();
  if (!cleaned) return;
  cachedConsoleToken = cleaned;
  try {
    window.sessionStorage.setItem(CONSOLE_TOKEN_STORAGE_KEY, cleaned);
  } catch {
    // Private or locked-down remote browsers can disable sessionStorage.
  }
  try {
    window.localStorage.setItem(CONSOLE_TOKEN_STORAGE_KEY, cleaned);
  } catch {
    // Local storage is only a resilience layer for reopened remote browsers.
  }
}

export function forgetConsoleToken(): void {
  cachedConsoleToken = '';
  try {
    window.sessionStorage.removeItem(CONSOLE_TOKEN_STORAGE_KEY);
  } catch {
    // Storage cleanup is best-effort.
  }
  try {
    window.localStorage.removeItem(CONSOLE_TOKEN_STORAGE_KEY);
  } catch {
    // Storage cleanup is best-effort.
  }
}

export function hasConsoleToken(): boolean {
  return Boolean(consoleToken());
}

function scrubBootstrapToken(): void {
  const url = new URL(window.location.href);
  let changed = false;
  if (url.searchParams.has('token')) {
    url.searchParams.delete('token');
    changed = true;
  }
  if (url.hash) {
    const rawHash = url.hash.replace(/^#/, '');
    const queryIndex = rawHash.indexOf('?');
    if (queryIndex >= 0) {
      const route = rawHash.slice(0, queryIndex);
      const params = new URLSearchParams(rawHash.slice(queryIndex + 1));
      if (params.has('token')) {
        params.delete('token');
        const query = params.toString();
        url.hash = query ? `${route}?${query}` : route;
        changed = true;
      }
    } else {
      const params = new URLSearchParams(rawHash);
      if (params.has('token')) {
        params.delete('token');
        url.hash = params.toString();
        changed = true;
      }
    }
  }
  if (changed) {
    window.history.replaceState(window.history.state, document.title, `${url.pathname}${url.search}${url.hash}`);
  }
}

export function consoleToken(): string {
  const searchToken = tokenFromSearch(window.location.search);
  const hashToken = tokenFromHash(window.location.hash);
  const token = searchToken || hashToken || storedConsoleToken();
  rememberConsoleToken(token);
  if (searchToken || hashToken) {
    scrubBootstrapToken();
  }
  return token;
}

function configuredApiBase(): string {
  const env = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env || {};
  return (env.VITE_API_BASE_URL || '').replace(/\/+$/, '');
}

export function apiBaseUrl(): string {
  return configuredApiBase();
}

export function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const base = apiBaseUrl();
  return base ? `${base}${normalizedPath}` : normalizedPath;
}

export function withConsoleToken(path: string): string {
  return apiUrl(path);
}

export function consoleAuthHeaders(): Record<string, string> {
  const token = consoleToken();
  return token ? { 'x-matts-console-token': token } : {};
}

type EndpointUrlOptions = {
  defaultPort?: number | string | null;
};

function applyDefaultPort(url: URL, defaultPort?: number | string | null): void {
  const port = defaultPort === undefined || defaultPort === null ? '' : String(defaultPort).trim();
  if (url.port && port && url.port !== port) {
    url.port = port;
  }
}

export function apiEndpointUrl(path: string, options: EndpointUrlOptions = {}): string {
  const base = apiBaseUrl() || window.location.origin;
  const url = new URL(path.startsWith('/') ? path : `/${path}`, base);
  applyDefaultPort(url, options.defaultPort);
  return url.toString();
}

export function apiWebSocketUrl(path: string, options: EndpointUrlOptions = {}): string {
  const base = apiBaseUrl() || window.location.origin;
  const url = new URL(path.startsWith('/') ? path : `/${path}`, base);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  applyDefaultPort(url, options.defaultPort);
  const token = consoleToken();
  if (token) {
    url.searchParams.set('token', token);
  }
  return url.toString();
}
