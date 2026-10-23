"""Initial application slots; local inference only, no durable writes or LLM.

Cache reuse is bound to session/customer, immutable bytes, slot and policy.
Missing/expired entries always revalidate. No client assertion is trusted.
"""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import threading
import time
import numpy as np
from PIL import Image,ImageOps
from . import vehicle_gate

VERSION='initial-photo-admission-2026-10-22-v3'
# Local v1 smoke: a printed-car document won by .0036 and severe blur by
# .0187. The .02 abstention band excludes both without lowering the existing
# absolute floor. This is a conservative operating point, not accuracy calibration.
MIN_SUBJECT_MARGIN=.020
SLOTS={
 'claims':('vehicle_overview','front_registration','damage_overview','damage_closeup'),
 'underwriting':('front_left','front_right','rear_left','rear_right','odometer','registration_plate'),
}
KINDS={'front_registration':'plate','registration_plate':'plate','odometer':'odometer',
       'damage_closeup':'damage','damage_overview':'damage'}
PROMPTS={
 'exterior':('a photograph of a passenger car exterior','a photograph of an SUV or passenger van',
  'a photograph of the front of a passenger car','a photograph of the rear of a passenger car',
  'a photograph of the side of a passenger car','a photograph of a parked sedan hatchback or station wagon',
  'a photograph of an off road passenger SUV','a photograph of a car driving on a road',
  'a photograph of a civilian pickup vehicle with a passenger cabin'),
 'damage':('a close up photograph of a damaged car body panel bumper or wheel','a photograph of scratches and dents on a car',
           'a close up photograph of a passenger car part or interior door panel',
           'a photograph of a passenger car interior showing the dashboard and seats',
           'a close up photograph of the engine compartment of a passenger car'),
 'plate':('a photograph of a registration license plate mounted on a car','a close up photograph of a car number plate and bumper',
          'a photograph of a passenger car front showing the bumper and number plate mounting area',
          'a front three quarter photograph of a passenger car',
          'a rear photograph of a passenger car with a number plate',
          'a photograph of a car with a license plate',
          'a front view of a parked sedan with a mounted license plate'),
 'odometer':('a photograph of a car dashboard instrument cluster odometer','a close up photograph of a vehicle mileage display behind the steering wheel'),
}
NEGATIVES=('a photograph of a motorcycle scooter or bicycle','a photograph of a truck bus or heavy machinery',
 'a photograph of an animal','a photograph of a person without a vehicle','a photograph of food',
 'a photograph of a landscape without a vehicle','a document invoice or printed picture of a car',
 'a screenshot or computer screen showing a car','an unrelated object or household item')
_lock=threading.Lock();_inference=threading.BoundedSemaphore(1)
_cache=OrderedDict();_texts={};TTL=600;MAX_CACHE=256

class InvalidPhoto(ValueError):pass
class ValidatorUnavailable(RuntimeError):pass

def readable_detail(category,texts):
 if category=='plate':
  from .checks.plate_ocr import coerce_to_plate
  return any(coerce_to_plate(text,observed_prefix=True) for text in texts+[''.join(texts)])
 # Unlabelled dashboard numbers could be speed/RPM, not mileage. Require
 # recorded mileage context; this conservative OCR heuristic is not metrology.
 joined=' '.join(texts).lower()
 return bool(re.search(r'(?:odo(?:meter)?|mileage)\s*[:\-]?\s*\d{3,7}|\d{4,7}(?:[.,]\d)?\s*(?:km|miles?|mi)\b(?!\s*/\s*h)',joined))

@dataclass
class Admission:
 slot:str
 state:str
 reason:str
 content_hash:str
 normalized_hash:str
 embedding:list[float]|None=None
 scores:dict|None=None
 cached:bool=False
 def to_dict(self):
  return dict(slot=self.slot,state=self.state,accepted=self.state=='accepted',reason=self.reason,
    validation_version=VERSION,content_hash=self.content_hash,normalized_hash=self.normalized_hash,
    scores=self.scores,cached=self.cached)

def assignments(kind,slots,count):
 expected=SLOTS.get(kind)
 if not expected:raise InvalidPhoto('Unknown case type.')
 if count!=len(expected):raise InvalidPhoto(f'{kind.title()} require exactly {len(expected)} photographs.')
 if len(slots)!=count or len(set(slots))!=count or set(slots)!=set(expected):
  raise InvalidPhoto('Provide each required slot exactly once, paired in order with its image; missing, duplicate or extra slots are invalid.')

