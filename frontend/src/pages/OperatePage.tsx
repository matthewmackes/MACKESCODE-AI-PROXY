import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useState, type KeyboardEvent } from 'react';
import { Alert, Button, Card, Checkbox, Collapse, Descriptions, Input, Space, Table, Tag, Typography } from 'antd';
import 'antd/dist/reset.css';
import { getMeCapabilities } from '../api/generated/v2Client';
import { acknowledgeOperateConfigDrift, getOnboarding, getOperate, importOperateRepositoryContext, launchOperateCiTriage, markOperateConfigDriftBaseline, overrideCostControl, previewOperateCiTriage, previewOperateModelDeprecation, previewOperateRepositoryContext, previewOperateRollback, runDueOperateAutomationSchedules, saveOperateEvalDataset, seedOnboardingModelTemplates, testOperateAutomation, updateCostControlThresholds, updateOperateReview, writeOperateReleaseReport } from '../api/generated/v2Client';
import type { OnboardingPayload } from '../api/generated/v2Client';
import { errorText } from '../utils/errors';
import { listValue, money, numberValue, recordValue } from '../utils/format';

function rows(payload: unknown, ...keys: string[]): Array<Record<string, unknown>> {
  const source = recordValue(payload);
  for (const key of keys) {
    const value = listValue(source[key]);
    if (value.length) return value;
  }
  return [];
}

function valueText(value: unknown, fallback = ''): string {
  return value === undefined || value === null || value === '' ? fallback : String(value);
}

function boolText(value: unknown): string {
  return value === true ? 'yes' : value === false ? 'no' : 'n/a';
}

