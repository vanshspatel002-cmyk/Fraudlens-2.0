import {useEffect, useRef, useState} from 'react';
import {fetchReportPdf, prepareReport, reportVersions, type ReportVersion} from './reportClient';
import './report-panel.css';

export default function ReportPanel({caseId, runId, processingStatus, initialSnapshotId}: {caseId: string; runId?: string; processingStatus?: string; initialSnapshotId?: string}) {
  const [versions, setVersions] = useState<ReportVersion[]>([]);
  const [snapshot, setSnapshot] = useState(initialSnapshotId || '');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [preview, setPreview] = useState('');
  const [filename, setFilename] = useState('');
  const alive = useRef(true);
  const requestEpoch = useRef(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const previewUrl = useRef('');
  const blocked = !snapshot && ['queued', 'running'].includes(processingStatus || '');
  const selected = versions.find(item => item.snapshot_id === snapshot);
  useEffect(() => {
    alive.current = true;
    requestEpoch.current++;
    let current = true;
    setLoaded(false); setError(''); setVersions([]); setSnapshot(initialSnapshotId || ''); setPreview(''); setBusy(false);
    reportVersions(caseId).then(items => {if (current) {setVersions(items); setLoaded(true);}}).catch(err => {if (current) {setError((err as Error).message); setLoaded(true);}});
    return () => {current = false; alive.current = false; if (previewUrl.current) URL.revokeObjectURL(previewUrl.current); previewUrl.current = '';};
  }, [caseId, runId, processingStatus, initialSnapshotId]);
  useEffect(() => {if (preview) dialog.current?.showModal();}, [preview]);
  function closePreview() {
    setPreview('');
    if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    previewUrl.current = '';
  }
  async function open(download: boolean) {
    if (busy) return;
    const epoch = requestEpoch.current;
    setBusy(true); setError('');
    try {
      const version = await prepareReport(caseId, snapshot || undefined);
      if (!alive.current || epoch !== requestEpoch.current) return;
      setSnapshot(version.snapshot_id);
      setVersions(items => [version, ...items.filter(item => item.snapshot_id !== version.snapshot_id)]);
      const result = await fetchReportPdf(caseId, version.snapshot_id, download);
      if (!alive.current || epoch !== requestEpoch.current) return;
      const url = URL.createObjectURL(result.blob);
      if (download) {
        const anchor = document.createElement('a'); anchor.href = url; anchor.download = result.filename;
        document.body.append(anchor); anchor.click(); anchor.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 30000);
      } else {
        if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
        previewUrl.current = url; setFilename(result.filename); setPreview(url);
      }
    } catch (err) {if (alive.current && epoch === requestEpoch.current) setError((err as Error).message);}
    finally {if (alive.current && epoch === requestEpoch.current) setBusy(false);}
  }
  return <section className="pdf-report-panel" aria-label="Saved PDF report">
    <h3>Saved PDF report</h3>
    {!initialSnapshotId && <label className="field"><span>Report version</span><select aria-label="PDF report version" disabled={busy || !loaded} value={snapshot} onChange={event => {setSnapshot(event.target.value); setError('');}}>
      <option value="">Current case · save analysis snapshot</option>
      {versions.map(version => <option key={version.snapshot_id} value={version.snapshot_id}>{new Date(version.snapshot_created_at * 1000).toLocaleString()} · {version.snapshot_id.slice(0,12)} · {version.pdf_status}</option>)}
    </select></label>}
    {selected && <p className="report-version">Version {selected.snapshot_id.slice(0,12)}<br />Run: {selected.run_id || 'Legacy, unscoped'}<br />{selected.generated_at ? 'PDF generated ' + new Date(selected.generated_at * 1000).toLocaleString() : selected.pdf_status === 'failed' ? 'PDF generation failed. Preview or download retries this saved version.' : 'PDF pending. Preview or download creates it from the saved snapshot.'}</p>}
    {blocked && <p role="status">Current analysis is {processingStatus}. Choose a saved historical version or wait for processing to finish.</p>}
    {!loaded && <p role="status">Loading saved report versions…</p>}
    <div className="pdf-report-actions"><button type="button" disabled={busy || blocked || !loaded} onClick={() => void open(false)}>{busy ? 'Preparing PDF…' : 'Preview report'}</button><button type="button" disabled={busy || blocked || !loaded} onClick={() => void open(true)}>Download PDF</button></div>
    {error && <p role="alert">{error}</p>}
    <small>Saved privately with this case. Opening a PDF uses the saved analysis and does not rerun AI or checks.</small>
    {preview && <dialog ref={dialog} className="pdf-preview-dialog" aria-label="PDF report preview" onCancel={closePreview}>
      <div className="pdf-preview-controls"><strong>FraudLens report</strong><a href={preview} target="_blank" rel="noopener noreferrer">Open PDF in a new tab</a><a href={preview} download={filename}>Download PDF</a><button type="button" onClick={closePreview}>Close preview</button></div>
      <p className="pdf-mobile-help">If the inline preview is unavailable on your device, use Open PDF or Download PDF above.</p>
      <iframe src={preview} title="Saved FraudLens PDF report" />
    </dialog>}
  </section>;
}
