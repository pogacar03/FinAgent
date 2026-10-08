import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type MouseEvent, type ReactNode } from 'react';
import {
  api,
  type AuditEvent,
  type BacktestJob,
  type BacktestResult,
  type BenchmarkEnvelope,
  type EvidenceItem,
  type Mode,
  type PersonaReport,
  type Pick,
  type PicksEnvelope,
  type ResearchMode,
  type ResearchResult,
  type RunJob,
} from './api';
import { resolveBacktestBenchmark } from './benchmarkProvenance';

const RUN_KEY = 'finagent.selectedRun';
const BACKTEST_PREFIX = 'finagent.backtest.';
const ACTIVE_JOB = new Set(['QUEUED', 'RUNNING', 'RETRY']);
const TERMINAL_RUN = new Set(['COMPLETED', 'INSUFFICIENT_ELIGIBLE_STOCKS', 'FAILED', 'UNAVAILABLE']);

const researchModeLabels: Record<ResearchMode, string> = {
  quant_only: '量化筛选',
  single_agent_skills: '单角色研究',
  multi_persona: '多角色研究',
  multi_persona_debate: '多角色 + 一轮复核',
};

const statusLabels: Record<string, string> = {
  QUEUED: '排队中',
  RUNNING: '研究中',
  RETRY: '重试中',
  COMPLETED: '已完成',
  INSUFFICIENT_ELIGIBLE_STOCKS: '合格标的不足',
  FAILED: '执行失败',
  UNAVAILABLE: '数据不可用',
  PENDING: '等待完整窗口',
  VALIDATION_FAILED: '数据校验失败',
  AVAILABLE: '已核验',
  UNVERIFIED: '未核验',
};

function statusTone(status?: string): string {
  if (status === 'COMPLETED' || status === 'AVAILABLE') return 'green';
  if (status === 'FAILED' || status === 'VALIDATION_FAILED') return 'red';
  if (status === 'UNAVAILABLE' || status === 'UNVERIFIED' || status === 'INSUFFICIENT_ELIGIBLE_STOCKS') return 'amber';
  return 'blue';
}

function labelStatus(status?: string): string {
  if (!status) return '未提交';
  return statusLabels[status] ?? status;
}

function money(value?: number | null, currency = 'USD'): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

function percent(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${(value * 100).toFixed(2)}%`;
}

function percentagePoints(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${value.toFixed(2)} 个百分点`;
}