function arrayLength(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

function paymentStatusColor(value: unknown): string {
  const status = valueText(value, 'open').toLowerCase();
  if (status === 'complete' || status === 'ready' || status === 'done') return 'green';
  if (status === 'blocked' || status === 'failed') return 'red';
  if (status === 'reviewing' || status === 'pending') return 'orange';
  return 'blue';
}

function driftSnapshotText(snapshot: Record<string, unknown>): string {
  if (!Object.keys(snapshot).length) return 'unavailable';
  const fingerprint = valueText(snapshot.sha256_short || snapshot.sha256, 'unavailable');
  const type = valueText(snapshot.type, 'unknown');
  const size = valueText(snapshot.size, 'n/a');
  return `${fingerprint} · ${type} / ${size} · JSON ${boolText(snapshot.json_valid)}`;
}

function driftRollbackParts(item: Record<string, unknown>): { backupItem: string; restoreAvailable: boolean; restoreCommand: string } {
  const current = recordValue(item.current);
  const baseline = recordValue(item.baseline);
  const rollback = recordValue(item.rollback);
  const currentRollback = recordValue(current.rollback);
  const baselineRollback = recordValue(baseline.rollback);
  const backupItem = valueText(rollback.backup_item || currentRollback.backup_item || baselineRollback.backup_item, 'none');
  const restoreCommand = valueText(rollback.restore_command || currentRollback.restore_command || baselineRollback.restore_command);
  return { backupItem, restoreAvailable: Boolean(restoreCommand), restoreCommand };
}

function driftRollbackReadinessText(item: Record<string, unknown>): string {
  const rollback = driftRollbackParts(item);
  return rollback.restoreAvailable ? `Restore available · ${rollback.backupItem}` : 'Manual compare · no direct restore target';
}

function riskColor(value: unknown): string {
  const risk = valueText(value).toLowerCase();
  if (risk === 'critical' || risk === 'high') return 'red';
  if (risk === 'medium') return 'orange';
  if (risk === 'low') return 'blue';
  return 'default';
}

function OnboardingTemplateGallery({
  data,
  canSeed,
  seedLoading,
  seedError,
  onSeed,
  onCopy,
  copiedKey
}: {
  data?: OnboardingPayload;
  canSeed: boolean;
  seedLoading: boolean;
  seedError: string;
  onSeed: () => void;
  onCopy: (text: string, key: string) => void;
  copiedKey: string;
}) {
  const modelTemplates = data?.model_templates;
  const summary = modelTemplates?.summary || { target: 0, existing: 0, missing: 0, seeded: 0 };
  const items = (modelTemplates?.items || []).slice(0, 9);
  return (
    <Card title="Golden Path Onboarding" data-testid="operate-onboarding">
      <Space direction="vertical" size={12} className="pageStack">
        <Space wrap>
          <Tag color="blue">{summary.target} routable models</Tag>
          <Tag color="green">{summary.existing} templates ready</Tag>
          <Tag color={summary.missing ? 'orange' : 'green'}>{summary.missing} missing</Tag>
          {summary.seeded ? <Tag color="purple">{summary.seeded} seeded</Tag> : null}
          <Button size="small" disabled={!canSeed || !summary.missing} loading={seedLoading} onClick={onSeed}>Seed Model Templates</Button>
        </Space>
        {seedError ? <Alert type="error" showIcon message={seedError} /> : null}
        <div className="onboardingTemplateGrid" data-testid="operate-onboarding-template-gallery">
          {items.map((item) => {
            const model = recordValue(item.model);
            const template = recordValue(item.template);
            const preview = recordValue(item.preview);
            const key = valueText(template.id || model.id || model.display_name);
            const rendered = valueText(preview.rendered || template.body);
            const variables = Array.isArray(preview.variables) ? preview.variables.map((variable) => valueText(variable)).filter(Boolean) : [];
            return (
              <article className="onboardingTemplateCard" key={key}>
                <div>
                  <span>{valueText(model.company, 'Model')}</span>
                  <strong>{valueText(model.display_name || model.id, 'Prepared model')}</strong>
                  <p>{valueText(model.family)} · {valueText(model.type)} · {valueText(model.cost_label)}</p>
                </div>
                <Space wrap>
                  <Tag color={item.status === 'missing' ? 'orange' : 'green'}>{item.status}</Tag>
                  {variables.map((variable) => <Tag key={variable}>{variable}</Tag>)}
                </Space>
                <pre className="templatePreview">{rendered.split('\n').slice(0, 8).join('\n')}</pre>
                <Button size="small" onClick={() => onCopy(rendered, key)}>{copiedKey === key ? 'Copied' : 'Copy Template'}</Button>
              </article>
            );
          })}
        </div>
      </Space>
    </Card>
  );
}

async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Remote plain-HTTP browser sessions can block clipboard writes.
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

function downloadText(filename: string, text: string, type: string): void {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function operatorHandoffItemMarkdown(item: Record<string, unknown>, index?: number): string {
  const rank = valueText(item.priority_rank, index ? String(index) : 'n/a');
  return [
    `### ${rank}. ${valueText(item.item, 'Operator-owned item')}`,
    `Urgency: ${valueText(item.urgency, 'normal')}`,
    `Owner: ${valueText(item.owner, 'Operator')}`,
    `Gate: ${valueText(item.gate_type, 'operator-decision')}`,
    `Why this matters: ${valueText(item.blocking_rationale, 'This item needs an external operator decision before the advisory ledger can be closed.')}`,
    `Needs: ${valueText(item.needs, 'Operator decision or external account state')}`,
    `Status: ${valueText(item.status, 'Open')}`,
    `Next action: ${valueText(item.next_action, 'Review the ledger row and record the operator decision.')}`,
    `Evidence required: ${valueText(item.evidence_required, 'Operator decision, external state, timestamp, and updated status.')}`,
    `Closure template: ${valueText(item.closure_template, 'Status cell: Closed <YYYY-MM-DD>: <outcome>. Evidence: <evidence summary>. Owner: Operator. Gate: operator-decision.')}`
  ].join('\n');
}

function operatorHandoffBriefMarkdown(operatorHandoff: Record<string, unknown>, items: Array<Record<string, unknown>>): string {
  const lines = [
    '# Operator Handoff Brief',
    '',
    `Generated: ${new Date().toISOString()}`,
    `Summary: ${valueText(operatorHandoff.summary, items.length ? `${items.length} operator-owned item${items.length === 1 ? '' : 's'} open` : 'No operator-owned release items are open.')}`,
    `Source: ${valueText(operatorHandoff.source, 'release candidate readiness')}`,
    '',
    '## Operator Items'
  ];
  if (!items.length) {
    lines.push('', 'No operator-owned release items are open.');
    return lines.join('\n');
  }
  lines.push('', '## Ranked Action Plan');
  items.forEach((item, index) => {
    lines.push(
      '',
      `${index + 1}. ${valueText(item.item, 'Operator-owned item')} (${valueText(item.urgency, 'normal')} · ${valueText(item.owner, 'Operator')})`,
      `   Why: ${valueText(item.blocking_rationale, 'External operator decision required.')}`,
      `   Next: ${valueText(item.next_action, 'Review the ledger row and record the operator decision.')}`
    );
  });
  lines.push('', '## Operator Item Packets');
  items.forEach((item, index) => {
    lines.push('', operatorHandoffItemMarkdown(item, index + 1));
  });
  return lines.join('\n');
}

function configDriftItemMarkdown(item: Record<string, unknown>, index?: number): string {
  const current = recordValue(item.current);
  const baseline = recordValue(item.baseline);
  const rollback = recordValue(item.rollback);
  const currentRollback = recordValue(current.rollback);
  const baselineRollback = recordValue(baseline.rollback);
  const rollbackNote = valueText(rollback.note || currentRollback.note || baselineRollback.note, 'Compare the current item to the baseline before changing release status.');
  const rollbackParts = driftRollbackParts(item);
  const restoreCommand = valueText(rollbackParts.restoreCommand, 'No direct restore command registered.');
  const backupCommand = valueText(rollback.backup_command || currentRollback.backup_command || baselineRollback.backup_command, 'python3 scripts/runtime-state.py backup --output build/runtime-state-backup.tar.gz');
  const heading = index ? `### ${index}. ${valueText(item.label || item.name, 'Config drift item')}` : `### ${valueText(item.label || item.name, 'Config drift item')}`;
  return [
    heading,
    `Name: ${valueText(item.name, 'unknown')}`,
    `Status: ${valueText(item.status, 'changed')}`,
    `Risk: ${valueText(item.risk, 'medium')}`,
    `Path: ${valueText(item.path || current.path || baseline.path, 'n/a')}`,
    `Acknowledged: ${boolText(item.acknowledged)}`,
    `Current fingerprint: ${valueText(current.sha256_short || current.sha256, 'unavailable')}`,
    `Baseline fingerprint: ${valueText(baseline.sha256_short || baseline.sha256, 'unavailable')}`,
    `Current type/size: ${valueText(current.type, 'unknown')} / ${valueText(current.size, 'n/a')}`,
    `Baseline type/size: ${valueText(baseline.type, 'unknown')} / ${valueText(baseline.size, 'n/a')}`,
    `JSON valid: current ${boolText(current.json_valid)}, baseline ${boolText(baseline.json_valid)}`,
    `Backup item: ${rollbackParts.backupItem}`,
    `Restore available: ${rollbackParts.restoreAvailable ? 'yes' : 'no'}`,
    `Rollback note: ${rollbackNote}`,
    `Backup command: ${backupCommand}`,
    `Restore command: ${restoreCommand}`,
    `Next action: Review this evidence. If intentional, acknowledge or mark a new baseline with a reason. If unexpected, restore or edit the file before release.`
  ].join('\n');
}

function configDriftBriefMarkdown(summary: Record<string, unknown>, items: Array<Record<string, unknown>>): string {
  const lines = [
    '# Config Drift Evidence Brief',
    '',
    `Generated: ${new Date().toISOString()}`,
    `State: ${valueText(summary.state, 'unknown')}`,
    `Baseline: ${summary.baseline_present === false ? 'missing' : 'present'}`,
    `Highest risk: ${valueText(summary.highest_risk, 'none')}`,
    `Active drift items: ${items.length}`,
    '',
    '## Drift Items'
  ];
  if (!items.length) {
    lines.push('', 'No active config drift items are open.');
    return lines.join('\n');
  }
  items.forEach((item, index) => {
    lines.push('', configDriftItemMarkdown(item, index + 1));
  });
  return lines.join('\n');
}

export default function OperatePage() {
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: getMeCapabilities, retry: false });
  const operate = useQuery({ queryKey: ['operate'], queryFn: getOperate, refetchInterval: 30000 });
  const onboarding = useQuery({ queryKey: ['onboarding'], queryFn: getOnboarding, refetchInterval: 60000, retry: false });
  const [ciReference, setCiReference] = useState('acme/app#5');
  const [datasetJson, setDatasetJson] = useState('{"id":"v2-smoke-dataset","name":"V2 Smoke Dataset","examples":[{"id":"ex-001","input":"Reply only ok","expected":"ok"}]}');
  const [automationEventJson, setAutomationEventJson] = useState('{"event":{"event":"run_profile.changed","source":"run","severity":"high","model":"model-a","session":"v2-smoke"}}');
  const [ciPreview, setCiPreview] = useState<Record<string, unknown> | null>(null);
  const [ciLaunch, setCiLaunch] = useState<Record<string, unknown> | null>(null);
  const [releaseReport, setReleaseReport] = useState<Record<string, unknown> | null>(null);
  const [datasetResult, setDatasetResult] = useState<Record<string, unknown> | null>(null);
  const [reviewResult, setReviewResult] = useState<Record<string, unknown> | null>(null);
  const [automationTest, setAutomationTest] = useState<Record<string, unknown> | null>(null);
  const [automationSchedulePreview, setAutomationSchedulePreview] = useState<Record<string, unknown> | null>(null);
  const [automationScheduleRun, setAutomationScheduleRun] = useState<Record<string, unknown> | null>(null);
  const [rollbackPreview, setRollbackPreview] = useState<Record<string, unknown> | null>(null);
  const [modelDeprecationPreview, setModelDeprecationPreview] = useState<Record<string, unknown> | null>(null);
  const [repositoryPreview, setRepositoryPreview] = useState<Record<string, unknown> | null>(null);
  const [repositoryImport, setRepositoryImport] = useState<Record<string, unknown> | null>(null);
  const [handoffBriefStatus, setHandoffBriefStatus] = useState('No handoff');
  const [copiedClosureKey, setCopiedClosureKey] = useState('');
  const [copiedPacketKey, setCopiedPacketKey] = useState('');
  const [copiedTemplateKey, setCopiedTemplateKey] = useState('');
  const [copiedDriftEvidenceKey, setCopiedDriftEvidenceKey] = useState('');
  const [driftBriefStatus, setDriftBriefStatus] = useState('No drift brief');
  const [driftReason, setDriftReason] = useState('Reviewed from V2 Operate.');
  const [highRiskDriftConfirmed, setHighRiskDriftConfirmed] = useState(false);
  const [driftActionResult, setDriftActionResult] = useState<Record<string, unknown> | null>(null);
  const [paymentReviewStatus, setPaymentReviewStatus] = useState('Payment review ready');
  const [operateCostThresholdDraft, setOperateCostThresholdDraft] = useState('');
  const [seedTemplatesError, setSeedTemplatesError] = useState('');
  const ciPreviewMutation = useMutation({
    mutationFn: () => previewOperateCiTriage({ reference: ciReference }),
    onSuccess: setCiPreview
  });
  const ciLaunchMutation = useMutation({
    mutationFn: () => launchOperateCiTriage({ reference: ciReference }),
    onSuccess: (result) => {
      setCiLaunch(result);
      operate.refetch();
    }
  });
  const repositoryPreviewMutation = useMutation({
    mutationFn: () => previewOperateRepositoryContext({ reference: ciReference }),
    onSuccess: setRepositoryPreview
  });
  const repositoryImportMutation = useMutation({
    mutationFn: () => importOperateRepositoryContext({ reference: ciReference }),
    onSuccess: (result) => {
      setRepositoryImport(result);
      operate.refetch();
    }
  });
  const releaseReportMutation = useMutation({
    mutationFn: () => writeOperateReleaseReport({ label: 'v2-operate' }),
    onSuccess: (result) => {
      setReleaseReport(result);
      operate.refetch();
    }
  });
  const acknowledgeDriftMutation = useMutation({
    mutationFn: (items: string[]) => acknowledgeOperateConfigDrift({
      items,
      reason: driftReason,
      ...(requiresHighRiskConfirmation ? { confirm_high_risk: highRiskDriftConfirmed, confirmed_high_risk_items: activeHighRiskDriftNames } : {})
    }),
    onSuccess: (result) => {
      setDriftActionResult({ ...result, action: 'acknowledge' });
      operate.refetch();
    }
  });
  const markBaselineMutation = useMutation({
    mutationFn: () => markOperateConfigDriftBaseline({
      label: 'v2-operate-baseline',
      reason: driftReason,
      ...(requiresHighRiskConfirmation ? { confirm_high_risk: highRiskDriftConfirmed, confirmed_high_risk_items: activeHighRiskDriftNames } : {})
    }),
    onSuccess: (result) => {
      setDriftActionResult({ ...result, action: 'baseline' });
      operate.refetch();
    }
  });
  const datasetMutation = useMutation({
    mutationFn: () => saveOperateEvalDataset(JSON.parse(datasetJson) as Record<string, unknown>),
    onSuccess: (result) => {
      setDatasetResult(result.dataset);
      operate.refetch();
    }
  });
  const reviewUpdateMutation = useMutation({
    mutationFn: (id: string) => updateOperateReview({ id, status: 'approved', notes: 'Approved from v2 Operate.' }),
    onSuccess: (result) => {
      setReviewResult(recordValue(result.review));
      operate.refetch();
    }
  });
  const automationTestMutation = useMutation({
    mutationFn: () => testOperateAutomation(JSON.parse(automationEventJson) as Record<string, unknown>),
    onSuccess: (result) => {
      setAutomationTest(result);
      operate.refetch();
    }
  });
  const automationSchedulePreviewMutation = useMutation({
    mutationFn: () => runDueOperateAutomationSchedules({ dry_run: true }),
    onSuccess: setAutomationSchedulePreview
  });
  const automationScheduleMutation = useMutation({
    mutationFn: () => runDueOperateAutomationSchedules({ dry_run: false }),
    onSuccess: (result) => {
      setAutomationScheduleRun(result);
      operate.refetch();
    }
  });
  const rollbackPreviewMutation = useMutation({
    mutationFn: (targetId: string) => previewOperateRollback({ target_id: targetId }),
    onSuccess: setRollbackPreview
  });
  const modelDeprecationPreviewMutation = useMutation({
    mutationFn: (modelId: string) => previewOperateModelDeprecation({ model_id: modelId }),
    onSuccess: setModelDeprecationPreview
  });
  const seedTemplatesMutation = useMutation({
    mutationFn: seedOnboardingModelTemplates,
    onSuccess: () => {
      setSeedTemplatesError('');
      onboarding.refetch();
    },
    onError: (error) => setSeedTemplatesError(errorText(error))
  });
  const paymentReviewMutation = useMutation({
    mutationFn: (items: Array<Record<string, unknown>>) => updateCostControlThresholds({ payment_review: { items } }),
    onSuccess: () => {
      setPaymentReviewStatus('Payment review saved');
      operate.refetch();
    }
  });
  const operateThresholdMutation = useMutation({
    mutationFn: () => updateCostControlThresholds({
      scope_type: 'workspace',
      scope_id: 'default',
      monthly_threshold_usd: numberValue(operateCostThresholdDraft, 0)
    }),
    onSuccess: () => {
      setPaymentReviewStatus('Threshold saved');
      operate.refetch();
    }
  });
  const operateOverrideMutation = useMutation({
    mutationFn: () => overrideCostControl({ action: 'override', duration_minutes: 60, reason: 'operate_payment_review' }),
    onSuccess: () => {
      setPaymentReviewStatus('Pause overridden');
      operate.refetch();
    }
  });
  const canView = capabilities.data?.capabilities['console.view']?.allowed ?? false;
  const canSeedTemplates = capabilities.data?.capabilities['run.edit']?.allowed ?? false;
  const canImportRepository = capabilities.data?.capabilities['operate.repository.import']?.allowed ?? false;
  const canReleaseReport = capabilities.data?.capabilities['operate.rollback.admin']?.allowed ?? false;
  const canManageReviews = capabilities.data?.capabilities['operate.review.manage']?.allowed ?? false;
  const canRunEvals = capabilities.data?.capabilities['evals.run']?.allowed ?? false;
  const canManageAutomation = capabilities.data?.capabilities['operate.automation.admin']?.allowed ?? false;
  const canManageModels = capabilities.data?.capabilities['models.admin']?.allowed ?? false;
  const canManageConfigDrift = capabilities.data?.capabilities['operate.config_drift.admin']?.allowed ?? false;
  const canEditCostControl = capabilities.data?.capabilities['cost_control.edit']?.allowed ?? false;
  const canOverrideCostControl = capabilities.data?.capabilities['cost_control.override']?.allowed ?? false;
  const payload = operate.data;
  const summary = recordValue(payload?.summary);
  const releaseChecks = rows(payload?.release_candidate, 'checks');
  const operatorHandoff = recordValue(recordValue(payload?.release_candidate).operator_handoff);
  const operatorHandoffItems = listValue(operatorHandoff.items);
  const hasOperatorHandoff = operatorHandoffItems.length > 0;
  const handoffBrief = operatorHandoffBriefMarkdown(operatorHandoff, operatorHandoffItems);
  const reviews = rows(payload?.reviews, 'reviews', 'items');
  const rollbackTargets = rows(payload?.rollback, 'targets', 'archives');
  const configDrift = recordValue(payload?.config_drift);
  const configDriftSummary = recordValue(configDrift.summary);
  const activeDriftItems = rows(configDrift, 'drift', 'drifts');
  const monitoredConfigItems = rows(configDrift, 'items');
  const driftItems = activeDriftItems.length ? activeDriftItems : monitoredConfigItems;
  const showingActiveDrift = activeDriftItems.length > 0;
  const activeDriftNames = activeDriftItems.map((row) => valueText(row.name || row.id)).filter(Boolean);
  const activeHighRiskDriftItems = activeDriftItems.filter((row) => valueText(row.risk).match(/critical|high/i));
  const activeHighRiskDriftNames = activeHighRiskDriftItems.map((row) => valueText(row.name || row.id || row.label)).filter(Boolean);
  const requiresHighRiskConfirmation = activeHighRiskDriftItems.length > 0;
  const highRiskConfirmationReady = !requiresHighRiskConfirmation || highRiskDriftConfirmed;
  const driftBrief = configDriftBriefMarkdown(configDriftSummary, activeDriftItems);
  const driftReasonReady = Boolean(driftReason.trim());
  const automation = recordValue(payload?.automation);
  const automationRules = rows(automation, 'rules').length ? rows(automation, 'rules') : rows(recordValue(automation.config), 'rules');
  const ciFindings = rows(payload?.ci_triage, 'findings', 'checks');
  const modelDeprecations = rows(payload?.model_deprecations, 'deprecated_models', 'items', 'models', 'deprecations');
  const evalGate = recordValue(payload?.eval_gates);
  const offlineMode = recordValue(payload?.offline_mode);
  const costControl = recordValue(payload?.cost_control);
  const costCosts = recordValue(costControl.costs);
  const costThreshold = recordValue(costControl.threshold);
  const costPause = recordValue(costControl.pause);
  const costProvider = recordValue(costControl.provider);
  const paymentReview = recordValue(costControl.payment_review);
  const paymentItems = listValue(paymentReview.items);
  const costStatus = valueText(costControl.status, 'unknown');
  const monthlyThreshold = numberValue(costThreshold.monthly_threshold_usd, 0);
  const monthlyCost = numberValue(costCosts.monthly_total_usd, 0);
  const monthlyPercent = numberValue(costThreshold.percent, 0);
  const providerSource = valueText(costProvider.monthly_source || recordValue(costCosts.sources).monthly, 'local_estimate');
  const providerLabel = providerSource === 'provider_billing_api' ? 'Provider billing' : 'Local estimate';
  const reviewsError = valueText(recordValue(payload?.reviews).error);
  const releaseError = valueText(recordValue(payload?.release_candidate).error);
  const rollbackError = valueText(recordValue(payload?.rollback).error);
  const configDriftError = valueText(configDrift.error);
  const automationError = valueText(automation.error);
  const ciTriageError = valueText(recordValue(payload?.ci_triage).error);
  const modelDeprecationsError = valueText(recordValue(payload?.model_deprecations).error);
  const costControlError = valueText(costControl.error);
  const evalGateError = valueText(evalGate.error);
  const scrollToSection = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  const sectionKeyDown = (event: KeyboardEvent<HTMLDivElement>, id: string) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      scrollToSection(id);
    }
  };
  useEffect(() => {
    setHandoffBriefStatus(hasOperatorHandoff ? 'Brief Ready' : 'No handoff');
  }, [hasOperatorHandoff, operatorHandoffItems.length]);
  useEffect(() => {
    setDriftBriefStatus(showingActiveDrift ? 'Drift Brief Ready' : 'No drift brief');
  }, [showingActiveDrift, activeDriftItems.length]);
  useEffect(() => {
    setHighRiskDriftConfirmed(false);
  }, [activeHighRiskDriftNames.join('|')]);
  useEffect(() => {
    setOperateCostThresholdDraft(String(monthlyThreshold));
  }, [monthlyThreshold]);
  const togglePaymentItem = (itemId: string, checked: boolean) => {
    const next = paymentItems.map((item) => (
      valueText(item.id) === itemId
        ? { ...item, status: checked ? 'complete' : 'open', completed_at: checked ? Date.now() / 1000 : 0 }
        : item
    ));
    setPaymentReviewStatus('Saving payment review');
    paymentReviewMutation.mutate(next);
  };
  const copyHandoffBrief = async () => {
    if (!hasOperatorHandoff) return;
    try {
      await copyText(handoffBrief);
      setHandoffBriefStatus('Handoff copied');
    } catch {
      setHandoffBriefStatus('Copy failed');
    }
  };
  const downloadHandoffBrief = () => {
    if (!hasOperatorHandoff) return;
    downloadText(`mde-llm-proxy-operator-handoff-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.md`, handoffBrief, 'text/markdown;charset=utf-8');
    setHandoffBriefStatus('Handoff downloaded');
  };
  const copyClosureTemplate = async (row: Record<string, unknown>, key: string) => {
    const closure = valueText(row.closure_template, 'Status cell: Closed <YYYY-MM-DD>: <outcome>. Evidence: <evidence summary>. Owner: Operator. Gate: operator-decision.');
    try {
      await copyText(closure);
      setCopiedClosureKey(key);
    } catch {
      setCopiedClosureKey('copy-failed');
    }
  };
  const copyOperatorPacket = async (row: Record<string, unknown>, key: string, index: number) => {
    try {
      await copyText(operatorHandoffItemMarkdown(row, index + 1));
      setCopiedPacketKey(key);
    } catch {
      setCopiedPacketKey('copy-failed');
    }
  };
  const copyDriftBrief = async () => {
    if (!showingActiveDrift) return;
    try {
      await copyText(driftBrief);
      setDriftBriefStatus('Drift brief copied');
    } catch {
      setDriftBriefStatus('Copy failed');
    }
  };
  const downloadDriftBrief = () => {
    if (!showingActiveDrift) return;
    downloadText(`mde-llm-proxy-config-drift-brief-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.md`, driftBrief, 'text/markdown;charset=utf-8');
    setDriftBriefStatus('Drift brief downloaded');
  };
  const copyDriftEvidence = async (row: Record<string, unknown>, key: string, index: number) => {
    try {
      await copyText(configDriftItemMarkdown(row, index + 1));
      setCopiedDriftEvidenceKey(key);
    } catch {
      setCopiedDriftEvidenceKey('copy-failed');
    }
  };
  const copyTemplatePreview = async (text: string, key: string) => {
    try {
      await copyText(text);
      setCopiedTemplateKey(key);
    } catch {
      setCopiedTemplateKey('copy-failed');
    }
  };

  return (
    <Space direction="vertical" size={16} className="pageStack">
      <Card>
        <Space direction="vertical" size={8}>
          <Typography.Title level={3}>Operate</Typography.Title>
          <Space wrap>
            <Tag color={canView ? 'blue' : 'default'}>{canView ? 'Operations allowed' : 'Operations disabled'}</Tag>
            <Tag color={offlineMode.enabled ? 'orange' : 'green'}>{offlineMode.enabled ? 'Offline' : 'Online'}</Tag>
            <Tag>{valueText(evalGate.decision, 'eval unknown')}</Tag>
          </Space>
        </Space>
      </Card>
      {!canView ? <Alert type="info" showIcon message="Viewing operation data requires console permission." /> : null}
      {operate.error ? <Alert type="error" showIcon message={errorText(operate.error)} /> : null}
      {onboarding.error ? <Alert type="error" showIcon message={errorText(onboarding.error)} /> : null}
      <OnboardingTemplateGallery
        data={onboarding.data}
        canSeed={canSeedTemplates}
        seedLoading={seedTemplatesMutation.isPending}
        seedError={seedTemplatesError}
        onSeed={() => seedTemplatesMutation.mutate()}
        onCopy={(text, key) => void copyTemplatePreview(text, key)}
        copiedKey={copiedTemplateKey}
      />
      <Space wrap data-testid="operate-summary">
        <Card
          className="metricCard"
          hoverable
          role="button"
          tabIndex={0}
          style={{ cursor: 'pointer' }}
          onClick={() => scrollToSection('operate-section-reviews')}
          onKeyDown={(event) => sectionKeyDown(event, 'operate-section-reviews')}
        >
          <Typography.Text type="secondary">Reviews</Typography.Text>
          <Typography.Title level={4}>{valueText(summary.open_reviews, String(reviews.length))}</Typography.Title>
        </Card>
        <Card
          className="metricCard"
          hoverable
          role="button"
          tabIndex={0}
          style={{ cursor: 'pointer' }}
          onClick={() => scrollToSection('operate-section-release')}
          onKeyDown={(event) => sectionKeyDown(event, 'operate-section-release')}
        >
          <Typography.Text type="secondary">Release Checks</Typography.Text>
          <Typography.Title level={4}>{valueText(summary.release_checks, String(releaseChecks.length))}</Typography.Title>
        </Card>
        <Card
          className="metricCard"
          hoverable
          role="button"
          tabIndex={0}
          style={{ cursor: 'pointer' }}
          onClick={() => scrollToSection('operate-section-rollback')}
          onKeyDown={(event) => sectionKeyDown(event, 'operate-section-rollback')}
        >
          <Typography.Text type="secondary">Rollback Targets</Typography.Text>
          <Typography.Title level={4}>{valueText(summary.rollback_targets, String(rollbackTargets.length))}</Typography.Title>
        </Card>
        <Card
          className="metricCard"
          hoverable
          role="button"
          tabIndex={0}
          style={{ cursor: 'pointer' }}
          onClick={() => scrollToSection('operate-section-drift')}
          onKeyDown={(event) => sectionKeyDown(event, 'operate-section-drift')}
        >
          <Typography.Text type="secondary">Active Drift</Typography.Text>
          <Typography.Title level={4}>{valueText(summary.config_drift_items, String(activeDriftItems.length))}</Typography.Title>
        </Card>
        <Card
          className="metricCard"
          hoverable
          role="button"
          tabIndex={0}
          style={{ cursor: 'pointer' }}
          onClick={() => scrollToSection('operate-section-ci')}
          onKeyDown={(event) => sectionKeyDown(event, 'operate-section-ci')}
        >
          <Typography.Text type="secondary">CI Findings</Typography.Text>
          <Typography.Title level={4}>{valueText(summary.ci_findings, String(ciFindings.length))}</Typography.Title>
        </Card>
      </Space>
      <Card
        title="Payment Review and Cost Guard"
        data-testid="operate-payment-review"
        extra={<Tag color={paymentReviewMutation.isPending || operateThresholdMutation.isPending || operateOverrideMutation.isPending ? 'orange' : 'blue'}>{paymentReviewStatus}</Tag>}
      >
        <Space direction="vertical" size={12} className="pageStack">
          <Space wrap>
            <Tag color={costStatus === 'paused' || costStatus === 'hard' ? 'red' : costStatus === 'warning' ? 'orange' : 'green'}>{costStatus}</Tag>
            <Tag color={providerSource === 'provider_billing_api' ? 'green' : 'orange'}>{providerLabel}</Tag>
            <Tag>{money(monthlyCost)} month</Tag>
            <Tag>{monthlyThreshold ? `${money(monthlyThreshold)} limit` : 'No monthly limit'}</Tag>
            <Tag>{monthlyPercent.toFixed(monthlyPercent >= 10 ? 0 : 1)}%</Tag>
            {costPause.active ? <Tag color="red">Paused</Tag> : null}
          </Space>
          {costControlError ? <Alert type="warning" showIcon message="Cost control data could not be loaded" description={costControlError} /> : null}
          {paymentReviewMutation.error ? <Alert type="error" showIcon message={errorText(paymentReviewMutation.error)} /> : null}
          {operateThresholdMutation.error ? <Alert type="error" showIcon message={errorText(operateThresholdMutation.error)} /> : null}
          {operateOverrideMutation.error ? <Alert type="error" showIcon message={errorText(operateOverrideMutation.error)} /> : null}
          <div className="paymentReviewMetrics">
            <div>
              <span>Minute</span>
              <strong>{money(costCosts.minute_total_usd)}</strong>
            </div>
            <div>
              <span>Daily</span>
              <strong>{money(costCosts.daily_total_usd)}</strong>
            </div>
            <div>
              <span>Dedicated</span>
              <strong>{money(recordValue(recordValue(costCosts.categories).dedicated_instances).monthly_usd)}</strong>
            </div>
            <div>
              <span>LLM Service</span>
              <strong>{money(recordValue(recordValue(costCosts.categories).llm_service).monthly_usd)}</strong>
            </div>
          </div>
          <Space.Compact>
            <Input
              data-testid="operate-cost-threshold"
              type="number"
              min="0"
              step="1"
              value={operateCostThresholdDraft}
              onChange={(event) => setOperateCostThresholdDraft(event.target.value)}
              addonBefore="Monthly"
            />
            <Button
              data-testid="operate-cost-threshold-save"
              disabled={!canEditCostControl}
              loading={operateThresholdMutation.isPending}
              onClick={() => {
                setPaymentReviewStatus('Saving threshold');
                operateThresholdMutation.mutate();
              }}
            >
              Save
            </Button>
            <Button
              data-testid="operate-cost-override"
              disabled={!canOverrideCostControl || !costPause.active}
              loading={operateOverrideMutation.isPending}
              onClick={() => {
                setPaymentReviewStatus('Overriding pause');
                operateOverrideMutation.mutate();
              }}
            >
              Override Pause
            </Button>
          </Space.Compact>
          <div className="paymentReviewList">
            {paymentItems.map((item) => {
              const itemId = valueText(item.id);
              const status = valueText(item.status, 'open');
              const checked = ['complete', 'ready', 'done'].includes(status.toLowerCase());
              return (
                <div className="paymentReviewItem" key={itemId || valueText(item.label)}>
                  <Checkbox
                    data-testid="operate-payment-review-item"
                    checked={checked}
                    disabled={!canEditCostControl || paymentReviewMutation.isPending}
                    onChange={(event) => togglePaymentItem(itemId, event.target.checked)}
                  >
                    <strong>{valueText(item.label, itemId || 'Payment item')}</strong>
                  </Checkbox>
                  <span>{valueText(item.detail)}</span>
                  <Tag color={paymentStatusColor(status)}>{status}</Tag>
                </div>
              );
            })}
          </div>
        </Space>
      </Card>
      <Card
        id="operate-section-release"
        title="Release Candidate"
        data-testid="operate-release"
        extra={
          <Button
            data-testid="operate-release-report"
            disabled={!canReleaseReport}
            loading={releaseReportMutation.isPending}
            onClick={() => releaseReportMutation.mutate()}
          >
            Report
          </Button>
        }
      >
        {releaseError ? <Alert type="warning" showIcon message="Release candidate data could not be loaded" description={releaseError} style={{ marginBottom: 12 }} /> : null}
        {releaseReportMutation.error ? <Alert type="error" showIcon message={errorText(releaseReportMutation.error)} /> : null}
        {releaseReport ? <Alert data-testid="operate-release-report-result" type="success" showIcon message="Release report written" description={valueText(releaseReport.report_file || releaseReport.path || releaseReport.label)} /> : null}
        {operatorHandoffItems.length ? (
          <Alert
            data-testid="operate-release-handoff"
            type="warning"
            showIcon
            message={valueText(operatorHandoff.summary, 'Operator handoff required')}
            description={valueText(operatorHandoff.source)}
            style={{ marginBottom: 12 }}
          />
        ) : (
          <Alert
            data-testid="operate-release-handoff"
            type="success"
            showIcon
            message={valueText(operatorHandoff.summary, 'No operator-owned release items are open.')}
            style={{ marginBottom: 12 }}
          />
        )}
        <div className="operatorHandoffBriefDock" data-testid="operate-release-handoff-brief">
          <span>{handoffBriefStatus}</span>
          <Button disabled={!hasOperatorHandoff} onClick={() => void copyHandoffBrief()}>Copy Handoff</Button>
          <Button disabled={!hasOperatorHandoff} onClick={downloadHandoffBrief}>Download Handoff</Button>
        </div>
        {operatorHandoffItems.length ? (
          <div className="operatorActionPlan" data-testid="operate-release-action-plan">
            <div data-testid="operate-release-handoff-list">
              <Collapse
                defaultActiveKey={[`${valueText(operatorHandoffItems[0].item, 'handoff')}-0`]}
                items={operatorHandoffItems.map((row, index) => {
                  const closureKey = `${valueText(row.item, 'handoff')}-${index}`;
                  const packetKey = `packet-${valueText(row.item, 'handoff')}-${index}`;
                  const packetCopied = copiedPacketKey === packetKey;
                  const closureCopied = copiedClosureKey === closureKey;
                  return {
                    key: closureKey,
                    label: (
                      <div className="operatorActionPlanItem" data-testid="operate-release-action-plan-item">
                        <Tag color={index === 0 ? 'red' : valueText(row.urgency) === 'high' ? 'orange' : 'blue'}>#{valueText(row.priority_rank, String(index + 1))}</Tag>
                        <div>
                          <strong>{valueText(row.item, 'Operator-owned item')}</strong>
                          <span>{valueText(row.urgency, 'normal')} · {valueText(row.owner, 'Operator')} · {valueText(row.gate_type, 'operator-decision')}</span>
                          <p>Why: {valueText(row.blocking_rationale, 'This item needs an external operator decision before the advisory ledger can be closed.')}</p>
                        </div>
                        <Space wrap size={8} onClick={(event) => event.stopPropagation()}>
                          <Button size="small" data-testid="operate-release-copy-packet" onClick={(event) => { event.stopPropagation(); void copyOperatorPacket(row, packetKey, index); }}>Copy Packet</Button>
                          {packetCopied ? <Tag color="green">Packet copied</Tag> : null}
                          {copiedPacketKey === 'copy-failed' ? <Tag color="red">Copy failed</Tag> : null}
                        </Space>
                      </div>
                    ),
                    children: (
                      <div className="operatorHandoffItem" data-testid="operate-release-handoff-item">
                        <div>
                          <span>Needs</span>
                          <p>{valueText(row.needs, 'Operator decision or external account state')}</p>
                        </div>
                        <div>
                          <span>Status</span>
                          <p>{valueText(row.status, 'Open')}</p>
                        </div>
                        <div>
                          <span>Next Action</span>
                          <p>{valueText(row.next_action, 'Review the ledger row and record the operator decision.')}</p>
                        </div>
                        <div>
                          <span>Evidence Required</span>
                          <p>{valueText(row.evidence_required, 'Operator decision, external state, timestamp, and updated status.')}</p>
                        </div>
                        <div>
                          <span>Closure Template</span>
                          <p>{valueText(row.closure_template, 'Status cell: Closed <YYYY-MM-DD>: <outcome>. Evidence: <evidence summary>. Owner: Operator. Gate: operator-decision.')}</p>
                          <Space wrap size={8}>
                            <Button size="small" data-testid="operate-release-copy-packet-detail" onClick={() => void copyOperatorPacket(row, `detail-${closureKey}`, index)}>Copy Packet</Button>
                            <Button size="small" data-testid="operate-release-copy-closure" onClick={() => void copyClosureTemplate(row, closureKey)}>Copy Closure</Button>
                            {copiedPacketKey === `detail-${closureKey}` ? <Tag color="green">Packet copied</Tag> : null}
                            {closureCopied ? <Tag color="green">Closure copied</Tag> : null}
                            {copiedClosureKey === 'copy-failed' ? <Tag color="red">Copy failed</Tag> : null}
                          </Space>
                        </div>
                      </div>
                    )
                  };
                })}
              />
            </div>
          </div>
        ) : null}
        <Table<Record<string, unknown>>
          rowKey={(row, index) => `${valueText(row.name || row.id, 'check')}-${index}`}
          dataSource={releaseChecks}
          loading={operate.isLoading}
          pagination={{ pageSize: 6 }}
          columns={[
            { title: 'Check', render: (_value, row) => valueText(row.name || row.id) },
            { title: 'Status', dataIndex: 'status', render: (value: string) => <Tag color={value === 'passed' || value === 'ok' ? 'green' : value === 'failed' || value === 'blocked' ? 'red' : 'default'}>{valueText(value, 'unknown')}</Tag> },
            { title: 'Severity', dataIndex: 'severity' },
            { title: 'Message', render: (_value, row) => valueText(row.message || row.summary) }
          ]}
        />
      </Card>
      <Card id="operate-section-reviews" title="Review Queue" data-testid="operate-reviews">
        {reviewsError ? <Alert type="warning" showIcon message="Review queue data could not be loaded" description={reviewsError} style={{ marginBottom: 12 }} /> : null}
        {reviewUpdateMutation.error ? <Alert type="error" showIcon message={errorText(reviewUpdateMutation.error)} /> : null}
        {reviewResult ? <Alert data-testid="operate-review-update-result" type="success" showIcon message={`Review ${valueText(reviewResult.id)} ${valueText(reviewResult.status)}`} /> : null}
        <Table<Record<string, unknown>>
          rowKey={(row, index) => valueText(row.id, String(index))}
          dataSource={reviews}
          loading={operate.isLoading}
          pagination={{ pageSize: 6 }}
          columns={[
            { title: 'Review', render: (_value, row) => valueText(row.title || row.id) },
            { title: 'Status', dataIndex: 'status' },
            { title: 'Severity', dataIndex: 'severity' },
            { title: 'Reason', dataIndex: 'reason' },
            {
              title: 'Action',
              render: (_value, row) => (
                <Button
                  data-testid="operate-review-approve"
                  size="small"
                  disabled={!canManageReviews || !row.id}
                  loading={reviewUpdateMutation.isPending}
                  onClick={() => reviewUpdateMutation.mutate(String(row.id || ''))}
                >
                  Approve
                </Button>
              )
            }
          ]}
        />
      </Card>
      <Card title="Eval Gate" data-testid="operate-eval-gate">
        <Space direction="vertical" size={12} className="pageStack">
          {evalGateError ? <Alert type="warning" showIcon message="Eval gate data could not be loaded" description={evalGateError} /> : null}
          <Space wrap>
            <Tag>{valueText(evalGate.surface, 'gateway_policy')}</Tag>
            <Tag color={evalGate.allowed === false ? 'red' : 'green'}>{valueText(evalGate.decision, 'unknown')}</Tag>
            <Tag>{listValue(evalGate.recommended_datasets).length} datasets</Tag>
            <Tag>{listValue(evalGate.evidence).length} evidence</Tag>
          </Space>
          <Input.TextArea data-testid="operate-eval-dataset-json" value={datasetJson} onChange={(event) => setDatasetJson(event.target.value)} autoSize={{ minRows: 3, maxRows: 8 }} />
          <Space wrap>
            <Button data-testid="operate-eval-dataset-save" disabled={!canRunEvals} loading={datasetMutation.isPending} onClick={() => datasetMutation.mutate()}>Save Dataset</Button>
            {datasetResult ? <Tag data-testid="operate-eval-dataset-result" color="green">{valueText(datasetResult.id, 'saved')}</Tag> : null}
          </Space>
          {datasetMutation.error ? <Alert type="error" showIcon message={errorText(datasetMutation.error)} /> : null}
          <details>
            <summary>Raw payload</summary>
            <pre className="templatePreview">{JSON.stringify(evalGate, null, 2)}</pre>
          </details>
        </Space>
      </Card>
      <Card title="Rollback and Drift" data-testid="operate-rollback">
        <Space direction="vertical" size={12} className="pageStack">
          {rollbackError ? <Alert type="warning" showIcon message="Rollback targets could not be loaded" description={rollbackError} /> : null}
          {configDriftError ? <Alert type="warning" showIcon message="Config drift data could not be loaded" description={configDriftError} /> : null}
          <Alert
            data-testid="operate-config-drift-summary"
            type={showingActiveDrift ? (valueText(configDriftSummary.highest_risk).match(/critical|high/i) ? 'error' : 'warning') : 'success'}
            showIcon
            message={showingActiveDrift ? `${activeDriftItems.length} active config drift item${activeDriftItems.length === 1 ? '' : 's'}` : 'No active config drift'}
            description={`State: ${valueText(configDriftSummary.state, 'unknown')}. Baseline: ${configDriftSummary.baseline_present === false ? 'missing' : 'present'}. Highest risk: ${valueText(configDriftSummary.highest_risk, 'none')}. ${showingActiveDrift ? 'Review path and rollback guidance before marking a new baseline.' : `${monitoredConfigItems.length} monitored item${monitoredConfigItems.length === 1 ? '' : 's'} available for context.`}`}
          />
          {rollbackPreviewMutation.error ? <Alert type="error" showIcon message={errorText(rollbackPreviewMutation.error)} /> : null}
          {acknowledgeDriftMutation.error ? <Alert type="error" showIcon message={errorText(acknowledgeDriftMutation.error)} /> : null}
          {markBaselineMutation.error ? <Alert type="error" showIcon message={errorText(markBaselineMutation.error)} /> : null}
          {rollbackPreview ? <Alert data-testid="operate-rollback-preview-result" type="info" showIcon message="Rollback preview ready" description={`${valueText(recordValue(rollbackPreview.summary).will_restore, '0')} items will restore`} /> : null}
          {driftActionResult ? <Alert data-testid="operate-config-drift-action-result" type="success" showIcon message={valueText(driftActionResult.action) === 'baseline' ? 'Config drift baseline marked' : 'Config drift acknowledged'} description={valueText(recordValue(driftActionResult.summary).state || driftActionResult.baseline_file || 'Operate payload refreshed.')} /> : null}
          <div className="operatorHandoffBriefDock" data-testid="operate-config-drift-brief">
            <span>{driftBriefStatus}</span>
            <Button disabled={!showingActiveDrift} onClick={() => void copyDriftBrief()}>Copy Drift Brief</Button>
            <Button disabled={!showingActiveDrift} onClick={downloadDriftBrief}>Download Drift Brief</Button>
          </div>
          <Space direction="vertical" size={8} className="pageStack" data-testid="operate-config-drift-actions">
            <Input.TextArea
              data-testid="operate-config-drift-reason"
              value={driftReason}
              onChange={(event) => setDriftReason(event.target.value)}
              autoSize={{ minRows: 2, maxRows: 4 }}
              placeholder="Reason for acknowledging drift or marking a baseline"
            />
            {requiresHighRiskConfirmation ? (
              <Alert
                data-testid="operate-config-drift-high-risk-warning"
                type="error"
                showIcon
                message="High-risk config drift requires explicit confirmation"
                description={`High-risk items: ${activeHighRiskDriftNames.join(', ')}. Review the drift brief before acknowledging or marking a new baseline.`}
              />
            ) : null}
            {requiresHighRiskConfirmation ? (
              <Checkbox
                data-testid="operate-config-drift-high-risk-confirm"
                checked={highRiskDriftConfirmed}
                onChange={(event) => setHighRiskDriftConfirmed(event.target.checked)}
              >
                I reviewed the high-risk drift evidence and intentionally want to enable acknowledgement or baseline actions.
              </Checkbox>
            ) : null}
            <Space wrap>
              <Button
                data-testid="operate-config-drift-acknowledge"
                disabled={!canManageConfigDrift || !showingActiveDrift || !driftReasonReady || !highRiskConfirmationReady}
                loading={acknowledgeDriftMutation.isPending}
                onClick={() => acknowledgeDriftMutation.mutate(activeDriftNames)}
              >
                Acknowledge Active Drift
              </Button>
              <Button
                data-testid="operate-config-drift-baseline"
                disabled={!canManageConfigDrift || !driftReasonReady || !highRiskConfirmationReady}
                loading={markBaselineMutation.isPending}
                onClick={() => markBaselineMutation.mutate()}
              >
                Mark New Baseline
              </Button>
              <Tag color={canManageConfigDrift ? 'blue' : 'default'}>{canManageConfigDrift ? 'config_drift_admin' : 'read only'}</Tag>
              {showingActiveDrift ? <Tag>{activeDriftNames.length} selected</Tag> : null}
              {requiresHighRiskConfirmation ? <Tag color={highRiskDriftConfirmed ? 'red' : 'orange'}>{highRiskDriftConfirmed ? 'high risk confirmed' : 'high risk locked'}</Tag> : null}
            </Space>
          </Space>
          <div id="operate-section-rollback" style={{ scrollMarginTop: 16 }}>
          <Table<Record<string, unknown>>
            rowKey={(row, index) => valueText(row.id || row.name || row.path, String(index))}
            dataSource={rollbackTargets}
            loading={operate.isLoading}
            pagination={{ pageSize: 4 }}
            columns={[
              { title: 'Target', render: (_value, row) => valueText(row.id || row.name || row.path) },
              { title: 'Kind', dataIndex: 'kind' },
              { title: 'Status', dataIndex: 'status' },
              {
                title: 'Action',
                render: (_value, row) => (
                  <Button
                    data-testid="operate-rollback-preview"
                    size="small"
                    disabled={!canReleaseReport || !(row.id || row.path)}
                    loading={rollbackPreviewMutation.isPending}
                    onClick={() => rollbackPreviewMutation.mutate(valueText(row.id || row.path))}
                  >
                    Preview
                  </Button>
                )
              }
            ]}
          />
          </div>
          {rollbackPreview ? (
            <>
              <Descriptions size="small" column={1} bordered>
                <Descriptions.Item label="Target">{valueText(recordValue(rollbackPreview.target).id || recordValue(rollbackPreview.target).path, 'n/a')}</Descriptions.Item>
                <Descriptions.Item label="Items">{valueText(recordValue(rollbackPreview.summary).items, '0')}</Descriptions.Item>
                <Descriptions.Item label="Will restore">{valueText(recordValue(rollbackPreview.summary).will_restore, '0')}</Descriptions.Item>
                <Descriptions.Item label="Move existing aside">{valueText(recordValue(rollbackPreview.summary).will_move_existing_aside, '0')}</Descriptions.Item>
                <Descriptions.Item label="Includes secrets">{boolText(recordValue(rollbackPreview.summary).include_secrets)}</Descriptions.Item>
              </Descriptions>
              <details>
                <summary>Raw payload</summary>
                <pre className="templatePreview">{JSON.stringify(rollbackPreview, null, 2)}</pre>
              </details>
            </>
          ) : null}
          <div id="operate-section-drift" style={{ scrollMarginTop: 16 }}>
          <Table<Record<string, unknown>>
            rowKey={(row, index) => valueText(row.id || row.path || row.key, String(index))}
            dataSource={driftItems}
            loading={operate.isLoading}
            pagination={{ pageSize: 4 }}
            expandable={{
              expandedRowRender: (row) => (
                <Descriptions size="small" column={1} bordered>
                  <Descriptions.Item label="Path"><code>{valueText(row.path || recordValue(row.current).path, 'n/a')}</code></Descriptions.Item>
                  <Descriptions.Item label="Acknowledged">{boolText(row.acknowledged)}</Descriptions.Item>
                  <Descriptions.Item label="Current Evidence"><code>{driftSnapshotText(recordValue(row.current))}</code></Descriptions.Item>
                  <Descriptions.Item label="Baseline Evidence"><code>{driftSnapshotText(recordValue(row.baseline))}</code></Descriptions.Item>
                  <Descriptions.Item label="Rollback Readiness">{driftRollbackReadinessText(row)}</Descriptions.Item>
                  <Descriptions.Item label="Restore Command"><code>{valueText(driftRollbackParts(row).restoreCommand, 'No direct restore command registered.')}</code></Descriptions.Item>
                  <Descriptions.Item label="Rollback Note">{valueText(recordValue(row.rollback).note || recordValue(recordValue(row.current).rollback).note, 'Review baseline before changing runtime state.')}</Descriptions.Item>
                </Descriptions>
              )
            }}
            columns={[
              { title: showingActiveDrift ? 'Active Drift' : 'Monitored Item', render: (_value, row) => valueText(row.label || row.name || row.id || row.path || row.key) },
              { title: 'Status', render: (_value, row) => valueText(row.status, showingActiveDrift ? 'changed' : 'monitored') },
              { title: 'Risk', render: (_value, row) => <Tag color={riskColor(row.risk || row.severity)}>{valueText(row.risk || row.severity, 'unknown')}</Tag> },
              {
                title: 'Action',
                render: (_value, row, index) => {
                  const evidenceKey = `${valueText(row.name || row.id || row.path, 'drift')}-${index}`;
                  const copied = copiedDriftEvidenceKey === evidenceKey;
                  return (
                    <Space wrap size={8}>
                      <Button size="small" data-testid="operate-config-drift-copy-row" disabled={!showingActiveDrift} onClick={() => void copyDriftEvidence(row, evidenceKey, index)}>Copy Evidence</Button>
                      {copied ? <Tag color="green">Evidence copied</Tag> : null}
                      {copiedDriftEvidenceKey === 'copy-failed' ? <Tag color="red">Copy failed</Tag> : null}
                    </Space>
                  );
                }
              }
            ]}
          />
          </div>
        </Space>
      </Card>
      <Card title="Automation and CI" data-testid="operate-automation">
        <Space direction="vertical" size={12} className="pageStack">
          {automationError ? <Alert type="warning" showIcon message="Automation data could not be loaded" description={automationError} /> : null}
          {ciTriageError ? <Alert type="warning" showIcon message="CI triage data could not be loaded" description={ciTriageError} /> : null}
          <Space.Compact>
            <Input data-testid="operate-ci-reference" value={ciReference} onChange={(event) => setCiReference(event.target.value)} />
            <Button data-testid="operate-ci-preview" disabled={!canImportRepository} loading={ciPreviewMutation.isPending} onClick={() => ciPreviewMutation.mutate()}>Preview</Button>
            <Button data-testid="operate-ci-launch" disabled={!canImportRepository} loading={ciLaunchMutation.isPending} onClick={() => ciLaunchMutation.mutate()}>Launch</Button>
          </Space.Compact>
          {ciPreviewMutation.error ? <Alert type="error" showIcon message={errorText(ciPreviewMutation.error)} /> : null}
          {ciLaunchMutation.error ? <Alert type="error" showIcon message={errorText(ciLaunchMutation.error)} /> : null}
          {repositoryPreviewMutation.error ? <Alert type="error" showIcon message={errorText(repositoryPreviewMutation.error)} /> : null}
          {repositoryImportMutation.error ? <Alert type="error" showIcon message={errorText(repositoryImportMutation.error)} /> : null}
          {ciPreview ? (
            <>
              <Descriptions size="small" column={1} bordered>
                <Descriptions.Item label="Reference">{valueText(ciPreview.reference, ciReference)}</Descriptions.Item>
                <Descriptions.Item label="Repository">{valueText(recordValue(ciPreview.context).owner)}/{valueText(recordValue(ciPreview.context).repo)}{recordValue(ciPreview.context).number ? `#${valueText(recordValue(ciPreview.context).number)}` : ''}</Descriptions.Item>
                <Descriptions.Item label="Title">{valueText(recordValue(ciPreview.context).title)}</Descriptions.Item>
                <Descriptions.Item label="Failures">{valueText(ciPreview.failure_count, '0')}</Descriptions.Item>
                <Descriptions.Item label="Changed files">{arrayLength(recordValue(ciPreview.context).changed_files)}</Descriptions.Item>
                <Descriptions.Item label="Warnings">{arrayLength(ciPreview.warnings)}</Descriptions.Item>
                <Descriptions.Item label="Degraded">{boolText(ciPreview.degraded)}</Descriptions.Item>
              </Descriptions>
              <details>
                <summary>Raw payload</summary>
                <pre data-testid="operate-ci-preview-result" className="templatePreview">{JSON.stringify(ciPreview, null, 2)}</pre>
              </details>
            </>
          ) : null}
          {ciLaunch ? <Alert data-testid="operate-ci-launch-result" type="success" showIcon message="CI launch patch ready" description={valueText(recordValue(ciLaunch.launch_patch).print_prompt_append || ciLaunch.reference, 'launch ready')} /> : null}
          <Space wrap>
            <Button data-testid="operate-repository-preview" disabled={!canImportRepository} loading={repositoryPreviewMutation.isPending} onClick={() => repositoryPreviewMutation.mutate()}>Repository Preview</Button>
            <Button data-testid="operate-repository-import" disabled={!canImportRepository} loading={repositoryImportMutation.isPending} onClick={() => repositoryImportMutation.mutate()}>Import Context</Button>
          </Space>
          {repositoryPreview ? (
            <>
              <Typography.Text type="secondary">Repository context preview ready · {valueText(repositoryPreview.reference || recordValue(repositoryPreview.preview).reference, ciReference)}</Typography.Text>
              <details>
                <summary>Raw payload</summary>
                <pre data-testid="operate-repository-preview-result" className="templatePreview">{JSON.stringify(repositoryPreview, null, 2)}</pre>
              </details>
            </>
          ) : null}
          {repositoryImport ? <Alert data-testid="operate-repository-import-result" type="success" showIcon message="Repository context imported" description={valueText(recordValue(repositoryImport.launch_patch).print_prompt_append || recordValue(repositoryImport.preview).reference, 'import ready')} /> : null}
          <Table<Record<string, unknown>>
            rowKey={(row, index) => valueText(row.id || row.name, String(index))}
            dataSource={automationRules}
            loading={operate.isLoading}
            pagination={{ pageSize: 4 }}
            columns={[
              { title: 'Rule', render: (_value, row) => valueText(row.name || row.id) },
              { title: 'Enabled', dataIndex: 'enabled', render: (value: unknown) => <Tag color={value === false ? 'default' : 'blue'}>{value === false ? 'disabled' : 'enabled'}</Tag> },
              {
                title: 'Trigger',
                dataIndex: 'trigger',
                render: (value: unknown) => {
                  const trigger = recordValue(value);
                  const label = valueText(trigger.type || trigger.event, Object.keys(trigger)[0] || valueText(value, 'n/a'));
                  return <code title={JSON.stringify(value || {})}>{label}</code>;
                }
              }
            ]}
          />
          <Input.TextArea data-testid="operate-automation-event-json" value={automationEventJson} onChange={(event) => setAutomationEventJson(event.target.value)} autoSize={{ minRows: 3, maxRows: 6 }} />
          <Space wrap>
            <Button data-testid="operate-automation-test" disabled={!canManageAutomation} loading={automationTestMutation.isPending} onClick={() => automationTestMutation.mutate()}>Test</Button>
            {automationTest ? <Tag data-testid="operate-automation-test-result" color="green">{valueText(automationTest.matched_count, '0')} matched</Tag> : null}
            <Button data-testid="operate-automation-preview-schedules" disabled={!canManageAutomation} loading={automationSchedulePreviewMutation.isPending} onClick={() => automationSchedulePreviewMutation.mutate()}>Preview Due Schedules</Button>
            {automationSchedulePreview ? <Tag data-testid="operate-automation-schedules-preview-result" color="blue">{listValue(automationSchedulePreview.schedules).filter((row) => row.due).length} due</Tag> : null}
            <Button data-testid="operate-automation-run-schedules" disabled={!canManageAutomation} loading={automationScheduleMutation.isPending} onClick={() => automationScheduleMutation.mutate()}>Run Due Schedules</Button>
            {automationScheduleRun ? <Tag data-testid="operate-automation-schedules-result" color="blue">{valueText(automationScheduleRun.executed_count, '0')} executed</Tag> : null}
          </Space>
          {automationTestMutation.error ? <Alert type="error" showIcon message={errorText(automationTestMutation.error)} /> : null}
          {automationSchedulePreviewMutation.error ? <Alert type="error" showIcon message={errorText(automationSchedulePreviewMutation.error)} /> : null}
          {automationScheduleMutation.error ? <Alert type="error" showIcon message={errorText(automationScheduleMutation.error)} /> : null}
          {automationTest ? (
            <details>
              <summary>Raw payload</summary>
              <pre className="templatePreview">{JSON.stringify(automationTest, null, 2)}</pre>
            </details>
          ) : null}
          {automationSchedulePreview ? (
            <details>
              <summary>Raw payload</summary>
              <pre className="templatePreview">{JSON.stringify(automationSchedulePreview, null, 2)}</pre>
            </details>
          ) : null}
          {automationScheduleRun ? (
            <details>
              <summary>Raw payload</summary>
              <pre className="templatePreview">{JSON.stringify(automationScheduleRun, null, 2)}</pre>
            </details>
          ) : null}
          <div id="operate-section-ci" style={{ scrollMarginTop: 16 }}>
          <Table<Record<string, unknown>>
            rowKey={(row, index) => valueText(row.id || row.name || row.check, String(index))}
            dataSource={ciFindings}
            loading={operate.isLoading}
            pagination={{ pageSize: 4 }}
            columns={[
              { title: 'Finding', render: (_value, row) => valueText(row.title || row.name || row.check || row.id) },
              { title: 'Status', dataIndex: 'status' },
              { title: 'Severity', dataIndex: 'severity' }
            ]}
          />
          </div>
        </Space>
      </Card>
      <Card title="Model Deprecations" data-testid="operate-deprecations">
        {modelDeprecationsError ? <Alert type="warning" showIcon message="Model deprecation data could not be loaded" description={modelDeprecationsError} style={{ marginBottom: 12 }} /> : null}
        {modelDeprecationPreviewMutation.error ? <Alert type="error" showIcon message={errorText(modelDeprecationPreviewMutation.error)} /> : null}
        {modelDeprecationPreview ? <Alert data-testid="operate-model-deprecation-preview-result" type="info" showIcon message="Migration preview ready" description={`${valueText(modelDeprecationPreview.model)} -> ${valueText(modelDeprecationPreview.replacement_model, 'select replacement')}`} /> : null}
        <Table<Record<string, unknown>>
          rowKey={(row, index) => valueText(row.id || row.model, String(index))}
          dataSource={modelDeprecations}
          loading={operate.isLoading}
          pagination={{ pageSize: 6 }}
          columns={[
            { title: 'Model', render: (_value, row) => valueText(row.id || row.model) },
            { title: 'Status', dataIndex: 'status' },
            { title: 'Replacement', render: (_value, row) => valueText(row.replacement || row.replacement_model) },
            {
              title: 'Action',
              render: (_value, row) => (
                <Button
                  data-testid="operate-model-deprecation-preview"
                  size="small"
                  disabled={!canManageModels || !(row.model || row.id)}
                  loading={modelDeprecationPreviewMutation.isPending}
                  onClick={() => modelDeprecationPreviewMutation.mutate(valueText(row.model || row.id))}
                >
                  Preview
                </Button>
              )
            }
          ]}
        />
        {modelDeprecationPreview ? (
          <>
            <Descriptions size="small" column={1} bordered style={{ marginTop: 12 }}>
              <Descriptions.Item label="Model">{valueText(modelDeprecationPreview.model)}</Descriptions.Item>
              <Descriptions.Item label="Replacement">{valueText(modelDeprecationPreview.replacement_model, 'select replacement')}</Descriptions.Item>
              <Descriptions.Item label="Status">{valueText(recordValue(modelDeprecationPreview.deprecation).status)}</Descriptions.Item>
              <Descriptions.Item label="Severity">{valueText(recordValue(modelDeprecationPreview.deprecation).severity)}</Descriptions.Item>
              <Descriptions.Item label="Affected artifacts">{arrayLength(modelDeprecationPreview.affected)}</Descriptions.Item>
              <Descriptions.Item label="Planned changes">{arrayLength(modelDeprecationPreview.changes)}</Descriptions.Item>
              <Descriptions.Item label="Recommendations">{arrayLength(modelDeprecationPreview.recommendations)}</Descriptions.Item>
              <Descriptions.Item label="Eval recommended">{boolText(recordValue(modelDeprecationPreview.eval_gate).recommended)}</Descriptions.Item>
            </Descriptions>
            <details>
              <summary>Raw payload</summary>
              <pre className="templatePreview">{JSON.stringify(modelDeprecationPreview, null, 2)}</pre>
            </details>
          </>
        ) : null}
      </Card>
    </Space>
  );
}
