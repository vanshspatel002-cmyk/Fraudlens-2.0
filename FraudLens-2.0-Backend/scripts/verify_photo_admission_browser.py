"""Controlled browser contracts: every API request intercepted, no model/DB."""
import io,json,re,sys
from pathlib import Path
from urllib.parse import urlparse
from PIL import Image,ImageDraw
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.photo_admission import SLOTS

def main():
 output=ROOT/'outputs/photo_admission/browser';output.mkdir(parents=True,exist_ok=True)
 image=Image.new('RGB',(128,128),'blue');ImageDraw.Draw(image).rectangle((5,5,55,55),fill='white')
 buffer=io.BytesIO();image.save(buffer,format='PNG');photo=buffer.getvalue();results=[]
 with sync_playwright() as p:
  browser=p.chromium.launch(channel='chrome',headless=True)
  for kind in ['claims','underwriting']:
   for width in [1365,390]:
    context=browser.new_context(viewport={'width':width,'height':900},has_touch=width==390)
    context.add_init_script("sessionStorage.setItem('fraudlens_customer_token','controlled-no-authority');window.__revoked=[];const r=URL.revokeObjectURL;URL.revokeObjectURL=(u)=>{window.__revoked.push(u);r(u);};")
    pending=[];submitted=[];errors=[]
    headers={'Access-Control-Allow-Origin':'http://127.0.0.1:5173','Access-Control-Allow-Headers':'Authorization, Content-Type, Idempotency-Key','Access-Control-Allow-Methods':'GET,POST,OPTIONS'}
    def route_request(route):
     request=route.request;url=urlparse(request.url)
     if url.port==5173:route.continue_();return
     if url.hostname not in {'127.0.0.1','localhost'} or url.port!=8001:route.abort();return
     if request.method=='OPTIONS':route.fulfill(status=204,headers=headers);return
     if url.path=='/v1/customer/auth/session':route.fulfill(status=200,json={'user':'fictional@example.test'},headers=headers);return
     if url.path=='/v1/photos/validate':
      body=(request.post_data_buffer or b'').decode('latin1');filename=re.search(r'filename="([^"]+)"',body).group(1)
      slot=re.search(r'name="slot"\r?\n\r?\n([^\r\n]+)',body).group(1)
      state='rejected' if filename=='reject.png' else 'accepted'
      data=dict(slot=slot,state=state,reason='Controlled '+state+' result',normalized_hash=filename)
      if filename=='slow.png':pending.append((route,data));return
      route.fulfill(status=200,json=data,headers=headers);return
     if url.path=='/v1/cases':
      body=(request.post_data_buffer or b'').decode('latin1');submitted.append(body)
      route.fulfill(status=422,json={'message':'Controlled final rejection; details retained','details':[{'field':SLOTS[kind][-1],'reason':'Retake final slot'}]},headers=headers);return
     route.fulfill(status=501,json={'message':'No live API fallback permitted'},headers=headers);errors.append(url.path)
    context.route('**/*',route_request);page=context.new_page();page.on('pageerror',lambda e:errors.append(type(e).__name__))
    page.goto('http://127.0.0.1:5173/apply/'+kind,wait_until='domcontentloaded')
    expect(page.locator('.upload-item')).to_have_count(len(SLOTS[kind]),timeout=30000)
    inputs=page.locator('.upload-slot input[type=file]');submit=page.locator('.submit-case')
    expect(submit).to_be_disabled()
    def choose(index,name):inputs.nth(index).set_input_files({'name':name,'mimeType':'image/png','buffer':photo})
    choose(0,'reject.png');expect(page.locator('.upload-item').nth(0)).to_contain_text('rejected:')
    choose(0,'slow.png');expect(page.locator('.upload-item').nth(0)).to_contain_text('checking:')
    choose(0,'replacement.png');assert len(pending)==1
    pending.pop()[0].fulfill(status=200,json={'state':'accepted','reason':'Stale old result','normalized_hash':'slow'},headers=headers)
    expect(page.locator('.upload-item').nth(0)).to_contain_text('accepted:')
    expect(page.locator('.upload-item').nth(0)).to_contain_text('replacement.png')
    assert page.evaluate('window.__revoked.length')>0
    # Removing a checking image invalidates its delayed accepted response.
    choose(0,'slow.png');remove=page.get_by_role('button',name=re.compile('Remove .* photograph')).first
    remove.tap() if width==390 else remove.click()
    pending.pop()[0].fulfill(status=200,json={'state':'accepted','reason':'Stale removed image','normalized_hash':'removed'},headers=headers)
    expect(page.locator('.upload-item').nth(0)).to_contain_text('Required: choose one photograph.')
    for i in range(len(SLOTS[kind])):choose(i,f'valid-{i}.png')
    expect(page.get_by_text(f'{len(SLOTS[kind])} of {len(SLOTS[kind])} photographs accepted.',exact=True)).to_be_visible()
    choose(len(SLOTS[kind])-1,'valid-0.png')
    expect(page.locator('.upload-item').last).to_contain_text('already assigned')
    expect(submit).to_be_disabled()
    choose(len(SLOTS[kind])-1,f'valid-{len(SLOTS[kind])-1}.png')
    expect(page.get_by_text(f'{len(SLOTS[kind])} of {len(SLOTS[kind])} photographs accepted.',exact=True)).to_be_visible()
    expect(submit).to_be_disabled() # Other form requirements still apply.
    values={'name':'Fictional Photo Test','email':'fixture@example.test','phone':'9000000041','registration':'MH12EX1203','year':'2023','idv':'500000','amount':'20000','incidentDate':'2026-10-20','incidentTime':'12:00','description':'Fictional browser validation fixture.'}
    for field in page.locator('.intake-form input[required],.intake-form textarea[required],.intake-form select[required]').all():
     name=field.get_attribute('name');kind_input=field.get_attribute('type')
     if kind_input=='checkbox':field.check()
     elif field.evaluate('(e)=>e.tagName')=='SELECT':field.select_option(index=1)
     elif kind_input!='file':field.fill(values.get(name,'100' if kind_input=='number' else 'Fictional example'))
    expect(submit).to_be_enabled()
    inputs.first.set_input_files({'name':'disguised.txt','mimeType':'text/plain','buffer':b'not an image'})
    expect(page.locator('.upload-item').first).to_contain_text('rejected:')
    expect(submit).to_be_disabled()
    choose(0,'valid-final.png')
    expect(submit).to_be_enabled() # Recompute form readiness after replacing invalid bytes.
    first=inputs.first;first.focus();expect(first).to_be_focused()
    page.evaluate("const legend=[...document.querySelectorAll('legend')].find(e=>e.textContent.includes('Vehicle photographs'));const note=document.createElement('p');note.textContent='CONTROLLED BROWSER FIXTURE — model responses are simulated; these placeholder images do not qualify as vehicle photographs.';note.style.fontWeight='bold';legend.after(note);")
    page.screenshot(path=str(output/f'{kind}-{width}.png'),full_page=True)
    page.locator('fieldset').filter(has_text='05 / Vehicle photographs').screenshot(path=str(output/f'{kind}-photos-{width}.png'),style='header, .skip { visibility: hidden !important; }')
    submit.click();expect(page.get_by_text('Retake final slot',exact=False).first).to_be_visible()
    expect(submit).to_be_disabled();assert len(submitted)==1
    for slot in SLOTS[kind]:assert slot in submitted[0]
    assert submitted[0].count('name="images"')==len(SLOTS[kind])
    assert page.locator('input[name=name]').input_value()=='Fictional Photo Test'
    expect(page.get_by_text(f'{len(SLOTS[kind])-1} of {len(SLOTS[kind])} photographs accepted.',exact=True)).to_be_visible()
    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
    assert not errors,errors
    results.append({'kind':kind,'width':width,'exact_slots':len(SLOTS[kind]),'stale_replacement_removal':'passed','form_and_other_images_preserved':True,'keyboard_focus':True,'mobile_no_overflow':True,'javascript_errors':0,'real_model_calls':0})
    context.close()
  browser.close()
 (output/'results.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))

if __name__=='__main__':main()
