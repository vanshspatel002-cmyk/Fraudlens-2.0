"""Real CPU-only slot classifier smoke. Existing authorized/local fixtures only.

No provider, database or historical case processing. Missing coverage is reported.
"""
import os,sys,json,time,tempfile
from pathlib import Path
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PIL import Image,ImageDraw,ImageFilter
from src import photo_admission as gate

def main():
 output=ROOT/'outputs/photo_admission';output.mkdir(parents=True,exist_ok=True)
 import skimage.data
 local=Path(skimage.data.__file__).parent
 examples=[('normal-car-'+str(i),ROOT/f'data/curated/whole/whole_{i:04}.jpg','vehicle_overview','existing corpus passenger-vehicle candidate') for i in range(1,7)]
 examples += [('damage-'+str(i),path,'damage_closeup','existing corpus damage photograph') for i,path in enumerate(sorted((ROOT/'data/curated/damaged').glob('*.jpg'))[:4],1)]
 examples += [(name,local/file,'vehicle_overview','packaged real negative') for name,file in [('person','astronaut.png'),('animal','chelsea.png'),('food','coffee.png'),('scenery','grass.png'),('motorcycle','motorcycle_left.png'),('document','page.png'),('object','coins.png')]]
 rows=[]
 with tempfile.TemporaryDirectory() as td:
  td=Path(td)
  original=ROOT/'data/curated/whole/whole_0001.jpg'
  with Image.open(original) as image:
   image.filter(ImageFilter.GaussianBlur(12)).save(td/'blur.jpg')
   paper=Image.new('RGB',(1000,1200),'white');pic=image.copy();pic.thumbnail((700,500));paper.paste(pic,(100,250));ImageDraw.Draw(paper).text((50,50),'VEHICLE INSURANCE DOCUMENT — FICTIONAL TEST',fill='black');paper.save(td/'paper.png')
   screen=Image.new('RGB',(1000,700),'#202124');screen.paste(pic,(100,120));ImageDraw.Draw(screen).text((20,20),'Browser screenshot / fictional local control',fill='white');screen.save(td/'screen.png')
  Image.new('RGB',(128,128),'white').save(td/'blank.png')
  Image.new('RGB',(16,16),'red').save(td/'tiny.png');(td/'bad.jpg').write_bytes(b'not a photo')
  examples += [(name,td/file,'vehicle_overview','authored degradation/negative control') for name,file in [('blurry','blur.jpg'),('printed-car-document','paper.png'),('screenshot-car','screen.png'),('blank','blank.png'),('tiny','tiny.png'),('corrupt','bad.jpg')]]
  start=time.perf_counter()
  from src import vehicle_gate
  vehicle_gate._default_embedder._ensure_loaded()
  cold=time.perf_counter()-start
  for name,path,slot,basis in examples:
   if not path.exists():rows.append(dict(name=name,basis=basis,state='fixture_unavailable'));continue
   with tempfile.TemporaryDirectory() as directory:
    started=time.perf_counter()
    try:
     mime={'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png'}[path.suffix[1:].lower()]
     result=gate.validate(path.read_bytes(),mime,'claims',slot,('local-smoke',name),directory)
     record=result.to_dict()
    except gate.InvalidPhoto as error:record={'state':'rejected','reason':str(error)}
    except gate.ValidatorUnavailable as error:record={'state':'unavailable','reason':str(error)}
    rows.append(dict(name=name,basis=basis,seconds=round(time.perf_counter()-started,3),**record))
  # Duplicate/identity and slot-specialty capability are separate from model scores.
  coverage={'plate':'No inspected legitimate mounted-plate fixture supplied; OCR/parser controlled tests only.',
    'odometer':'No inspected legitimate dashboard-mileage fixture supplied; explicit retake on unreadable text.',
    'same_vehicle':'Not established. Neither slot labels nor embeddings authenticate identity.',
    'blur':'No independently calibrated universal blur cutoff; unreadable OCR slots abstain. Exterior blur reliability remains a limitation.'}
  # Throughput benchmarks only: unrelated cars assigned to generic exterior
  # slots, not a same-vehicle required-photo set or accepted application.
  batches={}
  for count in [4,6]:
   start=time.perf_counter();states=[]
   for i in range(count):
    with tempfile.TemporaryDirectory() as directory:
     states.append(gate.validate(examples[i][1].read_bytes(),'image/jpeg','claims','vehicle_overview',('batch',str(count)+str(i)),directory).state)
   batches[str(count)]={'seconds':round(time.perf_counter()-start,3),'states':states,'basis':'Warm serial local inference throughput, heterogeneous generic exterior inputs; not initial acceptance'}
  payload={'cold_clip_ready_seconds':round(cold,3),'version':gate.VERSION,'new_gemini_calls':0,'examples':rows,'batch_throughput':batches,'limitations':coverage}
 (output/'real-local-results.json').write_text(json.dumps(payload,indent=2))
 print(json.dumps(payload,indent=2))

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--warmup-only',action='store_true',help='Measure complete local CLIP, slot-text and OCR readiness without image/provider requests.')
 args=parser.parse_args()
 if args.warmup_only:
  start=time.perf_counter();ready=gate.warmup()
  result=dict(version=gate.VERSION,cold_full_validator_seconds=round(time.perf_counter()-start,3),
    clip_and_slot_texts_ready=True,ocr_ready=ready,new_gemini_calls=0)
  output=ROOT/'outputs/photo_admission/startup-warmup.json';output.parent.mkdir(parents=True,exist_ok=True)
  output.write_text(json.dumps(result,indent=2));print(json.dumps(result))
 else:main()
