"""Isolated workflow contracts; controlled image embeddings, no live AI claims."""
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from test_pilot_workflow import client, auth, photo, submit,initial_files
from src.photo_admission import SLOTS
from src import api, db, runtime_store


def customer(client, email='alex.sample@example.com'):
    response = client.post('/v1/customer/auth/register', json={
        'email': email, 'password': 'fictional-password-2026', 'name': 'Alex Sample'})
    assert response.status_code == 201, response.text
    return {'Authorization': 'Bearer '+response.json()['token']}


def owned_submit(client, headers, kind='claims', key=None):
    return client.post('/v1/cases', headers={**headers, 'Idempotency-Key': key or str(uuid.uuid4())},
        data={'agent_type': kind, 'vehicle_registration': 'MH12AB1234', 'policy_number':'SAMPLE-POLICY',
              'person_name':'Alex Sample', 'person_contact':'alex.sample@example.com',
              'declaration_notes':'Fictional applicant statement; no model findings.','photo_slots':list(SLOTS[kind])},
        files=initial_files(kind))


def finish(case_id, status='completed'):
    with runtime_store.connection(api.DB_PATH) as conn:
        job = runtime_store.latest_job(conn,case_id)
        job.update(status=status,stage='complete' if status=='completed' else 'needs_review')
        runtime_store.save_job(conn,job)


def basis(client, case_id, reviewer):
    detail=client.get('/v1/cases/'+case_id,headers=reviewer).json()
    return {'expected_revision':detail['review_revision'],
            'expected_run_id':detail['processing']['job_id'],
            'expected_evidence_ids':[image['image_id'] for image in detail['images']]}


def test_registration_password_session_expiry_and_independent_roles(client):
    owner=customer(client); reviewer=auth(client)
    assert client.get('/v1/customer/auth/session',headers=reviewer).status_code==401
    assert client.get('/v1/auth/session',headers=owner).status_code==401
    assert client.get('/v1/cases',headers=owner).status_code==401
    assert client.post('/v1/customer/auth/login',json={'email':'alex.sample@example.com','password':'wrong'}).status_code==401
    assert client.post('/v1/customer/auth/register',json={'name':'Sample','email':'bad','password':'short'}).status_code==422
    with runtime_store.connection(api.DB_PATH) as conn:
        row=conn.execute('SELECT password_hash FROM customer_accounts').fetchone()
        assert row[0].startswith('pbkdf2_sha256$') and 'fictional-password' not in row[0]
        conn.execute('UPDATE customer_sessions SET expires_at=?',(time.time()-1,))
    assert client.get('/v1/customer/auth/session',headers=owner).status_code==401
    assert client.get('/v1/auth/session',headers=reviewer).status_code==200
    logged=client.post('/v1/customer/auth/login',json={'email':'alex.sample@example.com','password':'fictional-password-2026'})
    assert logged.status_code==200
    owner={'Authorization':'Bearer '+logged.json()['token']}
    assert client.post('/v1/auth/logout',headers=reviewer).status_code==200
    assert client.get('/v1/customer/auth/session',headers=owner).status_code==200
    assert client.post('/v1/customer/auth/logout',headers=owner).status_code==200
    assert client.get('/v1/customer/auth/session',headers=owner).status_code==401


@pytest.mark.parametrize('kind',['claims','underwriting'])
@pytest.mark.parametrize('action',['approve','reject'])
def test_owned_workflow_decision_visibility_and_privacy(client,kind,action):
    owner=customer(client); other=customer(client,'other.sample@example.com'); reviewer=auth(client)
    response=owned_submit(client,owner,kind); assert response.status_code==201,response.text
    receipt=response.json(); case_id=receipt['case_id']
    listed=client.get('/v1/customer/cases',headers=owner).json()['items']
    assert len(listed)==1 and listed[0]['id']==case_id and listed[0]['processingStatus']=='queued' and listed[0]['outcome'] is None
    assert client.get('/v1/customer/cases',headers=other).json()['items']==[]
    url='/v1/customer/cases/'+case_id
    assert client.get(url).status_code==401
    assert client.get(url,headers=other).status_code==404
    params={'case_id':case_id,'policy_number':'SAMPLE-POLICY'}
    assert client.get('/v1/track',params=params).status_code==401
    assert client.get('/v1/track',params=params,headers=other).status_code==404
    assert client.get('/v1/track',params=params,headers=owner).status_code==200
    assert client.get('/v1/track',params=params,headers={'X-Applicant-Token':receipt['applicant_token']}).status_code==200
    detail=client.get(url,headers=owner).json(); image_id=detail['images'][0]['id']
    assert detail['application']['declaration_notes'].startswith('Fictional') and detail['timeline']
    assert client.get('/v1/customer/images/'+image_id,headers=owner).status_code==200
    assert client.get('/v1/customer/images/'+image_id,headers=other).status_code==404
    assert client.get('/v1/cases/'+case_id+'/report',headers=owner).status_code==401
    assert client.get('/v1/jobs/'+receipt['job_id'],headers=owner).status_code==200
    assert client.get('/v1/jobs/'+receipt['job_id'],headers=other).status_code==404
    assert client.post('/v1/cases/'+case_id+'/action',headers=owner,json={'action':'approve'}).status_code==401
    assert client.post('/v1/cases/'+case_id+'/action',headers=reviewer,json={'action':'approve'}).status_code==409
    finish(case_id)
    payload={**basis(client,case_id,reviewer),'action':action,'reason':'Internal fictional review rationale',
             'public_message':'Your sample application is approved.' if action=='approve' else 'The required original photograph is missing.'}
    action_response=client.post('/v1/cases/'+case_id+'/action',headers=reviewer,json=payload)
    assert action_response.status_code==200,action_response.text
    updated=client.get(url,headers=owner).json()
    assert updated['outcome']==action and updated['publicNarrative']==payload['public_message']
    assert 'Internal fictional' not in json.dumps(updated)
    assert client.post('/v1/cases/'+case_id+'/action',headers=reviewer,json=payload).status_code==409
    queue=client.get('/v1/cases',headers=reviewer).json()['items'][0]
    assert queue['processing_status']=='completed' and queue['final_admin_action']==action


