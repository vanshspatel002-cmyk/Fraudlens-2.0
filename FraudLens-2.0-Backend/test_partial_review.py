"""Controlled outage + real persistence/check/report paths. Zero provider HTTP."""
from dataclasses import replace
from io import BytesIO
import json
from types import SimpleNamespace
import pytest
from pypdf import PdfReader
from src import api,db,runtime_store,perception
from src.processing_outcome import summary
from test_pilot_workflow import client,auth
from test_customer_workflow import customer,owned_submit,basis

PIPELINE=api._run_pipeline


class PausedProvider:
    model='offline-fixture';request_profile='offline-fixture';calls=0
    def describe_image(self,*args,**kwargs):
        self.calls+=1
        error=RuntimeError('Controlled pause; no HTTP was attempted.');error.error_category='provider_circuit_open';raise error
    def chat(self,*args,**kwargs):raise AssertionError('No agent HTTP is permitted in this fixture.')


@pytest.fixture
def pipeline(client,monkeypatch):
    from src import llm
    from src.agent import production_policy as pp
    from src.checks import plate_ocr
    real=pp.production_policy
    monkeypatch.setattr(pp,'production_policy',lambda kind:replace(real(kind),check_ids=('internal_duplicate','exif_metadata','entity_graph','plate_ocr')))
    monkeypatch.setattr(plate_ocr,'get_reader',lambda:SimpleNamespace(readtext=lambda path:[([], 'MH12AB1234',.95)]))
    provider=PausedProvider();monkeypatch.setattr(llm,'get_provider',lambda:provider)
    def run(job_id,case_id):
        with runtime_store.connection(api.DB_PATH) as conn:
            job=runtime_store.claim_next(conn);assert job['job_id']==job_id
        with runtime_store.execution(job):PIPELINE(job_id,case_id)
    return run,provider


@pytest.mark.parametrize('kind',['claims','underwriting'])
@pytest.mark.parametrize('action',['approve','reject','request_more_evidence'])
def test_outage_local_checks_pdf_and_human_outcome(client,pipeline,kind,action):
    owner=customer(client);reviewer=auth(client);receipt=owned_submit(client,owner,kind).json();run,provider=pipeline
    run(receipt['job_id'],receipt['case_id'])
    path='/v1/cases/'+receipt['case_id'];job=client.get('/v1/jobs/'+receipt['job_id'],headers=reviewer).json()
    assert job['status']=='completed_partial',job
    assert job['review_summary']['kind']=='provider_partial' and job['failures']
    assert client.get('/v1/jobs/'+receipt['job_id'],headers=owner).json()['failures']==[]
    detail=client.get(path+'/report',headers=reviewer).json()
    checks={f['check_id'] for group in detail['findings_by_category'].values() for f in group}
    assert {'internal_duplicate','exif_metadata','entity_graph','plate_ocr'}<=checks
    assert detail['assessment_presentation']['category'] is None and detail['assessment_presentation']['score'] is None
    calls=provider.calls;version=client.post(path+'/reports/prepare',headers=reviewer).json();url=path+'/reports/'+version['snapshot_id']+'/pdf'
    pdf=client.get(url,headers=reviewer).content
    assert pdf==client.get(url+'?download=true',headers=reviewer).content
    assert 'local checks complete' in ' '.join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages).lower()
    assert client.post(path+'/reports/prepare',headers=reviewer).json()['snapshot_id']==version['snapshot_id']
    assert provider.calls==calls
    public=client.get('/v1/customer/cases/'+receipt['case_id'],headers=owner).json()
    assert public['processingStatus']=='completed_partial' and public['processingDetail']=='Your application is saved and awaiting review.'
    outsider=customer(client,'other@example.test')
    assert client.get('/v1/customer/cases/'+receipt['case_id'],headers=outsider).status_code==404
    assert client.get(url,headers=owner).status_code==401
    payload={**basis(client,receipt['case_id'],reviewer),'action':action,'reason':'Controlled fictional manual review of saved evidence, no AI clearance.',
        'public_message':'Fictional reviewer outcome is recorded.','manual_review_override':True}
    if action=='request_more_evidence':payload['requested_artifacts']=['Diagnostic evidence supporting the declared condition']
    assert client.post(path+'/action',headers=reviewer,json=payload).status_code==200
    updated=client.get('/v1/customer/cases/'+receipt['case_id'],headers=owner).json()
    assert updated['publicNarrative']==payload['public_message']
    assert client.get(url,headers=reviewer).content==pdf
    assert provider.calls==calls


