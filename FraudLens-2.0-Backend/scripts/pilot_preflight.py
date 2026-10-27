"""Check a local pilot without printing secrets. --live spends a real model call."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import api, db


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Make one real Gemini/provider chat probe; retries may consume additional quota')
    parser.add_argument('--warm-models', action='store_true', help='Load/download the CLIP model before presenting')
    args = parser.parse_args()
    local = os.getenv('FRAUDLENS_ASSESSMENT_MODE')=='local_rules'
    if local and args.live:
        parser.error('--live is unavailable in local_rules mode; no provider request was made.')
    errors = []
    for name in ['fastapi', 'multipart', 'PIL', 'imagehash', 'torch', 'open_clip'] + ([] if local else ['google.genai']):
        try:
            found = importlib.util.find_spec(name) is not None
        except ModuleNotFoundError:
            found = False
        print(f'{name}: {"installed" if found else "MISSING"}')
        if not found: errors.append(name)
    for name in ['ADMIN_EMAIL', 'ADMIN_PASSWORD_SHA256'] + ([] if local else ['GEMINI_API_KEY']):
        configured = bool(os.environ.get(name))
        print(f'{name}: {"configured" if configured else "MISSING"}')
        if not configured: errors.append(name)
    if local:print('Assessment mode: Local rules assessment; Gemini is not required or probed.')
    if api.DB_PATH != 'postgresql':
        Path(api.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(api.DB_PATH)
    try:
        db.init_db(conn)
        print('Database: ready')
        print('Existing cases:', conn.execute('SELECT COUNT(*) FROM cases').fetchone()[0])
    finally: conn.close()
    if args.warm_models:
        try:
            from src.ingest import _default_embedder
            _default_embedder._ensure_loaded()
            print('CLIP: loaded')
        except Exception as exc:
            print('CLIP load failed:', type(exc).__name__)
            errors.append('CLIP')
    if args.live:
        provider = None
        try:
            from src.llm import get_provider
            provider = get_provider()
            result = provider.chat([{'role': 'user', 'content': 'Reply with ready.'}])
            if not result.text.strip(): raise ValueError('Empty provider reply')
            print('Live model: response received (not a vision or accuracy test)')
        except Exception as exc:
            print('Live model failed:', type(exc).__name__)
            errors.append('live model')
        finally:
            if provider is not None and hasattr(provider, 'close'): provider.close()
    print('BLOCKED: resolve missing items before rehearsal.' if errors else 'Preflight passed. Run the two-tab rehearsal next.')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
