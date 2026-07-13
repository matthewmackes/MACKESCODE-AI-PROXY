import { ChangeEvent, ClipboardEvent, DragEvent, Fragment, KeyboardEvent, Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  CodeAttachment,
  discoverModels,
  getChatPayload,
  getCodePayload,
  getCreatePayload,
  getResearchReport,
  getModels,
  getResearchPayload,
  getSpeechStatus,
  getWhatsNew,
  ModelCard,
  ResearchClaim,
  ResearchDossier,
  ResearchEvidence,
  ResearchModelOutput,
  ResearchModelRole,
  ResearchModelStrategy,
  ResearchPayload,
  ResearchReportPacket,
  ResearchSourceCoverage,
  WhatsNewPayload,
  deleteCodeAttachment,
  reviewCodeImages,
  runChat,
  runCreateImages,
  runResearchSearch,
  SpeechStatusPayload,
  synthesizeSpeech,
  sendCodeSession,
  startCodeSession,
  updateResearchPins,
  uploadCodeAttachment
} from '../api/v2';
import { getMeCapabilities, getOperate, getTmuxWorkspace } from '../api/generated/v2Client';
import type { OperatePayload, TmuxWorkspacePayload } from '../api/generated/v2Client';
import { applyThemeMode, useThemeMode } from '../theme';
import { briefDeliveryActions, copyText } from '../utils/delivery';
import { errorText } from '../utils/errors';
import { readableStatus } from '../utils/format';
import { CarbonIcon, ModelCardSelect, ModelIdentityCard, ModelLogo, V2_MODEL_DETAIL_EVENT, modelHealthLabel, useBrandSvg } from '../components/modelCard';
import { useModelFavorites } from '../favorites';
import {
  DEFAULT_VOICE_LANGUAGE,
  loadVoicePreferences,
  saveVoicePreferences,
  setModelVoicePreset,
  VoicePreferences,
  voiceInstructionForPreset,
  voicePresetForModel
} from '../voicePreferences';

export { CarbonIcon } from '../components/modelCard';

export const WHATS_NEW_DISMISSED_KEY = 'matts-v2-whats-new-dismissed';
export const V2_WORKSPACE_SESSION_KEYS = {
  chatTranscript: 'matts-v2-chat-transcript',
  chatUiState: 'matts-v2-chat-ui-state',
  codeWorkspace: 'matts-v2-code-workspace',
  researchWorkspace: 'matts-v2-research-workspace',
  createWorkspace: 'matts-v2-create-workspace',
  modelsShowcase: 'matts-v2-models-showcase',
  advancedTab: 'matts-v2-advanced-tab',
} as const;
export const V2_ADVANCED_TAB_EVENT = 'matts-v2-advanced-tab-change';
export const V2_AUTH_REQUIRED_EVENT = 'matts-v2-auth-required';
export const V2_ADVANCED_LAZY_DELAY_KEY = 'matts-v2-advanced-lazy-delay-ms';
export const V2_RESETTABLE_WORKSPACE_KEYS = [
  V2_WORKSPACE_SESSION_KEYS.chatTranscript,
  V2_WORKSPACE_SESSION_KEYS.chatUiState,
  V2_WORKSPACE_SESSION_KEYS.codeWorkspace,
  V2_WORKSPACE_SESSION_KEYS.researchWorkspace,
  V2_WORKSPACE_SESSION_KEYS.createWorkspace,
  V2_WORKSPACE_SESSION_KEYS.modelsShowcase,
  V2_WORKSPACE_SESSION_KEYS.advancedTab,
] as const;

function delayedAdvancedImport<T>(loader: () => Promise<T>): Promise<T> {
  if (typeof window === 'undefined') return loader();
  const delay = Math.min(2000, Math.max(0, Number(window.sessionStorage.getItem(V2_ADVANCED_LAZY_DELAY_KEY) || 0)));
  if (!delay) return loader();
  return new Promise((resolve, reject) => {
    window.setTimeout(() => loader().then(resolve, reject), delay);
  });
}

const ConsolePage = lazy(() => delayedAdvancedImport(() => import('./ConsolePage')));
const ObservePage = lazy(() => delayedAdvancedImport(() => import('./ObservePage')));
const OperatePage = lazy(() => delayedAdvancedImport(() => import('./OperatePage')));
const RunPage = lazy(() => delayedAdvancedImport(() => import('./RunPage')));
const AdvancedThemeProvider = lazy(() => delayedAdvancedImport(() => import('../components/AdvancedThemeProvider')));
const TuiTerminal = lazy(() => delayedAdvancedImport(() => import('../components/TuiTerminal')));
const TmuxTerminal = lazy(() => delayedAdvancedImport(() => import('../components/TmuxTerminal')));

function asText(value: unknown, fallback = ''): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

function responseObject(payload: unknown): Record<string, unknown> {
  const row = payload && typeof payload === 'object' ? payload as Record<string, unknown> : {};
  return row.response && typeof row.response === 'object' ? row.response as Record<string, unknown> : row;
}

function diagnosticWarningText(response: Record<string, unknown>): string {
  const diagnostics = response.diagnostics && typeof response.diagnostics === 'object' ? response.diagnostics as Record<string, unknown> : {};
  const warnings = Array.isArray(diagnostics.warnings) ? diagnostics.warnings : [];
  const warningLines = warnings
    .filter((warning): warning is Record<string, unknown> => Boolean(warning && typeof warning === 'object'))
    .map((warning) => asText(warning.message || warning.code))
    .filter(Boolean);
  const stopReason = asText(diagnostics.stop_reason);
  if (!warningLines.length && !stopReason) return '';
  const trace = response.trace && typeof response.trace === 'object' ? response.trace as Record<string, unknown> : {};
  const traceId = asText(trace.console_trace_id || response.trace_id);
  return [
    'Model response diagnostic',
    ...warningLines.map((line) => `- ${line}`),
    stopReason ? `- Stop reason: ${stopReason}` : '',
    traceId ? `- Trace: ${traceId}` : '',
  ].filter(Boolean).join('\n');
}

function responseText(payload: unknown): string {
  const response = responseObject(payload);
  if (Object.prototype.hasOwnProperty.call(response, 'text')) {
    const text = asText(response.text);
    return text.trim() ? text : diagnosticWarningText(response);
  }
  const readable = asText(response.text || response.content || response.message || response.answer);
  if (readable.trim()) return readable;
  return diagnosticWarningText(response) || 'The model returned a response with no readable text. Open Raw payload for the full detail.';
}

function responseHasDiagnostics(payload: unknown): boolean {
  const response = responseObject(payload);
  const diagnostics = response.diagnostics && typeof response.diagnostics === 'object' ? response.diagnostics as Record<string, unknown> : {};
  return Boolean(asText(diagnostics.output_format_issue) || (Array.isArray(diagnostics.warnings) && diagnostics.warnings.length));
}

function chatResponseMetadata(payload: unknown): string {
  const response = responseObject(payload);
  const routing = response.routing && typeof response.routing === 'object' ? response.routing as Record<string, unknown> : {};
  const trace = response.trace && typeof response.trace === 'object' ? response.trace as Record<string, unknown> : {};
  const cost = response.cost && typeof response.cost === 'object' ? response.cost as Record<string, unknown> : {};
  const costValue = Number(cost.total_cost_usd);
  const parts = [
    asText(routing.used || routing.requested),
    Number.isFinite(costValue) ? `$${costValue.toFixed(costValue < 0.01 ? 6 : 4)}` : '',
    asText(trace.console_trace_id || response.trace_id),
  ].filter(Boolean);
  return parts.join(' · ');
}

const STATUS_PANEL_LABELS: Record<string, string> = {
  neutral: 'Status',
  loading: 'Loading',
  error: 'Error',
  success: 'Ready',
};

function StatusPanel({ tone = 'neutral', title, detail }: { tone?: 'neutral' | 'loading' | 'error' | 'success'; title: string; detail?: string }) {
  return (
    <div className={`statusPanel ${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <span>{STATUS_PANEL_LABELS[tone] || 'Status'}</span>
      <strong>{title}</strong>
      {detail ? <p>{detail}</p> : null}
    </div>
  );
}

function authLikeError(error: unknown): boolean {
  return /403|missing_permission|anonymous|token/i.test(errorText(error));
}

function numeric(value: unknown): number {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function recordValues(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((row) => row && typeof row === 'object') as Array<Record<string, unknown>> : [];
}

function nonNegativeMetric(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

function pluralize(count: number, singular: string, pluralLabel = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralLabel}`;
}

function compactText(value: unknown, fallback = ''): string {
  return value === undefined || value === null || value === '' ? fallback : String(value);
}

function useTextModels(models: ModelCard[] | undefined) {
  return useMemo(() => (models || []).filter((model) => model.type === 'text' && model.route_enabled), [models]);
}

function ModelSelect({ models, value, onChange, label = 'Model' }: { models: ModelCard[]; value: string; onChange: (value: string) => void; label?: string }) {
  return <ModelCardSelect models={models} value={value} onChange={onChange} label={label} />;
}

export function WhatsNewModal({ data, onClose }: { data: WhatsNewPayload; onClose: () => void }) {
  const newModelsRef = useRef<HTMLElement>(null);
  const attentionRef = useRef<HTMLElement>(null);
  const digitalOceanRef = useRef<HTMLElement>(null);
  const scrollToSection = (target: { current: HTMLElement | null }) => {
    target.current?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  };
  return (
    <div className="modalBackdrop">
      <div className="whatsNewModal" role="dialog" aria-modal="true" aria-labelledby="whats-new-title">
        <div className="whatsNewHeader">
          <div>
            <p className="eyebrow">Startup Alert</p>
            <h2 id="whats-new-title">Whats New</h2>
            <p>{data.summary.new_models || 0} new models · {data.summary.attention || 0} need attention · {data.summary.route_enabled || 0} routable.</p>
          </div>
          <button className="closeButton modalCloseButton" type="button" aria-label="Close Whats New" onClick={onClose}>
            <CarbonIcon path="actions/window-close-symbolic.svg" label="Close" />
          </button>
        </div>
        <div className="whatsNewJumpStrip" aria-label="Whats New sections">
          <button type="button" onClick={() => scrollToSection(newModelsRef)}><CarbonIcon path="apps/list--checked.svg" label="New models" />New <strong>{data.new_models.length}</strong></button>
          <button type="button" onClick={() => scrollToSection(attentionRef)}><CarbonIcon path="apps/information--filled.svg" label="Needs attention" />Attention <strong>{data.attention.length}</strong></button>
          <button type="button" onClick={() => scrollToSection(digitalOceanRef)}><CarbonIcon path="actions/insert-link-symbolic.svg" label="DigitalOcean links" />DigitalOcean <strong>{data.digitalocean.links.length}</strong></button>
        </div>
        <div className="whatsNewSections">
          <section ref={newModelsRef}>
            <div className="whatsNewSectionHeader">
              <span>New models</span>
              <strong>{data.new_models.length}</strong>
            </div>
            {data.new_models.length ? (
              <div className="modelAlertGrid">
                {data.new_models.slice(0, 6).map((model) => <ModelIdentityCard key={model.id} model={model} size="small" />)}
              </div>
            ) : <div className="emptyState">No newly discovered models in this window.</div>}
          </section>
          <section ref={attentionRef}>
            <div className="whatsNewSectionHeader">
              <span>Need attention</span>
              <strong>{data.attention.length}</strong>
            </div>
            {data.attention.length ? (
              <div className="modelAlertGrid">
                {data.attention.slice(0, 6).map((model) => <ModelIdentityCard key={model.id} model={model} size="small" />)}
              </div>
            ) : <div className="emptyState">No model access issues reported.</div>}
          </section>
          <section ref={digitalOceanRef}>
            <div className="whatsNewSectionHeader">
              <span>DigitalOcean LLM links</span>
              <strong>{data.digitalocean.links.length}</strong>
            </div>
            <div className="linkGrid">{data.digitalocean.links.map((link) => <a key={link.url} href={link.url} target="_blank" rel="noreferrer">{link.label}</a>)}</div>
          </section>
        </div>
      </div>
    </div>
  );
}

function ModelArtworkGallery({ model }: { model: ModelCard }) {
  const sources = model.artwork?.sources || [];
  const backgroundLabel = String(model.artwork?.background || 'generated_brand_panel').replace(/_/g, ' ');
  const brandSvg = useBrandSvg(model);
  return (
    <div className="modelArtworkGallery" aria-label="Artwork source gallery">
      <div className="artworkIdentity" style={{ ['--accent' as string]: model.nation_palette?.accent || '#0f62fe', ['--secondary' as string]: model.nation_palette?.secondary || '#da1e28', ['--surface' as string]: model.nation_palette?.surface || '#edf5ff' }}>
        <ModelLogo model={model} size="xl" />
        <div>
          <span>Artwork Preview</span>
          <strong>{model.company}</strong>
          <p>{model.family} · {model.training_nation}</p>
        </div>
        {model.artwork?.brand_url ? <a className="artworkBrandLink" href={model.artwork.brand_url} target="_blank" rel="noreferrer">Brand Site</a> : <span className="artworkBrandLink muted">Generated Identity</span>}
      </div>
      <div className="artworkFacts" aria-label="Artwork metadata">
        <div><span>Logo</span><strong>{brandSvg ? 'Bundled SVG' : model.artwork?.logo ? 'Generated from source' : 'Generated initials'}</strong></div>
        <div><span>Background</span><strong>{backgroundLabel}</strong></div>
        <div><span>Sources</span><strong>{sources.length.toLocaleString()}</strong></div>
        <div><span>Policy</span><strong>{model.artwork?.policy_notes ? 'Tracked' : 'Default'}</strong></div>
      </div>
      <div className="artworkSources" aria-label="Artwork sources">
        <div className="artworkSourcesHeader">
          <span>Artwork Sources</span>
          <strong>{sources.length ? `${sources.length} tracked` : 'No external source'}</strong>
        </div>
        {sources.length ? sources.map((source, index) => {
          const url = source.source_url || source.url || '';
          const sourceLabel = source.source || url || 'Generated source';
          return (
            <div className="artworkSourceRow" key={`${source.kind || 'source'}-${index}`}>
              <span>{String(source.kind || 'source').replace(/_/g, ' ')}</span>
              {url ? <a href={url} target="_blank" rel="noreferrer">{sourceLabel}</a> : <strong>{sourceLabel}</strong>}
              {source.usage_notes ? <p>{source.usage_notes}</p> : null}
            </div>
          );
        }) : (
          <div className="artworkSourceRow">
            <span>fallback</span>
            <strong>Generated model initials</strong>
            <p>No public artwork has been configured for this model family.</p>
          </div>
        )}
        {model.artwork?.policy_notes ? <p className="artworkPolicyNote">{model.artwork.policy_notes}</p> : null}
      </div>
    </div>
  );
}

function ModelInspector({ model }: { model: ModelCard }) {
  const status = model.route_enabled ? 'Routable' : readableStatus(model.access_status);
  const facts = [
    ['Provider', model.provider],
    ['Company', model.company],
    ['Training Nation', model.training_nation],
    ['Family', model.family],
    ['Type', model.type],
    ['Access', status],
    ['Context', `${model.context_window.toLocaleString()} tokens`],
    ['Output', `${model.max_output_tokens.toLocaleString()} tokens`],
    ['Cost', model.cost_label],
    ['Health', modelHealthLabel(model)],
    ['Artwork', `${model.artwork?.sources?.length || 0} source${model.artwork?.sources?.length === 1 ? '' : 's'}`],
  ];
  return (
    <section className="modelInspector" aria-label="Model detail inspector" style={{ ['--accent' as string]: model.nation_palette?.accent || '#0f62fe', ['--secondary' as string]: model.nation_palette?.secondary || '#da1e28', ['--surface' as string]: model.nation_palette?.surface || '#edf5ff', ['--paletteText' as string]: model.nation_palette?.text || '#161616' }}>
      <div className="modelInspectorHeader">
        <ModelLogo model={model} size="large" />
        <div>
          <span>Model Inspector</span>
          <h2>{model.display_name}</h2>
          <p>{model.use_case}</p>
        </div>
        <span className={`statusPill ${model.route_enabled ? 'ok' : 'warn'}`}>{status}</span>
      </div>
      <div className="modelInspectorFacts">
        {facts.map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      <div className="modelInspectorPalette" aria-label="Training nation palette">
        <span style={{ background: model.nation_palette?.accent || '#0f62fe', color: '#ffffff' }}>Accent</span>
        <span style={{ background: model.nation_palette?.secondary || '#da1e28', color: '#ffffff' }}>Secondary</span>
        <span style={{ background: model.nation_palette?.surface || '#edf5ff', color: model.nation_palette?.text || '#161616' }}>{model.nation_palette?.name || 'Palette'}</span>
      </div>
      <ModelArtworkGallery model={model} />
    </section>
  );
}

export function ModelDetailHost() {
  const [model, setModel] = useState<ModelCard | null>(null);
  useEffect(() => {
    const onOpen = (event: Event) => {
      const detail = (event as CustomEvent<{ model?: ModelCard }>).detail;
      if (detail?.model) setModel(detail.model);
    };
    window.addEventListener(V2_MODEL_DETAIL_EVENT, onOpen);
    return () => window.removeEventListener(V2_MODEL_DETAIL_EVENT, onOpen);
  }, []);
  useEffect(() => {
    if (!model) return;
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') setModel(null);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [model]);
  if (!model) return null;
  return (
    <div className="modalBackdrop modelDetailBackdrop" data-testid="model-detail-dialog">
      <div className="modelDetailDialog" role="dialog" aria-modal="true" aria-label={`${model.display_name} details`}>
        <button className="closeButton inline modelDetailClose" type="button" aria-label="Close Model Details" onClick={() => setModel(null)}>
          <CarbonIcon path="actions/window-close-symbolic.svg" label="Close" />
        </button>
        <ModelInspector model={model} />
      </div>
    </div>
  );
}

const MODEL_COMPARE_ROWS: Array<[string, (model: ModelCard) => string]> = [
  ['Provider', (model: ModelCard) => model.provider],
  ['Company', (model: ModelCard) => model.company],
  ['Training Nation', (model: ModelCard) => model.training_nation],
  ['Status', (model: ModelCard) => model.route_enabled ? 'Routable' : readableStatus(model.access_status)],
  ['Context', (model: ModelCard) => `${model.context_window.toLocaleString()} tokens`],
  ['Output', (model: ModelCard) => `${model.max_output_tokens.toLocaleString()} tokens`],
  ['Type', (model: ModelCard) => model.type],
  ['Cost', (model: ModelCard) => model.cost_label],
  ['Health', (model: ModelCard) => modelHealthLabel(model)],
  ['Palette', (model: ModelCard) => model.nation_palette?.name || 'Default'],
  ['Artwork Sources', (model: ModelCard) => `${model.artwork?.sources?.length || 0}`],
];

function markdownCell(value: unknown): string {
  return String(value ?? '').replace(/\|/g, '\\|').replace(/\s+/g, ' ').trim() || 'n/a';
}

function modelCompareBriefMarkdown(models: ModelCard[]): string {
  const header = ['Detail', ...models.map((model) => model.display_name)].map(markdownCell).join(' | ');
  const separator = ['---', ...models.map(() => '---')].join(' | ');
  const matrix = MODEL_COMPARE_ROWS.map(([label, value]) => [label, ...models.map(value)].map(markdownCell).join(' | '));
  const notes = models.flatMap((model) => [
    `### ${model.display_name}`,
    `- Provider: ${model.provider}`,
    `- Company: ${model.company}`,
    `- Training Nation: ${model.training_nation}`,
    `- Family: ${model.family}`,
    `- Status: ${model.route_enabled ? 'Routable' : readableStatus(model.access_status)}`,
    `- Use Case: ${model.use_case}`,
    `- Cost: ${model.cost_label}`,
    `- Artwork: ${model.artwork?.brand_url || model.artwork?.background || 'Generated identity'}`,
    `- Artwork Sources: ${model.artwork?.sources?.length || 0}`,
    '',
  ]);
  return [
    '# Model Compare Brief',
    '',
    `Generated: ${new Date().toISOString()}`,
    `Selected Models: ${models.length}`,
    '',
    '## Matrix',
    '',
    header,
    separator,
    ...matrix,
    '',
    '## Model Notes',
    '',
    ...notes,
  ].join('\n');
}

function ModelCompareTray({ models, onRemove, onClear }: { models: ModelCard[]; onRemove: (id: string) => void; onClear: () => void }) {
  const [briefStatus, setBriefStatus] = useState('Brief Ready');
  const brief = useMemo(() => modelCompareBriefMarkdown(models), [models]);
  useEffect(() => {
    if (models.length) setBriefStatus('Brief Ready');
  }, [brief, models.length]);
  if (!models.length) return null;
  const { copyBrief, downloadBrief } = briefDeliveryActions(brief, 'mde-llm-proxy-model-compare-brief', setBriefStatus, {
    copied: 'Copied',
    copyFailed: 'Copy failed',
    downloaded: 'Downloaded',
  });
  return (
    <section className="modelCompareTray" aria-label="Model comparison tray">
      <div className="modelCompareHeader">
        <div>
          <span>Model Compare</span>
          <strong>{models.length} selected</strong>
        </div>
        <div className="modelCompareActions" aria-label="Model compare brief actions">
          <span>{briefStatus}</span>
          <button className="secondaryButton" type="button" onClick={() => void copyBrief()}>Copy Brief</button>
          <button className="secondaryButton" type="button" onClick={downloadBrief}>Download Brief</button>
          <button className="secondaryButton" type="button" onClick={onClear}>Clear Compare</button>
        </div>
      </div>
      <div className="modelCompareGrid" style={{ ['--compare-count' as string]: models.length }}>
        <div className="modelCompareLabel">Model</div>
        {models.map((model) => (
          <div className="modelCompareModel" key={model.id}>
            <ModelIdentityCard
              model={model}
              size="small"
              showFavorite={false}
              trailing={(
                <button className="mdlCardInfo" type="button" aria-label={`Remove ${model.display_name} from compare`} onClick={() => onRemove(model.id)}>
                  <CarbonIcon path="actions/list-remove-symbolic.svg" label="Remove" />
                </button>
              )}
            />
          </div>
        ))}
        {MODEL_COMPARE_ROWS.map(([label, value]) => (
          <Fragment key={String(label)}>
            <div className="modelCompareLabel">{String(label)}</div>
            {models.map((model) => <div className="modelCompareCell" key={`${model.id}-${label}`}>{(value as (model: ModelCard) => string)(model)}</div>)}
          </Fragment>
        ))}
      </div>
    </section>
  );
}

type ModelsShowcaseState = {
  filter: string;
  statusFilter: string;
  sortMode: string;
  inspectedModelId: string;
  compareIds: string[];
};

const MODELS_SHOWCASE_SESSION_KEY = V2_WORKSPACE_SESSION_KEYS.modelsShowcase;
const MODEL_COMPARE_LIMIT = 4;
const MODEL_STATUS_FILTERS = ['all', 'routable', 'new', 'attention', 'text', 'image'];
const MODEL_SORT_MODES = ['route', 'nation', 'company', 'name'];

function emptyModelsShowcaseState(): ModelsShowcaseState {
  return { filter: '', statusFilter: 'all', sortMode: 'route', inspectedModelId: '', compareIds: [] };
}

function loadModelsShowcaseState(): ModelsShowcaseState {
  if (typeof window === 'undefined') return emptyModelsShowcaseState();
  try {
    const raw = window.sessionStorage.getItem(MODELS_SHOWCASE_SESSION_KEY);
    if (!raw) return emptyModelsShowcaseState();
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return emptyModelsShowcaseState();
    const row = parsed as Record<string, unknown>;
    const statusFilter = asText(row.statusFilter, 'all');
    const sortMode = asText(row.sortMode, 'route');
    return {
      filter: asText(row.filter),
      statusFilter: MODEL_STATUS_FILTERS.includes(statusFilter) ? statusFilter : 'all',
      sortMode: MODEL_SORT_MODES.includes(sortMode) ? sortMode : 'route',
      inspectedModelId: asText(row.inspectedModelId),
      compareIds: normalizeStringArray(row.compareIds).slice(0, MODEL_COMPARE_LIMIT),
    };
  } catch {
    return emptyModelsShowcaseState();
  }
}

function hasModelsShowcaseState(state: ModelsShowcaseState): boolean {
  return Boolean(
    state.filter.trim() ||
    state.statusFilter !== 'all' ||
    state.sortMode !== 'route' ||
    state.inspectedModelId.trim() ||
    state.compareIds.length
  );
}

function saveModelsShowcaseState(state: ModelsShowcaseState): void {
  if (typeof window === 'undefined') return;
  try {
    if (!hasModelsShowcaseState(state)) {
      window.sessionStorage.removeItem(MODELS_SHOWCASE_SESSION_KEY);
      return;
    }
    window.sessionStorage.setItem(MODELS_SHOWCASE_SESSION_KEY, JSON.stringify({
      ...state,
      compareIds: state.compareIds.slice(0, MODEL_COMPARE_LIMIT),
    }));
  } catch {
    // Browser storage is a convenience, not a dependency for the showcase.
  }
}

type ChatDeliveryState = 'sending' | 'failed';
type ChatMessage = {
  id?: string;
  role: string;
  content: string;
  model?: string;
  company?: string;
  accent?: string;
  createdAt?: string;
  delivery?: ChatDeliveryState;
  metadata?: string;
  diagnostic?: boolean;
  diagnosticDetail?: string;
};
type BrowserSpeechRecognition = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: unknown) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};
type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition;
type ChatUiState = {
  selectedModel: string;
};
const CHAT_TRANSCRIPT_SESSION_KEY = V2_WORKSPACE_SESSION_KEYS.chatTranscript;
const CHAT_UI_STATE_SESSION_KEY = V2_WORKSPACE_SESSION_KEYS.chatUiState;
const CHAT_TRANSCRIPT_LIMIT = 50;
const DEFAULT_VOICE_INSTRUCT = 'calm, clear mission-control voice with concise pacing';

function chatMessageId(role: string): string {
  return `${role}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function chatTimestamp(): string {
  return new Date().toISOString();
}

function formatChatTimestamp(value?: string): string {
  if (!value) return 'Restored';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Restored';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function loadChatUiState(): ChatUiState {
  if (typeof window === 'undefined') return { selectedModel: '' };
  try {
    const parsed = JSON.parse(window.sessionStorage.getItem(CHAT_UI_STATE_SESSION_KEY) || '{}');
    const row = parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : {};
    return { selectedModel: asText(row.selectedModel) };
  } catch {
    return { selectedModel: '' };
  }
}

function saveChatUiState(state: ChatUiState): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.setItem(CHAT_UI_STATE_SESSION_KEY, JSON.stringify({
      selectedModel: state.selectedModel,
    }));
  } catch {
    // Browser storage failures should not block the Chat UI.
  }
}

function normalizeChatMessage(value: unknown): ChatMessage | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  if (typeof row.role !== 'string' || typeof row.content !== 'string') return null;
  const role = row.role.trim();
  const content = row.content;
  if (!role || !content.trim()) return null;
  return {
    ...(typeof row.id === 'string' && row.id ? { id: row.id } : {}),
    role,
    content,
    ...(typeof row.model === 'string' && row.model ? { model: row.model } : {}),
    ...(typeof row.company === 'string' && row.company ? { company: row.company } : {}),
    ...(typeof row.accent === 'string' && row.accent ? { accent: row.accent } : {}),
    ...(typeof row.createdAt === 'string' && row.createdAt ? { createdAt: row.createdAt } : {}),
    ...(row.delivery === 'sending' || row.delivery === 'failed' ? { delivery: row.delivery } : {}),
    ...(typeof row.metadata === 'string' && row.metadata ? { metadata: row.metadata } : {}),
    ...(row.diagnostic === true ? { diagnostic: true } : {}),
    ...(typeof row.diagnosticDetail === 'string' && row.diagnosticDetail ? { diagnosticDetail: row.diagnosticDetail } : {}),
  };
}

function loadChatTranscript(): ChatMessage[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.sessionStorage.getItem(CHAT_TRANSCRIPT_SESSION_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map(normalizeChatMessage)
      .filter((message): message is ChatMessage => Boolean(message))
      .slice(-CHAT_TRANSCRIPT_LIMIT);
  } catch {
    return [];
  }
}

function saveChatTranscript(messages: ChatMessage[]): void {
  if (typeof window === 'undefined') return;
  try {
    if (!messages.length) {
      window.sessionStorage.removeItem(CHAT_TRANSCRIPT_SESSION_KEY);
      return;
    }
    window.sessionStorage.setItem(CHAT_TRANSCRIPT_SESSION_KEY, JSON.stringify(messages.slice(-CHAT_TRANSCRIPT_LIMIT)));
  } catch {
    // Private-mode and remote-browser storage errors should not interrupt chat.
  }
}

function serializeTranscript(messages: ChatMessage[]): string {
  return messages.map((message, index) => {
    const label = [message.role.toUpperCase(), message.model, message.company, formatChatTimestamp(message.createdAt), message.delivery, message.diagnostic ? 'diagnostic' : ''].filter(Boolean).join(' · ');
    return `#${index + 1} ${label}\n${message.content}`;
  }).join('\n\n');
}

function chatBriefMarkdown(messages: ChatMessage[], selectedModel: string, modelCard?: ModelCard): string {
  const userCount = messages.filter((message) => message.role === 'user').length;
  const assistantCount = messages.filter((message) => message.role === 'assistant').length;
  const lastAssistant = [...messages].reverse().find((message) => message.role === 'assistant');
  const activeModel = modelCard?.display_name || selectedModel || lastAssistant?.model || 'Unknown model';
  return [
    '# Chat Brief',
    '',
    `Generated: ${new Date().toISOString()}`,
    `Active Model: ${activeModel}`,
    `Company: ${modelCard?.company || lastAssistant?.company || 'n/a'}`,
    `Training Nation: ${modelCard?.training_nation || 'n/a'}`,
    `Provider: ${modelCard?.provider || 'n/a'}`,
    `Messages: ${messages.length}`,
    `User Turns: ${userCount}`,
    `Assistant Turns: ${assistantCount}`,
    '',
    '## Latest Assistant Response',
    lastAssistant?.content || 'No assistant response yet.',
    '',
    '## Transcript',
    serializeTranscript(messages) || 'No conversation yet.',
  ].join('\n');
}

function chatContactSearchText(model: ModelCard): string {
  return [model.display_name, model.company, model.family, model.training_nation, model.type, model.cost_label].join(' ').toLowerCase();
}

function chatPresence(model?: ModelCard): { label: string; tone: 'online' | 'away' | 'offline' } {
  if (!model) return { label: 'offline', tone: 'offline' };
  if (model.route_enabled) return { label: 'online', tone: 'online' };
  if (['not_checked', 'rate_limited', 'probe_failed'].includes(model.access_status)) return { label: readableStatus(model.access_status), tone: 'away' };
  return { label: readableStatus(model.access_status), tone: 'offline' };
}

type ChatContactPane = {
  pinned: ModelCard[];
  drawer: ModelCard[];
  totalCount: number;
};

function chatContactPane(models: ModelCard[], favorites: string[], activeId: string, filter: string): ChatContactPane {
  const favoriteSet = new Set(favorites);
  const query = filter.trim().toLowerCase();
  const visible = models.filter((model) => !query || chatContactSearchText(model).includes(query));
  // The active contact rides with the pinned strip even when unstarred (V2-082 Q6).
  const pinned = visible
    .filter((model) => favoriteSet.has(model.id) || model.id === activeId)
    .sort((left, right) =>
      Number(favoriteSet.has(right.id)) - Number(favoriteSet.has(left.id))
      || left.display_name.localeCompare(right.display_name));
  const drawer = visible
    .filter((model) => !favoriteSet.has(model.id) && model.id !== activeId)
    .sort((left, right) =>
      Number(right.route_enabled) - Number(left.route_enabled)
      || left.display_name.localeCompare(right.display_name));
  return {
    pinned,
    drawer,
    totalCount: models.length,
  };
}


function speechRecognitionConstructor(): BrowserSpeechRecognitionConstructor | null {
  if (typeof window === 'undefined') return null;
  const scope = window as unknown as {
    SpeechRecognition?: BrowserSpeechRecognitionConstructor;
    webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
  };
  return scope.SpeechRecognition || scope.webkitSpeechRecognition || null;
}

function speechLocale(language: string): string {
  const normalized = language.toLowerCase();
  if (normalized.includes('chinese')) return 'zh-CN';
  if (normalized.includes('french')) return 'fr-FR';
  if (normalized.includes('german')) return 'de-DE';
  if (normalized.includes('italian')) return 'it-IT';
  if (normalized.includes('japanese')) return 'ja-JP';
  if (normalized.includes('korean')) return 'ko-KR';
  if (normalized.includes('portuguese')) return 'pt-BR';
  if (normalized.includes('russian')) return 'ru-RU';
  if (normalized.includes('spanish')) return 'es-ES';
  return 'en-US';
}

function recognitionTranscript(event: unknown): string {
  const results = Array.from(((event as Record<string, unknown>)?.results || []) as ArrayLike<unknown>);
  return results
    .map((result) => {
      const row = result as { isFinal?: boolean; [key: number]: { transcript?: string } | undefined };
      if (row.isFinal === false) return '';
      return row[0]?.transcript || '';
    })
    .join(' ')
    .trim();
}

function weatherCodeLabel(code: number): string {
  if ([0, 1].includes(code)) return 'Clear';
  if ([2, 3].includes(code)) return 'Clouds';
  if ([45, 48].includes(code)) return 'Fog';
  if ([51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82].includes(code)) return 'Rain';
  if ([71, 73, 75, 77, 85, 86].includes(code)) return 'Snow';
  if ([95, 96, 99].includes(code)) return 'Storm';
  return 'Weather';
}

function timeMood(date: Date): { label: string; tone: string } {
  const hour = date.getHours();
  if (hour < 5) return { label: 'Night', tone: 'Quiet focus' };
  if (hour < 11) return { label: 'Morning', tone: 'Fresh start' };
  if (hour < 17) return { label: 'Day', tone: 'High clarity' };
  if (hour < 21) return { label: 'Evening', tone: 'Soft landing' };
  return { label: 'Night', tone: 'Quiet focus' };
}

function useCreateMood() {
  const [now, setNow] = useState(() => new Date());
  const [weather, setWeather] = useState('Weather standby');
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    let cancelled = false;
    const loadWeather = async () => {
      if (!('permissions' in navigator) || !navigator.geolocation) {
        if (!cancelled) setWeather('Weather off');
        return;
      }
      try {
        const permission = await navigator.permissions.query({ name: 'geolocation' as PermissionName });
        if (cancelled) return;
        if (permission.state !== 'granted') {
          setWeather('Weather off');
          return;
        }
        navigator.geolocation.getCurrentPosition(async (position) => {
          try {
            const { latitude, longitude } = position.coords;
            const response = await fetch(`https://api.open-meteo.com/v1/forecast?latitude=${latitude.toFixed(3)}&longitude=${longitude.toFixed(3)}&current=temperature_2m,weather_code&temperature_unit=fahrenheit`, { cache: 'no-store' });
            const payload = await response.json();
            const current = payload?.current || {};
            if (!cancelled && typeof current.temperature_2m === 'number') setWeather(`${Math.round(current.temperature_2m)}F ${weatherCodeLabel(Number(current.weather_code || 0))}`);
          } catch {
            if (!cancelled) setWeather('Weather unavailable');
          }
        }, () => {
          if (!cancelled) setWeather('Weather unavailable');
        }, { maximumAge: 900_000, timeout: 2500 });
      } catch {
        if (!cancelled) setWeather('Weather standby');
      }
    };
    loadWeather();
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);
  const mood = timeMood(now);
  return {
    ...mood,
    time: now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }),
    weather,
  };
}

