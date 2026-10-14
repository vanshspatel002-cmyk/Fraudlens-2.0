"""
fraudlens.db
============

Thin sqlite3 storage layer. Plain sqlite3, not SQLAlchemy: it's stdlib
so there's zero dependency risk, the schema below is readable SQL you
can paste straight into a report, and there's no ORM magic to debug at
2am in week 4.

No check, agent, or UI code ever imports sqlite3 directly - it only
calls the functions in this file. That's what makes the migration note
below actually true.

--------------------------------------------------------------------
Migrating to PostgreSQL + pgvector later
--------------------------------------------------------------------
1. Swap `sqlite3.connect(...)` in `connect()` for a `psycopg` connect,
   and change every `?` placeholder in this file to `%s`.
2. Add `embedding vector(N)` to `images` (via the pgvector extension)
   instead of storing the embedding as a JSON blob, and add an
   ivfflat/hnsw index for nearest-neighbour search. That index is what
   turns src/ingest.py's find_similar() from a brute-force numpy scan
   into an actual index lookup - see the comment there.
3. Everything else - Finding/Case/Claimant/PerceptionRecord/ImageArtifact/
   Image/AuditEvent/AgentDecision, every check, the agent, the UI - is
   unchanged, because none of it imports sqlite3; it only calls the
   functions below.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Union

from .models import (
    AgentDecision,
    AdminAction,
    AdminActionRecord,
    AuditEvent,
    Case,
    CheckCategory,
    Claimant,
    Finding,
    Image,
    ImageArtifact,
    PerceptionRecord,
    Recommendation,
    RiskBand,
    Verdict,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS claimants (
    claimant_id   TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    phone         TEXT NOT NULL,
    bank_account  TEXT NOT NULL,
    address       TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claimants_phone ON claimants(phone);
CREATE INDEX IF NOT EXISTS idx_claimants_bank_account ON claimants(bank_account);

CREATE TABLE IF NOT EXISTS cases (
    case_id            TEXT PRIMARY KEY,
    claimant_id        TEXT NOT NULL,
    garage_id          TEXT NOT NULL,
    claim_type         TEXT NOT NULL,
    declared_time      TEXT,
    declared_location  TEXT,
    latitude           REAL,
    longitude          REAL,
    agent_type         TEXT NOT NULL DEFAULT 'claims',
    claim_amount       REAL,
    vehicle_registration TEXT,
    status             TEXT NOT NULL DEFAULT 'open',
    created_at         TEXT NOT NULL,
    vehicle_make       TEXT,
    vehicle_model      TEXT,
    vehicle_variant    TEXT,
    vehicle_year       INTEGER,
    engine_number      TEXT,
    chassis_number     TEXT,
    rto                TEXT,
    fuel_type          TEXT,
    idv                REAL,
    policy_number      TEXT,
    policy_type        TEXT,
    previous_policy_number TEXT,
    policy_ncb_percent REAL,
    policy_start_date  TEXT,
    policy_end_date    TEXT,
    person_name        TEXT,
    person_dob         TEXT,
    person_address     TEXT,
    person_contact     TEXT,
    driving_license_number TEXT,
    fir_number         TEXT,
    settlement_preference TEXT,
    bank_account_last4 TEXT
);
CREATE INDEX IF NOT EXISTS idx_cases_garage ON cases(garage_id);
CREATE INDEX IF NOT EXISTS idx_cases_vehicle_registration ON cases(vehicle_registration);

CREATE TABLE IF NOT EXISTS findings (
    finding_id   TEXT PRIMARY KEY,
    check_id     TEXT NOT NULL,
    case_id      TEXT NOT NULL REFERENCES cases(case_id),
    category     TEXT NOT NULL,
    verdict      TEXT NOT NULL,
    confidence   REAL NOT NULL,
    explanation  TEXT NOT NULL,
    evidence     TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_case ON findings(case_id);

CREATE TABLE IF NOT EXISTS perception_records (
    content_hash        TEXT PRIMARY KEY,
    source              TEXT NOT NULL,
    embedding           TEXT,
    caption             TEXT,
    ocr_text            TEXT,
    damage_description  TEXT,
    damage_severity     TEXT,
    weather_observed    TEXT,
    road_condition      TEXT,
    shadow_direction    TEXT,
    shadow_length       TEXT,
    lighting            TEXT,
    plate_text          TEXT,
    scene_context       TEXT,
    anomaly_notes       TEXT,
    raw_response        TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS image_artifacts (
    artifact_id   TEXT PRIMARY KEY,
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    content_hash  TEXT NOT NULL REFERENCES perception_records(content_hash),
    filename      TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'unspecified',
    uploaded_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_case ON image_artifacts(case_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_hash ON image_artifacts(content_hash);

-- policy_version and the three counters are ablation telemetry: the
-- rules-only baseline and the LLM agent both write here, and the
-- comparison is only meaningful if their rows can be told apart by
-- selection rather than by inference. See AgentDecision in models.py.
CREATE TABLE IF NOT EXISTS agent_decisions (
    decision_id             TEXT PRIMARY KEY,
    case_id                 TEXT NOT NULL REFERENCES cases(case_id),
    recommendation          TEXT NOT NULL,
    confidence              REAL NOT NULL,
    summary                 TEXT NOT NULL,
    supporting_finding_ids  TEXT NOT NULL,
    requested_artifacts     TEXT NOT NULL,
    policy_version          TEXT NOT NULL DEFAULT 'unversioned',
    risk_band               TEXT,
    score                   REAL,
    tool_calls_count        INTEGER NOT NULL DEFAULT 0,
    iterations_count        INTEGER NOT NULL DEFAULT 0,
    llm_calls_count         INTEGER NOT NULL DEFAULT 0,
    latency_ms              INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_case ON agent_decisions(case_id);
-- idx_decisions_policy is created in _migrate(), not here: on a database
-- that predates the policy_version column this script runs *before* the
-- ALTER TABLE that adds it, and indexing a column that does not exist yet
-- fails the whole schema script.

CREATE TABLE IF NOT EXISTS images (
    image_id      TEXT PRIMARY KEY,
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    path          TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    phash         TEXT NOT NULL,
    dhash         TEXT NOT NULL,
    embedding     TEXT,
    exif          TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_images_case ON images(case_id);
CREATE INDEX IF NOT EXISTS idx_images_content_hash ON images(content_hash);

CREATE TABLE IF NOT EXISTS audit_log (
    event_id    TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL,
    case_id     TEXT,
    details     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_log(case_id);

CREATE TABLE IF NOT EXISTS admin_actions (
    case_id    TEXT NOT NULL REFERENCES cases(case_id),
    admin_id   TEXT NOT NULL,
    action     TEXT NOT NULL,
    reason     TEXT,
    timestamp  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_actions_case ON admin_actions(case_id);

-- Generic key/value cache, namespaced per caller (e.g. "llm_chat",
-- "llm_vision"). Lives here rather than in a per-caller table because
-- every future cache in this project - LLM calls, CLIP embeddings,
-- OCR - wants the same shape: a namespace, a content-derived key, and
-- a JSON blob. One table, one pair of functions, reused everywhere.
CREATE TABLE IF NOT EXISTS cache_entries (
    namespace   TEXT NOT NULL,
    cache_key   TEXT NOT NULL,
    value       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (namespace, cache_key)
);
"""


