import { consoleAuthHeaders, withConsoleToken } from './auth';
import { responseJsonOrThrow } from './errors';

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(withConsoleToken(path), {
    ...init,
    headers: {
      'content-type': 'application/json',
      ...consoleAuthHeaders(),
      ...(init?.headers || {})
    }
  });
  return responseJsonOrThrow<T>(response);
}

export type ModelCard = {
  id: string;
  display_name: string;
  type: string;
  provider: string;
  company: string;
  family: string;
  training_nation: string;
  route_enabled: boolean;
  enabled: boolean;
  access_status: string;
  cost_label: string;
  context_window: number;
  max_output_tokens: number;
  is_new: boolean;
  use_case: string;
  artwork: {
    logo?: string;
    background?: string;
    brand_url?: string;
    render?: {
      mode?: string;
      key?: string;
      label?: string;
    };
    policy_notes?: string;
    sources?: Array<{
      kind?: string;
      url?: string;
      source?: string;
      source_url?: string;
      usage_notes?: string;
    }>;
  };
  nation_palette: { accent: string; secondary: string; surface: string; text: string; name: string };
};

export type ModelsPayload = {
  generated_at: number;
  registry: Record<string, unknown>;
  summary: Record<string, unknown>;
  models: ModelCard[];
  palettes: Record<string, Record<string, string>>;
  artwork_policy: Record<string, unknown>;
};

export type WhatsNewPayload = {
  generated_at: number;
  title: string;
  summary: Record<string, number>;
  new_models: ModelCard[];
  attention: ModelCard[];
  digitalocean: {
    catalog: Record<string, unknown>;
    links: Array<{ label: string; url: string; category: string }>;
    raw: Record<string, unknown>;
  };
};

export type ChatVoiceProfile = {
  mode: string;
  style: string;
  enabled_by_default: boolean;
  max_chars: number;
  preview: string;
};

export type ChatPayload = {
  models: ModelCard[];
  default_model: string;
  voice: ChatVoiceProfile;
};

export type CodeAttachment = {
  id: string;
  session_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  width: number;
  height: number;
  sha256: string;
  created_at: number;
  actor_id: string;
  preview_url?: string;
};

export type CodePayload = {
  defaults: Record<string, unknown>;
  sessions: Array<Record<string, unknown>>;
  models: ModelCard[];
  attachment_policy: Record<string, unknown>;
};

export type ResearchPayload = {
  engines: Array<{
    id: string;
    name: string;
    status: string;
    kind: string;
    configured?: boolean;
    requires_credentials?: boolean;
    detail?: string;
    setup_env?: string[];
    run_status?: string;
    result_count?: number;
    latency_ms?: number;
  }>;
  source_classes?: Array<{
    id: string;
    engine_id: string;
    label: string;
    name: string;
    kind: string;
    status: string;
    detail?: string;
    configured?: boolean;
    requires_credentials?: boolean;
  }>;
  modes: string[];
  model_strategy?: ResearchModelStrategy;
  generated_at: number;
};

export type ResearchModelRole = {
  role: string;
  label: string;
  focus: string;
  status: string;
  model_id?: string;
  display_name?: string;
  company?: string;
  family?: string;
  training_nation?: string;
  cost_label?: string;
  max_text_price_usd?: number;
  context_window?: number;
  recommendation?: string;
  fast_response?: {
    eligible?: boolean;
    basis?: string;
    latency_ms?: number;
    detail?: string;
  };
};

export type ResearchModelStrategy = {
  policy: {
    max_model_price_usd?: number;
    price_metric?: string;
    comparison?: string;
    fast_max_latency_ms?: number;
    fast_response_required?: boolean;
    llm_calls_enabled?: boolean;
  };
  candidate_count?: number;
  analysts: ResearchModelRole[];
  coordinator: ResearchModelRole;
};

export type ResearchModelOutput = ResearchModelRole & {
  text: string;
};

export type ResearchSourceCoverage = {
  id: string;
  engine_id: string;
  label: string;
  name: string;
  kind: string;
  required: boolean;
  status: string;
  result_count: number;
  usable_count: number;
  detail: string;
};

export type ResearchEvidence = {
  id: string;
  evidence_id: string;
  engine: string;
  engine_name: string;
  title: string;
  url: string;
  snippet: string;
  published_at: string;
  source: string;
  status: string;
  kind: string;
  source_type?: string;
  score: number;
  relevance_score?: number;
  position: number;
  citation: string;
  source_label?: string;
  metadata?: Record<string, unknown>;
  path?: string;
  chunk?: number;
  collection_id?: string;
  thumbnail_url?: string;
  content_url?: string;
  coordinates?: string;
};

export type ResearchResult = ResearchEvidence;

export type ResearchClaim = {
  claim_id: string;
  text: string;
  confidence: string;
  status: string;
  supporting_evidence_ids: string[];
  caveat: string;
};

