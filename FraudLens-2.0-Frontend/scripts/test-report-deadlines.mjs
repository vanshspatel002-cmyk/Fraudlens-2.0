import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';

// Simulate elapsed network time without sleeping or contacting any service.
const timers=new Map();let timerId=0,elapsed=0,token='controlled-reviewer';
globalThis.window={setTimeout(callback,delay){timers.set(++timerId,{callback,delay});return timerId;},clearTimeout(id){timers.delete(id);}};
globalThis.sessionStorage={getItem(){return token;}};
const requests=[];
globalThis.fetch=async(url,options)=>{
  requests.push({url,authorization:options.headers.Authorization});
  for(const timer of timers.values())if(timer.delay<=elapsed)timer.callback();
  if(options.signal.aborted)throw new DOMException('Controlled deadline','AbortError');
  return new Response(JSON.stringify({snapshot_id:'saved-snapshot',reports:[]}),{headers:{'Content-Type':'application/json'}});
};
const source=(await readFile(new URL('../src/experience/reportClient.ts',import.meta.url),'utf8'))
  .replace(/^import \{ API_BASE as base \} from .+;$/m,"const base='http://controlled.invalid';");
const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const api=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
elapsed=60000;
assert.equal((await api.prepareReport('case/one')).snapshot_id,'saved-snapshot');
assert.match(requests.at(-1).url,/case%2Fone\/reports\/prepare$/);
assert.equal(requests.at(-1).authorization,'Bearer controlled-reviewer');
elapsed=200000;
await assert.rejects(api.prepareReport('case-two'),/timed out/);
elapsed=60000;
await assert.rejects(api.fetchReportPdf('case-two','saved/snapshot'),/timed out/);
elapsed=0;
assert.deepEqual(await api.reportVersions('case-two'),[]);
assert.equal(timers.size,0);
console.log('Report preparation survives a simulated 60s generation; 180s generation and 45s download deadlines remain bounded. Case identity and reviewer authorization preserved.');