# ---------------------------------------------------------------------------
# Connection / schema
# ---------------------------------------------------------------------------


def connect(db_path: Union[str, Path] = "fraudlens.db") -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columns added to agent_decisions after the first databases were
# created. CREATE TABLE IF NOT EXISTS will not add a column to a table
# that already exists, so an existing fraudlens.db would keep the old
# shape and every insert would fail on the new fields. Each entry is
# (column, full DDL fragment); all are additive with defaults, so
# applying them to a populated table is lossless.
_AGENT_DECISION_MIGRATIONS = (
    ("policy_version", "TEXT NOT NULL DEFAULT 'unversioned'"),
    ("risk_band", "TEXT"),
    ("score", "REAL"),
    ("tool_calls_count", "INTEGER NOT NULL DEFAULT 0"),
    ("iterations_count", "INTEGER NOT NULL DEFAULT 0"),
    ("llm_calls_count", "INTEGER NOT NULL DEFAULT 0"),
    ("latency_ms", "INTEGER NOT NULL DEFAULT 0"),
)

_CASE_MIGRATIONS = (
    ("vehicle_make", "TEXT"),
    ("vehicle_model", "TEXT"),
    ("vehicle_variant", "TEXT"),
    ("vehicle_year", "INTEGER"),
    ("engine_number", "TEXT"),
    ("chassis_number", "TEXT"),
    ("rto", "TEXT"),
    ("fuel_type", "TEXT"),
    ("idv", "REAL"),
    ("policy_number", "TEXT"),
    ("policy_type", "TEXT"),
    ("previous_policy_number", "TEXT"),
    ("policy_ncb_percent", "REAL"),
    ("policy_start_date", "TEXT"),
    ("policy_end_date", "TEXT"),
    ("person_name", "TEXT"),
    ("person_dob", "TEXT"),
    ("person_address", "TEXT"),
    ("person_contact", "TEXT"),
    ("driving_license_number", "TEXT"),
    ("fir_number", "TEXT"),
    ("settlement_preference", "TEXT"),
    ("bank_account_last4", "TEXT"),
    ('declaration_notes','TEXT'),
)


