import {useEffect,useState} from 'react';
import {api} from './shared';

type Workspace={schema:string;dataset:string;note:string;examples:{case_id:string;label:string}[]};
export default function WorkspaceSelector({user,onOpen}:{user:string|null;onOpen:(id:string)=>void}) {
  const [workspace,setWorkspace]=useState<Workspace|null>(null);
  const [error,setError]=useState('');
  useEffect(()=>{let current=true;setWorkspace(null);if(user)api('workspace').then(value=>{if(current)setWorkspace(value as Workspace);}).catch(()=>{if(current)setError('Workspace identity unavailable. Confirm the selected dataset before presenting.');});return()=>{current=false;};},[user]);
  if(!user)return null;
  return <section className="case-panel" aria-label="Active review dataset" style={{marginBottom:20}}>
    <strong>{workspace ? 'Active dataset: '+workspace.dataset : error || 'Confirming active dataset…'}</strong>
    {workspace && <><div style={{display:'flex',gap:10,flexWrap:'wrap',marginTop:12}}>{workspace.examples.map(item=><button type="button" key={item.case_id} onClick={()=>onOpen(item.case_id)}>{item.label}</button>)}</div>
    <small>{workspace.note}</small><details><summary>Dataset selection</summary><p>PostgreSQL schema: {workspace.schema}. Switch using scripts/start_review.ps1 with the same dataset for API and worker. An empty public schema does not describe this application's private schema.</p></details></>}
  </section>;
}
