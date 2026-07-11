import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Alert, Button, Card, Space, Table, Tag, Typography } from 'antd';
import 'antd/dist/reset.css';
import { DecisionExplanation, ReportingExportResult, explainObserveDecision, exportObserveReporting, getMeCapabilities, getObserve } from '../api/generated/v2Client';
import { errorText } from '../utils/errors';

function money(value: unknown): string {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? `$${parsed.toFixed(4)}` : '$0.0000';
}

function list(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((row) => row && typeof row === 'object') as Array<Record<string, unknown>> : [];
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function auditExplanationRecord(row: Record<string, unknown>): Record<string, unknown> {
  const request = record(row.request);
  const rest = { ...row };
  delete rest.request;
  delete rest.related_links;
  return {
    ...rest,
    path: row.request_path || request.path,
    actor: record(row.actor),
    policy_decision: { ...record(request.policy_decision) }
  };
}

export default function ObservePage() {
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: getMeCapabilities, retry: false });
  const observe = useQuery({ queryKey: ['observe'], queryFn: () => getObserve(7, 50, 50), refetchInterval: 30000 });
  const [explanation, setExplanation] = useState<DecisionExplanation | null>(null);
  const [exportResult, setExportResult] = useState<ReportingExportResult | null>(null);
  const explainMutation = useMutation({
    mutationFn: (payload: { trace_id?: string; type?: string; record?: Record<string, unknown> }) => explainObserveDecision(payload),
    onSuccess: setExplanation
  });
  const exportMutation = useMutation({
    mutationFn: () => exportObserveReporting({ format: 'duckdb' }),
    onSuccess: (result) => {
      setExportResult(result);
      observe.refetch();
    }
  });
  const canView = capabilities.data?.capabilities['billing.view']?.allowed ?? false;
  const payload = observe.data;
  const consoleStatus = record(payload?.console);
  const cost = record(payload?.cost);
  const analytics = record(payload?.analytics);
  const providerHealth = record(payload?.provider_health);
  const audit = record(payload?.audit);
  const evals = record(payload?.evals);
  const evalSummary = record(evals.summary);
  const telemetry = record(payload?.telemetry);
  const telemetryMetrics = record(telemetry.metrics);
  const telemetryExporter = record(telemetry.exporter);
  const telemetryPrivacy = record(telemetry.privacy);
  const telemetryPolicy = record(telemetry.policy);
  const reportingExport = record(payload?.reporting_export);
  const reportingIntegrations = record(payload?.reporting_integrations);
  const traces = list(payload?.traces);
  const auditRows = list(audit.records);
  const evalDatasets = list(evals.datasets);
  const evalRuns = list(evals.runs);
  const metricFamilies = strings(telemetry.metric_families);
  const labelKeys = strings(telemetry.label_keys);
  const findings = list(providerHealth.findings);
  const analyticsSummary = record(analytics.summary);

  return (
    <Space direction="vertical" size={16} className="pageStack">
      <Card>
        <Space direction="vertical" size={8}>
          <Typography.Title level={3}>Observe</Typography.Title>
          <Typography.Text type="secondary">Trace, cost, provider health, audit, and reporting status from the v2 API.</Typography.Text>
          <Space wrap>
            <Tag color={canView ? 'blue' : 'default'}>{canView ? 'Reporting allowed' : 'Reporting disabled'}</Tag>
            <Tag color={String(consoleStatus.status || '') === 'ok' ? 'green' : 'orange'}>{String(consoleStatus.status || 'unknown')}</Tag>
            <Tag>{traces.length} traces</Tag>
            <Tag>{auditRows.length} audit rows</Tag>
            <Tag>{evalRuns.length} eval runs</Tag>
            <Tag>{findings.length} findings</Tag>
          </Space>
        </Space>
      </Card>
      {!canView ? <Alert type="info" showIcon message="Viewing reporting data requires billing/reporting permission." /> : null}
      {observe.error ? <Alert type="error" showIcon message={errorText(observe.error)} /> : null}
      <Space wrap data-testid="observe-summary">
        <Card className="metricCard">
          <Typography.Text type="secondary">Last 24h</Typography.Text>
          <Typography.Title level={4}>{money(cost.last_24h_total_usd ?? cost.last_24h_usd ?? analyticsSummary.last_24h_total_usd)}</Typography.Title>
        </Card>
        <Card className="metricCard">
          <Typography.Text type="secondary">Month</Typography.Text>
          <Typography.Title level={4}>{money(cost.month_total_usd ?? cost.month_to_date_total_usd)}</Typography.Title>
        </Card>
        <Card className="metricCard">
          <Typography.Text type="secondary">Requests</Typography.Text>
          <Typography.Title level={4}>{String(analyticsSummary.requests ?? analyticsSummary.total_requests ?? traces.length)}</Typography.Title>
        </Card>
        <Card className="metricCard">
          <Typography.Text type="secondary">Reporting Export</Typography.Text>
          <Typography.Title level={4}>{String(reportingExport.status || reportingExport.state || 'ready')}</Typography.Title>
        </Card>
        <Card className="metricCard">
          <Typography.Text type="secondary">Eval Passes</Typography.Text>
          <Typography.Title level={4}>{String(Number(evalSummary.requests || 0) - Number(evalSummary.failures || 0))}/{String(evalSummary.requests || 0)}</Typography.Title>
        </Card>
        <Card className="metricCard">
          <Typography.Text type="secondary">Telemetry Policy</Typography.Text>
          <Typography.Title level={4}>{String(telemetryPolicy.status || 'unknown')}</Typography.Title>
        </Card>
      </Space>
      <Card title="Recent Traces" data-testid="observe-traces">
        <Table<Record<string, unknown>>
          rowKey={(row, index) => String(row.trace_id || index)}
          dataSource={traces}
          pagination={{ pageSize: 8 }}
          columns={[
            { title: 'Trace', dataIndex: 'trace_id' },
            { title: 'Status', dataIndex: 'status', render: (value: string) => <Tag color={value === 'ok' || value === 'success' ? 'green' : value === 'error' ? 'red' : 'default'}>{value || 'unknown'}</Tag> },
            { title: 'Action', dataIndex: 'action' },
            { title: 'Model', render: (_value, row) => String(row.routed_model || row.requested_model || '') },
            { title: 'Latency', dataIndex: 'latency_ms', render: (value: unknown) => value === undefined ? '' : `${String(value)} ms` },
            { title: 'Cost', dataIndex: 'cost_usd', render: money },
            {
              title: 'Explain',
              render: (_value, row) => (
                <Button
                  data-testid="observe-explain-trace"
                  size="small"
                  disabled={!row.trace_id}
                  loading={explainMutation.isPending}
                  onClick={() => explainMutation.mutate({ trace_id: String(row.trace_id || '') })}
                >
                  Explain
                </Button>
              )
            }
          ]}
        />
      </Card>
      {explanation ? (
        <Card title="Decision Explanation" data-testid="observe-decision-explanation">
          <Space wrap>
            <Tag>{explanation.type}</Tag>
            <Tag>{explanation.selected_action}</Tag>
            <Tag>{explanation.confidence}</Tag>
            <Tag>{explanation.deterministic ? 'Deterministic' : 'Inferred'}</Tag>
          </Space>
          <Typography.Paragraph>{explanation.reason}</Typography.Paragraph>
          <pre className="templatePreview">{JSON.stringify(explanation, null, 2)}</pre>
        </Card>
      ) : null}
      <Card title="Provider Findings" data-testid="observe-provider-findings">
        <Table<Record<string, unknown>>
          rowKey={(row, index) => `${String(row.type || row.title || 'finding')}-${index}`}
          dataSource={findings}
          pagination={false}
          columns={[
            { title: 'Severity', dataIndex: 'severity' },
            { title: 'Type', dataIndex: 'type' },
            { title: 'Title', dataIndex: 'title' },
            { title: 'Detail', dataIndex: 'detail' }
          ]}
        />
      </Card>
      <Card title="Eval Runs" data-testid="observe-evals">
        <Space direction="vertical" size={12} className="pageStack">
          <Space wrap>
            <Tag>{String(evalSummary.datasets ?? evalDatasets.length)} datasets</Tag>
            <Tag>{String(evalSummary.runs ?? evalRuns.length)} runs</Tag>
            <Tag>{money(evalSummary.total_cost_usd)}</Tag>
          </Space>
          <Table<Record<string, unknown>>
            rowKey={(row, index) => String(row.id || index)}
            dataSource={evalRuns}
            pagination={{ pageSize: 6 }}
            columns={[
              { title: 'Run', dataIndex: 'id' },
              { title: 'Dataset', render: (_value, row) => String(record(row.dataset).name || record(row.dataset).id || row.dataset || '') },
              { title: 'Models', render: (_value, row) => Array.isArray(row.models) ? row.models.join(', ') : String(row.models || '') },
              { title: 'Examples', dataIndex: 'example_count' },
              {
                title: 'Requests',
                render: (_value, row) => list(row.summary).reduce((total, item) => total + Number(item.requests || 0), 0)
              },
              {
                title: 'Cost',
                render: (_value, row) => money(list(row.summary).reduce((total, item) => total + Number(item.total_cost_usd || 0), 0))
              }
            ]}
          />
        </Space>
      </Card>
      <Card title="Telemetry" data-testid="observe-telemetry">
        <Space direction="vertical" size={12} className="pageStack">
          <Space wrap>
            <Tag color={telemetryMetrics.reachable ? 'green' : 'orange'}>{telemetryMetrics.reachable ? 'Metrics reachable' : 'Metrics unavailable'}</Tag>
            <Tag color={telemetryExporter.enabled ? 'blue' : 'default'}>{telemetryExporter.enabled ? 'OTEL enabled' : 'OTEL disabled'}</Tag>
            <Tag color={telemetryPolicy.status === 'pass' ? 'green' : 'orange'}>{String(telemetryPolicy.status || 'unknown')}</Tag>
            <Tag>{String(telemetryMetrics.series_count ?? metricFamilies.length)} series</Tag>
            <Tag>{labelKeys.length} labels</Tag>
          </Space>
          <Typography.Text type="secondary">Excluded fields: {strings(telemetryPolicy.sensitive_fields_excluded ?? telemetryPrivacy.excluded).join(', ')}</Typography.Text>
          <Table<Record<string, unknown>>
            rowKey={(row) => String(row.family)}
            dataSource={metricFamilies.slice(0, 12).map((family) => ({ family }))}
            pagination={false}
            columns={[
              { title: 'Metric Family', dataIndex: 'family' }
            ]}
          />
          <pre className="templatePreview">{JSON.stringify({ exporter: telemetryExporter, policy: telemetryPolicy, label_keys: labelKeys }, null, 2)}</pre>
        </Space>
      </Card>
      <Card title="Audit" data-testid="observe-audit">
        <Table<Record<string, unknown>>
          rowKey={(row, index) => `${String(row.timestamp || '')}-${String(row.action || '')}-${index}`}
          dataSource={auditRows}
          pagination={{ pageSize: 8 }}
          columns={[
            { title: 'Action', dataIndex: 'action' },
            { title: 'Outcome', dataIndex: 'outcome' },
            { title: 'Permission', dataIndex: 'permission' },
            { title: 'Status', dataIndex: 'status' },
            {
              title: 'Explain',
              render: (_value, row) => (
                <Button
                  data-testid="observe-explain-audit"
                  size="small"
                  loading={explainMutation.isPending}
                  onClick={() => explainMutation.mutate({ record: auditExplanationRecord(row) })}
                >
                  Explain
                </Button>
              )
            }
          ]}
        />
      </Card>
      <Card
        title="Reporting Integrations"
        data-testid="observe-reporting"
        extra={
          <Button
            data-testid="observe-export-reporting"
            loading={exportMutation.isPending}
            onClick={() => exportMutation.mutate()}
          >
            Export
          </Button>
        }
      >
        {exportMutation.error ? <Alert type="error" showIcon message={errorText(exportMutation.error)} /> : null}
        {exportResult ? (
          <Alert
            data-testid="observe-reporting-export-result"
            type="success"
            showIcon
            message={`Exported ${exportResult.format} reporting database`}
            description={`${exportResult.path} (${exportResult.redaction_mode || 'default_safe'})`}
          />
        ) : null}
        <pre className="templatePreview">{JSON.stringify({ reporting_export: reportingExport, reporting_integrations: reportingIntegrations }, null, 2)}</pre>
      </Card>
    </Space>
  );
}
