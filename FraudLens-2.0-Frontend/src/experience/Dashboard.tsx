import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Logo, Icon, Empty } from './shared';
import { CustomerGate } from './CustomerSession';
import { customerFetch, customerLogout, customerRequest } from './customer-api';
import './user-dashboard.css';

type UserCase = {
  id: string; kind: 'claims'|'underwriting'; status: string; outcome: string|null;
  publicNarrative: string; submittedAt: string; updatedAt: string; processingStatus: string;
  processingStage?: string; processingDetail?: string; registration?: string; policy?: string;
  evidenceRequest?: {request_id: string; artifacts: string[]; status: string};
  application?: Record<string, unknown>;
  timeline?: {id: string; at: string; title: string; message: string}[];
  images?: {id: string; label: string; url: string}[];
};
const date = (value: string) => new Date(value).toLocaleString('en-IN', {dateStyle:'medium',timeStyle:'short'});
const outcomeLabel = (outcome: string|null) => outcome === 'approve' ? 'Approved' : outcome === 'reject' ? 'Declined' : 'Awaiting reviewer';
const humanize = (value: string) => value==='completed_partial' ? 'Saved — awaiting review' : value.replaceAll('_', ' ');

function Photograph({path, label}: {path: string; label: string}) {
  const [url, setUrl] = useState(''), [error, setError] = useState('');
  useEffect(() => {
    let disposed = false, objectUrl = '';
    const controller = new AbortController();
    customerFetch(path, {signal:controller.signal}).then(r => r.blob()).then(blob => {
      if (!disposed) {objectUrl = URL.createObjectURL(blob); setUrl(objectUrl);}
    }).catch((e: Error) => {if (!disposed) setError(e.message);});
    return () => {disposed = true; controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl);};
  }, [path]);
  return <figure>{url ? <a href={url} target="_blank" rel="noreferrer"><img src={url} alt={label} /></a>
    : <span>{error || 'Loading photograph…'}</span>}<figcaption>{label}</figcaption></figure>;
}
function AdditionalEvidence({current, accepted}: {current: UserCase; accepted: () => void}) {
  const [files, setFiles] = useState<File[]>([]), [urls, setUrls] = useState<string[]>([]);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const sending = useRef(false);
  useEffect(() => {
    const values = files.map(file => URL.createObjectURL(file)); setUrls(values);
    return () => values.forEach(value => URL.revokeObjectURL(value));
  }, [files]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (sending.current || !current.evidenceRequest) return;
    if (!files.length || files.length > 12 || files.some(file => !['image/jpeg','image/png','image/webp'].includes(file.type) || file.size > 5*1024*1024 || !file.size)) {
      setError('Select 1–12 JPEG, PNG or WebP photographs, at most 5 MB each.'); return;
    }
    sending.current = true; setBusy(true); setError('');
    const body = new FormData(); body.set('request_id',current.evidenceRequest.request_id);
    files.forEach(file => body.append('images',file));
    try {await customerRequest('/v1/cases/'+encodeURIComponent(current.id)+'/evidence',{method:'POST',body}); setFiles([]); accepted();}
    catch(e) {setError((e as Error).message);}
    finally {sending.current = false; setBusy(false);}
  }
  if (!current.evidenceRequest) return null;
  return <section className="ud-panel"><h2>Requested photographs</h2>
    <ul>{current.evidenceRequest.artifacts.map(item => <li key={item}>{item}</li>)}</ul>
    <form onSubmit={submit}>
      <label className="field"><span>Additional photographs (up to 12; 5 MB each)</span>
        <input type="file" accept="image/jpeg,image/png,image/webp" multiple disabled={busy}
          onChange={e => {setFiles(Array.from(e.target.files || [])); setError('');}} /></label>
      <div className="ud-evidence-gallery">{files.map((file,index) => <figure key={file.name+index}>
        <img src={urls[index]} alt={'Selected '+file.name} /><figcaption>{file.name}</figcaption>
        <button type="button" className="ud-outline" disabled={busy} onClick={() => setFiles(old => old.filter((_,i) => i !== index))}>Remove {file.name}</button>
      </figure>)}</div>
      {error && <p role="alert" className="ud-error">{error}</p>}
      <button className="ud-primary" disabled={busy || !files.length}>{busy ? 'Uploading…' : 'Submit requested evidence'}</button>
    </form>
  </section>;
}
function Workspace() {
  const [tab,setTab] = useState('Overview'), [cases,setCases] = useState<UserCase[]>([]);
  const [selected,setSelected] = useState<string|null>(null), [current,setCurrent] = useState<UserCase|null>(null);
  const [connect,setConnect] = useState(false), [query,setQuery] = useState(''), [error,setError] = useState('');
  const [loading,setLoading] = useState(true), [busy,setBusy] = useState(false), [revision,setRevision] = useState(0);
  useEffect(() => {setSelected(new URLSearchParams(window.location.search).get('case'));}, []);
  useEffect(() => {
    let disposed = false, running = false, failures = 0;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function refresh() {
      if (disposed || running) return;
      clearTimeout(timer); running = true;
      let next = 2500;
      try {
        const [list, detail] = await Promise.all([
          customerRequest<{items: UserCase[]}>('/v1/customer/cases',{signal:controller.signal}),
          selected ? customerRequest<UserCase>('/v1/customer/cases/'+encodeURIComponent(selected),{signal:controller.signal}) : Promise.resolve(null),
        ]);
        if (!disposed) {setCases(list.items); setCurrent(detail); setError(''); setLoading(false);}
        failures = 0;
        if (!list.items.some(item => !item.outcome)) next = 30000;
      } catch(e) {
        failures++; next = Math.min(30000,2500*2**failures);
        if (!disposed) {setError((e as Error).message); setLoading(false);}
      } finally {
        running = false;
        if (!disposed) timer = setTimeout(refresh,document.hidden ? 60000 : next);
      }
    }
    const resume = () => {if (!document.hidden) void refresh();};
    void refresh(); window.addEventListener('focus',resume); document.addEventListener('visibilitychange',resume);
    return () => {disposed=true; clearTimeout(timer); controller.abort(); window.removeEventListener('focus',resume); document.removeEventListener('visibilitychange',resume);};
  }, [selected, revision]);
  function open(id: string|null) {setCurrent(null); setSelected(id); setLoading(true); setConnect(false); setError('');}
  async function link(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return; setBusy(true); setError('');
    const form = new FormData(event.currentTarget);
    try {
      const result = await customerRequest<UserCase>('/v1/customer/cases/link',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({case_id:String(form.get('id')||'').trim(),receipt:String(form.get('receipt')||'').trim()})});
      open(result.id); setRevision(x=>x+1);
    } catch(e) {setError((e as Error).message);}
    finally {setBusy(false);}
  }
  const visible = cases.filter(item => (tab !== 'My claims' || item.kind === 'claims') &&
    (tab !== 'My underwriting' || item.kind === 'underwriting') &&
    (tab !== 'Updates' || !!item.evidenceRequest || !!item.outcome) &&
    [item.id,item.registration,item.policy].some(value => value?.toLowerCase().includes(query.toLowerCase())));
  return <div className="user-dashboard">
    <a className="skip" href="#user-main">Skip to dashboard</a>
    <header className="ud-header"><Logo /><span>YOUR WORKSPACE</span><div>
      <a href="/">View website ↗</a><button className="ud-outline" onClick={() => {void customerLogout().catch(()=>undefined);}}>Sign out customer</button>
    </div></header>
    <div className="ud-layout"><aside className="ud-sidebar"><span className="ud-kicker">MY DASHBOARD</span>
      {['Overview','My claims','My underwriting','Updates','Help & guidance'].map(name =>
        <button key={name} className={tab===name && !selected && !connect ? 'active' : ''}
          onClick={() => {setTab(name); open(null); setQuery('');}}><Icon name={name==='Updates'?'clock':'file'} size={18} />{name}</button>)}
      <div className="ud-sidebar-bottom"><Icon name="lock" /><h3>Your case. Your privacy.</h3>
        <p>Only cases submitted through your account or explicitly linked with a private receipt appear here.</p></div>
    </aside><main id="user-main" className="ud-main">
      <div className="ud-title"><div><span>FraudLens 2.0 / Your dashboard</span><h1>{selected ? 'Case overview' : connect ? 'Link an earlier case' : 'Your insurance, in view.'}</h1></div>
        <button className="ud-outline" onClick={() => setRevision(x=>x+1)}>Refresh cases</button></div>
      {error && <div className="ud-error" role="alert">{error} <button className="ud-text-button" onClick={()=>setRevision(x=>x+1)}>Retry</button></div>}
      {loading && <p role="status">Loading your cases…</p>}
      {connect ? <section className="ud-panel ud-connect"><div><h2>Use your private receipt.</h2><p>A registration, policy number, or matching email does not grant account ownership.</p></div>
        <form onSubmit={link}><label className="field"><span>Case ID</span><input name="id" required maxLength={64} /></label>
          <label className="field"><span>Private access receipt</span><input name="receipt" required autoComplete="off" maxLength={256} /></label>
          <button className="ud-primary" disabled={busy}>{busy?'Checking…':'Link case securely'}</button>
          <button className="ud-text-button" type="button" onClick={()=>setConnect(false)}>Cancel</button></form></section>
      : selected ? <><button className="ud-text-button" onClick={()=>open(null)}>← Back to dashboard</button>{current && <>
        <section className={'ud-panel ud-case-heading '+current.kind}><div><span className={'ud-tag '+current.kind}>{current.kind}</span>
          <h2>{current.id}</h2><p>Submitted {date(current.submittedAt)}</p></div><strong>{outcomeLabel(current.outcome)}</strong></section>
        <div className="ud-detail-grid"><section className="ud-panel"><span className="ud-kicker">ANALYSIS STATUS</span>
          <h2>{current.processingDetail?.startsWith('Assessment complete') ? current.processingDetail : humanize(current.processingStatus)}</h2><p>{current.processingStage}</p>{!current.processingDetail?.startsWith('Assessment complete') && <p>{current.processingDetail}</p>}
          <p>Processing produces an assessment. A human reviewer records the final outcome.</p></section>
          <section className="ud-panel"><span className="ud-kicker">REVIEWER UPDATE</span><h2>{outcomeLabel(current.outcome)}</h2>
            <p className="ud-narrative">{current.publicNarrative}</p></section></div>
        <AdditionalEvidence key={current.id + (current.evidenceRequest?.request_id||'')} current={current} accepted={()=>setRevision(x=>x+1)} />
        <section className="ud-panel"><h2>Your case journey</h2><ol className="ud-recorded-timeline">{current.timeline?.map(event =>
          <li key={event.id}><time dateTime={event.at}>{date(event.at)}</time><h3>{event.title}</h3>{event.message && <p>{event.message}</p>}</li>)}</ol></section>
        <section className="ud-panel"><h2>Submitted information</h2><dl className="ud-application">{Object.entries(current.application||{})
          .filter(([,value])=>value!==null && value!=='').map(([key,value])=><div key={key}><dt>{humanize(key)}</dt><dd>{String(value)}</dd></div>)}</dl></section>
        <section className="ud-panel"><h2>Your photographs</h2><div className="ud-evidence-gallery">{current.images?.map(image =>
          <Photograph key={image.id} path={image.url} label={image.label} />)}</div></section>
      </>}</> : tab==='Help & guidance' ? <section className="ud-panel"><h2>Follow your case</h2>
        <p>New applications are saved to your signed-in account and remain after a refresh. Use an earlier case’s private receipt to link it securely.</p>
        <p>Open a case to read recorded updates or respond to specific photograph requests. Internal reviewer notes and investigation findings stay private.</p>
        <p>Use the form’s “Sample suggestions” one field at a time for a fictional presentation. You can edit every selected value.</p></section>
      : <section className="ud-panel ud-case-list"><div className="ud-panel-head"><div><span className="ud-kicker">YOUR APPLICATIONS</span><h2>{tab==='Overview'?'Recent cases':tab}</h2></div><span className="ud-chip">{visible.length} cases</span></div>
        <label className="ud-search"><Icon name="search" size={18}/><input aria-label="Search your cases" placeholder="Search case ID, registration or policy" value={query} onChange={e=>setQuery(e.target.value)} /></label>
        {visible.length ? <div className="ud-table-scroll"><table><thead><tr><th>Case ID</th><th>Application</th><th>Submitted</th><th>Processing</th><th>Reviewer outcome</th><th/></tr></thead>
          <tbody>{visible.map(item=><tr key={item.id}><td><button className="ud-case-id" onClick={()=>open(item.id)}>{item.id}</button></td><td><span className={'ud-tag '+item.kind}>{item.kind}</span></td>
            <td>{date(item.submittedAt)}</td><td>{humanize(item.processingStatus)}</td><td>{outcomeLabel(item.outcome)}{item.evidenceRequest && <span> · Evidence requested</span>}</td>
            <td><button className="ud-text-button" onClick={()=>open(item.id)}>View ↗</button></td></tr>)}</tbody></table></div>
          : !loading && <Empty icon="file" title={query?'No matching cases':'Your cases will appear here'} text="Submit a new application or link an earlier case with its private receipt." />}
        <div className="ud-customer-actions"><a className="ud-primary" href="/apply/claims">New claim</a><a className="ud-outline" href="/apply/underwriting">New underwriting application</a>
          <button className="ud-outline" onClick={()=>setConnect(true)}>Link an earlier case</button></div>
      </section>}
    </main></div>
  </div>;
}
export default function Dashboard() {return <CustomerGate><Workspace /></CustomerGate>;}
