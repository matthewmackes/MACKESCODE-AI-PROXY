import { ChangeEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AdvancedPage, CarbonIcon, ChatPage, CodePage, CreatePage, HomeSummary, ModelsPage, ResearchPage, V2_ADVANCED_TAB_EVENT, V2_RESETTABLE_WORKSPACE_KEYS, V2_WORKSPACE_SESSION_KEYS, WHATS_NEW_DISMISSED_KEY, WhatsNewModal } from './pages/HeroPages';
import { getModels, getWhatsNew } from './api/v2';
import { getOperate, OperatePayload } from './api/generated/v2Client';
import { V2_FATAL_ERROR_DIAGNOSTIC_KEY } from './components/ShellErrorBoundary';

type NavItem = {
  key: string;
  label: string;
  icon: string;
  description: string;
};

const navItems: NavItem[] = [
  { key: 'chat', label: 'Chat', icon: 'actions/call-start-symbolic.svg', description: 'Autonomous command center' },
  { key: 'code', label: 'Code', icon: 'apps/utilities-terminal-symbolic.svg', description: 'Terminal, sessions, screenshots' },
  { key: 'research', label: 'Research', icon: 'actions/edit-find-symbolic.svg', description: 'Search and evidence' },
  { key: 'create', label: 'Create', icon: 'actions/document-new-symbolic.svg', description: 'Image creation studio' },
  { key: 'models', label: 'Models', icon: 'categories/applications-science-symbolic.svg', description: 'LLM showcase' },
  { key: 'advanced', label: 'Advanced', icon: 'actions/document-properties-symbolic.svg', description: 'Owner/admin tools' }
];

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

