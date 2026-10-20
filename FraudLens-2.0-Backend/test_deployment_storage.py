"""Storage deployment gates use private temporary files and no live provider."""
import pytest
from scripts import start_deployment
from src.storage_health import check_storage_ready


@pytest.fixture
def clean_environment(monkeypatch):
    monkeypatch.setattr('dotenv.load_dotenv',lambda *a,**k:None)
    for key in ('DATABASE_URL','FRAUDLENS_PERSISTENT_ROOT','FRAUDLENS_UPLOAD_DIR',
                'FRAUDLENS_THUMB_DIR','FRAUDLENS_LIVE_LEDGER','GEMINI_QUOTA_BUDGET','CORS_ORIGINS'):
        monkeypatch.delenv(key,raising=False)


def test_deployment_refuses_sqlite_fallback_and_missing_volume(clean_environment,monkeypatch):
    with pytest.raises(ValueError,match='DATABASE_URL'):
        start_deployment.configure()
    monkeypatch.setenv('DATABASE_URL','postgresql://fixture.invalid/example')
    with pytest.raises(ValueError,match='PERSISTENT_ROOT'):
        start_deployment.configure()


def test_deployment_requires_preserved_ledgers_and_exact_https_origins(clean_environment,tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_URL','postgresql://fixture.invalid/example')
    monkeypatch.setenv('FRAUDLENS_PERSISTENT_ROOT',str(tmp_path))
    with pytest.raises(ValueError,match='LIVE_LEDGER'):
        start_deployment.configure()
    for name in ('live_calls.json','quota_budget.json'):
        (tmp_path/name).write_text('{"fixture":true}',encoding='utf-8')
    monkeypatch.setenv('CORS_ORIGINS','*')
    with pytest.raises(ValueError,match='HTTPS'):
        start_deployment.configure()
    monkeypatch.setenv('CORS_ORIGINS','https://frontend.example.com')
    start_deployment.configure()
    check_storage_ready(tmp_path/'uploads',tmp_path/'thumbnails')
    assert not list(tmp_path.glob('uploads/*'))
    assert (tmp_path/'live_calls.json').read_text(encoding='utf-8')=='{"fixture":true}'


def test_readiness_refuses_paths_outside_declared_volume(clean_environment,tmp_path,monkeypatch):
    monkeypatch.setenv('FRAUDLENS_PERSISTENT_ROOT',str(tmp_path/'missing-volume'))
    with pytest.raises(OSError,match='volume'):
        check_storage_ready(tmp_path/'uploads',tmp_path/'thumbnails')
    monkeypatch.setenv('FRAUDLENS_PERSISTENT_ROOT',str(tmp_path))
    with pytest.raises(OSError,match='outside'):
        check_storage_ready(tmp_path.parent/'outside-volume',tmp_path/'thumbnails')
