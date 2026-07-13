import { ChangeEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AdvancedPage, CarbonIcon, ChatPage, CodePage, CreatePage, ModelDetailHost, ResearchPage, V2_ADVANCED_TAB_EVENT, V2_AUTH_REQUIRED_EVENT, V2_RESETTABLE_WORKSPACE_KEYS, V2_WORKSPACE_SESSION_KEYS, WHATS_NEW_DISMISSED_KEY, WhatsNewModal } from './pages/HeroPages';
import { forgetConsoleToken, hasConsoleToken, rememberConsoleToken } from './api/auth';
import { CostControlPayload, getCostControl, getSpeechStatus, getWhatsNew, overrideCostControl, updateCostControlThresholds } from './api/v2';
import { V2_FATAL_ERROR_DIAGNOSTIC_KEY } from './components/ShellErrorBoundary';
import { getPlatformBranding } from './branding';
import { applyThemeMode, resolveInitialThemeMode, useThemeMode } from './theme';
import { copyText, downloadTextFile, timestampSlug } from './utils/delivery';
import { DEFAULT_SPEECH_LANGUAGES, DEFAULT_VOICE_LANGUAGE, loadVoicePreferences, saveVoicePreferences, VoicePreferences, VOICE_PRESETS, voicePresetById } from './voicePreferences';

type NavItem = {
  key: string;
  label: string;
  icon: string;
  description: string;
};

// Workspace registry: every reachable workspace (hash routing, saved state, quick switcher).
const navItems: NavItem[] = [
  { key: 'chat', label: 'Chat', icon: 'actions/call-start-symbolic.svg', description: 'Autonomous command center' },
  { key: 'code', label: 'Code', icon: 'apps/utilities-terminal-symbolic.svg', description: 'Terminal, sessions, screenshots' },
  { key: 'research', label: 'Research', icon: 'actions/edit-find-symbolic.svg', description: 'Search and evidence' },
  { key: 'create', label: 'Create', icon: 'actions/document-new-symbolic.svg', description: 'Image creation studio' },
  { key: 'models', label: 'Models', icon: 'categories/applications-science-symbolic.svg', description: 'LLM showcase and health grades' },
  { key: 'advanced', label: 'Advanced', icon: 'actions/document-properties-symbolic.svg', description: 'Owner/admin tools' }
];

// Drawer primary nav: Advanced (and Models, now an Advanced tab) are reached via Settings.
const DRAWER_NAV_KEYS = ['chat', 'code', 'research', 'create'] as const;
const drawerItems: NavItem[] = navItems.filter((item) => (DRAWER_NAV_KEYS as readonly string[]).includes(item.key));

const ADVANCED_TAB_SESSION_KEY = 'matts-v2-advanced-tab';

/**
 * Models now lives inside Advanced. Resolve legacy keys by writing the target
 * Advanced tab to sessionStorage BEFORE the workspace activates — AdvancedPage
 * reads it at mount, so this is race-free where the tab-change event is not.
 */
function resolveWorkspaceKey(key: string): string {
  if (key !== 'models') return key;
  try {
    window.sessionStorage.setItem(ADVANCED_TAB_SESSION_KEY, 'models');
  } catch {
    // Advanced still opens on its remembered tab when storage is unavailable.
  }
  return 'advanced';
}

const platformBranding = getPlatformBranding();
const QUICK_SWITCHER_RECENTS_KEY = 'matts-v2-quick-switcher-recents';
const QUICK_SWITCHER_RECENT_LIMIT = 5;

type SavedWorkspaceSnapshot = {
  schema: 'matts-v2-saved-workspace-state/v1';
  generated_at: string;
  active_workspace: string;
  recent_workspace_keys: string[];
  saved_state_count: number;
  restore_state: Record<string, string>;
};

type AuthPromptState = {
  title: string;
  detail: string;
};

const DEFAULT_AUTH_PROMPT: AuthPromptState = {
  title: 'Sign In',
  detail: 'Enter a console token to unlock this action.',
};

