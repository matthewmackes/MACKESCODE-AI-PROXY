import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Card, Form, Input, Select, Space, Table, Tag, Typography } from 'antd';
import 'antd/dist/reset.css';
import {
  acquireConsoleTuiControl,
  captureCodeSession,
  ConsoleCommand,
  CodeSessionStartPayload,
  dispatchConsoleCommand,
  getConsoleCommands,
  getRunWorkspace,
  getCodeSessionDefaults,
  getConsoleOverview,
  getConsoleTuiStatus,
  getMeCapabilities,
  getTmuxWorkspace,
  PermissionPreview,
  previewCodeSessionPermissions,
  previewPromptTemplate,
  PromptTemplate,
  renameTmuxSession,
  releaseConsoleTuiControl,
  captureTmuxSession,
  sendCodeSessionInput,
  sendTmuxKey,
  sendTmuxText,
  startCodeSession,
  stopCodeSession,
  stopTmuxSession,
  TmuxWorkspacePayload
} from '../api/generated/v2Client';
import TmuxTerminal from '../components/TmuxTerminal';
import TuiTerminal from '../components/TuiTerminal';
import { apiEndpointUrl } from '../api/auth';
import { errorText } from '../utils/errors';

const iconBase = '/branding/Mackes-Carbon/scalable';

function CarbonIcon({ path, label }: { path: string; label: string }) {
  return <img className="carbonIcon" src={`${iconBase}/${path}`} alt="" title={label} aria-hidden="true" />;
}

function valueText(value: unknown, fallback = 'n/a'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString() : fallback;
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  return String(value);
}

function money(value: unknown): string {
  const amount = typeof value === 'number' ? value : Number(value || 0);
  return Number.isFinite(amount) ? `$${amount.toFixed(4)}` : '$0.0000';
}

function jsonObject(value: string): Record<string, unknown> {
  if (!value.trim()) return {};
  const parsed = JSON.parse(value);
  return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
}

