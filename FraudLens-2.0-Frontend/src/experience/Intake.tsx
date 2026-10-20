import { useEffect, useRef, useState, type FormEvent } from "react";
import { Shell, Icon, Safety, useConfig, api } from "./shared";
import Field from "./FieldSuggestions";
import { sampleSuggestions, todayForInput, vehicleDependencyWarning } from "./sampleSuggestions";
import { CustomerGate } from "./CustomerSession";
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
  applicant_token?: string;
  status?: string;
};
type JobResult = {
  status?: string;
  progress?: number;
  stage?: string;
  detail?: string;
  provider_unavailable?: boolean;
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
  const samples = (name: string) => sampleSuggestions(name, { kind, ...vehicle });
  const vehicleWarning = vehicleDependencyWarning(vehicle.make, vehicle.model, vehicle.variant);
  const [files, setFiles] = useState<Record<string, File>>({}),
    [previews, setPreviews] = useState<Record<string, string>>({}),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [jobStatus, setJobStatus] = useState(""),
    [result, setResult] = useState<SubmitResult | null>(null),
    [submissionKey] = useState(() => (typeof crypto !== "undefined" ? crypto.randomUUID() : ""));
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
          ["done", "completed"].includes(job.status || "")
            ? job.provider_unavailable
              ? "Automated analysis could not complete. A reviewer will assess your evidence."
              : "Analysis complete. Awaiting a human decision."
            : ["failed", "interrupted"].includes(job.status || "")
              ? "Background analysis is incomplete. Your case is saved; check your dashboard for review and recovery updates."
              : `${job.stage || job.status || "queued"}${pct ? ` - ${pct}%` : ""}`,
        );
        if (["done", "completed", "failed", "interrupted"].includes(job.status || "")) return;
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
            <form className="intake-form" method="post" onSubmit={submit}>
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
                        label="Incident time (IST)"
                        type="time"
                      />
                      <Field
                        suggestions={samples("location")}
                        name="location"
                        label="Incident location"
                      />
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
                <p className="help">
                  Images are decoded and indexed. A local classifier requires at least one likely
                  vehicle view; it cannot establish authenticity. Missing EXIF metadata is neutral.
                  {!claims &&
                    " View labels are your declarations; this system does not verify six views of the same vehicle."}
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
                    <div className="upload-item" key={label}>
                      <label className="upload-slot">
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
                          onChange={(e) => {
                            choose(label, e.target.files?.[0]);
                            e.currentTarget.value = "";
                          }}
                          aria-label={"Upload " + label}
                        />
                      </label>
                      {files[label] && (
                        <button
                          className="upload-remove"
                          type="button"
                          onClick={() =>
                            setFiles((previous) => {
                              const next = { ...previous };
                              delete next[label];
                              return next;
                            })
                          }
                        >
                          Remove {label.toLowerCase()} photograph
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
              <button className="submit-case" type="submit" disabled={!hydrated || busy}>
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