def test_idempotency_ownership_rollback_and_no_email_inheritance(client,monkeypatch):
    # This historical guest case already contains the new account's exact
    # applicant email; that string must confer no ownership.
    anonymous=owned_submit(client,{}).json()
    owner=customer(client); other=customer(client,'other.sample@example.com'); key=str(uuid.uuid4())
    first=owned_submit(client,owner,key=key); second=owned_submit(client,owner,key=key)
    assert first.status_code==second.status_code==201 and first.json()==second.json()
    assert owned_submit(client,other,key=key).status_code==409
    assert len(client.get('/v1/customer/cases',headers=owner).json()['items'])==1
    linked=client.post('/v1/customer/cases/link',headers=owner,json={'case_id':anonymous['case_id'],'receipt':anonymous['applicant_token']})
    assert linked.status_code==200,linked.text
    assert client.post('/v1/customer/cases/link',headers=other,json={'case_id':anonymous['case_id'],'receipt':anonymous['applicant_token']}).status_code==409
    with runtime_store.connection(api.DB_PATH) as conn:
        before=conn.execute('SELECT COUNT(*) FROM case_owners').fetchone()[0]
    monkeypatch.setattr(runtime_store,'enqueue',lambda *a,**k: (_ for _ in ()).throw(OSError('controlled queue failure')))
    assert owned_submit(client,owner).status_code==503
    with runtime_store.connection(api.DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM case_owners').fetchone()[0]==before
        assert conn.execute('SELECT COUNT(*) FROM cases').fetchone()[0]==before


def test_manual_override_stale_basis_and_rejection_public_reason(client):
    owner=customer(client); reviewer=auth(client); case_id=owned_submit(client,owner).json()['case_id'];finish(case_id,'failed')
    base=basis(client,case_id,reviewer)
    def act(**values): return client.post('/v1/cases/'+case_id+'/action',headers=reviewer,json={**base,'action':'approve',**values})
    assert act().json()['code']=='MANUAL_REVIEW_REQUIRED'
    assert act(manual_review_override=True).status_code==422
    assert act(expected_run_id='stale-run').status_code==409
    assert act(expected_evidence_ids=[]).status_code==409
    assert act(action='reject',manual_review_override=True,reason='Private').json()['code']=='PUBLIC_REASON_REQUIRED'
    assert act(action='approve',manual_review_override=True,reason='Reviewed saved photographs despite unavailable analysis.').status_code==200
    with runtime_store.connection(api.DB_PATH) as conn:
        event=[e for e in db.get_audit_events_for_case(conn,case_id) if e.event_type=='admin_action'][-1]
        assert event.details['manual_review_override'] is True and event.details['run_id']==base['expected_run_id']


def test_customer_additional_evidence_and_request_ownership(client):
    owner=customer(client); other=customer(client,'other.sample@example.com');reviewer=auth(client)
    receipt=owned_submit(client,owner).json();case_id=receipt['case_id'];finish(case_id)
    action=client.post('/v1/cases/'+case_id+'/action',headers=reviewer,json={**basis(client,case_id,reviewer),
        'action':'request_more_evidence','reason':'Private reviewer note','public_message':'Please upload the rear view.',
        'requested_artifacts':['Rear view with registration plate']})
    assert action.status_code==200,action.text
    request_id=client.get('/v1/customer/cases/'+case_id,headers=owner).json()['evidenceRequest']['request_id']
    def send(headers):return client.post('/v1/cases/'+case_id+'/evidence',headers=headers,data={'request_id':request_id},
        files={'images':('rear.png',photo('blue'),'image/png')})
    assert send(other).status_code==401
    assert send(owner).status_code==200
    updated=client.get('/v1/customer/cases/'+case_id,headers=owner).json()
    assert updated['outcome'] is None and updated['processingStatus']=='queued' and len(updated['images'])==5
    assert any(event['title']=='Additional photographs received' for event in updated['timeline'])


def test_conflicting_reviewers_and_changed_run_are_rejected(client):
    owner=customer(client);reviewer=auth(client);receipt=owned_submit(client,owner).json()
    case_id=receipt['case_id'];finish(case_id)
    base=basis(client,case_id,reviewer)
    barrier=threading.Barrier(2)
    def act(action):
        barrier.wait(timeout=15)
        return client.post('/v1/cases/'+case_id+'/action',headers=reviewer,json={**base,
            'action':action,'reason':'Fictional review','public_message':'Fictional customer explanation.'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(act,['approve','reject']))
    assert sorted(statuses)==[200,409]
    current=basis(client,case_id,reviewer)
    new=client.post('/v1/cases/'+case_id+'/reprocess',headers=reviewer)
    assert new.status_code==200,new.text
    finish(case_id)
    stale=client.post('/v1/cases/'+case_id+'/action',headers=reviewer,json={**current,'action':'approve'})
    assert stale.status_code==409 and stale.json()['code']=='REVIEW_BASIS_CHANGED'