def _migrate(conn: sqlite3.Connection) -> None:
    """
    Bring an existing database up to the current schema. Additive only -
    no column is ever dropped or retyped here, because this runs
    automatically on every connect() and a destructive migration that
    runs by surprise is how data gets lost.
    """
    decision_columns = {row["name"] for row in conn.execute("PRAGMA table_info(agent_decisions)")}
    if decision_columns:
        for column, ddl in _AGENT_DECISION_MIGRATIONS:
            if column not in decision_columns:
                conn.execute(f"ALTER TABLE agent_decisions ADD COLUMN {column} {ddl}")
    case_columns = {row["name"] for row in conn.execute("PRAGMA table_info(cases)")}
    if case_columns:
        for column, ddl in _CASE_MIGRATIONS:
            if column not in case_columns:
                conn.execute(f"ALTER TABLE cases ADD COLUMN {column} {ddl}")
    if decision_columns:
        # Safe now that the column is guaranteed present, whichever path got
        # us here - fresh CREATE TABLE or ALTER on an existing database.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_policy ON agent_decisions(policy_version)")
    if case_columns:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_policy_number ON cases(policy_number)")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


@contextmanager
def session(db_path: Union[str, Path] = "fraudlens.db") -> Iterator[sqlite3.Connection]:
    """Open a connection, ensure the schema exists, commit on success, always close."""
    conn = connect(db_path)
    try:
        init_db(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------

def _date_to_text(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _date_from_text(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def insert_case(conn: sqlite3.Connection, case: Case) -> None:
    conn.execute(
        "INSERT INTO cases "
        "(case_id, claimant_id, garage_id, claim_type, declared_time, "
        " declared_location, latitude, longitude, agent_type, claim_amount, "
        " vehicle_registration, status, created_at, vehicle_make, vehicle_model, "
        " vehicle_variant, vehicle_year, engine_number, chassis_number, rto, "
        " fuel_type, idv, policy_number, policy_type, previous_policy_number, "
        " policy_ncb_percent, policy_start_date, policy_end_date, person_name, "
        " person_dob, person_address, person_contact, driving_license_number, "
        " fir_number, settlement_preference, bank_account_last4, declaration_notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            case.case_id,
            case.claimant_id,
            case.garage_id,
            case.claim_type,
            case.declared_time.isoformat() if case.declared_time else None,
            case.declared_location,
            case.latitude,
            case.longitude,
            case.agent_type,
            case.claim_amount,
            case.vehicle_registration,
            case.status,
            case.created_at.isoformat(),
            case.vehicle_make,
            case.vehicle_model,
            case.vehicle_variant,
            case.vehicle_year,
            case.engine_number,
            case.chassis_number,
            case.rto,
            case.fuel_type,
            case.idv,
            case.policy_number,
            case.policy_type,
            case.previous_policy_number,
            case.policy_ncb_percent,
            _date_to_text(case.policy_start_date),
            _date_to_text(case.policy_end_date),
            case.person_name,
            _date_to_text(case.person_dob),
            case.person_address,
            case.person_contact,
            case.driving_license_number,
            case.fir_number,
            case.settlement_preference,
            case.bank_account_last4,
            case.declaration_notes,
        ),
    )


def get_case(conn: sqlite3.Connection, case_id: str) -> Optional[Case]:
    row = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    return _case_from_row(row) if row is not None else None


def get_all_cases(conn: sqlite3.Connection) -> list[Case]:
    """
    Every case ever ingested, any agent_type. Brute-force client-side
    aggregation over this is exactly what src.ingest.find_similar already
    does over images at this corpus size (see that function's own
    docstring) - src.checks.threshold scans this the same way, to compute
    one garage's in-band claim percentage against the population baseline,
    for the same reason: not worth indexing until it actually is the
    bottleneck.
    """
    rows = conn.execute("SELECT * FROM cases ORDER BY created_at").fetchall()
    return [_case_from_row(r) for r in rows]


def _case_from_row(row: sqlite3.Row) -> Case:
    return Case(
        case_id=row["case_id"],
        claimant_id=row["claimant_id"],
        garage_id=row["garage_id"],
        claim_type=row["claim_type"],
        declared_time=datetime.fromisoformat(row["declared_time"]) if row["declared_time"] else None,
        declared_location=row["declared_location"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        agent_type=row["agent_type"],
        claim_amount=row["claim_amount"],
        vehicle_registration=row["vehicle_registration"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
        vehicle_make=row["vehicle_make"],
        vehicle_model=row["vehicle_model"],
        vehicle_variant=row["vehicle_variant"],
        vehicle_year=row["vehicle_year"],
        engine_number=row["engine_number"],
        chassis_number=row["chassis_number"],
        rto=row["rto"],
        fuel_type=row["fuel_type"],
        idv=row["idv"],
        policy_number=row["policy_number"],
        policy_type=row["policy_type"],
        previous_policy_number=row["previous_policy_number"],
        policy_ncb_percent=row["policy_ncb_percent"],
        policy_start_date=_date_from_text(row["policy_start_date"]),
        policy_end_date=_date_from_text(row["policy_end_date"]),
        person_name=row["person_name"],
        person_dob=_date_from_text(row["person_dob"]),
        person_address=row["person_address"],
        person_contact=row["person_contact"],
        driving_license_number=row["driving_license_number"],
        fir_number=row["fir_number"],
        settlement_preference=row["settlement_preference"],
        bank_account_last4=row["bank_account_last4"],
        declaration_notes=row['declaration_notes'] if 'declaration_notes' in row.keys() else None,
    )


# ---------------------------------------------------------------------------
# Claimant
# ---------------------------------------------------------------------------


def save_claimant(conn: sqlite3.Connection, claimant: Claimant) -> None:
    conn.execute(
        "INSERT INTO claimants (claimant_id, name, phone, bank_account, address, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            claimant.claimant_id,
            claimant.name,
            claimant.phone,
            claimant.bank_account,
            claimant.address,
            claimant.created_at.isoformat(),
        ),
    )


def get_claimant(conn: sqlite3.Connection, claimant_id: str) -> Optional[Claimant]:
    row = conn.execute("SELECT * FROM claimants WHERE claimant_id = ?", (claimant_id,)).fetchone()
    if row is None:
        return None
    return Claimant(
        claimant_id=row["claimant_id"],
        name=row["name"],
        phone=row["phone"],
        bank_account=row["bank_account"],
        address=row["address"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


def insert_finding(conn: sqlite3.Connection, finding: Finding) -> None:
    conn.execute(
        "INSERT INTO findings "
        "(finding_id, check_id, case_id, category, verdict, confidence, "
        " explanation, evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            finding.finding_id,
            finding.check_id,
            finding.case_id,
            finding.category.value,
            finding.verdict.value,
            finding.confidence,
            finding.explanation,
            json.dumps(finding.evidence),
            finding.created_at.isoformat(),
        ),
    )


def get_findings_for_case(conn: sqlite3.Connection, case_id: str) -> list[Finding]:
    rows = conn.execute(
        "SELECT * FROM findings WHERE case_id = ? ORDER BY rowid", (case_id,)
    ).fetchall()
    return [_finding_from_row(r) for r in rows]


def _finding_from_row(row: sqlite3.Row) -> Finding:
    return Finding(
        finding_id=row["finding_id"],
        check_id=row["check_id"],
        case_id=row["case_id"],
        category=CheckCategory(row["category"]),
        verdict=Verdict(row["verdict"]),
        confidence=row["confidence"],
        explanation=row["explanation"],
        evidence=json.loads(row["evidence"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


# ---------------------------------------------------------------------------
# PerceptionRecord - the dedup cache
# ---------------------------------------------------------------------------


def get_perception_record(conn: sqlite3.Connection, content_hash: str) -> Optional[PerceptionRecord]:
    row = conn.execute(
        "SELECT * FROM perception_records WHERE content_hash = ?", (content_hash,)
    ).fetchone()
    return _perception_from_row(row) if row is not None else None


def upsert_perception_record(conn: sqlite3.Connection, record: PerceptionRecord) -> None:
    conn.execute(
        "INSERT INTO perception_records "
        "(content_hash, source, embedding, caption, ocr_text, damage_description, "
        " damage_severity, weather_observed, road_condition, shadow_direction, "
        " shadow_length, lighting, plate_text, scene_context, anomaly_notes, "
        " raw_response, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(content_hash) DO UPDATE SET "
        "  source=excluded.source, embedding=excluded.embedding, "
        "  caption=excluded.caption, ocr_text=excluded.ocr_text, "
        "  damage_description=excluded.damage_description, "
        "  damage_severity=excluded.damage_severity, "
        "  weather_observed=excluded.weather_observed, "
        "  road_condition=excluded.road_condition, "
        "  shadow_direction=excluded.shadow_direction, "
        "  shadow_length=excluded.shadow_length, "
        "  lighting=excluded.lighting, "
        "  plate_text=excluded.plate_text, "
        "  scene_context=excluded.scene_context, "
        "  anomaly_notes=excluded.anomaly_notes, "
        "  raw_response=excluded.raw_response",
        (
            record.content_hash,
            record.source,
            json.dumps(record.embedding) if record.embedding is not None else None,
            record.caption,
            record.ocr_text,
            record.damage_description,
            record.damage_severity,
            record.weather_observed,
            record.road_condition,
            record.shadow_direction,
            record.shadow_length,
            record.lighting,
            record.plate_text,
            record.scene_context,
            record.anomaly_notes,
            json.dumps(record.raw_response),
            record.created_at.isoformat(),
        ),
    )


def _perception_from_row(row: sqlite3.Row) -> PerceptionRecord:
    return PerceptionRecord(
        content_hash=row["content_hash"],
        source=row["source"],
        embedding=json.loads(row["embedding"]) if row["embedding"] is not None else None,
        caption=row["caption"],
        ocr_text=row["ocr_text"],
        damage_description=row["damage_description"],
        damage_severity=row["damage_severity"],
        weather_observed=row["weather_observed"],
        road_condition=row["road_condition"],
        shadow_direction=row["shadow_direction"],
        shadow_length=row["shadow_length"],
        lighting=row["lighting"],
        plate_text=row["plate_text"],
        scene_context=row["scene_context"],
        anomaly_notes=row["anomaly_notes"],
        raw_response=json.loads(row["raw_response"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


# save_perception/get_perception/perception_coverage: the names
# src/perception.py (and the rest of the codebase going forward) uses.
# Aliased rather than duplicated - upsert_perception_record/
# get_perception_record stay as the implementation so existing callers
# (test_models.py) keep working unchanged.
save_perception = upsert_perception_record
get_perception = get_perception_record


def perception_coverage(conn: sqlite3.Connection) -> dict[str, Any]:
    """
    How much of the corpus has been through the one-time vision pass.
    Counts distinct content hashes, not image rows or case rows - the
    entire point of keying PerceptionRecord by content_hash is that the
    same photo submitted to three cases is one call, so "coverage" has
    to mean unique photos covered, not submissions covered.
    """
    total = conn.execute("SELECT COUNT(DISTINCT content_hash) AS n FROM images").fetchone()["n"]
    covered = conn.execute(
        "SELECT COUNT(DISTINCT i.content_hash) AS n FROM images i "
        "JOIN perception_records p ON p.content_hash = i.content_hash"
    ).fetchone()["n"]
    return {
        "total": total,
        "covered": covered,
        "remaining": total - covered,
        "pct": (100.0 * covered / total) if total else 0.0,
    }


# ---------------------------------------------------------------------------
# ImageArtifact
# ---------------------------------------------------------------------------


def insert_image_artifact(conn: sqlite3.Connection, artifact: ImageArtifact) -> None:
    conn.execute(
        "INSERT INTO image_artifacts "
        "(artifact_id, case_id, content_hash, filename, role, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            artifact.artifact_id,
            artifact.case_id,
            artifact.content_hash,
            artifact.filename,
            artifact.role,
            artifact.uploaded_at.isoformat(),
        ),
    )


def get_artifacts_for_case(conn: sqlite3.Connection, case_id: str) -> list[ImageArtifact]:
    rows = conn.execute(
        "SELECT * FROM image_artifacts WHERE case_id = ? ORDER BY uploaded_at", (case_id,)
    ).fetchall()
    return [
        ImageArtifact(
            artifact_id=r["artifact_id"],
            case_id=r["case_id"],
            content_hash=r["content_hash"],
            filename=r["filename"],
            role=r["role"],
            uploaded_at=datetime.fromisoformat(r["uploaded_at"]),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# AgentDecision
# ---------------------------------------------------------------------------


def insert_agent_decision(conn: sqlite3.Connection, decision: AgentDecision) -> None:
    conn.execute(
        "INSERT INTO agent_decisions "
        "(decision_id, case_id, recommendation, confidence, summary, "
        " supporting_finding_ids, requested_artifacts, policy_version, risk_band, score, "
        " tool_calls_count, iterations_count, llm_calls_count, latency_ms, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            decision.decision_id,
            decision.case_id,
            decision.recommendation.value,
            decision.confidence,
            decision.summary,
            json.dumps(decision.supporting_finding_ids),
            json.dumps(decision.requested_artifacts),
            decision.policy_version,
            decision.risk_band.value if decision.risk_band is not None else None,
            decision.score,
            decision.tool_calls_count,
            decision.iterations_count,
            decision.llm_calls_count,
            decision.latency_ms,
            decision.created_at.isoformat(),
        ),
    )


def delete_decisions_for_policy(conn: sqlite3.Connection, policy_version: str) -> int:
    """
    Remove every decision written by one policy version, returning how
    many rows went. Re-running an ablation arm must replace that arm's
    decisions rather than accumulate a second set beside them - and it
    must not touch the other arm, which is exactly what policy_version
    is for.
    """
    cursor = conn.execute("DELETE FROM agent_decisions WHERE policy_version = ?", (policy_version,))
    return cursor.rowcount


def get_decisions_for_case(conn: sqlite3.Connection, case_id: str) -> list[AgentDecision]:
    rows = conn.execute(
        "SELECT * FROM agent_decisions WHERE case_id = ? ORDER BY rowid", (case_id,)
    ).fetchall()
    return [
        AgentDecision(
            decision_id=r["decision_id"],
            case_id=r["case_id"],
            recommendation=Recommendation(r["recommendation"]),
            confidence=r["confidence"],
            summary=r["summary"],
            supporting_finding_ids=json.loads(r["supporting_finding_ids"]),
            requested_artifacts=json.loads(r["requested_artifacts"]),
            policy_version=r["policy_version"],
            risk_band=RiskBand(r["risk_band"]) if r["risk_band"] else None,
            score=r["score"],
            tool_calls_count=r["tool_calls_count"],
            iterations_count=r["iterations_count"],
            llm_calls_count=r["llm_calls_count"],
            latency_ms=r["latency_ms"],
            created_at=datetime.fromisoformat(r["created_at"]),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# AdminActionRecord - human decisions, not agent recommendations
# ---------------------------------------------------------------------------

def insert_admin_action(conn: sqlite3.Connection, action: AdminActionRecord) -> None:
    conn.execute(
        "INSERT INTO admin_actions (case_id, admin_id, action, reason, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            action.case_id,
            action.admin_id,
            action.action.value,
            action.reason,
            action.timestamp.isoformat(),
        ),
    )


def get_admin_actions_for_case(conn: sqlite3.Connection, case_id: str) -> list[AdminActionRecord]:
    rows = conn.execute(
        "SELECT * FROM admin_actions WHERE case_id = ? ORDER BY rowid", (case_id,)
    ).fetchall()
    return [
        AdminActionRecord(
            case_id=r["case_id"],
            admin_id=r["admin_id"],
            action=AdminAction(r["action"]),
            reason=r["reason"],
            timestamp=datetime.fromisoformat(r["timestamp"]),
        )
        for r in rows
    ]


def get_latest_admin_action(conn: sqlite3.Connection, case_id: str) -> Optional[AdminActionRecord]:
    row = conn.execute(
        "SELECT * FROM admin_actions WHERE case_id = ? ORDER BY rowid DESC LIMIT 1",
        (case_id,),
    ).fetchone()
    if row is None:
        return None
    return AdminActionRecord(
        case_id=row["case_id"],
        admin_id=row["admin_id"],
        action=AdminAction(row["action"]),
        reason=row["reason"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
    )


# ---------------------------------------------------------------------------
# Image - the ingest pipeline's own record (see models.py for why this
# is a separate table from PerceptionRecord/ImageArtifact)
# ---------------------------------------------------------------------------


def save_image(conn: sqlite3.Connection, image: Image) -> None:
    conn.execute(
        "INSERT INTO images "
        "(image_id, case_id, path, content_hash, phash, dhash, embedding, exif, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            image.image_id,
            image.case_id,
            image.path,
            image.content_hash,
            image.phash,
            image.dhash,
            json.dumps(image.embedding) if image.embedding is not None else None,
            json.dumps(image.exif),
            image.created_at.isoformat(),
        ),
    )


def get_image(conn: sqlite3.Connection, image_id: str) -> Optional[Image]:
    row = conn.execute("SELECT * FROM images WHERE image_id = ?", (image_id,)).fetchone()
    return _image_from_row(row) if row is not None else None


def get_images_for_case(conn: sqlite3.Connection, case_id: str) -> list[Image]:
    rows = conn.execute(
        "SELECT * FROM images WHERE case_id = ? ORDER BY rowid", (case_id,)
    ).fetchall()
    return [_image_from_row(r) for r in rows]


def get_all_images(conn: sqlite3.Connection) -> list[Image]:
    """
    Every ingested image, any case. This is the corpus find_similar()
    in src/ingest.py scans - a full table read, brute-forced in numpy
    at the caller. Fine at hundreds of cases; once this becomes the
    bottleneck, it's also the one query the pgvector migration (see
    module docstring) replaces with an index lookup.
    """
    rows = conn.execute("SELECT * FROM images ORDER BY created_at").fetchall()
    return [_image_from_row(r) for r in rows]


def _image_from_row(row: sqlite3.Row) -> Image:
    return Image(
        image_id=row["image_id"],
        case_id=row["case_id"],
        path=row["path"],
        content_hash=row["content_hash"],
        phash=row["phash"],
        dhash=row["dhash"],
        embedding=json.loads(row["embedding"]) if row["embedding"] is not None else None,
        exif=json.loads(row["exif"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


# ---------------------------------------------------------------------------
# AuditEvent - append-only operational log
# ---------------------------------------------------------------------------


def log_audit_event(conn: sqlite3.Connection, event: AuditEvent) -> None:
    conn.execute(
        "INSERT INTO audit_log (event_id, event_type, case_id, details, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            event.event_id,
            event.event_type,
            event.case_id,
            json.dumps(event.details),
            event.created_at.isoformat(),
        ),
    )


def get_audit_events_for_case(conn: sqlite3.Connection, case_id: str) -> list[AuditEvent]:
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE case_id = ? ORDER BY rowid", (case_id,)
    ).fetchall()
    return [
        AuditEvent(
            event_id=r["event_id"],
            event_type=r["event_type"],
            case_id=r["case_id"],
            details=json.loads(r["details"]),
            created_at=datetime.fromisoformat(r["created_at"]),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Generic cache - keyed by (namespace, cache_key), value is arbitrary JSON.
#
# This is what makes the free tier survivable: src/llm.py hashes its
# inputs into cache_key and stores the response here before it ever
# touches usage_stats() again. Any other expensive, deterministic call
# (CLIP embeddings, OCR) can reuse this same pair of functions with its
# own namespace instead of growing a bespoke table.
# ---------------------------------------------------------------------------


def cache_get(conn: sqlite3.Connection, namespace: str, key: str) -> Optional[Any]:
    """Return the cached value for (namespace, key), or None on a miss."""
    row = conn.execute(
        "SELECT value FROM cache_entries WHERE namespace = ? AND cache_key = ?",
        (namespace, key),
    ).fetchone()
    return json.loads(row["value"]) if row is not None else None


def cache_set(conn: sqlite3.Connection, namespace: str, key: str, value: Any) -> None:
    """Store `value` (anything json.dumps can serialise) under (namespace, key)."""
    conn.execute(
        "INSERT INTO cache_entries (namespace, cache_key, value, created_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(namespace, cache_key) DO UPDATE SET "
        "  value=excluded.value, created_at=excluded.created_at",
        (namespace, key, json.dumps(value), datetime.now(timezone.utc).isoformat()),
    )
