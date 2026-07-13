import { CSSProperties, KeyboardEvent, MouseEvent, ReactNode, useEffect, useRef, useState } from 'react';
import type { ModelCard } from '../api/v2';
import { useModelFavorites } from '../favorites';
import { readableStatus } from '../utils/format';

const iconBase = '/branding/Mackes-Carbon/scalable';

export function CarbonIcon({ path, label }: { path: string; label: string }) {
  return <img className="carbonIcon" src={`${iconBase}/${path}`} alt="" title={label} aria-hidden="true" />;
}

let loadedBrandMarkArt: Record<string, string> = {};
const brandMarkArtReady = import('../brandMarkArt')
  .then((module) => {
    loadedBrandMarkArt = module.BRAND_MARK_ART;
    return loadedBrandMarkArt;
  })
  .catch(() => loadedBrandMarkArt);

function useBrandMarkArt(): Record<string, string> {
  const [art, setArt] = useState(loadedBrandMarkArt);
  useEffect(() => {
    let active = true;
    void brandMarkArtReady.then((loaded) => {
      if (active) setArt(loaded);
    });
    return () => {
      active = false;
    };
  }, []);
  return art;
}

function modelLogoInitials(model: ModelCard): string {
  const source = [model.company, model.family, model.provider, model.display_name].find((item) => String(item || '').trim()) || 'AI';
  const words = String(source).replace(/[^a-zA-Z0-9]+/g, ' ').trim().split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? words.slice(0, 2).map((word) => word[0]).join('') : words[0]?.slice(0, 2);
  return (letters || 'AI').toUpperCase();
}

type LocalBrandMark = { key: string; label: string; short: string };

const LOCAL_BRAND_MARKS: Record<string, LocalBrandMark> = {
  alibaba: { key: 'alibaba', label: 'Alibaba Cloud', short: 'ALI' },
  anthropic: { key: 'anthropic', label: 'Anthropic', short: 'ANT' },
  arcee: { key: 'arcee', label: 'Arcee AI', short: 'ARC' },
  baai: { key: 'baai', label: 'BAAI', short: 'BAAI' },
  blackforest: { key: 'blackforest', label: 'Black Forest Labs', short: 'BFL' },
  deepseek: { key: 'deepseek', label: 'DeepSeek', short: 'DS' },
  digitalocean: { key: 'digitalocean', label: 'DigitalOcean', short: 'DO' },
  google: { key: 'google', label: 'Google', short: 'G' },
  meta: { key: 'meta', label: 'Meta', short: 'META' },
  microsoft: { key: 'microsoft', label: 'Microsoft', short: 'MS' },
  minimax: { key: 'minimax', label: 'MiniMax', short: 'MINI' },
  mistral: { key: 'mistral', label: 'Mistral AI', short: 'M' },
  moonshot: { key: 'moonshot', label: 'Moonshot AI', short: 'KIMI' },
  nvidia: { key: 'nvidia', label: 'NVIDIA', short: 'NV' },
  openai: { key: 'openai', label: 'OpenAI', short: 'OAI' },
  stability: { key: 'stability', label: 'Stability AI', short: 'SD' },
  xiaomi: { key: 'xiaomi', label: 'Xiaomi', short: 'MI' },
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
  const renderKey = model.artwork?.render?.key;
  if (renderKey && LOCAL_BRAND_MARKS[renderKey]) return LOCAL_BRAND_MARKS[renderKey];
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

export const V2_MODEL_DETAIL_EVENT = 'matts-v2-open-model-detail';

export function openModelDetail(model: ModelCard): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(V2_MODEL_DETAIL_EVENT, { detail: { model } }));
}

export function useBrandSvg(model: ModelCard): string | undefined {
  const brandMark = localBrandMark(model);
  const brandArt = useBrandMarkArt();
  return brandMark ? brandArt[brandMark.key] : undefined;
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

export function ModelLogo({ model, size }: { model: ModelCard; size?: 'large' | 'xl' }) {
  const logo = model.artwork?.logo || '';
  const brandMark = localBrandMark(model);
  const brandArt = useBrandMarkArt();
  const brandSvg = brandMark ? brandArt[brandMark.key] : undefined;
  const renderableLogo = !brandMark && canRenderArtworkLogo(logo);
  const [failedLogo, setFailedLogo] = useState(false);
  useEffect(() => setFailedLogo(false), [model.id, logo, renderableLogo]);
  const className = ['modelLogo', size].filter(Boolean).join(' ');
  const artworkState = brandSvg ? 'local-brand-svg' : brandMark ? 'local-brand-text' : renderableLogo && logo && !failedLogo ? 'public-logo' : logo ? 'attributed-initials' : 'generated-initials';
  return (
    <div className={className} data-artwork-state={artworkState} data-brand={brandMark?.key || ''} data-testid="model-logo" aria-label={`${model.display_name} model identity`}>
      {brandSvg && brandMark ? (
        <span className="modelBrandSvg" aria-hidden="true" title={brandMark.label} dangerouslySetInnerHTML={{ __html: brandSvg }} />
      ) : brandMark ? (
        <span className="modelBrandText" aria-hidden="true" title={brandMark.label}>{brandMark.short}</span>
      ) : renderableLogo && logo && !failedLogo ? (
        <img src={logo} alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailedLogo(true)} />
      ) : (
        <span aria-hidden="true">{modelLogoInitials(model)}</span>
      )}
    </div>
  );
}

