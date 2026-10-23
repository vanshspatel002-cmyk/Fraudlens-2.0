import { useEffect, useRef, useState, type FormEvent } from "react";
import { Shell, Icon, Safety, useConfig, api } from "./shared";
import Field from "./FieldSuggestions";
import { sampleSuggestions, todayForInput, vehicleDependencyWarning } from "./sampleSuggestions";
import { CustomerGate } from "./CustomerSession";
import {photoSlots} from './photoSlots';
import {customerFetch} from './customer-api';
import {terminalProcessing} from './reviewPresentation';
type PhotoValidation={state:'checking'|'accepted'|'rejected'|'needs_replacement';reason:string;normalized_hash?:string};
type SubmitResult = {
  id: string;
  job_id?: string;
  applicant_token?: string;
  status?: string;
};
type JobResult = {
  status?: string;
  progress?: number;
  stage?: string;
  detail?: string;
  provider_unavailable?: boolean;
  review_summary?: {customer_label?: string};
};
const registrationPattern = /^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$/;
const maxUploadBytes = 5 * 1024 * 1024;
function IntakeForm({ kind }: { kind: "claims" | "underwriting" }) {
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  const claims = kind === "claims",
    config = useConfig();
  const [vehicle, setVehicle] = useState({ make: "", model: "", variant: "" });
  const submissionInFlight = useRef(false);
  const slots=photoSlots[kind];
  const formRef=useRef<HTMLFormElement>(null);
  const [formReady,setFormReady]=useState(false);
  const [photoStates,setPhotoStates]=useState<Record<string,PhotoValidation>>({});
  const revisions=useRef<Record<string,number>>({});
  const validationQueue=useRef<Promise<void>>(Promise.resolve());
  useEffect(()=>()=>{Object.keys(revisions.current).forEach(key=>{revisions.current[key]++;});},[]);
  const accepted=slots.filter(slot=>photoStates[slot.id]?.state==='accepted').length;
  const photosReady=accepted===slots.length;
  function updateFormReady(){const form=formRef.current;if(form)setFormReady(form.checkValidity() && !validate(form));}
  function removePhoto(key:string){
    revisions.current[key]=(revisions.current[key]||0)+1;
    setFiles(old=>{const next={...old};delete next[key];return next;});
    setPhotoStates(old=>{const next={...old};delete next[key];return next;});
  }
  const samples = (name: string) => sampleSuggestions(name, { kind, ...vehicle });
  const vehicleWarning = vehicleDependencyWarning(vehicle.make, vehicle.model, vehicle.variant);
  const [files, setFiles] = useState<Record<string, File>>({}),
    [previews, setPreviews] = useState<Record<string, string>>({}),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [jobStatus, setJobStatus] = useState(""),
    [result, setResult] = useState<SubmitResult | null>(null),
    [submissionKey] = useState(() => (typeof crypto !== "undefined" ? crypto.randomUUID() : ""));
  useEffect(()=>updateFormReady(),[files]);
  useEffect(() => {
    const urls = Object.fromEntries(
      Object.entries(files).map(([k, f]) => [k, URL.createObjectURL(f)]),
    );
    setPreviews(urls);
    return () => Object.values(urls).forEach(URL.revokeObjectURL);
  }, [files]);
  function choose(key: string, f?: File) {
    if(!f)return;
    setError('');const revision=(revisions.current[key]||0)+1;revisions.current[key]=revision;
    setFiles(old=>({...old,[key]:f}));
    if(!['image/jpeg','image/png','image/webp'].includes(f.type)||!f.size||f.size>maxUploadBytes){
      setPhotoStates(old=>({...old,[key]:{state:'rejected',reason:'Choose a nonempty JPEG, PNG or WebP up to 5 MB.'}}));return;
    }
    setPhotoStates(old=>({...old,[key]:{state:'checking',reason:'Waiting for local vehicle and slot validation…'}}));
    validationQueue.current=validationQueue.current.catch(()=>{}).then(async()=>{
      if(revisions.current[key]!==revision)return;
      const body=new FormData();body.set('agent_type',kind);body.set('slot',key);body.set('image',f,f.name);
      let result:PhotoValidation;
      try{
        result=await (await customerFetch('/v1/photos/validate',{method:'POST',body})).json() as PhotoValidation;
        if(!['accepted','rejected','needs_replacement'].includes(result.state))throw new Error('Validation did not return a usable result. Retry this photograph.');
      }catch(error){result={state:'needs_replacement',reason:(error as Error).message};}
      if(revisions.current[key]!==revision)return;
      setPhotoStates(old=>{
        if(result.state==='accepted' && result.normalized_hash && Object.entries(old).some(([slot,v])=>slot!==key && v.state==='accepted' && v.normalized_hash===result.normalized_hash))
          result={...result,state:'rejected',reason:'This exact photograph is already assigned to another slot. Choose a distinct photograph.'};
        return {...old,[key]:result};
      });
    });
  }
  function validate(form: HTMLFormElement) {
    const data = new FormData(form);
    const registration = String(data.get("registration") || "")
      .replace(/\s+/g, "")
      .toUpperCase();
    if (!registrationPattern.test(registration)) {
      return "Enter a valid Indian registration number, for example MH12AB1234.";
    }
    const phone = String(data.get("phone") || "").replace(/\D/g, "");
    if (phone.length < 10) return "Enter a valid mobile number.";
    const bankLast4 = String(data.get("bankLast4") || "");
    const latitude=String(data.get('latitude')||'').trim(),longitude=String(data.get('longitude')||'').trim();
    if(Boolean(latitude)!==Boolean(longitude))return 'Enter both incident coordinates, or leave both blank.';
    if(latitude && (!Number.isFinite(Number(latitude)) || Math.abs(Number(latitude))>90 || !Number.isFinite(Number(longitude)) || Math.abs(Number(longitude))>180))return 'Latitude must be -90 to 90; longitude -180 to 180.';
    if (bankLast4 && !/^[0-9]{4}$/.test(bankLast4)) {
      return "Bank account last four digits must be exactly four numbers.";
    }
    if (claims && Number(data.get("amount") || 0) <= 0) {
      return "Enter a claimed amount greater than zero.";
    }
    for (const file of Object.values(files)) {
      if (
        !["image/jpeg", "image/png", "image/webp"].includes(file.type) ||
        file.size > maxUploadBytes
      ) {
        return "Every upload must be a JPG, PNG or WebP photograph under 5 MB.";
      }
    }
    return "";
  }
  useEffect(() => {
    if (!result?.job_id) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    const delays = [900, 1400, 2200, 3400, 5000, 5000, 5000, 5000];
    async function poll() {
      try {
        const job = (await api("job?id=" + encodeURIComponent(result!.job_id!))) as JobResult;
        if (stopped) return;
        const pct = Math.round(Number(job.progress || 0) * 100);
        setJobStatus(
          job.review_summary?.customer_label || (job.status==='completed_partial' ? 'Your application is saved and awaiting review.' : ["done", "completed"].includes(job.status || "")
            ? job.provider_unavailable
              ? "Automated analysis could not complete. A reviewer will assess your evidence."
              : "Analysis complete. Awaiting a human decision."
            : ["failed", "interrupted"].includes(job.status || "")
              ? "Background analysis is incomplete. Your case is saved; check your dashboard for review and recovery updates."
              : `${job.stage || job.status || "queued"}${pct ? ` - ${pct}%` : ""}`),
        );
        if (terminalProcessing(job.status)) return;
        attempts += 1;
        if (attempts < delays.length) timer = setTimeout(poll, delays[attempts]);
        else
          setJobStatus(
            "Your case is saved and processing continues. Follow progress in your dashboard.",
          );
      } catch {
        if (!stopped)
          setJobStatus("Your case is saved. Open your dashboard to refresh its processing status.");
      }
    }
    timer = setTimeout(poll, delays[0]);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [result]);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submissionInFlight.current || result) return;
    setError("");
    setJobStatus("");
    if (!config?.intake) {
      setError(
        "Applications are not open yet. Vehicle-photo verification must be connected before a case can be accepted. Nothing has been submitted.",
      );
      return;
    }
    if(!photosReady){setError(`${claims?'Claims':'Underwriting'} require ${slots.length} accepted photographs.`);return;}
    const validation = validate(e.currentTarget);
    if (validation) {
      setError(validation);
      return;
    }
    const data = new FormData(e.currentTarget);
    data.set("submissionKey", submissionKey);
    data.set("kind", kind);
    data.set(
      "registration",
      String(data.get("registration") || "")
        .replace(/\s+/g, "")
        .toUpperCase(),
    );
    Object.entries(files).forEach(([label, f]) => data.append("photo:" + label, f));
    submissionInFlight.current = true;
    setBusy(true);
    try {
      setJobStatus("Uploading and validating vehicle photographs...");
      const submitted = (await api("submit", { method: "POST", body: data })) as SubmitResult;
      setResult(submitted);
      setJobStatus(
        "Case accepted and queued for background analysis. A reviewer has not made a decision yet.",
      );
    } catch (err) {
      setError((err as Error).message);
      setJobStatus("");
      const details=(err as Error & {details?:{field?:string;reason?:string}[]}).details;
      if(Array.isArray(details))setPhotoStates(old=>{
        const next={...old};
        details.forEach(item=>{if(item.field && slots.some(s=>s.id===item.field))next[item.field]={state:'needs_replacement',reason:item.reason||'Replace this photograph.'};});
        return next;
      });
    } finally {
      submissionInFlight.current = false;
      setBusy(false);
    }
  }
  return (
    <Shell>
      <div className={claims ? "intake-page recon" : "intake-page sentinel"}>
        <section className="page-title wrap">
          <a className="back-link" href={"/" + kind}>
            ← Agent {claims ? "Recon" : "Sentinel"}
          </a>
          <h1>Apply for {claims ? "Claims" : "Underwriting"}</h1>
          <p>
            {claims
              ? "Tell us what happened. Give the evidence its context."
              : "Help us establish an accurate picture of your vehicle today."}
          </p>
        </section>
        <div className="form-layout wrap">
          <aside className="intake-aside">
            <Icon name={claims ? "scan" : "shield"} size={35} />
            <h2>Before you begin</h2>
            <p>
              Keep your vehicle and policy details ready. Upload original, clear photographs where
              possible.
            </p>
            <ul>
              <li>No Aadhaar or PAN required</li>
              <li>Vehicle photographs only</li>
              <li>JPG, PNG or WebP, up to 5 MB each</li>
              <li>A human makes the final decision</li>
            </ul>
            <a href="/dashboard">Already applied? Open your dashboard →</a>
          </aside>
          {result ? (
            <section className="submitted">
              <Icon name="check" size={38} />
              <h2>Your case has been received.</h2>
              <p>Save this case ID:</p>
              <code>{result.id}</code>
              <p role="status">{jobStatus}</p>
              <details>
                <summary>Save your private evidence access receipt</summary>
                <p>
                  This receipt lets you upload requested photographs for 30 days. Keep it private.
                  It is saved in this tab's session.
                </p>
                <textarea
                  aria-label="Applicant access receipt"
                  readOnly
                  value={result.applicant_token || ""}
                  rows={3}
                />
              </details>
              {error && (
                <p role="alert">Your case is saved. Status could not be refreshed: {error}</p>
              )}
              <p>
                Your vehicle photographs have been accepted. The evidence will be reviewed and an
                adjuster will record the final decision. A request for additional photographs will
                name exactly what is needed.
              </p>
              <p>
                <a href={"/dashboard?case=" + encodeURIComponent(result.id)}>
                  View this case in your dashboard →
                </a>
              </p>
              <a href={"/track?case=" + encodeURIComponent(result.id)}>
                Track with a private receipt →
              </a>
            </section>
          ) : (
            <form ref={formRef} onInput={updateFormReady} onChange={updateFormReady} className="intake-form" method="post" onSubmit={submit}>
              {config && !config.intake && (
                <div className="notice">
                  Applications are not open yet. You can review the form; no case will be accepted
                  until vehicle-photo verification is available.
                </div>
              )}
              <fieldset>
                <legend>01 / {claims ? "Claimant" : "Applicant"} details</legend>
                <div className="form-grid">
                  <Field suggestions={samples("name")} name="name" label="Full name" />
                  <Field
                    suggestions={samples("email")}
                    name="email"
                    label="Email address"
                    type="email"
                  />
                  <Field
                    suggestions={samples("phone")}
                    name="phone"
                    label="Mobile number"
                    type="tel"
                  />
                  <Field
                    suggestions={samples("license")}
                    name="license"
                    label="Driving license number"
                    required={claims}
                  />
                  <Field
                    suggestions={samples("address")}
                    name="address"
                    label="Address"
                    full
                    multiline
                    maxLength={500}
                  />
                </div>
              </fieldset>
              <fieldset>
                <legend>02 / Vehicle details</legend>
                <div className="form-grid">
                  <Field
                    suggestions={samples("make")}
                    name="make"
                    label="Make"
                    onValueChange={(make) => setVehicle((previous) => ({ ...previous, make }))}
                  />
                  <Field
                    suggestions={samples("model")}
                    name="model"
                    label="Model"
                    warning={vehicleWarning}
                    onValueChange={(model) => setVehicle((previous) => ({ ...previous, model }))}
                  />
                  <Field
                    suggestions={samples("variant")}
                    name="variant"
                    label="Variant"
                    onValueChange={(variant) =>
                      setVehicle((previous) => ({ ...previous, variant }))
                    }
                  />
                  <Field
                    suggestions={samples("year")}
                    name="year"
                    label="Manufacturing year"
                    type="number"
                    min="1950"
                    max={String(new Date().getFullYear() + 1)}
                  />
                  <Field
                    suggestions={samples("registration")}
                    name="registration"
                    label="Registration number"
                  />
                  <Field suggestions={samples("engine")} name="engine" label="Engine number" />
                  <Field suggestions={samples("chassis")} name="chassis" label="Chassis number" />
                  <Field
                    suggestions={samples("idv")}
                    name="idv"
                    label="Insured declared value (₹)"
                    type="number"
                    min="1"
                  />
                </div>
              </fieldset>
              <fieldset>
                <legend>03 / Policy details</legend>
                <div className="form-grid">
                  <Field
                    suggestions={samples("policy")}
                    name="policy"
                    label="Policy number"
                    required={claims}
                  />
                  <Field
                    suggestions={samples("policyType")}
                    name="policyType"
                    label="Policy type"
                    options={["Comprehensive", "Own damage", "Third party"]}
                  />
                  {!claims && (
                    <>
                      <Field
                        suggestions={samples("applicationType")}
                        name="applicationType"
                        label="Application type"
                        options={["New policy", "Renewal", "Break-in Inspection"]}
                      />
                      <Field
                        suggestions={samples("previousPolicy")}
                        name="previousPolicy"
                        label="Previous policy number (if renewing)"
                        required={false}
                      />
                    </>
                  )}
                  <Field
                    suggestions={samples("ncb")}
                    name="ncb"
                    label="No-claim bonus (%)"
                    type="number"
                    min="0"
                    max="100"
                    required={false}
                  />
                </div>
              </fieldset>
              <fieldset>
                <legend>04 / {claims ? "Incident" : "Condition"} declaration</legend>
                <div className="form-grid">
                  {claims ? (
                    <>
                      <Field
                        suggestions={samples("incidentDate")}
                        name="incidentDate"
                        label="Incident date"
                        type="date"
                        max={todayForInput()}
                      />
                      <Field
                        suggestions={samples("incidentTime")}
                        name="incidentTime"
                        label="Incident local time"
                        type="time"
                      />
                      <Field
                        suggestions={samples("location")}
                        name="location"
                        label="Incident location"
                      />
                      <label className="field"><span>Incident UTC offset</span>
                        <select name="incidentOffset" defaultValue="+05:30" required>
                          <option value="+05:30">UTC +05:30 (India)</option>
                          <option value="+00:00">UTC +00:00</option>
                          <option value="+01:00">UTC +01:00</option>
                          <option value="+02:00">UTC +02:00</option>
                          <option value="+03:00">UTC +03:00</option>
                          <option value="+09:00">UTC +09:00 (Japan)</option>
                          <option value="-04:00">UTC -04:00</option>
                          <option value="-05:00">UTC -05:00</option>
                        </select>
                      </label>
                      <Field name="latitude" label="Incident latitude (optional)" type="number" min="-90" max="90" step="any" required={false}/>
                      <Field name="longitude" label="Incident longitude (optional)" type="number" min="-180" max="180" step="any" required={false}/>
                      <p className="help">Enter both coordinates from a known map pin, or leave both blank. These are your incident declarations, not independently verified GPS. Confirm the UTC offset for the incident date; location text does not generate coordinates.</p>
                      <Field
                        suggestions={samples("amount")}
                        name="amount"
                        label="Claimed amount (₹)"
                        type="number"
                        min="1"
                      />
                      <Field
                        suggestions={samples("garage")}
                        name="garage"
                        label="Repair garage"
                        required={false}
                      />
                      <Field
                        suggestions={samples("settlement")}
                        name="settlement"
                        label="Settlement preference"
                        options={["Cashless", "Reimbursement"]}
                      />
                      <Field
                        suggestions={samples("bankLast4")}
                        name="bankLast4"
                        label="Bank account last four digits only"
                        required={false}
                      />
                    </>
                  ) : (
                    <Field
                      suggestions={samples("condition")}
                      name="condition"
                      label="Declared vehicle condition"
                      options={[
                        "No visible damage",
                        "Existing damage disclosed",
                        "Unsure; inspection needed",
                      ]}
                    />
                  )}
                  <Field
                    suggestions={samples("description")}
                    name="description"
                    label={claims ? "Describe the incident" : "Condition notes"}
                    full
                    multiline
                    maxLength={3000}
                    rows={4}
                  />
                </div>
              </fieldset>
              <fieldset>
                <legend>05 / Vehicle photographs</legend>
                <p className="help">{claims?'Claims require 4 accepted photographs.':'Underwriting requires 6 accepted photographs.'} Each slot is checked separately. Passing does not prove authenticity, ownership, capture date or that all views show one vehicle. Missing EXIF is neutral.</p>
                <p role="status">{accepted} of {slots.length} photographs accepted.</p>
                <div className="upload-grid">
                  {slots.map(({id:label,label:title,instruction}) => (
                    <div className="upload-item" key={label}>
                      <label className="upload-slot">
                        {previews[label] ? (
                          <img src={previews[label]} alt={label + " preview"} />
                        ) : (
                          <Icon name="upload" size={25} />
                        )}
                        <strong>{title} — required</strong>
                        <span style={{whiteSpace:'normal',overflow:'visible',textOverflow:'clip',overflowWrap:'anywhere'}}>{instruction}</span>
                        <span style={{whiteSpace:'normal',overflow:'visible',textOverflow:'clip',overflowWrap:'anywhere'}}>{files[label] ? 'Replace photograph: '+files[label].name : "Choose photograph"}</span>
                        <input
                          type="file"
                          accept="image/jpeg,image/png,image/webp"
                          onChange={(e) => {
                            choose(label, e.target.files?.[0]);
                            e.currentTarget.value = "";
                          }}
                          aria-label={"Upload " + title}
                        />
                      </label>
                      <p role="status" aria-live="polite">{photoStates[label] ? `${photoStates[label].state.replaceAll('_',' ')}: ${photoStates[label].reason}` : 'Required: choose one photograph.'}</p>
                      {files[label] && photoStates[label]?.state!=='checking' && <button type="button" onClick={()=>choose(label,files[label])}>Recheck {title.toLowerCase()}</button>}
                      {files[label] && (
                        <button
                          className="upload-remove"
                          type="button"
                          onClick={() => removePhoto(label)}
                        >
                          Remove {title.toLowerCase()} photograph
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </fieldset>
              <label className="consent">
                <input type="checkbox" name="consent" required value="yes" />
                <span>
                  I confirm these details are accurate and consent to processing this evidence for
                  case review.
                </span>
              </label>
              <Safety />
              {error && (
                <p className="form-error" role="alert">
                  {error}
                </p>
              )}
              {jobStatus && (
                <p className="notice" role="status">
                  {jobStatus}
                </p>
              )}
              <button className="submit-case" type="submit" disabled={!hydrated || busy || !photosReady || !formReady}>
                {busy
                  ? "Validating and submitting…"
                  : "Submit " + (claims ? "claim" : "application")}
                <Icon name="arrow" size={18} />
              </button>
              <p className="help">A case ID is issued only after the submission is accepted.</p>
            </form>
          )}
        </div>
      </div>
    </Shell>
  );
}

export default function Intake({ kind }: { kind: "claims" | "underwriting" }) {
  return (
    <CustomerGate>
      <IntakeForm kind={kind} />
    </CustomerGate>
  );
}