function researchBriefMetrics(data: ResearchDossier, evidence: ResearchEvidence[]): Array<[string, number]> {
  const engineCount = new Set(evidence.map((result) => result.engine || result.engine_name).filter(Boolean)).size;
  const degradedCount = data.synthesis?.degraded_engines?.length || evidence.filter((result) => ['needs_key', 'not_indexed', 'unavailable', 'error'].includes(result.status)).length;
  const liveCount = numeric(data.synthesis?.live_result_count) || evidence.filter((result) => ['live', 'catalog', 'local'].includes(result.status)).length;
  const evidenceCount = numeric(data.synthesis?.evidence_count) || evidence.length;
  return [
    ['Evidence', evidenceCount],
    ['Live', liveCount],
    ['Sources', engineCount],
    ['Degraded', degradedCount],
  ];
}

const RESEARCH_SOURCE_LABELS: Array<[string, string]> = [
  ['images', 'Images'],
  ['examples', 'Examples'],
  ['mapping', 'Maps'],
  ['wikipedia', 'Wikipedia'],
  ['technical-docs', 'Docs'],
];

function researchSourceMetrics(data: ResearchDossier): Array<[string, number]> {
  const coverage = data.synthesis?.source_coverage || [];
  if (coverage.length) {
    return coverage
      .filter((row) => row.result_count > 0)
      .map((row): [string, number] => [row.label || row.name || row.engine_id, numeric(row.result_count)]);
  }
  const counts = data.synthesis?.source_engine_counts || {};
  return RESEARCH_SOURCE_LABELS
    .map(([engine, label]): [string, number] => [label, numeric(counts[engine])])
    .filter(([, value]) => value > 0);
}

function researchSourceCoverage(data: ResearchDossier): ResearchSourceCoverage[] {
  const coverage = data.synthesis?.source_coverage || [];
  if (coverage.length) return coverage;
  const counts = data.synthesis?.source_engine_counts || {};
  return RESEARCH_SOURCE_LABELS.map(([engine, label]) => ({
    id: engine,
    engine_id: engine,
    label,
    name: label,
    kind: engine.replace(/-/g, '_'),
    required: true,
    status: numeric(counts[engine]) > 0 ? 'covered' : 'unknown',
    result_count: numeric(counts[engine]),
    usable_count: numeric(counts[engine]),
    detail: numeric(counts[engine]) > 0 ? `${label} returned evidence.` : `${label} coverage was not reported by this saved result.`,
  }));
}

function researchEvidenceId(result: ResearchEvidence): string {
  return result.evidence_id || result.id || result.citation || result.title;
}

function researchEvidenceMap(data: ResearchDossier): Map<string, ResearchEvidence> {
  return new Map((data.evidence || []).map((item) => [researchEvidenceId(item), item]));
}

function researchBriefMarkdown(data: ResearchDossier, evidence: ResearchEvidence[], metrics: Array<[string, number]>): string {
  const sourceCoverage = researchSourceCoverage(data);
  const strategy = data.model_audit?.strategy;
  const outputs = data.model_audit?.outputs;
  const lines = [
    `# ${data.report_packet?.title || data.synthesis?.title || 'Research Packet'}`,
    '',
    `Dossier: ${data.dossier_id}`,
    `Query: ${data.query?.text || ''}`,
    `Mode: ${data.query?.mode || 'Balanced'}`,
    `Generated: ${new Date().toISOString()}`,
    '',
    '## Summary',
    data.synthesis?.summary || 'No synthesis available yet.',
    '',
    '## Answer',
    outputs?.answer || data.synthesis?.answer || data.synthesis?.coordinated_answer || 'No coordinated answer is available yet.',
    '',
    '## Claim Evidence Map',
    ...(data.claims?.length ? data.claims.map((claim) => `- ${claim.text} (${claim.confidence}; ${claim.status}) Evidence: ${claim.supporting_evidence_ids.join(', ') || 'n/a'}`) : ['- No structured claims are available.']),
    '',
    '## Research Team',
  ];
  const team = [
    ...(strategy?.analysts || []),
    ...(strategy?.coordinator ? [strategy.coordinator] : []),
  ];
  if (team.length) {
    team.forEach((role) => {
      lines.push(`- ${role.label}: ${role.display_name || role.model_id || role.status} (${role.cost_label || 'cost n/a'}; ${role.fast_response?.detail || 'fast-response history n/a'})`);
    });
  } else {
    lines.push('- No research team metadata available.');
  }
  lines.push(
    '',
    '## Metrics',
    ...metrics.map(([label, value]) => `- ${label}: ${Number(value).toLocaleString()}`),
    '',
    '## Source Classes',
    ...(sourceCoverage.length ? sourceCoverage.map((row) => `- ${row.label || row.name}: ${readableStatus(row.status)}; ${Number(row.usable_count || 0).toLocaleString()} usable / ${Number(row.result_count || 0).toLocaleString()} total. ${row.detail || ''}`) : ['- No source-class metadata available.']),
    '',
    '## Analyst Outputs',
  );
  const analystOutputs = outputs?.analysts || [];
  if (analystOutputs.length) {
    analystOutputs.forEach((output) => lines.push(`- ${output.label}: ${output.text}`));
  } else {
    lines.push('- No analyst outputs are available yet.');
  }
  lines.push(
    '',
    '## Evidence',
  );
  if (!evidence.length) {
    lines.push('- No evidence matches the active filter.');
  } else {
    evidence.forEach((result, index) => {
      lines.push(
        `${index + 1}. ${result.title}`,
        `   - Engine: ${result.engine_name} (${readableStatus(result.status)})`,
        `   - Source: ${result.source}${result.published_at ? `, ${result.published_at}` : ''}`,
        `   - Citation: ${result.citation}`,
        `   - Score: ${Number.isFinite(Number(result.score)) ? Math.round(Number(result.score) * 100) : 'n/a'}`,
        `   - URL: ${result.url || 'n/a'}`,
        `   - Snippet: ${result.snippet}`,
      );
    });
  }
  if (data.synthesis?.degraded_engines?.length) {
    lines.push('', '## Degraded Engines', ...data.synthesis.degraded_engines.map((engine) => `- ${engine}`));
  }
  return lines.join('\n');
}

function researchReportMarkdown(data: ResearchDossier, packet?: ResearchReportPacket): string {
  const report = packet || data.report_packet;
  const metrics = researchBriefMetrics(data, data.evidence || []);
  const lines = [
    researchBriefMarkdown(data, data.evidence || [], metrics),
    '',
    '## Full Report Sections',
  ];
  (report?.sections || []).forEach((section) => {
    lines.push('', `### ${section.title || section.id}`, section.content || '');
    if (Array.isArray(section.items) && section.items.length) {
      section.items.forEach((item, index) => lines.push(`${index + 1}. ${asText(item)}`));
    }
  });
  return lines.join('\n');
}

function researchSourcePacket(result: ResearchEvidence): string {
  const lines = [
    `# ${result.title || 'Research Source'}`,
    '',
    `Evidence ID: ${researchEvidenceId(result)}`,
    `Engine: ${result.engine_name || result.engine || 'n/a'}`,
    `Status: ${readableStatus(result.status)}`,
    `Citation: ${result.citation || 'n/a'}`,
    `Source: ${result.source || 'n/a'}`,
    `URL: ${result.url || 'n/a'}`,
  ];
  if (result.published_at) lines.push(`Published: ${result.published_at}`);
  if (result.coordinates) lines.push(`Coordinates: ${result.coordinates}`);
  if (result.thumbnail_url) lines.push(`Thumbnail: ${result.thumbnail_url}`);
  lines.push('', 'Snippet:', result.snippet || 'n/a');
  return lines.join('\n');
}

function ResearchReportActions({ dossier, onPrint, className = 'researchBriefActions researchReportActions' }: { dossier: ResearchDossier | null; onPrint: () => void; className?: string }) {
  const disabled = !dossier;
  const brief = dossier ? researchReportMarkdown(dossier) : '';
  const readyStatus = disabled ? 'No packet' : 'Packet Ready';
  const [briefStatus, setBriefStatus] = useState(readyStatus);
  useEffect(() => {
    setBriefStatus(readyStatus);
  }, [brief, readyStatus]);
  const { copyBrief, downloadBrief } = briefDeliveryActions(brief, 'mde-llm-proxy-research-packet', setBriefStatus, {
    copied: 'Copied',
    copyFailed: 'Copy failed',
    downloaded: 'Downloaded',
  }, !disabled);
  return (
    <div className={className} aria-label="Research brief actions">
      <span>{briefStatus}</span>
      <button className="secondaryButton" type="button" disabled={disabled} onClick={() => void copyBrief()}>Copy Packet</button>
      <button className="secondaryButton" type="button" disabled={disabled} onClick={downloadBrief}>Download Packet</button>
      <button className="primaryButton" type="button" disabled={disabled} onClick={onPrint}>Print / Save PDF</button>
    </div>
  );
}

function ResearchTeamPanel({ strategy }: { strategy?: ResearchModelStrategy }) {
  if (!strategy) return null;
  const policy = strategy.policy || {};
  const roles = [
    ...(strategy.analysts || []),
    ...(strategy.coordinator ? [strategy.coordinator] : []),
  ];
  const costLimit = Number.isFinite(Number(policy.max_model_price_usd)) ? `$${Number(policy.max_model_price_usd).toFixed(2)}` : '$0.50';
  const fastLimit = Number.isFinite(Number(policy.fast_max_latency_ms)) ? `${Number(policy.fast_max_latency_ms).toLocaleString()}ms` : 'fast history';
  return (
    <div className="researchTeamPanel" data-testid="research-team-panel">
      <div className="researchTeamHeader">
        <div>
          <span>Research Team</span>
          <strong>3 analysts + 1 coordinator</strong>
          <p>Cost guard: each model must be below {costLimit}; fast-response guard: measured or known fast history under {fastLimit}.</p>
        </div>
        <div className="researchTeamGuard">
          <span>{Number(strategy.candidate_count || 0).toLocaleString()} eligible</span>
          <span>{policy.llm_calls_enabled ? 'Live LLM calls' : 'Fallback-safe'}</span>
        </div>
      </div>
      <div className="researchTeamGrid">
        {roles.map((role) => (
          <article className={`researchRole status-${role.status}`} key={`${role.role}-${role.model_id || role.label}`}>
            <span>{role.role === 'coordinator' ? 'Coordinator' : 'Analyst'}</span>
            <strong>{role.display_name || role.model_id || role.label}</strong>
            <p>{role.focus || role.recommendation || role.status}</p>
            <small>{role.cost_label || (Number.isFinite(Number(role.max_text_price_usd)) ? `$${Number(role.max_text_price_usd).toFixed(3)} max / 1M tokens` : 'Cost unavailable')}</small>
            <small>{role.fast_response?.detail || 'Fast-response history unavailable'}</small>
          </article>
        ))}
      </div>
    </div>
  );
}