def decode(content,mime,path):
 if not content or len(content)>5*1024*1024:raise InvalidPhoto('Each image must be nonempty and at most 5 MB.')
 from io import BytesIO
 try:
  with Image.open(BytesIO(content)) as image:
   expected={'JPEG':'image/jpeg','PNG':'image/png','WEBP':'image/webp'}.get(image.format)
   if expected is None or mime!=expected:raise InvalidPhoto('File content must match its JPEG, PNG or WebP MIME type.')
   if min(image.size)<64 or image.width*image.height>25_000_000:raise InvalidPhoto('Retake at least 64 pixels on each side, up to 25 megapixels.')
   image.load();normalized=ImageOps.exif_transpose(image).convert('RGB')
   if all(low==high for low,high in normalized.getextrema()):raise InvalidPhoto('Blank image: replace it with a clear vehicle photograph.')
   # Conservative severe-blur floor measured on development/held-out local
   # cars, damage and real dashboard images. Not a universal sharpness metric.
   gray=normalized.convert('L');gray.thumbnail((512,512));a=np.asarray(gray,dtype=float)
   lap=4*a[1:-1,1:-1]-a[:-2,1:-1]-a[2:,1:-1]-a[1:-1,:-2]-a[1:-1,2:]
   if float(lap.var())<5:
    raise InvalidPhoto('Image is too blurred or lacks visible detail. Retake in focus; relevance could not be assessed reliably.')
   digest=hashlib.sha256(str(normalized.size).encode()+normalized.tobytes()).hexdigest()
   normalized.save(path,format='PNG')
   return digest
 except InvalidPhoto:raise
 except Exception:raise InvalidPhoto('Image cannot be decoded. Retake or export a valid JPEG, PNG or WebP.') from None

def infer(path,slot):
 category=KINDS.get(slot,'exterior');embedder=vehicle_gate._default_embedder
 try:
  vector=np.asarray(embedder.embed(path),dtype=float)
  if category not in _texts:
   _texts[category]=np.asarray(embedder.embed_texts(PROMPTS[category]+NEGATIVES),dtype=float)
  sims=_texts[category]@vector;n=len(PROMPTS[category]);positive=float(max(sims[:n]));negative=float(max(sims[n:]))
  if not np.isfinite(vector).all() or not np.isfinite(sims).all():raise ValueError()
 except Exception:raise ValidatorUnavailable('Local vehicle validator is unavailable; retry later.') from None
 scores=dict(subject_similarity=positive,competing_similarity=negative,subject_margin=positive-negative,
    threshold=vehicle_gate.VEHICLE_SCORE_THRESHOLD,minimum_margin=MIN_SUBJECT_MARGIN,
    rule='Supported slot subject must meet the existing similarity floor and exceed competing categories by the documented abstention margin; not a probability.')
 if positive<vehicle_gate.VEHICLE_SCORE_THRESHOLD or positive-negative<MIN_SUBJECT_MARGIN:
  return ('rejected' if negative-positive>MIN_SUBJECT_MARGIN else 'needs_replacement'),'Retake this slot: a supported passenger vehicle or the required mounted detail could not be established.',vector.tolist(),scores
 if category in {'plate','odometer'}:
  # Admission establishes relevance, not independent text/identity verification.
  # Real OCR runs once in assessment. An unreadable legitimate mounted detail
  # remains an evidence gap rather than a fabricated non-vehicle verdict.
  scores.update(quality_check='extraction_deferred_to_assessment',quality_readable=None,
                identity_verified=False,slot_label_verified=False)
  return 'accepted','Relevant vehicle detail accepted; text is not independently verified. Keep the '+('mounted plate sharp and include surrounding bodywork.' if category=='plate' else 'mileage and ODO/km/miles label sharp, with dashboard context.'),vector.tolist(),scores
 return 'accepted','Accepted for this slot. Identity, authenticity and capture date remain unverified.',vector.tolist(),scores

def warmup(include_ocr=True):
 """Prepare the shared slot model/texts and OCR during opted-in API startup."""
 with _inference:
  embedder=vehicle_gate._default_embedder;embedder._ensure_loaded()
  for category in PROMPTS:
   if category not in _texts:
    _texts[category]=np.asarray(embedder.embed_texts(PROMPTS[category]+NEGATIVES),dtype=float)
  if include_ocr:
   from .checks.plate_ocr import get_reader
   return get_reader() is not None
  return True

def validate(content,mime,kind,slot,actor,directory):
 if kind not in SLOTS or slot not in SLOTS[kind]:raise InvalidPhoto('Invalid photo slot for this case type.')
 path=Path(directory)/'normalized.png';normalized=decode(content,mime,path)
 raw=hashlib.sha256(content).hexdigest();key=(actor,kind,slot,raw,VERSION)
 with _lock:
  entry=_cache.get(key)
  if entry and time.monotonic()-entry[0]<TTL:
   result=Admission(**{**entry[1].__dict__,'cached':True});_cache.move_to_end(key);return result
 if not _inference.acquire(timeout=.1):raise ValidatorUnavailable('Vehicle validator is busy. Retry this photograph shortly.')
 try:state,reason,embedding,scores=infer(path,slot)
 finally:_inference.release()
 result=Admission(slot,state,reason,raw,normalized,embedding,scores)
 with _lock:
  _cache[key]=(time.monotonic(),result);_cache.move_to_end(key)
  while len(_cache)>MAX_CACHE:_cache.popitem(last=False)
 return result

def actor_key(account,authorization):
 return (account['customer_id'] if account else 'anonymous',hashlib.sha256((authorization or '').encode()).hexdigest())
