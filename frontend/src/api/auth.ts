const CONSOLE_TOKEN_STORAGE_KEY = 'matts-v2-console-token';

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
  try {
    return window.sessionStorage.getItem(CONSOLE_TOKEN_STORAGE_KEY) || '';
  } catch {
    return '';
  }
}

function rememberConsoleToken(token: string): void {
  if (!token) return;
  try {
    window.sessionStorage.setItem(CONSOLE_TOKEN_STORAGE_KEY, token);
  } catch {
    // Private or locked-down remote browsers can disable sessionStorage.
  }
}

export function consoleToken(): string {
  const token = tokenFromSearch(window.location.search) || tokenFromHash(window.location.hash) || storedConsoleToken();
  rememberConsoleToken(token);
  return token;
}

function configuredApiBase(): string {
  const env = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env || {};
  return (env.VITE_API_BASE_URL || '').replace(/\/+$/, '');
}

function tokenizedUrl(path: string, token: string): string {
  const joiner = path.includes('?') ? '&' : '?';
  return `${path}${joiner}token=${encodeURIComponent(token)}`;
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
  const token = consoleToken();
  const url = apiUrl(path);
  return token ? tokenizedUrl(url, token) : url;
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