function ResearchModelOutputs({ data }: { data: ResearchDossier }) {
  const outputs = data.model_audit?.outputs;
  const analysts = outputs?.analysts || [];
  const coordinator = outputs?.coordinator;
  const answer = outputs?.answer || data.synthesis?.answer || data.synthesis?.coordinated_answer || coordinator?.text || '';
  if (!answer && !analysts.length && !coordinator) return null;
  return (
    <div className="researchModelOutputs" data-testid="research-model-outputs">
      {answer ? (
        <div className="coordinatedAnswer" data-testid="research-coordinated-answer">
          <span>{coordinator?.display_name || data.synthesis?.coordinator_model || 'Coordinator'}</span>
          <strong>Coordinated Answer</strong>
          <p>{answer}</p>
        </div>
      ) : null}
      {analysts.length ? (
        <div className="analystGrid" data-testid="research-analyst-outputs">
          {analysts.map((output) => (
            <article className={`analystOutput status-${output.status}`} key={`${output.role}-${output.model_id || output.label}`}>
              <span>{output.label}</span>
              <strong>{output.display_name || output.model_id || 'Fallback analyst'}</strong>
              <p>{output.text}</p>
              <small>{output.cost_label || 'Cost guard active'} · {readableStatus(output.status)}</small>
            </article>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ResearchResultsTab({ data, pinnedIds, onTogglePin, pinPending }: { data: ResearchDossier; pinnedIds: string[]; onTogglePin: (id: string) => void; pinPending: boolean }) {
  const [engineFilter, setEngineFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [copiedResultId, setCopiedResultId] = useState('');
  const evidence = data.evidence || [];
  const engineOptions = useMemo(() => Array.from(new Map(evidence.map((result) => [result.engine || result.engine_name, result.engine_name || result.engine])).entries()).filter(([id]) => Boolean(id)), [evidence]);
  const statusOptions = useMemo(() => Array.from(new Set(evidence.map((result) => result.status).filter(Boolean))).sort(), [evidence]);
  const typeOptions = useMemo(() => Array.from(new Set(evidence.map((result) => result.source_type || result.kind).filter(Boolean))).sort(), [evidence]);
  useEffect(() => {
    if (engineFilter !== 'all' && !engineOptions.some(([id]) => id === engineFilter)) setEngineFilter('all');
  }, [engineFilter, engineOptions]);
  const visibleResults = evidence
    .filter((result) => engineFilter === 'all' || result.engine === engineFilter)
    .filter((result) => statusFilter === 'all' || result.status === statusFilter)
    .filter((result) => typeFilter === 'all' || (result.source_type || result.kind) === typeFilter);
  const metrics = researchBriefMetrics(data, visibleResults);
  const sourceCoverage = researchSourceCoverage(data);
  const copySourcePacket = async (result: ResearchEvidence) => {
    const resultId = researchEvidenceId(result);
    try {
      await copyText(researchSourcePacket(result));
      setCopiedResultId(resultId);
    } catch {
      setCopiedResultId(`failed:${resultId}`);
    }
  };
  return (
    <div className="researchEvidence lexisResultsPane">
      <div className="researchCommandBoard">
        <div className="researchMetrics" aria-label="Research result summary">
          {metrics.map(([label, value]) => <div key={label}><span>{label}</span><strong>{Number(value).toLocaleString()}</strong></div>)}
        </div>
        {sourceCoverage.length ? (
          <div className="sourceCoveragePanel" aria-label="Required research source coverage" data-testid="research-source-coverage">
            {sourceCoverage.map((row) => {
              const engineId = row.engine_id || row.id;
              const active = engineFilter === engineId;
              return (
                <button
                  aria-pressed={active}
                  className={`sourceCoverageChip status-${row.status} ${active ? 'active' : ''}`}
                  key={engineId}
                  onClick={() => setEngineFilter(active ? 'all' : engineId)}
                  title={`${row.detail} Filter evidence to ${row.label || row.name}.`}
                  type="button"
                >
                  <strong>{row.label || row.name}</strong>
                  <small>{readableStatus(row.status)} · {Number(row.usable_count || 0).toLocaleString()}/{Number(row.result_count || 0).toLocaleString()}</small>
                </button>
              );
            })}
          </div>
        ) : null}
        {engineOptions.length ? (
          <div className="researchFilters" aria-label="Research evidence filter">
            <button className={engineFilter === 'all' ? 'active' : ''} type="button" onClick={() => setEngineFilter('all')}>All evidence</button>
            {engineOptions.map(([id, label]) => (
              <button className={engineFilter === id ? 'active' : ''} key={id} type="button" onClick={() => setEngineFilter(id)}>{label}</button>
            ))}
            <select value={statusFilter} aria-label="Filter by status" onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="all">All status</option>
              {statusOptions.map((status) => <option value={status} key={status}>{readableStatus(status)}</option>)}
            </select>
            <select value={typeFilter} aria-label="Filter by source type" onChange={(event) => setTypeFilter(event.target.value)}>
              <option value="all">All types</option>
              {typeOptions.map((type) => <option value={type} key={type}>{readableStatus(type)}</option>)}
            </select>
          </div>
        ) : null}
      </div>
      <div className="lexisResultTable" role="table" aria-label="Research evidence results">
        <div className="lexisResultHeader" role="row">
          <span>Pin</span>
          <span>Score</span>
          <span>Source</span>
          <span>Title</span>
          <span>Status</span>
          <span>Actions</span>
        </div>
        {visibleResults.length ? visibleResults.map((result) => (
          <details className={`lexisResultRow status-${result.status}`} key={researchEvidenceId(result)}>
            <summary>
              <span><button className={`pinButton ${pinnedIds.includes(researchEvidenceId(result)) ? 'active' : ''}`} type="button" disabled={pinPending} aria-pressed={pinnedIds.includes(researchEvidenceId(result))} aria-label={`${pinnedIds.includes(researchEvidenceId(result)) ? 'Unpin' : 'Pin'} ${result.title}`} onClick={(event) => { event.preventDefault(); onTogglePin(researchEvidenceId(result)); }}><CarbonIcon path={pinnedIds.includes(researchEvidenceId(result)) ? 'apps/star--filled.svg' : 'apps/star.svg'} label="Pin" /></button></span>
              <span>{Number.isFinite(Number(result.relevance_score ?? result.score)) ? Number(result.relevance_score ?? result.score).toLocaleString() : 'n/a'}</span>
              <span>{result.engine_name || result.engine}</span>
              <strong>{result.url ? <a href={result.url} target="_blank" rel="noreferrer">{result.title}</a> : result.title}</strong>
              <span>{readableStatus(result.status)}</span>
              <button className={`resultCopyButton ${copiedResultId === researchEvidenceId(result) ? 'copied' : ''}`} type="button" onClick={(event) => { event.preventDefault(); void copySourcePacket(result); }} aria-label={`Copy Source for ${result.title}`}>
                {copiedResultId === `failed:${researchEvidenceId(result)}` ? 'Copy Failed' : copiedResultId === researchEvidenceId(result) ? 'Copied' : 'Copy Source'}
              </button>
            </summary>
            <div className="lexisResultDetail">
              <p>{result.snippet || 'No snippet provided.'}</p>
              <dl>
                <div><dt>Citation</dt><dd>{result.citation || 'n/a'}</dd></div>
                <div><dt>Type</dt><dd>{readableStatus(result.source_type || result.kind)}</dd></div>
                <div><dt>Source</dt><dd>{result.source}{result.published_at ? ` · ${result.published_at}` : ''}</dd></div>
                {result.coordinates ? <div><dt>Coordinates</dt><dd>{result.coordinates}</dd></div> : null}
                {result.path ? <div><dt>Path</dt><dd>{result.path}{result.chunk ? `#${result.chunk}` : ''}</dd></div> : null}
              </dl>
            </div>
          </details>
        )) : <div className="emptyState">No evidence matches this filter.</div>}
      </div>
    </div>
  );
}

function ResearchBriefTab({ data }: { data: ResearchDossier }) {
  const evidence = researchEvidenceMap(data);
  return (
    <div className="lexisBriefPane">
      <div className="synthesisPanel">
        <div>
          <span>{readableStatus(data.query?.mode)}</span>
          <strong>{data.synthesis?.title || 'Research synthesis'}</strong>
        </div>
        <p>{data.synthesis?.answer || data.synthesis?.coordinated_answer || data.synthesis?.summary || 'No synthesis available yet.'}</p>
      </div>
      <div className="claimMap" data-testid="research-claim-map">
        <div className="claimMapHeader">
          <span>{data.claims.length} claim{data.claims.length === 1 ? '' : 's'}</span>
          <strong>Claim Evidence Map</strong>
        </div>
        {data.claims.length ? data.claims.map((claim) => (
          <article className={`claimRow status-${claim.status}`} key={claim.claim_id}>
            <div>
              <span>{claim.confidence} · {readableStatus(claim.status)}</span>
              <strong>{claim.text}</strong>
              <p>{claim.caveat}</p>
            </div>
            <div className="claimEvidenceChips">
              {claim.supporting_evidence_ids.length ? claim.supporting_evidence_ids.map((id) => {
                const source = evidence.get(id);
                return <span key={id}>{source?.citation || source?.title || id}</span>;
              }) : <span>No linked evidence</span>}
            </div>
          </article>
        )) : <div className="emptyState">No structured claims are available.</div>}
      </div>
      <details className="researchAuditPanel">
        <summary>Model audit and diagnostics</summary>
        <ResearchTeamPanel strategy={data.model_audit?.strategy} />
        <ResearchModelOutputs data={data} />
        {Object.keys(data.model_audit?.diagnostics || {}).length
          ? <pre>{JSON.stringify(data.model_audit?.diagnostics, null, 2)}</pre>
          : <p className="researchAuditEmpty">No diagnostics were reported for this run.</p>}
      </details>
    </div>
  );
}

function ResearchSourceRegistryTab({ payload, dossier, activeEngineIds, onToggleEngine }: { payload?: ResearchPayload; dossier: ResearchDossier | null; activeEngineIds: string[]; onToggleEngine: (id: string) => void }) {
  const engines = dossier?.source_catalog?.engines || payload?.engines || [];
  const sourceClasses = dossier?.source_catalog?.source_classes || payload?.source_classes || [];
  const coverage = dossier ? researchSourceCoverage(dossier) : [];
  return (
    <div className="sourceRegistryPanel" data-testid="research-source-registry">
      <div className="sourceRegistryGrid">
        {engines.map((engine) => {
          const active = activeEngineIds.includes(engine.id);
          return (
            <article className={`sourceRegistryCard status-${engine.status} ${active ? 'active' : ''}`} key={engine.id}>
              <div>
                <span>{readableStatus(engine.kind)}</span>
                <strong>{engine.name}</strong>
                <p>{engine.detail || readableStatus(engine.status)}</p>
              </div>
              <button className="secondaryButton" type="button" aria-pressed={active} onClick={() => onToggleEngine(engine.id)}>{active ? 'Included' : 'Include'}</button>
              <small>{readableStatus(engine.status)}{engine.run_status ? ` · run ${readableStatus(engine.run_status)}` : ''}</small>
            </article>
          );
        })}
      </div>
      {sourceClasses.length ? (
        <div className="sourceClassStrip" aria-label="Research source classes">
          {sourceClasses.map((source) => {
            const row = coverage.find((item) => item.engine_id === source.engine_id || item.id === source.id);
            return (
              <span className={`sourceClassChip kind-${source.kind.replace(/[^a-z0-9_-]/gi, '-')}`} key={source.id} title={source.detail || source.name}>
                <strong>{source.label || source.name}</strong>
                <small>{readableStatus(row?.status || source.status)} · {readableStatus(source.kind)}</small>
              </span>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

function ResearchPrintPacket({ dossier, packet }: { dossier: ResearchDossier | null; packet: ResearchReportPacket | null }) {
  if (!dossier) return null;
  const report = packet || dossier.report_packet;
  return (
    <div className="researchPrintFrame" aria-hidden="true">
      <h1>{report?.title || 'Research Packet'}</h1>
      <p><strong>Query:</strong> {dossier.query.text}</p>
      <p><strong>Dossier:</strong> {dossier.dossier_id}</p>
      {(report?.sections || []).map((section) => (
        <section key={section.id}>
          <h2>{section.title}</h2>
          {section.content ? <pre>{section.content}</pre> : null}
          {Array.isArray(section.items) ? section.items.map((item, index) => <p key={`${section.id}-${index}`}>{asText(item)}</p>) : null}
        </section>
      ))}
    </div>
  );
}

function AdvancedLoading({ label }: { label: string }) {
  const title = readableStatus(label);
  return (
    <div className="advancedPanel advancedLoading" role="status" aria-live="polite" data-testid="advanced-loading-skeleton">
      <div className="advancedLoadingHeader">
        <span>{title}</span>
        <strong>{title} workspace loading</strong>
      </div>
      <div className="advancedLoadingGrid" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <div className="advancedLoadingRows" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
    </div>
  );
}

type CreateImageResult = {
  id: string;
  src: string;
  prompt: string;
  model: string;
  size: string;
  cost: string;
  filename: string;
};

type CreateHistoryItem = {
  id: string;
  prompt: string;
  summary: string;
  createdAt: string;
  thumbnail?: string;
  imageResult?: { images: CreateImageResult[]; raw: string } | null;
};

type CreateWorkspaceState = {
  prompt: string;
  model: string;
  imageResult: { images: CreateImageResult[]; raw: string } | null;
  historyItems: CreateHistoryItem[];
};

const CREATE_WORKSPACE_SESSION_KEY = V2_WORKSPACE_SESSION_KEYS.createWorkspace;
const CREATE_HISTORY_LIMIT = 6;

function emptyCreateWorkspace(): CreateWorkspaceState {
  return { prompt: '', model: '', imageResult: null, historyItems: [] };
}

function normalizeCreateHistoryItem(value: unknown): CreateHistoryItem | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const mode = asText(row.mode, 'Image');
  const prompt = asText(row.prompt);
  const summary = asText(row.summary);
  const createdAt = asText(row.createdAt);
  // Create is image-only: stale Chat/Research history entries are dropped on load.
  if (mode !== 'Image' || !prompt || !summary || !createdAt) return null;
  return {
    id: asText(row.id, `${createdAt}-image-${prompt.slice(0, 16)}`),
    prompt,
    summary,
    createdAt,
    imageResult: normalizeCreateImageResult(row.imageResult),
    ...(typeof row.thumbnail === 'string' && row.thumbnail ? { thumbnail: row.thumbnail } : {}),
  };
}

function normalizeCreateImage(value: unknown): CreateImageResult | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const src = asText(row.src);
  if (!src) return null;
  return {
    id: asText(row.id, `image-${src.slice(0, 16)}`),
    src,
    prompt: asText(row.prompt),
    model: asText(row.model),
    size: asText(row.size),
    cost: asText(row.cost),
    filename: asText(row.filename),
  };
}

function normalizeCreateImageResult(value: unknown): CreateWorkspaceState['imageResult'] {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const images = Array.isArray(row.images)
    ? row.images.map(normalizeCreateImage).filter((image): image is CreateImageResult => Boolean(image))
    : [];
  if (!images.length && !asText(row.raw)) return null;
  return { images, raw: asText(row.raw, JSON.stringify({ images }, null, 2)) };
}

function normalizeStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && Boolean(item)) : [];
}

function normalizeNumberRecord(value: unknown): Record<string, number> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .map(([key, row]): [string, number] => [key, Number(row)])
      .filter(([key, row]) => Boolean(key) && Number.isFinite(row)),
  );
}

function normalizeResearchSourceCoverage(value: unknown): ResearchSourceCoverage | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const engineId = asText(row.engine_id || row.id);
  const label = asText(row.label || row.name || engineId);
  if (!engineId || !label) return null;
  return {
    id: asText(row.id, engineId),
    engine_id: engineId,
    label,
    name: asText(row.name, label),
    kind: asText(row.kind, engineId.replace(/-/g, '_')),
    required: row.required === undefined ? true : Boolean(row.required),
    status: asText(row.status, 'unknown'),
    result_count: Number.isFinite(Number(row.result_count)) ? Number(row.result_count) : 0,
    usable_count: Number.isFinite(Number(row.usable_count)) ? Number(row.usable_count) : 0,
    detail: asText(row.detail),
  };
}

function normalizeResearchEvidence(value: unknown): ResearchEvidence | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const title = asText(row.title);
  if (!title) return null;
  const evidenceId = asText(row.evidence_id || row.id || row.citation || title);
  return {
    id: evidenceId,
    evidence_id: evidenceId,
    engine: asText(row.engine || row.engine_name, 'local'),
    engine_name: asText(row.engine_name || row.engine, 'Evidence'),
    title,
    url: asText(row.url),
    snippet: asText(row.snippet),
    published_at: asText(row.published_at),
    source: asText(row.source, 'Session'),
    status: asText(row.status, 'local'),
    kind: asText(row.kind, 'web'),
    source_type: asText(row.source_type || row.kind, 'web'),
    score: numeric(row.score),
    relevance_score: Number.isFinite(Number(row.relevance_score)) ? Number(row.relevance_score) : numeric(row.score),
    position: numeric(row.position),
    citation: asText(row.citation),
    source_label: asText(row.source_label || row.source || row.engine_name),
    metadata: row.metadata && typeof row.metadata === 'object' ? row.metadata as Record<string, unknown> : {},
    ...(typeof row.path === 'string' ? { path: row.path } : {}),
    ...(Number.isFinite(Number(row.chunk)) ? { chunk: Number(row.chunk) } : {}),
    ...(typeof row.collection_id === 'string' ? { collection_id: row.collection_id } : {}),
    ...(typeof row.thumbnail_url === 'string' ? { thumbnail_url: row.thumbnail_url } : {}),
    ...(typeof row.content_url === 'string' ? { content_url: row.content_url } : {}),
    ...(typeof row.coordinates === 'string' ? { coordinates: row.coordinates } : {}),
  };
}

function normalizeResearchClaim(value: unknown): ResearchClaim | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const text = asText(row.text);
  if (!text) return null;
  return {
    claim_id: asText(row.claim_id, text),
    text,
    confidence: asText(row.confidence, 'low'),
    status: asText(row.status, 'needs_review'),
    supporting_evidence_ids: normalizeStringArray(row.supporting_evidence_ids),
    caveat: asText(row.caveat),
  };
}

function normalizeResearchRole(value: unknown): ResearchModelRole | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const role = asText(row.role);
  const label = asText(row.label || row.display_name || row.model_id);
  if (!role && !label) return null;
  const fast = row.fast_response && typeof row.fast_response === 'object' ? row.fast_response as Record<string, unknown> : {};
  return {
    role,
    label,
    focus: asText(row.focus),
    status: asText(row.status, 'selected'),
    model_id: asText(row.model_id) || undefined,
    display_name: asText(row.display_name) || undefined,
    company: asText(row.company) || undefined,
    family: asText(row.family) || undefined,
    training_nation: asText(row.training_nation) || undefined,
    cost_label: asText(row.cost_label) || undefined,
    max_text_price_usd: Number.isFinite(Number(row.max_text_price_usd)) ? Number(row.max_text_price_usd) : undefined,
    context_window: Number.isFinite(Number(row.context_window)) ? Number(row.context_window) : undefined,
    recommendation: asText(row.recommendation) || undefined,
    fast_response: Object.keys(fast).length ? {
      eligible: Boolean(fast.eligible),
      basis: asText(fast.basis) || undefined,
      latency_ms: Number.isFinite(Number(fast.latency_ms)) ? Number(fast.latency_ms) : undefined,
      detail: asText(fast.detail) || undefined,
    } : undefined,
  };
}

function normalizeResearchModelOutput(value: unknown): ResearchModelOutput | null {
  const role = normalizeResearchRole(value);
  if (!role || !value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  return { ...role, text: asText(row.text) };
}

function normalizeResearchReportSection(value: unknown): ResearchReportPacket['sections'][number] | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const id = asText(row.id || row.title);
  const title = asText(row.title || row.id);
  if (!id || !title) return null;
  return {
    id,
    title,
    kind: asText(row.kind, 'section'),
    content: asText(row.content) || undefined,
    items: Array.isArray(row.items) ? row.items.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : undefined,
  };
}

function normalizeResearchReportPacket(value: unknown, dossierId: string): ResearchReportPacket {
  const row = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  return {
    dossier_id: asText(row.dossier_id, dossierId),
    title: asText(row.title, 'Research Packet'),
    generated_at: Number.isFinite(Number(row.generated_at)) ? Number(row.generated_at) : Date.now() / 1000,
    sections: Array.isArray(row.sections) ? row.sections.map(normalizeResearchReportSection).filter((item): item is ResearchReportPacket['sections'][number] => Boolean(item)) : [],
    pinned_evidence_ids: normalizeStringArray(row.pinned_evidence_ids),
  };
}

function normalizeResearchPayload(value: unknown): ResearchDossier | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  if (Number(row.schema_version) !== 2 || !asText(row.dossier_id) || !Array.isArray(row.evidence)) return null;
  const evidence = row.evidence.map(normalizeResearchEvidence).filter((result): result is ResearchEvidence => Boolean(result));
  const claims = Array.isArray(row.claims) ? row.claims.map(normalizeResearchClaim).filter((claim): claim is ResearchClaim => Boolean(claim)) : [];
  const synthesis = row.synthesis && typeof row.synthesis === 'object' ? row.synthesis as Record<string, unknown> : {};
  const auditRow = row.model_audit && typeof row.model_audit === 'object' ? row.model_audit as Record<string, unknown> : {};
  const strategyRow = auditRow.strategy && typeof auditRow.strategy === 'object' ? auditRow.strategy as Record<string, unknown> : {};
  const outputsRow = auditRow.outputs && typeof auditRow.outputs === 'object' ? auditRow.outputs as Record<string, unknown> : {};
  const analysts = Array.isArray(strategyRow.analysts) ? strategyRow.analysts.map(normalizeResearchRole).filter((item): item is ResearchModelRole => Boolean(item)) : [];
  const outputAnalysts = Array.isArray(outputsRow.analysts) ? outputsRow.analysts.map(normalizeResearchModelOutput).filter((item): item is ResearchModelOutput => Boolean(item)) : [];
  const coordinator = normalizeResearchRole(strategyRow.coordinator);
  const outputCoordinator = normalizeResearchModelOutput(outputsRow.coordinator);
  const policy = strategyRow.policy && typeof strategyRow.policy === 'object' ? strategyRow.policy as Record<string, unknown> : {};
  const queryRow = row.query && typeof row.query === 'object' ? row.query as Record<string, unknown> : {};
  const sourceCatalog = row.source_catalog && typeof row.source_catalog === 'object' ? row.source_catalog as Record<string, unknown> : {};
  const dossierId = asText(row.dossier_id);
  const reportPacket = normalizeResearchReportPacket(row.report_packet, dossierId);
  return {
    schema_version: 2,
    dossier_id: dossierId,
    query: {
      text: asText(queryRow.text),
      mode: asText(queryRow.mode, 'Balanced'),
      selected_engines: normalizeStringArray(queryRow.selected_engines),
      source_selection_mode: asText(queryRow.source_selection_mode, 'all'),
      submitted_at: Number.isFinite(Number(queryRow.submitted_at)) ? Number(queryRow.submitted_at) : 0,
    },
    source_catalog: {
      engines: Array.isArray(sourceCatalog.engines) ? sourceCatalog.engines as ResearchPayload['engines'] : [],
      source_classes: Array.isArray(sourceCatalog.source_classes) ? sourceCatalog.source_classes as ResearchPayload['source_classes'] : [],
    },
    engine_runs: Array.isArray(row.engine_runs) ? row.engine_runs as ResearchPayload['engines'] : [],
    evidence,
    claims,
    synthesis: {
      title: asText(synthesis.title) || undefined,
      summary: asText(synthesis.summary) || undefined,
      answer: asText(synthesis.answer) || undefined,
      citations: normalizeStringArray(synthesis.citations),
      degraded_engines: normalizeStringArray(synthesis.degraded_engines),
      live_result_count: Number.isFinite(Number(synthesis.live_result_count)) ? Number(synthesis.live_result_count) : undefined,
      evidence_count: Number.isFinite(Number(synthesis.evidence_count)) ? Number(synthesis.evidence_count) : undefined,
      analyst_count: Number.isFinite(Number(synthesis.analyst_count)) ? Number(synthesis.analyst_count) : undefined,
      coordinator_model: asText(synthesis.coordinator_model) || undefined,
      coordinated_answer: asText(synthesis.coordinated_answer) || undefined,
      source_engine_counts: normalizeNumberRecord(synthesis.source_engine_counts),
      source_kind_counts: normalizeNumberRecord(synthesis.source_kind_counts),
      source_coverage: Array.isArray(synthesis.source_coverage)
        ? synthesis.source_coverage.map(normalizeResearchSourceCoverage).filter((item): item is ResearchSourceCoverage => Boolean(item))
        : undefined,
      evidence_ids: normalizeStringArray(synthesis.evidence_ids),
    },
    model_audit: {
      strategy: Object.keys(strategyRow).length ? {
        policy: {
          max_model_price_usd: Number.isFinite(Number(policy.max_model_price_usd)) ? Number(policy.max_model_price_usd) : undefined,
          price_metric: asText(policy.price_metric) || undefined,
          comparison: asText(policy.comparison) || undefined,
          fast_max_latency_ms: Number.isFinite(Number(policy.fast_max_latency_ms)) ? Number(policy.fast_max_latency_ms) : undefined,
          fast_response_required: typeof policy.fast_response_required === 'boolean' ? policy.fast_response_required : undefined,
          llm_calls_enabled: typeof policy.llm_calls_enabled === 'boolean' ? policy.llm_calls_enabled : undefined,
        },
        candidate_count: Number.isFinite(Number(strategyRow.candidate_count)) ? Number(strategyRow.candidate_count) : undefined,
        analysts,
        coordinator: coordinator || { role: 'coordinator', label: 'Research coordinator', focus: '', status: 'unavailable' },
      } : undefined,
      outputs: Object.keys(outputsRow).length ? {
        analysts: outputAnalysts,
        coordinator: outputCoordinator || undefined,
        answer: asText(outputsRow.answer) || undefined,
        generated_at: Number.isFinite(Number(outputsRow.generated_at)) ? Number(outputsRow.generated_at) : undefined,
      } : undefined,
      diagnostics: auditRow.diagnostics && typeof auditRow.diagnostics === 'object' ? auditRow.diagnostics as Record<string, unknown> : {},
    },
    report_packet: reportPacket,
    pinned_evidence_ids: normalizeStringArray(row.pinned_evidence_ids || reportPacket.pinned_evidence_ids),
  };
}

type ResearchEngineSelectionMode = 'all' | 'custom';
type ResearchTab = 'search' | 'results' | 'brief' | 'sources';

type ResearchWorkspaceState = {
  query: string;
  mode: string;
  engineSelectionMode: ResearchEngineSelectionMode;
  selectedEngines: string[];
  activeTab: ResearchTab;
  dossier: ResearchDossier | null;
};

const RESEARCH_WORKSPACE_SESSION_KEY = V2_WORKSPACE_SESSION_KEYS.researchWorkspace;
const RESEARCH_SELECTED_ENGINE_LIMIT = 12;

function emptyResearchWorkspace(): ResearchWorkspaceState {
  return { query: '', mode: 'Balanced', engineSelectionMode: 'all', selectedEngines: [], activeTab: 'search', dossier: null };
}

function loadResearchWorkspace(): ResearchWorkspaceState {
  if (typeof window === 'undefined') return emptyResearchWorkspace();
  try {
    const raw = window.sessionStorage.getItem(RESEARCH_WORKSPACE_SESSION_KEY);
    if (!raw) return emptyResearchWorkspace();
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return emptyResearchWorkspace();
    const row = parsed as Record<string, unknown>;
    const selectedEngines = normalizeStringArray(row.selectedEngines).slice(0, RESEARCH_SELECTED_ENGINE_LIMIT);
    const storedMode = row.engineSelectionMode === 'custom' || row.engineSelectionMode === 'all' ? row.engineSelectionMode : '';
    const engineSelectionMode = (storedMode || (selectedEngines.length ? 'custom' : 'all')) as ResearchEngineSelectionMode;
    const activeTab = ['search', 'results', 'brief', 'sources'].includes(asText(row.activeTab)) ? asText(row.activeTab) as ResearchTab : 'search';
    const dossier = normalizeResearchPayload(row.dossier || row.result);
    return {
      query: asText(row.query),
      mode: asText(row.mode, 'Balanced'),
      engineSelectionMode,
      selectedEngines: engineSelectionMode === 'custom' ? selectedEngines : [],
      activeTab: dossier ? activeTab : 'search',
      dossier,
    };
  } catch {
    return emptyResearchWorkspace();
  }
}

function hasResearchWorkspaceState(state: ResearchWorkspaceState): boolean {
  return Boolean(state.query.trim() || state.mode !== 'Balanced' || state.engineSelectionMode !== 'all' || state.selectedEngines.length || state.activeTab !== 'search' || state.dossier);
}

function saveResearchWorkspace(state: ResearchWorkspaceState): void {
  if (typeof window === 'undefined') return;
  try {
    if (!hasResearchWorkspaceState(state)) {
      window.sessionStorage.removeItem(RESEARCH_WORKSPACE_SESSION_KEY);
      return;
    }
    window.sessionStorage.setItem(RESEARCH_WORKSPACE_SESSION_KEY, JSON.stringify({
      ...state,
      selectedEngines: state.selectedEngines.slice(0, RESEARCH_SELECTED_ENGINE_LIMIT),
    }));
  } catch {
    // Remote/private browser storage failures must not block research work.
  }
}

function loadCreateWorkspace(): CreateWorkspaceState {
  if (typeof window === 'undefined') return emptyCreateWorkspace();
  try {
    const raw = window.sessionStorage.getItem(CREATE_WORKSPACE_SESSION_KEY);
    if (!raw) return emptyCreateWorkspace();
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return emptyCreateWorkspace();
    const row = parsed as Record<string, unknown>;
    return {
      prompt: asText(row.prompt),
      model: asText(row.model),
      imageResult: normalizeCreateImageResult(row.imageResult),
      historyItems: Array.isArray(row.historyItems)
        ? row.historyItems.map(normalizeCreateHistoryItem).filter((item): item is CreateHistoryItem => Boolean(item)).slice(0, CREATE_HISTORY_LIMIT)
        : [],
    };
  } catch {
    return emptyCreateWorkspace();
  }
}

function hasCreateWorkspaceState(state: CreateWorkspaceState): boolean {
  return Boolean(state.prompt.trim() || state.model.trim() || state.imageResult || state.historyItems.length);
}

function saveCreateWorkspace(state: CreateWorkspaceState): void {
  if (typeof window === 'undefined') return;
  try {
    if (!hasCreateWorkspaceState(state)) {
      window.sessionStorage.removeItem(CREATE_WORKSPACE_SESSION_KEY);
      return;
    }
    window.sessionStorage.setItem(CREATE_WORKSPACE_SESSION_KEY, JSON.stringify({
      ...state,
      historyItems: state.historyItems.slice(0, CREATE_HISTORY_LIMIT),
    }));
  } catch {
    // Browser storage can fail in locked-down remote sessions; Create should keep running.
  }
}

function firstText(row: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === 'string' && value.trim()) return value;
  }
  return '';
}

function normalizeImageResults(payload: unknown): { images: CreateImageResult[]; raw: string } {
  const root = payload && typeof payload === 'object' ? payload as Record<string, unknown> : {};
  const response = root.response && typeof root.response === 'object' ? root.response as Record<string, unknown> : root;
  const candidates = Array.isArray(response.images) ? response.images : Array.isArray(response.data) ? response.data : [];
  const images = candidates
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
    .map((item, index) => {
      const filename = firstText(item, ['filename', 'file', 'path']);
      const direct = firstText(item, ['url', 'image_url', 'src', 'data_url']);
      const b64 = firstText(item, ['b64_json', 'base64']);
      const src = direct || (b64 ? `data:image/png;base64,${b64}` : filename ? `/images/${encodeURIComponent(filename)}` : '');
      return {
        id: firstText(item, ['id']) || `image-${index + 1}`,
        src,
        prompt: firstText(item, ['prompt', 'revised_prompt']) || firstText(response, ['prompt']),
        model: firstText(item, ['model']) || firstText(response, ['model']),
        size: firstText(item, ['size']) || firstText(response, ['size']),
        cost: item.cost_usd === undefined ? '' : `$${Number(item.cost_usd || 0).toFixed(4)}`,
        filename,
      };
    })
    .filter((item) => item.src);
  return { images, raw: JSON.stringify(payload, null, 2) };
}

function hasCreateBriefState({ imageResult, historyItems }: CreateWorkspaceState): boolean {
  return Boolean(imageResult?.images.length || imageResult?.raw.trim() || historyItems.length);
}

function createBriefMarkdown({ prompt, model, imageResult, historyItems }: CreateWorkspaceState): string {
  const lines = [
    '# Create Brief',
    '',
    `Generated: ${new Date().toISOString()}`,
    'Studio: Image creation',
    `Image Model: ${model.trim() || 'Default image model'}`,
    `Current Prompt: ${prompt.trim() || 'n/a'}`,
    `History Items: ${historyItems.length}`,
  ];
  lines.push('', '## Images');
  if (!imageResult) {
    lines.push('No image result is active.');
  } else if (!imageResult.images.length) {
    lines.push('Raw image provider data is available, but no image previews were found.');
  } else {
    imageResult.images.forEach((image, index) => {
      const src = image.src.startsWith('data:') ? 'embedded data URL' : image.src;
      lines.push(
        `${index + 1}. ${image.prompt || prompt.trim() || 'Generated image'}`,
        `   - ID: ${image.id || 'n/a'}`,
        `   - Model: ${image.model || 'n/a'}`,
        `   - Size: ${image.size || 'n/a'}`,
        `   - Cost: ${image.cost || 'n/a'}`,
        `   - Filename: ${image.filename || 'n/a'}`,
        `   - Source: ${src || 'n/a'}`,
      );
    });
  }
  lines.push('', '## Recent History');
  if (!historyItems.length) {
    lines.push('- No recent Create history.');
  } else {
    historyItems.forEach((item, index) => {
      lines.push(
        `${index + 1}. Image · ${item.createdAt}`,
        `   - Prompt: ${item.prompt}`,
        `   - Summary: ${item.summary}`,
      );
    });
  }
  return lines.join('\n');
}

function createHistoryPacket(item: CreateHistoryItem): string {
  const lines = [
    '# Create History Packet',
    '',
    'Mode: Image',
    `Created: ${item.createdAt || 'n/a'}`,
    `Prompt: ${item.prompt || 'n/a'}`,
    `Summary: ${item.summary || 'n/a'}`,
  ];
  if (item.imageResult) {
    lines.push('', '## Image Snapshot');
    if (!item.imageResult.images.length) {
      lines.push('No image previews were stored with this history item.');
    } else {
      item.imageResult.images.forEach((image, index) => {
        const src = image.src.startsWith('data:') ? 'embedded data URL' : image.src;
        lines.push(
          `${index + 1}. ${image.prompt || item.prompt || 'Generated image'}`,
          `   - ID: ${image.id || 'n/a'}`,
          `   - Model: ${image.model || 'n/a'}`,
          `   - Size: ${image.size || 'n/a'}`,
          `   - Cost: ${image.cost || 'n/a'}`,
          `   - Filename: ${image.filename || 'n/a'}`,
          `   - Source: ${src || 'n/a'}`,
        );
      });
    }
  } else {
    lines.push('', '## Snapshot', 'No image snapshot was stored with this history item.');
  }
  return lines.join('\n');
}

function CreateHistoryCard({ item, onReuse, onCopy }: { item: CreateHistoryItem; onReuse: (item: CreateHistoryItem) => void; onCopy: (item: CreateHistoryItem) => void }) {
  return (
    <article className="createHistoryCard">
      {item.thumbnail ? <img src={item.thumbnail} alt="" /> : <div className="createHistoryBadge">I</div>}
      <div>
        <span>Image · {item.createdAt}</span>
        <strong>{item.prompt}</strong>
        <p>{item.summary}</p>
        <div className="createHistoryActions">
          <button className="secondaryButton" type="button" onClick={() => onReuse(item)}>Reuse</button>
          <button className="secondaryButton" type="button" onClick={() => onCopy(item)}>Copy</button>
        </div>
      </div>
    </article>
  );
}

type CodeActionRecord = {
  id: string;
  title: string;
  status: string;
  detail: string;
  raw: string;
  createdAt: string;
};

type CodeContextType = 'file' | 'diff' | 'image' | 'terminal';

type CodeContextItem = {
  id: string;
  type: CodeContextType;
  label: string;
  detail: string;
  source: string;
  status: string;
};

type CodeApprovalKind = 'command' | 'edit' | 'test';

type CodeApprovalItem = {
  id: string;
  kind: CodeApprovalKind;
  title: string;
  content: string;
  status: 'queued' | 'approved' | 'running' | 'complete' | 'failed';
  risk: string;
  taskId: string;
  result: string;
};

type CodeWorkerRecord = {
  id: string;
  taskId: string;
  title: string;
  sessionName: string;
  status: string;
  mirror: string;
  promoted: boolean;
};

type CodeChangeCard = {
  id: string;
  taskId: string;
  file: string;
  kind: string;
  summary: string;
  lines: string;
  status: string;
  conflict: boolean;
};

type CodeEvidenceHighlight = {
  id: string;
  label: string;
  target: 'terminal' | 'diff' | 'approval';
  detail: string;
};

type CodePromptPreview = {
  id: string;
  prompt: string;
  context: CodeContextItem[];
  submitted: boolean;
};

type CodeWorkspaceState = {
  sessionName: string;
  projectDir: string;
  model: string;
  prompt: string;
  actions: CodeActionRecord[];
  attachments: CodeAttachment[];
  contextItems: CodeContextItem[];
  approvals: CodeApprovalItem[];
  workers: CodeWorkerRecord[];
  changeCards: CodeChangeCard[];
  evidenceHighlights: CodeEvidenceHighlight[];
};

const CODE_WORKSPACE_SESSION_KEY = V2_WORKSPACE_SESSION_KEYS.codeWorkspace;
const CODE_ACTION_LIMIT = 20;
const CODE_ATTACHMENT_LIMIT = 8;
const CODE_ATTACHMENT_PREVIEW_LIMIT = 1_500_000;
const CODE_CONTEXT_LIMIT = 12;
const CODE_QUEUE_LIMIT = 12;
const CODE_WORKER_LIMIT = 8;
const CODE_CHANGE_CARD_LIMIT = 12;

function emptyCodeWorkspace(): CodeWorkspaceState {
  return {
    sessionName: '',
    projectDir: '',
    model: '',
    prompt: '',
    actions: [],
    attachments: [],
    contextItems: [],
    approvals: [],
    workers: [],
    changeCards: [],
    evidenceHighlights: [],
  };
}

function normalizeCodeAction(value: unknown): CodeActionRecord | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const title = asText(row.title);
  const detail = asText(row.detail);
  const createdAt = asText(row.createdAt);
  if (!title || !detail || !createdAt) return null;
  return {
    id: asText(row.id, `${createdAt}-${title}`),
    title,
    status: asText(row.status, 'updated'),
    detail,
    raw: asText(row.raw),
    createdAt,
  };
}

function normalizeCodeAttachment(value: unknown): CodeAttachment | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const id = asText(row.id);
  const sessionId = asText(row.session_id);
  const filename = asText(row.filename);
  const mimeType = asText(row.mime_type);
  if (!id || !sessionId || !filename || !mimeType) return null;
  const preview = typeof row.preview_url === 'string' && row.preview_url.length <= CODE_ATTACHMENT_PREVIEW_LIMIT ? row.preview_url : '';
  return {
    id,
    session_id: sessionId,
    filename,
    mime_type: mimeType,
    size_bytes: numeric(row.size_bytes),
    width: numeric(row.width),
    height: numeric(row.height),
    sha256: asText(row.sha256),
    created_at: numeric(row.created_at),
    actor_id: asText(row.actor_id),
    ...(preview ? { preview_url: preview } : {}),
  };
}

function normalizeContextType(value: unknown): CodeContextType {
  return value === 'diff' || value === 'image' || value === 'terminal' ? value : 'file';
}

function normalizeCodeContextItem(value: unknown): CodeContextItem | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const label = asText(row.label);
  if (!label) return null;
  return {
    id: asText(row.id, `context-${label}`),
    type: normalizeContextType(row.type),
    label,
    detail: asText(row.detail),
    source: asText(row.source),
    status: asText(row.status, 'staged'),
  };
}

