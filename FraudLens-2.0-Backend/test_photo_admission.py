"""Deterministic local admission contracts; semantic outputs are controlled."""
import io,time
import pytest
from PIL import Image,ImageDraw,PngImagePlugin
from test_pilot_workflow import client,initial_files,photo
from test_customer_workflow import customer
from src import api,db,photo_admission as gate

def send(client,kind='claims',count=None,slots=None,files=None,headers=None,**extra):
 slots=list(gate.SLOTS[kind]) if slots is None else slots
 files=initial_files(kind) if files is None else files
 if count is not None:
  files=(files+[('images',('extra.png',photo('pink'),'image/png'))]*3)[:count]
 return client.post('/v1/cases',data={'agent_type':kind,'vehicle_registration':'MH12EX1203','photo_slots':slots,**extra},
    files=files or None,headers=headers or {})

def counts():
 conn=db.connect(api.DB_PATH)
 try:return tuple(conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ['cases','api_jobs','case_owners','submission_receipts'])
 finally:conn.close()

@pytest.mark.parametrize('kind,count',[(kind,n) for kind,required in [('claims',4),('underwriting',6)] for n in range(required+2) if n!=required])
def test_exact_counts_rejected_without_persistence(client,kind,count):
 before=counts();response=send(client,kind,count=count)
 assert response.status_code==422 and response.json()['code']=='INVALID_PHOTO_SLOTS'
 assert counts()==before

@pytest.mark.parametrize('kind',['claims','underwriting'])
def test_all_valid_distinct_slots_accepted(client,kind):
 response=send(client,kind);assert response.status_code==201,response.text
 assert response.json()['images_received']==len(gate.SLOTS[kind])
 assert counts()[:2]==(1,1)

@pytest.mark.parametrize('slots',[[],['vehicle_overview']*4,['vehicle_overview','front_registration','damage_overview','wrong']])
def test_ambiguous_assignments_rejected(client,slots):
 before=counts();assert send(client,slots=slots).status_code==422;assert counts()==before

def test_one_nonvehicle_rejects_entire_batch(client,monkeypatch):
 def infer(path,slot):return ('rejected' if slot=='damage_closeup' else 'accepted','Controlled content result',[1.,0.],{})
 monkeypatch.setattr(gate,'infer',infer)
 before=counts();response=send(client,valid='true')
 assert response.status_code==422 and response.json()['details'][0]['field']=='damage_closeup'
 assert counts()==before

def test_duplicate_normalized_content_not_filename(client):
 files=initial_files();meta=PngImagePlugin.PngInfo();meta.add_text('author','fictional')
 image=Image.open(io.BytesIO(files[0][1][1]));buffer=io.BytesIO();image.save(buffer,format='PNG',pnginfo=meta)
 files[1]=('images',('renamed.png',buffer.getvalue(),'image/png'))
 assert send(client,files=files).status_code==422
 assert counts()==(0,0,0,0)

@pytest.mark.parametrize('content,mime',[(b'not an image','image/jpeg'),(photo(),'image/jpeg'),(photo(),'application/octet-stream')])
def test_content_and_mime_are_verified(client,content,mime):
 files=initial_files();files[2]=('images',('renamed.jpg',content,mime))
 response=send(client,files=files);assert response.status_code==422
 assert counts()==(0,0,0,0)

def test_outage_is_retryable_not_rejection(client,monkeypatch):
 monkeypatch.setattr(gate,'infer',lambda *args:(_ for _ in ()).throw(gate.ValidatorUnavailable('Local validator unavailable; retry.')))
 response=send(client);assert response.status_code==503 and response.json()['code']=='VALIDATOR_UNAVAILABLE'
 assert counts()==(0,0,0,0)

def test_prevalidation_requires_auth_and_binds_session_bytes_slot_and_version(client,monkeypatch):
 calls=[]
 def infer(path,slot):calls.append(slot);return 'accepted','Controlled fixture',[1.,0.],{}
 monkeypatch.setattr(gate,'infer',infer)
 def pre(headers,slot='vehicle_overview',content=None):return client.post('/v1/photos/validate',headers=headers,
    data={'agent_type':'claims','slot':slot},files={'image':('photo.png',content or photo(),'image/png')})
 assert pre({}).status_code==401
 owner=customer(client);assert pre(owner).json()['state']=='accepted';assert pre(owner).json()['cached']
 assert len(calls)==1
 assert pre(owner,'damage_overview').status_code==200;assert len(calls)==2
 other=customer(client,'outsider@example.test');assert pre(other).status_code==200;assert len(calls)==3
 assert pre(owner,content=photo('blue')).status_code==200;assert len(calls)==4
 monkeypatch.setattr(gate,'VERSION','controlled-new-version');assert pre(owner).status_code==200;assert len(calls)==5
 assert send(client,headers=owner).status_code==201
 # A client has no accepted-token field to forge. Final validation recomputes
 # all bindings, even after a prevalidation response was accepted in the UI.
 assert len(calls)==8

def test_replaced_bytes_cannot_borrow_accepted_result(client,monkeypatch):
 owner=customer(client)
 assert client.post('/v1/photos/validate',headers=owner,data={'agent_type':'claims','slot':'vehicle_overview'},
    files={'image':('photo.png',photo(),'image/png')}).status_code==200
 gate._cache.clear()
 monkeypatch.setattr(gate,'infer',lambda *args:('rejected','Changed image is not a car',[1.,0.],{}))
 response=send(client,headers=owner,accepted='true',validation_version=gate.VERSION)
 assert response.status_code==422 and counts()==(0,0,0,0)