@pytest.mark.parametrize('failure',['missing_file','changed_file','snapshot_storage','database'])
def test_genuine_local_failures_remain_failed(client,pipeline,monkeypatch,failure):
    receipt=owned_submit(client,customer(client)).json();run,provider=pipeline
    if failure in {'missing_file','changed_file'}:
        with runtime_store.connection(api.DB_PATH) as conn:
            from pathlib import Path
            path=Path(db.get_images_for_case(conn,receipt['case_id'])[0].path)
            if failure=='missing_file':path.unlink()
            else:
                from PIL import Image
                Image.new('RGB',(128,128),'blue').save(path)
    elif failure=='snapshot_storage':
        monkeypatch.setattr(api,'_snapshot_report',lambda *a:(_ for _ in ()).throw(OSError('Controlled storage failure')))
    else:
        monkeypatch.setattr(db,'insert_finding',lambda *a:(_ for _ in ()).throw(RuntimeError('Controlled database write failure')))
    run(receipt['job_id'],receipt['case_id'])
    job=client.get('/v1/jobs/'+receipt['job_id'],headers=auth(client)).json()
    assert job['status']=='failed' and job['review_summary']['kind']=='failed'
    if failure in {'missing_file','changed_file'}:assert provider.calls==0


def test_legacy_summary_requires_proof_and_does_not_mutate():
    job=dict(status='failed',stage='needs_review',failures=[dict(stage='perception',error_category='provider_http_error')])
    before=json.dumps(job)
    assert summary(job)['kind']=='failed'
    assert summary(job,durable_result=True,saved_snapshot=True)['historical_derived']
    assert json.dumps(job)==before
    job['failures'].append(dict(stage='snapshot_persistence',error_category='database_error'))
    assert summary(job,durable_result=True,saved_snapshot=True)['kind']=='failed'


def test_cached_observation_contract_is_exact():
    from src.models import PerceptionRecord
    image=SimpleNamespace(content_hash='a'*64);provider=PausedProvider()
    record=PerceptionRecord(content_hash=image.content_hash,source=provider.model,damage_description='Controlled fixture observation',
        raw_response={'cache_contract':perception.perception_cache_contract(image,provider)})
    assert perception.perception_record_compatible(record,image,provider)
    for key in ['image_hash','requested_model','prompt_hash','schema','profile']:
        original=record.raw_response['cache_contract'][key];record.raw_response['cache_contract'][key]='changed'
        assert not perception.perception_record_compatible(record,image,provider)
        record.raw_response['cache_contract'][key]=original


def test_workspace_requires_reviewer(client):
    assert client.get('/v1/workspace').status_code==401
    result=client.get('/v1/workspace',headers=auth(client)).json()
    assert result['schema']=='local_test' and result['examples']==[]


def test_worker_launcher_uses_api_configuration_and_rejects_schema_drift(tmp_path,monkeypatch):
    from scripts import verify_review_configuration as launcher
    env={'FRAUDLENS_PG_SCHEMA':'fraudlens_validation_panel_20261022','GEMINI_MODEL':'api-model',
        'FRAUDLENS_UPLOAD_DIR':str(tmp_path/'outputs/final_presentation/rehearsal/uploads'),
        'FRAUDLENS_THUMB_DIR':str(tmp_path/'outputs/final_presentation/rehearsal/thumbnails')}
    calls=[]
    monkeypatch.setenv('GEMINI_MODEL','stale-shell-model');monkeypatch.setattr(launcher,'ROOT',tmp_path)
    monkeypatch.setattr(launcher,'process_environment',lambda pid:dict(env));monkeypatch.setattr(launcher,'load_pilot_environment',lambda source:source)
    monkeypatch.setattr(launcher.subprocess,'run',lambda *a,**kw:calls.append(kw['env']) or SimpleNamespace(returncode=0))
    monkeypatch.setattr('sys.argv',['verify','--api-process-id','123','--schema','fraudlens_validation_panel_20261022','--start-worker'])
    assert launcher.main()==0 and calls[0]['GEMINI_MODEL']=='api-model' and calls[0]['FRAUDLENS_WORKER_ENABLED']=='1'
    env['FRAUDLENS_PG_SCHEMA']='fraudlens_pilot'
    assert launcher.main()==1 and len(calls)==1