function normalizeApprovalKind(value: unknown): CodeApprovalKind {
  return value === 'edit' || value === 'test' ? value : 'command';
}

function normalizeApprovalStatus(value: unknown): CodeApprovalItem['status'] {
  return value === 'approved' || value === 'running' || value === 'complete' || value === 'failed' ? value : 'queued';
}

function normalizeCodeApproval(value: unknown): CodeApprovalItem | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const content = asText(row.content);
  const title = asText(row.title);
  if (!content || !title) return null;
  return {
    id: asText(row.id, `approval-${title}`),
    kind: normalizeApprovalKind(row.kind),
    title,
    content,
    status: normalizeApprovalStatus(row.status),
    risk: asText(row.risk, 'normal'),
    taskId: asText(row.taskId, 'main'),
    result: asText(row.result),
  };
}

function normalizeCodeWorker(value: unknown): CodeWorkerRecord | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const title = asText(row.title);
  if (!title) return null;
  return {
    id: asText(row.id, `worker-${title}`),
    taskId: asText(row.taskId, 'main'),
    title,
    sessionName: asText(row.sessionName),
    status: asText(row.status, 'idle'),
    mirror: asText(row.mirror),
    promoted: Boolean(row.promoted),
  };
}

function normalizeCodeChangeCard(value: unknown): CodeChangeCard | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const file = asText(row.file);
  if (!file) return null;
  return {
    id: asText(row.id, `change-${file}`),
    taskId: asText(row.taskId, 'main'),
    file,
    kind: asText(row.kind, 'modified'),
    summary: asText(row.summary, 'Changed file'),
    lines: asText(row.lines, 'n/a'),
    status: asText(row.status, 'review'),
    conflict: Boolean(row.conflict),
  };
}

function normalizeEvidenceHighlight(value: unknown): CodeEvidenceHighlight | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const label = asText(row.label);
  const target = row.target === 'diff' || row.target === 'approval' ? row.target : 'terminal';
  if (!label) return null;
  return {
    id: asText(row.id, `evidence-${label}`),
    label,
    target,
    detail: asText(row.detail),
  };
}

function loadCodeWorkspace(): CodeWorkspaceState {
  if (typeof window === 'undefined') return emptyCodeWorkspace();
  try {
    const raw = window.sessionStorage.getItem(CODE_WORKSPACE_SESSION_KEY);
    if (!raw) return emptyCodeWorkspace();
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return emptyCodeWorkspace();
    const row = parsed as Record<string, unknown>;
    return {
      sessionName: asText(row.sessionName),
      projectDir: asText(row.projectDir),
      model: asText(row.model),
      prompt: asText(row.prompt),
      actions: Array.isArray(row.actions)
        ? row.actions.map(normalizeCodeAction).filter((action): action is CodeActionRecord => Boolean(action)).slice(0, CODE_ACTION_LIMIT)
        : [],
      attachments: Array.isArray(row.attachments)
        ? row.attachments.map(normalizeCodeAttachment).filter((attachment): attachment is CodeAttachment => Boolean(attachment)).slice(0, CODE_ATTACHMENT_LIMIT)
        : [],
      contextItems: Array.isArray(row.contextItems)
        ? row.contextItems.map(normalizeCodeContextItem).filter((item): item is CodeContextItem => Boolean(item)).slice(0, CODE_CONTEXT_LIMIT)
        : [],
      approvals: Array.isArray(row.approvals)
        ? row.approvals.map(normalizeCodeApproval).filter((item): item is CodeApprovalItem => Boolean(item)).slice(0, CODE_QUEUE_LIMIT)
        : [],
      workers: Array.isArray(row.workers)
        ? row.workers.map(normalizeCodeWorker).filter((item): item is CodeWorkerRecord => Boolean(item)).slice(0, CODE_WORKER_LIMIT)
        : [],
      changeCards: Array.isArray(row.changeCards)
        ? row.changeCards.map(normalizeCodeChangeCard).filter((item): item is CodeChangeCard => Boolean(item)).slice(0, CODE_CHANGE_CARD_LIMIT)
        : [],
      evidenceHighlights: Array.isArray(row.evidenceHighlights)
        ? row.evidenceHighlights.map(normalizeEvidenceHighlight).filter((item): item is CodeEvidenceHighlight => Boolean(item)).slice(0, CODE_CONTEXT_LIMIT)
        : [],
    };
  } catch {
    return emptyCodeWorkspace();
  }
}

function hasCodeWorkspaceState(state: CodeWorkspaceState): boolean {
  return Boolean(
    state.sessionName.trim() ||
    state.projectDir.trim() ||
    state.model.trim() ||
    state.prompt.trim() ||
    state.actions.length ||
    state.attachments.length ||
    state.contextItems.length ||
    state.approvals.length ||
    state.workers.length ||
    state.changeCards.length ||
    state.evidenceHighlights.length
  );
}

function saveCodeWorkspace(state: CodeWorkspaceState): void {
  if (typeof window === 'undefined') return;
  try {
    if (!hasCodeWorkspaceState(state)) {
      window.sessionStorage.removeItem(CODE_WORKSPACE_SESSION_KEY);
      return;
    }
    window.sessionStorage.setItem(CODE_WORKSPACE_SESSION_KEY, JSON.stringify({
      ...state,
      actions: state.actions.slice(0, CODE_ACTION_LIMIT),
      attachments: state.attachments.slice(0, CODE_ATTACHMENT_LIMIT),
      contextItems: state.contextItems.slice(0, CODE_CONTEXT_LIMIT),
      approvals: state.approvals.slice(0, CODE_QUEUE_LIMIT),
      workers: state.workers.slice(0, CODE_WORKER_LIMIT),
      changeCards: state.changeCards.slice(0, CODE_CHANGE_CARD_LIMIT),
      evidenceHighlights: state.evidenceHighlights.slice(0, CODE_CONTEXT_LIMIT),
    }));
  } catch {
    // Remote/private browser storage failures must not block coding work.
  }
}

function summarizeCodeAction(kind: 'start' | 'send' | 'review', payload: unknown, sessionName: string, prompt: string): CodeActionRecord {
  const row = payload && typeof payload === 'object' ? payload as Record<string, unknown> : {};
  const now = new Date();
  if (kind === 'start') {
    const name = asText(row.name, sessionName);
    const model = asText(row.model || row.default_model, '');
    const status = asText(row.status || row.ok || 'started');
    return {
      id: `${now.getTime()}-${kind}`,
      title: 'Session started',
      status: readableStatus(status),
      detail: [name, model].filter(Boolean).join(' · ') || 'Code session is ready.',
      raw: JSON.stringify(payload, null, 2),
      createdAt: now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' }),
    };
  }
  if (kind === 'send') {
    const ok = row.ok === true || row.status === 'ok';
    return {
      id: `${now.getTime()}-${kind}`,
      title: 'Sent to tmux',
      status: ok ? 'delivered' : readableStatus(asText(row.status || row.ok || 'sent')),
      detail: prompt.trim() ? prompt.trim().slice(0, 220) : 'Input sent to the active session.',
      raw: JSON.stringify(payload, null, 2),
      createdAt: now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' }),
    };
  }
  const answer = responseText(payload);
  return {
    id: `${now.getTime()}-${kind}`,
    title: 'Image review response',
    status: readableStatus(asText(row.status || 'complete')),
    detail: answer.slice(0, 500) || 'Review response received.',
    raw: JSON.stringify(payload, null, 2),
    createdAt: now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' }),
  };
}

function codeActionPacket(action: CodeActionRecord): string {
  return [
    '# Code Event Packet',
    '',
    `Title: ${action.title || 'n/a'}`,
    `Status: ${action.status || 'n/a'}`,
    `Created: ${action.createdAt || 'n/a'}`,
    `Detail: ${action.detail || 'n/a'}`,
    '',
    '## Raw Payload',
    action.raw || 'n/a',
  ].join('\n');
}

