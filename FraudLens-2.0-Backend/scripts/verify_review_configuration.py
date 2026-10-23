"""Read-only process configuration check; never prints credentials or calls AI."""
import argparse,sys,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.diagnose_gemini import process_environment
from src.pilot_config import load_pilot_environment

def main():
    p=argparse.ArgumentParser();p.add_argument('--api-process-id',type=int,required=True);p.add_argument('--schema',choices=['fraudlens_pilot','fraudlens_validation_panel_20261022'],required=True);p.add_argument('--start-worker',action='store_true');a=p.parse_args()
    try:
        env=load_pilot_environment(process_environment(a.api_process_id))
        expected=ROOT/('outputs/final_presentation/rehearsal' if a.schema.endswith('panel_20261022') else 'outputs/pilot_validation')
        assert env['FRAUDLENS_PG_SCHEMA']==a.schema
        assert Path(env['FRAUDLENS_UPLOAD_DIR']).resolve()==(expected/'uploads').resolve()
        assert Path(env['FRAUDLENS_THUMB_DIR']).resolve()==(expected/'thumbnails').resolve()
    except Exception:
        print('API configuration mismatch/unavailable. Use the same dataset launcher for API and worker; no worker started.');return 1
    print('API schema, private evidence and original shared provider controls match the selected dataset.',flush=True)
    if a.start_worker:
        # Inherit the reference process, never stale shell keys/models/ledgers.
        env.update(FRAUDLENS_WORKER_ENABLED='1',FRAUDLENS_WARM_MODELS='0')
        return subprocess.run([sys.executable,'-u','-X','utf8',str(ROOT/'scripts/run_worker.py')],cwd=ROOT,env=env).returncode
    return 0

if __name__=='__main__':sys.exit(main())
