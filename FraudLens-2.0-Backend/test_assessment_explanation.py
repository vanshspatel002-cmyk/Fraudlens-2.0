"""Persistable arithmetic/routing provenance; no model or database is used."""
import pytest

from src import baseline
from src.assessment_explanation import explain_assessment
from src.agent.production_policy import production_policy
from src.models import AgentDecision,Case,CheckCategory,Finding,Recommendation,RiskBand,Verdict


def case(kind='claims'):
    return Case(case_id='explanation-fixture',claimant_id='fictional',garage_id='UNASSIGNED',claim_type='inspection',agent_type=kind)


def finding(check='external_corpus',verdict=Verdict.CONCERN,confidence=.8,**evidence):
    return Finding(check_id=check,case_id='explanation-fixture',category=CheckCategory.HISTORY,verdict=verdict,confidence=confidence,
                   explanation='Controlled recorded observation.',evidence=evidence)


def test_baseline_explanation_matches_existing_arithmetic_without_deduplicating():
    findings=[finding(),finding(confidence=.6),finding('plate_ocr',confidence=.9),finding('ai_generation'),finding('external_corpus',Verdict.PASS)]
    decision=baseline.decide(findings,case())
    result=explain_assessment(case(),findings,decision,production_policy('claims'),converged=True,use_agent=False)
    assert result['aggregation']['valid_numeric_score'] is True
    assert result['aggregation']['computed_value']==decision.score
    assert round(sum(row['contribution'] for row in result['findings']),4)==decision.score
    experimental=result['findings'][3]
    assert experimental['registered_weight']==0 and experimental['contribution']==0
    assert experimental['eligibility']['eligible'] is False
    assert result['findings'][4]['contribution']==0
    assert result['aggregation']['thresholds']=={'clear_below':.3,'request_evidence_below':.6,'desk_review_below':1.0}


def test_agent_explanation_has_no_arbitrary_score_or_numeric_contributions():
    observed=finding(cosine_similarity=.97)
    decision=AgentDecision(case_id=case().case_id,recommendation=Recommendation.ESCALATE,risk_band=RiskBand.DESK_REVIEW,
        confidence=.75,summary='Recorded interpretation.',supporting_finding_ids=[observed.finding_id],requested_artifacts=[],policy_version='controlled-agent')
    result=explain_assessment(case(),[observed],decision,production_policy('claims'),converged=True,run_id='run-fixture')
    assert result['aggregation']['computed_value'] is None and result['aggregation']['valid_numeric_score'] is False
    assert result['aggregation']['unrounded_value'] is None
    assert all(row['contribution'] is None for row in result['findings'])
    assert result['findings'][0]['cited_by_agent'] is True
    assert result['findings'][0]['observed_values']['cosine_similarity']==.97
    assert result['routing']['source']=='model' and result['routing']['recorded_band']=='desk_review'
    assert result['run_id']=='run-fixture'


def test_rule_parameters_freeze_actual_overrides_and_observations_are_detached():
    observed=finding('internal_duplicate',cosine_similarity=.96,execution_state='completed')
    decision=baseline.decide([observed],case())
    result=explain_assessment(case(),[observed],decision,production_policy('claims'),converged=True,use_agent=False,
        check_config={'duplicate_cosine_concern':.92})
    assert result['findings'][0]['rule_parameters']['duplicate_cosine_concern']==.92
    observed.evidence['cosine_similarity']=.2
    assert result['findings'][0]['observed_values']['cosine_similarity']==.96


def test_missing_failed_not_applicable_and_experimental_never_become_passes():
    findings=[finding('plate_ocr',Verdict.INCONCLUSIVE,0,execution_state='failed',error_type='FixtureUnavailable'),
              finding('baseline_linkage',Verdict.INCONCLUSIVE,0,execution_state='not_applicable'),
              finding('digital_edit',Verdict.INCONCLUSIVE,0,execution_state='inconclusive')]
    decision=baseline.decide(findings,case())
    result=explain_assessment(case(),findings,decision,production_policy('claims'),converged=False,use_agent=True,
        trace=[{'kind':'fallback','detail':'provider error with private machine detail'}])
    states=result['coverage']['check_states']
    assert states['plate_ocr']=='failed' and states['baseline_linkage']=='not_applicable'
    assert states['external_corpus']=='not_run' and result['coverage']['complete'] is False
    assert all(not row['eligibility']['eligible'] for row in result['findings'])
    assert result['routing']['source']=='fallback'
    assert 'private machine' not in str(result['routing']['overrides'])


def test_baseline_mismatched_recorded_value_is_not_published_as_a_valid_score():
    findings=[finding()];decision=baseline.decide(findings,case());decision.score=99
    result=explain_assessment(case(),findings,decision,production_policy('claims'),converged=True,use_agent=False)
    assert result['aggregation']['computed_value'] is None
    assert result['aggregation']['status']=='recorded_score_mismatch'


