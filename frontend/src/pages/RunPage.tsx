import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Card, Form, Input, Select, Space, Table, Tabs, Tag, Typography } from 'antd';
import 'antd/dist/reset.css';
import {
  activateRunProfile,
  ChatRunPayload,
  ConversationBranch,
  ContextWindowPayload,
  EvalGate,
  EvalGateRecord,
  exportWorkspaceBundle,
  getMeCapabilities,
  getRunWorkspace,
  importWorkspaceBundle,
  indexLocalRag,
  inspectContextWindow,
  listReplays,
  listWorkspaceBundles,
  listPromptTemplateVersions,
  LocalRagSearchResult,
  previewWorkspaceBundleImport,
  previewEvalGate,
  previewPromptTemplate,
  PromptTemplate,
  PromptTemplatePreview,
  ReplayRecord,
  ReplaySnapshot,
  RunProfile,
  RunRecord,
  rollbackPromptTemplate,
  rollbackRunProfile,
  runReplay,
  runChat,
  saveConversationBranch,
  saveLocalRagConfig,
  savePromptTemplate,
  saveRunRecord,
  saveRunProfile,
  saveSessionSnapshot,
  searchLocalRag,
  snapshotReplay,
  SessionSnapshot,
  WorkspaceBundleExport,
  WorkspaceBundlePreview,
  WorkspaceBundleSummary
} from '../api/generated/v2Client';
import { errorText } from '../utils/errors';

function csv(value: string): string[] {
  return value.split(',').map((item) => item.trim()).filter(Boolean);
}

function jsonObject(value: string): Record<string, unknown> {
  if (!value.trim()) return {};
  const parsed = JSON.parse(value);
  return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
}

function templateExamples(value: string): PromptTemplate['examples'] {
  if (!value.trim()) return [];
  const parsed = JSON.parse(value);
  if (!Array.isArray(parsed)) return [];
  return parsed
    .filter((item) => item && typeof item === 'object' && !Array.isArray(item))
    .map((item) => {
      const row = item as Record<string, unknown>;
      const rawValues = row.values;
      return {
        title: String(row.title || row.name || ''),
        values: rawValues && typeof rawValues === 'object' ? JSON.stringify(rawValues) : String(rawValues || ''),
        rendered: String(row.rendered || row.prompt || ''),
        note: String(row.note || row.description || '')
      };
    });
}

function optionalNumber(value: unknown): number | undefined {
  if (value === null || value === undefined || value === '') return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function chatResultText(result: Record<string, unknown>): string {
  const candidates = [result.text, recordValue(result.response).text, result.content, result.message];
  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim()) return candidate;
  }
  return '';
}