export type ResearchReportSection = {
  id: string;
  title: string;
  kind: string;
  content?: string;
  items?: Array<Record<string, unknown>>;
};

export type ResearchReportPacket = {
  dossier_id: string;
  title: string;
  generated_at: number;
  sections: ResearchReportSection[];
  pinned_evidence_ids: string[];
};

export type ResearchDossier = {
  schema_version: number;
  dossier_id: string;
  query: {
    text: string;
    mode: string;
    selected_engines: string[];
    source_selection_mode: string;
    submitted_at: number;
  };
  source_catalog: {
    engines: ResearchPayload['engines'];
    source_classes?: ResearchPayload['source_classes'];
  };
  engine_runs: ResearchPayload['engines'];
  evidence: ResearchEvidence[];
  claims: ResearchClaim[];
  synthesis: {
    title?: string;
    summary?: string;
    answer?: string;
    citations?: string[];
    degraded_engines?: string[];
    live_result_count?: number;
    evidence_count?: number;
    analyst_count?: number;
    coordinator_model?: string;
    coordinated_answer?: string;
    source_engine_counts?: Record<string, number>;
    source_kind_counts?: Record<string, number>;
    source_coverage?: ResearchSourceCoverage[];
    evidence_ids?: string[];
  };
  model_audit?: {
    strategy?: ResearchModelStrategy;
    outputs?: {
      analysts?: ResearchModelOutput[];
      coordinator?: ResearchModelOutput;
      answer?: string;
      generated_at?: number;
    };
    diagnostics?: Record<string, unknown>;
  };
  report_packet: ResearchReportPacket;
  pinned_evidence_ids: string[];
};

export type ResearchResultPayload = ResearchDossier;

export type CreatePayload = {
  image_models: ModelCard[];
  text_models: ModelCard[];
  wallpaper: Record<string, unknown>;
  modes: string[];
  research_source_classes?: ResearchPayload['source_classes'];
};

export function getModels(): Promise<ModelsPayload> {
  return requestJson<ModelsPayload>('/v2/models');
}

export function getWhatsNew(): Promise<WhatsNewPayload> {
  return requestJson<WhatsNewPayload>('/v2/models/whats-new');
}

export function discoverModels(): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>('/v2/models/discover', { method: 'POST' });
}

export function getChatPayload(): Promise<ChatPayload> {
  return requestJson<ChatPayload>('/v2/chat');
}

export function runChat(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>('/v2/chat', { method: 'POST', body: JSON.stringify(payload) });
}

export function getCodePayload(): Promise<CodePayload> {
  return requestJson<CodePayload>('/v2/code');
}

export function startCodeSession(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>('/v2/code/sessions/start', { method: 'POST', body: JSON.stringify(payload) });
}

export function sendCodeSession(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>('/v2/code/sessions/send', { method: 'POST', body: JSON.stringify(payload) });
}

export function uploadCodeAttachment(payload: Record<string, unknown>): Promise<{ attachment: CodeAttachment }> {
  return requestJson<{ attachment: CodeAttachment }>('/v2/code/attachments', { method: 'POST', body: JSON.stringify(payload) });
}

export function deleteCodeAttachment(sessionId: string, attachmentId: string): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>(`/v2/code/attachments/${encodeURIComponent(attachmentId)}?session_id=${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
}

export function reviewCodeImages(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>('/v2/code/review', { method: 'POST', body: JSON.stringify(payload) });
}

export function getResearchPayload(): Promise<ResearchPayload> {
  return requestJson<ResearchPayload>('/v2/research');
}

export function runResearchSearch(payload: Record<string, unknown>): Promise<ResearchDossier> {
  return requestJson<ResearchDossier>('/v2/research/search', { method: 'POST', body: JSON.stringify(payload) });
}

export function getResearchDossier(dossierId: string): Promise<ResearchDossier> {
  return requestJson<ResearchDossier>(`/v2/research/dossiers/${encodeURIComponent(dossierId)}`);
}

export function updateResearchPins(dossierId: string, evidenceIds: string[]): Promise<ResearchDossier> {
  return requestJson<ResearchDossier>(`/v2/research/dossiers/${encodeURIComponent(dossierId)}/pins`, { method: 'PATCH', body: JSON.stringify({ evidence_ids: evidenceIds }) });
}

export function getResearchReport(dossierId: string): Promise<ResearchReportPacket> {
  return requestJson<ResearchReportPacket>(`/v2/research/dossiers/${encodeURIComponent(dossierId)}/report`);
}

export function getCreatePayload(): Promise<CreatePayload> {
  return requestJson<CreatePayload>('/v2/create');
}

export function runCreateImages(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>('/v2/create/images', { method: 'POST', body: JSON.stringify(payload) });
}