function activeFromHash(): string {
  if (typeof window === 'undefined') return navItems[0].key;
  const key = window.location.hash.replace(/^#\/?/, '').split(/[/?&]/)[0].toLowerCase();
  return navItems.some((item) => item.key === key) ? key : navItems[0].key;
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

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function records(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((row) => row && typeof row === 'object') as Array<Record<string, unknown>> : [];
}

function metric(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

function plural(count: number, singular: string, pluralLabel = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralLabel}`;
}

function text(value: unknown, fallback = ''): string {
  return value === undefined || value === null || value === '' ? fallback : String(value);
}

async function copyText(text: string): Promise<void> {
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

function downloadText(filename: string, text: string, type: string): void {
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

function shouldTriggerFatalDiagnostic(): boolean {
  try {
    return window.sessionStorage.getItem(V2_FATAL_ERROR_DIAGNOSTIC_KEY) === '1';
  } catch {
    return false;
  }
}

function ReleaseReadinessPulse({ payload, loading, error, onOpen }: { payload?: OperatePayload; loading: boolean; error: unknown; onOpen: () => void }) {
  const releaseCandidate = record(payload?.release_candidate);
  const summary = record(releaseCandidate.summary);
  const operatorHandoff = record(releaseCandidate.operator_handoff);
  const operatorHandoffItems = records(operatorHandoff.items);
  const topOperatorItem = operatorHandoffItems[0] || {};
  const failedChecks = records(releaseCandidate.checks).filter((check) => check.status !== 'passed');
  const failedReasonRows = failedChecks.slice(0, 3).map((check) => {
    const evidence = record(check.evidence);
    const checkId = text(check.id);
    const title = text(check.title || check.id, 'Readiness check');
    let detail = text(check.severity, 'advisory');
    if (checkId === 'config_drift') {
      const blockingDrift = metric(evidence.blocking_drift_count);
      const advisoryDrift = metric(evidence.advisory_drift_count);
      detail = blockingDrift > 0 ? `${plural(blockingDrift, 'blocking drift item')}` : `${plural(advisoryDrift, 'low-risk drift item')}`;
    } else if (checkId === 'needs_operator') {
      detail = `${plural(metric(evidence.open_items), 'operator item')} open`;
    } else if (checkId === 'worklist') {
      detail = `${plural(metric(evidence.pending_p1_estimate), 'priority item')} open`;
    }
    return { id: checkId || title, title, detail };
  });
  const topOperatorTitle = text(topOperatorItem.item);
  const topOperatorOwner = text(topOperatorItem.owner, 'Operator');
  const topOperatorRank = text(topOperatorItem.priority_rank, '1');
  const ready = releaseCandidate.ready === true;
  const checks = metric(summary.checks);
  const blocking = metric(summary.blocking_failed);
  const advisory = metric(summary.advisory_failed);
  const operatorItems = metric(operatorHandoff.open_count);
  const showTopOperatorAction = blocking === 0 && operatorItems > 0 && Boolean(topOperatorTitle);
  const topOperatorReason = showTopOperatorAction
    ? [{
        id: 'operator-top-action',
        title: `#${topOperatorRank} Operator Action`,
        detail: `${topOperatorTitle} · ${topOperatorOwner}`
      }]
    : [];
  const reasonRows = topOperatorReason.length
    ? [...topOperatorReason, ...failedReasonRows.filter((row) => row.id !== 'needs_operator').slice(0, 2)]
    : failedReasonRows.slice(0, 3);
  const status = error ? 'error' : loading ? 'syncing' : blocking > 0 ? 'blocking' : advisory > 0 ? 'advisory' : ready ? 'ready' : 'review';
  const label = error ? 'Readiness Unavailable' : loading ? 'Syncing Readiness' : blocking > 0 ? 'Blocked' : operatorItems > 0 ? 'Ready With Handoff' : advisory > 0 ? 'Ready With Advisories' : ready ? 'Release Ready' : 'Review Needed';
  const detail = error
    ? 'Open Operate for diagnostics'
    : loading
      ? 'Checking release posture'
      : showTopOperatorAction
        ? `Next #${topOperatorRank}: ${topOperatorTitle}`
        : operatorItems > 0
          ? `${plural(operatorItems, 'operator item')} open`
          : advisory > 0 && reasonRows.length
          ? `${reasonRows[0].title}: ${reasonRows[0].detail}`
          : checks > 0
            ? `${plural(checks, 'check')} evaluated`
            : 'Awaiting release checks';
  return (
    <button className={`readinessPulse ${status}`} type="button" data-testid="shell-readiness-pulse" onClick={onOpen} aria-label={`${label}. ${detail}. Open Operate`}>
      <span className="readinessPulseMark">
        <CarbonIcon path="apps/ai-governance--tracked.svg" label="Readiness" />
      </span>
      <span className="readinessPulseBody">
        <strong>{label}</strong>
        <small>{detail}</small>
      </span>
      <span className="readinessPulseMetrics" aria-label={`${blocking} blocking, ${advisory} advisory, ${checks} checks`}>
        <span><b>{blocking}</b> block</span>
        <span><b>{advisory}</b> adv</span>
        <span><b>{checks}</b> checks</span>
      </span>
      {!loading && !error && reasonRows.length ? (
        <span className="readinessPulseReasons" data-testid="shell-readiness-reasons">
          {reasonRows.map((row) => (
            <span className="readinessPulseReason" data-testid="shell-readiness-reason" key={row.id}>
              <b>{row.title}</b>
              <small>{row.detail}</small>
            </span>
          ))}
        </span>
      ) : null}
    </button>
  );
}

