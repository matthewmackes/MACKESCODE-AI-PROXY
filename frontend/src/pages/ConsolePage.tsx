import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Card, Input, Space, Table, Tag, Typography } from 'antd';
import 'antd/dist/reset.css';
import {
  ConsoleCommand,
  dispatchConsoleCommand,
  getConsoleCommands,
  getConsoleOverview,
  getConsoleTuiStatus,
  getMeCapabilities,
  restartConsoleTui
} from '../api/generated/v2Client';
import { errorText } from '../utils/errors';
import { money } from '../utils/format';

function valueText(value: unknown, fallback = 'n/a'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString() : fallback;
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  return String(value);
}

export default function ConsolePage() {
  const queryClient = useQueryClient();
  const [commandQuery, setCommandQuery] = useState('');
  const [commandDispatchResult, setCommandDispatchResult] = useState('');
  const [restartError, setRestartError] = useState('');
  // System Operations is a read-mostly dashboard, so a single relaxed poll keeps
  // proxy/TUI status and operational state fresh without hammering the adapters.
  const pollInterval = 15000;
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: getMeCapabilities, retry: false });
  const status = useQuery({ queryKey: ['tui-status'], queryFn: getConsoleTuiStatus, refetchInterval: pollInterval });
  const overview = useQuery({ queryKey: ['console-overview'], queryFn: getConsoleOverview, refetchInterval: pollInterval });
  const commands = useQuery({ queryKey: ['console-commands', commandQuery], queryFn: () => getConsoleCommands(commandQuery), retry: false });
  const canControlTui = capabilities.data?.capabilities['tui.control']?.allowed ?? false;
  const errors = Object.entries(overview.data?.errors ?? {});
  const summary = overview.data?.summary;
  const sessions = overview.data?.sessions ?? [];
  const tasks = overview.data?.tasks ?? [];
  const restart = useMutation({
    mutationFn: () => restartConsoleTui(),
    onSuccess: () => {
      setRestartError('');
      queryClient.invalidateQueries({ queryKey: ['tui-status'] });
    },
    onError: (error) => setRestartError(errorText(error))
  });
  const dispatchCommand = useMutation({
    mutationFn: (command: ConsoleCommand) => dispatchConsoleCommand(command.id),
    onSuccess: (payload) => setCommandDispatchResult(`${payload.command.title}: ${String(payload.action?.type || 'action')}`),
    onError: (error) => setCommandDispatchResult(errorText(error))
  });

  return (
    <Space direction="vertical" size={16} className="pageStack">
      <Card className="consoleHeader">
        <Space direction="vertical" size={8}>
          <Typography.Title level={3}>System Operations</Typography.Title>
          <Typography.Text type="secondary">Proxy status, command palette, and live operational state.</Typography.Text>
          <Space wrap>
            <Tag color={status.data?.running ? 'green' : 'red'}>{status.data?.running ? 'Proxy TUI running' : 'Proxy TUI unavailable'}</Tag>
            <Tag color={canControlTui ? 'blue' : 'default'}>{canControlTui ? 'TUI control allowed' : 'TUI control unavailable'}</Tag>
            <Button data-testid="tui-restart" onClick={() => restart.mutate()} loading={restart.isPending} disabled={!canControlTui}>Restart proxy TUI</Button>
          </Space>
          {restartError ? <Alert type="error" showIcon message={restartError} /> : null}
          {capabilities.data ? (
            <Typography.Text type="secondary">Actor: {capabilities.data.actor.id} · {capabilities.data.actor.roles.join(', ') || 'no roles'}</Typography.Text>
          ) : null}
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
