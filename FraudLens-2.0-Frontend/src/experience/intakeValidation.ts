import { photoSlots } from './photoSlots';

export type PhotoValidation = {state:'checking'|'accepted'|'rejected'|'needs_replacement'|'unavailable'; reason:string; normalized_hash?:string; validation_version?:string};
export type ControlSnapshot = {name:string; value:string; label:string; missing:boolean; invalid:string};
export type Blocker = {reason:string; field?:string; slot?:string};

/** Read actual controls, including browser autofill and committed suggestions.
 * Native validity is read without checkValidity()'s invalid-event side effects. */
export function readControls(form: HTMLFormElement | null): ControlSnapshot[] {
  if (!form) return [];
  return Array.from(form.elements).flatMap(element => {
    if (!(element instanceof HTMLInputElement || element instanceof HTMLSelectElement || element instanceof HTMLTextAreaElement)
      || !element.name || !element.willValidate || element.type === 'file' || element.type === 'hidden'
      || element.closest('[hidden], [inert]')) return [];
    const label = element.labels?.[0]?.textContent?.replace(/\s*\*\s*$/, '').trim() || element.name;
    const value = element instanceof HTMLInputElement && element.type === 'checkbox' ? (element.checked ? element.value : '') : element.value;
    return [{name:element.name, value, label, missing:element.required && !value.trim(), invalid:element.validity.valid ? '' : element.validationMessage}];
  });
}

/** The same final validator drives the button, explanations and submit handler. */
export function submissionBlockers(kind:'claims'|'underwriting', controls:ControlSnapshot[], files:Record<string,File>, photos:Record<string,PhotoValidation>,
  options:{hydrated:boolean; busy:boolean; intake:boolean}):Blocker[] {
  const blockers:Blocker[] = [];
  if (!options.hydrated) blockers.push({reason:'Loading the application form.'});
  if (!options.intake) blockers.push({reason:'Applications are unavailable. Retry the connection shortly.'});
  if (options.busy) blockers.push({reason:'Submission is in progress. Wait for confirmation.'});
  const values = Object.fromEntries(controls.map(control=>[control.name,control.value]));
  for (const control of controls) {
    if (control.missing) blockers.push({field:control.name,reason:control.name === 'consent' ? 'Accept consent.' : `Enter ${control.label.toLowerCase()}.`});
    else if (control.invalid) blockers.push({field:control.name,reason:`${control.label}: ${control.invalid}`});
  }
  if (values.registration && !/^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$/.test(values.registration.replace(/\s+/g,'').toUpperCase())) blockers.push({field:'registration',reason:'Enter a valid Indian registration number, for example MH12AB1234.'});
  if (values.phone && values.phone.replace(/\D/g,'').length < 10) blockers.push({field:'phone',reason:'Enter a valid mobile number.'});
  if (kind === 'claims') {
    const latitude=values.latitude?.trim(), longitude=values.longitude?.trim();
    if (Boolean(latitude) !== Boolean(longitude)) blockers.push({field:latitude?'longitude':'latitude',reason:'Enter both incident coordinates, or leave both blank.'});
    if (values.bankLast4 && !/^[0-9]{4}$/.test(values.bankLast4)) blockers.push({field:'bankLast4',reason:'Bank account last four digits must be exactly four numbers.'});
    if (values.amount && Number(values.amount) <= 0) blockers.push({field:'amount',reason:'Enter a claimed amount greater than zero.'});
  }
  const checking=photoSlots[kind].filter(slot=>photos[slot.id]?.state === 'checking');
  if (checking.length) blockers.push({slot:checking[0].id,reason:`${checking.length} photo${checking.length===1?' is':'s are'} still being checked.`});
  const hashes = new Set<string>();
  for (const slot of photoSlots[kind]) {
    const file=files[slot.id], photo=photos[slot.id];
    if (!file) blockers.push({slot:slot.id,reason:`Upload ${slot.label.toLowerCase()}.`});
    else if (!['image/jpeg','image/png','image/webp'].includes(file.type) || !file.size || file.size>5*1024*1024) blockers.push({slot:slot.id,reason:`${slot.label}: choose a nonempty JPEG, PNG or WebP up to 5 MB.`});
    else if (!photo) blockers.push({slot:slot.id,reason:`Recheck ${slot.label.toLowerCase()}.`});
    else if (!['accepted','checking'].includes(photo.state)) blockers.push({slot:slot.id,reason:`${slot.label}: ${photo.reason}`});
    if (photo?.state==='accepted' && photo.normalized_hash) {
      if (hashes.has(photo.normalized_hash)) blockers.push({slot:slot.id,reason:`${slot.label}: choose a distinct photograph.`});
      hashes.add(photo.normalized_hash);
    }
  }
  return blockers;
}