const NATION_FLAGS: Record<string, string> = {
  'china': '🇨🇳',
  'united states': '🇺🇸',
  'usa': '🇺🇸',
  'france': '🇫🇷',
  'israel': '🇮🇱',
  'united kingdom': '🇬🇧',
  'japan': '🇯🇵',
  'south korea': '🇰🇷',
  'germany': '🇩🇪',
  'canada': '🇨🇦',
};

function nationFlag(nation: string | undefined): string {
  return NATION_FLAGS[String(nation || '').trim().toLowerCase()] || '';
}

export function useNarrowViewport(maxWidth = 620): boolean {
  const [narrow, setNarrow] = useState(() => typeof window !== 'undefined' && window.matchMedia(`(max-width: ${maxWidth}px)`).matches);
  useEffect(() => {
    const media = window.matchMedia(`(max-width: ${maxWidth}px)`);
    const onChange = () => setNarrow(media.matches);
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, [maxWidth]);
  return narrow;
}

export function modelStatusLabel(model: ModelCard): string {
  return model.route_enabled ? 'Routable' : readableStatus(model.access_status);
}

export function modelHealthLabel(model: ModelCard): string {
  return model.health?.grade ? `Health ${model.health.grade}` : 'Health —';
}

function modelHealthTitle(model: ModelCard): string {
  const health = model.health;
  if (!health?.measured || !health.grade) return 'No measured traffic yet for this model.';
  const success = health.success_rate === null || health.success_rate === undefined ? '' : `${(Number(health.success_rate) * 100).toFixed(1)}% ok`;
  const latency = health.p50_latency_ms === null || health.p50_latency_ms === undefined ? '' : `${health.p50_latency_ms}ms p50`;
  return [success, latency, `${health.requests} recent requests`].filter(Boolean).join(' · ');
}

export type ModelIdentityCardProps = {
  model: ModelCard;
  size?: 'big' | 'small';
  /**
   * Q16/Q19: card body opens detail everywhere except surfaces that pass
   * onPrimary (Chat contact selection); those get a separate info glyph.
   * interactive=false renders a passive card (dropdown options own the click).
   */
  onOpenDetail?: (model: ModelCard) => void;
  onPrimary?: (model: ModelCard) => void;
  interactive?: boolean;
  active?: boolean;
  compared?: boolean;
  onCompareToggle?: (model: ModelCard) => void;
  onUseInChat?: (model: ModelCard) => void;
  showFavorite?: boolean;
  trailing?: ReactNode;
  testId?: string;
};

function CardBody({ interactive, onClick, ariaLabel, children }: { interactive: boolean; onClick: () => void; ariaLabel: string; children: ReactNode }) {
  if (!interactive) return <span className="mdlCardBody passive">{children}</span>;
  return (
    <button type="button" className="mdlCardBody" onClick={onClick} aria-label={ariaLabel}>
      {children}
    </button>
  );
}

export function ModelIdentityCard({
  model,
  size = 'small',
  onOpenDetail,
  onPrimary,
  interactive = true,
  active = false,
  compared = false,
  onCompareToggle,
  onUseInChat,
  showFavorite = true,
  trailing,
  testId,
}: ModelIdentityCardProps) {
  const narrow = useNarrowViewport();
  const effectiveSize = size === 'big' && narrow ? 'small' : size;
  const { favorites, toggleFavorite } = useModelFavorites();
  const favorite = favorites.includes(model.id);
  const accent = model.nation_palette?.accent || '#0f62fe';
  const flag = nationFlag(model.training_nation);
  const detailAction = onOpenDetail || openModelDetail;
  const bodyAction = onPrimary || detailAction;
  const infoGlyphNeeded = interactive && Boolean(onPrimary);
  const facts = effectiveSize === 'big'
    ? [modelStatusLabel(model), model.cost_label, model.context_window ? `${model.context_window.toLocaleString()} ctx` : '', model.type, modelHealthLabel(model)]
    : [modelStatusLabel(model), model.cost_label, modelHealthLabel(model)];
  const stop = (event: MouseEvent, action: () => void) => {
    event.stopPropagation();
    action();
  };
  return (
    <article
      className={['mdlCard', effectiveSize, active ? 'active' : ''].filter(Boolean).join(' ')}
      style={{ ['--mdl-accent' as string]: accent } as CSSProperties}
      data-testid={testId || 'model-identity-card'}
      data-model-id={model.id}
    >
      <CardBody
        interactive={interactive}
        onClick={() => bodyAction?.(model)}
        ariaLabel={onPrimary ? `Open conversation with ${model.display_name}` : `Inspect ${model.display_name}`}
      >
        <span className="mdlCardLogo"><ModelLogo model={model} size={effectiveSize === 'big' ? 'large' : undefined} /></span>
        <span className="mdlCardIdentity">
          <strong className="mdlCardName">
            {model.display_name}
            {model.is_new ? <span className="mdlCardSparkle" title="New in the last 7 days" aria-label="New model">✨</span> : null}
          </strong>
          <small className="mdlCardByline">by {model.company || model.provider || 'Unknown'}{model.training_nation ? <> · {flag ? `${flag} ` : ''}{model.training_nation}</> : null}</small>
          {effectiveSize === 'big' && model.use_case ? <span className="mdlCardBlurb">{model.use_case}</span> : null}
          <span className="mdlCardFacts">
            {facts.filter(Boolean).map((fact, index) => (
              <span key={index} title={String(fact).startsWith('Health') ? modelHealthTitle(model) : undefined}>{fact}</span>
            ))}
          </span>
        </span>
      </CardBody>
      <span className="mdlCardCorner">
        {showFavorite && interactive ? (
          <button
            type="button"
            className={`mdlCardStar ${favorite ? 'active' : ''}`}
            aria-pressed={favorite}
            aria-label={favorite ? `Remove ${model.display_name} from favorites` : `Add ${model.display_name} to favorites`}
            title={favorite ? 'Remove favorite' : 'Add favorite'}
            onClick={(event) => stop(event, () => toggleFavorite(model.id))}
          >
            {favorite ? '★' : '☆'}
          </button>
        ) : null}
        {infoGlyphNeeded ? (
          <button
            type="button"
            className="mdlCardInfo"
            aria-label={`Model details for ${model.display_name}`}
            title="Model details"
            onClick={(event) => stop(event, () => detailAction(model))}
          >
            <CarbonIcon path="apps/information.svg" label="Details" />
          </button>
        ) : null}
        {trailing}
      </span>
      {effectiveSize === 'big' && (onCompareToggle || onUseInChat) ? (
        <span className="mdlCardActions">
          {onCompareToggle ? (
            <button type="button" className="secondaryButton" onClick={(event) => stop(event, () => onCompareToggle(model))}>
              <CarbonIcon path="apps/compare.svg" label="Compare" />
              {compared ? 'Remove Compare' : 'Compare'}
            </button>
          ) : null}
          {onUseInChat ? (
            <button type="button" className="secondaryButton" onClick={(event) => stop(event, () => onUseInChat(model))}>
              <CarbonIcon path="actions/call-start-symbolic.svg" label="Chat" />
              Use in Chat
            </button>
          ) : null}
        </span>
      ) : null}
    </article>
  );
}

export function ModelCardSelect({ models, value, onChange, label = 'Model' }: { models: ModelCard[]; value: string; onChange: (value: string) => void; label?: string }) {
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const { favorites } = useModelFavorites();
  const ordered = [...models].sort((left, right) => Number(favorites.includes(right.id)) - Number(favorites.includes(left.id)));
  const selected = models.find((model) => model.id === value) || models[0];
  useEffect(() => {
    if (!open) return;
    setHighlighted(Math.max(0, ordered.findIndex((model) => model.id === (selected?.id || value))));
    const onDocPointer = (event: Event) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocPointer);
    return () => document.removeEventListener('mousedown', onDocPointer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const choose = (model: ModelCard) => {
    onChange(model.id);
    setOpen(false);
  };
  const onTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'Escape') {
      setOpen(false);
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      setHighlighted((index) => {
        const delta = event.key === 'ArrowDown' ? 1 : -1;
        return (index + delta + ordered.length) % ordered.length;
      });
      return;
    }
    if ((event.key === 'Enter' || event.key === ' ') && open) {
      event.preventDefault();
      const target = ordered[highlighted];
      if (target) choose(target);
    }
  };
  return (
    <div className="field mdlSelectField" ref={rootRef}>
      <span>{label}</span>
      <button
        type="button"
        className="mdlSelectTrigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={onTriggerKeyDown}
      >
        {selected ? (
          <>
            <strong>{selected.display_name}</strong>
            <small>{modelStatusLabel(selected)} · {modelHealthLabel(selected)}</small>
          </>
        ) : 'Select model'}
      </button>
      {open ? (
        <div className="mdlSelectPopover" role="listbox" aria-label={`${label} options`}>
          {ordered.map((model, index) => (
            <div
              key={model.id}
              role="option"
              aria-selected={model.id === selected?.id}
              className={['mdlSelectOption', index === highlighted ? 'highlighted' : ''].filter(Boolean).join(' ')}
              onMouseEnter={() => setHighlighted(index)}
            >
              <ModelIdentityCard model={model} size="small" onPrimary={choose} testId="model-select-option" />
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
