from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Drug(Base):
    __tablename__ = "drugs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    generic_name: Mapped[str] = mapped_column(Text, nullable=False)
    brand_names: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    approved_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))


class FaersReport(Base):
    __tablename__ = "faers_reports"

    safetyreportid: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    receivedate: Mapped[date] = mapped_column(Date, nullable=False)
    patient_sex: Mapped[str] = mapped_column(Text, nullable=False)
    patient_age: Mapped[Decimal | None] = mapped_column()
    serious: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    outcomes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_duplicate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    __table_args__ = (
        CheckConstraint("patient_sex IN ('male','female','unknown')", name="ck_faers_reports_sex"),
    )


class FaersReportReaction(Base):
    __tablename__ = "faers_report_reactions"

    safetyreportid: Mapped[str] = mapped_column(
        Text,
        ForeignKey("faers_reports.safetyreportid", ondelete="CASCADE"),
        nullable=False,
    )
    meddra_pt: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("safetyreportid", "meddra_pt"),
    )


class FaersReportDrug(Base):
    __tablename__ = "faers_report_drugs"

    safetyreportid: Mapped[str] = mapped_column(
        Text,
        ForeignKey("faers_reports.safetyreportid", ondelete="CASCADE"),
        nullable=False,
    )
    drug_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("drugs.id", ondelete="SET NULL"),
    )
    drug_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("safetyreportid", "drug_name", "role"),
        CheckConstraint(
            "role IN ('suspect','concomitant','interacting','unknown')",
            name="ck_faers_report_drugs_role",
        ),
    )


class QuarterlyStat(Base):
    __tablename__ = "quarterly_stats"

    drug_id: Mapped[str] = mapped_column(
        Text, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False
    )
    quarter: Mapped[str] = mapped_column(Text, nullable=False)
    adverse_event: Mapped[str] = mapped_column(Text, nullable=False)

    report_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cumulative_count: Mapped[int] = mapped_column(Integer, nullable=False)
    drug_total_cumulative: Mapped[int] = mapped_column(Integer, nullable=False)
    all_total_cumulative: Mapped[int] = mapped_column(Integer, nullable=False)
    all_event_cumulative: Mapped[int] = mapped_column(Integer, nullable=False)

    ror: Mapped[float | None] = mapped_column(Double)
    ror_ci_lower: Mapped[float | None] = mapped_column(Double)
    ror_ci_upper: Mapped[float | None] = mapped_column(Double)
    prr: Mapped[float | None] = mapped_column(Double)
    chi_squared: Mapped[float | None] = mapped_column(Double)
    bcpnn_ic: Mapped[float | None] = mapped_column(Double)
    bcpnn_ic025: Mapped[float | None] = mapped_column(Double)
    ebgm: Mapped[float | None] = mapped_column(Double)
    eb05: Mapped[float | None] = mapped_column(Double)

    signal_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    term_level: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pt'"))
    family_key: Mapped[str | None] = mapped_column(Text)
    family_label: Mapped[str | None] = mapped_column(Text)
    method_votes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    consensus_tier: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'none'"))
    label_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unknown'"))
    priority_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    supporting_terms: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    trajectory: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("drug_id", "quarter", "adverse_event"),
        CheckConstraint(
            "trajectory IN ('accelerating','emerging','stable','declining','insufficient_data')",
            name="ck_quarterly_stats_trajectory",
        ),
    )


class FaersBackgroundCount(Base):
    __tablename__ = "faers_background_counts"

    quarter: Mapped[str] = mapped_column(Text, nullable=False)
    adverse_event: Mapped[str] = mapped_column(Text, nullable=False)
    all_total_cumulative: Mapped[int] = mapped_column(Integer, nullable=False)
    all_event_cumulative: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'openfda'"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (
        PrimaryKeyConstraint("quarter", "adverse_event"),
    )


