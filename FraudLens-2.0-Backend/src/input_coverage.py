"""Required-photo text sufficiency, separate from relevance and fraud findings."""


def assess_inputs(case_type,rows,config):
    if case_type!='underwriting' or not config.get('odometer_photo_required'):
        return {}
    from .photo_admission import readable_detail
    ids=set(config.get('required_odometer_image_ids') or [])
    evidence=[row for row in rows if row['check_id']=='plate_ocr' and row['observed_values'].get('image_id') in ids]
    text=[str(item['text']) for row in evidence for item in row['observed_values'].get('raw_ocr_strings',[]) if item.get('text')]
    readable=readable_detail('odometer',text)
    return {'odometer_readability':dict(required=True,applicable=True,executed=bool(evidence),
        evidence_sufficient=readable,execution_state='completed' if readable else 'inconclusive',
        reason=('A labelled mileage reading was extracted; true mileage, unit correctness and vehicle identity remain unverified.' if readable else
            'The required dashboard photograph is relevant, but no labelled mileage reading was established. Request a powered, sharp odometer display; missing text is not evidence of fraud.'),
        evidence_ids=sorted(ids),finding_ids=[row['finding_id'] for row in evidence],
        source='saved_local_ocr',scope='required_input_not_fraud_check')}
