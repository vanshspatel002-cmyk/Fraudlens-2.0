import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';

const compile = source => ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const asModule = source => 'data:text/javascript;base64,'+Buffer.from(compile(source)).toString('base64');
const slotsModule = asModule(await readFile(new URL('../src/experience/photoSlots.ts',import.meta.url),'utf8'));
const source = (await readFile(new URL('../src/experience/intakeValidation.ts',import.meta.url),'utf8')).replace("'./photoSlots'",JSON.stringify(slotsModule));
const {submissionBlockers}=await import(asModule(source));
const {photoSlots}=await import(slotsModule);
for (const kind of ['claims','underwriting']) {
  const controls=Object.entries({registration:'MH12AB1234',phone:'9000000041',consent:'yes',amount:'2000'}).map(([name,value])=>({name,value,label:name,missing:false,invalid:''}));
  const files=Object.fromEntries(photoSlots[kind].map(slot=>[slot.id,new File(['controlled fixture'],slot.id+'.png',{type:'image/png'})]));
  const photos=Object.fromEntries(photoSlots[kind].map(slot=>[slot.id,{state:'accepted',reason:'Controlled fixture',normalized_hash:slot.id}]));
  const options={hydrated:true,busy:false,intake:true};
  assert.deepEqual(submissionBlockers(kind,controls,files,photos,options),[]);
  for(const key of ['hydrated','intake','busy']){
    const changed={...options,[key]:!options[key]};assert.ok(submissionBlockers(kind,controls,files,photos,changed)[0].reason);
  }
  const slot=photoSlots[kind][0].id;
  for(const state of ['checking','unavailable','rejected','needs_replacement']){
    const changed={...photos,[slot]:{state,reason:'Recheck this photograph'}};
    const blocked=submissionBlockers(kind,controls,files,changed,options);assert.ok(blocked.length&&blocked.every(item=>item.reason));
  }
  const missing={...files};delete missing[slot];assert.match(submissionBlockers(kind,controls,missing,photos,options)[0].reason,/Upload/);
  const consent=controls.map(control=>control.name==='consent'?{...control,value:'',missing:true}:control);
  assert.match(submissionBlockers(kind,consent,files,photos,options)[0].reason,/Accept consent/);
  const invalid=controls.map(control=>control.name==='registration'?{...control,value:'invalid'}:control);
  assert.match(submissionBlockers(kind,invalid,files,photos,options)[0].reason,/valid Indian registration/);
  const inactive=[...controls,{name:'latitude',value:'22.3',label:'latitude',missing:false,invalid:''}];
  assert.equal(submissionBlockers(kind,inactive,files,photos,options).length,kind==='claims'?1:0);
}
console.log('Both intake validators: valid 4/6 slots, consent, invalid fields, loading/busy, unavailable/rejected/pending and inactive case fields passed.');