export default function App() {
  if (shouldTriggerFatalDiagnostic()) {
    throw new Error('V2 shell diagnostic render failure');
  }
  const [active, setActive] = useState(activeFromHash);
  const [quickOpen, setQuickOpen] = useState(false);
  const [quickQuery, setQuickQuery] = useState('');
  const [quickHighlightedIndex, setQuickHighlightedIndex] = useState(0);
  const [recentWorkspaceKeys, setRecentWorkspaceKeys] = useState(loadRecentWorkspaceKeys);
  const [workspaceResetVersion, setWorkspaceResetVersion] = useState(0);
  const [savedStateVersion, setSavedStateVersion] = useState(0);
  const [showStartupWhatsNew, setShowStartupWhatsNew] = useState(() => {
    try {
      return window.sessionStorage.getItem(WHATS_NEW_DISMISSED_KEY) !== '1';
    } catch {
      return true;
    }
  });
  const modelPayload = useQuery({ queryKey: ['models-shell'], queryFn: getModels, retry: false });
  const whatsNew = useQuery({ queryKey: ['whats-new'], queryFn: getWhatsNew, retry: false });
  const operatePayload = useQuery({ queryKey: ['operate-shell-readiness'], queryFn: getOperate, refetchInterval: 30000, retry: false });
  const activeItem = useMemo(() => navItems.find((item) => item.key === active) || navItems[0], [active]);
  const quickInputRef = useRef<HTMLInputElement | null>(null);
  const stateImportRef = useRef<HTMLInputElement | null>(null);
  const quickItems = useMemo(() => {
    const query = quickQuery.trim().toLowerCase();
    if (!query) return navItems;
    return navItems.filter((item) => `${item.label} ${item.description}`.toLowerCase().includes(query));
  }, [quickQuery]);
  const recentItems = useMemo(() => recentWorkspaceKeys.map((key) => navItemForKey(key)).filter((item): item is NavItem => Boolean(item)).filter((item) => item.key !== active).slice(0, QUICK_SWITCHER_RECENT_LIMIT), [active, recentWorkspaceKeys]);
  const highlightedQuickItem = quickItems[quickHighlightedIndex] || quickItems[0];
  const savedStateCount = useMemo(savedWorkspaceStateCount, [quickOpen, savedStateVersion]);
  const [savedStateStatus, setSavedStateStatus] = useState(savedStateCount ? 'State ready' : 'No saved state');
  const [workspaceLinkStatus, setWorkspaceLinkStatus] = useState('Link ready');
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
  const activate = (key: string) => {
    recordRecentWorkspace(key);
    setActive(key);
    const nextHash = `#${key}`;
    if (window.location.hash !== nextHash) window.history.pushState(null, '', nextHash);
  };
  const openOperateWorkspace = () => {
    try {
      window.sessionStorage.setItem(V2_WORKSPACE_SESSION_KEYS.advancedTab, 'operate');
    } catch {
      // Advanced can still be opened even if the browser blocks session storage.
    }
    activate('advanced');
    window.dispatchEvent(new CustomEvent(V2_ADVANCED_TAB_EVENT, { detail: { tab: 'operate' } }));
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
    downloadText(`mde-llm-proxy-workspace-state-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`, text, 'application/json;charset=utf-8');
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
      setActive(snapshot.active_workspace);
      const nextHash = `#${snapshot.active_workspace}`;
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
  return (
    <div className="carbonShell">
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
                <button className="closeButton inline" type="button" aria-label="Close Switch Workspace" onClick={closeQuickSwitcher}>x</button>
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
              )) : <div className="emptyState">No workspace matches this search.</div>}
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
      <aside className="sideRail">
        <div className="brandBlock">
          <span className="brandMark">M</span>
          <div>
            <strong>MDE</strong>
            <span>LLM-PROXY Console v2</span>
          </div>
          <button className="railIconButton" type="button" aria-label="Open Switch Workspace" onClick={() => setQuickOpen(true)}>
            <CarbonIcon path="actions/edit-find-symbolic.svg" label="Switch" />
          </button>
        </div>
        <nav className="heroNav" aria-label="Primary">
          {navItems.map((item) => (
            <button key={item.key} className={active === item.key ? 'active' : ''} type="button" onClick={() => activate(item.key)} aria-current={active === item.key ? 'page' : undefined}>
              <CarbonIcon path={item.icon} label={item.label} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="railSummary">
          <span>{activeItem.description}</span>
          <ReleaseReadinessPulse payload={operatePayload.data} loading={operatePayload.isLoading} error={operatePayload.error} onOpen={openOperateWorkspace} />
          <HomeSummary models={modelPayload.data?.models || []} />
        </div>
      </aside>
      <main className="mainSurface">
        {active === 'chat' ? <ChatPage key={`chat-${workspaceResetVersion}`} /> : null}
        {active === 'code' ? <CodePage key={`code-${workspaceResetVersion}`} /> : null}
        {active === 'research' ? <ResearchPage key={`research-${workspaceResetVersion}`} /> : null}
        {active === 'create' ? <CreatePage key={`create-${workspaceResetVersion}`} /> : null}
        {active === 'models' ? <ModelsPage key={`models-${workspaceResetVersion}`} /> : null}
        {active === 'advanced' ? <AdvancedPage key={`advanced-${workspaceResetVersion}`} /> : null}
      </main>
    </div>
  );
}