function dateTime(value?: string | number): string {
  if (value == null) return '—';
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
  if (!Number.isFinite(date.getTime())) return '—';
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function shortHash(hash?: string): string {
  return hash ? `${hash.slice(0, 12)}…${hash.slice(-6)}` : '—';
}

function runIdOf(run: RunJob): string {
  return run.run_id || run.id || '';
}

function StatusPill({ status, children }: { status?: string; children?: ReactNode }) {
  return <span className={`status-pill ${statusTone(status)}`}><i aria-hidden="true" />{children ?? labelStatus(status)}</span>;
}

function EmptyState({ title, children, icon = '⌁' }: { title: string; children: ReactNode; icon?: string }) {
  return (
    <div className="empty-state">
      <span className="empty-icon" aria-hidden="true">{icon}</span>
      <strong>{title}</strong>
      <p>{children}</p>
    </div>
  );
}

function DemoNotice({ mode }: { mode: Mode }) {
  return mode === 'DEMO' ? (
    <div className="demo-notice" role="note">
      <span className="notice-mark" aria-hidden="true">!</span>
      <div><strong>DEMO / SYNTHETIC</strong><span>本模式中的历史价格、财务、预测假设与回报路径均为合成示例，不代表真实历史表现。</span></div>
    </div>
  ) : (
    <div className="real-notice" role="note">
      <span className="notice-mark" aria-hidden="true">i</span>
      <div><strong>REAL 数据模式</strong><span>需要已配置并通过时间点校验的数据源；缺少可验证数据时系统会明确返回 UNAVAILABLE。</span></div>
    </div>
  );
}

function safeExternalUri(uri: string): boolean {
  try {
    const parsed = new URL(uri);
    return parsed.protocol === 'https:' || parsed.protocol === 'http:';
  } catch {
    return false;
  }
}

function EvidenceRow({ item }: { item: EvidenceItem }) {
  const external = safeExternalUri(item.source_uri);
  return (
    <article className="evidence-row">
      <div className="evidence-heading">
        <div><strong>{item.field}</strong><span className="evidence-kind">{item.kind === 'ASSUMPTION' ? '假设' : '证据'}</span></div>
        <StatusPill status={item.pit_status}>{item.pit_status}</StatusPill>
      </div>
      <div className="evidence-value">{String(item.value)}</div>
      <div className="evidence-meta">
        <span>可用时间 {dateTime(item.available_at)}</span>
        <span title={item.content_hash}>SHA {shortHash(item.content_hash)}</span>
      </div>
      <div className="source-uri">
        <span>来源</span>
        {external ? <a href={item.source_uri} target="_blank" rel="noreferrer">{item.source_uri}</a> : <code>{item.source_uri}</code>}
      </div>
    </article>
  );
}

function PersonaCard({ report }: { report: PersonaReport }) {
  return (
    <article className="persona-card">
      <div className="persona-title"><span className={`persona-dot ${report.persona.toLowerCase()}`} />
        <h3>{report.persona}</h3>
        {report.target_price_candidate != null && <strong>{money(report.target_price_candidate)}</strong>}
      </div>
      <p className="persona-rationale">{report.rationale || report.abstain_reason || '该角色未提供文字说明。'}</p>
      {report.abstain_reason && <div className="inline-warning">弃权原因：{report.abstain_reason}</div>}
      {report.risk_flags && report.risk_flags.length > 0 ? (
        <div className="risk-tags">{report.risk_flags.map((risk) => <span key={risk}>{risk}</span>)}</div>
      ) : <div className="muted-line">角色未列出风险提示；这不表示没有风险。</div>}
      {report.assumptions && report.assumptions.length > 0 && (
        <div className="assumption-list">
          <span className="mini-label">关键假设</span>
          {report.assumptions.map((assumption) => (
            <div className="assumption-row" key={`${assumption.name}-${assumption.value}`}>
              <span>{assumption.name}</span><b>{assumption.value} {assumption.unit}</b>
              <small>{assumption.rationale}</small>
            </div>
          ))}
        </div>
      )}
      <div className="persona-foot">证据引用 {report.evidence_ids?.length ?? 0} 项 · 模型 {report.model_version ?? '—'}</div>
    </article>
  );
}

function ResearchDialog({
  ticker,
  runId,
  onClose,
}: {
  ticker: string;
  runId: string;
  onClose: () => void;
}) {
  const [research, setResearch] = useState<ResearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const dialogRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api<ResearchResult>(`/api/stocks/${encodeURIComponent(ticker)}/research?run_id=${encodeURIComponent(runId)}`, { signal: controller.signal })
      .then((data) => { setResearch(data); setLoading(false); })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : '读取研究记录失败');
        setLoading(false);
      });
    return () => controller.abort();
  }, [runId, ticker]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKeyDown);
    dialogRef.current?.focus();
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const valuation = research?.valuation;
  const currency = valuation?.currency ?? 'USD';
  return (
    <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="research-dialog" role="dialog" aria-modal="true" aria-labelledby="research-dialog-title" tabIndex={-1} ref={dialogRef}>
        <header className="dialog-header">
          <div><span className="eyebrow">个股研究档案</span><h2 id="research-dialog-title">{ticker} <span>{research?.sector ?? ''}</span></h2></div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="关闭研究档案">×</button>
        </header>
        {research?.mode === 'DEMO' && <div className="dialog-demo-label">DEMO / SYNTHETIC · 本档案内的所有历史数据与预测均为合成示例</div>}
        {loading && <div className="dialog-loading"><span className="spinner" />正在读取研究快照…</div>}
        {error && !loading && <div className="error-panel"><strong>研究记录暂不可用</strong><span>{error}</span></div>}
        {research && !loading && (
          <div className="dialog-body">
            <div className="research-meta-grid">
              <div><span>时间点状态</span><StatusPill status={research.snapshot.pit_status}>{research.snapshot.pit_status}</StatusPill></div>
              <div><span>研究模式</span><b>{researchModeLabels[research.research_mode]}</b></div>
              <div><span>目标价 · 12 个月</span><b>{money(valuation?.target_12m, currency)}</b></div>
              <div><span>估值入场价</span><b>{money(valuation?.entry_price, currency)}</b></div>
              <div><span>安全边际</span><b>{valuation ? `${(valuation.safety_margin * 100).toFixed(0)}%` : '—'}</b></div>
              <div><span>币种 / 公司行动口径</span><b>{currency} · {valuation?.corporate_action_basis ?? '—'}</b></div>
            </div>
            {valuation?.abstain_reason && <div className="inline-warning">估值弃权：{valuation.abstain_reason}</div>}
            {valuation?.methods && valuation.methods.length > 0 && (
              <section className="dialog-section">
                <div className="subsection-heading"><h3>估值拆解</h3><span>由研究证据和显式假设计算</span></div>
                <div className="method-grid">{valuation.methods.map((method) => <div className="method-card" key={method.method}><span>{method.method}</span><b>{money(method.value, currency)}</b><small>{method.assumptions?.map((a) => `${a.name}: ${a.value} ${a.unit}`).join(' · ') || '未返回拆分假设'}</small></div>)}</div>
              </section>
            )}
            <section className="dialog-section">
              <div className="subsection-heading"><h3>角色观点</h3><span>同一 12 个月期限 · 分别记录依据与假设</span></div>
              <div className="persona-grid">
                {research.reports.map((report) => <PersonaCard key={report.persona} report={report} />)}
                {research.reports.length === 0 && <p className="muted-line">此研究模式没有角色报告。</p>}
              </div>
            </section>
            <section className="dialog-section">
              <div className="subsection-heading"><h3>证据快照</h3><span title={research.snapshot.content_hash}>快照 {shortHash(research.snapshot.content_hash)} · 截止 {dateTime(research.snapshot.decision_at)}</span></div>
              {research.snapshot.warnings && research.snapshot.warnings.length > 0 && <div className="warning-list">{research.snapshot.warnings.map((warning) => <span key={warning}>{warning}</span>)}</div>}
              <div className="evidence-list">{research.snapshot.items.map((item) => <EvidenceRow key={item.evidence_id} item={item} />)}</div>
            </section>
            <div className="record-foot">快照 ID <code>{research.snapshot.snapshot_id}</code> · 模型 {research.versions?.model ?? '—'} · 图版本 {research.versions?.graph ?? '—'} · 提示版本 {research.versions?.prompt ?? '—'}</div>
          </div>
        )}
      </section>
    </div>
  );
}

