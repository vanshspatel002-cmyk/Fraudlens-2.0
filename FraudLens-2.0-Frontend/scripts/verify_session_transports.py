"""Chrome transport regressions using explicit controlled network/clock fixtures.

This transpiles the actual frontend clients with the installed TypeScript
compiler and executes them in Chrome. No server, accounts or model calls.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def compiled_clients():
    configured = Path(os.environ.get('FRAUDLENS_NODE22_HOME',r'D:\tools\FraudLens-node22\node-v22.23.3-win-x64'))/'node.exe'
    node = str(configured) if configured.is_file() else shutil.which('node')
    if not node:
        raise RuntimeError('Install the supported Node runtime and frontend dependencies first.')
    compiler = '''const ts=require('typescript'),fs=require('fs'),result={};
    for(const [name,path] of Object.entries({customer:'src/experience/customer-api.ts',reports:'src/experience/reportClient.ts'})){
      const source=fs.readFileSync(path,'utf8').replaceAll('import.meta.env.VITE_API_BASE_URL',"'http://fixture.invalid'");
      const code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
      result[name]='data:text/javascript;base64,'+Buffer.from(code).toString('base64');
    }process.stdout.write(JSON.stringify(result));'''
    return json.loads(subprocess.check_output([node,'-e',compiler],cwd=ROOT,text=True))


def run():
    clients=compiled_clients()
    html='<!doctype html><html><body><script type="module">const customer=await import('+json.dumps(clients['customer'])+');const reports=await import('+json.dumps(clients['reports'])+');window.transportClients={customer,reports};</script></body></html>'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page()
        page.route('http://fixture.invalid/**', lambda route: route.fulfill(status=200,content_type='text/html',body=html))
        page.goto('http://fixture.invalid/__session-transports')
        page.wait_for_function('!!window.transportClients')
        result = page.evaluate('''async () => {
          const {customer,reports}=window.transportClients;
          const checks=[];
          const assert=(condition,label)=>{if(!condition)throw Error(label);checks.push(label);};
          const originalFetch=window.fetch, originalTimeout=window.setTimeout;
          const errorOf=promise=>promise.then(()=>'',error=>error.message);
          let release;
          const pendingBody=()=>new Promise(resolve=>{release=resolve;});
          const waitBody=async()=>{while(!release)await new Promise(resolve=>originalTimeout(resolve,0));};
          sessionStorage.setItem('fraudlens_admin_token','reviewer-fixture');
          sessionStorage.setItem('fraudlens_customer_token','old-customer-fixture');
          window.fetch=async()=>({ok:true,status:200,json:pendingBody});
          const lateCustomer=errorOf(customer.customerRequest('/v1/customer/cases'));
          await waitBody();
          sessionStorage.setItem('fraudlens_customer_token','new-customer-fixture');
          release({items:[{id:'prior-customer-private-case'}]});
          assert((await lateCustomer).includes('session changed'),'Customer response from an earlier session is rejected');
          assert(sessionStorage.getItem('fraudlens_customer_token')==='new-customer-fixture','New customer session survives a late response');
          release=undefined;
          const lateLogout=errorOf(customer.customerLogout()); await waitBody();
          sessionStorage.setItem('fraudlens_customer_token','newest-customer-fixture'); release({ok:true});
          await lateLogout;
          assert(sessionStorage.getItem('fraudlens_customer_token')==='newest-customer-fixture','Earlier logout cannot clear a newer customer login');
          let expired=0;window.addEventListener('fraudlens-customer-session-expired',()=>expired++);
          window.fetch=async()=>new Response(JSON.stringify({message:'Fixture expired'}),{status:401,headers:{'Content-Type':'application/json'}});
          await errorOf(customer.customerRequest('/v1/customer/cases'));
          assert(!sessionStorage.getItem('fraudlens_customer_token')&&expired===1,'Customer 401 clears only its affected session');
          assert(sessionStorage.getItem('fraudlens_admin_token')==='reviewer-fixture','Customer expiry preserves the reviewer session');
          release=undefined;
          window.fetch=async()=>({ok:true,status:200,json:pendingBody});
          const lateReport=errorOf(reports.prepareReport('fixture-case'));await waitBody();
          sessionStorage.setItem('fraudlens_admin_token','new-reviewer-fixture');release({snapshot_id:'private-old-report'});
          assert((await lateReport).includes('session changed'),'Report response from an earlier reviewer session is rejected');
          window.setTimeout=(callback,delay,...args)=>originalTimeout(callback,delay===45000?5:delay,...args);
          window.fetch=(_url,options)=>new Promise((_resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('Fixture abort','AbortError'))));
          const timeout=await errorOf(reports.prepareReport('fixture-case'));
          assert(timeout.includes('timed out')&&timeout.includes('saved analysis is intact'),'PDF requests time out with a recoverable saved-analysis message');
          window.fetch=originalFetch;window.setTimeout=originalTimeout;sessionStorage.clear();
          return checks;
        }''')
        browser.close()
        print(json.dumps({'passed':len(result),'checks':result,'fixtures':'Controlled fetch/body delay and shortened timeout; no live service requests.'},indent=2))


if __name__ == '__main__':
    run()
