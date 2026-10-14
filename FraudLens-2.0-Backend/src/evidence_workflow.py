"""Secure supplementary photographs and local organization account management."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import uuid
from typing import Optional
from fastapi import Depends, File, Form, Header, UploadFile
from pydantic import BaseModel, Field
from . import db, ingest, runtime_store
from .models import AuditEvent


def install(app):
    from .api import ApiError, SubmitCaseOut, get_conn, require_owner, _snapshot_report, UPLOAD_DIR

    @app.post('/v1/cases/{case_id}/evidence', response_model=SubmitCaseOut, tags=['cases'])
    def submit_evidence(case_id: str, request_id: str = Form(...), images: list[UploadFile] = File(...),
                        x_applicant_token: Optional[str] = Header(default=None),
                        conn: sqlite3.Connection = Depends(get_conn)):
        if not runtime_store.applicant_authorized(conn,x_applicant_token,case_id):
            raise ApiError(401,'APPLICANT_UNAUTHORISED','A valid applicant access receipt for this case is required.')
        if not 1<=len(images)<=12:
            raise ApiError(422,'INVALID_EVIDENCE_COUNT','Attach 1–12 requested photographs.')
        request=runtime_store.open_request(conn,case_id)
        if not request or request['request_id']!=request_id:
            raise ApiError(409,'EVIDENCE_REQUEST_CLOSED','This evidence request is closed or superseded.')
        from .api import UPLOAD_DIR as upload_root
        batch_dir=upload_root/case_id/('supplement-'+uuid.uuid4().hex)
        created_batch_dir=False
        try:
            with tempfile.TemporaryDirectory(prefix='fraudlens_supplement_') as tmp:
                staged=[]; hashes=set()
                for upload in images:
                    content=upload.file.read(5*1024*1024+1)
                    if not content or len(content)>5*1024*1024:
                        raise ApiError(422,'INVALID_IMAGE_SIZE','Each photograph must be nonempty and at most 5 MB.')
                    content_hash=hashlib.sha256(content).hexdigest()
                    if content_hash in hashes or conn.execute('SELECT 1 FROM images WHERE case_id=? AND content_hash=?',(case_id,content_hash)).fetchone():
                        raise ApiError(409,'DUPLICATE_EVIDENCE','This photograph is already attached to the case.')
                    hashes.add(content_hash)
                    target=Path(tmp)/uuid.uuid4().hex; target.write_bytes(content)
                    try:
                        from PIL import Image
                        with Image.open(target) as picture:
                            if picture.format not in {'JPEG','PNG','WEBP'} or picture.width*picture.height>25_000_000:
                                raise ValueError('unsupported image')
                            suffix={'JPEG':'.jpg','PNG':'.png','WEBP':'.webp'}[picture.format]
                            picture.verify()
                    except Exception as exc:
                        raise ApiError(422,'INVALID_IMAGE','Upload valid JPEG, PNG or WebP photographs up to 25 megapixels.') from exc
                    staged.append((target,suffix,upload.filename or 'photograph'))
                # Requested closeups (plate/odometer/damage) may not show a whole
                # vehicle. Decode and index them; do not apply the intake gate.
                embeddings=[ingest._default_embedder.embed(source) for source,_,_ in staged]
                conn.execute('BEGIN IMMEDIATE')
                request=runtime_store.open_request(conn,case_id)
                if not request or request['request_id']!=request_id:
                    raise ApiError(409,'EVIDENCE_REQUEST_CLOSED','The evidence request changed; refresh the tracker.')
                if conn.execute("SELECT 1 FROM api_jobs WHERE case_id=? AND status IN ('queued','running')",(case_id,)).fetchone():
                    raise ApiError(409,'ANALYSIS_RUNNING','Wait for current analysis before adding evidence.')
                _snapshot_report(conn,case_id)
                batch_dir.mkdir(parents=True,exist_ok=False)
                created_batch_dir=True
                image_ids=[]
                for (source,suffix,original),embedding in zip(staged,embeddings):
                    content_hash=hashlib.sha256(source.read_bytes()).hexdigest()
                    if conn.execute('SELECT 1 FROM images WHERE case_id=? AND content_hash=?',(case_id,content_hash)).fetchone():
                        raise ApiError(409,'DUPLICATE_EVIDENCE','This photograph is already attached.')
                    target=batch_dir/(uuid.uuid4().hex+suffix); shutil.copyfile(source,target)
                    indexed=ingest.ingest_image(conn,case_id,target,embedding=embedding); image_ids.append(indexed.image_id)
                job=runtime_store.enqueue(conn,case_id)
                now=time.time()
                conn.execute("UPDATE evidence_requests SET status='fulfilled',fulfilled_at=? WHERE request_id=?",(now,request_id))
                conn.execute('INSERT INTO evidence_batches VALUES (?,?,?,?,?)',(batch_dir.name,case_id,request_id,json.dumps(image_ids),now))
                conn.execute("UPDATE cases SET status='evidence_received' WHERE case_id=?",(case_id,))
                db.log_audit_event(conn,AuditEvent(event_type='additional_evidence_received',case_id=case_id,
                    details={'actor':'authorized_applicant','request_id':request_id,'image_ids':image_ids,
                             'run_id':job['job_id'],'hashes':sorted(hashes)}))
                conn.commit()
            return SubmitCaseOut(case_id=case_id,job_id=job['job_id'],status='queued',images_received=len(image_ids))
        except Exception as exc:
            conn.rollback()
            if created_batch_dir and not batch_dir.is_symlink() and batch_dir.resolve().parent == (upload_root/case_id).resolve():
                shutil.rmtree(batch_dir,ignore_errors=True)
            if isinstance(exc,ApiError): raise
            raise ApiError(503,'EVIDENCE_INGEST_FAILED','Additional evidence was not accepted. Original evidence is preserved; please retry.') from exc

    class AccountIn(BaseModel):
        email: str = Field(min_length=3,max_length=254)
        password: str = Field(min_length=12,max_length=1024)
        role: str = 'reviewer'
        enabled: bool = True

    @app.get('/v1/accounts',tags=['auth'])
    def accounts(actor: str=Depends(require_owner),conn: sqlite3.Connection=Depends(get_conn)):
        return [dict(row) for row in conn.execute('SELECT email,role,organization_id,enabled FROM reviewer_accounts ORDER BY email')]

    @app.put('/v1/accounts',tags=['auth'])
    def save_account(payload: AccountIn,actor: str=Depends(require_owner),conn: sqlite3.Connection=Depends(get_conn)):
        email=payload.email.strip().lower()
        if '@' not in email or payload.role not in {'admin','reviewer','viewer'}:
            raise ApiError(422,'VALIDATION_FAILED','A reviewer email and an admin, reviewer or viewer role are required.')
        if email==actor and (not payload.enabled or payload.role!='admin'):
            raise ApiError(409,'ACCOUNT_SELF_LOCKOUT','Use a different administrator to change your own access.')
        value=runtime_store.password_hash(payload.password)
        conn.execute('''INSERT INTO reviewer_accounts(email,password_hash,role,enabled) VALUES (?,?,?,?)
            ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash,role=excluded.role,enabled=excluded.enabled''',
            (email,value,payload.role,int(payload.enabled)))
        conn.execute('DELETE FROM admin_sessions WHERE actor=?',(email,))
        db.log_audit_event(conn,AuditEvent(event_type='reviewer_account_updated',details={'admin_id':actor,'email':email,'role':payload.role,'enabled':payload.enabled}))
        conn.commit()
        return {'email':email,'role':payload.role,'organization_id':'local','enabled':payload.enabled}