function codeBriefMarkdown({
  sessionName,
  projectDir,
  model,
  prompt,
  actions,
  attachments,
  contextItems = [],
  approvals = [],
  workers = [],
  changeCards = [],
}: {
  sessionName: string;
  projectDir: string;
  model: string;
  prompt: string;
  actions: CodeActionRecord[];
  attachments: CodeAttachment[];
  contextItems?: CodeContextItem[];
  approvals?: CodeApprovalItem[];
  workers?: CodeWorkerRecord[];
  changeCards?: CodeChangeCard[];
}): string {
  const lines = [
    '# Code Brief',
    '',
    `Generated: ${new Date().toISOString()}`,
    `Session: ${sessionName || 'n/a'}`,
    `Project: ${projectDir || 'n/a'}`,
    `Model: ${model || 'n/a'}`,
    `Pending Prompt: ${prompt.trim() || 'n/a'}`,
    `Actions: ${actions.length}`,
    `Attachments: ${attachments.length}`,
    `Context Items: ${contextItems.length}`,
    `Approvals: ${approvals.length}`,
    `Workers: ${workers.length}`,
    `Change Cards: ${changeCards.length}`,
    '',
    '## Attachments',
  ];
  if (!attachments.length) {
    lines.push('- No image attachments.');
  } else {
    attachments.forEach((attachment, index) => {
      lines.push(
        `${index + 1}. ${attachment.filename}`,
        `   - MIME: ${attachment.mime_type}`,
        `   - Size: ${Math.round(attachment.size_bytes / 1024)} KB`,
        `   - Dimensions: ${attachment.width || '?'} x ${attachment.height || '?'}`,
        `   - SHA256: ${attachment.sha256}`,
      );
    });
  }
  lines.push('', '## Context Tray');
  if (!contextItems.length) {
    lines.push('- No staged context.');
  } else {
    contextItems.forEach((item, index) => {
      lines.push(`${index + 1}. [${contextTypeLabel(item.type)}] ${item.label} - ${item.detail || item.source || item.status}`);
    });
  }
  lines.push('', '## Approval Queue');
  if (!approvals.length) {
    lines.push('- No queued approvals.');
  } else {
    approvals.forEach((item, index) => {
      lines.push(`${index + 1}. ${item.title} [${item.status}] - ${item.kind} · ${item.risk}`);
    });
  }
  lines.push('', '## Worker Mirrors');
  if (!workers.length) {
    lines.push('- No worker mirrors.');
  } else {
    workers.forEach((worker, index) => {
      lines.push(`${index + 1}. ${worker.title} [${worker.status}] - ${worker.sessionName || 'n/a'}`);
    });
  }
  lines.push('', '## Change Cards');
  if (!changeCards.length) {
    lines.push('- No change cards.');
  } else {
    changeCards.forEach((card, index) => {
      lines.push(`${index + 1}. ${card.file} - ${card.summary} (${card.kind}, ${card.status})`);
    });
  }
  lines.push('', '## Actions');
  if (!actions.length) {
    lines.push('- No code actions recorded.');
  } else {
    actions.forEach((action, index) => {
      lines.push(
        `### ${index + 1}. ${action.title}`,
        `- Time: ${action.createdAt}`,
        `- Status: ${action.status}`,
        `- Detail: ${action.detail}`,
        '',
        '```json',
        action.raw.replace(/```/g, '\\`\\`\\`'),
        '```',
        '',
      );
    });
  }
  return lines.join('\n');
}

function codeNowId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function contextTypeLabel(type: CodeContextType): string {
  if (type === 'diff') return 'Diff';
  if (type === 'image') return 'Image';
  if (type === 'terminal') return 'Terminal';
  return 'File';
}

function attachmentContextItem(attachment: CodeAttachment): CodeContextItem {
  return {
    id: `attachment:${attachment.id}`,
    type: 'image',
    label: attachment.filename,
    detail: `${Math.round(attachment.size_bytes / 1024)} KB · ${attachment.width || '?'} x ${attachment.height || '?'}`,
    source: attachment.sha256.slice(0, 12),
    status: 'attached',
  };
}

function uniqueCodeContext(items: CodeContextItem[]): CodeContextItem[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = `${item.type}:${item.label}:${item.source}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, CODE_CONTEXT_LIMIT);
}

function buildPromptBundle(prompt: string, context: CodeContextItem[]): string {
  const lines = [
    prompt.trim() || 'Continue the current Claude Code task.',
    '',
    'Context bundle:',
  ];
  if (!context.length) {
    lines.push('- No explicit context selected.');
  } else {
    context.forEach((item, index) => {
      lines.push(`${index + 1}. [${contextTypeLabel(item.type)}] ${item.label}`);
      if (item.detail) lines.push(`   Detail: ${item.detail}`);
      if (item.source) lines.push(`   Source: ${item.source}`);
    });
  }
  return lines.join('\n');
}

function sessionValue(row: Record<string, unknown>, key: string): string {
  return asText(row[key], '');
}

function dedupeTmuxSessions(rows: Array<Record<string, unknown>>): Array<Record<string, unknown>> {
  const seen = new Set<string>();
  return rows.filter((row) => {
    const name = sessionValue(row, 'name') || sessionValue(row, 'display_name');
    if (!name || seen.has(name)) return false;
    seen.add(name);
    return true;
  });
}

function findSessionRow(rows: Array<Record<string, unknown>>, sessionName: string): Record<string, unknown> | undefined {
  const clean = sessionName.trim();
  if (!clean) return undefined;
  return rows.find((row) => {
    const name = sessionValue(row, 'name');
    const display = sessionValue(row, 'display_name');
    return name === clean || display === clean || name === `matts-${clean}` || display === `matts-${clean}`;
  });
}

function parsedCodeStatus({
  promptPreview,
  approvals,
  workers,
  latestAction,
  pending,
  terminalController,
}: {
  promptPreview: CodePromptPreview | null;
  approvals: CodeApprovalItem[];
  workers: CodeWorkerRecord[];
  latestAction?: CodeActionRecord;
  pending: boolean;
  terminalController: boolean;
}): { state: string; task: string; waitingOn: string } {
  const queued = approvals.filter((item) => item.status === 'queued');
  const runningWorker = workers.find((item) => item.status === 'running');
  if (promptPreview && !promptPreview.submitted) {
    return { state: 'Waiting', task: 'Prompt bundle preview', waitingOn: 'Send or revise bundle' };
  }
  if (queued.length) {
    return { state: 'Waiting', task: queued[0].title, waitingOn: 'Approval queue' };
  }
  if (pending || runningWorker) {
    return { state: 'Running', task: runningWorker?.title || 'Claude Code action', waitingOn: 'Worker output' };
  }
  if (terminalController) {
    return { state: 'Manual', task: 'Direct terminal control', waitingOn: 'User terminal input' };
  }
  return { state: latestAction ? latestAction.status : 'Ready', task: latestAction?.title || 'Claude Code session', waitingOn: 'No input needed' };
}

function taskChangeCardsForContext(context: CodeContextItem[], taskId: string): CodeChangeCard[] {
  return context
    .filter((item) => item.type === 'file' || item.type === 'diff')
    .map((item) => ({
      id: codeNowId('change'),
      taskId,
      file: item.label,
      kind: item.type === 'diff' ? 'diff' : 'context',
      summary: item.detail || `Included as ${contextTypeLabel(item.type).toLowerCase()} context`,
      lines: item.source || 'selected context',
      status: 'review',
      conflict: false,
    }));
}

function starterApprovalItems(taskId: string, bundle: string): CodeApprovalItem[] {
  return [
    {
      id: codeNowId('approval'),
      kind: 'command',
      title: 'Submit Claude Code bundle',
      content: bundle,
      status: 'queued',
      risk: 'normal',
      taskId,
      result: '',
    },
    {
      id: codeNowId('approval'),
      kind: 'test',
      title: 'Run focused validation',
      content: 'npm --prefix frontend run build',
      status: 'queued',
      risk: 'normal',
      taskId,
      result: '',
    },
  ];
}

export function ChatPage({ voicePreferences, onVoicePreferencesChange }: { voicePreferences?: VoicePreferences; onVoicePreferencesChange?: (updater: VoicePreferences | ((current: VoicePreferences) => VoicePreferences)) => void } = {}) {
  const chat = useQuery({ queryKey: ['chat-payload'], queryFn: getChatPayload });
  const speech = useQuery({ queryKey: ['speech-status'], queryFn: getSpeechStatus, retry: false, refetchInterval: 30000 });
  const chatCapabilities = useQuery({ queryKey: ['chat-capabilities'], queryFn: getMeCapabilities, retry: false });
  const [localVoicePreferences, setLocalVoicePreferences] = useState(loadVoicePreferences);
  const activeVoicePreferences = voicePreferences || localVoicePreferences;
  const commitVoicePreferences = (updater: VoicePreferences | ((current: VoicePreferences) => VoicePreferences)) => {
    if (onVoicePreferencesChange) {
      onVoicePreferencesChange(updater);
      return;
    }
    setLocalVoicePreferences((current) => saveVoicePreferences(typeof updater === 'function' ? updater(current) : updater));
  };
  const models = useTextModels(chat.data?.models);
  const restoredUi = useMemo(loadChatUiState, []);
  const [model, setModel] = useState(restoredUi.selectedModel);
  const [contactFilter, setContactFilter] = useState('');
  const { favorites: favoriteIds } = useModelFavorites();
  const chatTheme = useThemeMode();
  const [contactsOpen, setContactsOpen] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>(loadChatTranscript);
  const [voiceEnabled, setVoiceEnabled] = useState(activeVoicePreferences.enabled);
  const [voiceDefaultLoaded, setVoiceDefaultLoaded] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState('Ready');
  const [speechInputStatus, setSpeechInputStatus] = useState('Speech input idle');
  const [listening, setListening] = useState(false);
  const [lastSpeechUrl, setLastSpeechUrl] = useState('');
  const [transcriptStatus, setTranscriptStatus] = useState('Ready');
  const selectedModel = models.some((item) => item.id === model)
    ? model
    : models.some((item) => item.id === chat.data?.default_model)
      ? chat.data?.default_model || ''
      : models[0]?.id || '';
  const selectedModelCard = models.find((item) => item.id === selectedModel) || models[0];
  const [contactsDrawerOpen, setContactsDrawerOpen] = useState(false);
  const contactPane = useMemo(() => chatContactPane(models, favoriteIds, selectedModel, contactFilter), [contactFilter, favoriteIds, models, selectedModel]);
  const contactsDrawerExpanded = contactsDrawerOpen || Boolean(contactFilter.trim());
  const activePresence = chatPresence(selectedModelCard);
  const canUseChat = chatCapabilities.data?.capabilities['chat.use']?.allowed === true;
  const chatUseDenied = Boolean(chatCapabilities.data && !canUseChat);
  const chatAuthPrompted = useRef(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const lastSpeechUrlRef = useRef('');
  const previousGlobalVoicePreset = useRef(activeVoicePreferences.globalPresetId);
  const voiceProfile = chat.data?.voice;
  const embeddedSpeechStatus = voiceProfile?.server_engine;
  const speechStatus: SpeechStatusPayload | undefined = speech.data || embeddedSpeechStatus;
  const serverSpeechMode = speechStatus?.mode || voiceProfile?.mode || '';
  const serverSpeechAvailable = Boolean(speechStatus?.available && ['server_qwen3_tts', 'server_do_qwen3_tts'].includes(serverSpeechMode));
  const digitalOceanSpeech = speechStatus?.engine === 'digitalocean_qwen3_tts' || serverSpeechMode === 'server_do_qwen3_tts';
  const selectedVoicePreset = voicePresetForModel(activeVoicePreferences, selectedModelCard);
  const voiceInstruct = voiceInstructionForPreset(selectedVoicePreset, selectedModelCard) || DEFAULT_VOICE_INSTRUCT;
  const voiceLanguage = activeVoicePreferences.language || DEFAULT_VOICE_LANGUAGE;
  const voiceStyle = selectedVoicePreset.label;
  const voiceMode = serverSpeechAvailable ? (digitalOceanSpeech ? 'DigitalOcean Qwen3 TTS' : 'Qwen3 TTS VoiceDesign') : readableStatus(voiceProfile?.fallback_mode || voiceProfile?.mode || 'browser_speech_synthesis');
  const voiceEngineLabel = serverSpeechAvailable ? voiceMode : 'Browser fallback';
  const voicePreview = selectedVoicePreset.sample || voiceProfile?.preview || "Hello, I'm your MDE assistant.";
  const voiceMaxChars = Math.max(200, numeric(speechStatus?.max_chars || voiceProfile?.max_chars) || 1200);
  const speechInputSupported = Boolean(speechRecognitionConstructor());
  const serverSpeechInputUnavailable = speechStatus?.input?.server_speech_to_text === false || speechStatus?.input?.digitalocean_speech_to_text === false;
  const speechInputLabel = speechInputSupported ? speechInputStatus : (serverSpeechInputUnavailable ? 'Browser-native input unavailable' : 'Speech input unavailable');
  const serverVoiceStatusLabel = serverSpeechAvailable ? (digitalOceanSpeech ? 'DigitalOcean Qwen3 voice' : 'Qwen3 server voice') : (digitalOceanSpeech ? 'DigitalOcean voice unavailable' : 'Browser fallback');
  const voiceDetail = [voiceEngineLabel, voiceStatus, `${voiceMaxChars.toLocaleString()} chars`].filter(Boolean).join(' · ');
  const transcript = serializeTranscript(messages);
  const chatBrief = chatBriefMarkdown(messages, selectedModel, selectedModelCard);
  const lastAssistant = [...messages].reverse().find((message) => message.role === 'assistant');
  const activeContactLabel = selectedModelCard?.display_name || 'No contact selected';
  const modelForMessage = (message: ChatMessage): ModelCard | undefined => {
    if (message.role !== 'assistant') return undefined;
    return models.find((item) => item.display_name === message.model || item.id === message.model) || selectedModelCard;
  };
  const copyTranscript = async () => {
    if (!transcript) return;
    try {
      await copyText(transcript);
      setTranscriptStatus('Copied');
    } catch {
      setTranscriptStatus('Copy failed');
    }
  };
  const downloadTranscript = () => {
    if (!transcript) return;
    const blob = new Blob([transcript], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `mde-llm-proxy-chat-transcript-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.txt`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    setTranscriptStatus('Downloaded');
  };
  const { copyBrief: copyChatBrief, downloadBrief: downloadChatBrief } = briefDeliveryActions(chatBrief, 'mde-llm-proxy-chat-brief', setTranscriptStatus, {
    copied: 'Brief copied',
    copyFailed: 'Brief copy failed',
    downloaded: 'Brief downloaded',
  }, messages.length > 0);
  useEffect(() => {
    if (!voiceProfile || voiceDefaultLoaded) return;
    if (!voicePreferences) {
      setVoiceEnabled(voiceProfile.enabled_by_default !== false);
    }
    setVoiceDefaultLoaded(true);
  }, [voiceDefaultLoaded, voicePreferences, voiceProfile]);
  useEffect(() => {
    if (voiceEnabled === activeVoicePreferences.enabled) return;
    if (!activeVoicePreferences.enabled) stopVoice(true);
    setVoiceEnabled(activeVoicePreferences.enabled);
  }, [activeVoicePreferences.enabled, voiceEnabled]);
  useEffect(() => {
    const previous = previousGlobalVoicePreset.current;
    if (previous === activeVoicePreferences.globalPresetId) return;
    previousGlobalVoicePreset.current = activeVoicePreferences.globalPresetId;
    if (!selectedModel) return;
    commitVoicePreferences((current) => setModelVoicePreset(current, selectedModel, activeVoicePreferences.globalPresetId));
  }, [activeVoicePreferences.globalPresetId, selectedModel]);
  useEffect(() => {
    if (!voiceProfile && !speechStatus) return;
    if (serverSpeechAvailable) {
      setVoiceStatus(voiceEnabled ? 'Ready' : 'Muted');
    } else if (!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') {
      setVoiceStatus('Unavailable');
    } else {
      setVoiceStatus(voiceEnabled ? 'Ready' : 'Muted');
    }
  }, [serverSpeechAvailable, speechStatus, voiceEnabled, voiceProfile]);
  useEffect(() => () => {
    if (lastSpeechUrlRef.current) URL.revokeObjectURL(lastSpeechUrlRef.current);
    audioRef.current?.pause();
    recognitionRef.current?.abort();
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  }, []);
  useEffect(() => {
    saveChatTranscript(messages);
  }, [messages]);
  useEffect(() => {
    saveChatUiState({ selectedModel });
  }, [selectedModel]);
  useEffect(() => {
    if (!models.length) return;
    if (!selectedModel || !models.some((item) => item.id === selectedModel)) setModel(models[0].id);
  }, [models, selectedModel]);
  const requestChatModelUse = () => {
    window.dispatchEvent(new CustomEvent(V2_AUTH_REQUIRED_EVENT, {
      detail: {
        title: 'Model Use Required',
        detail: 'Sign in with a console token that includes model_use to send Chat requests.',
      },
    }));
  };
  useEffect(() => {
    if (!chatUseDenied || chatAuthPrompted.current) return;
    chatAuthPrompted.current = true;
    requestChatModelUse();
  }, [chatUseDenied]);
  const stopVoice = (fade = false) => {
    const player = audioRef.current;
    if (player) {
      if (fade && !player.paused) {
        const startVolume = player.volume || 1;
        const startedAt = window.performance.now();
        const fadeAudio = () => {
          const elapsed = window.performance.now() - startedAt;
          const progress = Math.min(1, elapsed / 1000);
          player.volume = Math.max(0, startVolume * (1 - progress));
          if (progress < 1) {
            window.requestAnimationFrame(fadeAudio);
            return;
          }
          player.pause();
          player.currentTime = 0;
          player.volume = startVolume;
        };
        window.requestAnimationFrame(fadeAudio);
      } else {
        player.pause();
        player.currentTime = 0;
        player.volume = 1;
      }
    }
    if ('speechSynthesis' in window) {
      if (fade) window.setTimeout(() => window.speechSynthesis.cancel(), 1000);
      else window.speechSynthesis.cancel();
    }
    setVoiceStatus(voiceEnabled ? 'Ready' : 'Muted');
  };
  const browserSpeak = (text: string) => {
    if (!voiceEnabled) return;
    if (!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') {
      setVoiceStatus('Unavailable');
      return;
    }
    const utterance = new SpeechSynthesisUtterance(text.slice(0, voiceMaxChars));
    utterance.rate = 0.96;
    utterance.pitch = 1;
    utterance.onstart = () => setVoiceStatus('Speaking');
    utterance.onend = () => setVoiceStatus('Ready');
    utterance.onerror = () => setVoiceStatus('Interrupted');
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  };
  const speak = async (text: string) => {
    if (!voiceEnabled) return;
    const speechText = text.slice(0, voiceMaxChars).trim();
    if (!speechText) return;
    if (!serverSpeechAvailable) {
      browserSpeak(speechText);
      return;
    }
    stopVoice();
    setVoiceStatus('Synthesizing');
    try {
      const audio = await synthesizeSpeech({
        text: speechText,
        language: voiceLanguage || speechStatus?.language || 'Auto',
        instruct: voiceInstruct || speechStatus?.instruct || DEFAULT_VOICE_INSTRUCT,
      });
      const url = URL.createObjectURL(audio);
      if (lastSpeechUrlRef.current) URL.revokeObjectURL(lastSpeechUrlRef.current);
      lastSpeechUrlRef.current = url;
      setLastSpeechUrl(url);
      const player = new Audio(url);
      audioRef.current = player;
      player.onplaying = () => setVoiceStatus('Speaking');
      player.onended = () => setVoiceStatus(voiceEnabled ? 'Ready' : 'Muted');
      player.onerror = () => {
        setVoiceStatus('Browser fallback');
        browserSpeak(speechText);
      };
      await player.play();
    } catch {
      setVoiceStatus('Browser fallback');
      browserSpeak(speechText);
    }
  };
  const downloadLastSpeech = () => {
    if (!lastSpeechUrl) return;
    const link = document.createElement('a');
    link.href = lastSpeechUrl;
    link.download = `mde-llm-proxy-speech-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.wav`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setVoiceStatus('Downloaded');
  };
  const toggleListening = () => {
    const Recognition = speechRecognitionConstructor();
    if (!Recognition) {
      setSpeechInputStatus('Speech input unavailable');
      return;
    }
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      setSpeechInputStatus('Speech input idle');
      return;
    }
    const recognition = new Recognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = speechLocale(voiceLanguage || 'English');
    recognition.onresult = (event: unknown) => {
      const transcriptText = recognitionTranscript(event);
      if (!transcriptText) return;
      setPrompt((current) => current.trim() ? `${current.trim()} ${transcriptText}` : transcriptText);
      setSpeechInputStatus('Captured speech');
    };
    recognition.onerror = () => {
      setListening(false);
      setSpeechInputStatus('Speech input error');
    };
    recognition.onend = () => {
      recognitionRef.current = null;
      setListening(false);
      setSpeechInputStatus((current) => current === 'Listening' ? 'Speech input idle' : current);
    };
    recognitionRef.current = recognition;
    setListening(true);
    setSpeechInputStatus('Listening');
    try {
      recognition.start();
    } catch {
      recognitionRef.current = null;
      setListening(false);
      setSpeechInputStatus('Speech input error');
    }
  };
  const toggleVoice = () => {
    const next = !voiceEnabled;
    if (!next) stopVoice(true);
    setVoiceEnabled(next);
    commitVoicePreferences((current) => ({ ...current, enabled: next }));
  };
  const clearTranscript = () => {
    setMessages([]);
    saveChatTranscript([]);
    setTranscriptStatus('Cleared');
    stopVoice();
  };
  const selectContact = (id: string) => {
    setModel(id);
    setContactsOpen(false);
  };
  type ChatSendRequest = {
    prompt: string;
    baseMessages: ChatMessage[];
    userMessageId: string;
    modelId: string;
    modelName: string;
    company?: string;
    accent?: string;
  };
  const mutation = useMutation({
    mutationFn: (request: ChatSendRequest) => runChat({ model: request.modelId, client_selected_model_id: request.modelId, messages: [...request.baseMessages, { role: 'user', content: request.prompt }] }),
    onSuccess: (payload, request) => {
      const answer = responseText(payload);
      const diagnostic = responseHasDiagnostics(payload);
      const metadata = chatResponseMetadata(payload);
      const diagnosticDetail = diagnostic ? JSON.stringify(responseObject(payload), null, 2) : '';
      setMessages((current) => [
        ...current.map((message) => message.id === request.userMessageId ? { ...message, delivery: undefined } : message),
        {
          id: chatMessageId('assistant'),
          role: 'assistant',
          content: answer || 'Model response diagnostic\n- The model returned no visible assistant text.',
          model: request.modelName,
          company: request.company,
          accent: request.accent,
          createdAt: chatTimestamp(),
          ...(metadata ? { metadata } : {}),
          diagnostic,
          ...(diagnosticDetail ? { diagnosticDetail } : {}),
        }
      ].slice(-CHAT_TRANSCRIPT_LIMIT));
      setPrompt('');
      if (!diagnostic) void speak(answer);
    },
    onError: (error, request) => {
      setMessages((current) => current.map((message) => message.id === request.userMessageId ? { ...message, delivery: 'failed' } : message));
      if (authLikeError(error)) requestChatModelUse();
    }
  });
  const canSendChat = Boolean(prompt.trim()) && !mutation.isPending && canUseChat;
  const sendChat = () => {
    if (chatUseDenied) {
      requestChatModelUse();
      return;
    }
    if (!canSendChat) return;
    const text = prompt.trim();
    const userMessageId = chatMessageId('user');
    const userMessage: ChatMessage = {
      id: userMessageId,
      role: 'user',
      content: text,
      createdAt: chatTimestamp(),
      delivery: 'sending',
    };
    setMessages((current) => [...current, userMessage].slice(-CHAT_TRANSCRIPT_LIMIT));
    setPrompt('');
    mutation.mutate({
      prompt: text,
      baseMessages: messages,
      userMessageId,
      modelId: selectedModel,
      modelName: selectedModelCard?.display_name || selectedModel,
      company: selectedModelCard?.company,
      accent: selectedModelCard?.nation_palette?.accent,
    });
  };
  const handleChatComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey) return;
    if (!canSendChat) return;
    event.preventDefault();
    sendChat();
  };
  return (
    <section className={`heroWorkspace chatHero ${chatTheme === 'dark' ? 'chatThemeDark' : 'chatThemeLight'} ${contactsOpen ? 'contactPaneOpen' : ''}`}>
      <div className="heroHeader">
        <div>
          <p className="eyebrow">Autonomous System Manager</p>
          <h1>Chat</h1>
          <p>Classic contact-list chat where routable LLMs appear as online buddies with Carbon-aware status and controls.</p>
        </div>
        <div className="heroActions">
          <button className="secondaryButton chatContactsToggle" type="button" onClick={() => setContactsOpen(true)}>
            <CarbonIcon path="apps/system-users.svg" label="Contacts" />
            Contacts
          </button>
          <button className="secondaryButton" type="button" aria-pressed={chatTheme === 'dark'} onClick={() => applyThemeMode(chatTheme === 'dark' ? 'light' : 'dark')}>
            <CarbonIcon path={chatTheme === 'dark' ? 'apps/light.svg' : 'apps/moon.svg'} label="Theme" />
            {chatTheme === 'dark' ? 'Light' : 'Dark'}
          </button>
        </div>
      </div>
      <div className="icqChatShell">
        <button className="icqContactScrim" type="button" aria-label="Close contacts" onClick={() => setContactsOpen(false)} />
        <aside className="icqContactPane" aria-label="LLM contact list">
          <div className="icqWindowTitle">
            <div>
              <span>ICQ Contacts</span>
              <strong>{models.length.toLocaleString()} online</strong>
            </div>
            <button className="iconButton icqCloseContacts" type="button" aria-label="Close contacts" onClick={() => setContactsOpen(false)}>
              <CarbonIcon path="actions/window-close-symbolic.svg" label="Close" />
            </button>
          </div>
          {chat.isLoading ? <StatusPanel tone="loading" title="Loading chat workspace" /> : null}
          {chat.error ? <StatusPanel tone="error" title="Chat API unavailable" detail={errorText(chat.error)} /> : null}
          {chatUseDenied && !chat.error ? <StatusPanel tone="error" title="Model-use permission required" detail="Chat is visible with console view access, but sending messages requires model_use." /> : null}
          {!chat.isLoading && !chat.error && !models.length ? <StatusPanel title="No routable text models" detail="Enable or discover a routable text model before sending chat requests." /> : null}
          <label className="icqContactSearch">
            <CarbonIcon path="actions/system-search-symbolic.svg" label="Search" />
            <input value={contactFilter} onChange={(event) => setContactFilter(event.target.value)} placeholder="Find LLM contact" />
          </label>
          <div className="icqContactGroups">
            <section className="icqContactGroup icqPinnedGroup" key="pinned">
              <div className="icqGroupHeader">
                <span>⭐ Pinned</span>
                <strong>{contactPane.pinned.length}</strong>
              </div>
              {contactPane.pinned.map((contact) => (
                <ModelIdentityCard
                  key={`pinned-${contact.id}`}
                  model={contact}
                  size="small"
                  onPrimary={(target) => selectContact(target.id)}
                  active={contact.id === selectedModel}
                  testId="chat-contact-card"
                />
              ))}
              {favoriteIds.length === 0 && !contactFilter.trim() ? (
                <p className="icqPinnedHint">☆ Star a model to keep it here.</p>
              ) : null}
            </section>
            <button
              type="button"
              className={`icqDrawerHeader ${contactsDrawerExpanded ? 'open' : ''}`}
              aria-expanded={contactsDrawerExpanded}
              data-testid="chat-contacts-drawer-toggle"
              onClick={() => setContactsDrawerOpen((current) => !current)}
            >
              <span className="icqDrawerChevron" aria-hidden="true">▸</span>
              All contacts ({contactPane.totalCount})
            </button>
            <section className={`icqContactDrawer ${contactsDrawerExpanded ? 'open' : ''}`} aria-hidden={!contactsDrawerExpanded}>
              {contactsDrawerExpanded ? (
                contactPane.drawer.length ? contactPane.drawer.map((contact) => (
                  <ModelIdentityCard
                    key={`drawer-${contact.id}`}
                    model={contact}
                    size="small"
                    onPrimary={(target) => selectContact(target.id)}
                    active={contact.id === selectedModel}
                    testId="chat-contact-card"
                  />
                )) : <div className="emptyState">No contacts match this search.</div>
              ) : null}
            </section>
          </div>
        </aside>
        <main className="icqChatWindow">
          <div className="icqWindowTitle icqChatTitle">
            <div className="icqActiveContact">
              {selectedModelCard ? <ModelLogo model={selectedModelCard} /> : <div className="chatUserAvatar"><CarbonIcon path="apps/chat-bot.svg" label="Model" /></div>}
              <div>
                <span><i className={`presenceDot ${activePresence.tone}`} /> {activePresence.label}</span>
                <strong>{activeContactLabel}</strong>
                <p>{selectedModelCard ? `${selectedModelCard.company} · ${selectedModelCard.training_nation} · ${selectedModelCard.cost_label}` : 'Select an LLM contact'}</p>
              </div>
            </div>
            <div className="icqChatStats">
              <span>{messages.length} message{messages.length === 1 ? '' : 's'}</span>
              <span>{transcriptStatus}</span>
            </div>
          </div>
          <div className={`voiceConsole icqVoiceStrip ${voiceEnabled ? 'active' : 'muted'}`} aria-label="Chat voice controls">
            <div className="voiceConsoleLead">
              <CarbonIcon path={voiceEnabled ? 'actions/media-playback-start-symbolic.svg' : 'actions/media-playback-stop-symbolic.svg'} label="Voice status" />
              <div>
                <span>{voiceEnabled ? 'Voice enabled' : 'Voice muted'}</span>
                <strong>{voiceStyle}</strong>
                <p>{voiceDetail}</p>
              </div>
            </div>
            <div className="voiceControls">
              <button className="secondaryButton" type="button" onClick={toggleVoice}>{voiceEnabled ? 'Mute' : 'Enable'}</button>
              <button className="secondaryButton" type="button" onClick={() => void speak(voicePreview)} disabled={!voiceEnabled}>Preview</button>
              <button className="secondaryButton" type="button" onClick={toggleListening} disabled={!speechInputSupported}>{listening ? 'Stop Listen' : 'Listen'}</button>
              <button className="secondaryButton" type="button" onClick={downloadLastSpeech} disabled={!lastSpeechUrl}>Download Speech</button>
            </div>
            <div className="voiceSettings">
              <span className="voiceToolbarHint">{voiceLanguage} · global preset</span>
              <span className="voiceToolbarHint">{serverVoiceStatusLabel}</span>
              <span className="voiceInputStatus" role="status">{speechInputLabel}</span>
            </div>
          </div>
          <div className="transcriptToolbar icqTranscriptStrip" aria-label="Chat transcript controls">
            <div>
              <span>History</span>
              <strong>{lastAssistant?.model || selectedModelCard?.display_name || 'No response yet'}</strong>
            </div>
            <div className="transcriptActions">
              <button className="secondaryButton" type="button" disabled={!messages.length} onClick={() => void copyTranscript()}>Copy</button>
              <button className="secondaryButton" type="button" disabled={!messages.length} onClick={downloadTranscript}>Download</button>
              <button className="secondaryButton" type="button" disabled={!messages.length} onClick={() => void copyChatBrief()}>Copy Brief</button>
              <button className="secondaryButton" type="button" disabled={!messages.length} onClick={downloadChatBrief}>Download Brief</button>
              <button className="secondaryButton" type="button" disabled={!messages.length} onClick={clearTranscript}>Clear</button>
            </div>
          </div>
          <div className="conversationPanel icqTranscriptPane">
            {mutation.isPending ? <div className="icqSystemNotice">Waiting for {selectedModelCard?.display_name || selectedModel}...</div> : null}
            {messages.length ? messages.map((message, index) => {
              const rowModel = modelForMessage(message);
              const isAssistant = message.role === 'assistant';
              const isUser = message.role === 'user';
              const rowTitle = message.diagnostic ? 'System message' : isUser ? 'You' : message.model || rowModel?.display_name || 'Assistant';
              return (
                <div className={`messageRow ${message.role} ${message.diagnostic ? 'diagnostic system' : ''}`} key={message.id || `${message.role}-${index}`} style={{ ['--message-accent' as string]: message.accent || rowModel?.nation_palette?.accent || undefined }}>
                  {isAssistant && rowModel && !message.diagnostic ? (
                    <div className="messageModelCard">
                      <ModelIdentityCard model={rowModel} size="small" showFavorite={false} testId="chat-message-model-card" />
                    </div>
                  ) : (
                    <div className="messageAvatar" aria-hidden="true">
                      {message.diagnostic ? <CarbonIcon path="apps/information--filled.svg" label="System" /> : <div className="chatUserAvatar"><CarbonIcon path="apps/user--avatar.svg" label="User" /></div>}
                    </div>
                  )}
                  <div className="messageBody">
                    <div className="messageHeaderLine">
                      <strong>{rowTitle}</strong>
                      <time>{formatChatTimestamp(message.createdAt)}</time>
                      {message.delivery ? <small className={`deliveryState ${message.delivery}`}>{message.delivery}</small> : null}
                    </div>
                    {message.metadata ? <small className="messageMetadata">{message.metadata}</small> : null}
                    <p>{message.content}</p>
                    {message.diagnosticDetail ? (
                      <details className="messageDiagnostics">
                        <summary>Raw payload</summary>
                        <pre>{message.diagnosticDetail}</pre>
                      </details>
                    ) : null}
                  </div>
                </div>
              );
            }) : (
              <div className="chatEmptyState">
                <div className="chatEmptyMark">
                  {selectedModelCard ? <ModelLogo model={selectedModelCard} /> : <CarbonIcon path="apps/chat-bot.svg" label="Model" />}
                </div>
                <div>
                  <span>Ready for dialogue</span>
                  <strong>{activeContactLabel}</strong>
                  <small>No conversation yet.</small>
                  <p>{selectedModelCard ? `${selectedModelCard.company} model contact. ${selectedModelCard.cost_label || 'Cost metadata pending.'}` : 'Select an LLM contact to start a session.'}</p>
                </div>
                <div className="chatStarterRow" aria-label="Suggested starters">
                  <button type="button" onClick={() => setPrompt('Summarize the current operator status and next action.')}>Status brief</button>
                  <button type="button" onClick={() => setPrompt('Compare the active model with a lower-cost alternative.')}>Compare model</button>
                  <button type="button" onClick={() => setPrompt('Draft a concise technical answer with citations where available.')}>Draft answer</button>
                </div>
              </div>
            )}
          </div>
          <form className="icqComposer" onSubmit={(event) => { event.preventDefault(); sendChat(); }}>
            <textarea className="icqComposerInput" value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={handleChatComposerKeyDown} placeholder="Message active LLM contact" aria-label="Chat message" />
            <button className="primaryButton" type="submit" disabled={!canSendChat}>
              <CarbonIcon path="actions/document-send-symbolic.svg" label="Send" />
              {mutation.isPending ? 'Sending' : 'Send'}
            </button>
          </form>
          {mutation.error ? <div className="errorBanner">{errorText(mutation.error)}</div> : null}
        </main>
      </div>
    </section>
  );
}

async function fileToUploadPayload(file: File, sessionId: string): Promise<{ payload: Record<string, unknown>; previewUrl: string }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Unable to read image file.'));
    reader.onload = () => {
      const data = String(reader.result || '');
      resolve({ payload: { session_id: sessionId, filename: file.name, mime_type: file.type, data }, previewUrl: data });
    };
    reader.readAsDataURL(file);
  });
}

export function CodePage() {
  const queryClient = useQueryClient();
  const code = useQuery({ queryKey: ['code-payload'], queryFn: getCodePayload });
  const capabilities = useQuery({ queryKey: ['code-capabilities'], queryFn: getMeCapabilities, retry: false });
  const tmuxWorkspace = useQuery({ queryKey: ['code-tmux-workspace'], queryFn: getTmuxWorkspace, refetchInterval: 5000, retry: false });
  const models = useTextModels(code.data?.models);
  const defaults = code.data?.defaults || {};
  const restoredWorkspace = useMemo(loadCodeWorkspace, []);
  const defaultWorkspaceLoaded = useRef(false);
  const [sessionName, setSessionName] = useState(restoredWorkspace.sessionName || asText(defaults.default_name, 'matts-code'));
  const [projectDir, setProjectDir] = useState(restoredWorkspace.projectDir || asText(defaults.default_project_dir, ''));
  const [model, setModel] = useState(restoredWorkspace.model);
  const [prompt, setPrompt] = useState(restoredWorkspace.prompt);
  const [actions, setActions] = useState<CodeActionRecord[]>(restoredWorkspace.actions);
  const [outputStatus, setOutputStatus] = useState(restoredWorkspace.actions.length ? 'Restored' : 'Ready');
  const [copiedActionId, setCopiedActionId] = useState('');
  const [attachments, setAttachments] = useState<CodeAttachment[]>(restoredWorkspace.attachments);
  const [contextItems, setContextItems] = useState<CodeContextItem[]>(restoredWorkspace.contextItems);
  const [approvals, setApprovals] = useState<CodeApprovalItem[]>(restoredWorkspace.approvals);
  const [workers, setWorkers] = useState<CodeWorkerRecord[]>(restoredWorkspace.workers);
  const [changeCards, setChangeCards] = useState<CodeChangeCard[]>(restoredWorkspace.changeCards);
  const [evidenceHighlights, setEvidenceHighlights] = useState<CodeEvidenceHighlight[]>(restoredWorkspace.evidenceHighlights);
  const [promptPreview, setPromptPreview] = useState<CodePromptPreview | null>(null);
  const [contextType, setContextType] = useState<CodeContextType>('file');
  const [contextLabel, setContextLabel] = useState('');
  const [contextDetail, setContextDetail] = useState('');
  const [contextSource, setContextSource] = useState('');
  const [replyText, setReplyText] = useState('');
  const [selectedSession, setSelectedSession] = useState(restoredWorkspace.sessionName || '');
  const [attachmentError, setAttachmentError] = useState('');
  const [tmuxAttachActive, setTmuxAttachActive] = useState(false);
  const [proxyTuiOpen, setProxyTuiOpen] = useState(false);
  const [terminalController, setTerminalController] = useState(false);
  const terminalClient = useMemo(clientId, []);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const selectedModel = model || asText(defaults.default_model, models[0]?.id || '');
  const canControlTmux = capabilities.data?.capabilities['tmux.control']?.allowed ?? false;
  const canControlTui = capabilities.data?.capabilities['tui.control']?.allowed ?? false;
  const tmuxSessions = useMemo(
    () => dedupeTmuxSessions([...(tmuxWorkspace.data?.sessions ?? []), ...(code.data?.sessions ?? [])]),
    [code.data?.sessions, tmuxWorkspace.data?.sessions]
  );
  const activeSession = selectedSession || sessionName;
  const activeSessionRow = findSessionRow(tmuxSessions, activeSession);
  const visibleContext = useMemo(
    () => uniqueCodeContext([...contextItems, ...attachments.map(attachmentContextItem)]),
    [attachments, contextItems]
  );
  const hasCodeBrief = Boolean(actions.length || attachments.length || contextItems.length || approvals.length || workers.length || changeCards.length);
  const codeBrief = useMemo(
    () => codeBriefMarkdown({ sessionName, projectDir, model: selectedModel, prompt, actions, attachments, contextItems, approvals, workers, changeCards }),
    [actions, approvals, attachments, changeCards, contextItems, projectDir, prompt, selectedModel, sessionName, workers]
  );
  useEffect(() => {
    if (defaultWorkspaceLoaded.current || restoredWorkspace.sessionName || !code.data?.defaults) return;
    const nextDefaults = code.data.defaults;
    setSessionName(asText(nextDefaults.default_name, sessionName || 'matts-code'));
    setSelectedSession(asText(nextDefaults.default_name, sessionName || 'matts-code'));
    setProjectDir(asText(nextDefaults.default_project_dir, projectDir));
    if (!model) setModel(asText(nextDefaults.default_model, ''));
    defaultWorkspaceLoaded.current = true;
  }, [code.data?.defaults, model, projectDir, restoredWorkspace.sessionName, sessionName]);
  useEffect(() => {
    saveCodeWorkspace({ sessionName, projectDir, model, prompt, actions, attachments, contextItems, approvals, workers, changeCards, evidenceHighlights });
  }, [sessionName, projectDir, model, prompt, actions, attachments, contextItems, approvals, workers, changeCards, evidenceHighlights]);
  useEffect(() => {
    if (!selectedSession && sessionName) setSelectedSession(sessionName);
  }, [selectedSession, sessionName]);
  const addAction = (kind: 'start' | 'send' | 'review', payload: unknown, actionPrompt = prompt) => {
    setActions((current) => [summarizeCodeAction(kind, payload, sessionName, actionPrompt), ...current]);
    setOutputStatus('Updated');
  };
  const copyCodeOutput = async () => {
    if (!actions.length) return;
    try {
      await copyText(actions.map((item) => `${item.createdAt} ${item.title} [${item.status}]\n${item.detail}\n${item.raw}`).join('\n\n'));
      setOutputStatus('Copied');
    } catch {
      setOutputStatus('Copy failed');
    }
  };
  const clearCodeOutput = () => {
    setActions([]);
    setCopiedActionId('');
    setOutputStatus('Cleared');
  };
  const copyCodeAction = async (action: CodeActionRecord) => {
    try {
      await copyText(codeActionPacket(action));
      setCopiedActionId(action.id);
    } catch {
      setCopiedActionId(`failed:${action.id}`);
    }
  };
  const { copyBrief: copyCodeBrief, downloadBrief: downloadCodeBrief } = briefDeliveryActions(codeBrief, 'mde-llm-proxy-code-brief', setOutputStatus, {
    copied: 'Brief copied',
    copyFailed: 'Brief copy failed',
    downloaded: 'Brief downloaded',
  }, hasCodeBrief);
  const startMutation = useMutation({
    mutationFn: () => startCodeSession({ name: sessionName, project_dir: projectDir, model: selectedModel, permission_mode: 'bypassPermissions', run_mode: 'interactive' }),
    onSuccess: (payload) => {
      addAction('start', payload);
      const nextSession = asText((payload as Record<string, unknown>).name, sessionName);
      if (nextSession) {
        setSessionName(nextSession);
        setSelectedSession(nextSession);
        setTmuxAttachActive(true);
      }
      setWorkers((current) => [{
        id: codeNowId('worker'),
        taskId: 'session',
        title: 'Claude Code session',
        sessionName: nextSession || sessionName,
        status: 'attached',
        mirror: 'Session started and ready for prompt bundles.',
        promoted: true,
      }, ...current].slice(0, CODE_WORKER_LIMIT));
      queryClient.invalidateQueries({ queryKey: ['code-payload'] });
      queryClient.invalidateQueries({ queryKey: ['code-tmux-workspace'] });
    }
  });
  type SendCodeVariables = { text: string; actionPrompt: string; clearPrompt?: boolean; workerId?: string; approvalId?: string; previewId?: string };
  const sendMutation = useMutation({
    mutationFn: (values: SendCodeVariables) => sendCodeSession({ name: activeSession || sessionName, text: values.text, enter: true }),
    onSuccess: (payload, values) => {
      addAction('send', payload, values.actionPrompt);
      if (values.clearPrompt) setPrompt('');
      if (values.previewId) setPromptPreview(null);
      if (values.workerId) {
        setWorkers((current) => current.map((worker) => worker.id === values.workerId
          ? { ...worker, status: 'complete', mirror: `${worker.mirror}\n\nDelivered to Claude Code at ${new Date().toLocaleTimeString()}.` }
          : worker
        ));
      }
      if (values.approvalId) {
        setApprovals((current) => current.map((item) => item.id === values.approvalId
          ? { ...item, status: 'complete', result: 'Delivered to Claude Code.' }
          : item
        ));
      }
      queryClient.invalidateQueries({ queryKey: ['code-tmux-workspace'] });
    },
    onError: (error, values) => {
      if (values.workerId) {
        setWorkers((current) => current.map((worker) => worker.id === values.workerId
          ? { ...worker, status: 'failed', mirror: `${worker.mirror}\n\n${errorText(error)}` }
          : worker
        ));
      }
      if (values.approvalId) {
        setApprovals((current) => current.map((item) => item.id === values.approvalId
          ? { ...item, status: 'failed', result: errorText(error) }
          : item
        ));
      }
    }
  });
  const reviewMutation = useMutation({
    mutationFn: () => reviewCodeImages({ session_id: sessionName, model: selectedModel, prompt, attachment_ids: attachments.map((item) => item.id) }),
    onSuccess: (payload) => {
      addAction('review', payload, prompt);
      setPrompt('');
    }
  });
  const canSendCode = Boolean(prompt.trim()) && !sendMutation.isPending;
  const openPromptPreview = () => {
    if (!canSendCode) return;
    setPromptPreview({ id: codeNowId('preview'), prompt, context: visibleContext, submitted: false });
    setOutputStatus('Preview ready');
  };
  const submitPromptPreview = (preview: CodePromptPreview) => {
    const bundle = buildPromptBundle(preview.prompt, preview.context);
    const workerId = codeNowId('worker');
    setPromptPreview({ ...preview, submitted: true });
    setWorkers((current) => [{
      id: workerId,
      taskId: preview.id,
      title: 'Claude Code prompt bundle',
      sessionName: activeSession || sessionName,
      status: 'running',
      mirror: `Submitting prompt bundle through the Claude Code tmux session.\n\n${bundle}`,
      promoted: false,
    }, ...current].slice(0, CODE_WORKER_LIMIT));
    setChangeCards((current) => [...taskChangeCardsForContext(preview.context, preview.id), ...current].slice(0, CODE_CHANGE_CARD_LIMIT));
    setEvidenceHighlights((current) => [{
      id: codeNowId('evidence'),
      label: 'Prompt bundle submitted',
      target: 'terminal' as const,
      detail: activeSession || sessionName,
    }, ...current].slice(0, CODE_CONTEXT_LIMIT));
    setTmuxAttachActive(true);
    sendMutation.mutate({ text: bundle, actionPrompt: preview.prompt, clearPrompt: true, workerId, previewId: preview.id });
  };
  const queuePromptPreview = (preview: CodePromptPreview) => {
    const bundle = buildPromptBundle(preview.prompt, preview.context);
    setApprovals((current) => [...starterApprovalItems(preview.id, bundle), ...current].slice(0, CODE_QUEUE_LIMIT));
    setChangeCards((current) => [...taskChangeCardsForContext(preview.context, preview.id), ...current].slice(0, CODE_CHANGE_CARD_LIMIT));
    setPromptPreview(null);
    setOutputStatus('Queued');
  };
  const handleCodeComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || (!event.ctrlKey && !event.metaKey) || event.nativeEvent.isComposing) return;
    if (!canSendCode) return;
    event.preventDefault();
    openPromptPreview();
  };
  const sendFocusedReply = () => {
    const text = replyText.trim();
    if (!text || sendMutation.isPending) return;
    const workerId = codeNowId('worker');
    setWorkers((current) => [{
      id: workerId,
      taskId: 'reply',
      title: 'Focused reply',
      sessionName: activeSession || sessionName,
      status: 'running',
      mirror: `Reply sent through web controls.\n\n${text}`,
      promoted: false,
    }, ...current].slice(0, CODE_WORKER_LIMIT));
    sendMutation.mutate({ text, actionPrompt: text, clearPrompt: false, workerId });
    setReplyText('');
    setTmuxAttachActive(true);
  };
  const addManualContext = () => {
    const label = contextLabel.trim();
    if (!label) return;
    setContextItems((current) => uniqueCodeContext([{
      id: codeNowId('context'),
      type: contextType,
      label,
      detail: contextDetail.trim(),
      source: contextSource.trim(),
      status: 'staged',
    }, ...current]));
    setContextLabel('');
    setContextDetail('');
    setContextSource('');
  };
  const removeContextItem = (id: string) => {
    setContextItems((current) => current.filter((item) => item.id !== id));
  };
  const updateApproval = (id: string, content: string) => {
    setApprovals((current) => current.map((item) => item.id === id ? { ...item, content } : item));
  };
  const approveQueuedAction = (item: CodeApprovalItem) => {
    const workerId = codeNowId('worker');
    setApprovals((current) => current.map((row) => row.id === item.id ? { ...row, status: 'running' } : row));
    setWorkers((current) => [{
      id: workerId,
      taskId: item.taskId,
      title: item.title,
      sessionName: activeSession || sessionName,
      status: 'running',
      mirror: `Approval queue item executing in worker mirror.\n\n${item.content}`,
      promoted: false,
    }, ...current].slice(0, CODE_WORKER_LIMIT));
    sendMutation.mutate({ text: item.content, actionPrompt: item.content, workerId, approvalId: item.id });
    setTmuxAttachActive(true);
  };
  const rejectQueuedAction = (id: string) => {
    setApprovals((current) => current.filter((item) => item.id !== id));
  };
  const promoteWorker = (id: string) => {
    setWorkers((current) => current.map((worker) => worker.id === id ? { ...worker, promoted: true, status: worker.status === 'running' ? 'promoted' : worker.status } : worker));
    setTmuxAttachActive(true);
    setTerminalController(true);
  };
  const removeAttachment = async (attachment: CodeAttachment) => {
    setAttachmentError('');
    try {
      await deleteCodeAttachment(sessionName, attachment.id);
      setAttachments((current) => current.filter((item) => item.id !== attachment.id));
    } catch (error) {
      setAttachmentError(errorText(error) || 'Unable to remove image attachment.');
    }
  };
  const handleFiles = async (files: FileList | File[]) => {
    setAttachmentError('');
    const rows = Array.from(files).filter((file) => file.type.startsWith('image/'));
    try {
      for (const file of rows) {
        const { payload, previewUrl } = await fileToUploadPayload(file, sessionName);
        const saved = await uploadCodeAttachment(payload);
        setAttachments((current) => [...current, { ...saved.attachment, preview_url: previewUrl }]);
      }
    } catch (error) {
      setAttachmentError(errorText(error) || 'Unable to upload image attachment.');
    }
  };
  const paste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(event.clipboardData.files).filter((file) => file.type.startsWith('image/'));
    if (files.length) void handleFiles(files);
  };
  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    void handleFiles(event.dataTransfer.files);
  };
  const parsedStatus = parsedCodeStatus({
    promptPreview,
    approvals,
    workers,
    latestAction: actions[0],
    pending: startMutation.isPending || sendMutation.isPending || reviewMutation.isPending,
    terminalController,
  });
  return (
    <section className="heroWorkspace codeHero" onDrop={drop} onDragOver={(event) => event.preventDefault()}>
      <div className="heroHeader">
        <div>
          <p className="eyebrow">Terminal-First IDE</p>
          <h1>Code</h1>
          <p>Embedded Claude Code in TMux with prompt bundles, staged context, approvals, worker mirrors, and live repo impact beside the terminal.</p>
        </div>
        <button className="secondaryButton" type="button" onClick={() => fileInput.current?.click()}>
          <CarbonIcon path="actions/document-open-symbolic.svg" label="Attach" />
          Attach Image
        </button>
      </div>
      <input ref={fileInput} type="file" hidden multiple accept="image/png,image/jpeg,image/webp,image/gif" onChange={(event: ChangeEvent<HTMLInputElement>) => event.target.files && void handleFiles(event.target.files)} />
      <div className="codeTerminalSection codeTerminalPrimary" data-testid="code-tui-section">
        <div className="codeTerminalHeader">
          <div>
            <span>Embedded Claude Code TMux</span>
            <strong>{activeSessionRow ? asText(activeSessionRow.display_name || activeSessionRow.name) : activeSession || 'No session selected'}</strong>
            <small>{tmuxAttachActive ? (terminalController ? 'Direct terminal control' : 'Worker mirror attached') : 'Ready to attach'} · {canControlTmux ? 'tmux.control allowed' : 'tmux.control unavailable'}</small>
          </div>
          <div className="codeTerminalActions">
            <select value={activeSession} aria-label="Recent sessions" onChange={(event) => { setSelectedSession(event.target.value); setTmuxAttachActive(false); }}>
              <option value={sessionName}>{sessionName || 'Current session'}</option>
              {tmuxSessions.map((session) => {
                const name = asText(session.name);
                return name && name !== sessionName ? <option key={name} value={name}>{asText(session.display_name || session.name)}</option> : null;
              })}
            </select>
            <button className="secondaryButton" type="button" onClick={() => setTmuxAttachActive(true)} disabled={!activeSession || !canControlTmux}>Attach</button>
            <button className="secondaryButton" type="button" onClick={() => setTerminalController(!terminalController)}>{terminalController ? 'Release Control' : 'Take Terminal Control'}</button>
            <button className="secondaryButton" type="button" aria-expanded={proxyTuiOpen} data-testid="code-tui-toggle" onClick={() => setProxyTuiOpen(true)}>Open Proxy TUI</button>
          </div>
        </div>
        <div className="codeStatusStrip" data-testid="code-status-strip">
          <span>{parsedStatus.state}</span>
          <strong>{parsedStatus.task}</strong>
          <small>{parsedStatus.waitingOn}</small>
          {tmuxWorkspace.error ? <small>{errorText(tmuxWorkspace.error)}</small> : null}
        </div>
        <div className="codeTmuxEmbed" data-testid="code-embedded-tmux">
          <Suspense fallback={<AdvancedLoading label="tmux terminal" />}>
            <TmuxTerminal active={tmuxAttachActive} canControl={canControlTmux} sessionName={activeSession} workspace={tmuxWorkspace.data as TmuxWorkspacePayload | undefined} />
          </Suspense>
        </div>
        <div className="focusedReplyBar" data-testid="code-focused-reply">
          <div>
            <span>Focused Reply</span>
            <strong>{parsedStatus.waitingOn === 'No input needed' ? 'Ready for Claude Code input' : parsedStatus.waitingOn}</strong>
          </div>
          <input value={replyText} onChange={(event) => setReplyText(event.target.value)} onKeyDown={(event) => {
            if (event.key === 'Enter') sendFocusedReply();
          }} placeholder="Reply to the active Claude Code prompt" aria-label="Reply to the active Claude Code prompt" />
          <button className="secondaryButton" type="button" onClick={sendFocusedReply} disabled={!replyText.trim() || sendMutation.isPending}>Send Reply</button>
        </div>
        {proxyTuiOpen ? (
          <Suspense fallback={<AdvancedLoading label="terminal" />}>
            <TuiTerminal clientId={terminalClient} controller={terminalController && canControlTui} />
          </Suspense>
        ) : null}
      </div>
      <div className="workspaceGrid codeIdeGrid">
        <div className="composerPanel">
          {code.isLoading ? <StatusPanel tone="loading" title="Loading code workspace" /> : null}
          {code.error ? <StatusPanel tone="error" title="Code API unavailable" detail={errorText(code.error)} /> : null}
          {capabilities.error ? <StatusPanel tone="error" title="Capability check failed" detail={errorText(capabilities.error)} /> : null}
          {attachmentError ? <StatusPanel tone="error" title="Image upload failed" detail={attachmentError} /> : null}
          {startMutation.error ? <StatusPanel tone="error" title="Session start failed" detail={errorText(startMutation.error)} /> : null}
          {sendMutation.error ? <StatusPanel tone="error" title="Tmux send failed" detail={errorText(sendMutation.error)} /> : null}
          {reviewMutation.error ? <StatusPanel tone="error" title="Image review failed" detail={errorText(reviewMutation.error)} /> : null}
          <div className="inlineFields">
            <label className="field"><span>Session</span><input value={sessionName} onChange={(event) => setSessionName(event.target.value)} /></label>
            <label className="field"><span>Project</span><input value={projectDir} onChange={(event) => setProjectDir(event.target.value)} /></label>
          </div>
          <ModelSelect models={models} value={selectedModel} onChange={setModel} />
          <textarea className="xlInput" value={prompt} onPaste={paste} onKeyDown={handleCodeComposerKeyDown} onChange={(event) => setPrompt(event.target.value)} placeholder="Describe the coding task or ask the model to review the attached screenshot." />
          <div className="contextComposer" data-testid="code-context-composer">
            <select value={contextType} onChange={(event) => setContextType(normalizeContextType(event.target.value))} aria-label="Context type">
              <option value="file">File</option>
              <option value="diff">Diff</option>
              <option value="terminal">Terminal</option>
            </select>
            <input value={contextLabel} onChange={(event) => setContextLabel(event.target.value)} placeholder="Path, diff, or terminal label" />
            <input value={contextDetail} onChange={(event) => setContextDetail(event.target.value)} placeholder="Reason or line range" />
            <input value={contextSource} onChange={(event) => setContextSource(event.target.value)} placeholder="Source" />
            <button className="secondaryButton" type="button" onClick={addManualContext} disabled={!contextLabel.trim()}>Add Context</button>
          </div>
          <div className="contextTray" data-testid="code-context-tray">
            <div className="contextTrayHeader">
              <span>Context Tray</span>
              <strong>{visibleContext.length} item{visibleContext.length === 1 ? '' : 's'} staged</strong>
            </div>
            {visibleContext.length ? visibleContext.map((item) => (
              <article className="contextPill" key={item.id}>
                <span>{contextTypeLabel(item.type)}</span>
                <strong>{item.label}</strong>
                <small>{[item.detail, item.source].filter(Boolean).join(' · ') || item.status}</small>
                {!item.id.startsWith('attachment:') ? (
                  <button type="button" onClick={() => removeContextItem(item.id)} aria-label={`Remove ${item.label}`}>
                    <CarbonIcon path="actions/window-close-symbolic.svg" label="Remove" />
                  </button>
                ) : null}
              </article>
            )) : <div className="attachmentDropHint">No staged context.</div>}
          </div>
          {attachments.length ? (
            <div className="attachmentTray" aria-label="Code image attachments">
              <div className="attachmentTrayHeader">
                <span>{attachments.length} image{attachments.length === 1 ? '' : 's'} ready</span>
                <strong>Review before sending</strong>
              </div>
              {attachments.map((attachment) => (
                <article className="attachmentCard" key={attachment.id}>
                  {attachment.preview_url ? <img src={attachment.preview_url} alt="" /> : <div className="attachmentPreviewFallback">Image</div>}
                  <div>
                    <strong>{attachment.filename}</strong>
                    <span>{Math.round(attachment.size_bytes / 1024)} KB · {attachment.width || '?'} x {attachment.height || '?'} · {attachment.mime_type}</span>
                    <small>{attachment.sha256.slice(0, 12)}</small>
                  </div>
                  <button className="secondaryButton" type="button" onClick={() => void removeAttachment(attachment)}>Remove</button>
                </article>
              ))}
            </div>
          ) : <div className="attachmentDropHint">Paste, drop, or attach screenshots for model review.</div>}
          {promptPreview ? (
            <div className="promptBundlePreview" data-testid="code-prompt-preview">
              <div className="promptBundleHeader">
                <div>
                  <span>Prompt Bundle Preview</span>
                  <strong>{promptPreview.context.length} context item{promptPreview.context.length === 1 ? '' : 's'}</strong>
                </div>
                <button className="secondaryButton" type="button" onClick={() => setPromptPreview(null)}>Close</button>
              </div>
              <pre>{buildPromptBundle(promptPreview.prompt, promptPreview.context)}</pre>
              <div className="buttonRow">
                <button className="primaryButton" type="button" onClick={() => submitPromptPreview(promptPreview)} disabled={sendMutation.isPending}>Send Bundle</button>
                <button className="secondaryButton" type="button" onClick={() => queuePromptPreview(promptPreview)}>Queue For Approval</button>
              </div>
            </div>
          ) : null}
          <div className="buttonRow">
            <button className="secondaryButton" type="button" onClick={() => startMutation.mutate()} disabled={startMutation.isPending}>Start Session</button>
            <button className="secondaryButton" type="button" onClick={openPromptPreview} disabled={!canSendCode}>Send To Tmux</button>
            <button className="primaryButton" type="button" onClick={() => reviewMutation.mutate()} disabled={!attachments.length || reviewMutation.isPending}>Ask Model To Review Image</button>
          </div>
        </div>
        <div className="codeSupportPane">
          <div className="codeChangePanel" data-testid="code-change-cards">
            <div className="codePanelHeader">
              <div>
                <span>Staged Context Changes</span>
                <strong>{changeCards.length} change card{changeCards.length === 1 ? '' : 's'}</strong>
              </div>
              <small>Grouped by task</small>
            </div>
            {changeCards.length ? changeCards.map((card) => (
              <article className={`changeCard ${card.conflict ? 'conflict' : ''}`} key={card.id}>
                <span>{card.taskId}</span>
                <strong>{card.file}</strong>
                <p>{card.summary}</p>
                <small>{card.kind} · {card.lines} · {card.status}{card.conflict ? ' · conflict' : ''}</small>
              </article>
            )) : <div className="emptyState">Changed files and selected diffs will appear as task cards.</div>}
          </div>
          <div className="approvalQueue" data-testid="code-approval-queue">
            <div className="codePanelHeader">
              <div>
                <span>Approval Queue</span>
                <strong>{approvals.length} item{approvals.length === 1 ? '' : 's'}</strong>
              </div>
              <small>Commands, edits, tests</small>
            </div>
            {approvals.length ? approvals.map((item) => (
              <article className="approvalItem" key={item.id}>
                <div className="approvalItemHeader">
                  <div>
                    <span>{item.kind} · {item.risk}</span>
                    <strong>{item.title}</strong>
                    <small>{item.status}{item.result ? ` · ${item.result}` : ''}</small>
                  </div>
                  <button className="secondaryButton" type="button" onClick={() => rejectQueuedAction(item.id)}>Reject</button>
                </div>
                <textarea value={item.content} onChange={(event) => updateApproval(item.id, event.target.value)} />
                <button className="secondaryButton" type="button" onClick={() => approveQueuedAction(item)} disabled={sendMutation.isPending || item.status === 'running'}>{item.status === 'running' ? 'Running' : 'Approve'}</button>
              </article>
            )) : <div className="emptyState">Queued actions will collect here before execution.</div>}
          </div>
          <div className="workerMirrorPanel" data-testid="code-worker-mirrors">
            <div className="codePanelHeader">
              <div>
                <span>Worker Mirrors</span>
                <strong>{workers.length} worker{workers.length === 1 ? '' : 's'}</strong>
              </div>
              <small>Main + workers</small>
            </div>
            {workers.length ? workers.map((worker) => (
              <article className="workerMirror" key={worker.id}>
                <div className="workerMirrorHeader">
                  <div>
                    <span>{worker.status}</span>
                    <strong>{worker.title}</strong>
                    <small>{worker.sessionName || activeSession}</small>
                  </div>
                  <button className="secondaryButton" type="button" onClick={() => promoteWorker(worker.id)}>{worker.promoted ? 'Promoted' : 'Promote'}</button>
                </div>
                <pre>{worker.mirror}</pre>
              </article>
            )) : <div className="emptyState">Background worker output will mirror here.</div>}
          </div>
          <div className="evidenceDock" data-testid="code-evidence-dock">
            <div className="codePanelHeader">
              <div>
                <span>Evidence</span>
                <strong>{evidenceHighlights.length} highlight{evidenceHighlights.length === 1 ? '' : 's'}</strong>
              </div>
              <button className="secondaryButton" type="button" onClick={() => setEvidenceHighlights([])} disabled={!evidenceHighlights.length}>Clear All</button>
            </div>
            {evidenceHighlights.length ? evidenceHighlights.map((item) => (
              <article className="evidenceItem" key={item.id}>
                <button type="button" aria-label={`Remove ${item.label}`} onClick={() => setEvidenceHighlights((current) => current.filter((row) => row.id !== item.id))}>
                  <CarbonIcon path="actions/window-close-symbolic.svg" label="Remove" />
                </button>
                <span>{item.target}</span>
                <strong>{item.label}</strong>
                <small>{item.detail}</small>
              </article>
            )) : <div className="emptyState">Pinned evidence appears here until dismissed.</div>}
          </div>
        </div>
        <div className="codeOutputConsole" aria-label="Code command output">
          <div className="codeOutputHeader">
            <div>
              <span>{actions.length} event{actions.length === 1 ? '' : 's'}</span>
              <strong>{actions[0]?.title || 'No code output yet'}</strong>
              <small>{outputStatus}</small>
            </div>
            <div className="codeOutputActions">
              <button className="secondaryButton" type="button" disabled={!actions.length} onClick={() => void copyCodeOutput()}>Copy</button>
              <button className="secondaryButton" type="button" disabled={!hasCodeBrief} onClick={() => void copyCodeBrief()}>Copy Brief</button>
              <button className="secondaryButton" type="button" disabled={!hasCodeBrief} onClick={downloadCodeBrief}>Download Brief</button>
              <button className="secondaryButton" type="button" disabled={!actions.length} onClick={clearCodeOutput}>Clear</button>
            </div>
          </div>
          {(startMutation.isPending || sendMutation.isPending || reviewMutation.isPending) ? <StatusPanel tone="loading" title="Code action running" detail={sessionName} /> : null}
          {actions.length ? actions.map((action) => (
            <article className="codeOutputCard" key={action.id}>
              <div className="codeOutputCardHeader">
                <div>
                  <span>{action.createdAt}</span>
                  <strong>{action.title}</strong>
                  <small>{action.status}</small>
                </div>
                <button className="secondaryButton" type="button" onClick={() => void copyCodeAction(action)} aria-label={`Copy Event ${action.title}`}>
                  {copiedActionId === `failed:${action.id}` ? 'Copy Failed' : copiedActionId === action.id ? 'Copied' : 'Copy Event'}
                </button>
              </div>
              <p>{action.detail}</p>
              <details>
                <summary>Raw payload</summary>
                <pre>{action.raw}</pre>
              </details>
            </article>
          )) : <div className="emptyState">Session output and image review responses will appear here.</div>}
        </div>
      </div>
    </section>
  );
}

export function ResearchPage() {
  const payload = useQuery({ queryKey: ['research-payload'], queryFn: getResearchPayload });
  const restoredWorkspace = useMemo(loadResearchWorkspace, []);
  const [query, setQuery] = useState(restoredWorkspace.query);
  const [mode, setMode] = useState(restoredWorkspace.mode);
  const [engineSelectionMode, setEngineSelectionMode] = useState<ResearchEngineSelectionMode>(restoredWorkspace.engineSelectionMode);
  const [selectedEngines, setSelectedEngines] = useState<string[]>(restoredWorkspace.selectedEngines);
  const [activeTab, setActiveTab] = useState<ResearchTab>(restoredWorkspace.activeTab);
  const [researchDossier, setResearchDossier] = useState<ResearchDossier | null>(restoredWorkspace.dossier);
  const [printPacket, setPrintPacket] = useState<ResearchReportPacket | null>(researchDossier?.report_packet || null);
  const engines = payload.data?.engines || [];
  const sourceClasses = payload.data?.source_classes || [];
  const engineIds = useMemo(() => engines.map((engine) => engine.id).filter(Boolean), [engines]);
  const requiredSourceIds = useMemo(() => {
    const allowed = new Set(engineIds);
    return sourceClasses
      .map((source) => source.engine_id || source.id)
      .filter((engineId) => allowed.has(engineId))
      .slice(0, RESEARCH_SELECTED_ENGINE_LIMIT);
  }, [engineIds, sourceClasses]);
  const activeEngineIds = useMemo(() => {
    if (engineSelectionMode === 'all') return engineIds;
    const allowed = new Set(engineIds);
    return selectedEngines.filter((engineId) => allowed.has(engineId));
  }, [engineIds, engineSelectionMode, selectedEngines]);
  const customSelectionEmpty = engineSelectionMode === 'custom' && activeEngineIds.length === 0;
  const requiredSourceSetSelected = engineSelectionMode === 'custom'
    && requiredSourceIds.length > 0
    && activeEngineIds.length === requiredSourceIds.length
    && requiredSourceIds.every((engineId) => activeEngineIds.includes(engineId));
  const selectionSummary = engineSelectionMode === 'all'
    ? 'All engines selected'
    : requiredSourceSetSelected
      ? `${requiredSourceIds.length} required sources selected`
      : `${activeEngineIds.length} selected`;
  const selectRequiredSources = () => {
    setEngineSelectionMode('custom');
    setSelectedEngines(requiredSourceIds);
  };
  const toggleEngine = (engineId: string) => {
    if (engineSelectionMode === 'all') {
      setEngineSelectionMode('custom');
      setSelectedEngines(engineIds.filter((id) => id !== engineId).slice(0, RESEARCH_SELECTED_ENGINE_LIMIT));
      return;
    }
    const next = selectedEngines.includes(engineId)
      ? selectedEngines.filter((id) => id !== engineId)
      : [...selectedEngines, engineId].filter((id) => engineIds.includes(id)).slice(0, RESEARCH_SELECTED_ENGINE_LIMIT);
    if (next.length === engineIds.length && engineIds.length > 0) {
      setEngineSelectionMode('all');
      setSelectedEngines([]);
      return;
    }
    setSelectedEngines(next);
  };
  const searchMutation = useMutation({
    mutationFn: () => runResearchSearch({ query, mode, ...(engineSelectionMode === 'custom' ? { engines: activeEngineIds } : {}) }),
    onSuccess: (result) => {
      setResearchDossier(result);
      setPrintPacket(result.report_packet);
      setActiveTab('results');
    },
  });
  const pinMutation = useMutation({
    mutationFn: (evidenceIds: string[]) => {
      if (!researchDossier) throw new Error('No research dossier is active.');
      return updateResearchPins(researchDossier.dossier_id, evidenceIds);
    },
    onSuccess: (result) => {
      setResearchDossier(result);
      setPrintPacket(result.report_packet);
    },
  });
  const canRunResearchSearch = Boolean(query.trim()) && !searchMutation.isPending && !customSelectionEmpty;
  const submitResearchSearch = () => {
    if (!canRunResearchSearch) return;
    searchMutation.mutate();
  };
  const handleResearchSearchKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Enter' || event.nativeEvent.isComposing || !canRunResearchSearch) return;
    event.preventDefault();
    searchMutation.mutate();
  };
  const pinnedIds = researchDossier?.pinned_evidence_ids || [];
  const toggleEvidencePin = (evidenceId: string) => {
    if (!researchDossier || pinMutation.isPending) return;
    const next = pinnedIds.includes(evidenceId) ? pinnedIds.filter((id) => id !== evidenceId) : [...pinnedIds, evidenceId];
    pinMutation.mutate(next);
  };
  const printResearchReport = async () => {
    if (!researchDossier) return;
    try {
      const report = await getResearchReport(researchDossier.dossier_id);
      setPrintPacket(report);
    } catch {
      setPrintPacket(researchDossier.report_packet);
    }
    window.setTimeout(() => window.print(), 0);
  };
  const visibleSourceClasses = sourceClasses.length ? sourceClasses : researchDossier?.source_catalog?.source_classes || [];
  useEffect(() => {
    saveResearchWorkspace({ query, mode, engineSelectionMode, selectedEngines: engineSelectionMode === 'custom' ? activeEngineIds : [], activeTab, dossier: researchDossier });
  }, [query, mode, engineSelectionMode, activeEngineIds, activeTab, researchDossier]);
  return (
    <section className="heroWorkspace researchHero lexisResearchHero">
      <div className="heroHeader">
        <div>
          <p className="eyebrow">Technical Research Dossier</p>
          <h1>Research</h1>
          <p>Professional technical research with source controls, evidence tables, claim mapping, and a full printable packet.</p>
        </div>
        <ResearchReportActions dossier={researchDossier} onPrint={() => void printResearchReport()} className="researchBriefDock" />
      </div>
      <div className="researchTabs" role="tablist" aria-label="Research workspace tabs">
        {([
          ['search', 'Advanced Search'],
          ['results', 'Results'],
          ['brief', 'Synthesis Brief'],
          ['sources', 'Source Registry'],
        ] as Array<[ResearchTab, string]>).map(([tab, label]) => (
          <button key={tab} role="tab" type="button" aria-selected={activeTab === tab} className={activeTab === tab ? 'active' : ''} disabled={tab !== 'search' && tab !== 'sources' && !researchDossier} onClick={() => setActiveTab(tab)}>
            {label}
          </button>
        ))}
      </div>
      {payload.isLoading ? <StatusPanel tone="loading" title="Loading research engines" /> : null}
      {payload.error ? <StatusPanel tone="error" title="Research setup unavailable" detail={errorText(payload.error)} /> : null}
      {searchMutation.error ? <StatusPanel tone="error" title="Research search failed" detail={errorText(searchMutation.error)} /> : null}
      {pinMutation.error ? <StatusPanel tone="error" title="Research pin update failed" detail={errorText(pinMutation.error)} /> : null}
      {customSelectionEmpty ? <StatusPanel tone="neutral" title="Select at least one research engine" detail="Use Select All or turn on one source before searching." /> : null}

      {activeTab === 'search' ? (
        <div className="researchTabPanel lexisSearchPanel" role="tabpanel">
          <div className="searchLine lexisSearchLine">
            <input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={handleResearchSearchKeyDown} placeholder="Search technical documentation, examples, papers, web, and local RAG" aria-label="Research search query" />
            <select value={mode} onChange={(event) => setMode(event.target.value)}>{(payload.data?.modes || ['Balanced']).map((item) => <option key={item}>{item}</option>)}</select>
            <button className="primaryButton" type="button" onClick={submitResearchSearch} disabled={!canRunResearchSearch}>{searchMutation.isPending ? 'Searching' : 'Search'}</button>
          </div>
          {searchMutation.isPending ? (
            <div className="researchSearchStatus" role="status">
              <strong>Searching configured sources</strong>
              <span>{query}</span>
              <div className="resultSkeleton"><span /><span /><span /></div>
            </div>
          ) : null}
          <div className="engineControls" aria-label="Research engine selection controls">
            <span>{selectionSummary}</span>
            <button className="secondaryButton" type="button" aria-pressed={engineSelectionMode === 'all'} onClick={() => { setEngineSelectionMode('all'); setSelectedEngines([]); }}>Select All</button>
            <button className="secondaryButton" type="button" aria-pressed={requiredSourceSetSelected} onClick={selectRequiredSources} disabled={!requiredSourceIds.length}>Required Sources</button>
            <button className="secondaryButton" type="button" onClick={() => { setEngineSelectionMode('custom'); setSelectedEngines([]); }} disabled={!engineIds.length}>Clear</button>
          </div>
          <div className="engineStrip">
            {engines.map((engine) => {
              const checked = engineSelectionMode === 'all' || activeEngineIds.includes(engine.id);
              return <button aria-pressed={checked} className={`engineChip ${checked ? 'active' : ''} status-${engine.status}`} key={engine.id} type="button" title={engine.detail || engine.status} onClick={() => toggleEngine(engine.id)}>{engine.name}<span>{readableStatus(engine.status)}</span></button>;
            })}
          </div>
          {visibleSourceClasses.length ? (
            <div className="sourceClassStrip" aria-label="Research source classes">
              {visibleSourceClasses.map((source) => (
                <span className={`sourceClassChip kind-${source.kind.replace(/[^a-z0-9_-]/gi, '-')}`} key={source.id} title={source.detail || source.name}>
                  <strong>{source.label || source.name}</strong>
                  <small>{readableStatus(source.status)} · {readableStatus(source.kind)}</small>
                </span>
              ))}
            </div>
          ) : null}
          {!payload.isLoading && !payload.error && !engines.length ? <StatusPanel title="No research engines reported" detail="Configure external search credentials or local RAG to populate search sources." /> : null}
          {!researchDossier && !searchMutation.isPending ? <div className="emptyState">Enter a technical query and choose sources to create a research dossier.</div> : null}
        </div>
      ) : null}
      {activeTab === 'results' ? (
        <div className="researchTabPanel" role="tabpanel">
          {researchDossier ? <ResearchResultsTab data={researchDossier} pinnedIds={pinnedIds} onTogglePin={toggleEvidencePin} pinPending={pinMutation.isPending} /> : <div className="emptyState">Run a search to populate Results.</div>}
        </div>
      ) : null}
      {activeTab === 'brief' ? (
        <div className="researchTabPanel" role="tabpanel">
          {researchDossier ? <ResearchBriefTab data={researchDossier} /> : <div className="emptyState">Run a search to create a synthesis brief.</div>}
        </div>
      ) : null}
      {activeTab === 'sources' ? (
        <div className="researchTabPanel" role="tabpanel">
          <ResearchSourceRegistryTab payload={payload.data} dossier={researchDossier} activeEngineIds={activeEngineIds} onToggleEngine={toggleEngine} />
        </div>
      ) : null}
      <ResearchPrintPacket dossier={researchDossier} packet={printPacket} />
    </section>
  );
}

export function CreatePage() {
  const create = useQuery({ queryKey: ['create-payload'], queryFn: getCreatePayload });
  const mood = useCreateMood();
  const restoredWorkspace = useMemo(loadCreateWorkspace, []);
  const [model, setModel] = useState(restoredWorkspace.model);
  const [prompt, setPrompt] = useState(restoredWorkspace.prompt);
  const [imageResult, setImageResult] = useState<{ images: CreateImageResult[]; raw: string } | null>(restoredWorkspace.imageResult);
  const [historyItems, setHistoryItems] = useState<CreateHistoryItem[]>(restoredWorkspace.historyItems);
  const [historyStatus, setHistoryStatus] = useState(restoredWorkspace.historyItems.length ? 'Restored' : 'Ready');
  const imageModels = useMemo(
    () => (create.data?.image_models || []).filter((card) => card.route_enabled),
    [create.data?.image_models],
  );
  const selectedImageModel = model || imageModels[0]?.id || '';
  const hasCreateBrief = hasCreateBriefState({ prompt, model, imageResult, historyItems });
  const createBrief = useMemo(() => createBriefMarkdown({ prompt, model: selectedImageModel, imageResult, historyItems }), [prompt, selectedImageModel, imageResult, historyItems]);
  const [briefStatus, setBriefStatus] = useState(hasCreateBriefState(restoredWorkspace) ? 'Brief Ready' : 'No brief');
  const addHistory = (item: Omit<CreateHistoryItem, 'id' | 'createdAt'>) => {
    const now = new Date();
    setHistoryItems((current) => [{
      ...item,
      id: `${now.getTime()}-image`,
      createdAt: now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }),
    }, ...current].slice(0, 6));
    setHistoryStatus('Updated');
  };
  const reuseHistory = (item: CreateHistoryItem) => {
    setPrompt(item.prompt);
    setImageResult(item.imageResult || null);
    setHistoryStatus('Reused');
  };
  const copyHistory = async (item: CreateHistoryItem) => {
    try {
      await copyText(createHistoryPacket(item));
      setHistoryStatus('Packet copied');
    } catch {
      setHistoryStatus('Copy failed');
    }
  };
  const { copyBrief: copyCreateBrief, downloadBrief: downloadCreateBrief } = briefDeliveryActions(createBrief, 'mde-llm-proxy-create-brief', setBriefStatus, {
    copied: 'Brief copied',
    copyFailed: 'Brief copy failed',
    downloaded: 'Brief downloaded',
  }, hasCreateBrief);
  const imageMutation = useMutation({
    mutationFn: () => runCreateImages({ prompt, ...(selectedImageModel ? { model: selectedImageModel } : {}) }),
    onSuccess: (payload) => {
      const normalized = normalizeImageResults(payload);
      setImageResult(normalized);
      addHistory({ prompt, summary: `${normalized.images.length} image output${normalized.images.length === 1 ? '' : 's'}${normalized.images[0]?.model ? ` · ${normalized.images[0].model}` : ''}`, thumbnail: normalized.images[0]?.src, imageResult: normalized });
    }
  });
  const pending = imageMutation.isPending;
  const canSubmit = Boolean(prompt.trim()) && !pending;
  const submit = () => {
    if (!canSubmit) return;
    imageMutation.mutate();
  };
  const handleCreateComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || (!event.ctrlKey && !event.metaKey) || !canSubmit) return;
    event.preventDefault();
    submit();
  };
  useEffect(() => {
    saveCreateWorkspace({ prompt, model, imageResult, historyItems });
  }, [prompt, model, imageResult, historyItems]);
  useEffect(() => {
    setBriefStatus(hasCreateBrief ? 'Brief Ready' : 'No brief');
  }, [createBrief, hasCreateBrief]);
  const wallpaper = String(create.data?.wallpaper?.remote_url || create.data?.wallpaper?.url || '');
  return (
    <section className="heroWorkspace createHero" style={{ backgroundImage: wallpaper ? `linear-gradient(180deg, rgba(0,0,0,.34), rgba(0,0,0,.72)), url(${wallpaper})` : undefined }}>
      <div className="createAtmosphere" aria-hidden="true"><span /><span /><span /></div>
      <div className="createCenter">
        <p className="eyebrow">Image Creation Studio</p>
        <h1>Create</h1>
        <div id="v2-create-mood" className="createMood" aria-label="Create mood">
          <span>{mood.label}</span>
          <strong>{mood.time}</strong>
          <span>{mood.weather}</span>
          <span>{mood.tone}</span>
        </div>
        {create.isLoading ? <StatusPanel tone="loading" title="Loading image studio" /> : null}
        {create.error ? <StatusPanel tone="error" title="Create setup unavailable" detail={errorText(create.error)} /> : null}
        {pending ? <StatusPanel tone="loading" title="Image generation running" detail={prompt} /> : null}
        {imageMutation.error ? <StatusPanel tone="error" title="Image request failed" detail={errorText(imageMutation.error)} /> : null}
        {!create.isLoading && !create.error && !imageModels.length ? <StatusPanel title="No image models available" detail="Enable an image model in the registry to generate images." /> : null}
        {imageModels.length ? (
          <div className="createModelDock" aria-label="Image model selection">
            <span>{imageModels.length} image model{imageModels.length === 1 ? '' : 's'}</span>
            <ModelSelect models={imageModels} value={selectedImageModel} onChange={setModel} label="Image Model" />
          </div>
        ) : null}
        <div className="createPrompt">
          <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={handleCreateComposerKeyDown} placeholder="Describe the image to create" />
          <button className="primaryButton" type="button" onClick={submit} disabled={!canSubmit}>Generate</button>
        </div>
        <div className="createBriefDock" aria-label="Create brief actions">
          <span>{briefStatus}</span>
          <button className="secondaryButton" type="button" disabled={!hasCreateBrief} onClick={() => void copyCreateBrief()}>Copy Brief</button>
          <button className="secondaryButton" type="button" disabled={!hasCreateBrief} onClick={downloadCreateBrief}>Download Brief</button>
        </div>
        {historyItems.length ? (
          <div className="createHistory" aria-label="Create session history">
            <div className="createHistoryHeader">
              <span>{historyItems.length} recent output{historyItems.length === 1 ? '' : 's'}</span>
              <strong>{historyStatus}</strong>
            </div>
            <div className="createHistoryGrid">
              {historyItems.map((item) => <CreateHistoryCard key={item.id} item={item} onReuse={reuseHistory} onCopy={(row) => void copyHistory(row)} />)}
            </div>
          </div>
        ) : null}
        {imageResult ? (
          <div className="createResult imageGalleryResult">
            <div className="imageGalleryHeader">
              <span>Image result</span>
              <strong>{imageResult.images.length} output{imageResult.images.length === 1 ? '' : 's'}</strong>
            </div>
            {imageResult.images.length ? (
              <div className="createImageGrid" aria-label="Generated image results">
                {imageResult.images.map((image, index) => (
                  <article className="createImageCard" key={`${image.id}-${index}`}>
                    <img src={image.src} alt={image.prompt || `Generated image ${index + 1}`} />
                    <div>
                      <strong>{image.prompt || 'Generated image'}</strong>
                      <span>{[image.model, image.size, image.cost].filter(Boolean).join(' · ') || 'Image output'}</span>
                      <div className="imageCardActions">
                        <a href={image.src} target="_blank" rel="noreferrer">Open</a>
                        <a href={image.src} download={image.filename || `${image.id}.png`}>Download</a>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            ) : <StatusPanel title="No image previews found" detail="The image provider returned a payload without a URL, filename, or base64 image body." />}
            <details className="rawPayload">
              <summary>Raw payload</summary>
              <pre>{imageResult.raw}</pre>
            </details>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function openModelInChat(model: ModelCard): void {
  try {
    const parsed = JSON.parse(window.sessionStorage.getItem(CHAT_UI_STATE_SESSION_KEY) || '{}');
    const row = parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : {};
    window.sessionStorage.setItem(CHAT_UI_STATE_SESSION_KEY, JSON.stringify({ ...row, selectedModel: model.id }));
  } catch {
    // Chat still opens; the model can be selected manually.
  }
  window.location.hash = '#chat';
}

export function ModelsPage() {
  const queryClient = useQueryClient();
  const models = useQuery({ queryKey: ['models'], queryFn: getModels });
  const whatsNew = useQuery({ queryKey: ['whats-new'], queryFn: getWhatsNew });
  const { favorites } = useModelFavorites();
  const [gridExpanded, setGridExpanded] = useState(false);
  const restoredShowcase = useMemo(loadModelsShowcaseState, []);
  const [filter, setFilter] = useState(restoredShowcase.filter);
  const [statusFilter, setStatusFilter] = useState(restoredShowcase.statusFilter);
  const [sortMode, setSortMode] = useState(restoredShowcase.sortMode);
  const [showWhatsNew, setShowWhatsNew] = useState(false);
  const [inspectedModelId, setInspectedModelId] = useState(restoredShowcase.inspectedModelId);
  const [compareIds, setCompareIds] = useState<string[]>(restoredShowcase.compareIds);
  const discover = useMutation({ mutationFn: discoverModels, onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['models'] }); queryClient.invalidateQueries({ queryKey: ['whats-new'] }); } });
  const allCards = models.data?.models || [];
  const attentionCount = allCards.filter((model) => !model.route_enabled || ['not_checked', 'forbidden', 'rate_limited', 'probe_failed', 'removed'].includes(model.access_status)).length;
  const cards = allCards
    .filter((model) => {
      const text = [model.display_name, model.company, model.family, model.training_nation, model.type, model.access_status].join(' ').toLowerCase();
      if (!text.includes(filter.toLowerCase())) return false;
      if (statusFilter === 'routable') return model.route_enabled;
      if (statusFilter === 'new') return model.is_new;
      if (statusFilter === 'attention') return !model.route_enabled || ['not_checked', 'forbidden', 'rate_limited', 'probe_failed', 'removed'].includes(model.access_status);
      if (statusFilter === 'text') return model.type === 'text';
      if (statusFilter === 'image') return model.type === 'image';
      return true;
    })
    .sort((left, right) => {
      if (sortMode === 'nation') return `${left.training_nation}${left.display_name}`.localeCompare(`${right.training_nation}${right.display_name}`);
      if (sortMode === 'company') return `${left.company}${left.display_name}`.localeCompare(`${right.company}${right.display_name}`);
      if (sortMode === 'name') return left.display_name.localeCompare(right.display_name);
      return Number(right.route_enabled) - Number(left.route_enabled) || Number(right.is_new) - Number(left.is_new) || left.display_name.localeCompare(right.display_name);
    });
  const inspectedModel = allCards.find((model) => model.id === inspectedModelId) || cards.find((model) => model.route_enabled) || cards[0];
  const compareModels = compareIds.map((id) => allCards.find((model) => model.id === id)).filter((model): model is ModelCard => Boolean(model));
  const toggleCompare = (id: string) => {
    setCompareIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id].slice(0, MODEL_COMPARE_LIMIT));
  };
  useEffect(() => {
    saveModelsShowcaseState({ filter, statusFilter, sortMode, inspectedModelId, compareIds });
  }, [filter, statusFilter, sortMode, inspectedModelId, compareIds]);
  const metrics = [
    { label: 'Total', value: numeric(models.data?.summary?.total) || allCards.length },
    { label: 'Routable', value: numeric(models.data?.summary?.route_enabled) || allCards.filter((model) => model.route_enabled).length },
    { label: 'New', value: numeric(models.data?.summary?.new) || allCards.filter((model) => model.is_new).length },
    { label: 'Attention', value: attentionCount },
  ];
  return (
    <section className="heroWorkspace modelsHero">
      {showWhatsNew && whatsNew.data ? <WhatsNewModal data={whatsNew.data} onClose={() => setShowWhatsNew(false)} /> : null}
      <div className="heroHeader">
        <div>
          <p className="eyebrow">LLM Showcase</p>
          <h1>Models</h1>
          <p>Every LLM gets country-of-training color, company artwork, pricing, access state, and route status.</p>
        </div>
        <div className="heroActions">
          <button className="secondaryButton" type="button" onClick={() => setShowWhatsNew(true)} disabled={!whatsNew.data}>Whats New</button>
          <button className="primaryButton" type="button" onClick={() => discover.mutate()} disabled={discover.isPending}>Discover Models</button>
        </div>
      </div>
      {models.isLoading ? <StatusPanel tone="loading" title="Loading model showcase" /> : null}
      {models.error ? <StatusPanel tone="error" title="Model registry unavailable" detail={errorText(models.error)} /> : null}
      {whatsNew.error ? <StatusPanel tone="error" title="Whats New unavailable" detail={errorText(whatsNew.error)} /> : null}
      {discover.isPending ? <StatusPanel tone="loading" title="Discovering DigitalOcean models" detail="Live access checks decide which newly discovered text LLMs become routable." /> : null}
      {discover.error ? <StatusPanel tone="error" title="Model discovery failed" detail={errorText(discover.error)} /> : null}
      <div className="modelCommandBoard">
        <div className="modelMetrics" aria-label="Model summary">
          {metrics.map((metric) => <div className="modelMetric" key={metric.label}><span>{metric.label}</span><strong>{metric.value.toLocaleString()}</strong></div>)}
        </div>
        <div className="modelControls">
          <div className="searchLine compact"><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter models by company, nation, family, status, or type" /></div>
          <div className="modeSwitch" aria-label="Model status filter">
            {[
              ['all', 'All'],
              ['routable', 'Routable'],
              ['new', 'New'],
              ['attention', 'Attention'],
              ['text', 'Text'],
              ['image', 'Image'],
            ].map(([value, label]) => <button className={statusFilter === value ? 'active' : ''} key={value} type="button" onClick={() => setStatusFilter(value)}>{label}</button>)}
          </div>
          <label className="field modelSort"><span>Sort</span><select value={sortMode} onChange={(event) => setSortMode(event.target.value)}><option value="route">Route readiness</option><option value="nation">Nation</option><option value="company">Company</option><option value="name">Name</option></select></label>
        </div>
      </div>
      {inspectedModel ? <ModelInspector model={inspectedModel} /> : null}
      <ModelCompareTray models={compareModels} onRemove={(id) => setCompareIds((current) => current.filter((item) => item !== id))} onClear={() => setCompareIds([])} />
      {!models.isLoading && !models.error && !cards.length ? <StatusPanel title="No models match this filter" detail={filter ? `No model matched "${filter}".` : 'The registry did not return any model cards.'} /> : null}
      {(() => {
        const favoriteSet = new Set(favorites);
        const favoriteCards = cards.filter((model) => favoriteSet.has(model.id));
        // Favorites lead; without any (or while filtering) the full grid shows (V2-082 Q10).
        const collapsedGrid = favoriteCards.length > 0 && !gridExpanded && !filter.trim();
        const visibleCards = collapsedGrid ? favoriteCards : cards;
        const hiddenCount = cards.length - visibleCards.length;
        return (
          <>
            <div className="modelGrid">
              {visibleCards.map((model) => (
                <ModelIdentityCard
                  key={model.id}
                  model={model}
                  size="big"
                  onOpenDetail={(target) => setInspectedModelId(target.id)}
                  compared={compareIds.includes(model.id)}
                  onCompareToggle={(target) => toggleCompare(target.id)}
                  onUseInChat={model.route_enabled ? openModelInChat : undefined}
                  testId="model-showcase-card"
                />
              ))}
            </div>
            {collapsedGrid && hiddenCount > 0 ? (
              <button type="button" className="secondaryButton modelGridMore" data-testid="models-grid-more" onClick={() => setGridExpanded(true)}>
                All models ({hiddenCount} more)
              </button>
            ) : null}
          </>
        );
      })()}
    </section>
  );
}

function clientId(): string {
  return `code-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

const ADVANCED_TAB_SESSION_KEY = V2_WORKSPACE_SESSION_KEYS.advancedTab;
// The TMux/TUI console moved to the Code hero; stale saved tabs fall back to the overview dashboard.
const ADVANCED_TABS = ['overview', 'models', 'console', 'run', 'observe', 'operate'];

function normalizeAdvancedTab(value: unknown): string {
  return typeof value === 'string' && ADVANCED_TABS.includes(value) ? value : 'overview';
}

function loadAdvancedTab(): string {
  if (typeof window === 'undefined') return 'overview';
  try {
    return normalizeAdvancedTab(window.sessionStorage.getItem(ADVANCED_TAB_SESSION_KEY));
  } catch {
    return 'overview';
  }
}

function saveAdvancedTab(tab: string): void {
  if (typeof window === 'undefined') return;
  try {
    const normalized = normalizeAdvancedTab(tab);
    if (normalized === 'overview') {
      window.sessionStorage.removeItem(ADVANCED_TAB_SESSION_KEY);
      return;
    }
    window.sessionStorage.setItem(ADVANCED_TAB_SESSION_KEY, normalized);
  } catch {
    // Advanced remains usable even when browser storage is unavailable.
  }
}

function ReleaseReadinessPulse({ payload, loading, error, onOpen }: { payload?: OperatePayload; loading: boolean; error: unknown; onOpen: () => void }) {
  const releaseCandidate = recordValue(payload?.release_candidate);
  const summary = recordValue(releaseCandidate.summary);
  const operatorHandoff = recordValue(releaseCandidate.operator_handoff);
  const operatorHandoffItems = recordValues(operatorHandoff.items);
  const topOperatorItem = operatorHandoffItems[0] || {};
  const failedChecks = recordValues(releaseCandidate.checks).filter((check) => check.status !== 'passed');
  const failedReasonRows = failedChecks.slice(0, 3).map((check) => {
    const evidence = recordValue(check.evidence);
    const checkId = compactText(check.id);
    const title = compactText(check.title || check.id, 'Readiness check');
    let detail = compactText(check.severity, 'advisory');
    if (checkId === 'config_drift') {
      const blockingDrift = nonNegativeMetric(evidence.blocking_drift_count);
      const advisoryDrift = nonNegativeMetric(evidence.advisory_drift_count);
      detail = blockingDrift > 0 ? `${pluralize(blockingDrift, 'blocking drift item')}` : `${pluralize(advisoryDrift, 'low-risk drift item')}`;
    } else if (checkId === 'needs_operator') {
      detail = `${pluralize(nonNegativeMetric(evidence.open_items), 'operator item')} open`;
    } else if (checkId === 'worklist') {
      detail = `${pluralize(nonNegativeMetric(evidence.pending_p1_estimate), 'priority item')} open`;
    }
    return { id: checkId || title, title, detail };
  });
  const topOperatorTitle = compactText(topOperatorItem.item);
  const topOperatorOwner = compactText(topOperatorItem.owner, 'Operator');
  const topOperatorRank = compactText(topOperatorItem.priority_rank, '1');
  const ready = releaseCandidate.ready === true;
  const checks = nonNegativeMetric(summary.checks);
  const blocking = nonNegativeMetric(summary.blocking_failed);
  const advisory = nonNegativeMetric(summary.advisory_failed);
  const operatorItems = nonNegativeMetric(operatorHandoff.open_count);
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
          ? `${pluralize(operatorItems, 'operator item')} open`
          : advisory > 0 && reasonRows.length
          ? `${reasonRows[0].title}: ${reasonRows[0].detail}`
          : checks > 0
            ? `${pluralize(checks, 'check')} evaluated`
            : 'Awaiting release checks';
  return (
    <button className={`readinessPulse ${status}`} type="button" data-testid="advanced-readiness-pulse" onClick={onOpen} aria-label={`${label}. ${detail}. Open Operate`}>
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
        <span className="readinessPulseReasons" data-testid="advanced-readiness-reasons">
          {reasonRows.map((row) => (
            <span className="readinessPulseReason" data-testid="advanced-readiness-reason" key={row.id}>
              <b>{row.title}</b>
              <small>{row.detail}</small>
            </span>
          ))}
        </span>
      ) : null}
    </button>
  );
}