export default function RunPage() {
  const queryClient = useQueryClient();
  const [templateForm] = Form.useForm();
  const [chatForm] = Form.useForm();
  const [profileForm] = Form.useForm();
  const [recordForm] = Form.useForm();
  const [branchForm] = Form.useForm();
  const [snapshotForm] = Form.useForm();
  const [ragForm] = Form.useForm();
  const [ragSearchForm] = Form.useForm();
  const [replayForm] = Form.useForm();
  const [contextForm] = Form.useForm();
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: getMeCapabilities, retry: false });
  const workspace = useQuery({ queryKey: ['run-workspace'], queryFn: getRunWorkspace });
  const replayRecords = useQuery({ queryKey: ['run-replays'], queryFn: () => listReplays(25) });
  const workspaceBundleRecords = useQuery({ queryKey: ['workspace-bundles'], queryFn: listWorkspaceBundles });
  const canEdit = capabilities.data?.capabilities['run.edit']?.allowed ?? false;
  const canChat = capabilities.data?.capabilities['chat.use']?.allowed ?? false;
  const templates = workspace.data?.prompt_templates ?? [];
  const profiles = workspace.data?.run_profiles ?? [];
  const records = workspace.data?.run_records ?? [];
  const gateRecords = workspace.data?.eval_gate_records ?? [];
  const branches = workspace.data?.conversation_branches ?? [];
  const snapshots = workspace.data?.session_snapshots ?? [];
  const localRag = workspace.data?.local_rag;
  const replays = replayRecords.data?.replays ?? [];
  const workspaceBundles = workspaceBundleRecords.data?.bundles ?? [];
  const [templateId, setTemplateId] = useState('');
  const [templatePreview, setTemplatePreview] = useState<PromptTemplatePreview | null>(null);
  const [templatePreviewError, setTemplatePreviewError] = useState('');
  const [templateSchemaError, setTemplateSchemaError] = useState('');
  const [templateSaveError, setTemplateSaveError] = useState('');
  const [templateRollbackStatus, setTemplateRollbackStatus] = useState<{ type: 'success' | 'warning' | 'error'; message: string } | null>(null);
  const [templateSearch, setTemplateSearch] = useState('');
  const [profileSearch, setProfileSearch] = useState('');
  const [profileSettingsError, setProfileSettingsError] = useState('');
  const [profileActionError, setProfileActionError] = useState('');
  const [evalGatePreview, setEvalGatePreview] = useState<EvalGate | null>(null);
  const [recordError, setRecordError] = useState('');
  const [branchError, setBranchError] = useState('');
  const [snapshotError, setSnapshotError] = useState('');
  const [ragError, setRagError] = useState('');
  const [ragSearchResults, setRagSearchResults] = useState<LocalRagSearchResult | null>(null);
  const [replaySnapshot, setReplaySnapshot] = useState<ReplaySnapshot | null>(null);
  const [replayResult, setReplayResult] = useState<ReplayRecord | null>(null);
  const [replayError, setReplayError] = useState('');
  const [bundleSections, setBundleSections] = useState<string[]>(['prompt_templates', 'run_profiles']);
  const [bundleImportJson, setBundleImportJson] = useState('');
  const [bundleExportResult, setBundleExportResult] = useState<WorkspaceBundleExport | null>(null);
  const [bundlePreview, setBundlePreview] = useState<WorkspaceBundlePreview | null>(null);
  const [bundleError, setBundleError] = useState('');
  const [contextResult, setContextResult] = useState<ContextWindowPayload | null>(null);
  const [contextError, setContextError] = useState('');
  const [chatResult, setChatResult] = useState<Record<string, unknown> | null>(null);
  const [chatError, setChatError] = useState('');
  const filteredTemplates = templates.filter((template) => {
    const haystack = [template.name, template.description, template.body, template.owner_notes, JSON.stringify(template.examples || []), ...(template.tags || [])].join(' ').toLowerCase();
    return haystack.includes(templateSearch.toLowerCase());
  });
  const filteredProfiles = profiles.filter((profile) => {
    const haystack = [profile.name, profile.description, profile.model, JSON.stringify(profile.settings || {}), ...(profile.tags || [])].join(' ').toLowerCase();
    return haystack.includes(profileSearch.toLowerCase());
  });

  const saveProfile = (values: Record<string, string>) => {
    try {
      const settings = {
        mode: values.mode || 'chat',
        default_prompt: values.default_prompt || '',
        system_prompt: values.system_prompt || '',
        parameters: {
          temperature: optionalNumber(values.temperature),
          max_tokens: optionalNumber(values.max_tokens)
        },
        tools: {
          allowed: csv(values.allowed_tools || ''),
          disallowed: csv(values.disallowed_tools || '')
        },
        budget: {
          max_usd: optionalNumber(values.max_budget_usd)
        },
        gateway_policy: jsonObject(values.gateway_policy || '')
      };
      setProfileSettingsError('');
      profileMutation.mutate({
        id: values.id || undefined,
        name: values.name,
        description: values.description || '',
        model: values.model || '',
        template_id: values.template_id || '',
        tags: csv(values.tags || ''),
        settings
      });
    } catch (error) {
      setProfileSettingsError('Gateway policy must be a JSON object.');
    }
  };

  const templateMutation = useMutation({
    mutationFn: (payload: Partial<PromptTemplate>) => savePromptTemplate(payload),
    onSuccess: () => {
      setTemplateSchemaError('');
      setTemplateSaveError('');
      setTemplateRollbackStatus(null);
      templateForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ['run-workspace'] });
    },
    onError: (error) => setTemplateSaveError(errorText(error))
  });
  const previewMutation = useMutation({
    mutationFn: (payload: { body?: string; variables?: string[]; values?: Record<string, unknown> }) => previewPromptTemplate(payload),
    onSuccess: (payload) => {
      setTemplatePreviewError('');
      setTemplatePreview(payload.preview);
    },
    onError: (error) => setTemplatePreviewError(errorText(error))
  });
  const profileMutation = useMutation({
    mutationFn: (payload: Partial<RunProfile>) => saveRunProfile(payload),
    onSuccess: () => {
      setProfileSettingsError('');
      setProfileActionError('');
      profileForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ['run-workspace'] });
    },
    onError: (error) => setProfileActionError(errorText(error))
  });
  const activateProfileMutation = useMutation({
    mutationFn: (profileId: string) => activateRunProfile(profileId),
    onSuccess: () => {
      setProfileActionError('');
      queryClient.invalidateQueries({ queryKey: ['run-workspace'] });
    },
    onError: (error) => setProfileActionError(errorText(error))
  });
  const evalGatePreviewMutation = useMutation({
    mutationFn: (profile: RunProfile) => previewEvalGate({ surface: 'run_profile', after: { profile } }),
    onSuccess: (payload) => {
      setProfileActionError('');
      setEvalGatePreview(payload.eval_gate);
    },
    onError: (error) => setProfileActionError(errorText(error))
  });
  const rollbackProfileMutation = useMutation({
    mutationFn: (payload: { profileId: string; version: number }) => rollbackRunProfile(payload.profileId, payload.version),
    onSuccess: () => {
      setProfileActionError('');
      queryClient.invalidateQueries({ queryKey: ['run-workspace'] });
    },
    onError: (error) => setProfileActionError(errorText(error))
  });
  const rollbackTemplateMutation = useMutation({
    mutationFn: (payload: { templateId: string; version: number }) => rollbackPromptTemplate(payload.templateId, payload.version),
    onSuccess: (_payload, variables) => {
      setTemplateRollbackStatus({ type: 'success', message: `Prompt template rolled back to version ${variables.version}.` });
      queryClient.invalidateQueries({ queryKey: ['run-workspace'] });
    },
    onError: (error) => setTemplateRollbackStatus({ type: 'error', message: errorText(error) })
  });
  const recordMutation = useMutation({
    mutationFn: (payload: Partial<RunRecord>) => saveRunRecord(payload),
    onSuccess: () => {
      setRecordError('');
      recordForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ['run-workspace'] });
    },
    onError: (error) => setRecordError(errorText(error))
  });
  const branchMutation = useMutation({
    mutationFn: (payload: Partial<ConversationBranch>) => saveConversationBranch(payload),
    onSuccess: () => {
      setBranchError('');
      branchForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ['run-workspace'] });
    },
    onError: (error) => setBranchError(errorText(error))
  });
  const snapshotMutation = useMutation({
    mutationFn: (payload: Partial<SessionSnapshot>) => saveSessionSnapshot(payload),
    onSuccess: () => {
      setSnapshotError('');
      snapshotForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ['run-workspace'] });
    },
    onError: (error) => setSnapshotError(errorText(error))
  });
  const ragConfigMutation = useMutation({
    mutationFn: (payload: { collections: Array<{ id: string; name: string; include: string[]; exclude: string[]; max_file_bytes: number }> }) => saveLocalRagConfig(payload),
    onSuccess: () => {
      setRagError('');
      queryClient.invalidateQueries({ queryKey: ['run-workspace'] });
    },
    onError: (error) => setRagError(errorText(error))
  });
  const ragIndexMutation = useMutation({
    mutationFn: (collectionId: string) => indexLocalRag(collectionId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['run-workspace'] }),
    onError: (error) => setRagError(errorText(error))
  });
  const ragSearchMutation = useMutation({
    mutationFn: (payload: { query: string; collection_id?: string; limit?: number }) => searchLocalRag(payload),
    onSuccess: (payload) => {
      setRagError('');
      setRagSearchResults(payload.results);
    },
    onError: (error) => setRagError(errorText(error))
  });
  const replaySnapshotMutation = useMutation({
    mutationFn: (values: Record<string, string>) => snapshotReplay({ source: { type: values.source_type || 'trace', id: values.source_id || '' } }),
    onSuccess: (payload) => {
      setReplayError('');
      setReplaySnapshot(payload.snapshot);
    },
    onError: (error) => setReplayError(errorText(error))
  });
  const replayMutation = useMutation({
    mutationFn: (values: Record<string, string>) => runReplay({
      source: { type: values.source_type || 'trace', id: values.source_id || '' },
      target: values.target || 'original',
      models: csv(values.models || ''),
      baseline_text: values.baseline_text || '',
      max_tokens: optionalNumber(values.max_tokens),
      temperature: values.temperature ?? ''
    }),
    onSuccess: (payload) => {
      setReplayError('');
      setReplayResult(payload);
      queryClient.invalidateQueries({ queryKey: ['run-replays'] });
    },
    onError: (error) => setReplayError(errorText(error))
  });
  const workspaceBundleExportMutation = useMutation({
    mutationFn: () => exportWorkspaceBundle({ sections: bundleSections }),
    onSuccess: (payload) => {
      setBundleError('');
      setBundleExportResult(payload);
      setBundleImportJson(JSON.stringify(payload.bundle || {}, null, 2));
      queryClient.invalidateQueries({ queryKey: ['workspace-bundles'] });
    },
    onError: (error) => setBundleError(errorText(error))
  });
  const workspaceBundlePayload = (dryRun = true): Record<string, unknown> => {
    const parsed = bundleImportJson.trim() ? JSON.parse(bundleImportJson) : {};
    const payload = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
    payload.selected_sections = bundleSections;
    payload.dry_run = dryRun;
    return payload;
  };
  const workspaceBundlePreviewMutation = useMutation({
    mutationFn: () => previewWorkspaceBundleImport(workspaceBundlePayload(true)),
    onSuccess: (payload) => {
      setBundleError('');
      setBundlePreview(payload);
    },
    onError: (error) => setBundleError(errorText(error))
  });
  const workspaceBundleImportMutation = useMutation({
    mutationFn: () => importWorkspaceBundle(workspaceBundlePayload(false)),
    onSuccess: (payload) => {
      setBundleError('');
      setBundlePreview(payload);
      queryClient.invalidateQueries({ queryKey: ['run-workspace'] });
      queryClient.invalidateQueries({ queryKey: ['workspace-bundles'] });
    },
    onError: (error) => setBundleError(errorText(error))
  });
  const contextInspectMutation = useMutation({
    mutationFn: (values: Record<string, string>) => inspectContextWindow({
      action: values.action || 'chat',
      payload: {
        model: values.model || '',
        models: csv(values.models || ''),
        messages: [
          ...(values.system_prompt ? [{ role: 'system', content: values.system_prompt }] : []),
          { role: 'user', content: values.prompt || '' }
        ],
        print_prompt: values.prompt || '',
        max_tokens: optionalNumber(values.max_tokens)
      }
    }),
    onSuccess: (payload) => {
      setContextError('');
      setContextResult(payload);
    },
    onError: (error) => setContextError(errorText(error))
  });
  const chatMutation = useMutation({
    mutationFn: (values: Record<string, string>) => {
      const payload: ChatRunPayload = {
        model: values.model || undefined,
        messages: [
          ...(values.system_prompt ? [{ role: 'system', content: values.system_prompt }] : []),
          { role: 'user', content: values.prompt || '' }
        ],
        max_tokens: optionalNumber(values.max_tokens),
        temperature: values.temperature ?? '',
        run_profile_id: values.run_profile_id || undefined,
        prompt_template_id: values.prompt_template_id || undefined
      };
      return runChat(payload);
    },
    onSuccess: (payload) => {
      setChatError('');
      setChatResult(payload.response || {});
    },
    onError: (error) => setChatError(errorText(error))
  });
  const chatText = chatResult ? chatResultText(chatResult) : '';
  const chatRouting = recordValue(chatResult?.routing);
  const chatModel = String(chatRouting.used || chatRouting.requested || '');
  const chatBackend = String(chatRouting.backend || '');
  const chatCostUsd = optionalNumber(recordValue(chatResult?.cost).total_cost_usd ?? chatResult?.cost_usd);

  return (
    <Space direction="vertical" size={16} className="pageStack">
      <Card>
        <Space direction="vertical" size={8}>
          <Typography.Title level={3}>Run</Typography.Title>
          <Typography.Text type="secondary">Prompt templates and run profiles persisted through the v2 SQLite repository.</Typography.Text>
          <Space wrap>
            <Tag color={canEdit ? 'blue' : 'default'}>{canEdit ? 'Edit allowed' : 'Read-only'}</Tag>
            <Tag color={canChat ? 'blue' : 'default'}>{canChat ? 'Chat allowed' : 'Chat disabled'}</Tag>
            <Tag>{templates.length} templates</Tag>
            <Tag>{profiles.length} profiles</Tag>
            <Tag>{records.length} run records</Tag>
            <Tag>{gateRecords.length} eval gates</Tag>
            <Tag>{branches.length} branches</Tag>
            <Tag>{snapshots.length} snapshots</Tag>
            <Tag>{localRag?.index?.reduce((total, row) => total + Number(row.documents || 0), 0) ?? 0} RAG chunks</Tag>
            <Tag>{replays.length} replays</Tag>
            <Tag>{workspaceBundles.length} bundles</Tag>
          </Space>
        </Space>
      </Card>
      {!canEdit ? <Alert type="info" showIcon message="You can inspect Run assets, but editing requires model_use permission." /> : null}
      <Tabs
        tabPosition="left"
        items={[
          {
            key: 'chat',
            label: 'Chat Run',
            children: (
              <Space direction="vertical" size={16} className="pageStack">
                {chatError ? <Alert type="error" showIcon message={chatError} /> : null}
                <Card title="Chat Run" data-testid="chat-run-panel">
                  <Form
                    form={chatForm}
                    layout="vertical"
                    initialValues={{ max_tokens: '512' }}
                    onFinish={(values) => chatMutation.mutate(values)}
                  >
                    <Space wrap>
                      <Form.Item name="model" label="Model">
                        <Input data-testid="chat-run-model" placeholder="default text model" />
                      </Form.Item>
                      <Form.Item name="max_tokens" label="Max Tokens">
                        <Input data-testid="chat-run-max-tokens" type="number" />
                      </Form.Item>
                      <Form.Item name="temperature" label="Temperature">
                        <Input data-testid="chat-run-temperature" type="number" step="0.1" />
                      </Form.Item>
                    </Space>
                    <Space wrap>
                      <Form.Item name="run_profile_id" label="Run Profile">
                        <Select data-testid="chat-run-profile" allowClear options={profiles.map((profile) => ({ value: profile.id, label: `${profile.name} v${profile.version}` }))} />
                      </Form.Item>
                      <Form.Item name="prompt_template_id" label="Prompt Template">
                        <Select data-testid="chat-run-template" allowClear options={templates.map((template) => ({ value: template.id, label: `${template.name} v${template.version}` }))} />
                      </Form.Item>
                    </Space>
                    <Form.Item name="system_prompt" label="System Prompt">
                      <Input.TextArea data-testid="chat-run-system" rows={3} />
                    </Form.Item>
                    <Form.Item name="prompt" label="Prompt" rules={[{ required: true }]}>
                      <Input.TextArea data-testid="chat-run-prompt" rows={5} />
                    </Form.Item>
                    <Button data-testid="chat-run-send" type="primary" htmlType="submit" disabled={!canChat} loading={chatMutation.isPending}>
                      Send
                    </Button>
                  </Form>
                </Card>
                {chatResult ? (
                  <Card title="Chat Result" data-testid="chat-run-result">
                    <Space direction="vertical" size={12} className="pageStack">
                      {chatModel || chatBackend || chatCostUsd !== undefined ? (
                        <Space wrap>
                          {chatModel ? <Tag>{chatModel}</Tag> : null}
                          {chatBackend ? <Tag>{chatBackend}</Tag> : null}
                          {chatCostUsd !== undefined ? <Tag>${String(chatCostUsd)}</Tag> : null}
                        </Space>
                      ) : null}
                      {chatText ? (
                        <pre className="templatePreview">{chatText}</pre>
                      ) : (
                        <Typography.Text type="secondary">No assistant text in this response.</Typography.Text>
                      )}
                      <details>
                        <summary>Raw payload</summary>
                        <pre className="templatePreview">{JSON.stringify(chatResult, null, 2)}</pre>
                      </details>
                    </Space>
                  </Card>
                ) : null}
              </Space>
            )
          },
          {
            key: 'templates',
            label: 'Prompt Templates',
            children: (
              <Space direction="vertical" size={16} className="pageStack">
                {templateSaveError ? <Alert type="error" showIcon message={templateSaveError} /> : null}
                <Card title="New Prompt Template">
                  <Form form={templateForm} layout="vertical" disabled={!canEdit} onFinish={(values) => {
                    try {
                      setTemplateSchemaError('');
                      templateMutation.mutate({
                        id: values.id || undefined,
                        name: values.name,
                        description: values.description || '',
                        body: values.body,
                        variables: csv(values.variables || ''),
                        examples: templateExamples(values.examples || ''),
                        owner_notes: values.owner_notes || '',
                        tags: csv(values.tags || '')
                      });
                    } catch (error) {
                      setTemplateSchemaError('Examples must be a JSON array of objects.');
                    }
                  }}>
                    <Form.Item name="id" hidden>
                      <Input />
                    </Form.Item>
                    <Form.Item name="name" label="Name" rules={[{ required: true }]}>
                      <Input data-testid="template-name" />
                    </Form.Item>
                    <Form.Item name="description" label="Description">
                      <Input data-testid="template-description" />
                    </Form.Item>
                    <Form.Item name="body" label="Template Body" rules={[{ required: true }]}>
                      <Input.TextArea data-testid="template-body" rows={6} />
                    </Form.Item>
                    <Form.Item name="variables" label="Variables">
                      <Input data-testid="template-variables" placeholder="goal, audience, constraints" />
                    </Form.Item>
                    <Form.Item name="examples" label="Examples">
                      <Input.TextArea data-testid="template-examples" rows={3} placeholder='[{"title":"Review","values":{"file":"app.py"},"rendered":"Review app.py"}]' />
                    </Form.Item>
                    <Form.Item name="owner_notes" label="Owner Notes">
                      <Input.TextArea data-testid="template-owner-notes" rows={2} />
                    </Form.Item>
                    <Form.Item name="tags" label="Tags">
                      <Input data-testid="template-tags" placeholder="coding, review" />
                    </Form.Item>
                    <Form.Item name="preview_values" label="Preview Values">
                      <Input.TextArea data-testid="template-preview-values" rows={3} placeholder='{"goal":"ship safely","audience":"operators"}' />
                    </Form.Item>
                    <Space wrap>
                      <Button
                        data-testid="template-new"
                        onClick={() => {
                          templateForm.resetFields();
                          setTemplatePreview(null);
                          setTemplatePreviewError('');
                          setTemplateSchemaError('');
                          setTemplateRollbackStatus(null);
                        }}
                      >
                        New
                      </Button>
                      <Button
                        data-testid="template-preview"
                        onClick={() => {
                          const values = templateForm.getFieldsValue();
                          try {
                            previewMutation.mutate({
                              body: values.body || '',
                              variables: csv(values.variables || ''),
                              values: jsonObject(values.preview_values || '')
                            });
                          } catch (error) {
                            setTemplatePreviewError('Preview values must be a JSON object.');
                          }
                        }}
                        loading={previewMutation.isPending}
                      >
                        Preview
                      </Button>
                      <Button data-testid="template-save" type="primary" htmlType="submit" loading={templateMutation.isPending}>Save template</Button>
                    </Space>
                    {templateSchemaError ? <Alert type="error" showIcon message={templateSchemaError} /> : null}
                    {templatePreviewError ? <Alert type="error" showIcon message={templatePreviewError} /> : null}
                    {templatePreview ? (
                      <div data-testid="template-preview-output">
                        <Space wrap>
                          <Tag color={templatePreview.missing_variables.length ? 'red' : 'green'}>{templatePreview.missing_variables.length} missing</Tag>
                          {templatePreview.used_variables.map((variable) => <Tag key={variable}>{variable}</Tag>)}
                        </Space>
                        <pre className="templatePreview">{templatePreview.rendered}</pre>
                      </div>
                    ) : null}
                  </Form>
                </Card>
                <Input.Search
                  data-testid="template-search"
                  placeholder="Search templates"
                  allowClear
                  value={templateSearch}
                  onChange={(event) => setTemplateSearch(event.target.value)}
                />
                <Table<PromptTemplate>
                  rowKey="id"
                  dataSource={filteredTemplates}
                  pagination={false}
                  columns={[
                    { title: 'Name', dataIndex: 'name' },
                    { title: 'Version', dataIndex: 'version', width: 90 },
                    { title: 'Examples', dataIndex: 'examples', width: 90, render: (examples: PromptTemplate['examples']) => examples?.length || 0 },
                    { title: 'Tags', dataIndex: 'tags', render: (tags: string[]) => <Space wrap>{tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</Space> },
                    { title: 'Updated', dataIndex: 'updated_at', render: (value: number) => value ? new Date(value * 1000).toLocaleString() : 'n/a' },
                    {
                      title: 'Actions',
                      width: 300,
                      render: (_value, template) => (
                        <Space>
                          <Button
                            data-testid="template-edit"
                            onClick={() => {
                              templateForm.setFieldsValue({
                                id: template.id,
                                name: template.name,
                                description: template.description,
                                body: template.body,
                                variables: template.variables.join(', '),
                                examples: JSON.stringify(template.examples || [], null, 2),
                                owner_notes: template.owner_notes || '',
                                tags: template.tags.join(', ')
                              });
                              setTemplatePreview(null);
                              setTemplateRollbackStatus(null);
                            }}
                          >
                            Edit
                          </Button>
                          <Button
                            data-testid="template-duplicate"
                            onClick={() => templateMutation.mutate({
                              name: `${template.name} Copy`,
                              description: template.description,
                              body: template.body,
                              variables: template.variables,
                              examples: template.examples,
                              owner_notes: template.owner_notes,
                              tags: template.tags
                            })}
                          >
                            Duplicate
                          </Button>
                          <Button
                            data-testid="template-rollback"
                            loading={rollbackTemplateMutation.isPending}
                            onClick={async () => {
                              setTemplateRollbackStatus(null);
                              try {
                                const versions = await listPromptTemplateVersions(template.id);
                                const previous = versions.versions.find((item) => item.version < template.version);
                                if (!previous) {
                                  setTemplateRollbackStatus({ type: 'warning', message: 'No previous template version is available.' });
                                  return;
                                }
                                rollbackTemplateMutation.mutate({ templateId: template.id, version: previous.version });
                              } catch (error) {
                                setTemplateRollbackStatus({ type: 'error', message: errorText(error) });
                              }
                            }}
                          >
                            Rollback
                          </Button>
                        </Space>
                      )
                    }
                  ]}
                />
                {templateRollbackStatus ? <Alert data-testid="template-rollback-status" type={templateRollbackStatus.type} showIcon message={templateRollbackStatus.message} /> : null}
              </Space>
            )
          },
          {
            key: 'profiles',
            label: 'Run Profiles',
            children: (
              <Space direction="vertical" size={16} className="pageStack">
                {profileActionError ? <Alert type="error" showIcon message={profileActionError} /> : null}
                <Card title="New Run Profile">
                  <Form form={profileForm} layout="vertical" disabled={!canEdit} onFinish={saveProfile}>
                    <Form.Item name="id" hidden>
                      <Input />
                    </Form.Item>
                    <Form.Item name="name" label="Name" rules={[{ required: true }]}>
                      <Input data-testid="profile-name" />
                    </Form.Item>
                    <Form.Item name="description" label="Description">
                      <Input data-testid="profile-description" />
                    </Form.Item>
                    <Form.Item name="model" label="Model">
                      <Input data-testid="profile-model" placeholder="deepseek-3.2" />
                    </Form.Item>
                    <Form.Item name="template_id" label="Prompt Template">
                      <Select data-testid="profile-template" allowClear value={templateId} onChange={setTemplateId} options={templates.map((template) => ({ value: template.id, label: template.name }))} />
                    </Form.Item>
                    <Form.Item name="mode" label="Mode">
                      <Select data-testid="profile-mode" options={[{ value: 'chat', label: 'Chat' }, { value: 'code', label: 'Code' }, { value: 'eval', label: 'Eval' }]} />
                    </Form.Item>
                    <Form.Item name="default_prompt" label="Default Prompt">
                      <Input.TextArea data-testid="profile-default-prompt" rows={3} placeholder="Reusable task prompt for this profile" />
                    </Form.Item>
                    <Form.Item name="system_prompt" label="System Instructions">
                      <Input.TextArea data-testid="profile-system-prompt" rows={3} placeholder="Operator/system instructions to apply with this profile" />
                    </Form.Item>
                    <Space wrap>
                      <Form.Item name="temperature" label="Temperature">
                        <Input data-testid="profile-temperature" type="number" step="0.1" />
                      </Form.Item>
                      <Form.Item name="max_tokens" label="Max Tokens">
                        <Input data-testid="profile-max-tokens" type="number" />
                      </Form.Item>
                      <Form.Item name="max_budget_usd" label="Max Budget USD">
                        <Input data-testid="profile-max-budget" type="number" step="0.01" />
                      </Form.Item>
                    </Space>
                    <Form.Item name="allowed_tools" label="Allowed Tools">
                      <Input data-testid="profile-allowed-tools" placeholder="Bash(*), Edit, Read" />
                    </Form.Item>
                    <Form.Item name="disallowed_tools" label="Disallowed Tools">
                      <Input data-testid="profile-disallowed-tools" placeholder="Bash(rm -rf *), Bash(shutdown *)" />
                    </Form.Item>
                    <Form.Item name="gateway_policy" label="Gateway Policy">
                      <Input.TextArea data-testid="profile-gateway-policy" rows={3} placeholder='{"preferred_route":"serverless","fallback":"dedicated"}' />
                    </Form.Item>
                    <Form.Item name="tags" label="Tags">
                      <Input data-testid="profile-tags" placeholder="daily, coding" />
                    </Form.Item>
                    {profileSettingsError ? <Alert type="error" showIcon message={profileSettingsError} /> : null}
                    <Space wrap>
                      <Button data-testid="profile-new" onClick={() => {
                        setProfileSettingsError('');
                        profileForm.resetFields();
                      }}>New</Button>
                      <Button data-testid="profile-save" type="primary" htmlType="submit" loading={profileMutation.isPending}>Save profile</Button>
                    </Space>
                  </Form>
                </Card>
                <Input.Search
                  data-testid="profile-search"
                  placeholder="Search profiles"
                  allowClear
                  value={profileSearch}
                  onChange={(event) => setProfileSearch(event.target.value)}
                />
                <Table<RunProfile>
                  rowKey="id"
                  dataSource={filteredProfiles}
                  pagination={false}
                  columns={[
                    { title: 'Name', dataIndex: 'name' },
                    { title: 'Model', dataIndex: 'model' },
                    { title: 'Version', dataIndex: 'version', width: 90 },
                    { title: 'State', dataIndex: 'active', width: 100, render: (active: boolean) => active ? <Tag color="green">Active</Tag> : <Tag>Saved</Tag> },
                    {
                      title: 'Settings',
                      render: (_value, profile) => {
                        const settings = recordValue(profile.settings);
                        const parameters = recordValue(settings.parameters);
                        const budget = recordValue(settings.budget);
                        return (
                          <Space wrap>
                            <Tag>{String(settings.mode || 'chat')}</Tag>
                            {settings.system_prompt ? <Tag>system</Tag> : null}
                            {settings.default_prompt ? <Tag>prompt</Tag> : null}
                            {parameters.temperature !== undefined ? <Tag>temp {String(parameters.temperature)}</Tag> : null}
                            {budget.max_usd !== undefined ? <Tag>budget ${String(budget.max_usd)}</Tag> : null}
                          </Space>
                        );
                      }
                    },
                    { title: 'Tags', dataIndex: 'tags', render: (tags: string[]) => <Space wrap>{tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</Space> },
                    { title: 'Updated', dataIndex: 'updated_at', render: (value: number) => value ? new Date(value * 1000).toLocaleString() : 'n/a' },
                    {
                      title: 'Actions',
                      width: 340,
                      render: (_value, profile) => (
                        <Space wrap>
                          <Button
                            data-testid="profile-edit"
                            onClick={() => {
                              const settings = recordValue(profile.settings);
                              const parameters = recordValue(settings.parameters);
                              const tools = recordValue(settings.tools);
                              const budget = recordValue(settings.budget);
                              profileForm.setFieldsValue({
                                id: profile.id,
                                name: profile.name,
                                description: profile.description,
                                model: profile.model,
                                template_id: profile.template_id || undefined,
                                mode: String(settings.mode || 'chat'),
                                default_prompt: String(settings.default_prompt || ''),
                                system_prompt: String(settings.system_prompt || ''),
                                temperature: parameters.temperature ?? '',
                                max_tokens: parameters.max_tokens ?? '',
                                max_budget_usd: budget.max_usd ?? '',
                                allowed_tools: Array.isArray(tools.allowed) ? tools.allowed.join(', ') : '',
                                disallowed_tools: Array.isArray(tools.disallowed) ? tools.disallowed.join(', ') : '',
                                gateway_policy: JSON.stringify(recordValue(settings.gateway_policy), null, 2),
                                tags: profile.tags.join(', ')
                              });
                              setTemplateId(profile.template_id || '');
                            }}
                          >
                            Edit
                          </Button>
                          <Button
                            data-testid="profile-duplicate"
                            onClick={() => profileMutation.mutate({
                              name: `${profile.name} Copy`,
                              description: profile.description,
                              model: profile.model,
                              template_id: profile.template_id,
                              settings: profile.settings,
                              tags: profile.tags
                            })}
                          >
                            Duplicate
                          </Button>
                          <Button
                            data-testid="profile-gate-preview"
                            loading={evalGatePreviewMutation.isPending}
                            onClick={() => evalGatePreviewMutation.mutate(profile)}
                          >
                            Gate
                          </Button>
                          <Button
                            data-testid="profile-activate"
                            disabled={profile.active}
                            loading={activateProfileMutation.isPending}
                            onClick={() => activateProfileMutation.mutate(profile.id)}
                          >
                            Activate
                          </Button>
                          <Button
                            data-testid="profile-rollback"
                            disabled={profile.version <= 1}
                            loading={rollbackProfileMutation.isPending}
                            onClick={() => rollbackProfileMutation.mutate({ profileId: profile.id, version: profile.version - 1 })}
                          >
                            Rollback
                          </Button>
                        </Space>
                      )
                    }
                  ]}
                />
                {evalGatePreview ? (
                  <Alert
                    type={evalGatePreview.required && !evalGatePreview.would_allow ? 'warning' : 'info'}
                    showIcon
                    message={`Eval gate ${evalGatePreview.decision}`}
                    description={`Recommended datasets: ${(evalGatePreview.recommended_datasets || []).map((row) => String(row['id'] || row['name'] || '')).filter(Boolean).join(', ') || 'none'}. Evidence: ${(evalGatePreview.evidence || []).length}.`}
                  />
                ) : null}
              </Space>
            )
          },
          {
            key: 'eval-gates',
            label: 'Eval Gates',
            children: (
              <Table<EvalGateRecord>
                rowKey="id"
                dataSource={gateRecords}
                pagination={false}
                columns={[
                  { title: 'Surface', dataIndex: 'surface' },
                  { title: 'Target', dataIndex: 'target_id' },
                  { title: 'Version', dataIndex: 'target_version', width: 90 },
                  { title: 'Decision', dataIndex: 'decision', render: (value: string, record) => <Tag color={record.allowed ? 'green' : 'red'}>{value}</Tag> },
                  { title: 'Required', dataIndex: 'required', width: 100, render: (value: boolean) => value ? <Tag color="orange">Required</Tag> : <Tag>Advisory</Tag> },
                  { title: 'Datasets', render: (_value, record) => (record.gate.recommended_datasets || []).map((row) => String(row['id'] || row['name'] || '')).filter(Boolean).join(', ') || 'none' },
                  { title: 'Evidence', render: (_value, record) => (record.gate.evidence || []).map((row) => String(row['id'] || '')).filter(Boolean).join(', ') || 'none' },
                  { title: 'Created', dataIndex: 'created_at', render: (value: number) => value ? new Date(value * 1000).toLocaleString() : 'n/a' }
                ]}
              />
            )
          },
          {
            key: 'context',
            label: 'Context Inspector',
            children: (
              <Space direction="vertical" size={16} className="pageStack">
                {contextError ? <Alert type="error" showIcon message={contextError} /> : null}
                <Card title="Context Estimate">
                  <Form
                    form={contextForm}
                    layout="vertical"
                    initialValues={{ action: 'chat', max_tokens: '512' }}
                    onFinish={(values) => contextInspectMutation.mutate(values)}
                  >
                    <Space wrap>
                      <Form.Item name="action" label="Action">
                        <Select
                          data-testid="context-action"
                          options={[
                            { value: 'chat', label: 'Chat' },
                            { value: 'comparison', label: 'Comparison' },
                            { value: 'eval', label: 'Eval' },
                            { value: 'code', label: 'Code' }
                          ]}
                        />
                      </Form.Item>
                      <Form.Item name="model" label="Model">
                        <Input data-testid="context-model" placeholder="deepseek-3.2" />
                      </Form.Item>
                      <Form.Item name="max_tokens" label="Max Output">
                        <Input data-testid="context-max-tokens" type="number" />
                      </Form.Item>
                    </Space>
                    <Form.Item name="models" label="Comparison Models">
                      <Input data-testid="context-models" placeholder="model-a, model-b" />
                    </Form.Item>
                    <Form.Item name="system_prompt" label="System Prompt">
                      <Input.TextArea data-testid="context-system-prompt" rows={3} />
                    </Form.Item>
                    <Form.Item name="prompt" label="Prompt" rules={[{ required: true }]}>
                      <Input.TextArea data-testid="context-prompt" rows={4} />
                    </Form.Item>
                    <Button data-testid="context-inspect" type="primary" htmlType="submit" loading={contextInspectMutation.isPending}>
                      Inspect
                    </Button>
                  </Form>
                </Card>
                {contextResult ? (
                  <Card title="Context Result" data-testid="context-result">
                    <Space wrap>
                      <Tag>{contextResult.action}</Tag>
                      <Tag>{contextResult.input_tokens_est} input tokens</Tag>
                      <Tag>{contextResult.message_count} messages</Tag>
                      <Tag>{contextResult.warnings.length} warnings</Tag>
                    </Space>
                    <Table<Record<string, unknown>>
                      rowKey={(row) => String(row.model || row.display_name || '')}
                      dataSource={contextResult.models}
                      pagination={false}
                      columns={[
                        { title: 'Model', dataIndex: 'model' },
                        { title: 'Context', dataIndex: 'context_window' },
                        { title: 'Input', dataIndex: 'input_tokens_est' },
                        { title: 'Total', dataIndex: 'total_tokens_est' },
                        { title: 'Remaining', dataIndex: 'remaining_context_tokens' },
                        { title: 'Fits', dataIndex: 'fits', render: (value: boolean) => value ? <Tag color="green">Fits</Tag> : <Tag color="red">Over</Tag> }
                      ]}
                    />
                    <Table<Record<string, unknown>>
                      rowKey={(row) => `${String(row.index)}-${String(row.role)}`}
                      dataSource={contextResult.messages}
                      pagination={false}
                      columns={[
                        { title: 'Role', dataIndex: 'role' },
                        { title: 'Tokens', dataIndex: 'tokens' },
                        { title: 'Chars', dataIndex: 'chars' },
                        { title: 'Preview', dataIndex: 'preview' }
                      ]}
                    />
                    {contextResult.warnings.length ? (
                      <Table<Record<string, unknown>>
                        rowKey={(row, index) => `${String(row.code || 'warning')}-${index}`}
                        dataSource={contextResult.warnings}
                        pagination={false}
                        columns={[
                          { title: 'Severity', dataIndex: 'severity' },
                          { title: 'Code', dataIndex: 'code' },
                          { title: 'Model', dataIndex: 'model' },
                          { title: 'Message', dataIndex: 'message' }
                        ]}
                      />
                    ) : null}
                  </Card>
                ) : null}
              </Space>
            )
          },
          {
            key: 'records',
            label: 'Run Records',
            children: (
              <Space direction="vertical" size={16} className="pageStack">
                {recordError ? <Alert type="error" showIcon message={recordError} /> : null}
                <Card title="New Run Record">
                  <Form form={recordForm} layout="vertical" disabled={!canEdit} onFinish={(values) => recordMutation.mutate({
                    title: values.title || '',
                    trace_id: values.trace_id || '',
                    session_id: values.session_id || '',
                    profile_id: values.profile_id || '',
                    prompt_template_id: values.prompt_template_id || '',
                    status: values.status || 'recorded',
                    input: { prompt: values.prompt || '' },
                    result: { summary: values.result_summary || '' },
                    metadata: { source: 'react-run-workspace' },
                    tags: csv(values.tags || '')
                  })}>
                    <Form.Item name="title" label="Title">
                      <Input data-testid="record-title" />
                    </Form.Item>
                    <Form.Item name="trace_id" label="Trace ID">
                      <Input data-testid="record-trace-id" />
                    </Form.Item>
                    <Form.Item name="session_id" label="Session ID">
                      <Input data-testid="record-session-id" />
                    </Form.Item>
                    <Form.Item name="profile_id" label="Run Profile">
                      <Select data-testid="record-profile" allowClear options={profiles.map((profile) => ({ value: profile.id, label: `${profile.name} v${profile.version}` }))} />
                    </Form.Item>
                    <Form.Item name="prompt_template_id" label="Prompt Template">
                      <Select data-testid="record-template" allowClear options={templates.map((template) => ({ value: template.id, label: `${template.name} v${template.version}` }))} />
                    </Form.Item>
                    <Form.Item name="status" label="Status">
                      <Select data-testid="record-status" options={[{ value: 'recorded', label: 'Recorded' }, { value: 'success', label: 'Success' }, { value: 'failed', label: 'Failed' }]} />
                    </Form.Item>
                    <Form.Item name="prompt" label="Prompt">
                      <Input.TextArea data-testid="record-prompt" rows={3} />
                    </Form.Item>
                    <Form.Item name="result_summary" label="Result Summary">
                      <Input.TextArea data-testid="record-result" rows={3} />
                    </Form.Item>
                    <Form.Item name="tags" label="Tags">
                      <Input data-testid="record-tags" placeholder="trace, profile-link" />
                    </Form.Item>
                    <Button data-testid="record-save" type="primary" htmlType="submit" loading={recordMutation.isPending}>Save run record</Button>
                  </Form>
                </Card>
                <Table<RunRecord>
                  rowKey="id"
                  dataSource={records}
                  pagination={false}
                  columns={[
                    { title: 'Title', dataIndex: 'title' },
                    { title: 'Trace', dataIndex: 'trace_id' },
                    { title: 'Session', dataIndex: 'session_id' },
                    { title: 'Profile Version', render: (_value, record) => record.profile_id ? <Tag>{record.profile_version || 'current'}</Tag> : <Tag>None</Tag> },
                    { title: 'Template Version', render: (_value, record) => record.prompt_template_id ? <Tag>{record.prompt_template_version || 'current'}</Tag> : <Tag>None</Tag> },
                    { title: 'Status', dataIndex: 'status' },
                    { title: 'Tags', dataIndex: 'tags', render: (tags: string[]) => <Space wrap>{tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</Space> },
                    { title: 'Updated', dataIndex: 'updated_at', render: (value: number) => value ? new Date(value * 1000).toLocaleString() : 'n/a' }
                  ]}
                />
              </Space>
            )
          },
          {
            key: 'branches',
            label: 'Branches',
            children: (
              <Space direction="vertical" size={16} className="pageStack">
                {branchError ? <Alert type="error" showIcon message={branchError} /> : null}
                <Card title="New Conversation Branch">
                  <Form form={branchForm} layout="vertical" disabled={!canEdit} onFinish={(values) => branchMutation.mutate({
                    title: values.title,
                    root_session_id: values.root_session_id || '',
                    parent_branch_id: values.parent_branch_id || '',
                    summary: values.summary || '',
                    messages: values.seed_message ? [{ role: 'user', content: values.seed_message }] : [],
                    metadata: { source: 'react-run-workspace' },
                    tags: csv(values.tags || '')
                  })}>
                    <Form.Item name="title" label="Title" rules={[{ required: true }]}>
                      <Input data-testid="branch-title" />
                    </Form.Item>
                    <Form.Item name="root_session_id" label="Root Session ID">
                      <Input data-testid="branch-root-session" />
                    </Form.Item>
                    <Form.Item name="parent_branch_id" label="Parent Branch ID">
                      <Input data-testid="branch-parent" />
                    </Form.Item>
                    <Form.Item name="summary" label="Summary">
                      <Input.TextArea data-testid="branch-summary" rows={3} />
                    </Form.Item>
                    <Form.Item name="seed_message" label="Seed Message">
                      <Input.TextArea data-testid="branch-seed" rows={4} />
                    </Form.Item>
                    <Form.Item name="tags" label="Tags">
                      <Input data-testid="branch-tags" placeholder="experiment, shorter" />
                    </Form.Item>
                    <Button data-testid="branch-save" type="primary" htmlType="submit" loading={branchMutation.isPending}>Save branch</Button>
                  </Form>
                </Card>
                <Table<ConversationBranch>
                  rowKey="id"
                  dataSource={branches}
                  pagination={false}
                  columns={[
                    { title: 'Title', dataIndex: 'title' },
                    { title: 'Root Session', dataIndex: 'root_session_id' },
                    { title: 'Version', dataIndex: 'version', width: 90 },
                    { title: 'Tags', dataIndex: 'tags', render: (tags: string[]) => <Space wrap>{tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</Space> },
                    { title: 'Updated', dataIndex: 'updated_at', render: (value: number) => value ? new Date(value * 1000).toLocaleString() : 'n/a' }
                  ]}
                />
              </Space>
            )
          },
          {
            key: 'snapshots',
            label: 'Session Snapshots',
            children: (
              <Space direction="vertical" size={16} className="pageStack">
                {snapshotError ? <Alert type="error" showIcon message={snapshotError} /> : null}
                <Card title="New Session Snapshot">
                  <Form form={snapshotForm} layout="vertical" disabled={!canEdit} onFinish={(values) => snapshotMutation.mutate({
                    session_id: values.session_id,
                    title: values.title || values.session_id,
                    trace_id: values.trace_id || '',
                    summary: values.summary || '',
                    agentboard: {
                      status: values.agent_status || '',
                      model: values.agent_model || ''
                    },
                    resource: {
                      cpu_percent: Number(values.cpu_percent || 0),
                      rss_mb: Number(values.rss_mb || 0)
                    },
                    tags: csv(values.tags || '')
                  })}>
                    <Form.Item name="session_id" label="Session ID" rules={[{ required: true }]}>
                      <Input data-testid="snapshot-session-id" />
                    </Form.Item>
                    <Form.Item name="title" label="Title">
                      <Input data-testid="snapshot-title" />
                    </Form.Item>
                    <Form.Item name="trace_id" label="Trace ID">
                      <Input data-testid="snapshot-trace-id" />
                    </Form.Item>
                    <Form.Item name="summary" label="Summary">
                      <Input.TextArea data-testid="snapshot-summary" rows={3} />
                    </Form.Item>
                    <Form.Item name="agent_status" label="AgentBoard Status">
                      <Input data-testid="snapshot-agent-status" placeholder="working, waiting, complete" />
                    </Form.Item>
                    <Form.Item name="agent_model" label="Agent Model">
                      <Input data-testid="snapshot-agent-model" placeholder="codex" />
                    </Form.Item>
                    <Form.Item name="cpu_percent" label="CPU Percent">
                      <Input data-testid="snapshot-cpu-percent" type="number" />
                    </Form.Item>
                    <Form.Item name="rss_mb" label="RSS MB">
                      <Input data-testid="snapshot-rss-mb" type="number" />
                    </Form.Item>
                    <Form.Item name="tags" label="Tags">
                      <Input data-testid="snapshot-tags" placeholder="snapshot, before-change" />
                    </Form.Item>
                    <Button data-testid="snapshot-save" type="primary" htmlType="submit" loading={snapshotMutation.isPending}>Save snapshot</Button>
                  </Form>
                </Card>
                <Table<SessionSnapshot>
                  rowKey="id"
                  dataSource={snapshots}
                  pagination={false}
                  columns={[
                    { title: 'Title', dataIndex: 'title' },
                    { title: 'Session', dataIndex: 'session_id' },
                    { title: 'Trace', dataIndex: 'trace_id' },
                    { title: 'Version', dataIndex: 'version', width: 90 },
                    { title: 'Tags', dataIndex: 'tags', render: (tags: string[]) => <Space wrap>{tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</Space> },
                    { title: 'Updated', dataIndex: 'updated_at', render: (value: number) => value ? new Date(value * 1000).toLocaleString() : 'n/a' }
                  ]}
                />
              </Space>
            )
          },
          {
            key: 'rag',
            label: 'Local RAG',
            children: (
              <Space direction="vertical" size={16} className="pageStack">
                {ragError ? <Alert type="error" showIcon message={ragError} /> : null}
                <Card title="Collection">
                  <Form
                    form={ragForm}
                    layout="vertical"
                    disabled={!canEdit}
                    initialValues={{
                      id: localRag?.config?.collections?.[0]?.id || 'project-docs',
                      name: localRag?.config?.collections?.[0]?.name || 'Project Docs',
                      include: (localRag?.config?.collections?.[0]?.include || ['README.md', 'docs/**/*.md']).join(', '),
                      exclude: (localRag?.config?.collections?.[0]?.exclude || []).join(', '),
                      max_file_bytes: localRag?.config?.collections?.[0]?.max_file_bytes || 250000
                    }}
                    onFinish={(values) => {
                      ragConfigMutation.mutate({
                        collections: [{
                          id: values.id,
                          name: values.name || values.id,
                          include: csv(values.include || ''),
                          exclude: csv(values.exclude || ''),
                          max_file_bytes: Number(values.max_file_bytes || 250000)
                        }]
                      });
                    }}
                  >
                    <Form.Item name="id" label="Collection ID" rules={[{ required: true }]}>
                      <Input data-testid="rag-collection-id" />
                    </Form.Item>
                    <Form.Item name="name" label="Name">
                      <Input data-testid="rag-collection-name" />
                    </Form.Item>
                    <Form.Item name="include" label="Include">
                      <Input data-testid="rag-include" placeholder="README.md, docs/**/*.md" />
                    </Form.Item>
                    <Form.Item name="exclude" label="Exclude">
                      <Input data-testid="rag-exclude" placeholder="docs/private/**" />
                    </Form.Item>
                    <Form.Item name="max_file_bytes" label="Max File Bytes">
                      <Input data-testid="rag-max-file-bytes" type="number" />
                    </Form.Item>
                    <Space wrap>
                      <Button data-testid="rag-config-save" type="primary" htmlType="submit" loading={ragConfigMutation.isPending}>Save collection</Button>
                      <Button data-testid="rag-index" onClick={() => ragIndexMutation.mutate(ragForm.getFieldValue('id') || '')} loading={ragIndexMutation.isPending}>Index</Button>
                    </Space>
                  </Form>
                </Card>
                <Card title="Search">
                  <Form
                    form={ragSearchForm}
                    layout="vertical"
                    onFinish={(values) => ragSearchMutation.mutate({
                      query: values.query,
                      collection_id: values.collection_id || undefined,
                      limit: Number(values.limit || 5)
                    })}
                  >
                    <Form.Item name="query" label="Query" rules={[{ required: true }]}>
                      <Input data-testid="rag-query" />
                    </Form.Item>
                    <Space wrap>
                      <Form.Item name="collection_id" label="Collection">
                        <Select
                          data-testid="rag-search-collection"
                          allowClear
                          options={(localRag?.config?.collections || []).map((collection) => ({ value: collection.id, label: collection.name || collection.id }))}
                        />
                      </Form.Item>
                      <Form.Item name="limit" label="Limit">
                        <Input data-testid="rag-search-limit" type="number" placeholder="5" />
                      </Form.Item>
                    </Space>
                    <Button data-testid="rag-search" type="primary" htmlType="submit" loading={ragSearchMutation.isPending}>Search</Button>
                  </Form>
                </Card>
                <Table<Record<string, unknown>>
                  rowKey={(row) => `${String(row.path || '')}:${String(row.chunk || '')}:${String(row.hash || '')}`}
                  dataSource={ragSearchResults?.matches || []}
                  pagination={false}
                  columns={[
                    { title: 'Score', dataIndex: 'score', width: 90 },
                    { title: 'Source', render: (_value, row) => <Tag>{String(row.path || '')}#{String(row.chunk || '')}</Tag> },
                    { title: 'Text', dataIndex: 'text', render: (value: string) => <Typography.Paragraph ellipsis={{ rows: 3 }}>{value}</Typography.Paragraph> }
                  ]}
                />
                <Table<Record<string, unknown>>
                  rowKey={(row) => String(row.id)}
                  dataSource={localRag?.index || []}
                  pagination={false}
                  columns={[
                    { title: 'Collection', dataIndex: 'name' },
                    { title: 'Documents', dataIndex: 'documents' },
                    { title: 'Files', dataIndex: 'files' },
                    { title: 'Indexed', dataIndex: 'indexed_at', render: (value: number) => value ? new Date(value * 1000).toLocaleString() : 'Never' }
                  ]}
                />
              </Space>
            )
          },
          {
            key: 'replay',
            label: 'Trace Replay',
            children: (
              <Space direction="vertical" size={16} className="pageStack">
                {replayError ? <Alert type="error" showIcon message={replayError} /> : null}
                <Card title="Replay Source">
                  <Form
                    form={replayForm}
                    layout="vertical"
                    initialValues={{ source_type: 'trace', target: 'original', max_tokens: '512' }}
                    onFinish={(values) => replayMutation.mutate(values)}
                  >
                    <Space wrap>
                      <Form.Item name="source_type" label="Source">
                        <Select
                          data-testid="replay-source-type"
                          options={[{ value: 'trace', label: 'Trace' }, { value: 'chat', label: 'Chat' }]}
                        />
                      </Form.Item>
                      <Form.Item name="source_id" label="Source ID" rules={[{ required: true }]}>
                        <Input data-testid="replay-source-id" placeholder="trace_id or chat_id" />
                      </Form.Item>
                      <Form.Item name="target" label="Target">
                        <Select
                          data-testid="replay-target"
                          options={[
                            { value: 'original', label: 'Original' },
                            { value: 'default', label: 'Default' },
                            { value: 'selected', label: 'Selected' },
                            { value: 'comparison', label: 'Comparison' }
                          ]}
                        />
                      </Form.Item>
                    </Space>
                    <Form.Item name="models" label="Models">
                      <Input data-testid="replay-models" placeholder="model-a, model-b for selected/comparison" />
                    </Form.Item>
                    <Space wrap>
                      <Form.Item name="max_tokens" label="Max Tokens">
                        <Input data-testid="replay-max-tokens" type="number" />
                      </Form.Item>
                      <Form.Item name="temperature" label="Temperature">
                        <Input data-testid="replay-temperature" type="number" step="0.1" />
                      </Form.Item>
                    </Space>
                    <Form.Item name="baseline_text" label="Baseline Text">
                      <Input.TextArea data-testid="replay-baseline" rows={3} />
                    </Form.Item>
                    <Space wrap>
                      <Button
                        data-testid="replay-snapshot"
                        onClick={() => replaySnapshotMutation.mutate(replayForm.getFieldsValue())}
                        loading={replaySnapshotMutation.isPending}
                      >
                        Snapshot
                      </Button>
                      <Button data-testid="replay-run" type="primary" htmlType="submit" disabled={!canEdit} loading={replayMutation.isPending}>
                        Run replay
                      </Button>
                    </Space>
                  </Form>
                </Card>
                {replaySnapshot ? (
                  <Card title="Replay Snapshot" data-testid="replay-snapshot-output">
                    <Space wrap>
                      <Tag color={replaySnapshot.available ? 'green' : 'red'}>{replaySnapshot.available ? 'Available' : 'Unavailable'}</Tag>
                      <Tag>{replaySnapshot.redaction}</Tag>
                      <Tag>{replaySnapshot.model || 'model n/a'}</Tag>
                    </Space>
                    {replaySnapshot.limitations?.length ? <Alert type="warning" showIcon message={replaySnapshot.limitations.join(' ')} /> : null}
                    <Typography.Text type="secondary">{(replaySnapshot.messages || []).length} messages captured.</Typography.Text>
                    <details>
                      <summary>Raw payload</summary>
                      <pre className="templatePreview">{JSON.stringify(replaySnapshot.messages || [], null, 2)}</pre>
                    </details>
                  </Card>
                ) : null}
                {replayResult ? (
                  <Card title="Replay Result" data-testid="replay-result-output">
                    <Space wrap>
                      <Tag>{replayResult.id}</Tag>
                      <Tag>{String(replayResult.summary?.models || replayResult.results?.length || 0)} models</Tag>
                      <Tag>${String(replayResult.summary?.total_cost_usd || 0)}</Tag>
                    </Space>
                    <Typography.Text type="secondary">{(replayResult.results || []).map((row) => `${String(row.model || 'model n/a')}: ${row.ok ? 'ok' : 'error'}`).join(', ') || 'No per-model results.'}</Typography.Text>
                    <details>
                      <summary>Raw payload</summary>
                      <pre className="templatePreview">{JSON.stringify(replayResult, null, 2)}</pre>
                    </details>
                  </Card>
                ) : null}
                <Table<ReplayRecord>
                  rowKey="id"
                  dataSource={replays}
                  pagination={false}
                  columns={[
                    { title: 'Replay', dataIndex: 'id' },
                    { title: 'Source', render: (_value, record) => `${String(record.source?.type || '')}:${String(record.source?.id || '')}` },
                    { title: 'Targets', render: (_value, record) => (record.targets || []).join(', ') },
                    { title: 'Models', render: (_value, record) => String(record.summary?.models || record.results?.length || 0) },
                    { title: 'Cost', render: (_value, record) => `$${String(record.summary?.total_cost_usd || 0)}` },
                    { title: 'Created', dataIndex: 'created_at', render: (value: number) => value ? new Date(value * 1000).toLocaleString() : 'n/a' }
                  ]}
                />
              </Space>
            )
          },
          {
            key: 'bundles',
            label: 'Workspace Bundles',
            children: (
              <Space direction="vertical" size={16} className="pageStack">
                {bundleError ? <Alert type="error" showIcon message={bundleError} /> : null}
                <Card title="Bundle Controls">
                  <Space direction="vertical" size={12} className="pageStack">
                    <Select
                      data-testid="bundle-sections"
                      mode="multiple"
                      value={bundleSections}
                      onChange={setBundleSections}
                      options={[
                        { value: 'model_registry', label: 'Model registry' },
                        { value: 'gateway_policy', label: 'Gateway policy' },
                        { value: 'eval_datasets', label: 'Eval datasets' },
                        { value: 'comparison_reports', label: 'Comparison reports' },
                        { value: 'release_reports', label: 'Release reports' },
                        { value: 'prompt_templates', label: 'Prompt templates' },
                        { value: 'run_profiles', label: 'Run profiles' }
                      ]}
                    />
                    <Space wrap>
                      <Button data-testid="bundle-export" type="primary" onClick={() => workspaceBundleExportMutation.mutate()} loading={workspaceBundleExportMutation.isPending}>
                        Export
                      </Button>
                      <Button
                        data-testid="bundle-preview"
                        onClick={() => {
                          try {
                            workspaceBundlePreviewMutation.mutate();
                          } catch (error) {
                            setBundleError('Bundle JSON must be a valid object.');
                          }
                        }}
                        loading={workspaceBundlePreviewMutation.isPending}
                      >
                        Preview import
                      </Button>
                      <Button
                        data-testid="bundle-import"
                        danger
                        disabled={!canEdit || !bundlePreview || bundlePreview.blocking}
                        onClick={() => {
                          try {
                            workspaceBundleImportMutation.mutate();
                          } catch (error) {
                            setBundleError('Bundle JSON must be a valid object.');
                          }
                        }}
                        loading={workspaceBundleImportMutation.isPending}
                      >
                        Import
                      </Button>
                    </Space>
                    <Input.TextArea
                      data-testid="bundle-import-json"
                      rows={8}
                      value={bundleImportJson}
                      onChange={(event) => setBundleImportJson(event.target.value)}
                      placeholder='{"manifest":{"schema_version":1},"sections":{}}'
                    />
                  </Space>
                </Card>
                {bundleExportResult ? (
                  <Alert
                    data-testid="bundle-export-result"
                    type="success"
                    showIcon
                    message={`Exported ${bundleExportResult.bundle_id}`}
                    description={bundleExportResult.path}
                  />
                ) : null}
                {bundlePreview ? (
                  <Card title="Import Preview" data-testid="bundle-preview-result">
                    <Space wrap>
                      <Tag color={bundlePreview.blocking ? 'red' : 'green'}>{bundlePreview.blocking ? 'Blocked' : 'Ready'}</Tag>
                      <Tag>{bundlePreview.selected_sections.join(', ') || 'no sections'}</Tag>
                      <Tag>{bundlePreview.issues.length} issues</Tag>
                      {bundlePreview.applied ? <Tag>{bundlePreview.applied.join(', ') || 'nothing applied'}</Tag> : null}
                    </Space>
                    <Table<Record<string, unknown>>
                      rowKey={(row, index) => `${String(row.code || 'issue')}-${index}`}
                      dataSource={bundlePreview.issues}
                      pagination={false}
                      columns={[
                        { title: 'Severity', dataIndex: 'severity' },
                        { title: 'Code', dataIndex: 'code' },
                        { title: 'Message', dataIndex: 'message' },
                        { title: 'Details', dataIndex: 'details', render: (value: unknown) => JSON.stringify(value || {}) }
                      ]}
                    />
                  </Card>
                ) : null}
                <Table<WorkspaceBundleSummary>
                  rowKey="id"
                  dataSource={workspaceBundles}
                  pagination={false}
                  columns={[
                    { title: 'Bundle', dataIndex: 'id' },
                    { title: 'Sections', render: (_value, record) => (record.sections || []).join(', ') },
                    { title: 'Redaction', render: (_value, record) => record.redaction?.contains_sensitive ? `${String(record.redaction.redacted_values || 0)} redacted` : 'clean' },
                    { title: 'Path', dataIndex: 'path' },
                    { title: 'Created', dataIndex: 'created_at', render: (value: number) => value ? new Date(value * 1000).toLocaleString() : 'n/a' }
                  ]}
                />
              </Space>
            )
          }
        ]}
      />
    </Space>
  );
}