function ReturnChart({ result }: { result: BacktestResult }) {
  const series = [
    result.finagent && { name: 'FinAgent', value: result.finagent.total_return, color: '#5bd1bc' },
    result.seeking_alpha && { name: 'Seeking Alpha', value: result.seeking_alpha.total_return, color: '#75a7ff' },
    result.spy && { name: 'SPY', value: result.spy.total_return, color: '#f2b96e' },
  ].filter((item): item is { name: string; value: number; color: string } => Boolean(item));
  if (series.length === 0) return null;
  const minValue = Math.min(0, ...series.map((item) => item.value));
  const maxValue = Math.max(0, ...series.map((item) => item.value));
  const span = Math.max(maxValue - minValue, 0.01);
  const padding = span * 0.12;
  const min = minValue - padding;
  const max = maxValue + padding;
  const plotStart = 160;
  const plotWidth = 390;
  const scale = (value: number) => plotStart + ((value - min) / (max - min)) * plotWidth;
  const zero = scale(0);
  return (
    <div className="chart-wrap">
      <svg className="return-chart" viewBox="0 0 650 162" role="img" aria-label="FinAgent、Seeking Alpha 与 SPY 的实际组合总回报对比">
        <line x1={zero} x2={zero} y1="12" y2="146" stroke="#52657d" strokeDasharray="4 5" />
        <text x={plotStart} y="158" className="axis-label">{percent(min)}</text>
        <text x={plotStart + plotWidth} y="158" className="axis-label" textAnchor="end">{percent(max)}</text>
        {series.map((item, index) => {
          const y = 28 + index * 42;
          const end = scale(item.value);
          const x = Math.min(zero, end);
          const width = Math.max(1, Math.abs(end - zero));
          return <g key={item.name}>
            <text x="0" y={y + 14} className="chart-label">{item.name}</text>
            <line x1={plotStart} x2={plotStart + plotWidth} y1={y + 10} y2={y + 10} stroke="#223249" strokeWidth="10" strokeLinecap="round" />
            <rect x={x} y={y + 4} width={width} height="13" rx="6.5" fill={item.color} />
            <text x="640" y={y + 14} className="chart-value" textAnchor="end">{percent(item.value)}</text>
          </g>;
        })}
      </svg>
    </div>
  );
}

function BacktestBenchmarkProvenance({ job }: { job: BacktestJob }) {
  const provenance = resolveBacktestBenchmark(job);
  const pinned = provenance.kind === 'pinned' ? provenance.benchmark : null;
  const resultStatus = job.result?.seeking_alpha_status;
  const sourceTone = pinned?.verification_status === 'PIT_VERIFIED' ? 'AVAILABLE' : 'UNVERIFIED';
  return (
    <section className="backtest-provenance" aria-label="本次回测的 Seeking Alpha 基准来源">
      <div className="provenance-heading">
        <div><span className="eyebrow">回测输入快照</span><strong>本次回测绑定的 SA 榜单</strong></div>
        <div className="provenance-badges">
          {pinned && <StatusPill status={sourceTone}>{pinned.verification_status}</StatusPill>}
          {resultStatus && <StatusPill status={resultStatus}>本次比较 · {resultStatus}</StatusPill>}
        </div>
      </div>
      {pinned ? <>
        <div className="pinned-source-line">
          <span>{pinned.period} · 发布于 {dateTime(pinned.published_at)}</span>
          {safeExternalUri(pinned.source_uri)
            ? <a href={pinned.source_uri} target="_blank" rel="noreferrer">{pinned.source_uri}</a>
            : <code>{pinned.source_uri}</code>}
          <code title={pinned.content_hash}>SHA {shortHash(pinned.content_hash)}</code>
        </div>
        {pinned.verification_note && <p className="provenance-note">{pinned.verification_note}</p>}
      </> : <p className="provenance-missing">{provenance.kind === 'not_bound'
        ? '提交这次回测时没有绑定 SA 榜单，因此本次结果不包含 Seeking Alpha 对照。'
        : '这条回测记录没有保存 SA 基准快照，无法确认它使用过哪份榜单。当前登记列表不会关联到这次回测。'}</p>}
    </section>
  );
}

