import { CSSProperties, KeyboardEvent, MouseEvent, ReactNode, useEffect, useId, useRef, useState } from 'react';
import cnFlag from 'flag-icons/flags/1x1/cn.svg';
import usFlag from 'flag-icons/flags/1x1/us.svg';
import frFlag from 'flag-icons/flags/1x1/fr.svg';
import ilFlag from 'flag-icons/flags/1x1/il.svg';
import gbFlag from 'flag-icons/flags/1x1/gb.svg';
import jpFlag from 'flag-icons/flags/1x1/jp.svg';
import krFlag from 'flag-icons/flags/1x1/kr.svg';
import deFlag from 'flag-icons/flags/1x1/de.svg';
import caFlag from 'flag-icons/flags/1x1/ca.svg';
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

type LocalBrandMark = { key: string; label: string; short: string; color?: string };

// Brand colors are the official simple-icons hex values (OpenAI/Microsoft are
// well-known brand colors); marks without one fall back to the platform blue.
const LOCAL_BRAND_MARKS: Record<string, LocalBrandMark> = {
  alibaba: { key: 'alibaba', label: 'Alibaba Cloud', short: 'ALI', color: '#FF6A00' },
  anthropic: { key: 'anthropic', label: 'Anthropic', short: 'ANT', color: '#191919' },
  arcee: { key: 'arcee', label: 'Arcee AI', short: 'ARC' },
  baai: { key: 'baai', label: 'BAAI', short: 'BAAI' },
  blackforest: { key: 'blackforest', label: 'Black Forest Labs', short: 'BFL' },
  deepseek: { key: 'deepseek', label: 'DeepSeek', short: 'DS', color: '#5786FE' },
  digitalocean: { key: 'digitalocean', label: 'DigitalOcean', short: 'DO', color: '#0080FF' },
  google: { key: 'google', label: 'Google', short: 'G', color: '#4285F4' },
  meta: { key: 'meta', label: 'Meta', short: 'META', color: '#0467DF' },
  microsoft: { key: 'microsoft', label: 'Microsoft', short: 'MS', color: '#0078D4' },
  minimax: { key: 'minimax', label: 'MiniMax', short: 'MINI', color: '#E73562' },
  mistral: { key: 'mistral', label: 'Mistral AI', short: 'M', color: '#FA520F' },
  moonshot: { key: 'moonshot', label: 'Moonshot AI', short: 'KIMI', color: '#000000' },
  nvidia: { key: 'nvidia', label: 'NVIDIA', short: 'NV', color: '#76B900' },
  openai: { key: 'openai', label: 'OpenAI', short: 'OAI', color: '#10A37F' },
  stability: { key: 'stability', label: 'Stability AI', short: 'SD' },
  xiaomi: { key: 'xiaomi', label: 'Xiaomi', short: 'MI', color: '#FF6900' },
  zhipu: { key: 'zhipu', label: 'Zhipu AI', short: 'GLM' },
};

export function modelBrandColor(model: ModelCard): string {
  return localBrandMark(model)?.color || '#0f62fe';
}

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

const NATION_FLAG_ASSETS: Record<string, string> = {
  'china': cnFlag,
  'united states': usFlag,
  'usa': usFlag,
  'france': frFlag,
  'israel': ilFlag,
  'united kingdom': gbFlag,
  'japan': jpFlag,
  'south korea': krFlag,
  'germany': deFlag,
  'canada': caFlag,
};

function nationFlagAsset(nation: string | undefined): string | undefined {
  return NATION_FLAG_ASSETS[String(nation || '').trim().toLowerCase()];
}

