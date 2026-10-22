"""Offline functional checks. Real CPU model caches; no downloads or providers."""
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageOps,UnidentifiedImageError
import pytest

def test_pixels_exif_hash_and_numeric_search(tmp_path):
 import cv2,imagehash
 image=Image.new('RGB',(320,100),'white');ImageDraw.Draw(image).text((10,10),'MH12EX1203',fill='black')
 exif=image.getexif();exif[274]=6;exif[306]='2026:10:22 12:00:00'
 path=tmp_path/'image.jpg';image.save(path,exif=exif)
 with Image.open(path) as loaded:
  assert loaded.getexif()[306]=='2026:10:22 12:00:00'
  assert ImageOps.exif_transpose(loaded).size==(100,320)
  thumb=loaded.copy();thumb.thumbnail((64,64));assert max(thumb.size)<=64
 a=np.asarray(image);gray=cv2.cvtColor(a,cv2.COLOR_RGB2GRAY);assert cv2.Canny(gray,50,150).shape==(100,320)
 assert imagehash.phash(image)-imagehash.phash(image.resize((160,50)))<10
 assert np.argmax(np.array([[1.,0.],[0.,1.]])@np.array([1.,0.]))==0
 bad=tmp_path/'bad.jpg';bad.write_bytes(b'not an image')
 with pytest.raises(UnidentifiedImageError):Image.open(bad)

def test_solar_and_authentication_primitives():
 from datetime import datetime,timezone
 from src.checks.scene_consistency import solar_position,local_wallclock_to_utc
 import hashlib,secrets,hmac
 value=solar_position(datetime(2026,3,20,12,tzinfo=timezone.utc),0,0)
 assert value is not None and value[1]>85
 instant=local_wallclock_to_utc(datetime(2026,1,1,12),20,73)
 assert (instant.hour,instant.minute)==(6,30)
 salt=secrets.token_bytes(16);a=hashlib.scrypt(b'fictional-password',salt=salt,n=16384,r=8,p=1)
 assert hmac.compare_digest(a,hashlib.scrypt(b'fictional-password',salt=salt,n=16384,r=8,p=1))

def test_actual_clip_and_torchvision(tmp_path,monkeypatch):
 monkeypatch.setenv('HF_HUB_OFFLINE','1');monkeypatch.setenv('TRANSFORMERS_OFFLINE','1')
 import torch,torchvision
 from src.ingest import CLIPEmbedder
 assert torchvision.ops.nms(torch.tensor([[0.,0.,5.,5.],[1.,1.,4.,4.]]),torch.tensor([.9,.5]),.2).tolist()==[0]
 root=Path(__file__).resolve().parent
 first=root/'data/curated/damaged/damaged_0002.jpg'
 second=tmp_path/'different.jpg';Image.new('RGB',(224,224),'white').save(second)
 model=CLIPEmbedder();a=np.array(model.embed(first));b=np.array(model.embed(first));c=np.array(model.embed(second))
 assert a.shape==(512,) and np.isfinite(a).all() and abs(np.linalg.norm(a)-1)<1e-4
 assert np.allclose(a,b,atol=1e-6) and a@b>a@c

def test_actual_ocr_labeled_plate_and_abstention(tmp_path):
 import easyocr
 image=Image.new('RGB',(650,160),'white')
 font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',65)
 ImageDraw.Draw(image).text((20,30),'MH12EX1203',fill='black',font=font)
 reader=easyocr.Reader(['en'],gpu=False,download_enabled=False)
 result=reader.readtext(np.asarray(image),detail=0)
 normalized=''.join(''.join(result).upper().split())
 assert 'MH12EX1203' in normalized
 assert reader.readtext(np.full((160,650,3),255,dtype=np.uint8),detail=0)==[]
