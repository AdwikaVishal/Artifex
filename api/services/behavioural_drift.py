"""
api/services/behavioural_drift.py – Pydantic models for the
Predictive Crisis Engine's behavioural drift signal schema.

These models validate the JSON payloads produced by the signal-ingestion
pipeline (NATS consumer) and consumed by the crisis predictor.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Nested signal-entry models ────────────────────────────────────────────────


class VisitNoteEntry(BaseModel):
    visit_date: date
    worker_id: str
    visit_type: str = Field(default="scheduled", pattern=r"^(scheduled|emergency|follow_up)$")
    note_length_chars: int | None = None
    sentiment_score: float = Field(..., ge=-1.0, le=1.0)
    sentiment_label: str = Field(..., pattern=r"^(negative|neutral|positive)$")
    keyword_flags: list[str] = Field(default_factory=list)
    note_snippet: str | None = Field(default=None, max_length=500)


class IncidentEntry(BaseModel):
    incident_date: date
    severity: int = Field(..., ge=1, le=5)
    category: str
    resolved_within_24h: bool | None = None
    involved_caseworker: str | None = None


class MedicationEntry(BaseModel):
    name: str
    total_doses: int = Field(..., ge=0)
    missed_doses: int = Field(..., ge=0)
    compliance_rate: float = Field(..., ge=0.0, le=1.0)


# ── Signal-domain models ──────────────────────────────────────────────────────


class SchoolAttendanceSignal(BaseModel):
    school_days_total: int = Field(..., ge=0)
    days_attended: int = Field(..., ge=0)
    days_absent_excused: int | None = Field(default=0, ge=0)
    days_absent_unexcused: int | None = Field(default=0, ge=0)
    late_arrivals: int | None = Field(default=0, ge=0)
    early_departures: int | None = Field(default=0, ge=0)
    attendance_rate: float = Field(..., ge=0.0, le=1.0)
    attendance_trend: float = 0.0
    baseline_attendance_rate: float = Field(..., ge=0.0, le=1.0)
    delta_from_baseline: float = 0.0
    school_engagement_flags: list[str] = Field(default_factory=list)


class CaseworkerVisitsSignal(BaseModel):
    visit_count: int = Field(..., ge=0)
    entries: list[VisitNoteEntry] = Field(default_factory=list)
    avg_sentiment: float = 0.0
    sentiment_trend: float = 0.0
    min_sentiment: float | None = Field(default=None, ge=-1.0, le=1.0)
    flag_count_total: int = Field(default=0, ge=0)
    dominant_flags: list[str] = Field(default_factory=list, max_length=3)
    baseline_avg_sentiment: float | None = None
    delta_sentiment_from_baseline: float | None = None


class IncidentReportsSignal(BaseModel):
    incidents_7d: int = Field(..., ge=0)
    incidents_14d: int = Field(..., ge=0)
    incidents_28d: int = Field(..., ge=0)
    incidents: list[IncidentEntry] = Field(default_factory=list)
    cumulative_severity_28d: int = Field(..., ge=0)
    avg_severity: float = Field(..., ge=1.0, le=5.0)
    severity_trend: float = 0.0
    baseline_incident_rate: float | None = None
    delta_incident_rate_from_baseline: float | None = None
    resolved_fraction: float = Field(default=0.0, ge=0.0, le=1.0)


class MedicationComplianceSignal(BaseModel):
    applies: bool
    total_doses: int | None = Field(default=None, ge=0)
    doses_administered: int | None = Field(default=None, ge=0)
    doses_missed: int | None = Field(default=None, ge=0)
    compliance_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    compliance_trend: float | None = None
    baseline_compliance_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    delta_compliance_from_baseline: float | None = None
    medications: list[MedicationEntry] = Field(default_factory=list)
    refusal_incidents: int | None = Field(default=0, ge=0)


class CommunicationPatternsSignal(BaseModel):
    outreach_attempts: int = Field(..., ge=0)
    responded_count: int = Field(..., ge=0)
    response_rate: float = Field(..., ge=0.0, le=1.0)
    missed_contacts: int | None = Field(default=0, ge=0)
    avg_response_lag_hours: float = Field(..., ge=0.0)
    response_lag_trend: float = 0.0
    baseline_avg_lag_hours: float | None = None
    delta_lag_from_baseline: float | None = None
    avg_tone_score: float = Field(..., ge=-1.0, le=1.0)
    tone_trend: float = 0.0
    communication_channels: list[str] = Field(default_factory=list)
    primary_channel: str | None = None
    after_hours_contacts: int | None = Field(default=0, ge=0)


class CompositeDriftScore(BaseModel):
    overall_drift_index: float = Field(..., ge=0.0, le=100.0)
    drifting_signals: list[str] = Field(default_factory=list)
    signal_trend_direction: str = Field(
        default="stable",
        pattern=r"^(improving|stable|declining|rapidly_declining)$",
    )
    prediction_window_horizon: str = Field(
        default="21_days",
        pattern=r"^(14_days|21_days|28_days)$",
    )


class DriftSignalsContainer(BaseModel):
    school_attendance: SchoolAttendanceSignal
    caseworker_visits: CaseworkerVisitsSignal
    incident_reports: IncidentReportsSignal
    medication_compliance: MedicationComplianceSignal
    communication_patterns: CommunicationPatternsSignal


# ── Root model ────────────────────────────────────────────────────────────────


class BehaviouralDriftSnapshot(BaseModel):
    """Root model for a single drift-signal snapshot ingested by the Predictive Crisis Engine."""

    child_id: str
    placement_id: str
    snapshot_date: datetime
    window_start: date
    window_end: date
    weeks_in_placement: int | None = None
    drift_signals: DriftSignalsContainer
    composite_drift_score: CompositeDriftScore


# ── Migration helper ──────────────────────────────────────────────────────────


SIGNAL_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS behavioural_drift_signals (
    id              SERIAL PRIMARY KEY,
    child_id        TEXT        NOT NULL REFERENCES children(child_id),
    placement_id    TEXT        NOT NULL REFERENCES placements(workflow_id),
    snapshot_date   TIMESTAMP   NOT NULL DEFAULT NOW(),
    window_start    DATE        NOT NULL,
    window_end      DATE        NOT NULL,
    signals_json    JSONB       NOT NULL,
    drift_score     DOUBLE PRECISION,
    trend_direction TEXT,
    ingested_at     TIMESTAMP   NOT NULL DEFAULT NOW(),

    -- Speed up the crisis predictor's feature-query step
    CONSTRAINT uq_child_window UNIQUE (child_id, window_start, window_end)
);

CREATE INDEX idx_behavioural_drift_child
    ON behavioural_drift_signals (child_id, snapshot_date DESC);

CREATE INDEX idx_behavioural_drift_placement
    ON behavioural_drift_signals (placement_id, snapshot_date DESC);

CREATE INDEX idx_behavioural_drift_score
    ON behavioural_drift_signals (drift_score DESC);
"""
