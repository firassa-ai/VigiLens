from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SignalTrajectory = Literal[
    "accelerating",
    "emerging",
    "stable",
    "declining",
    "insufficient_data",
]

DiffLineType = Literal["added", "removed", "unchanged"]
FDAActionType = Literal["label_change", "safety_communication", "warning"]
ScopeType = Literal["drug", "class", "global"]
ScorecardResult = Literal["validated", "pending", "missed", "early"]
ForesightWriteStatus = Literal["ok", "warning", "idle"]
PredictionBasisType = Literal[
    "signal_threshold",
    "cross_signal_guardrail",
    "sentinel_report_guardrail",
    "threshold_crossing",
    "cross_signal_precursor",
    "label_gap_escalation",
    "serious_event_sentinel",
]
SignalTermLevel = Literal["pt", "family"]
SignalConsensusTier = Literal["none", "watchlist", "public_signal", "priority_review"]
SignalLabelStatus = Literal["known_label", "label_gap", "unknown"]
PredictionTrack = Literal["receipt", "proof"]
PredictionNoveltyStatus = Literal["known_label", "label_gap", "indication_confounded", "generic_noise"]
PredictionVisibility = Literal["watchlist", "public"]
PredictionEvidenceGrade = Literal["exploratory", "moderate", "strong"]


class Drug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    generic_name: str
    brand_names: list[str]
    total_reports: int
    quarters_loaded: list[str]
    next_quarter: str | None
    current_profile_summary: str


class DeleteDrugResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drug_id: str
    deleted: bool


class SignalPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quarter: str
    adverse_event: str
    report_count: int
    cumulative_count: int
    drug_total_cumulative: int
    ror: float | None
    ror_ci_lower: float | None
    ror_ci_upper: float | None
    prr: float | None
    chi_squared: float | None
    bcpnn_ic: float | None = None
    bcpnn_ic025: float | None = None
    ebgm: float | None = None
    eb05: float | None = None
    signal_detected: bool
    trajectory: SignalTrajectory
    term_level: SignalTermLevel = "pt"
    family_key: str | None = None
    family_label: str | None = None
    method_votes: dict[str, bool] = Field(default_factory=dict)
    consensus_tier: SignalConsensusTier = "none"
    label_status: SignalLabelStatus = "unknown"
    priority_flag: bool = False
    supporting_terms: list[str] = Field(default_factory=list)


class FAERSReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    safetyreportid: str
    version: int
    receivedate: str
    patient_sex: Literal["male", "female", "unknown"]
    patient_age: float | None
    reactions: list[str]
    suspect_drugs: list[str]
    concomitant_drugs: list[str]
    serious: bool
    outcomes: list[str]
    evidence_api_path: str
    eventlog_memory_id: str | None = None


class ScopeRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ScopeType
    key: str
    label: str


class PredictionVerificationCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    url: str
    source_type: Literal["fda", "dailymed", "literature", "safety_bulletin"]
    source_date: str | None = None


class PredictionVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["supported", "mixed", "unverified", "not_run"]
    summary: str
    checked_at: str | None = None
    queries: list[str]
    citations: list[PredictionVerificationCitation]
    source_types: list[Literal["fda", "dailymed", "literature", "safety_bulletin"]]


class PredictionBasis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: PredictionBasisType
    summary: str


class PredictionSupportingEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adverse_event: str
    quarter: str
    trajectory: SignalTrajectory | None = None
    cumulative_count: int | None = None
    evidence_report_ids: list[str]
    evidence_api_paths: list[str]


class EpisodicSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quarter: str
    narrative: str
    key_signals_mentioned: list[str]
    report_count_ingested: int
    created_at: str
    memory_source: Literal["evermemos", "postgres_fallback"] | None = None
    memory_id: str | None = None


class DrugProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drug_id: str
    current_assessment: str
    risk_level: Literal["low", "moderate", "elevated", "high"]
    known_signals: list[str]
    investigating_signals: list[str]
    last_updated: str


class Belief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    drug_id: str
    question_hash: str
    question_text: str
    answer_text: str
    confidence_score: int
    evidence_report_ids: list[str]
    episodic_ids_used: list[str]
    created_at: str
    quarter_context: str


class DiffLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: DiffLineType
    text: str


class BeliefDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    before: Belief
    after: Belief
    text_diff: list[DiffLine]
    confidence_delta: int
    new_evidence_ids: list[str]
    reinterpreted_report_ids: list[str]
    triggered_by_quarter: str


class QueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_text: str
    confidence: int
    signal_summary: list[SignalPoint]
    evidence: list[FAERSReport]
    episodic_context: list[EpisodicSummary]
    belief_id: str
    foresight_memory_ids: list[str] = []


class FDAAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    date: str
    type: FDAActionType
    title: str
    description: str
    source_url: str
    scope: ScopeRef


class Prediction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    drug_id: str
    adverse_event: str
    predicted_action: FDAActionType
    confidence: int
    predicted_date_range: tuple[str, str]
    created_at_quarter: str
    visibility: PredictionVisibility = "public"
    track: PredictionTrack = "receipt"
    novelty_status: PredictionNoveltyStatus = "label_gap"
    evidence_grade: PredictionEvidenceGrade = "moderate"
    trigger_basis: str = "signal_threshold"
    label_gap: bool = False
    basis: PredictionBasis
    scope: ScopeRef
    supporting_event: PredictionSupportingEvent
    verification: PredictionVerification | None = None


class CasefileSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drug_id: str
    viewed_quarter: str
    stage: Literal["baseline", "emergence", "escalation", "receipt_validation"]
    headline: str
    summary: str
    lead_signal: SignalPoint | None = None
    lead_family: str | None = None
    key_label_gaps: list[str]
    watchlist_alerts: list[SignalPoint]
    public_forecasts: list[Prediction]
    validated_receipts: int
    pending_receipts: int
    proof_backed_signals: int = 0
    receipt_summary: str


class ScorecardEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction: Prediction
    actual_fda_action: FDAAction | None
    result: ScorecardResult


class ForesightMemoryStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ForesightWriteStatus
    message: str
    total_predictions: int
    attempted_writes: int
    successful_writes: int
    failed_writes: int
    last_attempted_quarter: str | None = None


class SituationAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    drug_id: str
    quarter: str
    narrative: str
    risk_level: Literal["low", "moderate", "elevated", "high"]
    key_changes: list[str]
    memory_sources: list[str]
    created_at: str


class MemoryProxyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: str
    drug_id: str
    cached: bool
    refreshed: bool
    memory_type: str | None = None
    group_id: str | None = None
    quarter: str | None = None
    source_endpoint: str | None = None
    payload: dict[str, Any]