function App() {
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [runs, setRuns] = useState<RunJob[]>([]);
  const [selectedRunId, setSelectedRunId] = useState(() => {
    try { return localStorage.getItem(RUN_KEY) ?? ''; } catch { return ''; }
  });
  const [runRecord, setRunRecord] = useState<RunJob | null>(null);
  const [picksEnvelope, setPicksEnvelope] = useState<PicksEnvelope | null>(null);
  const [benchmark, setBenchmark] = useState<BenchmarkEnvelope | null>(null);
  const [coverage, setCoverage] = useState<{ settled: boolean; loaded: number; riskFlags: number } | null>(null);
  const [backtestId, setBacktestId] = useState('');
  const [backtestRecord, setBacktestRecord] = useState<BacktestJob | null>(null);
  const [period, setPeriod] = useState('2025-H2');
  const [mode, setMode] = useState<Mode>('DEMO');
  const [researchMode, setResearchMode] = useState<ResearchMode>('multi_persona');
  const [policy, setPolicy] = useState<'PRIMARY' | 'LIMIT_ENTRY'>('PRIMARY');
  const [submitting, setSubmitting] = useState(false);
  const [submittingBacktest, setSubmittingBacktest] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [auditOpen, setAuditOpen] = useState(false);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditError, setAuditError] = useState<string | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const closeResearch = useCallback(() => setSelectedTicker(null), []);

  const activeRun = useMemo(() => {
    if (runRecord && runIdOf(runRecord) === selectedRunId) return runRecord;
    return runs.find((run) => runIdOf(run) === selectedRunId) ?? null;
  }, [runRecord, runs, selectedRunId]);
  const runStatus = activeRun?.status;
  const activeMode: Mode = activeRun?.payload?.mode ?? mode;
  const picks = picksEnvelope?.run_id === selectedRunId ? picksEnvelope.picks : [];
  const isFrozen = Boolean(picksEnvelope?.run_id === selectedRunId && picksEnvelope.signal);
  const result = backtestRecord?.result ?? null;
  const backtestDisplayStatus = result?.status ?? backtestRecord?.status;

  const refreshRuns = useCallback(async (signal?: AbortSignal) => {
    const data = await api<{ runs: RunJob[] }>('/api/runs', { signal });
    const list = data.runs ?? [];
    setRuns(list);
    setSelectedRunId((current) => {
      if (current && list.some((item) => runIdOf(item) === current)) return current;
      return list[0] ? runIdOf(list[0]) : '';
    });
  }, []);

  useEffect(() => {
    let timer = 0;
    const controller = new AbortController();
    const checkHealth = async () => {
      try {
        await api('/api/health', { signal: controller.signal });
        setApiOnline(true);
      } catch {
        if (!controller.signal.aborted) setApiOnline(false);
      }
      if (!controller.signal.aborted) timer = window.setTimeout(checkHealth, 12000);
    };
    void checkHealth();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    refreshRuns(controller.signal).catch((error: unknown) => {
      if (!controller.signal.aborted) setPageError(error instanceof Error ? error.message : '读取任务列表失败');
    });
    return () => controller.abort();
  }, [refreshRuns]);

  useEffect(() => {
    try { if (selectedRunId) localStorage.setItem(RUN_KEY, selectedRunId); } catch { /* storage may be disabled */ }
  }, [selectedRunId]);

  useEffect(() => {
    setRunRecord(null);
    setPicksEnvelope(null);
    setBenchmark(null);
    setCoverage(null);
    setBacktestRecord(null);
    setAuditEvents([]);
    if (!selectedRunId) return;
    try { setBacktestId(localStorage.getItem(`${BACKTEST_PREFIX}${selectedRunId}`) ?? ''); } catch { setBacktestId(''); }

    const controller = new AbortController();
    let timer = 0;
    const loadRun = async () => {
      try {
        const item = await api<RunJob>(`/api/runs/${encodeURIComponent(selectedRunId)}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setRunRecord(item);
        setRuns((current) => [item, ...current.filter((entry) => runIdOf(entry) !== selectedRunId)]);
        setPageError(null);
        if (ACTIVE_JOB.has(item.status)) timer = window.setTimeout(loadRun, 1500);
      } catch (error) {
        if (controller.signal.aborted) return;
        setPageError(error instanceof Error ? error.message : '读取任务状态失败');
        timer = window.setTimeout(loadRun, 5000);
      }
    };
    void loadRun();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [selectedRunId]);

  useEffect(() => {
    if (!selectedRunId || !runStatus || !TERMINAL_RUN.has(runStatus)) return;
    const controller = new AbortController();
    api<PicksEnvelope>(`/api/runs/${encodeURIComponent(selectedRunId)}/picks`, { signal: controller.signal })
      .then(setPicksEnvelope)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setPageError(error instanceof Error ? error.message : '读取选股结果失败');
      });
    return () => controller.abort();
  }, [runStatus, selectedRunId]);

  useEffect(() => {
    if (!selectedRunId || !activeRun || !TERMINAL_RUN.has(activeRun.status)) return;
    const controller = new AbortController();
    api<BenchmarkEnvelope>(`/api/benchmarks/sa/${encodeURIComponent(activeRun.payload.period)}`, { signal: controller.signal })
      .then(setBenchmark)
      .catch(() => { if (!controller.signal.aborted) setBenchmark({ status: 'UNAVAILABLE' }); });
    return () => controller.abort();
  }, [activeRun, selectedRunId]);

  useEffect(() => {
    if (!selectedRunId || picksEnvelope?.run_id !== selectedRunId || picks.length === 0) return;
    const controller = new AbortController();
    setCoverage({ settled: false, loaded: 0, riskFlags: 0 });
    Promise.allSettled(picks.map((pick) => api<ResearchResult>(
      `/api/stocks/${encodeURIComponent(pick.ticker)}/research?run_id=${encodeURIComponent(selectedRunId)}`,
      { signal: controller.signal },
    ))).then((results) => {
      if (controller.signal.aborted) return;
      const records = results.flatMap((item) => item.status === 'fulfilled' ? [item.value] : []);
      const riskFlags = records.reduce((count, record) => count + record.reports.reduce((sum, report) => sum + (report.risk_flags?.length ?? 0), 0), 0);
      setCoverage({ settled: true, loaded: records.length, riskFlags });
    });
    return () => controller.abort();
  }, [picks, picksEnvelope?.run_id, selectedRunId]);

  useEffect(() => {
    if (!backtestId) { setBacktestRecord(null); return; }
    const controller = new AbortController();
    let timer = 0;
    const loadBacktest = async () => {
      try {
        const item = await api<BacktestJob>(`/api/backtests/${encodeURIComponent(backtestId)}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setBacktestRecord(item);
        if (ACTIVE_JOB.has(item.status)) timer = window.setTimeout(loadBacktest, 1500);
      } catch (error) {
        if (controller.signal.aborted) return;
        setPageError(error instanceof Error ? error.message : '读取回测状态失败');
        timer = window.setTimeout(loadBacktest, 5000);
      }
    };
    void loadBacktest();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [backtestId]);

  useEffect(() => {
    if (!auditOpen || !selectedRunId) return;
    const controller = new AbortController();
    setAuditError(null);
    api<{ events: AuditEvent[] }>(`/api/runs/${encodeURIComponent(selectedRunId)}/audit`, { signal: controller.signal })
      .then((data) => setAuditEvents(data.events ?? []))
      .catch((error: unknown) => { if (!controller.signal.aborted) setAuditError(error instanceof Error ? error.message : '读取审计事件失败'); });
    return () => controller.abort();
  }, [auditOpen, selectedRunId]);

  useEffect(() => {
    if (!selectedTicker) triggerRef.current?.focus();
  }, [selectedTicker]);

  const submitRun = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!/^20\d{2}-H[12]$/.test(period)) {
      setPageError('周期格式应为 YYYY-H1 或 YYYY-H2，例如 2025-H2。');
      return;
    }
    setSubmitting(true);
    setPageError(null);
    try {
      const created = await api<{ run_id: string; status: string; mode: Mode }>('/api/runs', {
        method: 'POST',
        body: JSON.stringify({ period, mode, research_mode: researchMode }),
      });
      setSelectedRunId(created.run_id);
      await refreshRuns();
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '提交研究任务失败');
    } finally {
      setSubmitting(false);
    }
  };

  const submitBacktest = async () => {
    if (!selectedRunId || !isFrozen) return;
    setSubmittingBacktest(true);
    setPageError(null);
    try {
      const created = await api<{ backtest_id: string; status: string }>('/api/backtests', {
        method: 'POST',
        body: JSON.stringify({ run_id: selectedRunId, policy }),
      });
      setBacktestId(created.backtest_id);
      try { localStorage.setItem(`${BACKTEST_PREFIX}${selectedRunId}`, created.backtest_id); } catch { /* storage may be disabled */ }
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '提交回测任务失败');
    } finally {
      setSubmittingBacktest(false);
    }
  };

  const openResearch = (ticker: string, event: MouseEvent<HTMLButtonElement>) => {
    triggerRef.current = event.currentTarget;
    setSelectedTicker(ticker);
  };

  const percentageRegexValid = /^20\d{2}-H[12]$/.test(period);
  const outerRunStatus = activeRun?.status;
  const progress = Math.max(0, Math.min(100, activeRun?.progress ?? (outerRunStatus === 'COMPLETED' ? 100 : 0)));
  const noResearchResult = outerRunStatus && TERMINAL_RUN.has(outerRunStatus) && picksEnvelope?.run_id === selectedRunId && picks.length === 0;

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="FinAgent 首页">
          <span className="brand-mark"><i /><i /><i /></span>
          <span><strong>FINAGENT</strong><small>RESEARCH TERMINAL</small></span>
        </a>
        <div className="topbar-right">
          <label className="history-picker"><span>最近任务</span>
            <select aria-label="选择历史研究任务" value={selectedRunId} onChange={(event) => setSelectedRunId(event.target.value)}>
              <option value="">选择任务</option>
              {runs.map((run) => <option key={runIdOf(run)} value={runIdOf(run)}>{run.payload?.period ?? '未知周期'} · {run.payload?.mode ?? '未知模式'} · {labelStatus(run.status)}</option>)}
            </select>
          </label>
          <span className={`connection ${apiOnline === true ? 'online' : apiOnline === false ? 'offline' : ''}`}><i />API {apiOnline === true ? '在线' : apiOnline === false ? '离线' : '检测中'}</span>
          <span className="avatar-mark" aria-hidden="true">F</span>
        </div>
      </header>

      <main id="top" className="page-content">
        <div className="page-intro">
          <div><div className="breadcrumb"><span>工作台</span><b>/</b><strong>半年度研究</strong></div><h1>研究工作台</h1><p>从冻结的研究信号到六个月回测，每一步都能追溯到来源与时间点。</p></div>
          <div className="intro-mark"><span>US EQUITIES</span><strong>H1 / H2</strong></div>
        </div>

        <DemoNotice mode={activeMode} />

        {pageError && <div className="page-error" role="alert"><span><b>请求未完成</b>{pageError}</span><button type="button" onClick={() => setPageError(null)} aria-label="关闭错误提示">×</button></div>}

        <section className="setup-grid" aria-labelledby="setup-title">
          <div className="panel setup-panel">
            <div className="panel-heading"><div><span className="eyebrow">研究配置</span><h2 id="setup-title">创建半年度研究</h2></div><span className="step-index">01 <i>/ 03</i></span></div>
            <form onSubmit={submitRun}>
              <div className="form-grid">
                <label className="field"><span>研究周期</span><div className="input-wrap"><input aria-label="研究周期" value={period} onChange={(event) => setPeriod(event.target.value.toUpperCase())} placeholder="2025-H2" maxLength={7} aria-invalid={!percentageRegexValid} /><span className="input-suffix">H1 / H2</span></div><small>按半年度决策时点筛选，例如 2025-H2</small></label>
                <label className="field"><span>数据环境</span><select aria-label="数据环境" value={mode} onChange={(event) => setMode(event.target.value as Mode)}><option value="DEMO">DEMO · 离线合成演示</option><option value="REAL">REAL · 配置的真实数据</option></select><small>{mode === 'DEMO' ? '整条研究和回测链路使用 SYNTHETIC 数据' : '必须提供来源和 PIT 核验的真实数据'}</small></label>
                <label className="field field-wide"><span>研究方法</span><select aria-label="研究方法" value={researchMode} onChange={(event) => setResearchMode(event.target.value as ResearchMode)}>{Object.entries(researchModeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><small>同一合格股票池按所选方法生成可复核报告</small></label>
              </div>
              <div className="form-footer"><span><span className="tiny-dot" />无交易执行 · 冻结信号后再做模拟比较</span><button className="primary-button" type="submit" disabled={!percentageRegexValid || submitting}><span>{submitting ? '正在提交…' : '开始研究'}</span><b aria-hidden="true">↗</b></button></div>
            </form>
          </div>

          <div className="panel run-panel">
            <div className="panel-heading"><div><span className="eyebrow">当前任务</span><h2>{activeRun?.payload?.period ?? '等待提交'}</h2></div><StatusPill status={outerRunStatus} /></div>
            {activeRun ? <>
              <div className="run-identity"><span>RUN ID</span><code title={selectedRunId}>{selectedRunId}</code><button type="button" className="copy-button" onClick={() => navigator.clipboard?.writeText(selectedRunId).catch(() => undefined)} aria-label="复制运行编号">复制</button></div>
              <div className="progress-head"><span>研究进度</span><b>{progress}%</b></div>
              <div className="progress-track" role="progressbar" aria-label="研究进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div>
              <div className="run-meta"><span>{activeRun.payload.mode} · {researchModeLabels[activeRun.payload.research_mode]}</span><span>创建于 {dateTime(activeRun.created_at)}</span></div>
              {activeRun.error && <div className="run-error">错误代码：{activeRun.error}</div>}
            </> : <EmptyState title="还没有研究任务" icon="↗">选择周期和研究方法后提交。演示预设为 2025-H2 / DEMO / 多角色研究。</EmptyState>}
          </div>
        </section>

        <section className="metrics-grid" aria-label="研究概览">
          <article className="metric-card"><div className="metric-icon cyan">⌖</div><div><span>研究周期</span><strong>{activeRun?.payload?.period ?? '—'}</strong><small>{activeRun?.payload?.mode ?? '待选择数据环境'}</small></div></article>
          <article className="metric-card"><div className="metric-icon violet">▤</div><div><span>冻结标的</span><strong>{picksEnvelope?.run_id === selectedRunId ? picks.length : '—'}<small>{picksEnvelope?.run_id === selectedRunId ? ' / 10' : ''}</small></strong><small>{isFrozen ? '等权信号已冻结' : labelStatus(outerRunStatus)}</small></div></article>
          <article className="metric-card"><div className="metric-icon amber">◷</div><div><span>时间点状态</span><strong className="metric-text">{picksEnvelope?.signal?.pit_status ?? '待验证'}</strong><small>{picksEnvelope?.signal ? `冻结于 ${dateTime(picksEnvelope.signal.frozen_at)}` : '结果到达后显示'}</small></div></article>
          <article className="metric-card"><div className="metric-icon green">◇</div><div><span>已检查风险提示</span><strong>{coverage?.settled ? coverage.riskFlags : '—'}<small> 条</small></strong><small>{coverage?.settled ? `已读取 ${coverage.loaded}/${picks.length} 只研究档案` : '完成选股后读取角色报告'}</small></div></article>
        </section>

        <section className="panel picks-panel" aria-labelledby="picks-heading">
          <div className="panel-heading picks-heading"><div><span className="eyebrow">冻结信号 · 等权 Top 10</span><h2 id="picks-heading">本期研究名单</h2></div><div className="picks-heading-right">{picksEnvelope?.run_id === selectedRunId && <StatusPill status={picksEnvelope.status}>{picksEnvelope.label ?? labelStatus(picksEnvelope.status)}</StatusPill>}<span className="count-chip">{picksEnvelope?.run_id === selectedRunId ? `${picks.length} / 10` : '— / 10'}</span></div></div>
          {picksEnvelope?.run_id === selectedRunId && picks.length > 0 ? <>
            <div className="table-scroll"><table className="picks-table"><thead><tr><th>排名</th><th>标的</th><th>行业</th><th>因子分</th><th>12 个月目标价</th><th>入场参考</th><th>详情</th></tr></thead>
              <tbody>{picks.map((pick) => <PickRow key={pick.ticker} pick={pick} onOpen={openResearch} />)}</tbody></table></div>
            <div className="table-foot"><span>信号 ID <code>{picksEnvelope.signal?.signal_id ?? '—'}</code></span><span>配置指纹 <code title={picksEnvelope.signal?.config_hash}>{shortHash(picksEnvelope.signal?.config_hash)}</code></span><span>权重规则 等权 10%</span></div>
          </> : noResearchResult ? <EmptyState title={outerRunStatus === 'INSUFFICIENT_ELIGIBLE_STOCKS' ? '合格标的不足，未生成 Top 10' : '本次任务没有可用名单'} icon="⌕">{activeRun?.result?.reason ?? activeRun?.error ?? '检查数据状态与排除原因后，可调整配置重新提交。'}</EmptyState>
            : activeRun && ACTIVE_JOB.has(activeRun.status) ? <div className="table-loading"><span className="spinner" />研究任务正在推进，结果冻结后会显示在这里。</div>
              : <EmptyState title="暂无冻结名单" icon="⌕">完成研究并成功生成冻结信号后，可以打开任一标的查看角色依据、证据来源与估值拆解。</EmptyState>}
          {picksEnvelope?.run_id === selectedRunId && ((picksEnvelope.warnings?.length ?? 0) > 0 || (picksEnvelope.exclusions?.length ?? 0) > 0) && <div className="result-notes"><div>{picksEnvelope.warnings?.map((warning) => <span className="warning-chip" key={warning}>{warning}</span>)}</div>{picksEnvelope.exclusions && picksEnvelope.exclusions.length > 0 && <details><summary>排除 {picksEnvelope.exclusions.length} 个输入</summary><ul>{picksEnvelope.exclusions.map((item, index) => <li key={`${item.ticker}-${index}`}><b>{item.ticker ?? '—'}</b> · {item.reason ?? '未知原因'}</li>)}</ul></details>}</div>}
        </section>

        <section className="panel comparison-panel" aria-labelledby="comparison-heading">
          <div className="panel-heading comparison-heading"><div><span className="eyebrow">回测实验 · {activeRun?.payload?.period ?? '等待研究周期'} · 同一时间窗口</span><h2 id="comparison-heading">组合回报比较</h2></div>
            <div className="comparison-actions">
              {benchmark && <span className="benchmark-inline"><span>当前登记榜单</span><StatusPill status={benchmark.status}>{benchmark.status === 'AVAILABLE' ? '已核验' : benchmark.status === 'UNVERIFIED' ? '未核验' : '不可用'}</StatusPill></span>}
              {backtestRecord && <StatusPill status={backtestDisplayStatus}>{labelStatus(backtestDisplayStatus)}</StatusPill>}
              {isFrozen && <div className="backtest-controls"><label><span className="sr-only">回测策略</span><select aria-label="回测策略" value={policy} onChange={(event) => setPolicy(event.target.value as 'PRIMARY' | 'LIMIT_ENTRY')}><option value="PRIMARY">主实验 · 下期开盘买入</option><option value="LIMIT_ENTRY">次实验 · 限价入场</option></select></label><button className="secondary-button" type="button" onClick={submitBacktest} disabled={submittingBacktest || ACTIVE_JOB.has(backtestRecord?.status ?? '')}>{submittingBacktest ? '正在提交…' : backtestId ? '刷新回测' : '运行回测'}<span aria-hidden="true">→</span></button></div>}
            </div>
          </div>
          {benchmark?.list && <div className="benchmark-source latest"><strong>当前登记记录</strong><span>此榜单供之后新建的回测参考，不代表已载入回测使用的输入。</span>{safeExternalUri(benchmark.list.source_uri) ? <a href={benchmark.list.source_uri} target="_blank" rel="noreferrer">{benchmark.list.source_uri}</a> : <code>{benchmark.list.source_uri}</code>}<small>{benchmark.list.period} · 发布 {dateTime(benchmark.list.published_at)} · {benchmark.list.verification_status}</small></div>}
          {backtestRecord && <BacktestBenchmarkProvenance job={backtestRecord} />}
          {backtestRecord && ACTIVE_JOB.has(backtestRecord.status) ? <div className="backtest-running"><span className="spinner" /><div><strong>正在计算冻结信号的六个月回报</strong><span>回测任务 {backtestRecord.backtest_id} · {backtestRecord.progress ?? 0}%</span></div><StatusPill status={backtestRecord.status} /></div>
            : result?.status === 'COMPLETED' ? <>
              {result.mode === 'DEMO' && <div className="backtest-demo"><b>DEMO / SYNTHETIC</b><span>以下路径与回报都是合成演示，不是投资业绩或真实历史回测。</span></div>}
              <div className="comparison-meta"><span><b>实际区间</b>{result.entry_session ?? '—'} → {result.exit_session ?? '—'}</span><span><b>执行规则</b>{result.policy === 'PRIMARY' ? '下一个合格开盘 · 持有六个月' : '限价入场 · 未成交保留现金'}</span><span><b>现金权重</b>{percent(result.cash_weight ?? 0)}</span></div>
              <div className="chart-section"><div className="subsection-heading"><h3>组合总回报</h3><span>数值采用实际组合回报；相对差额单独以百分点呈现</span></div><ReturnChart result={result} /></div>
              <div className="comparison-summary">
                <div><span>FinAgent 相对 SPY</span><strong className={result.excess_vs_spy_pp != null && result.excess_vs_spy_pp > 0 ? 'positive' : ''}>{percentagePoints(result.excess_vs_spy_pp)}</strong></div>
                <div><span>FinAgent 相对 SA</span><strong>{result.excess_vs_sa_pp == null ? '—' : percentagePoints(result.excess_vs_sa_pp)}</strong></div>
                <div className="sa-status-cell"><span>本次 Seeking Alpha 对照</span><StatusPill status={result.seeking_alpha_status}>{result.seeking_alpha_status === 'AVAILABLE' ? '已核验，可比较' : result.seeking_alpha_status === 'UNVERIFIED' ? '存在但未核验' : '不可用'}</StatusPill></div>
              </div>
              <div className="return-table-wrap"><table className="return-table"><thead><tr><th>组合</th><th>总回报</th><th>起始会话</th><th>结束会话</th><th>覆盖</th></tr></thead><tbody>
                <PortfolioRow name="FinAgent" portfolio={result.finagent} />
                <PortfolioRow name="Seeking Alpha" portfolio={result.seeking_alpha} fallback={result.seeking_alpha_status === 'UNVERIFIED' ? '来源存在，但榜单未核验' : '原始榜单未提供'} />
                <PortfolioRow name="SPY" portfolio={result.spy} />
              </tbody></table></div>
              {result.warnings && result.warnings.length > 0 && <div className="warning-list compact">{result.warnings.map((warning) => <span key={warning}>{warning}</span>)}</div>}
            </> : backtestRecord && result ? <div className={`backtest-state ${statusTone(result.status)}`}><StatusPill status={result.status} /><div><strong>{result.status === 'PENDING' ? '该窗口尚未成熟或暂缺合格交易日' : result.status === 'UNAVAILABLE' ? '当前数据源无法提供回测' : '回测数据未通过校验'}</strong><span>{result.reason ?? '接口没有返回具体原因。'}</span></div>{result.mode === 'DEMO' && <b className="synthetic-inline">SYNTHETIC</b>}</div>
              : backtestRecord && backtestRecord.status === 'FAILED' ? <div className="error-panel"><strong>回测任务执行失败</strong><span>{backtestRecord.error ?? '请检查任务状态并稍后重试。'}</span></div>
                : !isFrozen ? <EmptyState title="等待冻结信号" icon="↗">成功生成 Top 10 后，启动主实验或限价入场实验。若 SA 榜单未导入，界面会显示不可用且不生成对比结果。</EmptyState>
                  : <EmptyState title="尚无回测结果" icon="↗">选择一种执行规则并运行回测。结果只在 worker 计算完成后展示。</EmptyState>}
        </section>

        <section className="trace-section">
          <button type="button" className="trace-toggle" aria-expanded={auditOpen} onClick={() => setAuditOpen((open) => !open)} disabled={!selectedRunId}><span className="trace-icon">⌘</span><span><b>运行审计轨迹</b><small>查看计划、数据工具、证据验证与结果冻结事件</small></span><span className="trace-count">{auditOpen ? '收起' : '展开'} <b aria-hidden="true">{auditOpen ? '−' : '+'}</b></span></button>
          {auditOpen && <div className="audit-list">{auditError && <div className="error-panel">{auditError}</div>}{auditEvents.length > 0 ? auditEvents.map((item) => <article className="audit-event" key={item.id}><span className="audit-dot" /><div><b>{item.phase}</b><time>{dateTime(item.timestamp)}</time><code>{JSON.stringify(item.metadata)}</code></div></article>) : !auditError && <div className="audit-empty">此任务尚无审计事件。</div>}</div>}
        </section>

        <footer className="page-footer"><span>FinAgent · 半年度研究原型</span><span>研究输出用于工程验证，不构成投资建议。</span><a href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">API 文档 ↗</a></footer>
      </main>

      {selectedTicker && selectedRunId && <ResearchDialog key={`${selectedRunId}-${selectedTicker}`} ticker={selectedTicker} runId={selectedRunId} onClose={closeResearch} />}
    </div>
  );
}

