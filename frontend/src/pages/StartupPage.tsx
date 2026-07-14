import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Card, Form, Input, InputNumber, Modal, Space, Switch, Table, Tag, Typography } from 'antd';
import 'antd/dist/reset.css';
import {
  getIrcBridge,
  getMeCapabilities,
  getStartup,
  IrcBridgeConfig,
  IrcBridgePayload,
  restartIrcBridge,
  runStartupServiceAction,
  startIrcBridge,
  StartupServicePayload,
  stopIrcBridge,
  updateIrcBridgeConfig,
  updateStartupConfig
} from '../api/generated/v2Client';
import { errorText } from '../utils/errors';

function valueText(value: unknown, fallback = 'n/a'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString() : fallback;
  return String(value);
}

function statusText(row: StartupServicePayload): string {
  const status = row.status || {};
  return valueText(status.active_state || status.session_name || status.pid || (row.running ? 'running' : 'stopped'));
}

function serviceStatusColor(row: StartupServicePayload): string {
  if (row.errors?.length) return 'red';
  return row.running ? 'green' : 'default';
}

function bridgeAddress(payload?: IrcBridgePayload): string {
  const config = payload?.config;
  if (!config) return 'n/a';
  return `${config.host}:${config.port}`;
}

export default function StartupPage() {
  const queryClient = useQueryClient();
  const [ircDraft, setIrcDraft] = useState<Partial<IrcBridgeConfig>>({});
  const [message, setMessage] = useState('');
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: getMeCapabilities, retry: false });
  const startup = useQuery({ queryKey: ['startup'], queryFn: getStartup, refetchInterval: 10000 });
  const irc = useQuery({ queryKey: ['irc-bridge'], queryFn: getIrcBridge, refetchInterval: 10000 });
  const canView = capabilities.data?.capabilities['startup.view']?.allowed ?? false;
  const canAdmin = capabilities.data?.capabilities['startup.admin']?.allowed ?? false;
  const canAdminIrc = capabilities.data?.capabilities['irc.admin']?.allowed ?? false;
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['startup'] });
    queryClient.invalidateQueries({ queryKey: ['irc-bridge'] });
  };

  useEffect(() => {
    if (irc.data?.config) {
      setIrcDraft(irc.data.config);
    }
  }, [irc.data?.config]);

  const toggleBoot = useMutation({
    mutationFn: ({ serviceId, enabled }: { serviceId: string; enabled: boolean }) => updateStartupConfig({ services: { [serviceId]: { enabled } } }),
    onSuccess: () => {
      setMessage('Startup configuration updated.');
      refresh();
    },
    onError: (error) => setMessage(errorText(error))
  });

  const serviceAction = useMutation({
    mutationFn: ({ serviceId, action, confirm }: { serviceId: string; action: string; confirm?: string }) => runStartupServiceAction(serviceId, action, confirm ? { confirm } : {}),
    onSuccess: (payload) => {
      setMessage(`${payload.service_id} ${payload.action} requested.`);
      refresh();
    },
    onError: (error) => setMessage(errorText(error))
  });

  const saveIrc = useMutation({
    mutationFn: () => updateIrcBridgeConfig(ircDraft),
    onSuccess: () => {
      setMessage('IRC bridge configuration saved.');
      refresh();
    },
    onError: (error) => setMessage(errorText(error))
  });

  const ircAction = useMutation({
    mutationFn: (action: 'start' | 'stop' | 'restart') => {
      if (action === 'start') return startIrcBridge();
      if (action === 'stop') return stopIrcBridge();
      return restartIrcBridge();
    },
    onSuccess: () => {
      setMessage('IRC bridge action requested.');
      refresh();
    },
    onError: (error) => setMessage(errorText(error))
  });

  const requestAction = (row: StartupServicePayload, action: string) => {
    if (row.critical && ['stop', 'restart'].includes(action)) {
      Modal.confirm({
        title: `${action === 'stop' ? 'Stop' : 'Restart'} ${row.label}?`,
        content: 'This can interrupt active clients and may briefly disconnect the current console.',
        okText: action === 'stop' ? 'Stop service' : 'Restart service',
        okButtonProps: { danger: action === 'stop' },
        onOk: () => serviceAction.mutate({ serviceId: row.id, action, confirm: `${action}:${row.id}` })
      });
      return;
    }
    serviceAction.mutate({ serviceId: row.id, action });
  };

  if (capabilities.error) {
    return <Alert type="error" showIcon message={errorText(capabilities.error)} />;
  }

  return (
    <Space direction="vertical" size={16} className="pageStack">
      <Card className="consoleHeader">
        <Space direction="vertical" size={8}>
          <Typography.Title level={3}>Boot / Startup</Typography.Title>
          <Typography.Text type="secondary">Manage service boot policy, live process state, and the remote IRC LLM bridge.</Typography.Text>
          <Space wrap>
            <Tag color={canView ? 'blue' : 'default'}>{canView ? 'Startup view allowed' : 'Startup view unavailable'}</Tag>
            <Tag color={canAdmin ? 'green' : 'default'}>{canAdmin ? 'Startup admin allowed' : 'Read-only'}</Tag>
            <Tag color={irc.data?.listening ? 'green' : 'default'}>IRC {irc.data?.listening ? 'listening' : 'not listening'}</Tag>
            <Tag>Connect {bridgeAddress(irc.data)}</Tag>
          </Space>
          {message ? <Alert type={/failed|error|denied|required/i.test(message) ? 'error' : 'info'} showIcon message={message} /> : null}
          {startup.error ? <Alert type="error" showIcon message={errorText(startup.error)} /> : null}
          {irc.error ? <Alert type="error" showIcon message={errorText(irc.error)} /> : null}
        </Space>
      </Card>

      <Card title="Managed Services" data-testid="startup-services-card">
        <Table<StartupServicePayload>
          rowKey="id"
          data-testid="startup-services-table"
          dataSource={startup.data?.services || []}
          loading={startup.isLoading}
          pagination={false}
          columns={[
            {
              title: 'Service',
              dataIndex: 'label',
              render: (_value, row) => (
                <Space direction="vertical" size={0}>
                  <Typography.Text strong>{row.label}</Typography.Text>
                  <Typography.Text type="secondary">{row.description}</Typography.Text>
                </Space>
              )
            },
            { title: 'Kind', dataIndex: 'kind', width: 130, render: (value) => <Tag>{valueText(value)}</Tag> },
            { title: 'State', width: 140, render: (_value, row) => <Tag color={serviceStatusColor(row)}>{row.running ? 'Running' : 'Stopped'} · {statusText(row)}</Tag> },
            {
              title: 'Boot',
              width: 110,
              render: (_value, row) => (
                <Switch
                  checked={row.boot_enabled}
                  disabled={!canAdmin || toggleBoot.isPending}
                  checkedChildren="On"
                  unCheckedChildren="Off"
                  onChange={(enabled) => toggleBoot.mutate({ serviceId: row.id, enabled })}
                />
              )
            },
            {
              title: 'Actions',
              width: 280,
              render: (_value, row) => (
                <Space wrap>
                  <Button size="small" disabled={!canAdmin || serviceAction.isPending} onClick={() => requestAction(row, 'start')}>Start</Button>
                  <Button size="small" disabled={!canAdmin || serviceAction.isPending} onClick={() => requestAction(row, 'stop')}>Stop</Button>
                  <Button size="small" disabled={!canAdmin || serviceAction.isPending} onClick={() => requestAction(row, 'restart')}>Restart</Button>
                  <Button size="small" disabled={!canAdmin || serviceAction.isPending} onClick={() => requestAction(row, 'apply')}>Apply</Button>
                </Space>
              )
            }
          ]}
          expandable={{
            expandedRowRender: (row) => (
              <Space direction="vertical" className="pageStack">
                {row.errors?.length ? <Alert type="warning" showIcon message={row.errors.join(' · ')} /> : null}
                <Typography.Paragraph copyable={{ text: JSON.stringify(row.status, null, 2) }}>
                  <pre>{JSON.stringify(row.status, null, 2)}</pre>
                </Typography.Paragraph>
              </Space>
            )
          }}
        />
      </Card>

      <Card title="IRC Bridge" data-testid="irc-bridge-config-card">
        <Form layout="vertical">
          <Space wrap align="start">
            <Form.Item label="Bridge Enabled">
              <Switch
                checked={Boolean(ircDraft.enabled)}
                disabled={!canAdminIrc}
                checkedChildren="On"
                unCheckedChildren="Off"
                onChange={(enabled) => setIrcDraft((current) => ({ ...current, enabled }))}
              />
            </Form.Item>
            <Form.Item label="Host">
              <Input value={valueText(ircDraft.host, '')} disabled={!canAdminIrc} onChange={(event) => setIrcDraft((current) => ({ ...current, host: event.target.value }))} />
            </Form.Item>
            <Form.Item label="Port">
              <InputNumber min={1} max={65535} value={Number(ircDraft.port || 6667)} disabled={!canAdminIrc} onChange={(port) => setIrcDraft((current) => ({ ...current, port: Number(port || 6667) }))} />
            </Form.Item>
            <Form.Item label="Session">
              <Input value={valueText(ircDraft.session_name, '')} disabled={!canAdminIrc} onChange={(event) => setIrcDraft((current) => ({ ...current, session_name: event.target.value }))} />
            </Form.Item>
            <Form.Item label="TLS">
              <Switch
                checked={Boolean(ircDraft.tls_enabled)}
                disabled={!canAdminIrc}
                checkedChildren="On"
                unCheckedChildren="Off"
                onChange={(tls_enabled) => setIrcDraft((current) => ({ ...current, tls_enabled }))}
              />
            </Form.Item>
            <Form.Item label="TLS Cert">
              <Input value={valueText(ircDraft.tls_cert_file, '')} disabled={!canAdminIrc} onChange={(event) => setIrcDraft((current) => ({ ...current, tls_cert_file: event.target.value }))} />
            </Form.Item>
            <Form.Item label="TLS Key">
              <Input value={valueText(ircDraft.tls_key_file, '')} disabled={!canAdminIrc} onChange={(event) => setIrcDraft((current) => ({ ...current, tls_key_file: event.target.value }))} />
            </Form.Item>
          </Space>
          <Space wrap>
            <Button type="primary" disabled={!canAdminIrc} loading={saveIrc.isPending} onClick={() => saveIrc.mutate()}>Save IRC config</Button>
            <Button disabled={!canAdminIrc || ircAction.isPending} onClick={() => ircAction.mutate('start')}>Start</Button>
            <Button disabled={!canAdminIrc || ircAction.isPending} onClick={() => ircAction.mutate('stop')}>Stop</Button>
            <Button disabled={!canAdminIrc || ircAction.isPending} onClick={() => ircAction.mutate('restart')}>Restart</Button>
          </Space>
        </Form>
        <Space direction="vertical" size={8} className="pageStack">
          <Space wrap>
            <Tag color={irc.data?.tmux.running ? 'green' : 'default'}>tmux {irc.data?.tmux.running ? 'running' : 'stopped'}</Tag>
            <Tag color={irc.data?.listening ? 'green' : 'default'}>{irc.data?.listening ? 'Listening' : 'Not listening'}</Tag>
            <Tag>{irc.data?.models.length || 0} routable text models</Tag>
            <Tag>{irc.data?.metadata_log || 'metadata log unavailable'}</Tag>
          </Space>
          {irc.data?.tmux.tail ? <pre data-testid="irc-bridge-tail">{irc.data.tmux.tail}</pre> : null}
        </Space>
      </Card>
    </Space>
  );
}
