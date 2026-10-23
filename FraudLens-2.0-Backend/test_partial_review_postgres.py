"""Focused real PostgreSQL transactions in a disposable schema; no model HTTP."""
import pytest
from test_postgres import client,pg_schema,pytestmark
from test_partial_review import pipeline
from test_customer_workflow import customer,owned_submit
from test_pilot_workflow import auth
from src import api,db,runtime_store

@pytest.mark.parametrize('kind',['claims','underwriting'])
def test_partial_state_snapshot_and_pdf_are_durable(client,pipeline,kind):
    receipt=owned_submit(client,customer(client),kind).json();run,provider=pipeline
    run(receipt['job_id'],receipt['case_id'])
    with runtime_store.connection('postgresql') as conn:
        assert runtime_store.get_job(conn,receipt['job_id'])['status']=='completed_partial'
        assert conn.execute('SELECT COUNT(*) FROM report_snapshots WHERE run_id=?',(receipt['job_id'],)).fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM findings WHERE case_id=?',(receipt['case_id'],)).fetchone()[0]>=4
    reviewer=auth(client);path='/v1/cases/'+receipt['case_id']+'/reports'
    response=client.post(path+'/prepare',headers=reviewer);assert response.status_code==200,response.text
    version=response.json();pdf=client.get(path+'/'+version['snapshot_id']+'/pdf',headers=reviewer)
    assert pdf.status_code==200 and pdf.content.startswith(b'%PDF-')
    calls=provider.calls
    assert client.post(path+'/prepare',headers=reviewer).json()['snapshot_id']==version['snapshot_id']
    assert provider.calls==calls
