export type Mode = 'DEMO' | 'REAL';
export type ResearchMode = 'quant_only' | 'single_agent_skills' | 'multi_persona' | 'multi_persona_debate';

export interface RunPayload {
  period: string;
  mode: Mode;
  research_mode: ResearchMode;
}

export interface Pick {
  rank: number;
  ticker: string;
  sector: string;
  weight: number;
  score: number;
  target_12m: number;
  entry_price: number;
  snapshot_id: string;
  snapshot_hash: string;
  rationale: string;
}

export interface FrozenSignal {
  signal_id: string;
  period: string;
  mode: Mode;
  pit_status: string;
  frozen_at: string;
  decision_at: string;
  config_hash: string;
  picks: Pick[];
  warnings?: string[];
}

export interface RunResult {
  signal?: FrozenSignal | null;
  picks?: Pick[];
  warnings?: string[];
  exclusions?: Array<{ ticker?: string; reason?: string }>;
  reason?: string;
  eligible_count?: number;
}

export interface RunJob {
  id?: string;
  run_id: string;
  kind?: string;
  status: string;
  progress?: number;
  payload: RunPayload;
  result?: RunResult | null;
  error?: string | null;
  created_at?: number;
  updated_at?: number;
}

export interface Assumption {
  name: string;
  value: number;
  unit: string;
  rationale: string;
  evidence_ids?: string[];
}

export interface PersonaReport {
  persona: string;
  rationale: string;
  assumptions?: Assumption[];
  evidence_ids?: string[];
  risk_flags?: string[];
  target_price_candidate?: number | null;
  abstain_reason?: string | null;
  model_version?: string;
  prompt_version?: string;
}

export interface EvidenceItem {
  evidence_id: string;
  field: string;
  value: string | number;
  source_uri: string;
  available_at: string;
  content_hash: string;
  pit_status: string;
  kind?: string;
}

export interface ResearchResult {
  ticker: string;
  sector: string;
  mode: Mode;
  research_mode: ResearchMode;
  snapshot: {
    snapshot_id: string;
    decision_at: string;
    content_hash: string;
    pit_status: string;
    warnings?: string[];
    items: EvidenceItem[];
  };
  reports: PersonaReport[];
  valuation: {
    fair_value?: number | null;
    target_12m?: number | null;
    entry_price?: number | null;
    safety_margin: number;
    currency: string;
    corporate_action_basis: string;
    pit_status: string;
    methods?: Array<{
      method: string;
      value: number;
      assumptions?: Assumption[];
      evidence_ids?: string[];
    }>;
    explanations?: string[];
    abstain_reason?: string | null;
  };
  factors?: Array<{ name: string; value?: number | null; missing_reason?: string | null }>;
  eligible?: boolean;
  exclusion_reasons?: string[];
  versions?: { model?: string; graph?: string; prompt?: string; strategy?: string };
}

export interface PicksEnvelope {
  run_id: string;
  status: string;
  mode: Mode;
  label: string;
  picks: Pick[];
  signal?: FrozenSignal | null;
  warnings?: string[];
  exclusions?: Array<{ ticker?: string; reason?: string }>;
}

export interface BenchmarkList {
  period: string;
  tickers: string[];
  source_uri: string;
  published_at: string;
  content_hash: string;
  verification_status: string;
  verification_note: string;
  mode?: Mode;
}

export interface BenchmarkEnvelope {
  status: 'AVAILABLE' | 'UNAVAILABLE' | 'UNVERIFIED' | string;
  list?: BenchmarkList | null;
}

export interface PortfolioReturn {
  name: string;
  total_return: number;
  entry_session: string;
  exit_session: string;
  holdings: Array<{ ticker: string; weight: number; total_return: number; filled: boolean }>;
}

export interface BacktestResult {
  status: string;
  policy: 'PRIMARY' | 'LIMIT_ENTRY';
  mode: Mode;
  period: string;
  entry_session?: string | null;
  exit_session?: string | null;
  finagent?: PortfolioReturn | null;
  spy?: PortfolioReturn | null;
  seeking_alpha?: PortfolioReturn | null;
  seeking_alpha_status: 'AVAILABLE' | 'UNAVAILABLE' | 'UNVERIFIED' | string;
  excess_vs_spy_pp?: number | null;
  excess_vs_sa_pp?: number | null;
  warnings?: string[];
  reason?: string | null;
  cash_weight?: number;
  snapshot_hash?: string | null;
}

export interface BacktestJob {
  id?: string;
  backtest_id: string;
  status: string;
  progress?: number;
  payload?: {
    run_id?: string;
    as_of?: string | null;
    policy?: 'PRIMARY' | 'LIMIT_ENTRY';
    benchmark?: BenchmarkList | null;
    execution_context?: Record<string, unknown>;
  };
  result?: BacktestResult | null;
  error?: string | null;
}

export interface AuditEvent {
  id: string;
  run_id: string;
  phase: string;
  timestamp: number;
  metadata: Record<string, unknown>;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const response = await fetch(`${import.meta.env.VITE_API_BASE ?? ''}${path}`, {
    ...init,
    headers,
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const data = body as { detail?: unknown; message?: unknown } | null;
    const detail = typeof data?.detail === 'string'
      ? data.detail
      : typeof data?.message === 'string'
        ? data.message
        : `HTTP ${response.status}`;
    throw new ApiError(response.status, detail);
  }
  return body as T;
}