function AdvancedOverview({ onOpenOperate }: { onOpenOperate: () => void }) {
  const models = useQuery({ queryKey: ['models'], queryFn: getModels, retry: false });
  const operate = useQuery({ queryKey: ['operate'], queryFn: getOperate, refetchInterval: 30000, retry: false });
  const authPrompted = useRef(false);
  useEffect(() => {
    if (authPrompted.current) return;
    if (![models.error, operate.error].some(authLikeError)) return;
    authPrompted.current = true;
    window.dispatchEvent(new CustomEvent(V2_AUTH_REQUIRED_EVENT, {
      detail: {
        title: 'Console Access Required',
        detail: 'Sign in with a console token to load Advanced overview intelligence.',
      },
    }));
  }, [models.error, operate.error]);
  return (
    <div className="advancedOverview" data-testid="advanced-overview">
      <article className="advancedOverviewCard advancedWorkspaceCard" data-testid="advanced-active-workspace">
        <div className="advancedOverviewIdentity">
          <span className="advancedOverviewIcon">
            <CarbonIcon path="actions/document-properties-symbolic.svg" label="Advanced" />
          </span>
          <div>
            <span>Active Workspace</span>
            <strong>Advanced</strong>
            <p>Owner/admin tools</p>
          </div>
        </div>
        <div className="advancedOverviewFacts" aria-label="Advanced workspace summary">
          <span><b>4</b> primary workspaces</span>
          <span><b>6</b> advanced tabs</span>
        </div>
      </article>
      <ReleaseReadinessPulse payload={operate.data} loading={operate.isLoading} error={operate.error} onOpen={onOpenOperate} />
      <HomeSummary models={models.data?.models || []} />
      {models.error ? <StatusPanel tone="error" title="Model intelligence unavailable" detail={errorText(models.error)} /> : null}
    </div>
  );
}