function FlagBadge({ nation }: { nation: string | undefined }) {
  const asset = nationFlagAsset(nation);
  const label = String(nation || '').trim() || 'Unknown training nation';
  return (
    <span className="mdlFlagBadge" title={label} aria-label={`Training nation: ${label}`}>
      {asset ? <img src={asset} alt="" /> : <span className="mdlFlagGlobe" aria-hidden="true">🌐</span>}
    </span>
  );
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
  const accent = modelBrandColor(model);
  const detailAction = onOpenDetail || openModelDetail;
  const bodyAction = onPrimary || detailAction;
  const infoGlyphNeeded = interactive && Boolean(onPrimary);
  const hasCorner = interactive && (showFavorite || infoGlyphNeeded || Boolean(trailing));
  const facts = effectiveSize === 'big'
    ? [modelStatusLabel(model), model.cost_label, model.context_window ? `${model.context_window.toLocaleString()} ctx` : '', model.type, modelHealthLabel(model)]
    : [modelStatusLabel(model), model.cost_label, modelHealthLabel(model)];
  const stop = (event: MouseEvent, action: () => void) => {
    event.stopPropagation();
    action();
  };
  return (
    <article
      className={['mdlCard', effectiveSize, active ? 'active' : '', hasCorner ? 'hasCorner' : ''].filter(Boolean).join(' ')}
      style={{ ['--mdl-accent' as string]: accent } as CSSProperties}
      data-testid={testId || 'model-identity-card'}
      data-model-id={model.id}
    >
      <CardBody
        interactive={interactive}
        onClick={() => bodyAction?.(model)}
        ariaLabel={onPrimary ? `Open conversation with ${model.display_name}` : `Inspect ${model.display_name}`}
      >
        <span className="mdlCardLogo">
          <ModelLogo model={model} size={effectiveSize === 'big' ? 'large' : undefined} />
          <FlagBadge nation={model.training_nation} />
        </span>
        <span className="mdlCardIdentity">
          <span className="mdlCardNameRow">
            <strong className="mdlCardName">{model.display_name}</strong>
            {model.is_new ? <span className="mdlCardSparkle" title="New in the last 7 days" role="img" aria-label="New model">✨</span> : null}
          </span>
          <small className="mdlCardByline">by {model.company || model.provider || 'Unknown'}{model.training_nation ? <> · {model.training_nation}</> : null}</small>
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

export function ModelCardSelect({ models, value, onChange, label = 'Model', allowClear = false }: { models: ModelCard[]; value: string; onChange: (value: string) => void; label?: string; allowClear?: boolean }) {
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [optionFilter, setOptionFilter] = useState('');
  const rootRef = useRef<HTMLDivElement | null>(null);
  const listId = useId();
  const optionId = (index: number) => `${listId}-opt-${index}`;
  const { favorites } = useModelFavorites();
  const query = optionFilter.trim().toLowerCase();
  const matching = query
    ? models.filter((model) => `${model.display_name} ${model.company} ${model.id}`.toLowerCase().includes(query))
    : models;
  const ordered = [...matching].sort((left, right) =>
    Number(favorites.includes(right.id)) - Number(favorites.includes(left.id))
    || Number(right.route_enabled) - Number(left.route_enabled)
    || left.display_name.localeCompare(right.display_name));
  const favoriteCount = ordered.filter((model) => favorites.includes(model.id)).length;
  // Favorites lead; the rest stays behind the More-models expander (V2-082 Q10)
  // unless searching, expanded, or there is nothing pinned to lead with.
  const collapsed = !query && !expanded && favoriteCount > 0;
  const visible = collapsed ? ordered.slice(0, favoriteCount) : ordered;
  const hiddenCount = ordered.length - visible.length;
  const selected = models.find((model) => model.id === value);
  useEffect(() => {
    if (!open) {
      setExpanded(false);
      setOptionFilter('');
      return;
    }
    setHighlighted(0);
    const onDocPointer = (event: Event) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocPointer);
    return () => document.removeEventListener('mousedown', onDocPointer);
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
        return visible.length ? (index + delta + visible.length) % visible.length : 0;
      });
      return;
    }
    if ((event.key === 'Enter' || event.key === ' ') && open) {
      event.preventDefault();
      const target = visible[highlighted];
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
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open && visible[highlighted] ? optionId(highlighted) : undefined}
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
      {allowClear && value ? (
        <button
          type="button"
          className="mdlSelectClear"
          aria-label={`Clear ${label}`}
          title="Clear selection"
          onClick={() => onChange('')}
        >
          <CarbonIcon path="actions/window-close-symbolic.svg" label="Clear" />
        </button>
      ) : null}
      {open ? (
        <div className="mdlSelectPopover">
          <input
            className="mdlSelectFilter"
            value={optionFilter}
            onChange={(event) => setOptionFilter(event.target.value)}
            placeholder="Filter models"
            aria-label={`Filter ${label} options`}
          />
          <div id={listId} className="mdlSelectListbox" role="listbox" aria-label={`${label} options`}>
            {visible.map((model, index) => (
              <div
                key={model.id}
                id={optionId(index)}
                role="option"
                aria-selected={model.id === selected?.id}
                className={['mdlSelectOption', index === highlighted ? 'highlighted' : ''].filter(Boolean).join(' ')}
                onMouseEnter={() => setHighlighted(index)}
                onClick={() => choose(model)}
              >
                <ModelIdentityCard model={model} size="small" interactive={false} showFavorite={false} testId="model-select-option" />
              </div>
            ))}
          </div>
          {collapsed && hiddenCount > 0 ? (
            <button type="button" className="mdlSelectMore" onClick={() => setExpanded(true)}>
              More models ({hiddenCount})…
            </button>
          ) : null}
          {!visible.length ? <div className="emptyState">No model matches.</div> : null}
        </div>
      ) : null}
    </div>
  );
}
