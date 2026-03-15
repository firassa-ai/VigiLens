export type SignalTrajectory =
  | "accelerating"
  | "emerging"
  | "stable"
  | "declining"
  | "insufficient_data";

export type FDAActionType = "label_change" | "safety_communication" | "warning";
export type DiffLineType = "added" | "removed" | "unchanged";
export type ScorecardResult = "validated" | "pending" | "missed" | "early";
export type ForesightWriteStatus = "ok" | "warning" | "idle";
export type ScopeType = "drug" | "class" | "global";
export type PredictionBasisType =
  | "signal_threshold"
  | "cross_signal_guardrail"
  | "sentinel_report_guardrail"
  | "threshold_crossing"
  | "cross_signal_precursor"
  | "label_gap_escalation"
  | "serious_event_sentinel";
export type SignalTermLevel = "pt" | "family";
export type SignalConsensusTier = "none" | "watchlist" | "public_signal" | "priority_review";
export type SignalLabelStatus = "known_label" | "label_gap" | "unknown";
export type PredictionVisibility = "watchlist" | "public";
export type PredictionEvidenceGrade = "exploratory" | "moderate" | "strong";
export type PredictionVerificationStatus = "supported" | "mixed" | "unverified" | "not_run";
export type PredictionVerificationSourceType = "fda" | "dailymed" | "literature" | "safety_bulletin";

export interface ErrorResponse {
  error: string;
  detail: string;
  status_code: number;
}

export interface Drug {
  id: string;
  generic_name: string;
  brand_names: string[];
  total_reports: number;
  quarters_loaded: string[];
  next_quarter: string | null;
  current_profile_summary: string;
}

export interface DeleteDrugResponse {
  drug_id: string;
  deleted: boolean;
}

export type CatalogSource = "tracked" | "dailymed" | "faers";

export interface CatalogSearchResult {
  generic_name: string;
  brand_names: string[];
  tracked: boolean;
  tracked_drug_id: string | null;
  label_available: boolean;
  sources: CatalogSource[];
}

export interface CatalogPreviewResponse {
  generic_name: string;
  brand_names: string[];
  tracked: boolean;
  tracked_drug_id: string | null;
  dailymed_setid: string | null;
  dailymed_title: string | null;
  dailymed_published_date: string | null;
  faers_available: boolean;
  faers_report_count: number | null;
  faers_report_count_is_estimate: boolean;
}

export interface FAERSReport {
  safetyreportid: string;
  version: number;
  receivedate: string;
  patient_sex: "male" | "female" | "unknown";
  patient_age: number | null;
  reactions: string[];
  suspect_drugs: string[];
  concomitant_drugs: string[];
  serious: boolean;
  outcomes: string[];
  evidence_api_path: string;
  eventlog_memory_id?: string | null;
}

export interface ScopeRef {
  type: ScopeType;
  key: string;
  label: string;
}

export interface SignalPoint {
  quarter: string;
  adverse_event: string;
  report_count: number;
  cumulative_count: number;
  drug_total_cumulative: number;
  ror: number | null;
  ror_ci_lower: number | null;
  ror_ci_upper: number | null;
  prr: number | null;
  chi_squared: number | null;
  bcpnn_ic?: number | null;
  bcpnn_ic025?: number | null;
  ebgm?: number | null;
  eb05?: number | null;
  signal_detected: boolean;
  trajectory: SignalTrajectory;
  term_level?: SignalTermLevel;
  family_key?: string | null;
  family_label?: string | null;
  method_votes?: Record<string, boolean>;
  consensus_tier?: SignalConsensusTier;
  label_status?: SignalLabelStatus;
  priority_flag?: boolean;
  supporting_terms?: string[];
}

export interface FDAAction {
  id: string;
  date: string;
  type: FDAActionType;
  title: string;
  description: string;
  source_url: string;
  scope: ScopeRef;
}

export interface EpisodicSummary {
  quarter: string;
  narrative: string;
  key_signals_mentioned: string[];
  report_count_ingested: number;
  created_at: string;
  memory_source?: "evermemos" | "postgres_fallback";
  memory_id?: string | null;
}

export interface DrugProfile {
  drug_id: string;
  current_assessment: string;
  risk_level: "low" | "moderate" | "elevated" | "high";
  known_signals: string[];
  investigating_signals: string[];
  last_updated: string;
}

export interface Belief {
  id: string;
  drug_id: string;
  question_hash: string;
  question_text: string;
  answer_text: string;
  confidence_score: number;
  evidence_report_ids: string[];
  episodic_ids_used: string[];
  created_at: string;
  quarter_context: string;
}

export interface DiffLine {
  type: DiffLineType;
  text: string;
}

export interface BeliefDiff {
  before: Belief;
  after: Belief;
  text_diff: DiffLine[];
  confidence_delta: number;
  new_evidence_ids: string[];
  reinterpreted_report_ids: string[];
  triggered_by_quarter: string;
}