@pytest.mark.parametrize('confidence,band,rounded',[
    (.299999999,'clear',.3),(.3,'request_evidence',.3),
    (.999999999,'desk_review',1.0),(1.0,'escalate_siu',1.0),
])
def test_baseline_rounding_trace_preserves_unrounded_threshold_comparisons(confidence,band,rounded):
    findings=[finding(confidence=confidence)]
    decision=baseline.decide(findings,case())
    result=explain_assessment(case(),findings,decision,production_policy('claims'),converged=True,use_agent=False)
    aggregation=result['aggregation']
    assert decision.score==rounded and decision.risk_band.value==band
    assert aggregation['computed_value']==rounded
    assert aggregation['unrounded_value']==confidence
    assert aggregation['rounding_places']==4
    assert aggregation['band_comparison_basis']=='unrounded_concern_sum'
    assert aggregation['reproduced_band']==band and aggregation['matches_recorded_band'] is True
    decision.risk_band=RiskBand.ESCALATE_SIU if band!='escalate_siu' else RiskBand.CLEAR
    changed=explain_assessment(case(),findings,decision,production_policy('claims'),converged=True,use_agent=False)
    assert changed['aggregation']['matches_recorded_band'] is False


def test_baseline_rounding_trace_uses_the_original_sequential_addition():
    findings=[finding(confidence=.1) for _ in range(10)]
    decision=baseline.decide(findings,case())
    aggregation=explain_assessment(case(),findings,decision,production_policy('claims'),converged=True,use_agent=False)['aggregation']
    assert aggregation['unrounded_value']==.9999999999999999
    assert aggregation['computed_value']==1.0
    assert aggregation['reproduced_band']=='desk_review' and aggregation['matches_recorded_band'] is True


def test_zero_weight_checks_do_not_make_material_coverage_incomplete():
    from dataclasses import replace
    findings=[finding(verdict=Verdict.PASS),finding('ai_generation',Verdict.INCONCLUSIVE,0)]
    policy=replace(production_policy('claims'),check_ids=('external_corpus','ai_generation'))
    decision=baseline.decide(findings,case())
    result=explain_assessment(case(),findings,decision,policy,converged=True,use_agent=False)
    assert result['coverage']['complete'] is False
    assert result['coverage']['material_complete'] is True
    assert result['coverage']['eligible_check_ids']==['external_corpus']


def test_baseline_eligibility_matches_its_actual_arithmetic_even_for_inconsistent_labels():
    findings=[finding(execution_state='failed')]
    decision=baseline.decide(findings,case())
    result=explain_assessment(case(),findings,decision,production_policy('claims'),converged=True,use_agent=False)
    row=result['findings'][0]
    assert row['contribution']==decision.score and row['eligibility']['eligible'] is True
    assert 'inconsistency' in row['eligibility']['reason']


def test_new_assessment_persists_exact_explanation_with_zero_weight_exclusion(client,tmp_path,monkeypatch):
    from dataclasses import replace
    from src import api,db,orchestrator,runtime_store
    from test_report_pdf import seed_case
    case_id=seed_case(tmp_path,status='completed')
    recorded=[finding(),finding('ai_generation')]
    for item in recorded:item.case_id=case_id
    monkeypatch.setattr(orchestrator,'run_checks',lambda *args,**kwargs:recorded)
    policy=replace(production_policy('claims'),check_ids=('external_corpus','ai_generation'))
    with runtime_store.connection(api.DB_PATH) as conn:
        run_id=runtime_store.latest_job(conn,case_id)['job_id']
        decision=orchestrator.process_case(conn,case_id,policy=policy,use_agent=False,run_id=run_id)
        event=[event for event in db.get_audit_events_for_case(conn,case_id) if event.event_type=='case_adjudicated'][-1]
        explanation=event.details['assessment_explanation']
        assert explanation['run_id']==run_id and explanation['policy_version']==baseline.POLICY_VERSION
        assert explanation['aggregation']['computed_value']==decision.score
        experimental=next(row for row in explanation['findings'] if row['check_id']=='ai_generation')
        assert experimental['registered_weight']==0 and experimental['contribution']==0
        assert experimental['execution_state']=='inconclusive'
        assert explanation['findings'][0]['finding_id']==recorded[0].finding_id
        assert api._build_report(conn,case_id).assessment_explanation==explanation
        snapshot_id=api._snapshot_report(conn,case_id);conn.commit()
        saved=conn.execute('SELECT payload FROM report_snapshots WHERE snapshot_id=?',(snapshot_id,)).fetchone()[0]
        new_job=runtime_store.enqueue(conn,case_id);conn.commit()
        assert new_job['job_id']!=run_id
        assert api._build_report(conn,case_id).assessment_explanation is None
        assert conn.execute('SELECT payload FROM report_snapshots WHERE snapshot_id=?',(snapshot_id,)).fetchone()[0]==saved


# Imported fixture is intentionally shared with the isolated API contract suite.
from test_pilot_workflow import client
