"""Single-host deployment entrypoint with explicit PostgreSQL/private volume.

Provision the volume and restore the preserved provider ledgers before launch.
Use --worker for a separate worker attached to the SAME host/volume. Multi-host
object storage and a distributed provider budget are separate deployment work.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def configure():
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    if not os.environ.get('DATABASE_URL'):
        raise ValueError('DATABASE_URL is required; deployment never falls back to SQLite.')
    os.environ['FRAUDLENS_DB'] = 'postgresql'
    configured = os.environ.get('FRAUDLENS_PERSISTENT_ROOT', '')
    volume = Path(configured)
    if not configured or not volume.is_absolute() or not volume.is_dir():
        raise ValueError('FRAUDLENS_PERSISTENT_ROOT must name an existing absolute private persistent-volume mount.')
    volume = volume.resolve()
    # Every mutable file, including the persistent stop controls, shares the
    # declared volume. This declaration cannot verify the host's actual mount.
    defaults = {'FRAUDLENS_UPLOAD_DIR': 'uploads', 'FRAUDLENS_THUMB_DIR': 'thumbnails',
                'FRAUDLENS_LIVE_LEDGER': 'live_calls.json', 'GEMINI_QUOTA_BUDGET': 'quota_budget.json'}
    for key, name in defaults.items():
        path = Path(os.environ.get(key, str(volume / name)))
        if not path.is_absolute() or not path.resolve().is_relative_to(volume):
            raise ValueError(key + ' must be an absolute path inside the persistent root.')
        os.environ[key] = str(path)
    for key in ('FRAUDLENS_LIVE_LEDGER', 'GEMINI_QUOTA_BUDGET'):
        if not Path(os.environ[key]).is_file():
            raise ValueError(key + ' is missing. Restore the existing ledger; never reset the allowance.')
    origins = [value.strip() for value in os.environ.get('CORS_ORIGINS', '').split(',') if value.strip()]
    if not origins or any(not value.startswith('https://') or '*' in value for value in origins):
        raise ValueError('CORS_ORIGINS must list the exact HTTPS frontend origins for deployment.')
    for key in ('FRAUDLENS_UPLOAD_DIR', 'FRAUDLENS_THUMB_DIR'):
        Path(os.environ[key]).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=volume) as probe:
        probe.write(b'fraudlens-readiness')
    os.environ.setdefault('GEMINI_QUOTA_CONSUMER', 'pilot')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--worker', action='store_true')
    mode.add_argument('--embedded-worker', action='store_true', help='Single-service API and durable worker sharing one volume')
    args = parser.parse_args()
    try:
        configure()
        port = int(os.environ.get('PORT', '8000'))
        if not 1 <= port <= 65535:
            raise ValueError('PORT must be between 1 and 65535.')
    except (ValueError, OSError) as exc:
        print('Deployment prerequisites failed:', str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
        return 1
    os.environ['FRAUDLENS_WORKER_ENABLED'] = '1' if args.worker or args.embedded_worker else '0'
    command = [sys.executable, '-u', 'scripts/run_worker.py'] if args.worker else [
        sys.executable, '-m', 'uvicorn', 'src.api:app', '--host', '0.0.0.0', '--port', str(port)]
    return subprocess.call(command, cwd=ROOT)


if __name__ == '__main__':
    raise SystemExit(main())
