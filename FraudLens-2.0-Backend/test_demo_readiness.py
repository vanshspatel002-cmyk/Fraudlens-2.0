"""Offline request-contract/coverage regressions, never live model validation."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import httpx
import pytest
from src import db, llm, perception
from src.checks.base import CheckContext
from src.checks.plate_ocr import PlateOCRCheck
from src.checks.scene_consistency import SceneConsistencyCheck
from src.models import PerceptionRecord, Verdict


def scene_inputs():
    case = SimpleNamespace(case_id='offline', declared_time=datetime(2025,9,5,6,55,tzinfo=timezone.utc),
        latitude=22.3181, longitude=73.2101, declared_location='Declared place')
    image = SimpleNamespace(image_id='image', content_hash='a'*64, path='offline.jpg')
    record = PerceptionRecord(content_hash=image.content_hash, source='offline-fixture',
        weather_observed='unknown', shadow_direction='none_visible', shadow_length='none',
        lighting='unknown', raw_response={})
    return case, image, record


@pytest.mark.parametrize('weather', [None, {'error':'offline'}, {'precipitation_mm':None}])
def test_scene_missing_context_never_passes(weather):
    case,image,record=scene_inputs()
    ctx=CheckContext(None,case,[image],{image.content_hash:record})
    result=SceneConsistencyCheck()._check_one_image(ctx,image,case.declared_time,None,weather)
    assert result.verdict is Verdict.INCONCLUSIVE
    assert not result.evidence['subchecks_conclusive']


def test_selected_context_pattern_does_not_invent_a_contradiction():
    case,image,record=scene_inputs()
    record.weather_observed='overcast';record.road_condition='dry asphalt with debris';record.lighting='daylight'
    ctx=CheckContext(None,case,[image],{image.content_hash:record})
    result=SceneConsistencyCheck()._check_one_image(ctx,image,case.declared_time,(85.51,7.08),
        {'precipitation_mm':33.9,'hourly_precipitation_mm':{'6':1.2},'cloudcover_mean_pct':100})
    assert result.verdict is Verdict.PASS
    assert result.evidence['shadow_direction_status']=='not visible in image'
    assert not result.evidence['subchecks_fired']


@pytest.mark.parametrize('observations,registration,status,comparison,verdict',[
    ([], 'MH12AB1234', 'no_text_detected', None, Verdict.INCONCLUSIVE),
    ([(None,'unreadable lettering',.9)], 'MH12AB1234', 'no_plate_candidate', None, Verdict.INCONCLUSIVE),
    ([(None,'MH12AB1234',.95)], 'MH12AB1234', 'candidate_read', 'match', Verdict.PASS),
    ([(None,'MH12AB1234',.95)], 'MH12AB9999', 'candidate_read', 'mismatch', Verdict.CONCERN),
    ([(None,'MH12AB1234',.2)], 'MH12AB9999', 'candidate_read', 'low_confidence_mismatch', Verdict.INCONCLUSIVE),
    ([(None,'MH12AB1234',.9)], None, 'candidate_read', 'declaration_missing', Verdict.INCONCLUSIVE),
])
def test_ocr_outcomes_are_distinct(observations,registration,status,comparison,verdict):
    case,image,_=scene_inputs();case.vehicle_registration=registration
    ctx=CheckContext(None,case,[image],{})
    reader=SimpleNamespace(readtext=lambda path:observations)
    result=PlateOCRCheck()._check_one_image(ctx,image,reader,.5)
    assert result.verdict is verdict
    assert result.evidence['ocr_status']==status
    assert result.evidence.get('comparison_status')==comparison


def test_ocr_engine_failure_is_distinct_from_no_text():
    case,image,_=scene_inputs();case.vehicle_registration='MH12AB1234'
    result=PlateOCRCheck()._check_one_image(CheckContext(None,case,[image],{}),image,None,.5)
    assert result.evidence['ocr_status']=='engine_unavailable'


def test_gemini_three_defaults_and_separate_cache_protocol():
    for model,temp,suffix in [('gemini-3.5-flash',None,'_gemini3_defaults_v2'),('gemini-2.5-flash',0,'')]:
        provider=llm.GeminiProvider(model=model,api_key='offline-placeholder')
        assert provider._config().temperature==temp
        assert provider._config().automatic_function_calling.disable
        assert provider._request_cache_suffix==suffix
        provider.close()


def test_sdk_serializes_vision_and_chat_without_network(tmp_path,monkeypatch):
    from google import genai
    from google.genai import types
    from PIL import Image
    requests=[]
    def handle(request):
        requests.append((request.url.path,json.loads(request.content)))
        return httpx.Response(200,json={'candidates':[{'content':{'role':'model','parts':[{'text':'offline test'}]}}]})
    transport=httpx.Client(transport=httpx.MockTransport(handle))
    client=genai.Client(api_key='offline-placeholder',http_options=types.HttpOptions(
        httpx_client=transport,timeout=60000,retry_options=types.HttpRetryOptions(attempts=1)))
    provider=llm.GeminiProvider(api_key='offline-placeholder')
    # This isolated transport is the only execution path; no ledger is opened.
    monkeypatch.setattr(provider,'_call_rotating',lambda call,**kw:call(client))
    path=tmp_path/'photo.png';Image.new('RGB',(8,8),'blue').save(path)
    try:
        provider.describe_image(str(path),'Describe visible observations only')
        provider.chat([{'role':'system','content':'Offline test instructions'}, {'role':'user','content':'Review recorded findings'}])
        assert len(requests)==2
        assert all(path.endswith(':generateContent') and '/v1beta/' in path for path,_ in requests)
        assert requests[0][1]['contents'][0]['parts'][1]['inlineData']['mimeType']=='image/png'
        assert all('temperature' not in body['generationConfig'] for _,body in requests)
    finally:
        client.close();provider.close();transport.close()


@pytest.mark.parametrize('source,cached',[('fresh_provider',False),('request_cache',True)])
def test_perception_provenance_distinguishes_request_cache(monkeypatch,source,cached):
    _,image,_=scene_inputs();provenance={}
    monkeypatch.setattr(db,'get_perception',lambda *a:None)
    monkeypatch.setattr(db,'save_perception',lambda *a:None)
    payload={key:'unknown' for key in perception._EXPECTED_FIELDS}
    payload.update(damage_severity='none',shadow_direction='none_visible',shadow_length='none',plate_text='',anomaly_notes='')
    provider=SimpleNamespace(model='offline',describe_image=lambda *a,**kw:SimpleNamespace(text=json.dumps(payload),cached=cached))
    result=perception.perceive_image(None,image,provider,provenance=provenance)
    assert not result.raw_response.get('error')
    assert provenance['source']==source


def test_perception_cache_provenance_never_calls_provider(monkeypatch):
    _,image,record=scene_inputs();provenance={}
    monkeypatch.setattr(db,'get_perception',lambda *a:record)
    assert perception.perceive_image(None,image,object(),provenance=provenance) is record
    assert provenance['source']=='perception_cache'


def test_concurrent_reader_initialization_never_returns_half_loaded_state(monkeypatch):
    import concurrent.futures
    import sys
    import time
    from src.checks import plate_ocr
    calls=[];reader=object()
    def initialize(*a,**kw):
        calls.append(1);time.sleep(.03);return reader
    monkeypatch.setattr(plate_ocr,'_reader_attempted',False)
    monkeypatch.setattr(plate_ocr,'_reader',None)
    monkeypatch.setattr(plate_ocr,'_reader_error',None)
    monkeypatch.setitem(sys.modules,'easyocr',SimpleNamespace(Reader=initialize))
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(set_num_threads=lambda n:None))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:plate_ocr.get_reader(),range(4)))
    assert calls==[1] and all(value is reader for value in results)
