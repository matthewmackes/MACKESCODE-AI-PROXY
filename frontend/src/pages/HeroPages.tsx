import { ChangeEvent, ClipboardEvent, DragEvent, Fragment, KeyboardEvent, Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import alibabaCloudMark from 'simple-icons/icons/alibabacloud.svg?raw';
import anthropicMark from 'simple-icons/icons/anthropic.svg?raw';
import deepseekMark from 'simple-icons/icons/deepseek.svg?raw';
import googleMark from 'simple-icons/icons/google.svg?raw';
import metaMark from 'simple-icons/icons/meta.svg?raw';
import mistralMark from 'simple-icons/icons/mistralai.svg?raw';
import nvidiaMark from 'simple-icons/icons/nvidia.svg?raw';
import xiaomiMark from 'simple-icons/icons/xiaomi.svg?raw';
import {
  CodeAttachment,
  discoverModels,
  getChatPayload,
  getCodePayload,
  getCreatePayload,
  getModels,
  getResearchPayload,
  getWhatsNew,
  ModelCard,
  ResearchModelOutput,
  ResearchModelRole,
  ResearchSourceCoverage,
  WhatsNewPayload,
  ResearchResult,
  ResearchResultPayload,
  deleteCodeAttachment,
  reviewCodeImages,
  runChat,
  runCreateImages,
  runResearchSearch,
  sendCodeSession,
  startCodeSession,
  uploadCodeAttachment
} from '../api/v2';
import { errorText } from '../utils/errors';

const iconBase = '/branding/Mackes-Carbon/scalable';
export const WHATS_NEW_DISMISSED_KEY = 'matts-v2-whats-new-dismissed';
export const V2_WORKSPACE_SESSION_KEYS = {
  chatTranscript: 'matts-v2-chat-transcript',
  codeWorkspace: 'matts-v2-code-workspace',
  researchWorkspace: 'matts-v2-research-workspace',
  createWorkspace: 'matts-v2-create-workspace',
  modelsShowcase: 'matts-v2-models-showcase',
  advancedTab: 'matts-v2-advanced-tab',
} as const;
export const V2_ADVANCED_TAB_EVENT = 'matts-v2-advanced-tab-change';
export const V2_ADVANCED_LAZY_DELAY_KEY = 'matts-v2-advanced-lazy-delay-ms';
export const V2_RESETTABLE_WORKSPACE_KEYS = [
  V2_WORKSPACE_SESSION_KEYS.chatTranscript,
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
const TuiTerminal = lazy(() => delayedAdvancedImport(() => import('../components/TuiTerminal')));

export function CarbonIcon({ path, label }: { path: string; label: string }) {
  return <img className="carbonIcon" src={`${iconBase}/${path}`} alt="" title={label} aria-hidden="true" />;
}

function asText(value: unknown, fallback = ''): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

function responseText(payload: unknown): string {
  const row = payload && typeof payload === 'object' ? payload as Record<string, unknown> : {};
  const response = row.response && typeof row.response === 'object' ? row.response as Record<string, unknown> : row;
  return asText(response.text || response.content || response.message || response.answer || response);
}

function StatusPanel({ tone = 'neutral', title, detail }: { tone?: 'neutral' | 'loading' | 'error' | 'success'; title: string; detail?: string }) {
  return (
    <div className={`statusPanel ${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <span>{tone === 'loading' ? 'Loading' : tone}</span>
      <strong>{title}</strong>
      {detail ? <p>{detail}</p> : null}
    </div>
  );
}

function numeric(value: unknown): number {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function useTextModels(models: ModelCard[] | undefined) {
  return useMemo(() => (models || []).filter((model) => model.type === 'text' && model.route_enabled), [models]);
}

function ModelSelect({ models, value, onChange, label = 'Model' }: { models: ModelCard[]; value: string; onChange: (value: string) => void; label?: string }) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {models.map((model) => <option key={model.id} value={model.id}>{model.display_name}</option>)}
      </select>
    </label>
  );
}

function modelLogoInitials(model: ModelCard): string {
  const source = [model.company, model.family, model.provider, model.display_name].find((item) => String(item || '').trim()) || 'AI';
  const words = String(source).replace(/[^a-zA-Z0-9]+/g, ' ').trim().split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? words.slice(0, 2).map((word) => word[0]).join('') : words[0]?.slice(0, 2);
  return (letters || 'AI').toUpperCase();
}

type LocalBrandMark = { key: string; label: string; short: string; svg?: string };

const LOCAL_BRAND_MARKS: Record<string, LocalBrandMark> = {
  alibaba: { key: 'alibaba', label: 'Alibaba Cloud', short: 'ALI', svg: alibabaCloudMark },
  anthropic: { key: 'anthropic', label: 'Anthropic', short: 'ANT', svg: anthropicMark },
  arcee: { key: 'arcee', label: 'Arcee AI', short: 'ARC' },
  baai: { key: 'baai', label: 'BAAI', short: 'BAAI' },
  blackforest: { key: 'blackforest', label: 'Black Forest Labs', short: 'BFL' },
  deepseek: { key: 'deepseek', label: 'DeepSeek', short: 'DS', svg: deepseekMark },
  google: { key: 'google', label: 'Google', short: 'G', svg: googleMark },
  meta: { key: 'meta', label: 'Meta', short: 'META', svg: metaMark },
  microsoft: { key: 'microsoft', label: 'Microsoft', short: 'MS' },
  minimax: { key: 'minimax', label: 'MiniMax', short: 'MINI' },
  mistral: { key: 'mistral', label: 'Mistral AI', short: 'M', svg: mistralMark },
  moonshot: { key: 'moonshot', label: 'Moonshot AI', short: 'KIMI' },
  nvidia: { key: 'nvidia', label: 'NVIDIA', short: 'NV', svg: nvidiaMark },
  openai: { key: 'openai', label: 'OpenAI', short: 'OAI' },
  stability: { key: 'stability', label: 'Stability AI', short: 'SD' },
  xiaomi: { key: 'xiaomi', label: 'Xiaomi', short: 'MI', svg: xiaomiMark },
  zhipu: { key: 'zhipu', label: 'Zhipu AI', short: 'GLM' },
};

const LOCAL_BRAND_MATCHERS: Array<[string, string[]]> = [
  ['anthropic', ['anthropic', 'claude']],
  ['openai', ['openai', 'gpt']],
  ['deepseek', ['deepseek']],
  ['mistral', ['mistral']],
  ['alibaba', ['alibaba', 'qwen', 'gte']],
  ['zhipu', ['zhipu', 'glm']],
  ['moonshot', ['moonshot', 'kimi']],
  ['meta', ['meta', 'llama']],
  ['google', ['google', 'gemma', 'gemini']],
  ['nvidia', ['nvidia', 'nemotron']],
  ['minimax', ['minimax']],
  ['xiaomi', ['xiaomi', 'mimo']],
  ['arcee', ['arcee']],
  ['stability', ['stability', 'stable diffusion', 'stable-diffusion', 'sdxl']],
  ['blackforest', ['black forest', 'blackforest', 'flux']],
  ['baai', ['baai', 'bge']],
  ['microsoft', ['microsoft', 'e5']],
];

function localBrandMark(model: ModelCard): LocalBrandMark | undefined {
  const haystack = [
    model.id,
    model.display_name,
    model.company,
    model.family,
    model.provider,
    model.artwork?.logo,
    model.artwork?.brand_url,
  ].join(' ').toLowerCase();
  const match = LOCAL_BRAND_MATCHERS.find(([, needles]) => needles.some((needle) => haystack.includes(needle)));
  return match ? LOCAL_BRAND_MARKS[match[0]] : undefined;
}

function canRenderArtworkLogo(url: string): boolean {
  if (!url) return false;
  if (/^(blob|data):/i.test(url)) return true;
  if (url.startsWith('/')) return true;
  if (typeof window === 'undefined') return false;
  try {
    return new URL(url, window.location.origin).origin === window.location.origin;
  } catch {
    return false;
  }
}

function ModelLogo({ model, size }: { model: ModelCard; size?: 'large' | 'xl' }) {
  const logo = model.artwork?.logo || '';
  const renderableLogo = canRenderArtworkLogo(logo);
  const brandMark = localBrandMark(model);
  const [failedLogo, setFailedLogo] = useState(false);
  useEffect(() => setFailedLogo(false), [model.id, logo, renderableLogo]);
  const className = ['modelLogo', size].filter(Boolean).join(' ');
  const artworkState = renderableLogo && logo && !failedLogo ? 'public-logo' : brandMark?.svg ? 'local-brand-svg' : brandMark ? 'local-brand-text' : logo ? 'attributed-initials' : 'generated-initials';
  return (
    <div className={className} data-artwork-state={artworkState} data-brand={brandMark?.key || ''} data-testid="model-logo" aria-label={`${model.display_name} model identity`}>
      {renderableLogo && logo && !failedLogo ? (
        <img src={logo} alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailedLogo(true)} />
      ) : brandMark?.svg ? (
        <span className="modelBrandSvg" aria-hidden="true" title={brandMark.label} dangerouslySetInnerHTML={{ __html: brandMark.svg }} />
      ) : brandMark ? (
        <span className="modelBrandText" aria-hidden="true" title={brandMark.label}>{brandMark.short}</span>
      ) : (
        <span aria-hidden="true">{modelLogoInitials(model)}</span>
      )}
    </div>
  );
}

function ModelMiniCard({ model }: { model: ModelCard }) {
  return (
    <article className="modelMiniCard" style={{ ['--accent' as string]: model.nation_palette?.accent || '#0f62fe', ['--surface' as string]: model.nation_palette?.surface || '#f4f4f4' }}>
      <ModelLogo model={model} />
      <div>
        <strong>{model.display_name}</strong>
        <span>{model.company} · {model.training_nation}</span>
      </div>
    </article>
  );
}

function ModelAlertCard({ model }: { model: ModelCard }) {
  return (
    <article className="modelAlertCard" style={{ ['--accent' as string]: model.nation_palette?.accent || '#0f62fe', ['--surface' as string]: model.nation_palette?.surface || '#f4f4f4' }}>
      <ModelLogo model={model} />
      <div>
        <strong>{model.display_name}</strong>
        <span>{model.company} · {model.training_nation}</span>
        <small>{[model.route_enabled ? 'Routable' : readableStatus(model.access_status), model.type, model.cost_label].filter(Boolean).join(' · ')}</small>
      </div>
    </article>
  );
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
                {data.new_models.slice(0, 6).map((model) => <ModelAlertCard key={model.id} model={model} />)}
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
                {data.attention.slice(0, 6).map((model) => <ModelAlertCard key={model.id} model={model} />)}
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
  const brandMark = localBrandMark(model);
  return (
    <div className="modelArtworkGallery" aria-label="Artwork source gallery">
      <div className="artworkIdentity" style={{ ['--accent' as string]: model.nation_palette?.accent || '#0f62fe', ['--secondary' as string]: model.nation_palette?.secondary || '#da1e28', ['--surface' as string]: model.nation_palette?.surface || '#edf5ff' }}>
        <ModelLogo model={model} size="xl" />
        <div>
          <span>Brand Identity</span>
          <strong>{model.company}</strong>
          <p>{model.family} · {model.training_nation}</p>
        </div>
        {model.artwork?.brand_url ? <a className="artworkBrandLink" href={model.artwork.brand_url} target="_blank" rel="noreferrer">Brand Site</a> : <span className="artworkBrandLink muted">Generated Identity</span>}
      </div>
      <div className="artworkFacts" aria-label="Artwork metadata">
        <div><span>Logo</span><strong>{model.artwork?.logo ? 'Tracked public URL' : brandMark ? 'Local brand mark' : 'Generated initials'}</strong></div>
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

const MODEL_COMPARE_ROWS: Array<[string, (model: ModelCard) => string]> = [
  ['Provider', (model: ModelCard) => model.provider],
  ['Company', (model: ModelCard) => model.company],
  ['Training Nation', (model: ModelCard) => model.training_nation],
  ['Status', (model: ModelCard) => model.route_enabled ? 'Routable' : readableStatus(model.access_status)],
  ['Context', (model: ModelCard) => `${model.context_window.toLocaleString()} tokens`],
  ['Output', (model: ModelCard) => `${model.max_output_tokens.toLocaleString()} tokens`],
  ['Type', (model: ModelCard) => model.type],
  ['Cost', (model: ModelCard) => model.cost_label],
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
  const copyBrief = async () => {
    try {
      await copyText(brief);
      setBriefStatus('Copied');
    } catch {
      setBriefStatus('Copy failed');
    }
  };
  const downloadBrief = () => {
    const blob = new Blob([brief], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `mde-llm-proxy-model-compare-brief-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    setBriefStatus('Downloaded');
  };
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
          <div className="modelCompareModel" key={model.id} style={{ ['--accent' as string]: model.nation_palette?.accent || '#0f62fe', ['--surface' as string]: model.nation_palette?.surface || '#f4f4f4' }}>
            <ModelLogo model={model} />
            <div>
              <strong>{model.display_name}</strong>
              <span>{model.company}</span>
            </div>
            <button className="iconButton" type="button" aria-label={`Remove ${model.display_name} from compare`} onClick={() => onRemove(model.id)}><CarbonIcon path="actions/list-remove-symbolic.svg" label="Remove" /></button>
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

function SelectedModelPanel({ model }: { model?: ModelCard }) {
  if (!model) return <StatusPanel title="No model selected" detail="Choose a routable model before sending a chat request." />;
  return (
    <div className="selectedModelPanel" style={{ ['--accent' as string]: model.nation_palette?.accent || '#0f62fe', ['--surface' as string]: model.nation_palette?.surface || '#edf5ff' }}>
      <ModelLogo model={model} />
      <div>
        <span>Selected Model</span>
        <strong>{model.display_name}</strong>
        <p>{model.company} · {model.training_nation}</p>
      </div>
      <div className="selectedModelFacts">
        <span>{model.route_enabled ? 'Routable' : model.access_status}</span>
        <span>{model.cost_label}</span>
        <span>{model.context_window.toLocaleString()} ctx</span>
      </div>
    </div>
  );
}

type ChatMessage = { role: string; content: string; model?: string; company?: string; accent?: string };
const CHAT_TRANSCRIPT_SESSION_KEY = V2_WORKSPACE_SESSION_KEYS.chatTranscript;
const CHAT_TRANSCRIPT_LIMIT = 50;

function normalizeChatMessage(value: unknown): ChatMessage | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  if (typeof row.role !== 'string' || typeof row.content !== 'string') return null;
  const role = row.role.trim();
  const content = row.content;
  if (!role || !content.trim()) return null;
  return {
    role,
    content,
    ...(typeof row.model === 'string' && row.model ? { model: row.model } : {}),
    ...(typeof row.company === 'string' && row.company ? { company: row.company } : {}),
    ...(typeof row.accent === 'string' && row.accent ? { accent: row.accent } : {}),
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
    const label = [message.role.toUpperCase(), message.model, message.company].filter(Boolean).join(' · ');
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

async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Fall back for plain-HTTP remote browser sessions where clipboard access is restricted.
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

function readableStatus(value: string | undefined): string {
  return String(value || 'unknown').replace(/_/g, ' ');
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
      if (!('permissions' in navigator) || !navigator.geolocation) return;
      try {
        const permission = await navigator.permissions.query({ name: 'geolocation' as PermissionName });
        if (permission.state !== 'granted' || cancelled) return;
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

function researchBriefMetrics(data: ResearchResultPayload, results: ResearchResult[]): Array<[string, number]> {
  const engineCount = new Set(results.map((result) => result.engine || result.engine_name).filter(Boolean)).size;
  const degradedCount = data.synthesis?.degraded_engines?.length || results.filter((result) => ['needs_key', 'not_indexed', 'unavailable', 'error'].includes(result.status)).length;
  const liveCount = numeric(data.synthesis?.live_result_count) || results.filter((result) => ['live', 'catalog', 'local'].includes(result.status)).length;
  const evidenceCount = numeric(data.synthesis?.evidence_count) || results.length;
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

function researchSourceMetrics(data: ResearchResultPayload): Array<[string, number]> {
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

function researchSourceCoverage(data: ResearchResultPayload): ResearchSourceCoverage[] {
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

function researchBriefMarkdown(data: ResearchResultPayload, results: ResearchResult[], metrics: Array<[string, number]>): string {
  const sourceCoverage = researchSourceCoverage(data);
  const lines = [
    `# ${data.synthesis?.title || 'Research Brief'}`,
    '',
    `Query: ${data.query}`,
    `Mode: ${data.mode}`,
    `Generated: ${new Date().toISOString()}`,
    '',
    '## Summary',
    data.synthesis?.summary || 'No synthesis available yet.',
    '',
    '## Coordinated Answer',
    data.model_outputs?.answer || data.synthesis?.coordinated_answer || 'No coordinated answer is available yet.',
    '',
    '## Research Team',
  ];
  const team = [
    ...(data.model_strategy?.analysts || []),
    ...(data.model_strategy?.coordinator ? [data.model_strategy.coordinator] : []),
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
  const analystOutputs = data.model_outputs?.analysts || [];
  if (analystOutputs.length) {
    analystOutputs.forEach((output) => lines.push(`- ${output.label}: ${output.text}`));
  } else {
    lines.push('- No analyst outputs are available yet.');
  }
  lines.push(
    '',
    '## Evidence',
  );
  if (!results.length) {
    lines.push('- No evidence matches the active filter.');
  } else {
    results.forEach((result, index) => {
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

function researchSourcePacket(result: ResearchResult): string {
  const lines = [
    `# ${result.title || 'Research Source'}`,
    '',
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

function ResearchBriefActions({ brief, disabled = false, className = 'researchBriefActions' }: { brief: string; disabled?: boolean; className?: string }) {
  const readyStatus = disabled ? 'No brief' : 'Brief Ready';
  const [briefStatus, setBriefStatus] = useState(readyStatus);
  useEffect(() => {
    setBriefStatus(readyStatus);
  }, [brief, readyStatus]);
  const copyBrief = async () => {
    if (disabled) return;
    try {
      await copyText(brief);
      setBriefStatus('Copied');
    } catch {
      setBriefStatus('Copy failed');
    }
  };
  const downloadBrief = () => {
    if (disabled) return;
    const blob = new Blob([brief], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `mde-llm-proxy-research-brief-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    setBriefStatus('Downloaded');
  };
  return (
    <div className={className} aria-label="Research brief actions">
      <span>{briefStatus}</span>
      <button className="secondaryButton" type="button" disabled={disabled} onClick={() => void copyBrief()}>Copy Brief</button>
      <button className="secondaryButton" type="button" disabled={disabled} onClick={downloadBrief}>Download Brief</button>
    </div>
  );
}

function ResearchTeamPanel({ strategy }: { strategy?: ResearchResultPayload['model_strategy'] }) {
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

function ResearchModelOutputs({ data }: { data: ResearchResultPayload }) {
  const outputs = data.model_outputs;
  const analysts = outputs?.analysts || [];
  const coordinator = outputs?.coordinator;
  const answer = outputs?.answer || data.synthesis?.coordinated_answer || coordinator?.text || '';
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

function ResearchEvidence({ data, compact = false }: { data: ResearchResultPayload; compact?: boolean }) {
  const [engineFilter, setEngineFilter] = useState('all');
  const [copiedResultId, setCopiedResultId] = useState('');
  const results = data.results || [];
  const engineOptions = useMemo(() => {
    const rows = new Map<string, string>();
    results.forEach((result) => rows.set(result.engine || result.engine_name, result.engine_name || result.engine));
    return Array.from(rows.entries()).filter(([id]) => Boolean(id));
  }, [results]);
  const filterableEngineIds = useMemo(() => new Set(engineOptions.map(([id]) => id)), [engineOptions]);
  useEffect(() => {
    if (engineFilter !== 'all' && !engineOptions.some(([id]) => id === engineFilter)) setEngineFilter('all');
  }, [engineFilter, engineOptions]);
  const visibleResults = engineFilter === 'all' ? results : results.filter((result) => result.engine === engineFilter);
  const metrics = researchBriefMetrics(data, visibleResults);
  const sourceMetrics = researchSourceMetrics(data);
  const sourceCoverage = researchSourceCoverage(data);
  const brief = researchBriefMarkdown(data, visibleResults, metrics);
  const copySourcePacket = async (result: ResearchResult) => {
    const resultId = String(result.id || result.citation || result.title);
    try {
      await copyText(researchSourcePacket(result));
      setCopiedResultId(resultId);
    } catch {
      setCopiedResultId(`failed:${resultId}`);
    }
  };
  return (
    <div className={compact ? 'researchEvidence compact' : 'researchEvidence'}>
      <div className="synthesisPanel">
        <div>
          <span>{readableStatus(data.mode)}</span>
          <strong>{data.synthesis?.title || 'Research synthesis'}</strong>
        </div>
        <p>{data.synthesis?.summary || 'No synthesis available yet.'}</p>
      </div>
      <ResearchTeamPanel strategy={data.model_strategy} />
      <ResearchModelOutputs data={data} />
      <div className="researchCommandBoard">
        <div className="researchMetrics" aria-label="Research result summary">
          {metrics.map(([label, value]) => <div key={label}><span>{label}</span><strong>{Number(value).toLocaleString()}</strong></div>)}
        </div>
        {sourceMetrics.length ? (
          <div className="researchSourceMix" aria-label="Research source classes">
            {sourceMetrics.map(([label, value]) => <span key={label}>{label}<strong>{Number(value).toLocaleString()}</strong></span>)}
          </div>
        ) : null}
        {sourceCoverage.length ? (
          <div className="sourceCoveragePanel" aria-label="Required research source coverage" data-testid="research-source-coverage">
            {sourceCoverage.map((row) => {
              const engineId = row.engine_id || row.id;
              const filterable = filterableEngineIds.has(engineId);
              const active = engineFilter === engineId;
              return (
                <button
                  aria-pressed={active}
                  className={`sourceCoverageChip status-${row.status} ${active ? 'active' : ''}`}
                  disabled={!filterable}
                  key={engineId}
                  onClick={() => setEngineFilter(active ? 'all' : engineId)}
                  title={filterable ? `${row.detail} Filter evidence to ${row.label || row.name}.` : row.detail}
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
          </div>
        ) : null}
        <ResearchBriefActions brief={brief} />
      </div>
      <div className="resultList">
        {visibleResults.length ? visibleResults.map((result) => (
          <article className={`searchResult status-${result.status}`} key={String(result.id)}>
            <div className="resultMeta">
              <span>{result.engine_name}</span>
              <span>{readableStatus(result.status)}</span>
              <span>{result.citation}</span>
              {Number.isFinite(Number(result.score)) ? <span>{Math.round(Number(result.score) * 100)} score</span> : null}
              <button
                className={`resultCopyButton ${copiedResultId === String(result.id || result.citation || result.title) ? 'copied' : ''}`}
                type="button"
                onClick={() => void copySourcePacket(result)}
                aria-label={`Copy Source for ${result.title}`}
              >
                <CarbonIcon path="apps/copy--to-clipboard.svg" label="Copy Source" />
                {copiedResultId === `failed:${String(result.id || result.citation || result.title)}` ? 'Copy Failed' : copiedResultId === String(result.id || result.citation || result.title) ? 'Copied' : 'Copy Source'}
              </button>
            </div>
            <h3>{result.url ? <a href={result.url} target="_blank" rel="noreferrer">{result.title}</a> : result.title}</h3>
            {result.thumbnail_url ? <img className="resultThumbnail" src={result.thumbnail_url} alt="" loading="lazy" /> : null}
            <p>{result.snippet}</p>
            {result.coordinates ? <small>Coordinates: {result.coordinates}</small> : null}
            <small>{result.source}{result.published_at ? ` · ${result.published_at}` : ''}</small>
          </article>
        )) : <div className="emptyState">No evidence matches this filter.</div>}
      </div>
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
  mode: string;
  prompt: string;
  summary: string;
  createdAt: string;
  thumbnail?: string;
  result?: string;
  imageResult?: { images: CreateImageResult[]; raw: string } | null;
  researchResult?: ResearchResultPayload | null;
  researchSourceMode?: CreateResearchSourceMode;
};

type CreateResearchSourceMode = 'all' | 'required';

type CreateWorkspaceState = {
  mode: string;
  prompt: string;
  result: string;
  imageResult: { images: CreateImageResult[]; raw: string } | null;
  researchResult: ResearchResultPayload | null;
  researchSourceMode: CreateResearchSourceMode;
  historyItems: CreateHistoryItem[];
};

const CREATE_WORKSPACE_SESSION_KEY = V2_WORKSPACE_SESSION_KEYS.createWorkspace;
const CREATE_HISTORY_LIMIT = 6;
const CREATE_MODES = ['Chat', 'Research', 'Image'];

function emptyCreateWorkspace(): CreateWorkspaceState {
  return { mode: 'Chat', prompt: '', result: '', imageResult: null, researchResult: null, researchSourceMode: 'all', historyItems: [] };
}

function normalizeCreateHistoryItem(value: unknown): CreateHistoryItem | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const mode = asText(row.mode);
  const prompt = asText(row.prompt);
  const summary = asText(row.summary);
  const createdAt = asText(row.createdAt);
  if (!mode || !prompt || !summary || !createdAt) return null;
  return {
    id: asText(row.id, `${createdAt}-${mode}-${prompt.slice(0, 16)}`),
    mode,
    prompt,
    summary,
    createdAt,
    result: asText(row.result),
    imageResult: normalizeCreateImageResult(row.imageResult),
    researchResult: normalizeResearchPayload(row.researchResult),
    researchSourceMode: row.researchSourceMode === 'required' ? 'required' : 'all',
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

function normalizeResearchResult(value: unknown): ResearchResult | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const title = asText(row.title);
  if (!title) return null;
  return {
    id: asText(row.id, title),
    engine: asText(row.engine || row.engine_name, 'local'),
    engine_name: asText(row.engine_name || row.engine, 'Evidence'),
    title,
    url: asText(row.url),
    snippet: asText(row.snippet),
    published_at: asText(row.published_at),
    source: asText(row.source, 'Session'),
    status: asText(row.status, 'local'),
    kind: asText(row.kind, 'web'),
    score: numeric(row.score),
    position: numeric(row.position),
    citation: asText(row.citation),
    ...(typeof row.path === 'string' ? { path: row.path } : {}),
    ...(Number.isFinite(Number(row.chunk)) ? { chunk: Number(row.chunk) } : {}),
    ...(typeof row.collection_id === 'string' ? { collection_id: row.collection_id } : {}),
    ...(typeof row.thumbnail_url === 'string' ? { thumbnail_url: row.thumbnail_url } : {}),
    ...(typeof row.content_url === 'string' ? { content_url: row.content_url } : {}),
    ...(typeof row.coordinates === 'string' ? { coordinates: row.coordinates } : {}),
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

function normalizeResearchPayload(value: unknown): ResearchResultPayload | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  if (!Array.isArray(row.results)) return null;
  const results = row.results.map(normalizeResearchResult).filter((result): result is ResearchResult => Boolean(result));
  const synthesis = row.synthesis && typeof row.synthesis === 'object' ? row.synthesis as Record<string, unknown> : {};
  const strategyRow = row.model_strategy && typeof row.model_strategy === 'object' ? row.model_strategy as Record<string, unknown> : {};
  const outputsRow = row.model_outputs && typeof row.model_outputs === 'object' ? row.model_outputs as Record<string, unknown> : {};
  const analysts = Array.isArray(strategyRow.analysts) ? strategyRow.analysts.map(normalizeResearchRole).filter((item): item is ResearchModelRole => Boolean(item)) : [];
  const outputAnalysts = Array.isArray(outputsRow.analysts) ? outputsRow.analysts.map(normalizeResearchModelOutput).filter((item): item is ResearchModelOutput => Boolean(item)) : [];
  const coordinator = normalizeResearchRole(strategyRow.coordinator);
  const outputCoordinator = normalizeResearchModelOutput(outputsRow.coordinator);
  const policy = strategyRow.policy && typeof strategyRow.policy === 'object' ? strategyRow.policy as Record<string, unknown> : {};
  return {
    query: asText(row.query),
    mode: asText(row.mode, 'Balanced'),
    engines: Array.isArray(row.engines) ? row.engines as ResearchResultPayload['engines'] : [],
    results,
    model_strategy: Object.keys(strategyRow).length ? {
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
    model_outputs: Object.keys(outputsRow).length ? {
      analysts: outputAnalysts,
      coordinator: outputCoordinator || undefined,
      answer: asText(outputsRow.answer) || undefined,
      generated_at: Number.isFinite(Number(outputsRow.generated_at)) ? Number(outputsRow.generated_at) : undefined,
    } : undefined,
    synthesis: {
      title: asText(synthesis.title) || undefined,
      summary: asText(synthesis.summary) || undefined,
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
    },
  };
}

type ResearchEngineSelectionMode = 'all' | 'custom';

type ResearchWorkspaceState = {
  query: string;
  mode: string;
  engineSelectionMode: ResearchEngineSelectionMode;
  selectedEngines: string[];
  result: ResearchResultPayload | null;
};

const RESEARCH_WORKSPACE_SESSION_KEY = V2_WORKSPACE_SESSION_KEYS.researchWorkspace;
const RESEARCH_SELECTED_ENGINE_LIMIT = 12;

function emptyResearchWorkspace(): ResearchWorkspaceState {
  return { query: '', mode: 'Balanced', engineSelectionMode: 'all', selectedEngines: [], result: null };
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
    return {
      query: asText(row.query),
      mode: asText(row.mode, 'Balanced'),
      engineSelectionMode,
      selectedEngines: engineSelectionMode === 'custom' ? selectedEngines : [],
      result: normalizeResearchPayload(row.result),
    };
  } catch {
    return emptyResearchWorkspace();
  }
}

function hasResearchWorkspaceState(state: ResearchWorkspaceState): boolean {
  return Boolean(state.query.trim() || state.mode !== 'Balanced' || state.engineSelectionMode !== 'all' || state.selectedEngines.length || state.result);
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
    const mode = asText(row.mode, 'Chat');
    return {
      mode: CREATE_MODES.includes(mode) ? mode : 'Chat',
      prompt: asText(row.prompt),
      result: asText(row.result),
      imageResult: normalizeCreateImageResult(row.imageResult),
      researchResult: normalizeResearchPayload(row.researchResult),
      researchSourceMode: row.researchSourceMode === 'required' ? 'required' : 'all',
      historyItems: Array.isArray(row.historyItems)
        ? row.historyItems.map(normalizeCreateHistoryItem).filter((item): item is CreateHistoryItem => Boolean(item)).slice(0, CREATE_HISTORY_LIMIT)
        : [],
    };
  } catch {
    return emptyCreateWorkspace();
  }
}

function hasCreateWorkspaceState(state: CreateWorkspaceState): boolean {
  return state.mode !== 'Chat' || state.researchSourceMode !== 'all' || Boolean(state.prompt.trim() || state.result.trim() || state.imageResult || state.researchResult || state.historyItems.length);
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

function hasCreateBriefState({ result, imageResult, researchResult, historyItems }: CreateWorkspaceState): boolean {
  return Boolean(result.trim() || researchResult || imageResult?.images.length || imageResult?.raw.trim() || historyItems.length);
}

function createBriefMarkdown({ mode, prompt, result, imageResult, researchResult, researchSourceMode, historyItems }: CreateWorkspaceState): string {
  const lines = [
    '# Create Brief',
    '',
    `Generated: ${new Date().toISOString()}`,
    `Active Mode: ${mode || 'n/a'}`,
    `Research Source Mode: ${researchSourceMode === 'required' ? 'Required Sources' : 'All Sources'}`,
    `Current Prompt: ${prompt.trim() || 'n/a'}`,
    `History Items: ${historyItems.length}`,
    '',
    '## Current Output',
    result.trim() || 'No chat text output in the current Create workspace.',
    '',
    '## Research',
  ];
  if (!researchResult) {
    lines.push('No research synthesis is active.');
  } else {
    const evidenceCount = numeric(researchResult.synthesis?.evidence_count) || researchResult.results.length;
    const engines = researchResult.engines.map((engine) => `${engine.name} (${readableStatus(engine.status)})`);
    const coverage = researchSourceCoverage(researchResult);
    lines.push(
      `Query: ${researchResult.query || prompt.trim() || 'n/a'}`,
      `Mode: ${researchResult.mode || 'n/a'}`,
      `Engines: ${engines.length ? engines.join(', ') : 'n/a'}`,
      `Evidence Count: ${evidenceCount}`,
      '',
      '### Synthesis',
      researchResult.synthesis?.summary || 'No synthesis summary available.',
      '',
      '### Source Coverage',
      ...(coverage.length ? coverage.map((row) => `- ${row.label || row.name}: ${readableStatus(row.status)}; ${Number(row.usable_count || 0).toLocaleString()} usable / ${Number(row.result_count || 0).toLocaleString()} total`) : ['- No source coverage reported.']),
      '',
      '### Evidence',
    );
    if (!researchResult.results.length) {
      lines.push('- No evidence results were returned.');
    } else {
      researchResult.results.forEach((item, index) => {
        lines.push(
          `${index + 1}. ${item.title}`,
          `   - Engine: ${item.engine_name} (${readableStatus(item.status)})`,
          `   - Source: ${item.source}${item.published_at ? `, ${item.published_at}` : ''}`,
          `   - Citation: ${item.citation || 'n/a'}`,
          `   - URL: ${item.url || 'n/a'}`,
          `   - Snippet: ${item.snippet || 'n/a'}`,
        );
      });
    }
  }
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
        `${index + 1}. ${item.mode} · ${item.createdAt}`,
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
    `Mode: ${item.mode || 'n/a'}`,
    `Created: ${item.createdAt || 'n/a'}`,
    `Prompt: ${item.prompt || 'n/a'}`,
    `Summary: ${item.summary || 'n/a'}`,
  ];
  if (item.researchSourceMode) {
    lines.push(`Research Source Mode: ${item.researchSourceMode === 'required' ? 'Required Sources' : 'All Sources'}`);
  }
  if (item.result?.trim()) {
    lines.push('', '## Chat Output', item.result.trim());
  }
  if (item.researchResult) {
    const research = item.researchResult;
    lines.push(
      '',
      '## Research Snapshot',
      researchBriefMarkdown(research, research.results || [], researchBriefMetrics(research, research.results || [])),
    );
  }
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
  }
  if (!item.result?.trim() && !item.researchResult && !item.imageResult) {
    lines.push('', '## Snapshot', 'No output snapshot was stored with this history item.');
  }
  return lines.join('\n');
}

function CreateHistoryCard({ item, onReuse, onCopy }: { item: CreateHistoryItem; onReuse: (item: CreateHistoryItem) => void; onCopy: (item: CreateHistoryItem) => void }) {
  return (
    <article className="createHistoryCard">
      {item.thumbnail ? <img src={item.thumbnail} alt="" /> : <div className="createHistoryBadge">{item.mode.slice(0, 1)}</div>}
      <div>
        <span>{item.mode} · {item.createdAt}</span>
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

type CodeWorkspaceState = {
  sessionName: string;
  projectDir: string;
  model: string;
  prompt: string;
  actions: CodeActionRecord[];
  attachments: CodeAttachment[];
};

const CODE_WORKSPACE_SESSION_KEY = V2_WORKSPACE_SESSION_KEYS.codeWorkspace;
const CODE_ACTION_LIMIT = 20;
const CODE_ATTACHMENT_LIMIT = 8;
const CODE_ATTACHMENT_PREVIEW_LIMIT = 1_500_000;

function emptyCodeWorkspace(): CodeWorkspaceState {
  return { sessionName: '', projectDir: '', model: '', prompt: '', actions: [], attachments: [] };
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
    state.attachments.length
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
}: {
  sessionName: string;
  projectDir: string;
  model: string;
  prompt: string;
  actions: CodeActionRecord[];
  attachments: CodeAttachment[];
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

export function ChatPage() {
  const chat = useQuery({ queryKey: ['chat-payload'], queryFn: getChatPayload });
  const models = useTextModels(chat.data?.models);
  const [model, setModel] = useState('');
  const [prompt, setPrompt] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>(loadChatTranscript);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [voiceDefaultLoaded, setVoiceDefaultLoaded] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState('Ready');
  const [transcriptStatus, setTranscriptStatus] = useState('Ready');
  const selectedModel = model || chat.data?.default_model || models[0]?.id || '';
  const selectedModelCard = models.find((item) => item.id === selectedModel) || models[0];
  const voiceProfile = chat.data?.voice;
  const voiceStyle = voiceProfile?.style || 'calm mission-computer';
  const voiceMode = readableStatus(voiceProfile?.mode || 'browser_speech_synthesis');
  const voicePreview = voiceProfile?.preview || 'MDE LLM-PROXY voice online.';
  const voiceMaxChars = Math.max(200, numeric(voiceProfile?.max_chars) || 1200);
  const transcript = serializeTranscript(messages);
  const chatBrief = chatBriefMarkdown(messages, selectedModel, selectedModelCard);
  const lastAssistant = [...messages].reverse().find((message) => message.role === 'assistant');
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
  const copyChatBrief = async () => {
    if (!messages.length) return;
    try {
      await copyText(chatBrief);
      setTranscriptStatus('Brief copied');
    } catch {
      setTranscriptStatus('Brief copy failed');
    }
  };
  const downloadChatBrief = () => {
    if (!messages.length) return;
    const blob = new Blob([chatBrief], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `mde-llm-proxy-chat-brief-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    setTranscriptStatus('Brief downloaded');
  };
  useEffect(() => {
    if (!voiceProfile || voiceDefaultLoaded) return;
    setVoiceEnabled(voiceProfile.enabled_by_default !== false);
    setVoiceDefaultLoaded(true);
  }, [voiceDefaultLoaded, voiceProfile]);
  useEffect(() => {
    if (!voiceProfile) return;
    if (!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') {
      setVoiceStatus('Unavailable');
    } else {
      setVoiceStatus(voiceEnabled ? 'Ready' : 'Muted');
    }
  }, [voiceEnabled, voiceProfile]);
  useEffect(() => {
    saveChatTranscript(messages);
  }, [messages]);
  const stopVoice = () => {
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    setVoiceStatus(voiceEnabled ? 'Ready' : 'Muted');
  };
  const speak = (text: string) => {
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
  const toggleVoice = () => {
    const next = !voiceEnabled;
    if (!next) stopVoice();
    setVoiceEnabled(next);
  };
  const clearTranscript = () => {
    setMessages([]);
    saveChatTranscript([]);
    setTranscriptStatus('Cleared');
    stopVoice();
  };
  const mutation = useMutation({
    mutationFn: () => runChat({ model: selectedModel, messages: [...messages, { role: 'user', content: prompt }] }),
    onSuccess: (payload) => {
      const answer = responseText(payload);
      const nextMessages = [
        ...messages,
        { role: 'user', content: prompt },
        {
          role: 'assistant',
          content: answer,
          model: selectedModelCard?.display_name || selectedModel,
          company: selectedModelCard?.company,
          accent: selectedModelCard?.nation_palette?.accent,
        }
      ];
      setMessages(nextMessages);
      setPrompt('');
      speak(answer);
    }
  });
  const canSendChat = Boolean(prompt.trim()) && !mutation.isPending;
  const sendChat = () => {
    if (!canSendChat) return;
    mutation.mutate();
  };
  const handleChatComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || (!event.ctrlKey && !event.metaKey) || !canSendChat) return;
    event.preventDefault();
    mutation.mutate();
  };
  return (
    <section className="heroWorkspace chatHero">
      <div className="heroHeader">
        <div>
          <p className="eyebrow">Autonomous System Manager</p>
          <h1>Chat</h1>
          <p>Command-center chat with RBAC-aware model execution, voice output, and model identity carried into every response.</p>
        </div>
        <div className="heroActions">
          <button className={`iconButton ${voiceEnabled ? 'active' : ''}`} type="button" aria-label={voiceEnabled ? 'Mute voice' : 'Enable voice'} aria-pressed={voiceEnabled} onClick={toggleVoice}>
            <CarbonIcon path="actions/call-start-symbolic.svg" label="Voice" />
          </button>
        </div>
      </div>
      <div className="workspaceGrid twoColumn">
        <div className="composerPanel">
          {chat.isLoading ? <StatusPanel tone="loading" title="Loading chat workspace" /> : null}
          {chat.error ? <StatusPanel tone="error" title="Chat API unavailable" detail={errorText(chat.error)} /> : null}
          {!chat.isLoading && !chat.error && !models.length ? <StatusPanel title="No routable text models" detail="Enable or discover a routable text model before sending chat requests." /> : null}
          <ModelSelect models={models} value={selectedModel} onChange={setModel} />
          <SelectedModelPanel model={selectedModelCard} />
          <div className={`voiceConsole ${voiceEnabled ? 'active' : 'muted'}`} aria-label="Chat voice controls">
            <div className="voiceConsoleLead">
              <CarbonIcon path={voiceEnabled ? 'actions/media-playback-start-symbolic.svg' : 'actions/media-playback-stop-symbolic.svg'} label="Voice status" />
              <div>
                <span>{voiceEnabled ? 'Voice enabled' : 'Voice muted'}</span>
                <strong>{voiceStyle}</strong>
                <p>{voiceMode} · {voiceStatus} · {voiceMaxChars.toLocaleString()} chars</p>
              </div>
            </div>
            <div className="voiceControls">
              <button className="secondaryButton" type="button" onClick={toggleVoice}>{voiceEnabled ? 'Mute' : 'Enable'}</button>
              <button className="secondaryButton" type="button" onClick={() => speak(voicePreview)} disabled={!voiceEnabled}>Preview Voice</button>
              <button className="secondaryButton" type="button" onClick={stopVoice}>Stop</button>
            </div>
          </div>
          <textarea className="xlInput" value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={handleChatComposerKeyDown} placeholder="Ask the platform to inspect, explain, run, or coordinate work." />
          <button className="primaryButton" type="button" disabled={!canSendChat} onClick={sendChat}>
            <CarbonIcon path="actions/document-send-symbolic.svg" label="Send" />
            {mutation.isPending ? 'Sending' : 'Send'}
          </button>
          {mutation.error ? <div className="errorBanner">{errorText(mutation.error)}</div> : null}
        </div>
        <div className="conversationPanel">
          <div className="transcriptToolbar" aria-label="Chat transcript controls">
            <div>
              <span>{messages.length} message{messages.length === 1 ? '' : 's'}</span>
              <strong>{lastAssistant?.model || selectedModelCard?.display_name || 'No response yet'}</strong>
              <small>{transcriptStatus}</small>
            </div>
            <div className="transcriptActions">
              <button className="secondaryButton" type="button" disabled={!messages.length} onClick={() => void copyTranscript()}>Copy</button>
              <button className="secondaryButton" type="button" disabled={!messages.length} onClick={downloadTranscript}>Download</button>
              <button className="secondaryButton" type="button" disabled={!messages.length} onClick={() => void copyChatBrief()}>Copy Brief</button>
              <button className="secondaryButton" type="button" disabled={!messages.length} onClick={downloadChatBrief}>Download Brief</button>
              <button className="secondaryButton" type="button" disabled={!messages.length} onClick={clearTranscript}>Clear</button>
            </div>
          </div>
          {mutation.isPending ? <StatusPanel tone="loading" title="Waiting for model response" detail={selectedModelCard?.display_name || selectedModel} /> : null}
          {messages.length ? messages.map((message, index) => (
            <div className={`messageRow ${message.role}`} key={`${message.role}-${index}`} style={{ ['--message-accent' as string]: message.accent || undefined }}>
              <span>{message.role}{message.model ? ` · ${message.model}` : ''}{message.company ? ` · ${message.company}` : ''}</span>
              <p>{message.content}</p>
            </div>
          )) : <div className="emptyState">No conversation yet.</div>}
        </div>
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
  const models = useTextModels(code.data?.models);
  const defaults = code.data?.defaults || {};
  const restoredWorkspace = useMemo(loadCodeWorkspace, []);
  const [sessionName, setSessionName] = useState(restoredWorkspace.sessionName || asText(defaults.default_name, 'matts-code'));
  const [projectDir, setProjectDir] = useState(restoredWorkspace.projectDir || asText(defaults.default_project_dir, ''));
  const [model, setModel] = useState(restoredWorkspace.model);
  const [prompt, setPrompt] = useState(restoredWorkspace.prompt);
  const [actions, setActions] = useState<CodeActionRecord[]>(restoredWorkspace.actions);
  const [outputStatus, setOutputStatus] = useState(restoredWorkspace.actions.length ? 'Restored' : 'Ready');
  const [copiedActionId, setCopiedActionId] = useState('');
  const [attachments, setAttachments] = useState<CodeAttachment[]>(restoredWorkspace.attachments);
  const [attachmentError, setAttachmentError] = useState('');
  const fileInput = useRef<HTMLInputElement | null>(null);
  const selectedModel = model || asText(defaults.default_model, models[0]?.id || '');
  const hasCodeBrief = Boolean(actions.length || attachments.length);
  const codeBrief = useMemo(() => codeBriefMarkdown({ sessionName, projectDir, model: selectedModel, prompt, actions, attachments }), [actions, attachments, projectDir, prompt, selectedModel, sessionName]);
  useEffect(() => {
    saveCodeWorkspace({ sessionName, projectDir, model, prompt, actions, attachments });
  }, [sessionName, projectDir, model, prompt, actions, attachments]);
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
  const copyCodeBrief = async () => {
    if (!hasCodeBrief) return;
    try {
      await copyText(codeBrief);
      setOutputStatus('Brief copied');
    } catch {
      setOutputStatus('Brief copy failed');
    }
  };
  const downloadCodeBrief = () => {
    if (!hasCodeBrief) return;
    const blob = new Blob([codeBrief], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `mde-llm-proxy-code-brief-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    setOutputStatus('Brief downloaded');
  };
  const startMutation = useMutation({
    mutationFn: () => startCodeSession({ name: sessionName, project_dir: projectDir, model: selectedModel, permission_mode: 'bypassPermissions', run_mode: 'interactive' }),
    onSuccess: (payload) => {
      addAction('start', payload);
      queryClient.invalidateQueries({ queryKey: ['code-payload'] });
    }
  });
  const sendMutation = useMutation({
    mutationFn: () => sendCodeSession({ name: sessionName, text: prompt, enter: true }),
    onSuccess: (payload) => {
      addAction('send', payload, prompt);
      setPrompt('');
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
  const sendCodeToTmux = () => {
    if (!canSendCode) return;
    sendMutation.mutate();
  };
  const handleCodeComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || (!event.ctrlKey && !event.metaKey) || event.nativeEvent.isComposing) return;
    if (!canSendCode) return;
    event.preventDefault();
    sendMutation.mutate();
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
  return (
    <section className="heroWorkspace codeHero" onDrop={drop} onDragOver={(event) => event.preventDefault()}>
      <div className="heroHeader">
        <div>
          <p className="eyebrow">Repository + Terminal + Vision Input</p>
          <h1>Code</h1>
          <p>Start coding sessions, send terminal input, and attach screenshots/images for direct model review.</p>
        </div>
        <button className="secondaryButton" type="button" onClick={() => fileInput.current?.click()}>
          <CarbonIcon path="actions/document-open-symbolic.svg" label="Attach" />
          Attach Image
        </button>
      </div>
      <input ref={fileInput} type="file" hidden multiple accept="image/png,image/jpeg,image/webp,image/gif" onChange={(event: ChangeEvent<HTMLInputElement>) => event.target.files && void handleFiles(event.target.files)} />
      <div className="workspaceGrid twoColumn">
        <div className="composerPanel">
          {code.isLoading ? <StatusPanel tone="loading" title="Loading code workspace" /> : null}
          {code.error ? <StatusPanel tone="error" title="Code API unavailable" detail={errorText(code.error)} /> : null}
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
          <div className="buttonRow">
            <button className="secondaryButton" type="button" onClick={() => startMutation.mutate()} disabled={startMutation.isPending}>Start Session</button>
            <button className="secondaryButton" type="button" onClick={sendCodeToTmux} disabled={!canSendCode}>Send To Tmux</button>
            <button className="primaryButton" type="button" onClick={() => reviewMutation.mutate()} disabled={!attachments.length || reviewMutation.isPending}>Ask Model To Review Image</button>
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
                <summary>Raw details</summary>
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
  const [researchResult, setResearchResult] = useState<ResearchResultPayload | null>(restoredWorkspace.result);
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
    onSuccess: (result) => setResearchResult(result),
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
  const researchBrief = useMemo(() => {
    if (!researchResult) return '';
    const results = researchResult.results || [];
    return researchBriefMarkdown(researchResult, results, researchBriefMetrics(researchResult, results));
  }, [researchResult]);
  useEffect(() => {
    saveResearchWorkspace({ query, mode, engineSelectionMode, selectedEngines: engineSelectionMode === 'custom' ? activeEngineIds : [], result: researchResult });
  }, [query, mode, engineSelectionMode, activeEngineIds, researchResult]);
  return (
    <section className="heroWorkspace researchHero">
      <div className="heroHeader">
        <div>
          <p className="eyebrow">Search + Evidence + Synthesis</p>
          <h1>Research</h1>
          <p>Wide search-style results with search engine badges, evidence workspace, and model-backed synthesis.</p>
        </div>
      </div>
      <div className="searchLine">
        <input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={handleResearchSearchKeyDown} placeholder="Search across configured engines" />
        <select value={mode} onChange={(event) => setMode(event.target.value)}>{(payload.data?.modes || ['Balanced']).map((item) => <option key={item}>{item}</option>)}</select>
        <button className="primaryButton" type="button" onClick={submitResearchSearch} disabled={!canRunResearchSearch}>Search</button>
      </div>
      <ResearchBriefActions brief={researchBrief} disabled={!researchResult} className="researchBriefDock" />
      <ResearchTeamPanel strategy={researchResult?.model_strategy || payload.data?.model_strategy} />
      {payload.isLoading ? <StatusPanel tone="loading" title="Loading research engines" /> : null}
      {payload.error ? <StatusPanel tone="error" title="Research setup unavailable" detail={errorText(payload.error)} /> : null}
      {searchMutation.isPending ? <StatusPanel tone="loading" title="Searching configured engines" detail={query} /> : null}
      {searchMutation.error ? <StatusPanel tone="error" title="Research search failed" detail={errorText(searchMutation.error)} /> : null}
      {customSelectionEmpty ? <StatusPanel tone="neutral" title="Select at least one research engine" detail="Use Select All or turn on one source before searching." /> : null}
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
      {sourceClasses.length ? (
        <div className="sourceClassStrip" aria-label="Research source classes">
          {sourceClasses.map((source) => (
            <span className={`sourceClassChip kind-${source.kind.replace(/[^a-z0-9_-]/gi, '-')}`} key={source.id} title={source.detail || source.name}>
              <strong>{source.label || source.name}</strong>
              <small>{readableStatus(source.status)} · {readableStatus(source.kind)}</small>
            </span>
          ))}
        </div>
      ) : null}
      {!payload.isLoading && !payload.error && !engines.length ? <StatusPanel title="No research engines reported" detail="Configure external search credentials or local RAG to populate search sources." /> : null}
      {researchResult ? <ResearchEvidence data={researchResult} /> : null}
    </section>
  );
}

export function CreatePage() {
  const create = useQuery({ queryKey: ['create-payload'], queryFn: getCreatePayload });
  const mood = useCreateMood();
  const restoredWorkspace = useMemo(loadCreateWorkspace, []);
  const [mode, setMode] = useState(restoredWorkspace.mode);
  const [prompt, setPrompt] = useState(restoredWorkspace.prompt);
  const [result, setResult] = useState(restoredWorkspace.result);
  const [imageResult, setImageResult] = useState<{ images: CreateImageResult[]; raw: string } | null>(restoredWorkspace.imageResult);
  const [researchResult, setResearchResult] = useState<ResearchResultPayload | null>(restoredWorkspace.researchResult);
  const [researchSourceMode, setResearchSourceMode] = useState<CreateResearchSourceMode>(restoredWorkspace.researchSourceMode);
  const [historyItems, setHistoryItems] = useState<CreateHistoryItem[]>(restoredWorkspace.historyItems);
  const [historyStatus, setHistoryStatus] = useState(restoredWorkspace.historyItems.length ? 'Restored' : 'Ready');
  const createResearchSourceClasses = create.data?.research_source_classes || [];
  const createRequiredSourceIds = useMemo(() => createResearchSourceClasses.map((source) => source.engine_id || source.id).filter(Boolean).slice(0, RESEARCH_SELECTED_ENGINE_LIMIT), [createResearchSourceClasses]);
  const hasCreateBrief = hasCreateBriefState({ mode, prompt, result, imageResult, researchResult, researchSourceMode, historyItems });
  const createBrief = useMemo(() => createBriefMarkdown({ mode, prompt, result, imageResult, researchResult, researchSourceMode, historyItems }), [mode, prompt, result, imageResult, researchResult, researchSourceMode, historyItems]);
  const [briefStatus, setBriefStatus] = useState(hasCreateBriefState(restoredWorkspace) ? 'Brief Ready' : 'No brief');
  const addHistory = (item: Omit<CreateHistoryItem, 'id' | 'createdAt'>) => {
    const now = new Date();
    setHistoryItems((current) => [{
      ...item,
      id: `${now.getTime()}-${item.mode}`,
      createdAt: now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }),
    }, ...current].slice(0, 6));
    setHistoryStatus('Updated');
  };
  const reuseHistory = (item: CreateHistoryItem) => {
    const nextMode = CREATE_MODES.includes(item.mode) ? item.mode : 'Chat';
    setMode(nextMode);
    setPrompt(item.prompt);
    setResearchSourceMode(item.researchSourceMode || 'all');
    if (nextMode === 'Research') {
      setResult('');
      setImageResult(null);
      setResearchResult(item.researchResult || null);
    } else if (nextMode === 'Image') {
      setResult('');
      setResearchResult(null);
      setImageResult(item.imageResult || null);
    } else {
      setResult(item.result || item.summary || '');
      setResearchResult(null);
      setImageResult(null);
    }
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
  const copyCreateBrief = async () => {
    if (!hasCreateBrief) return;
    try {
      await copyText(createBrief);
      setBriefStatus('Brief copied');
    } catch {
      setBriefStatus('Brief copy failed');
    }
  };
  const downloadCreateBrief = () => {
    if (!hasCreateBrief) return;
    const blob = new Blob([createBrief], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `mde-llm-proxy-create-brief-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    setBriefStatus('Brief downloaded');
  };
  const chatMutation = useMutation({
    mutationFn: () => runChat({ messages: [{ role: 'user', content: prompt }] }),
    onSuccess: (payload) => {
      const text = responseText(payload);
      setImageResult(null);
      setResearchResult(null);
      setResult(text);
      addHistory({ mode: 'Chat', prompt, summary: text.slice(0, 180) || 'Chat response received.', result: text });
    }
  });
  const researchMutation = useMutation({
    mutationFn: () => runResearchSearch({
      query: prompt,
      mode: 'Balanced',
      ...(researchSourceMode === 'required' && createRequiredSourceIds.length ? { engines: createRequiredSourceIds } : {})
    }),
    onSuccess: (payload) => {
      setImageResult(null);
      setResult('');
      setResearchResult(payload);
      const evidence = numeric(payload.synthesis?.evidence_count) || payload.results.length;
      addHistory({ mode: 'Research', prompt, summary: `${payload.synthesis?.summary || 'Research synthesis received.'} · ${evidence} evidence item${evidence === 1 ? '' : 's'}`, researchResult: payload, researchSourceMode });
    }
  });
  const imageMutation = useMutation({
    mutationFn: () => runCreateImages({ prompt, model: create.data?.image_models?.[0]?.id }),
    onSuccess: (payload) => {
      const normalized = normalizeImageResults(payload);
      setResearchResult(null);
      setResult('');
      setImageResult(normalized);
      addHistory({ mode: 'Image', prompt, summary: `${normalized.images.length} image output${normalized.images.length === 1 ? '' : 's'}${normalized.images[0]?.model ? ` · ${normalized.images[0].model}` : ''}`, thumbnail: normalized.images[0]?.src, imageResult: normalized });
    }
  });
  const pending = chatMutation.isPending || researchMutation.isPending || imageMutation.isPending;
  const canSubmit = Boolean(prompt.trim()) && !pending;
  const submit = () => {
    if (!canSubmit) return;
    if (mode === 'Research') researchMutation.mutate();
    else if (mode === 'Image') imageMutation.mutate();
    else chatMutation.mutate();
  };
  const handleCreateComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || (!event.ctrlKey && !event.metaKey) || !canSubmit) return;
    event.preventDefault();
    submit();
  };
  useEffect(() => {
    saveCreateWorkspace({ mode, prompt, result, imageResult, researchResult, researchSourceMode, historyItems });
  }, [mode, prompt, result, imageResult, researchResult, researchSourceMode, historyItems]);
  useEffect(() => {
    setBriefStatus(hasCreateBrief ? 'Brief Ready' : 'No brief');
  }, [createBrief, hasCreateBrief]);
  const wallpaper = String(create.data?.wallpaper?.remote_url || create.data?.wallpaper?.url || '');
  return (
    <section className="heroWorkspace createHero" style={{ backgroundImage: wallpaper ? `linear-gradient(180deg, rgba(0,0,0,.34), rgba(0,0,0,.72)), url(${wallpaper})` : undefined }}>
      <div className="createAtmosphere" aria-hidden="true"><span /><span /><span /></div>
      <div className="createCenter">
        <p className="eyebrow">Creative Studio</p>
        <h1>Create</h1>
        <div id="v2-create-mood" className="createMood" aria-label="Create mood">
          <span>{mood.label}</span>
          <strong>{mood.time}</strong>
          <span>{mood.weather}</span>
          <span>{mood.tone}</span>
        </div>
        <div className="modeSwitch">{(create.data?.modes || ['Chat', 'Research', 'Image']).map((item) => <button className={mode === item ? 'active' : ''} key={item} type="button" onClick={() => setMode(item)}>{item}</button>)}</div>
        {mode === 'Research' && createRequiredSourceIds.length ? (
          <div className="createSourceControls" aria-label="Create Research source mode">
            <span>{researchSourceMode === 'required' ? `${createRequiredSourceIds.length} required sources` : 'All sources'}</span>
            <button className={`secondaryButton ${researchSourceMode === 'all' ? 'active' : ''}`} type="button" aria-pressed={researchSourceMode === 'all'} onClick={() => setResearchSourceMode('all')}>All Sources</button>
            <button className={`secondaryButton ${researchSourceMode === 'required' ? 'active' : ''}`} type="button" aria-pressed={researchSourceMode === 'required'} onClick={() => setResearchSourceMode('required')}>Required Sources</button>
          </div>
        ) : null}
        {create.isLoading ? <StatusPanel tone="loading" title="Loading creative workspace" /> : null}
        {create.error ? <StatusPanel tone="error" title="Create setup unavailable" detail={errorText(create.error)} /> : null}
        {pending ? <StatusPanel tone="loading" title={`${mode} request running`} detail={prompt} /> : null}
        {chatMutation.error ? <StatusPanel tone="error" title="Chat request failed" detail={errorText(chatMutation.error)} /> : null}
        {researchMutation.error ? <StatusPanel tone="error" title="Research request failed" detail={errorText(researchMutation.error)} /> : null}
        {imageMutation.error ? <StatusPanel tone="error" title="Image request failed" detail={errorText(imageMutation.error)} /> : null}
        <div className="createPrompt">
          <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={handleCreateComposerKeyDown} placeholder={mode === 'Research' ? 'Search line' : 'Describe what to create'} />
          <button className="primaryButton" type="button" onClick={submit} disabled={!canSubmit}>Run</button>
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
        {researchResult && mode === 'Research' ? <div className="createResult"><ResearchEvidence data={researchResult} compact /></div> : null}
        {imageResult && mode === 'Image' ? (
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
        {result ? <div className="createResult"><span>{mode} result</span><pre>{result}</pre></div> : null}
      </div>
    </section>
  );
}

export function ModelsPage() {
  const queryClient = useQueryClient();
  const models = useQuery({ queryKey: ['models'], queryFn: getModels });
  const whatsNew = useQuery({ queryKey: ['whats-new'], queryFn: getWhatsNew });
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
  const spotlight = cards.find((model) => model.route_enabled) || cards[0];
  const inspectedModel = allCards.find((model) => model.id === inspectedModelId) || spotlight;
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
        {spotlight ? (
          <div className="modelSpotlight" style={{ ['--accent' as string]: spotlight.nation_palette?.accent || '#0f62fe', ['--surface' as string]: spotlight.nation_palette?.surface || '#edf5ff' }}>
            <ModelLogo model={spotlight} size="large" />
            <div>
              <span>Spotlight</span>
              <strong>{spotlight.display_name}</strong>
              <p>{spotlight.use_case}</p>
            </div>
            <div className="modelSpotlightFacts">
              <span>{spotlight.company}</span>
              <span>{spotlight.training_nation}</span>
              <span>{spotlight.cost_label}</span>
              <span>{spotlight.context_window.toLocaleString()} ctx</span>
              <span>{spotlight.route_enabled ? 'Routable' : spotlight.access_status}</span>
              <button className="secondaryButton" type="button" onClick={() => setInspectedModelId(spotlight.id)}><CarbonIcon path="apps/information.svg" label="Inspect" />Inspect</button>
              <button className="secondaryButton" type="button" onClick={() => toggleCompare(spotlight.id)}><CarbonIcon path="apps/compare.svg" label="Compare" />{compareIds.includes(spotlight.id) ? 'Remove Compare' : 'Compare'}</button>
            </div>
          </div>
        ) : null}
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
      <div className="modelGrid">
        {cards.map((model) => (
          <article className="modelShowcaseCard" key={model.id} style={{ ['--accent' as string]: model.nation_palette?.accent || '#0f62fe', ['--secondary' as string]: model.nation_palette?.secondary || '#da1e28', ['--surface' as string]: model.nation_palette?.surface || '#f4f4f4' }}>
            <div className="modelCardTop">
              <ModelLogo model={model} size="large" />
              <span className={`statusPill ${model.route_enabled ? 'ok' : 'warn'}`}>{model.route_enabled ? 'Routable' : model.access_status}</span>
            </div>
            <h3>{model.display_name}</h3>
            <p>{model.use_case}</p>
            <div className="modelFacts">
              <span>{model.company}</span>
              <span>{model.training_nation}</span>
              <span>{model.type}</span>
              <span>{model.cost_label}</span>
            </div>
            <div className="modelCardActions">
              <button className="secondaryButton" type="button" onClick={() => setInspectedModelId(model.id)} aria-label={`Inspect ${model.display_name}`}><CarbonIcon path="apps/information.svg" label="Inspect" />Inspect</button>
              <button className="secondaryButton" type="button" onClick={() => toggleCompare(model.id)} aria-label={`${compareIds.includes(model.id) ? 'Remove' : 'Compare'} ${model.display_name}`}><CarbonIcon path="apps/compare.svg" label="Compare" />{compareIds.includes(model.id) ? 'Remove' : 'Compare'}</button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function clientId(): string {
  return `advanced-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

const ADVANCED_TAB_SESSION_KEY = V2_WORKSPACE_SESSION_KEYS.advancedTab;
const ADVANCED_TABS = ['console', 'run', 'observe', 'operate', 'tui'];

function normalizeAdvancedTab(value: unknown): string {
  return typeof value === 'string' && ADVANCED_TABS.includes(value) ? value : 'console';
}

function loadAdvancedTab(): string {
  if (typeof window === 'undefined') return 'console';
  try {
    return normalizeAdvancedTab(window.sessionStorage.getItem(ADVANCED_TAB_SESSION_KEY));
  } catch {
    return 'console';
  }
}

function saveAdvancedTab(tab: string): void {
  if (typeof window === 'undefined') return;
  try {
    const normalized = normalizeAdvancedTab(tab);
    if (normalized === 'console') {
      window.sessionStorage.removeItem(ADVANCED_TAB_SESSION_KEY);
      return;
    }
    window.sessionStorage.setItem(ADVANCED_TAB_SESSION_KEY, normalized);
  } catch {
    // Advanced remains usable even when browser storage is unavailable.
  }
}

export function AdvancedPage() {
  const [tab, setTab] = useState(loadAdvancedTab);
  const [controller, setController] = useState(false);
  const client = useMemo(clientId, []);
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
  return (
    <section className="heroWorkspace advancedHero">
      <div className="heroHeader">
        <div>
          <p className="eyebrow">Owner/Admin Operations</p>
          <h1>Advanced</h1>
          <p>Operational dashboards, reporting, governance, TUI bridge, evals, automation, and raw diagnostics.</p>
        </div>
      </div>
      <div className="advancedTabs">
        {ADVANCED_TABS.map((item) => <button className={tab === item ? 'active' : ''} key={item} type="button" onClick={() => setTab(item)}>{item}</button>)}
      </div>
      <Suspense fallback={<AdvancedLoading label={tab} />}>
        {tab === 'console' ? <ConsolePage /> : null}
        {tab === 'run' ? <RunPage /> : null}
        {tab === 'observe' ? <ObservePage /> : null}
        {tab === 'operate' ? <OperatePage /> : null}
        {tab === 'tui' ? (
          <div className="advancedPanel">
            <button className="secondaryButton" type="button" onClick={() => setController(!controller)}>{controller ? 'Release Local Control' : 'Take Local Control'}</button>
            <TuiTerminal clientId={client} controller={controller} />
          </div>
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
        {models.slice(0, 3).map((model) => <ModelMiniCard key={model.id} model={model} />)}
      </div>
    </div>
  );
}