function PickRow({ pick, onOpen }: { pick: Pick; onOpen: (ticker: string, event: MouseEvent<HTMLButtonElement>) => void }) {
  return <tr>
    <td><span className="rank-number">{String(pick.rank).padStart(2, '0')}</span></td>
    <td><div className="ticker-cell"><strong>{pick.ticker}</strong><small>等权 {percent(pick.weight)}</small></div></td>
    <td className="sector-cell">{pick.sector}</td>
    <td><span className="score-value">{pick.score.toFixed(3)}</span><span className="score-track"><i style={{ width: `${Math.max(0, Math.min(100, pick.score * 100))}%` }} /></span></td>
    <td className="price-cell">{money(pick.target_12m)}</td>
    <td className="price-cell entry-price">{money(pick.entry_price)}</td>
    <td><button type="button" className="detail-link" onClick={(event) => onOpen(pick.ticker, event)}>研究详情 <span aria-hidden="true">↗</span></button></td>
  </tr>;
}

function PortfolioRow({ name, portfolio, fallback }: { name: string; portfolio?: BacktestResult['finagent']; fallback?: string }) {
  return <tr><td><b>{name}</b></td><td className="portfolio-return">{portfolio ? percent(portfolio.total_return) : '—'}</td><td>{portfolio?.entry_session ?? '—'}</td><td>{portfolio?.exit_session ?? '—'}</td><td>{portfolio ? `${portfolio.holdings.length} 项` : fallback ?? '不可用'}</td></tr>;
}

export default App;