export function AdvancedPage() {
  const [tab, setTab] = useState(loadAdvancedTab);
  useEffect(() => {
    saveAdvancedTab(tab);
  }, [tab]);
  useEffect(() => {
    const onTabChange = (event: Event) => {
      const tabName = (event as CustomEvent<{ tab?: unknown }>).detail?.tab;
      setTab(normalizeAdvancedTab(tabName));
    };
    window.addEventListener(V2_ADVANCED_TAB_EVENT, onTabChange);
    return () => window.removeEventListener(V2_ADVANCED_TAB_EVENT, onTabChange);
  }, []);
  const openOperateTab = () => setTab('operate');
  return (
    <section className="heroWorkspace advancedHero">
      <div className="heroHeader">
        <div>
          <p className="eyebrow">Owner/Admin Operations</p>
          <h1>Advanced</h1>
          <p>Operational dashboards, reporting, governance, evals, automation, and raw diagnostics.</p>
        </div>
      </div>
      <div className="advancedTabs">
        {ADVANCED_TABS.map((item) => <button className={tab === item ? 'active' : ''} key={item} type="button" onClick={() => setTab(item)}>{item}</button>)}
      </div>
      {tab === 'overview' ? <AdvancedOverview onOpenOperate={openOperateTab} /> : null}
      {tab === 'models' ? <ModelsPage /> : null}
      <Suspense fallback={<AdvancedLoading label={tab} />}>
        {tab === 'console' || tab === 'run' || tab === 'observe' || tab === 'operate' ? (
          <AdvancedThemeProvider>
            {tab === 'console' ? <ConsolePage /> : null}
            {tab === 'run' ? <RunPage /> : null}
            {tab === 'observe' ? <ObservePage /> : null}
            {tab === 'operate' ? <OperatePage /> : null}
          </AdvancedThemeProvider>
        ) : null}
      </Suspense>
    </section>
  );
}