class Belief(Base):
    __tablename__ = "beliefs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    drug_id: Mapped[str] = mapped_column(
        Text, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False
    )
    question_hash: Mapped[str] = mapped_column(Text, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_report_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    episodic_ids_used: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    quarter_context: Mapped[str] = mapped_column(Text, nullable=False)
    reinterpreted_report_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    reinterpretation_reason: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 100",
            name="ck_beliefs_confidence",
        ),
        UniqueConstraint("drug_id", "question_hash", "quarter_context", name="uq_beliefs_drug_question_quarter"),
    )


class FdaAction(Base):
    __tablename__ = "fda_actions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    drug_id: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "type IN ('label_change','safety_communication','warning')",
            name="ck_fda_actions_type",
        ),
    )


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    drug_id: Mapped[str] = mapped_column(
        Text, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False
    )
    adverse_event: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_action: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    predicted_date_start: Mapped[date] = mapped_column(Date, nullable=False)
    predicted_date_end: Mapped[date] = mapped_column(Date, nullable=False)
    created_at_quarter: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'public'"))
    track: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'receipt'"))
    novelty_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'label_gap'"))
    evidence_grade: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'moderate'"))
    trigger_basis: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'signal_threshold'"))
    label_gap: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_predictions_confidence"),
        CheckConstraint(
            "predicted_action IN ('label_change','safety_communication','warning')",
            name="ck_predictions_predicted_action",
        ),
        CheckConstraint("track IN ('receipt','proof')", name="ck_predictions_track"),
        CheckConstraint(
            "novelty_status IN ('known_label','label_gap','indication_confounded','generic_noise')",
            name="ck_predictions_novelty_status",
        ),
    )


class IngestionState(Base):
    __tablename__ = "ingestion_state"

    drug_id: Mapped[str] = mapped_column(
        Text, ForeignKey("drugs.id", ondelete="CASCADE"), primary_key=True
    )
    quarters_loaded: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    next_quarter: Mapped[str | None] = mapped_column(Text)
    evermemos_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'idle'"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (
        CheckConstraint(
            "evermemos_status IN ('idle','ingesting','consolidating','ready')",
            name="ck_ingestion_state_evermemos_status",
        ),
    )


class TrackingJob(Base):
    __tablename__ = "tracking_jobs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    step: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    medication_name: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_generic_name: Mapped[str | None] = mapped_column(Text)
    drug_id: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    options_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    details_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','ready','failed')",
            name="ck_tracking_jobs_status",
        ),
        CheckConstraint(
            "step IN ('queued','resolving_identity','fetching_faers','deduping_transforming','seeding_database','computing_baseline_stats','writing_memory','ready','failed')",
            name="ck_tracking_jobs_step",
        ),
        CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_tracking_jobs_progress",
        ),
    )


class SituationAnalysis(Base):
    __tablename__ = "situation_analyses"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    drug_id: Mapped[str] = mapped_column(
        Text, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False
    )
    quarter: Mapped[str] = mapped_column(Text, nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(Text, nullable=False)
    key_changes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    memory_sources: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    belief_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (
        UniqueConstraint("drug_id", "quarter", name="uq_situation_analyses_drug_quarter"),
        CheckConstraint(
            "risk_level IN ('low','moderate','elevated','high')",
            name="ck_situation_analyses_risk_level",
        ),
    )


class EvermemosRequest(Base):
    __tablename__ = "evermemos_requests"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    drug_id: Mapped[str] = mapped_column(
        Text, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False
    )
    quarter: Mapped[str | None] = mapped_column(Text)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    request_body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (
        CheckConstraint("status IN ('pending','ok','failed')", name="ck_evermemos_requests_status"),
    )


class EvermemosMemoryCache(Base):
    __tablename__ = "evermemos_memory_cache"

    memory_id: Mapped[str] = mapped_column(Text, primary_key=True)
    drug_id: Mapped[str] = mapped_column(
        Text, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[str | None] = mapped_column(Text)
    memory_type: Mapped[str | None] = mapped_column(Text)
    quarter: Mapped[str | None] = mapped_column(Text)
    source_endpoint: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