function clientId(): string {
  const browserCrypto = globalThis.crypto;
  if (typeof browserCrypto?.randomUUID === 'function') {
    return browserCrypto.randomUUID();
  }
  if (typeof browserCrypto?.getRandomValues === 'function') {
    const bytes = new Uint8Array(16);
    browserCrypto.getRandomValues(bytes);
    return `client-${Array.from(bytes, (item) => item.toString(16).padStart(2, '0')).join('')}`;
  }
  return `client-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function terminalUrl(name: string, workspace?: TmuxWorkspacePayload): string {
  const terminal = workspace?.terminal;
  const url = new URL(apiEndpointUrl(terminal?.path || '/terminal', { defaultPort: terminal?.default_legacy_port }));
  url.searchParams.set(terminal?.query_param || 'name', name);
  return url.toString();
}

export default function ConsolePage() {
  const queryClient = useQueryClient();
  const client = useMemo(clientId, []);
  const [controller, setController] = useState(false);
  const [codeForm] = Form.useForm();
  const [selectedSession, setSelectedSession] = useState('');
  const [sessionInput, setSessionInput] = useState('');
  const [sessionScreen, setSessionScreen] = useState('');
  const [sessionRename, setSessionRename] = useState('');
  const [tmuxAttachActive, setTmuxAttachActive] = useState(false);
  const [templateValues, setTemplateValues] = useState('{"goal":"complete the task","audience":"operators"}');
  const [templateApplyError, setTemplateApplyError] = useState('');
  const [permissionPreview, setPermissionPreview] = useState<PermissionPreview | null>(null);
  const [commandQuery, setCommandQuery] = useState('');
  const [commandDispatchResult, setCommandDispatchResult] = useState('');
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: getMeCapabilities, retry: false });
  const status = useQuery({ queryKey: ['tui-status'], queryFn: getConsoleTuiStatus, refetchInterval: 5000 });
  const overview = useQuery({ queryKey: ['console-overview'], queryFn: getConsoleOverview, refetchInterval: 10000 });
  const tmuxWorkspace = useQuery({ queryKey: ['tmux-workspace'], queryFn: getTmuxWorkspace, refetchInterval: 5000 });
  const commands = useQuery({ queryKey: ['console-commands', commandQuery, selectedSession], queryFn: () => getConsoleCommands(commandQuery, { session: selectedSession }), retry: false });
  const defaults = useQuery({ queryKey: ['code-session-defaults'], queryFn: getCodeSessionDefaults });
  const runWorkspace = useQuery({ queryKey: ['run-workspace'], queryFn: getRunWorkspace });
  const canControlTui = capabilities.data?.capabilities['tui.control']?.allowed ?? false;
  const canControlTmux = capabilities.data?.capabilities['tmux.control']?.allowed ?? false;
  const errors = Object.entries(overview.data?.errors ?? {});
  const summary = overview.data?.summary;
  const sessions = overview.data?.sessions ?? [];
  const tmuxSessions = tmuxWorkspace.data?.sessions ?? sessions;
  const tmuxSummary = tmuxWorkspace.data?.summary;
  const tmuxAllowedKeys = tmuxWorkspace.data?.allowed_keys ?? [];
  const tasks = overview.data?.tasks ?? [];
  const templates = runWorkspace.data?.prompt_templates ?? [];
  useEffect(() => {
    if (!defaults.data) return;
    codeForm.setFieldsValue({
      name: defaults.data.default_name,
      project_dir: defaults.data.default_project_dir,
      model: defaults.data.default_model,
      permission_mode: 'acceptEdits',
      run_mode: 'interactive',
      profile: 'builder'
    });
  }, [codeForm, defaults.data]);
  useEffect(() => {
    setTmuxAttachActive(false);
  }, [selectedSession]);
  const acquire = useMutation({
    mutationFn: () => acquireConsoleTuiControl(client),
    onSuccess: (payload) => {
      setController(payload.lease.holder === client);
      queryClient.invalidateQueries({ queryKey: ['tui-status'] });
    }
  });
  const release = useMutation({
    mutationFn: () => releaseConsoleTuiControl(client),
    onSuccess: () => {
      setController(false);
      queryClient.invalidateQueries({ queryKey: ['tui-status'] });
    }
  });
  const startSession = useMutation({
    mutationFn: (payload: CodeSessionStartPayload) => startCodeSession(payload),
    onSuccess: (payload) => {
      const name = valueText(payload.name || payload.display_name, '');
      if (name) {
        setSelectedSession(name);
        setSessionRename(name);
      }
      queryClient.invalidateQueries({ queryKey: ['console-overview'] });
      queryClient.invalidateQueries({ queryKey: ['tmux-workspace'] });
    }
  });
  const captureSession = useMutation({
    mutationFn: (name: string) => captureCodeSession(name),
    onSuccess: (payload) => setSessionScreen(payload.screen || '')
  });
  const captureTmux = useMutation({
    mutationFn: (name: string) => captureTmuxSession(name),
    onSuccess: (payload) => setSessionScreen(payload.screen || '')
  });
  const sendSessionInput = useMutation({
    mutationFn: () => sendCodeSessionInput(selectedSession, sessionInput, true),
    onSuccess: () => {
      setSessionInput('');
      setTimeout(() => selectedSession && captureSession.mutate(selectedSession), 250);
    }
  });
  const sendTmuxInput = useMutation({
    mutationFn: (enter: boolean) => sendTmuxText(selectedSession, sessionInput, enter),
    onSuccess: () => {
      setSessionInput('');
      setTimeout(() => selectedSession && captureTmux.mutate(selectedSession), 250);
    }
  });
  const sendTmuxControlKey = useMutation({
    mutationFn: (key: string) => sendTmuxKey(selectedSession, key),
    onSuccess: () => setTimeout(() => selectedSession && captureTmux.mutate(selectedSession), 250)
  });
  const renameTmux = useMutation({
    mutationFn: () => renameTmuxSession(selectedSession, sessionRename || selectedSession, sessionRename || selectedSession),
    onSuccess: (payload) => {
      const name = valueText(payload.name, selectedSession);
      setSelectedSession(name);
      setSessionRename(valueText(payload.display_name || payload.name, name));
      queryClient.invalidateQueries({ queryKey: ['tmux-workspace'] });
      queryClient.invalidateQueries({ queryKey: ['console-overview'] });
    }
  });
  const stopSession = useMutation({
    mutationFn: (name: string) => stopCodeSession(name),
    onSuccess: () => {
      setSelectedSession('');
      setSessionRename('');
      setSessionScreen('');
      queryClient.invalidateQueries({ queryKey: ['console-overview'] });
      queryClient.invalidateQueries({ queryKey: ['tmux-workspace'] });
    }
  });
  const stopTmux = useMutation({
    mutationFn: (name: string) => stopTmuxSession(name),
    onSuccess: () => {
      setSelectedSession('');
      setSessionRename('');
      setSessionScreen('');
      queryClient.invalidateQueries({ queryKey: ['tmux-workspace'] });
      queryClient.invalidateQueries({ queryKey: ['console-overview'] });
    }
  });
  const applyTemplate = useMutation({
    mutationFn: (template: PromptTemplate) => previewPromptTemplate({
      body: template.body,
      variables: template.variables,
      values: jsonObject(templateValues)
    }),
    onSuccess: (payload) => {
      setTemplateApplyError('');
      codeForm.setFieldsValue({ print_prompt: payload.preview.rendered });
    },
    onError: (error) => setTemplateApplyError(errorText(error))
  });
  const previewPermissions = useMutation({
    mutationFn: (payload: CodeSessionStartPayload) => previewCodeSessionPermissions(payload),
    onSuccess: (payload) => setPermissionPreview(payload.permission_preview)
  });
  const dispatchCommand = useMutation({
    mutationFn: (command: ConsoleCommand) => dispatchConsoleCommand(command.id, { session: selectedSession }),
    onSuccess: (payload) => setCommandDispatchResult(`${payload.command.title}: ${String(payload.action?.type || 'action')}`),
    onError: (error) => setCommandDispatchResult(errorText(error))
  });

  const handleApplyTemplate = (template: PromptTemplate) => {
    try {
      applyTemplate.mutate(template);
    } catch (error) {
      setTemplateApplyError('Template values must be a JSON object.');
    }
  };

  const onProfileChange = (profile: string) => {
    if (profile === 'careful') {
      codeForm.setFieldsValue({ permission_mode: 'plan', run_mode: 'interactive' });
    } else if (profile === 'fullauto') {
      codeForm.setFieldsValue({ permission_mode: 'bypassPermissions', run_mode: 'interactive' });
    } else if (profile === 'review') {
      codeForm.setFieldsValue({ permission_mode: 'manual', run_mode: 'interactive' });
    } else if (profile === 'background') {
      codeForm.setFieldsValue({ permission_mode: 'acceptEdits', run_mode: 'background' });
    } else {
      codeForm.setFieldsValue({ permission_mode: 'acceptEdits', run_mode: 'interactive' });
    }
  };

  const launchCodeSession = (values: CodeSessionStartPayload) => {
    startSession.mutate({
      ...values,
      display_name: values.name,
      new_session: true,
      cols: 120,
      rows: 40
    });
  };

  return (
    <Space direction="vertical" size={16} className="pageStack">
      <Card className="consoleHeader">
        <Space direction="vertical" size={8}>
          <Typography.Title level={3}>Console</Typography.Title>
          <Typography.Text type="secondary">Standing proxy TUI connection for local operations.</Typography.Text>
          <Space wrap>
            <Tag color={status.data?.running ? 'green' : 'red'}>{status.data?.running ? 'TUI running' : 'TUI unavailable'}</Tag>
            <Tag>{controller ? 'You control input' : 'Read-only'}</Tag>
            <Tag color={canControlTui ? 'blue' : 'default'}>{canControlTui ? 'TUI control allowed' : 'TUI control unavailable'}</Tag>
            <Button data-testid="tui-take-control" type="primary" onClick={() => acquire.mutate()} loading={acquire.isPending} disabled={controller || !canControlTui}>Take control</Button>
            <Button data-testid="tui-release-control" onClick={() => release.mutate()} loading={release.isPending} disabled={!controller}>Release</Button>
          </Space>
          {capabilities.data ? (
            <Typography.Text type="secondary">Actor: {capabilities.data.actor.id} · {capabilities.data.actor.roles.join(', ') || 'no roles'}</Typography.Text>
          ) : null}
        </Space>
      </Card>
          <TuiTerminal clientId={client} controller={controller} />
      <Card
        title={<Space><CarbonIcon path="apps/utilities-terminal-symbolic.svg" label="TMux" />TMux Workspace</Space>}
        data-testid="tmux-workspace"
      >
        <Space direction="vertical" size={16} className="pageStack">
          {!canControlTmux ? <Alert type="info" showIcon message="TMux capture and control require tmux.control permission." /> : null}
          {tmuxWorkspace.error ? <Alert type="error" showIcon message={errorText(tmuxWorkspace.error)} /> : null}
          {Object.entries(tmuxWorkspace.data?.errors ?? {}).length ? (
            <Alert
              type="warning"
              showIcon
              message="TMux state is degraded"
              description={Object.entries(tmuxWorkspace.data?.errors ?? {}).map(([key, value]) => `${key}: ${value}`).join(' · ')}
            />
          ) : null}
          <Space wrap className="tmuxSummary">
            <Tag color="blue">Sessions {tmuxSummary?.sessions_total ?? tmuxSessions.length}</Tag>
            <Tag color="green">Live {tmuxSummary?.sessions_live ?? tmuxSessions.filter((row) => row.live).length}</Tag>
            <Tag>Attached {tmuxSummary?.sessions_attached ?? tmuxSessions.filter((row) => row.attached).length}</Tag>
            <Tag>Read-only {tmuxSummary?.sessions_read_only ?? tmuxSessions.filter((row) => row.read_only || !row.live).length}</Tag>
            <Tag>Tokens {valueText(tmuxSummary?.estimated_tokens, '0')}</Tag>
            <Tag>Cost {money(tmuxSummary?.estimated_cost_usd)}</Tag>
          </Space>
          <Table<Record<string, unknown>>
            rowKey={(row) => valueText(row.name || row.display_name)}
            data-testid="tmux-session-table"
            dataSource={tmuxSessions}
            loading={tmuxWorkspace.isLoading && !tmuxSessions.length}
            pagination={{ pageSize: 5, hideOnSinglePage: true }}
            columns={[
              {
                title: 'Session',
                dataIndex: 'display_name',
                render: (_value, row) => (
                  <Space direction="vertical" size={0}>
                    <Typography.Text strong>{valueText(row.display_name || row.name)}</Typography.Text>
                    <Typography.Text type="secondary">{valueText(row.name)}</Typography.Text>
                  </Space>
                )
              },
              { title: 'State', dataIndex: 'process_status', width: 120, render: (_value, row) => <Tag color={row.live ? 'green' : 'default'}>{valueText(row.process_status || row.status)}</Tag> },
              { title: 'Attached', dataIndex: 'attached', width: 110, render: (value) => <Tag>{valueText(value)}</Tag> },
              { title: 'Windows', dataIndex: 'windows', width: 100, render: (value) => valueText(value, '0') },
              { title: 'Idle', dataIndex: 'idle_seconds', width: 110, render: (value) => `${valueText(value, '0')}s` },
              { title: 'Project', dataIndex: 'project_dir', ellipsis: true, render: (value) => valueText(value) },
              {
                title: 'Action',
                width: 210,
                render: (_value, row) => {
                  const name = valueText(row.name, '');
                  return (
                    <Space wrap>
                      <Button
                        data-testid="tmux-session-select"
                        onClick={() => {
                          setSelectedSession(name);
                          setSessionRename(valueText(row.display_name || row.name, name));
                          if (canControlTmux) captureTmux.mutate(name);
                        }}
                      >
                        Select
                      </Button>
                      <Button data-testid="tmux-session-open" href={name ? terminalUrl(name, tmuxWorkspace.data) : undefined} target="_blank" disabled={!name}>
                        Open
                      </Button>
                    </Space>
                  );
                }
              }
            ]}
          />
          <div className="tmuxControlDock" data-testid="tmux-control-dock">
            <Space wrap>
              <Select
                data-testid="tmux-session-selector"
                value={selectedSession || undefined}
                placeholder="Select TMux session"
                style={{ minWidth: 240 }}
                onChange={(name) => {
                  setSelectedSession(name);
                  setSessionRename(name);
                  if (canControlTmux) captureTmux.mutate(name);
                }}
                options={tmuxSessions.map((session) => ({ value: valueText(session.name), label: valueText(session.display_name || session.name) }))}
              />
              <Button
                data-testid="tmux-capture"
                disabled={!selectedSession || !canControlTmux}
                loading={captureTmux.isPending}
                onClick={() => captureTmux.mutate(selectedSession)}
              >
                <CarbonIcon path="actions/view-fullscreen-symbolic.svg" label="Capture" />Capture
              </Button>
              <Button
                data-testid="tmux-attach-toggle"
                type={tmuxAttachActive ? 'default' : 'primary'}
                disabled={!selectedSession || !canControlTmux}
                onClick={() => setTmuxAttachActive(true)}
              >
                <CarbonIcon path="actions/media-playback-start-symbolic.svg" label="Attach" />Attach
              </Button>
              <Button
                data-testid="tmux-attach-disconnect"
                disabled={!tmuxAttachActive}
                onClick={() => setTmuxAttachActive(false)}
              >
                Disconnect
              </Button>
              <Button data-testid="tmux-open-terminal" href={selectedSession ? terminalUrl(selectedSession, tmuxWorkspace.data) : undefined} target="_blank" disabled={!selectedSession}>
                <CarbonIcon path="actions/window-new-symbolic.svg" label="Open" />Open terminal
              </Button>
              <Button
                danger
                disabled={!selectedSession || !canControlTmux}
                loading={stopTmux.isPending}
                onClick={() => stopTmux.mutate(selectedSession)}
              >
                <CarbonIcon path="actions/process-stop-symbolic.svg" label="Stop" />Stop
              </Button>
            </Space>
            <Space.Compact block>
              <Input
                data-testid="tmux-rename-input"
                value={sessionRename}
                onChange={(event) => setSessionRename(event.target.value)}
                disabled={!selectedSession || !canControlTmux}
                placeholder="Rename selected TMux session"
              />
              <Button
                data-testid="tmux-rename"
                disabled={!selectedSession || !sessionRename || !canControlTmux}
                loading={renameTmux.isPending}
                onClick={() => renameTmux.mutate()}
              >
                Rename
              </Button>
            </Space.Compact>
            <Space.Compact block>
              <Input
                data-testid="tmux-input"
                value={sessionInput}
                onChange={(event) => setSessionInput(event.target.value)}
                disabled={!selectedSession || !canControlTmux}
                placeholder="Paste text into selected TMux session"
              />
              <Button
                data-testid="tmux-send"
                disabled={!selectedSession || !sessionInput || !canControlTmux}
                loading={sendTmuxInput.isPending}
                onClick={() => sendTmuxInput.mutate(false)}
              >
                Paste
              </Button>
              <Button
                data-testid="tmux-send-enter"
                disabled={!selectedSession || !sessionInput || !canControlTmux}
                loading={sendTmuxInput.isPending}
                onClick={() => sendTmuxInput.mutate(true)}
              >
                Send Enter
              </Button>
            </Space.Compact>
            <div className="tmuxKeyGrid" data-testid="tmux-key-grid">
              {tmuxAllowedKeys.map((key) => (
                <Button
                  key={key}
                  size="small"
                  disabled={!selectedSession || !canControlTmux}
                  loading={sendTmuxControlKey.isPending}
                  onClick={() => sendTmuxControlKey.mutate(key)}
                >
                  {key}
                </Button>
              ))}
            </div>
          </div>
          <div className="tmuxAttachDock" data-testid="tmux-attach-dock">
            <Space wrap className="tmuxAttachHeader">
              <Typography.Text strong>Live Attach</Typography.Text>
              <Tag color={tmuxAttachActive ? 'green' : 'default'}>{tmuxAttachActive ? 'Attached' : 'Detached'}</Tag>
              <Typography.Text type="secondary">{selectedSession || 'Select a session before attaching'}</Typography.Text>
            </Space>
            <TmuxTerminal active={tmuxAttachActive} canControl={canControlTmux} sessionName={selectedSession} workspace={tmuxWorkspace.data} />
          </div>
          <pre className="sessionScreen tmuxScreen" data-testid="tmux-screen">{sessionScreen || 'Select a TMux session and capture its pane.'}</pre>
        </Space>
      </Card>
      <Card title="Command Palette">
        <Space direction="vertical" size={12} className="pageStack">
          <Input.Search
            data-testid="console-command-search"
            placeholder="Search commands"
            allowClear
            value={commandQuery}
            onChange={(event) => setCommandQuery(event.target.value)}
          />
          {commandDispatchResult ? <Alert data-testid="console-command-result" type="info" showIcon message={commandDispatchResult} /> : null}
          <Table<ConsoleCommand>
            rowKey="id"
            data-testid="console-command-table"
            dataSource={commands.data?.commands || []}
            loading={commands.isLoading}
            pagination={{ pageSize: 5, hideOnSinglePage: true }}
            columns={[
              { title: 'Command', dataIndex: 'title' },
              { title: 'Group', dataIndex: 'group', width: 140 },
              { title: 'State', width: 140, render: (_value, command) => <Tag color={command.available ? 'green' : command.context_ready ? 'default' : 'orange'}>{command.available ? 'Available' : command.context_ready ? 'Denied' : 'Needs context'}</Tag> },
              {
                title: 'Action',
                width: 120,
                render: (_value, command) => (
                  <Button
                    data-testid="console-command-run"
                    disabled={!command.available}
                    loading={dispatchCommand.isPending}
                    onClick={() => dispatchCommand.mutate(command)}
                  >
                    Run
                  </Button>
                )
              }
            ]}
          />
        </Space>
      </Card>
      <Card title="Code Session Launcher" data-testid="code-session-launcher">
        <Space direction="vertical" size={16} className="pageStack">
          {!canControlTmux ? <Alert type="info" showIcon message="Code session launch requires tmux.control permission." /> : null}
          {startSession.error ? <Alert type="error" showIcon message={errorText(startSession.error)} /> : null}
          <Form form={codeForm} layout="vertical" disabled={!canControlTmux} onFinish={launchCodeSession}>
            <Space direction="vertical" size={8} className="pageStack">
              <Space wrap>
                <Form.Item name="name" label="Session Name" rules={[{ required: true }]}>
                  <Input data-testid="code-session-name" />
                </Form.Item>
                <Form.Item name="project_dir" label="Project Directory" rules={[{ required: true }]}>
                  <Input data-testid="code-session-project" />
                </Form.Item>
                <Form.Item name="model" label="Model">
                  <Select
                    data-testid="code-session-model"
                    style={{ minWidth: 220 }}
                    options={(defaults.data?.text_models ?? []).map((model) => ({ value: model, label: model }))}
                  />
                </Form.Item>
                <Form.Item name="profile" label="Profile">
                  <Select
                    data-testid="code-session-profile"
                    style={{ minWidth: 160 }}
                    onChange={onProfileChange}
                    options={(defaults.data?.profiles ?? []).map((profile) => ({ value: String(profile.key), label: String(profile.label) }))}
                  />
                </Form.Item>
              </Space>
              <Space wrap>
                <Form.Item name="permission_mode" label="Permission">
                  <Select
                    data-testid="code-session-permission"
                    style={{ minWidth: 170 }}
                    options={[
                      { value: 'acceptEdits', label: 'Accept edits' },
                      { value: 'plan', label: 'Plan' },
                      { value: 'manual', label: 'Manual' },
                      { value: 'bypassPermissions', label: 'Bypass' }
                    ]}
                  />
                </Form.Item>
                <Form.Item name="run_mode" label="Run Mode">
                  <Select
                    data-testid="code-session-run-mode"
                    style={{ minWidth: 170 }}
                    options={[
                      { value: 'interactive', label: 'Interactive' },
                      { value: 'print', label: 'Print' },
                      { value: 'json', label: 'JSON' },
                      { value: 'stream-json', label: 'Stream JSON' },
                      { value: 'background', label: 'Background' }
                    ]}
                  />
                </Form.Item>
              </Space>
              <Form.Item name="print_prompt" label="Task Prompt">
                <Input.TextArea data-testid="code-session-prompt" rows={4} placeholder="Optional prompt for print/background runs" />
              </Form.Item>
              <Card size="small" title="Prompt Templates">
                <Space direction="vertical" size={8} className="pageStack">
                  <Input.TextArea
                    data-testid="code-template-values"
                    value={templateValues}
                    onChange={(event) => setTemplateValues(event.target.value)}
                    rows={3}
                    placeholder='{"goal":"refactor safely","audience":"operators"}'
                  />
                  {templateApplyError ? <Alert type="error" showIcon message={templateApplyError} /> : null}
                  <Table<PromptTemplate>
                    rowKey="id"
                    data-testid="code-template-table"
                    dataSource={templates}
                    pagination={{ pageSize: 4, hideOnSinglePage: true }}
                    columns={[
                      { title: 'Template', dataIndex: 'name' },
                      { title: 'Tags', dataIndex: 'tags', render: (tags: string[]) => <Space wrap>{tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</Space> },
                      {
                        title: 'Action',
                        width: 110,
                        render: (_value, template) => (
                          <Button data-testid="code-template-apply" loading={applyTemplate.isPending} onClick={() => handleApplyTemplate(template)}>Apply</Button>
                        )
                      }
                    ]}
                  />
                </Space>
              </Card>
              <Space wrap>
                <Button
                  data-testid="code-session-permission-preview"
                  onClick={() => previewPermissions.mutate(codeForm.getFieldsValue())}
                  loading={previewPermissions.isPending}
                >
                  Preview permissions
                </Button>
                <Button data-testid="code-session-start" type="primary" htmlType="submit" loading={startSession.isPending}>Start code session</Button>
              </Space>
              {permissionPreview ? (
                <Card size="small" data-testid="code-permission-preview" title="Permission Preview">
                  <Space direction="vertical" size={8} className="pageStack">
                    <Space wrap>
                      <Tag color={permissionPreview.risk_level === 'critical' ? 'red' : permissionPreview.risk_level === 'high' ? 'orange' : 'blue'}>{permissionPreview.risk_level}</Tag>
                      <Tag>{permissionPreview.allows_edits ? 'edits' : 'read-only'}</Tag>
                      <Tag>{permissionPreview.allows_bash ? 'bash' : 'no bash'}</Tag>
                    </Space>
                    <Table<Record<string, unknown>>
                      rowKey={(row) => String(row.code || row.message)}
                      dataSource={permissionPreview.warnings || []}
                      pagination={false}
                      size="small"
                      columns={[
                        { title: 'Severity', dataIndex: 'severity', width: 100, render: (value: string) => <Tag color={value === 'critical' ? 'red' : value === 'high' ? 'orange' : 'default'}>{value}</Tag> },
                        { title: 'Warning', dataIndex: 'message' }
                      ]}
                    />
                    <Typography.Text type="secondary">
                      Suggested preset: {String(permissionPreview.suggested_preset?.profile || 'n/a')} / {String(permissionPreview.suggested_preset?.permission_mode || 'n/a')}
                    </Typography.Text>
                  </Space>
                </Card>
              ) : null}
            </Space>
          </Form>
          <Space wrap>
            <Select
              data-testid="code-session-selector"
              value={selectedSession || undefined}
              placeholder="Select session"
              style={{ minWidth: 240 }}
              onChange={(name) => {
                setSelectedSession(name);
                setSessionRename(name);
                captureSession.mutate(name);
              }}
              options={tmuxSessions.map((session) => ({ value: valueText(session.name), label: valueText(session.display_name || session.name) }))}
            />
            <Button data-testid="code-session-capture" disabled={!selectedSession || !canControlTmux} loading={captureSession.isPending} onClick={() => captureSession.mutate(selectedSession)}>Capture</Button>
            <Button danger disabled={!selectedSession || !canControlTmux} loading={stopSession.isPending} onClick={() => stopSession.mutate(selectedSession)}>Stop</Button>
          </Space>
          <Space.Compact block>
            <Input value={sessionInput} onChange={(event) => setSessionInput(event.target.value)} disabled={!selectedSession || !canControlTmux} placeholder="Send input to selected tmux session" />
            <Button data-testid="code-session-send" disabled={!selectedSession || !sessionInput || !canControlTmux} loading={sendSessionInput.isPending} onClick={() => sendSessionInput.mutate()}>Send</Button>
          </Space.Compact>
          <pre className="sessionScreen" data-testid="code-session-screen">{sessionScreen || 'No captured screen.'}</pre>
        </Space>
      </Card>
      <Card title="Operational State" data-testid="console-operational-state">
        <Space direction="vertical" size={16} className="pageStack">
          {errors.length ? (
            <Alert
              type="warning"
              showIcon
              message="Some service adapter state could not be loaded"
              description={errors.map(([key, value]) => `${key}: ${value}`).join(' · ')}
            />
          ) : null}
          <Space wrap>
            <Tag color="blue">Sessions {summary?.sessions_total ?? sessions.length}</Tag>
            <Tag color="green">Live {summary?.sessions_live ?? sessions.filter((row) => row.live).length}</Tag>
            <Tag>Agent sessions {summary?.agent_sessions ?? 0}</Tag>
            <Tag>Requests OK {summary?.requests_ok ?? 0}</Tag>
            <Tag color={(summary?.requests_error ?? 0) > 0 ? 'red' : 'default'}>Errors {summary?.requests_error ?? 0}</Tag>
            <Tag>Spend {money(summary?.spend_usd)}</Tag>
          </Space>
          <Table<Record<string, unknown>>
            rowKey={(row) => valueText(row.name || row.display_name)}
            data-testid="console-session-table"
            dataSource={sessions}
            pagination={{ pageSize: 6, hideOnSinglePage: true }}
            columns={[
              { title: 'Session', dataIndex: 'display_name', render: (_value, row) => valueText(row.display_name || row.name) },
              { title: 'State', dataIndex: 'process_status', render: (_value, row) => <Tag color={row.live ? 'green' : 'default'}>{valueText(row.process_status || row.status)}</Tag> },
              { title: 'Model', dataIndex: 'model_display', render: (_value, row) => valueText(row.model_display || row.model) },
              { title: 'Project', dataIndex: 'project_dir', ellipsis: true, render: (value) => valueText(value) },
              { title: 'Cost', dataIndex: 'estimated_cost_usd', render: money, width: 110 }
            ]}
          />
          <Table<Record<string, unknown>>
            rowKey={(row, index) => `${valueText(row.session, 'task')}-${index}`}
            data-testid="console-task-table"
            dataSource={tasks}
            pagination={{ pageSize: 5, hideOnSinglePage: true }}
            columns={[
              { title: 'Task Session', dataIndex: 'session', render: (value) => valueText(value) },
              { title: 'Status', dataIndex: 'status', render: (value) => <Tag>{valueText(value)}</Tag> },
              { title: 'Path', dataIndex: 'path', ellipsis: true, render: (value) => valueText(value) },
              { title: 'Last Prompt', dataIndex: 'last_prompt', ellipsis: true, render: (value) => valueText(value) }
            ]}
          />
        </Space>
      </Card>
    </Space>
  );
}
