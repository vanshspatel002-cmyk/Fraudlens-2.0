import { useEffect, useState, type FormEvent } from "react";
import { Shell, Icon, Safety, useConfig, api } from "./shared";
const angles = [
  "Front left",
  "Front right",
  "Rear left",
  "Rear right",
  "Odometer",
  "Registration plate",
];
type SubmitResult = {
  id: string;
  job_id?: string;
  status?: string;
};
type JobResult = {
  status?: string;
  progress?: number;
  stage?: string;
  detail?: string;
};
const registrationPattern = /^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$/;
const maxUploadBytes = 5 * 1024 * 1024;
function Field({
  name,
  label,
  type = "text",
  required = true,
  options,
  min,
  max,
}: {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
  options?: string[];
  min?: string;
  max?: string;
}) {
  return (
    <label className="field">
      <span>
        {label}
        {required ? " *" : ""}
      </span>
      {options ? (
        <select name={name} required={required} defaultValue="">
          <option value="" disabled>
            Select an option
          </option>
          {options.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      ) : (
        <input
          name={name}
          type={type}
          required={required}
          maxLength={type === "text" ? 160 : undefined}
          min={min}
          max={max}
        />
      )}
    </label>
  );
}
export default function Intake({ kind }: { kind: "claims" | "underwriting" }) {
  const claims = kind === "claims",
    config = useConfig();
  const [files, setFiles] = useState<Record<string, File>>({}),
    [previews, setPreviews] = useState<Record<string, string>>({}),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [jobStatus, setJobStatus] = useState(""),
    [result, setResult] = useState<SubmitResult | null>(null);
  useEffect(() => {
    const urls = Object.fromEntries(
      Object.entries(files).map(([k, f]) => [k, URL.createObjectURL(f)]),
    );
    setPreviews(urls);
    return () => Object.values(urls).forEach(URL.revokeObjectURL);
  }, [files]);
  function choose(key: string, f?: File) {
    setError("");
    if (!f) return;
    if (!["image/jpeg", "image/png", "image/webp"].includes(f.type) || f.size > maxUploadBytes) {
      setError("Choose a JPG, PNG or WebP photograph under 5 MB.");
      return;
    }
    setFiles((old) => ({ ...old, [key]: f }));
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
  async function waitForJob(jobId: string) {
    const delays = [900, 1400, 2200, 3400, 5000, 5000, 5000, 5000];
    for (let i = 0; i < delays.length; i += 1) {
      const job = (await api("job?id=" + encodeURIComponent(jobId))) as JobResult;
      const pct = Math.round(Number(job.progress || 0) * 100);
      setJobStatus(
        job.status === "done"
          ? "Analysis queued successfully."
          : job.status === "failed"
            ? job.detail || "The background analysis failed."
            : `${job.stage || job.status || "queued"}${pct ? ` - ${pct}%` : ""}`,
      );
      if (job.status === "done") return;
      if (job.status === "failed") throw new Error(job.detail || "The background analysis failed.");
      await new Promise((resolve) => setTimeout(resolve, delays[i]));
    }
  }
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");
    setJobStatus("");
    if (!config?.intake) {
      setError(
        "Applications are not open yet. Vehicle-photo verification must be connected before a case can be accepted. Nothing has been submitted.",
      );
      return;
    }
    if (!claims && angles.some((a) => !files[a])) {
      setError("Upload all four corners, the odometer and the registration plate.");
      return;
    }
    if (!Object.keys(files).length) {
      setError("Upload at least one photograph of the vehicle.");
      return;
    }
    const validation = validate(e.currentTarget);
    if (validation) {
      setError(validation);
      return;
    }
    const data = new FormData(e.currentTarget);
    data.set("kind", kind);
    data.set(
      "registration",
      String(data.get("registration") || "")
        .replace(/\s+/g, "")
        .toUpperCase(),
    );
    Object.entries(files).forEach(([label, f]) => data.append("photo:" + label, f));
    setBusy(true);
    try {
      setJobStatus("Uploading and validating vehicle photographs...");
      const submitted = (await api("submit", { method: "POST", body: data })) as SubmitResult;
      setJobStatus("Case accepted. Waiting for background analysis...");
      if (submitted.job_id) await waitForJob(submitted.job_id);
      setResult(submitted);
    } catch (err) {
      setError((err as Error).message);
    } finally {
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
            <a href="/track">Already applied? Track a case →</a>
          </aside>
          {result ? (
            <section className="submitted">
              <Icon name="check" size={38} />
              <h2>Your case has been received.</h2>
              <p>Save this case ID:</p>
              <code>{result.id}</code>
              <p>
                Your vehicle photographs have been accepted. The evidence will be reviewed and an
                adjuster will record the final decision. A request for additional photographs will
                name exactly what is needed.
              </p>
              <a href={"/track?case=" + encodeURIComponent(result.id)}>Track this case →</a>
            </section>
          ) : (
            <form className="intake-form" onSubmit={submit}>
              {config && !config.intake && (
                <div className="notice">
                  Applications are not open yet. You can review the form; no case will be accepted
                  until vehicle-photo verification is available.
                </div>
              )}
              <fieldset>
                <legend>01 / {claims ? "Claimant" : "Applicant"} details</legend>
                <div className="form-grid">
                  <Field name="name" label="Full name" />
                  <Field name="email" label="Email address" type="email" />
                  <Field name="phone" label="Mobile number" type="tel" />
                  <Field name="license" label="Driving license number" required={claims} />
                  <label className="field full">
                    <span>Address *</span>
                    <textarea name="address" required maxLength={500} />
                  </label>
                </div>
              </fieldset>
              <fieldset>
                <legend>02 / Vehicle details</legend>
                <div className="form-grid">
                  <Field name="make" label="Make" />
                  <Field name="model" label="Model" />
                  <Field name="variant" label="Variant" />
                  <Field
                    name="year"
                    label="Manufacturing year"
                    type="number"
                    min="1950"
                    max="2027"
                  />
                  <Field name="registration" label="Registration number" />
                  <Field name="engine" label="Engine number" />
                  <Field name="chassis" label="Chassis number" />
                  <Field name="idv" label="Insured declared value (₹)" type="number" min="1" />
                </div>
              </fieldset>
              <fieldset>
                <legend>03 / Policy details</legend>
                <div className="form-grid">
                  <Field name="policy" label="Policy number" required={claims} />
                  <Field
                    name="policyType"
                    label="Policy type"
                    options={["Comprehensive", "Own damage", "Third party"]}
                  />
                  {!claims && (
                    <>
                      <Field
                        name="applicationType"
                        label="Application type"
                        options={["New policy", "Renewal", "Break-in Inspection"]}
                      />
                      <Field
                        name="previousPolicy"
                        label="Previous policy number (if renewing)"
                        required={false}
                      />
                    </>
                  )}
                  <Field
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
                      <Field name="incidentDate" label="Incident date" type="date" />
                      <Field name="incidentTime" label="Incident time (IST)" type="time" />
                      <Field name="location" label="Incident location" />
                      <Field name="amount" label="Claimed amount (₹)" type="number" min="1" />
                      <Field name="garage" label="Repair garage" required={false} />
                      <Field
                        name="settlement"
                        label="Settlement preference"
                        options={["Cashless", "Reimbursement"]}
                      />
                      <Field
                        name="bankLast4"
                        label="Bank account last four digits only"
                        required={false}
                      />
                    </>
                  ) : (
                    <Field
                      name="condition"
                      label="Declared vehicle condition"
                      options={[
                        "No visible damage",
                        "Existing damage disclosed",
                        "Unsure; inspection needed",
                      ]}
                    />
                  )}
                  <label className="field full">
                    <span>{claims ? "Describe the incident" : "Condition notes"} *</span>
                    <textarea name="description" required maxLength={3000} rows={4} />
                  </label>
                </div>
              </fieldset>
              <fieldset>
                <legend>05 / Vehicle photographs</legend>
                <p className="help">
                  Every image must be validated as a genuine vehicle photograph before acceptance.
                  Missing EXIF metadata is neutral.
                </p>
                <div className="upload-grid">
                  {(claims
                    ? [
                        "Damage overview",
                        "Damage close-up",
                        "Registration plate",
                        "Additional view",
                      ]
                    : angles
                  ).map((label) => (
                    <label className="upload-slot" key={label}>
                      {previews[label] ? (
                        <img src={previews[label]} alt={label + " preview"} />
                      ) : (
                        <Icon name="upload" size={25} />
                      )}
                      <strong>{label}</strong>
                      <span>{files[label] ? files[label].name : "Choose photograph"}</span>
                      <input
                        type="file"
                        accept="image/jpeg,image/png,image/webp"
                        onChange={(e) => choose(label, e.target.files?.[0])}
                        aria-label={"Upload " + label}
                      />
                    </label>
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
              <button className="submit-case" type="submit" disabled={busy}>
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
