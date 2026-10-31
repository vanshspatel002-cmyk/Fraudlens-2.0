"""Browser-visible error contracts, without production data or provider calls."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from src import api


@pytest.mark.parametrize('failure, status, code', [
    (sqlite3.OperationalError('database unavailable'), 503, 'DATABASE_UNAVAILABLE'),
    (RuntimeError('unexpected failure'), 500, 'INTERNAL_ERROR'),
])
def test_backend_errors_remain_readable_cross_origin(monkeypatch, failure, status, code):
    def unavailable():
        raise failure

    monkeypatch.setitem(api.app.dependency_overrides, api.get_conn, unavailable)
    monkeypatch.setitem(api.app.dependency_overrides, api.require_admin, lambda: 'test-reviewer')
    # No lifespan: fail before database access or model loading.
    client = TestClient(api.app, raise_server_exceptions=False)
    origin = api._cors_origins()[0]
    response = client.get('/v1/cases', headers={'Origin': origin})
    assert response.status_code == status
    assert response.json()['code'] == code
    assert response.headers['access-control-allow-origin'] == origin
    assert response.headers['cache-control'] == 'no-store'


def test_rate_limit_remains_readable_cross_origin(monkeypatch):
    monkeypatch.setattr(api, '_rate_limited', lambda request: (True, 12))
    client = TestClient(api.app, raise_server_exceptions=False)
    origin = api._cors_origins()[0]
    response = client.post('/v1/cases', headers={'Origin': origin})
    assert response.status_code == 429
    assert response.json()['code'] == 'RATE_LIMITED'
    assert response.headers['retry-after'] == '12'
    assert response.headers['access-control-allow-origin'] == origin


def test_untrusted_origin_is_not_allowed(monkeypatch):
    monkeypatch.setattr(api, '_rate_limited', lambda request: (True, 12))
    response = TestClient(api.app).post('/v1/cases', headers={'Origin': 'https://untrusted.example'})
    assert response.status_code == 429
    assert 'access-control-allow-origin' not in response.headers