function activeFromHash(): string {
  if (typeof window === 'undefined') return navItems[0].key;
  const key = window.location.hash.replace(/^#\/?/, '').split(/[/?&]/)[0].toLowerCase();
  return navItems.some((item) => item.key === key) ? resolveWorkspaceKey(key) : navItems[0].key;
}

function navItemForKey(key: string): NavItem | undefined {
  return navItems.find((item) => item.key === key);
}

function normalizeRecentWorkspaceKeys(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  return value.filter((key): key is string => {
    if (typeof key !== 'string' || seen.has(key) || !navItemForKey(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, QUICK_SWITCHER_RECENT_LIMIT);
}

function loadRecentWorkspaceKeys(): string[] {
  if (typeof window === 'undefined') return [];
  try {
    return normalizeRecentWorkspaceKeys(JSON.parse(window.sessionStorage.getItem(QUICK_SWITCHER_RECENTS_KEY) || '[]'));
  } catch {
    return [];
  }
}

function savedWorkspaceStateCount(): number {
  return savedWorkspaceStateEntries().length;
}

function savedWorkspaceStateEntries(): Array<[string, string]> {
  if (typeof window === 'undefined') return [];
  try {
    const entries: Array<[string, string]> = [];
    V2_RESETTABLE_WORKSPACE_KEYS.forEach((key) => {
      const value = window.sessionStorage.getItem(key);
      if (value) entries.push([key, value]);
    });
    return entries;
  } catch {
    return [];
  }
}

function buildSavedWorkspaceSnapshot(active: string, recentWorkspaceKeys: string[]): SavedWorkspaceSnapshot | null {
  const entries = savedWorkspaceStateEntries();
  if (!entries.length) return null;
  return {
    schema: 'matts-v2-saved-workspace-state/v1',
    generated_at: new Date().toISOString(),
    active_workspace: active,
    recent_workspace_keys: normalizeRecentWorkspaceKeys(recentWorkspaceKeys),
    saved_state_count: entries.length,
    restore_state: Object.fromEntries(entries),
  };
}

function currentWorkspaceUrl(active: string): string {
  if (typeof window === 'undefined') return `#${active}`;
  const url = new URL(window.location.href);
  url.hash = active;
  return url.toString();
}

function parseSavedWorkspaceSnapshot(text: string): SavedWorkspaceSnapshot | null {
  try {
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== 'object') return null;
    const row = parsed as Record<string, unknown>;
    if (row.schema !== 'matts-v2-saved-workspace-state/v1') return null;
    const restoreSource = row.restore_state && typeof row.restore_state === 'object' ? row.restore_state as Record<string, unknown> : {};
    const restore_state: Record<string, string> = {};
    V2_RESETTABLE_WORKSPACE_KEYS.forEach((key) => {
      const value = restoreSource[key];
      if (typeof value === 'string' && value) restore_state[key] = value;
    });
    const restoreKeys = Object.keys(restore_state);
    if (!restoreKeys.length) return null;
    const activeWorkspace = typeof row.active_workspace === 'string' && navItemForKey(row.active_workspace) ? row.active_workspace : navItems[0].key;
    const recentWorkspaceKeys = normalizeRecentWorkspaceKeys(row.recent_workspace_keys);
    return {
      schema: 'matts-v2-saved-workspace-state/v1',
      generated_at: typeof row.generated_at === 'string' ? row.generated_at : '',
      active_workspace: activeWorkspace,
      recent_workspace_keys: recentWorkspaceKeys,
      saved_state_count: restoreKeys.length,
      restore_state,
    };
  } catch {
    return null;
  }
}

function shouldTriggerFatalDiagnostic(): boolean {
  try {
    return window.sessionStorage.getItem(V2_FATAL_ERROR_DIAGNOSTIC_KEY) === '1';
  } catch {
    return false;
  }
}

function numberValue(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function money(value: unknown): string {
  const amount = numberValue(value, 0);
  const places = amount > 0 && amount < 0.01 ? 4 : 2;
  return `$${amount.toFixed(places)}`;
}

function percentValue(value: unknown): string {
  const percent = numberValue(value, 0);
  return `${percent.toFixed(percent >= 10 ? 0 : 1)}%`;
}

function costStatusClass(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized === 'paused' || normalized === 'hard') return 'hard';
  if (normalized === 'warning') return 'warning';
  if (normalized === 'offline') return 'offline';
  return 'ready';
}

function categoryCost(payload: CostControlPayload | undefined, key: string, field: string): unknown {
  return payload?.costs?.categories?.[key]?.[field];
}

function BrandMark({ testId }: { testId: string }) {
  return (
    <span className="brandMark" data-testid={testId} aria-hidden="true">
      <img src={platformBranding.appIconUrl} alt="" />
    </span>
  );
}

function TagLike({ status, children }: { status: string; children: string }) {
  return <span className={`tagLike ${status}`}>{children}</span>;
}

function ConsoleSignInDialog({ prompt, onClose, onSubmit }: { prompt: AuthPromptState; onClose: () => void; onSubmit: (token: string) => void }) {
  const [token, setToken] = useState('');
  const inputRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }, []);
  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);
  const submit = () => {
    const value = token.trim();
    if (!value) return;
    onSubmit(value);
    setToken('');
  };
  return (
    <div className="modalBackdrop authBackdrop">
      <div className="authDialog" role="dialog" aria-modal="true" aria-labelledby="console-sign-in-title">
        <div className="authDialogHeader">
          <CarbonIcon path="apps/user--settings.svg" label="Sign in" />
          <div>
            <span>Console Access</span>
            <h2 id="console-sign-in-title">{prompt.title}</h2>
          </div>
          <button className="closeButton inline" type="button" aria-label="Close Sign In" onClick={onClose}>
            <CarbonIcon path="actions/window-close-symbolic.svg" label="Close" />
          </button>
        </div>
        <p className="authDialogDetail">{prompt.detail}</p>
        <label className="field authTokenField">
          <span>Console Token</span>
          <input
            ref={inputRef}
            value={token}
            onChange={(event) => setToken(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') submit();
            }}
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <div className="authDialogActions">
          <button className="primaryButton" type="button" disabled={!token.trim()} onClick={submit}>Sign In</button>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  if (shouldTriggerFatalDiagnostic()) {
    throw new Error('V2 shell diagnostic render failure');
  }
  const queryClient = useQueryClient();
  const [active, setActive] = useState(activeFromHash);
  const [quickOpen, setQuickOpen] = useState(false);
  const [quickQuery, setQuickQuery] = useState('');
  const [quickHighlightedIndex, setQuickHighlightedIndex] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [recentWorkspaceKeys, setRecentWorkspaceKeys] = useState(loadRecentWorkspaceKeys);
  const [workspaceResetVersion, setWorkspaceResetVersion] = useState(0);
  const [savedStateVersion, setSavedStateVersion] = useState(0);
  const [authPromptOpen, setAuthPromptOpen] = useState(false);
  const [authPrompt, setAuthPrompt] = useState<AuthPromptState>(DEFAULT_AUTH_PROMPT);
  const [signedIn, setSignedIn] = useState(() => hasConsoleToken());
  const themeMode = useThemeMode();
  const [voicePreferences, setVoicePreferences] = useState(loadVoicePreferences);
  const [costThresholdDraft, setCostThresholdDraft] = useState('');
  const [costControlStatus, setCostControlStatus] = useState('Cost ready');
  const [showStartupWhatsNew, setShowStartupWhatsNew] = useState(() => {
    try {
      return window.sessionStorage.getItem(WHATS_NEW_DISMISSED_KEY) !== '1';
    } catch {
      return true;
    }
  });
  const whatsNew = useQuery({ queryKey: ['whats-new'], queryFn: getWhatsNew, retry: false });
  const speechStatus = useQuery({ queryKey: ['shell-speech-status'], queryFn: getSpeechStatus, retry: false, refetchInterval: 30000 });
  const costControl = useQuery({ queryKey: ['cost-control'], queryFn: getCostControl, retry: false, refetchInterval: 60000 });
  const quickInputRef = useRef<HTMLInputElement | null>(null);
  const stateImportRef = useRef<HTMLInputElement | null>(null);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const voicePresetRef = useRef<HTMLSelectElement | null>(null);
  const drawerRef = useRef<HTMLElement | null>(null);
  const drawerNavRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  useEffect(() => {
    applyThemeMode(resolveInitialThemeMode());
  }, []);
  const toggleThemeMode = () => applyThemeMode(themeMode === 'dark' ? 'light' : 'dark');
  useEffect(() => {
    const threshold = costControl.data?.threshold?.monthly_threshold_usd;
    if (threshold === undefined || threshold === null) return;
    setCostThresholdDraft(String(numberValue(threshold, 0)));
  }, [costControl.data?.threshold?.monthly_threshold_usd]);
  const quickItems = useMemo(() => {
    const query = quickQuery.trim().toLowerCase();
    if (!query) return navItems;
    return navItems.filter((item) => `${item.label} ${item.description}`.toLowerCase().includes(query));
  }, [quickQuery]);
  const recentItems = useMemo(() => recentWorkspaceKeys.map((key) => navItemForKey(key)).filter((item): item is NavItem => Boolean(item)).filter((item) => item.key !== active).slice(0, QUICK_SWITCHER_RECENT_LIMIT), [active, recentWorkspaceKeys]);
  const highlightedQuickItem = quickItems[quickHighlightedIndex] || quickItems[0];
  const activeItem = useMemo(() => navItemForKey(active) || navItems[0], [active]);
  const activeVoicePreset = voicePresetById(voicePreferences.globalPresetId);
  const voiceLanguages = speechStatus.data?.languages?.length ? speechStatus.data.languages : DEFAULT_SPEECH_LANGUAGES;
  const savedStateCount = useMemo(savedWorkspaceStateCount, [quickOpen, savedStateVersion]);
  const [savedStateStatus, setSavedStateStatus] = useState(savedStateCount ? 'State ready' : 'No saved state');
  const [workspaceLinkStatus, setWorkspaceLinkStatus] = useState('Link ready');
  useEffect(() => {
    const onAuthRequired = (event: Event) => {
      const detail = (event as CustomEvent<Partial<AuthPromptState>>).detail || {};
      setAuthPrompt({
        title: detail.title || DEFAULT_AUTH_PROMPT.title,
        detail: detail.detail || DEFAULT_AUTH_PROMPT.detail,
      });
      setAuthPromptOpen(true);
    };
    window.addEventListener(V2_AUTH_REQUIRED_EVENT, onAuthRequired);
    return () => window.removeEventListener(V2_AUTH_REQUIRED_EVENT, onAuthRequired);
  }, []);
  useEffect(() => {
    const syncFromHash = () => setActive(activeFromHash());
    window.addEventListener('hashchange', syncFromHash);
    window.addEventListener('popstate', syncFromHash);
    return () => {
      window.removeEventListener('hashchange', syncFromHash);
      window.removeEventListener('popstate', syncFromHash);
    };
  }, []);
  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setDrawerOpen(false);
        setQuickOpen(true);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);
  useEffect(() => {
    if (!quickOpen) return;
    window.setTimeout(() => quickInputRef.current?.focus(), 0);
  }, [quickOpen]);
  useEffect(() => {
    if (!quickOpen) return;
    setQuickHighlightedIndex(quickItems.length ? 0 : -1);
  }, [quickItems, quickOpen]);
  const recordRecentWorkspace = (key: string) => {
    const next = normalizeRecentWorkspaceKeys([key, ...recentWorkspaceKeys]);
    setRecentWorkspaceKeys(next);
    try {
      window.sessionStorage.setItem(QUICK_SWITCHER_RECENTS_KEY, JSON.stringify(next));
    } catch {
      // Recents are an enhancement; switching must still work in restricted browsers.
    }
  };
  const commitVoicePreferences = (updater: VoicePreferences | ((current: VoicePreferences) => VoicePreferences)) => {
    setVoicePreferences((current) => {
      const next = saveVoicePreferences(typeof updater === 'function' ? updater(current) : updater);
      return next;
    });
  };
  const toggleGlobalVoice = () => {
    const turningOn = !voicePreferences.enabled;
    commitVoicePreferences((current) => ({
      ...current,
      enabled: turningOn,
      presetPickerSeen: current.presetPickerSeen || turningOn,
    }));
    if (turningOn && !voicePreferences.presetPickerSeen) {
      window.setTimeout(() => voicePresetRef.current?.focus(), 0);
    }
  };
  const saveCostThreshold = async () => {
    try {
      setCostControlStatus('Saving limit');
      await updateCostControlThresholds({
        scope_type: 'workspace',
        scope_id: 'default',
        monthly_threshold_usd: numberValue(costThresholdDraft, 0),
      });
      await queryClient.invalidateQueries({ queryKey: ['cost-control'] });
      setCostControlStatus('Limit saved');
    } catch {
      setCostControlStatus('Save failed');
    }
  };
  const overrideCostPause = async () => {
    try {
      setCostControlStatus('Overriding');
      await overrideCostControl({ action: 'override', duration_minutes: 60, reason: 'toolbar_override' });
      await queryClient.invalidateQueries({ queryKey: ['cost-control'] });
      setCostControlStatus('Override active');
    } catch {
      setCostControlStatus('Override failed');
    }
  };
  const activate = (key: string) => {
    const resolved = resolveWorkspaceKey(key);
    recordRecentWorkspace(resolved);
    setActive(resolved);
    const nextHash = `#${resolved}`;
    if (window.location.hash !== nextHash) window.history.pushState(null, '', nextHash);
  };
  const activateFromDrawer = (key: string) => {
    activate(key);
    setDrawerOpen(false);
  };
  const openSettingsWorkspace = () => {
    try {
      window.sessionStorage.removeItem(V2_WORKSPACE_SESSION_KEYS.advancedTab);
    } catch {
      // Advanced can still open if browser storage is restricted.
    }
    setDrawerOpen(false);
    activate('advanced');
    window.dispatchEvent(new CustomEvent(V2_ADVANCED_TAB_EVENT, { detail: { tab: 'overview' } }));
  };
  const submitConsoleToken = (token: string) => {
    rememberConsoleToken(token);
    setSignedIn(true);
    setAuthPromptOpen(false);
    queryClient.invalidateQueries();
  };
  const signOut = () => {
    forgetConsoleToken();
    setSignedIn(false);
    setAuthPrompt(DEFAULT_AUTH_PROMPT);
    setAuthPromptOpen(true);
    queryClient.invalidateQueries();
  };
  const openAuthPrompt = () => {
    setAuthPrompt(DEFAULT_AUTH_PROMPT);
    setAuthPromptOpen(true);
  };
  const openQuickSwitcherFromDrawer = () => {
    setDrawerOpen(false);
    setQuickOpen(true);
  };
  const triggerAuthFromDrawer = () => {
    setDrawerOpen(false);
    if (signedIn) {
      signOut();
    } else {
      openAuthPrompt();
    }
  };
  const closeQuickSwitcher = () => {
    setQuickOpen(false);
    setQuickQuery('');
  };
  const activateQuickItem = (key: string) => {
    activate(key);
    closeQuickSwitcher();
  };
  const onQuickKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      closeQuickSwitcher();
      return;
    }
    if (!quickItems.length) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setQuickHighlightedIndex((index) => (index + 1) % quickItems.length);
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setQuickHighlightedIndex((index) => (index <= 0 ? quickItems.length - 1 : index - 1));
      return;
    }
    if (event.key === 'Home') {
      event.preventDefault();
      setQuickHighlightedIndex(0);
      return;
    }
    if (event.key === 'End') {
      event.preventDefault();
      setQuickHighlightedIndex(quickItems.length - 1);
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      activateQuickItem((highlightedQuickItem || quickItems[0]).key);
    }
  };
  useEffect(() => {
    if (!quickOpen) return;
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') closeQuickSwitcher();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [quickOpen]);
  useEffect(() => {
    if (!drawerOpen) return;
    window.setTimeout(() => {
      const activeButton = drawerNavRefs.current[active];
      const firstFocusable = drawerRef.current?.querySelector<HTMLElement>('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      (activeButton || firstFocusable)?.focus();
    }, 0);
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setDrawerOpen(false);
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = Array.from(drawerRef.current?.querySelectorAll<HTMLElement>('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])') || [])
        .filter((element) => !element.hasAttribute('disabled') && element.getAttribute('aria-hidden') !== 'true');
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      menuButtonRef.current?.focus();
    };
  }, [active, drawerOpen]);
  const dismissStartupWhatsNew = () => {
    try {
      window.sessionStorage.setItem(WHATS_NEW_DISMISSED_KEY, '1');
    } catch {
      // Session storage can be unavailable in restricted browsers; dismissal still works for this render.
    }
    setShowStartupWhatsNew(false);
  };
  useEffect(() => {
    if (quickOpen) setWorkspaceLinkStatus('Link ready');
  }, [active, quickOpen]);
  const copyCurrentWorkspaceLink = async () => {
    try {
      await copyText(currentWorkspaceUrl(active));
      setWorkspaceLinkStatus('Link copied');
    } catch {
      setWorkspaceLinkStatus('Copy failed');
    }
  };
  useEffect(() => {
    if (quickOpen) setSavedStateStatus(savedStateCount ? 'State ready' : 'No saved state');
  }, [quickOpen, savedStateCount]);
  const savedWorkspaceSnapshotText = () => {
    const snapshot = buildSavedWorkspaceSnapshot(active, recentWorkspaceKeys);
    return snapshot ? JSON.stringify(snapshot, null, 2) : '';
  };
  const copySavedWorkspaceState = async () => {
    const text = savedWorkspaceSnapshotText();
    if (!text) return;
    try {
      await copyText(text);
      setSavedStateStatus('State copied');
    } catch {
      setSavedStateStatus('Copy failed');
    }
  };
  const downloadSavedWorkspaceState = () => {
    const text = savedWorkspaceSnapshotText();
    if (!text) return;
    downloadTextFile(`mde-llm-proxy-workspace-state-${timestampSlug()}.json`, text, 'application/json;charset=utf-8');
    setSavedStateStatus('State downloaded');
  };
  const importSavedWorkspaceState = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const snapshot = parseSavedWorkspaceSnapshot(await file.text());
      if (!snapshot) {
        setSavedStateStatus('Import failed');
        return;
      }
      V2_RESETTABLE_WORKSPACE_KEYS.forEach((key) => window.sessionStorage.removeItem(key));
      Object.entries(snapshot.restore_state).forEach(([key, value]) => window.sessionStorage.setItem(key, value));
      setRecentWorkspaceKeys(snapshot.recent_workspace_keys);
      window.sessionStorage.setItem(QUICK_SWITCHER_RECENTS_KEY, JSON.stringify(snapshot.recent_workspace_keys));
      setSavedStateVersion((value) => value + 1);
      setWorkspaceResetVersion((value) => value + 1);
      setSavedStateStatus('State imported');
      const restoredWorkspace = resolveWorkspaceKey(snapshot.active_workspace);
      setActive(restoredWorkspace);
      const nextHash = `#${restoredWorkspace}`;
      if (window.location.hash !== nextHash) window.history.pushState(null, '', nextHash);
      closeQuickSwitcher();
    } catch {
      setSavedStateStatus('Import failed');
    }
  };
  const resetSavedWorkspaces = () => {
    try {
      V2_RESETTABLE_WORKSPACE_KEYS.forEach((key) => window.sessionStorage.removeItem(key));
    } catch {
      // Reset is best-effort when browser storage is restricted.
    }
    setSavedStateVersion((value) => value + 1);
    setWorkspaceResetVersion((value) => value + 1);
    closeQuickSwitcher();
  };
  const costPayload = costControl.data;
  const costStatus = costPayload?.status || (costControl.error ? 'offline' : 'ready');
  const costClass = costStatusClass(costStatus);
  const costThreshold = numberValue(costPayload?.threshold?.monthly_threshold_usd, 0);
  const costPercent = numberValue(costPayload?.threshold?.percent, 0);
  const costPaused = Boolean(costPayload?.pause?.active);
  const costSource = String(costPayload?.provider?.monthly_source || costPayload?.costs?.sources?.monthly || 'local_estimate');
  const costSourceLabel = costSource === 'provider_billing_api' ? 'Provider billing' : 'Local estimate';
  return (
    <div className="carbonShell">
      {authPromptOpen ? <ConsoleSignInDialog prompt={authPrompt} onClose={() => setAuthPromptOpen(false)} onSubmit={submitConsoleToken} /> : null}
      {showStartupWhatsNew && whatsNew.data ? <WhatsNewModal data={whatsNew.data} onClose={dismissStartupWhatsNew} /> : null}
      {quickOpen ? (
        <div className="modalBackdrop quickSwitcherBackdrop">
          <div className="quickSwitcher" role="dialog" aria-modal="true" aria-labelledby="quick-switcher-title">
            <div className="quickSwitcherHeader">
              <div>
                <span>Workspace</span>
                <h2 id="quick-switcher-title">Switch Workspace</h2>
                <small className="quickSwitcherLinkStatus">{workspaceLinkStatus}</small>
              </div>
              <div className="quickSwitcherHeaderActions">
                <button className="iconButton" type="button" aria-label="Copy Current Workspace Link" title="Copy current workspace link" onClick={() => void copyCurrentWorkspaceLink()}>
                  <CarbonIcon path="actions/insert-link-symbolic.svg" label="Copy link" />
                </button>
                <button className="closeButton inline" type="button" aria-label="Close Switch Workspace" onClick={closeQuickSwitcher}>
                  <CarbonIcon path="actions/window-close-symbolic.svg" label="Close" />
                </button>
              </div>
            </div>
            <div className="searchLine compact quickSwitcherSearch">
              <input
                ref={quickInputRef}
                value={quickQuery}
                onChange={(event) => setQuickQuery(event.target.value)}
                onKeyDown={onQuickKeyDown}
                placeholder="Search workspaces"
                role="combobox"
                aria-expanded="true"
                aria-controls="quick-switcher-results"
                aria-activedescendant={highlightedQuickItem ? `quick-workspace-${highlightedQuickItem.key}` : undefined}
              />
            </div>
            {recentItems.length ? (
              <div className="quickSwitcherRecents" aria-label="Recent workspaces">
                <span>Recent</span>
                <div>
                  {recentItems.map((item) => (
                    <button key={item.key} type="button" onClick={() => activateQuickItem(item.key)}>
                      <CarbonIcon path={item.icon} label={item.label} />
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            <div id="quick-switcher-results" className="quickSwitcherList" role="listbox" aria-label="Workspace results">
              {quickItems.length ? quickItems.map((item, index) => (
                <button
                  key={item.key}
                  id={`quick-workspace-${item.key}`}
                  type="button"
                  role="option"
                  aria-selected={quickHighlightedIndex === index}
                  className={[active === item.key ? 'active' : '', quickHighlightedIndex === index ? 'highlighted' : ''].filter(Boolean).join(' ')}
                  onMouseEnter={() => setQuickHighlightedIndex(index)}
                  onClick={() => activateQuickItem(item.key)}
                >
                  <CarbonIcon path={item.icon} label={item.label} />
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.description}</small>
                  </span>
                </button>
              )) : <div className="emptyState">No workspace matches.</div>}
            </div>
            <div className="quickSwitcherFooter">
              <div>
                <span>Saved State</span>
                <strong>{savedStateCount ? `${savedStateCount} workspace${savedStateCount === 1 ? '' : 's'} ready to restore` : 'No saved workspace state'}</strong>
                <small>{savedStateStatus}</small>
              </div>
              <div className="quickSwitcherFooterActions">
                <button className="secondaryButton" type="button" disabled={!savedStateCount} onClick={() => void copySavedWorkspaceState()}>Copy State</button>
                <button className="secondaryButton" type="button" disabled={!savedStateCount} onClick={downloadSavedWorkspaceState}>Download State</button>
                <button className="secondaryButton" type="button" onClick={() => stateImportRef.current?.click()}>Import State</button>
                <button className="secondaryButton" type="button" disabled={!savedStateCount} onClick={resetSavedWorkspaces}>Reset Saved State</button>
                <input ref={stateImportRef} className="workspaceStateImportInput" data-testid="workspace-state-import" type="file" accept="application/json,.json" onChange={(event) => void importSavedWorkspaceState(event)} />
              </div>
            </div>
          </div>
        </div>
      ) : null}
      <div className="shellFloatingChrome" data-testid="shell-floating-menu">
        <button
          ref={menuButtonRef}
          className="shellMenuButton"
          type="button"
          aria-label={drawerOpen ? 'Close Navigation Menu' : 'Open Navigation Menu'}
          aria-expanded={drawerOpen}
          aria-controls="shell-navigation-drawer"
          onClick={() => setDrawerOpen((open) => !open)}
          data-testid="shell-menu-toggle"
        >
          <CarbonIcon path="actions/open-menu-symbolic.svg" label="Menu" />
        </button>
        <div className="shellFloatingBrand">
          <BrandMark testId="shell-brand-icon" />
          <div>
            <strong>{platformBranding.product}</strong>
            <span>{platformBranding.platform} Console v2</span>
          </div>
        </div>
        <div className="shellCurrentWorkspace" aria-live="polite">
          <span>Workspace</span>
          <strong>{activeItem.label}</strong>
        </div>
        <div className={`shellVoiceTools ${voicePreferences.enabled ? 'enabled' : 'muted'}`} aria-label="Global voice controls">
          <button
            className="shellVoiceToggle"
            type="button"
            aria-pressed={voicePreferences.enabled}
            onClick={toggleGlobalVoice}
          >
            <CarbonIcon path={voicePreferences.enabled ? 'actions/media-playback-start-symbolic.svg' : 'actions/media-playback-stop-symbolic.svg'} label="Voice" />
            <span>{voicePreferences.enabled ? 'Voice On' : 'Voice Off'}</span>
          </button>
          {voicePreferences.enabled ? (
            <>
              <label className="shellVoiceField">
                <span>Preset</span>
                <select
                  ref={voicePresetRef}
                  aria-label="Global voice preset"
                  value={voicePreferences.globalPresetId}
                  onChange={(event) => commitVoicePreferences((current) => ({ ...current, globalPresetId: event.target.value as VoicePreferences['globalPresetId'], presetPickerSeen: true }))}
                >
                  {VOICE_PRESETS.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}
                </select>
              </label>
              <label className="shellVoiceField compact">
                <span>Language</span>
                <select
                  aria-label="Global speech language"
                  value={voicePreferences.language || DEFAULT_VOICE_LANGUAGE}
                  onChange={(event) => commitVoicePreferences((current) => ({ ...current, language: event.target.value || DEFAULT_VOICE_LANGUAGE }))}
                >
                  {voiceLanguages.map((language) => <option key={language} value={language}>{language}</option>)}
                </select>
              </label>
              <span className="shellVoiceStatus">{activeVoicePreset.shortLabel}</span>
            </>
          ) : null}
        </div>
        <button
          className="shellThemeToggle"
          type="button"
          aria-pressed={themeMode === 'dark'}
          aria-label={themeMode === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
          title={themeMode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          onClick={toggleThemeMode}
          data-testid="shell-theme-toggle"
        >
          <CarbonIcon path={themeMode === 'dark' ? 'apps/light.svg' : 'apps/moon.svg'} label="Theme" />
          <span>{themeMode === 'dark' ? 'Dark' : 'Light'}</span>
        </button>
        <details className={`shellCostTools ${costClass}`} data-testid="shell-cost-control">
          <summary aria-label="Cost controls">
            <CarbonIcon path="actions/system-run-symbolic.svg" label="Cost" />
            <span>
              <small>MIN</small>
              <strong data-testid="shell-cost-minute">{money(costPayload?.costs?.minute_total_usd)}</strong>
            </span>
            <span>
              <small>DAY</small>
              <strong data-testid="shell-cost-day">{money(costPayload?.costs?.daily_total_usd)}</strong>
            </span>
            <span>
              <small>MONTH</small>
              <strong data-testid="shell-cost-month">{money(costPayload?.costs?.monthly_total_usd)}</strong>
            </span>
          </summary>
          <div className="shellCostPanel" role="group" aria-label="Cost threshold and pause controls">
            <div className="shellCostPanelHeader">
              <div>
                <span>{costSourceLabel}</span>
                <strong>{costStatus === 'offline' ? 'Cost unavailable' : `${costStatus.toUpperCase()} · ${percentValue(costPercent)}`}</strong>
              </div>
              <TagLike status={costClass}>{costThreshold ? `${money(costThreshold)} limit` : 'No limit'}</TagLike>
            </div>
            <div className="shellCostBreakdown">
              <span>
                <small>Dedicated</small>
                <strong>{money(categoryCost(costPayload, 'dedicated_instances', 'monthly_usd'))}</strong>
              </span>
              <span>
                <small>LLM Service</small>
                <strong>{money(categoryCost(costPayload, 'llm_service', 'monthly_usd'))}</strong>
              </span>
              <span>
                <small>Guard</small>
                <strong>{costPaused ? 'Paused' : costPayload?.threshold?.warning ? 'Warning' : 'Ready'}</strong>
              </span>
            </div>
            <div className="shellCostActions">
              <label className="shellCostThreshold">
                <span>Monthly</span>
                <input
                  data-testid="shell-cost-threshold"
                  type="number"
                  min="0"
                  step="1"
                  value={costThresholdDraft}
                  onChange={(event) => setCostThresholdDraft(event.target.value)}
                />
              </label>
              <button data-testid="shell-cost-save" type="button" onClick={() => void saveCostThreshold()}>Save</button>
              <button data-testid="shell-cost-override" type="button" disabled={!costPaused} onClick={() => void overrideCostPause()}>Override</button>
            </div>
            <p className="shellCostStatus">{costControlStatus}</p>
          </div>
        </details>
      </div>
      <div className={`shellDrawerLayer ${drawerOpen ? 'open' : ''}`} aria-hidden={!drawerOpen}>
        <button className="shellDrawerBackdrop" type="button" aria-label="Close Navigation Menu" tabIndex={-1} onClick={() => setDrawerOpen(false)} />
        <aside id="shell-navigation-drawer" ref={drawerRef} className="shellDrawer" role="dialog" aria-modal="true" aria-labelledby="shell-menu-title" data-testid="shell-navigation-drawer">
          <div className="shellDrawerHeader">
            <BrandMark testId="drawer-brand-icon" />
            <div>
              <span>Navigation</span>
              <h2 id="shell-menu-title">{platformBranding.product}</h2>
              <small>{platformBranding.platform} Console v2</small>
            </div>
            <button className="shellDrawerClose" type="button" aria-label="Close Navigation Menu" tabIndex={drawerOpen ? 0 : -1} onClick={() => setDrawerOpen(false)}>
              <CarbonIcon path="apps/close.svg" label="Close" />
            </button>
          </div>
          <nav className="drawerNav" aria-label="Primary">
            {drawerItems.map((item) => (
              <button
                key={item.key}
                ref={(node) => { drawerNavRefs.current[item.key] = node; }}
                className={active === item.key ? 'active' : ''}
                type="button"
                onClick={() => activateFromDrawer(item.key)}
                aria-current={active === item.key ? 'page' : undefined}
                tabIndex={drawerOpen ? 0 : -1}
                data-testid={`shell-nav-${item.key}`}
              >
                <CarbonIcon path={item.icon} label={item.label} />
                <span>
                  <strong>{item.label}</strong>
                  {active === item.key ? <small>{item.description}</small> : null}
                </span>
              </button>
            ))}
          </nav>
          <div className="shellDrawerUtilities" aria-label="Utilities">
            <button type="button" onClick={openQuickSwitcherFromDrawer} tabIndex={drawerOpen ? 0 : -1} data-testid="shell-drawer-switcher">
              <CarbonIcon path="actions/edit-find-symbolic.svg" label="Switch" />
              <span>Switch Workspace</span>
            </button>
            <button type="button" onClick={openSettingsWorkspace} tabIndex={drawerOpen ? 0 : -1} data-testid="shell-drawer-settings">
              <CarbonIcon path="apps/settings.svg" label="Settings" />
              <span>Settings</span>
            </button>
            <button type="button" onClick={triggerAuthFromDrawer} tabIndex={drawerOpen ? 0 : -1} data-testid="shell-drawer-auth">
              <CarbonIcon path="apps/user--settings.svg" label={signedIn ? 'Sign Out' : 'Sign In'} />
              <span>{signedIn ? 'Sign Out' : 'Sign In'}</span>
            </button>
          </div>
        </aside>
      </div>
      <main className="mainSurface">
        {active === 'chat' ? <ChatPage key={`chat-${workspaceResetVersion}`} voicePreferences={voicePreferences} onVoicePreferencesChange={commitVoicePreferences} /> : null}
        {active === 'code' ? <CodePage key={`code-${workspaceResetVersion}`} /> : null}
        {active === 'research' ? <ResearchPage key={`research-${workspaceResetVersion}`} /> : null}
        {active === 'create' ? <CreatePage key={`create-${workspaceResetVersion}`} /> : null}
        {active === 'advanced' ? <AdvancedPage key={`advanced-${workspaceResetVersion}`} /> : null}
      </main>
      <ModelDetailHost />
    </div>
  );
}
