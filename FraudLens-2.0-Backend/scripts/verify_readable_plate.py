"""Actual local OCR/cache/comparison on an existing, visually inspected photo.

Uses the project's existing research evidence only for the authorized local
verification; does not redistribute photographs or assert ownership/licensing.
The photograph contains two vehicles. The rear plate was manually transcribed
before inference. This exercises comparison paths, not identity/accuracy claims.
"""
import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src import db
from src.checks.base import CheckContext
from src.checks.plate_ocr import PLATE_OCR_CHECK,get_reader
from src.timing import windows_memory


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    destination=args.output.with_suffix('.db')
    if args.output.exists() or destination.exists():raise SystemExit('Use new output/database paths.')
    os.environ['HF_HUB_OFFLINE']='1'
    source=db.connect(args.source)
    try:
        original=db.get_case(source,'case-0237')
        image=next(i for i in db.get_images_for_case(source,original.case_id) if Path(i.path).name=='whole_0725.jpg')
    finally:source.close()
    photo=Path(image.path)
    if not photo.is_absolute():photo=ROOT/photo
    assert hashlib.sha256(photo.read_bytes()).hexdigest()==image.content_hash
    ledger=ROOT/'outputs/pilot_validation/live_calls.json'
    before=hashlib.sha256(ledger.read_bytes()).hexdigest()
    started=time.monotonic();reader=get_reader();warmup=time.monotonic()-started
    if reader is None:raise SystemExit('OCR unavailable; no successful comparison claimed.')
    result={'provider_requests':0,'reader_initialization_seconds':round(warmup,3),
        'source_image_sha256':image.content_hash,'manual_rear_plate':'HR26TC0710',
        'manual_front_plate':'HR26TC0711','photo_contains_two_vehicles':True,
        'limitation':'One existing photo with two vehicles; comparison execution is not verified vehicle identity or general OCR accuracy.',
        'comparisons':[]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    conn=db.connect(destination);db.init_db(conn)
    try:
        for registration in ('HR26TC0710','HR26TC9999'):
            case=replace(original,case_id='case-'+uuid.uuid4().hex[:12],vehicle_registration=registration)
            local_image=replace(image,image_id=uuid.uuid4().hex,case_id=case.case_id,path=str(photo))
            db.insert_case(conn,case);db.save_image(conn,local_image);conn.commit()
            ctx=CheckContext(conn,case,[local_image],{},config={'cache_ocr':True,'plate_ocr_observed_prefix':True})
            started=time.monotonic()
            finding=PLATE_OCR_CHECK._check_one_image(ctx,local_image,reader,PLATE_OCR_CHECK.OCR_CONFIDENCE_CONCERN)
            result['comparisons'].append({'declaration':registration,'verdict':finding.verdict.value,
                'seconds':round(time.monotonic()-started,3),'explanation':finding.explanation,'evidence':finding.evidence})
            args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        result.update(windows_memory())
        result['actual_local_ocr_executions']=sum(not row['evidence'].get('ocr_cache_reused',False) for row in result['comparisons'])
        assert result['comparisons'][1]['evidence'].get('ocr_cache_reused'), 'Cache reuse did not execute'
        assert hashlib.sha256(ledger.read_bytes()).hexdigest()==before
        args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='comparisons'}),flush=True)
        print([(r['declaration'],r['verdict'],r['seconds']) for r in result['comparisons']],flush=True)
    finally:conn.close()


if __name__=='__main__':main()