def test_ocr_slot_abstains_and_optional_whole_vehicle_not_required(monkeypatch,tmp_path):
 from src import vehicle_gate
 from src.checks import plate_ocr
 class Embedder:
  def embed(self,path):return [1.,0.]
  def embed_texts(self,prompts):return [[1.,0.]]*2+[[0.,1.]]*len(gate.NEGATIVES)
 monkeypatch.setattr(vehicle_gate,'_default_embedder',Embedder());monkeypatch.setattr(gate,'_texts',{})
 monkeypatch.setattr(plate_ocr,'get_reader',lambda:type('Reader',(),{'readtext':lambda *a:[]})())
 assert gate.infer(tmp_path/'unused','front_registration')[0]=='needs_replacement'
 assert gate.infer(tmp_path/'unused','odometer')[0]=='needs_replacement'
 assert gate.infer(tmp_path/'unused','damage_closeup')[0]=='accepted'

def test_cache_expiry_and_orientation(monkeypatch,tmp_path):
 monkeypatch.setattr(gate,'infer',lambda *args:('accepted','Controlled',[1.,0.],{}))
 a=gate.validate(photo(),'image/png','claims','damage_closeup',('fixture','session'),tmp_path)
 assert not a.cached
 now=time.monotonic();monkeypatch.setattr(gate.time,'monotonic',lambda:now+gate.TTL+1)
 assert not gate.validate(photo(),'image/png','claims','damage_closeup',('fixture','session'),tmp_path).cached
 image=Image.new('RGB',(128,96),'blue');ImageDraw.Draw(image).rectangle((1,1,50,50),fill='white')
 exif=image.getexif();exif[274]=6;out=io.BytesIO();image.save(out,format='JPEG',exif=exif)
 gate.decode(out.getvalue(),'image/jpeg',tmp_path/'oriented.png')
 assert Image.open(tmp_path/'oriented.png').size==(96,128)

@pytest.mark.parametrize('margin,state',[(.0036,'needs_replacement'),(.0187,'needs_replacement'),(.021,'accepted'),(-.07,'rejected')])
def test_measured_abstention_band(monkeypatch,tmp_path,margin,state):
 from src import vehicle_gate
 import numpy as np
 class Embedder:
  def embed(self,path):return [1.,0.]
 monkeypatch.setattr(vehicle_gate,'_default_embedder',Embedder())
 monkeypatch.setattr(gate,'_texts',{'exterior':np.array([[.25,0],[.25,0]]+[[.25-margin,0]]*len(gate.NEGATIVES))})
 assert gate.infer(tmp_path/'not-opened','vehicle_overview')[0]==state

@pytest.mark.parametrize('texts,expected',[(['ODO 123456'],True),(['123456 km'],True),(['120 km/h'],False),(['RPM 4000'],False),(['123456'],False),([],False)])
def test_odometer_requires_readable_mileage_context(texts,expected):
 assert gate.readable_detail('odometer',texts)==expected

def test_warmup_reuses_one_model_and_slot_text_cache(monkeypatch):
 from src import vehicle_gate
 from src.checks import plate_ocr
 calls=[]
 class Embedder:
  def _ensure_loaded(self):calls.append('same-model')
  def embed_texts(self,prompts):calls.append(len(prompts));return [[1.,0.]]*len(prompts)
 monkeypatch.setattr(vehicle_gate,'_default_embedder',Embedder())
 monkeypatch.setattr(gate,'_texts',{})
 monkeypatch.setattr(plate_ocr,'get_reader',lambda:object())
 assert gate.warmup() and gate.warmup()
 assert calls.count('same-model')==2 and sum(isinstance(v,int) for v in calls)==len(gate.PROMPTS)

def test_successful_receipt_replay_does_not_revalidate_or_enqueue_again(client,monkeypatch):
 import uuid
 headers={'Idempotency-Key':str(uuid.uuid4())}
 first=send(client,headers=headers);assert first.status_code==201
 before=counts()
 monkeypatch.setattr(gate,'validate',lambda *args:(_ for _ in ()).throw(AssertionError('Committed receipt replay must not infer')))
 second=send(client,headers=headers)
 assert second.status_code==201 and second.json()==first.json() and counts()==before

def test_concurrent_validator_busy_is_unavailable(client):
 gate._inference.acquire()
 try:
  response=send(client)
  assert response.status_code==503 and counts()==(0,0,0,0)
 finally:gate._inference.release()

@pytest.mark.parametrize('kind',['claims','underwriting'])
def test_all_prevalidated_files_reused_and_durable_acceptance_timed(client,monkeypatch,kind):
 import json
 from pathlib import Path
 calls=[]
 monkeypatch.setattr(gate,'infer',lambda path,slot:(calls.append(slot) or ('accepted','Controlled fixture',[1.,0.],{})))
 owner=customer(client);files=initial_files(kind)
 start=time.perf_counter()
 for slot,(_,(_,content,mime)) in zip(gate.SLOTS[kind],files):
  response=client.post('/v1/photos/validate',headers=owner,data={'agent_type':kind,'slot':slot},files={'image':('photo.png',content,mime)})
  assert response.status_code==200 and response.json()['state']=='accepted'
 validation=time.perf_counter()-start;before=len(calls);start=time.perf_counter()
 response=send(client,kind,headers=owner)
 elapsed=time.perf_counter()-start
 assert response.status_code==201 and len(calls)==before==len(gate.SLOTS[kind])
 output=Path(__file__).parent/'outputs/photo_admission/controlled-timings.json';output.parent.mkdir(parents=True,exist_ok=True)
 data=json.loads(output.read_text()) if output.exists() else {}
 data[kind]=dict(source='Controlled semantic model, actual isolated SQLite/API persistence',prevalidation_seconds=validation,
   durable_acceptance_seconds=elapsed,initial_files=before,final_model_calls=0)
 output.write_text(json.dumps(data,indent=2))
