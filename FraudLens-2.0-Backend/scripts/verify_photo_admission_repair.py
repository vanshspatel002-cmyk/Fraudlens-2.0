"""Offline native CLIP qualification plus real isolated four/six-slot API intake.

No provider generation, external network, business records or model downloads.
Corpus pictures exercise recognition; they are not a same-car application set.
Only the separately licensed presentation car is used for isolated submissions.
"""
import argparse, hashlib, json, os, sys, tempfile, time, uuid
from pathlib import Path
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',FRAUDLENS_WORKER_ENABLED='0',FRAUDLENS_WARM_MODELS='0')
B=Path(__file__).resolve().parents[1];R=B.parent
sys.path.insert(0,str(B))
from PIL import Image,ImageOps,ImageFilter,ImageDraw
from src import photo_admission as gate,vehicle_gate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=B/'outputs/photo_admission/repair-native.json')
    args=parser.parse_args();rows=[]
    # Reuse real image embeddings across slot tests, never substitute model scores.
    class NativeMemo:
        def __init__(self):self.base=vehicle_gate._default_embedder;self.vectors={};self.calls=0
        def _ensure_loaded(self):self.base._ensure_loaded()
        def embed_texts(self,texts):return self.base.embed_texts(texts)
        def embed(self,path):
            key=hashlib.sha256(Path(path).read_bytes()).hexdigest();self.calls+=1
            if key not in self.vectors:self.vectors[key]=self.base.embed(path)
            return self.vectors[key]
    memo=NativeMemo();vehicle_gate._default_embedder=memo
    start=time.perf_counter();gate.warmup(include_ocr=False);warmup=time.perf_counter()-start
    print(json.dumps({'stage':'native_ready','seconds':round(warmup,3)}),flush=True)
    assets=R/'docs/presentation_assets'
    with tempfile.TemporaryDirectory(prefix='fraudlens_native_admission_') as directory:
        td=Path(directory)
        with Image.open(assets/'chevrolet-classic-rear.jpg') as im:
            w,h=im.size;im.crop((int(w*.34),int(h*.62),int(w*.72),int(h*.99))).save(td/'mounted-plate.png')
        with Image.open(B/'data/curated/whole/whole_0004.jpg') as im:
            rgb=ImageOps.exif_transpose(im).convert('RGB')
            exif=Image.Exif();exif[274]=6
            rgb.transpose(Image.Transpose.ROTATE_90).save(td/'rotated-exif.jpg',exif=exif)
            paper=Image.new('RGB',(1000,1200),'white');pic=ImageOps.contain(rgb,(700,500));paper.paste(pic,(100,250))
            ImageDraw.Draw(paper).text((50,50),'VEHICLE INSURANCE DOCUMENT - FICTIONAL CONTROL',fill='black');paper.save(td/'printed-document.png')
            rgb.filter(ImageFilter.GaussianBlur(12)).save(td/'blur.jpg')
        def check(name,path,kind,slot,expected,basis):
            mime={'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png'}[path.suffix[1:].lower()]
            started=time.perf_counter()
            with tempfile.TemporaryDirectory(dir=td) as work:
                try:result=gate.validate(path.read_bytes(),mime,kind,slot,('native-repair',name),work).to_dict()
                except gate.InvalidPhoto as exc:result={'state':'rejected','reason':str(exc)}
                except gate.ValidatorUnavailable as exc:result={'state':'unavailable','reason':str(exc)}
            row={'name':name,'kind':kind,'slot':slot,'expected':expected,'basis':basis,
                'matched':result['state']=='accepted' if expected=='accepted' else result['state'] in {'rejected','needs_replacement'},
                'seconds':round(time.perf_counter()-started,3),**result}
            rows.append(row)
            print(json.dumps({k:row[k] for k in ['name','slot','state','matched']}),flush=True)
        # First six reproduced the bug; the next six are held out from this repair.
        for i in range(1,13):
            path=B/f'data/curated/whole/whole_{i:04}.jpg'
            for slot in ['vehicle_overview','damage_overview','damage_closeup']:
                check(f'corpus-{i}-{slot}',path,'claims',slot,'accepted','reproduction_positive' if i<=6 else 'held_out_positive')
        for path in sorted((B/'data/curated/damaged').glob('*.jpg'))[:4]:
            for slot in ['damage_overview','damage_closeup']:check(path.stem+'-'+slot,path,'claims',slot,'accepted','real_damaged_part')
        sets={
            'claims':['chevrolet-classic-front-right.jpg','mounted-plate.png','chevrolet-classic-left.jpg','chevrolet-classic-door.jpg'],
            'underwriting':['chevrolet-classic-left.jpg','chevrolet-classic-front-right.jpg','chevrolet-classic-rear-left.jpg','chevrolet-classic-rear-right.jpg','chevrolet-classic-gauges.jpg','mounted-plate.png'],
        }
        def asset(name):return td/name if name=='mounted-plate.png' else assets/name
        for kind,names in sets.items():
            for slot,name in zip(gate.SLOTS[kind],names):check(kind+'-'+slot,asset(name),kind,slot,'accepted','licensed_same_car; views declared, off odometer and text not verified')
        check('rotated-exif',td/'rotated-exif.jpg','claims','damage_overview','accepted','real photograph with authored orientation metadata')
        check('printed-document',td/'printed-document.png','claims','damage_overview','not_accepted','authored printed-car document control')
        check('severe-blur',td/'blur.jpg','claims','damage_overview','not_accepted','authored degradation control')
        import skimage.data
        packaged=Path(skimage.data.__file__).parent
        for name in ['astronaut.png','chelsea.png','coffee.png','grass.png','motorcycle_left.png','page.png','coins.png']:
            path=packaged/name
            if not path.is_file():raise RuntimeError('Required packaged negative is missing.')
            for kind,slots in gate.SLOTS.items():
                for slot in slots:check(name+'-'+kind+'-'+slot,path,kind,slot,'not_accepted','packaged real unrelated negative')
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.with_suffix('.recognition.json').write_text(json.dumps({'policy':gate.VERSION,'rows':rows},indent=2),encoding='utf8')
        # Native prevalidation and final submission use the exact same normal gate.
        # Worker remains off: durable acceptance is verified, not live processing.
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from src import api,db
        database=str(td/'acceptance.db');submissions={}
        with patch.object(api,'DB_PATH',database),patch.object(api,'UPLOAD_DIR',td/'uploads'),patch.object(api,'RATE_LIMIT_SUBMIT_MAX',500):
            api._RATE_LIMITS.clear()
            with TestClient(api.app) as client:
                result=client.post('/v1/customer/auth/register',json={'email':'native-admission@example.test','name':'Fictional Admission Test','password':'fixture-only-not-an-account-secret'})
                assert result.status_code==201,result.status_code
                headers={'Authorization':'Bearer '+result.json()['token']}
                for kind,names in sets.items():
                    files=[];start=time.perf_counter();key=str(uuid.uuid4())
                    for slot,name in zip(gate.SLOTS[kind],names):
                        path=asset(name);content=path.read_bytes();mime='image/png' if path.suffix=='.png' else 'image/jpeg'
                        reply=client.post('/v1/photos/validate',headers=headers,data={'agent_type':kind,'slot':slot},files={'image':(name,content,mime)})
                        assert reply.status_code==200 and reply.json()['accepted'],(kind,slot,reply.status_code)
                        files.append(('images',(name,content,mime)))
                    count=memo.calls
                    reply=client.post('/v1/cases',headers={**headers,'Idempotency-Key':key},data={'agent_type':kind,'vehicle_registration':'MH12EX1203','photo_slots':list(gate.SLOTS[kind])},files=files)
                    assert reply.status_code==201,(kind,reply.status_code,reply.text)
                    assert memo.calls==count, 'Compatible prevalidation must be reused at final acceptance.'
                    replay=client.post('/v1/cases',headers={**headers,'Idempotency-Key':key},data={'agent_type':kind,'vehicle_registration':'MH12EX1203','photo_slots':list(gate.SLOTS[kind])},files=files)
                    assert replay.status_code==201 and replay.json()==reply.json()
                    conn=db.connect(database)
                    try:
                        case_id=reply.json()['case_id']
                        assert conn.execute('SELECT COUNT(*) FROM images WHERE case_id=?',(case_id,)).fetchone()[0]==len(names)
                        assert conn.execute('SELECT COUNT(*) FROM api_jobs WHERE case_id=?',(case_id,)).fetchone()[0]==1
                        assert conn.execute('SELECT COUNT(*) FROM case_owners WHERE case_id=?',(case_id,)).fetchone()[0]==1
                    finally:conn.close()
                    submissions[kind]={'http':201,'images':len(names),'native_admission':True,'final_additional_embedding_calls':memo.calls-count,'receipt_replay_unchanged':True,'durable_job_and_owner':True,'seconds':round(time.perf_counter()-start,3),'processing':'Not run; isolated worker disabled'}
        result={'policy':gate.VERSION,'new_generation_requests':0,'native_warmup_seconds':round(warmup,3),'rows':rows,'submissions':submissions,
            'feature_reuse':'Actual local CLIP embeddings memoized by normalized file bytes across slots; no simulated classifier scores.',
            'limitations':['Small local corpus is not an accuracy calibration.','A printed page dominated by a large car photograph can still pass; inspect every mismatch above.','Same-car plate crop is genuine; text and front/rear identity are not independently verified.','Dashboard is off: readable mileage remains unverified.','No heavy-truck/bus real negative or independently sourced new camera-photo set.']}
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2),encoding='utf8')
        print(json.dumps({'summary':{'matched':sum(r['matched'] for r in rows),'total':len(rows)},'submissions':submissions}),flush=True)

if __name__=='__main__':main()
