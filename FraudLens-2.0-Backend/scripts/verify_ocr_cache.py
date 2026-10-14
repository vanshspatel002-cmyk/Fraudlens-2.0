"""One actual local OCR reading plus cache reuse on an isolated database.

No LLM/provider calls; no detection-accuracy assertion or original data writes.
"""
import json
import os
from pathlib import Path
import sys
import time
import argparse

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.chdir(ROOT)
from src import db
from src.checks.base import CheckContext
from src.checks.plate_ocr import PLATE_OCR_CHECK,get_reader


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--name',default='ocr-cache')
    name=parser.parse_args().name
    if not name or any(not (c.isalnum() or c in '-_') for c in name):raise SystemExit('Use a simple unique output name.')
    import torch
    torch.set_num_threads(2)
    out=ROOT/'outputs/pilot_validation';path=out/(name+'.db')
    if path.exists():raise SystemExit('Preserve the existing OCR verification rather than overwrite it.')
    source=db.connect(ROOT/'fraudlens.db')
    try:
        selected=next((c,images[0]) for c in db.get_all_cases(source) if c.agent_type=='claims'
            and (images:=db.get_images_for_case(source,c.case_id)) and Path(images[0].path).is_file())
    finally:source.close()
    case,image=selected;conn=db.connect(path);db.init_db(conn)
    try:
        db.insert_case(conn,case);db.save_image(conn,image);conn.commit()
        reader=get_reader()
        if reader is None:raise RuntimeError('Actual local OCR engine unavailable; no success claimed.')
        ctx=CheckContext(conn=conn,case=case,images=[image],perception={},config={'cache_ocr':True})
        started=time.monotonic();first=PLATE_OCR_CHECK._check_one_image(ctx,image,reader,.8);first_seconds=time.monotonic()-started
        assert first.evidence.get('ocr_cache_key') and not first.evidence['ocr_cache_reused']
        started=time.monotonic();second=PLATE_OCR_CHECK._check_one_image(ctx,image,reader,.8);second_seconds=time.monotonic()-started
        assert second.evidence['ocr_cache_reused']
        assert first.verdict==second.verdict and first.evidence.get('raw_ocr_strings')==second.evidence.get('raw_ocr_strings')
        another=db.connect(path)
        try:another.execute('BEGIN IMMEDIATE');another.rollback()
        finally:another.close()
        result={'actual_local_ocr_calls':1,'provider_calls':0,'first_seconds':round(first_seconds,3),
            'cached_seconds':round(second_seconds,3),'verdict':first.verdict.value,
            'raw_observation_count':len(first.evidence.get('raw_ocr_strings',[])),
            'second_reused_cache':True,'writer_lock_released':True,
            'limitation':'One execution/cache example; no OCR matching or detection accuracy demonstrated.'}
        (out/(name+'-verification.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)
    finally:conn.close()


if __name__=='__main__':main()