export function HomeSummary({ models }: { models: ModelCard[] }) {
  const summary = useMemo(() => {
    const attentionStatuses = new Set(['not_checked', 'forbidden', 'rate_limited', 'probe_failed', 'removed']);
    const nationCounts = new Map<string, number>();
    models.forEach((model) => {
      const nation = model.training_nation || 'Unknown';
      nationCounts.set(nation, (nationCounts.get(nation) || 0) + 1);
    });
    return {
      total: models.length,
      routable: models.filter((model) => model.route_enabled).length,
      newModels: models.filter((model) => model.is_new).length,
      attention: models.filter((model) => !model.route_enabled || attentionStatuses.has(model.access_status)).length,
      nations: Array.from(nationCounts.entries()).sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0])).slice(0, 3),
    };
  }, [models]);
  return (
    <div className="homeSummary" data-testid="home-model-intelligence">
      <div className="homeSummaryHeader">
        <span>Model Intelligence</span>
        <strong>{summary.total ? `${summary.total} tracked` : 'Catalog loading'}</strong>
      </div>
      <div className="homeSummaryMetrics" aria-label="Model catalog summary">
        <div className="homeSummaryMetric">
          <span>Total</span>
          <strong>{summary.total}</strong>
        </div>
        <div className="homeSummaryMetric">
          <span>Routable</span>
          <strong>{summary.routable}</strong>
        </div>
        <div className="homeSummaryMetric">
          <span>New</span>
          <strong>{summary.newModels}</strong>
        </div>
        <div className="homeSummaryMetric">
          <span>Attention</span>
          <strong>{summary.attention}</strong>
        </div>
      </div>
      <div className="homeNationMix" aria-label="Training nation mix">
        {summary.nations.length ? summary.nations.map(([nation, count]) => (
          <span key={nation}><b>{nation}</b>{count}</span>
        )) : <span><b>Unknown</b>0</span>}
      </div>
      <div className="homeModelMiniStack">
        {models.slice(0, 3).map((model) => <ModelIdentityCard key={model.id} model={model} size="small" />)}
      </div>
    </div>
  );
}
