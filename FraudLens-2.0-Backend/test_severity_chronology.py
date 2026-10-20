"""Damage chronology must compare instants, including differing UTC offsets."""
from datetime import datetime
import sqlite3
from types import SimpleNamespace

import pytest

from src.checks.base import CheckContext
from src.checks.severity_progression import SeverityProgressionCheck
from src.models import Verdict


@pytest.mark.parametrize('earlier,later', [
    ('2026-10-20T09:00:00+05:30', '2026-10-20T08:00:00-05:00'),
    ('2026-10-19T23:00:00-05:00', '2026-10-20T10:00:00+05:30'),
    ('2026-10-20T01:00:00', '2026-10-20T02:00:00'),
])
def test_worsening_damage_is_not_a_repeat_when_offsets_sort_differently(monkeypatch, earlier, later):
    conn = sqlite3.connect(':memory:')
    try:
        conn.execute('CREATE TABLE cases (case_id TEXT, declared_time TEXT, vehicle_registration TEXT, agent_type TEXT)')
        conn.execute('CREATE TABLE audit_log (event_type TEXT, created_at TEXT, case_id TEXT)')
        conn.executemany('INSERT INTO cases VALUES (?,?,?,?)', [
            ('prior', earlier, 'FICTIONAL', 'claims'), ('current', later, 'FICTIONAL', 'claims')])
        case = SimpleNamespace(case_id='current', declared_time=datetime.fromisoformat(later),
                               vehicle_registration='FICTIONAL', agent_type='claims')
        check = SeverityProgressionCheck()
        monkeypatch.setattr(check, '_severity_for', lambda ctx, case_id:
                            ('minor' if case_id == 'prior' else 'moderate', 'bumper damage'))
        result = check.run(CheckContext(conn, case, [], {}))[0]
        assert result.verdict is Verdict.PASS
        assert [row['case_id'] for row in result.evidence['sequence']] == ['prior', 'current']
    finally:
        conn.close()