export interface Prediction {
  id: string;
  drug_id: string;
  adverse_event: string;
  predicted_action: FDAActionType;
  confidence: number;
  predicted_date_range: [string, string];
  created_at_quarter: string;
  visibility?: PredictionVisibility;
  track?: "receipt" | "proof";
  novelty_status?: "known_label" | "label_gap" | "indication_confounded" | "generic_noise";
  evidence_grade?: PredictionEvidenceGrade;
  trigger_basis?: string;
  label_gap?: boolean;
  basis: {
    type: PredictionBasisType;
    summary: string;
  };
  scope: ScopeRef;
  supporting_event: {
    adverse_event: string;
    quarter: string;
    trajectory?: SignalTrajectory | null;
    cumulative_count?: number | null;
    evidence_report_ids: string[];
    evidence_api_paths: string[];
  };
  verification?: {
    status: PredictionVerificationStatus;
    summary: string;
    checked_at?: string | null;
    queries: string[];
    citations: Array<{
      title: string;
      url: string;
      source_type: PredictionVerificationSourceType;
      source_date?: string | null;
    }>;
    source_types: PredictionVerificationSourceType[];
  } | null;
}

export interface ScorecardEntry {
  prediction: Prediction;
  actual_fda_action: FDAAction | null;
  result: ScorecardResult;
}

export interface ForesightMemoryStatus {
  status: ForesightWriteStatus;
  message: string;
  total_predictions: number;
  attempted_writes: number;
  successful_writes: number;
  failed_writes: number;
  last_attempted_quarter: string | null;
}

export interface CasefileSummary {
  drug_id: string;
  viewed_quarter: string;
  stage: "baseline" | "emergence" | "escalation" | "receipt_validation";
  headline: string;
  summary: string;
  lead_signal?: SignalPoint | null;
  lead_family?: string | null;
  key_label_gaps: string[];
  watchlist_alerts: SignalPoint[];
  public_forecasts: Prediction[];
  validated_receipts: number;
  pending_receipts: number;
  proof_backed_signals?: number;
  receipt_summary: string;
}

export interface QueryResponse {
  answer_text: string;
  confidence: number;
  signal_summary: SignalPoint[];
  evidence: FAERSReport[];
  episodic_context: EpisodicSummary[];
  belief_id: string;
  foresight_memory_ids: string[];
}

export interface IngestStatus {
  drug_id: string;
  quarters_loaded: string[];
  next_quarter: string | null;
  total_reports_loaded: number;
  total_quarters_available?: number;
  evermemos_status: "idle" | "ingesting" | "consolidating" | "ready";
}

export type AgentThoughtType =
  | "perceive"
  | "tool"
  | "memory_query"
  | "memory_recall"
  | "reasoning"
  | "reinterpretation"
  | "memory_write"
  | "foresight"
  | "action";

export interface AgentThought {
  type: AgentThoughtType;
  content: string;
  timestamp: string;
  memory_refs?: string[] | null;
  metadata?: Record<string, unknown> | null;
}

export interface IngestProgressMessage {
  phase:
    | "starting"
    | "loading_reports"
    | "computing_signals"
    | "posting_evermemos"
    | "generating_beliefs"
    | "done"
    | "error";
  quarter: string;
  reports_processed: number;
  total_reports: number;
  signals_updated: number;
  evermemos_consolidation_status: "idle" | "posting" | "ready" | "failed";
  detail?: string;
  thoughts?: AgentThought[] | null;
}

export interface IngestProgress {
  message: IngestProgressMessage;
}

export interface HealthResponse {
  ok: boolean;
  postgres_ok: boolean;
  evermemos_ok: boolean;
  evermemos_version?: string;
  timestamp: string;
}

export interface SituationAnalysis {
  id: string;
  drug_id: string;
  quarter: string;
  narrative: string;
  risk_level: "low" | "moderate" | "elevated" | "high";
  key_changes: string[];
  memory_sources: string[];
  created_at: string;
}

export interface MemoryProxyResponse {
  memory_id: string;
  drug_id: string;
  cached: boolean;
  refreshed: boolean;
  memory_type: string | null;
  group_id: string | null;
  quarter: string | null;
  source_endpoint: string | null;
  payload: Record<string, unknown>;
}

export interface OnboardDrugResponse {
  drug_id: string;
  generic_name: string;
  source: "existing" | "cache" | "openfda";
  created: boolean;
  reports_loaded: number;
  baseline_quarters_loaded: string[];
  next_quarter: string | null;
  message: string;
}

export type TrackingJobStatus = "queued" | "running" | "ready" | "failed";
export type TrackingJobMode = "onboard" | "full_history_rebuild";
export type TrackingJobStep =
  | "queued"
  | "resolving_identity"
  | "fetching_faers"
  | "deduping_transforming"
  | "seeding_database"
  | "computing_baseline_stats"
  | "writing_memory"
  | "ready"
  | "failed";

export interface TrackingJobDetails {
  status_message?: string;
  search_strategy?: string;
  search_value?: string;
  window_index?: number;
  window_total?: number;
  window_label?: string;
  window_start?: string;
  window_end?: string;
  pages_fetched?: number;
  provider_rows_seen?: number;
  matched_reports?: number;
  window_complete?: boolean;
  reports_loaded?: number;
  baseline_quarters_loaded?: string[];
  next_quarter?: string | null;
  message?: string;
}

export interface TrackingJob {
  id: string;
  status: TrackingJobStatus;
  step: TrackingJobStep;
  progress: number;
  medication_name: string;
  resolved_generic_name: string | null;
  drug_id: string | null;
  source: string | null;
  error: string | null;
  options_json: {
    mode?: TrackingJobMode;
    drug_id?: string;
    baseline_quarters?: number;
    max_reports?: number | null;
    prefer_cached?: boolean;
  };
  details_json?: TrackingJobDetails;
  created_at: string;
  updated_at: string;
}
