import { Icon } from "./shared";
/** Architecture illustration, never live telemetry. */
export default function IntelligenceEngine() {
  return (
    <div
      className="intelligence-engine"
      aria-label="Recon and Sentinel share the Evidence Battery, Agentic Adjudication and Case Memory"
    >
      <div className="engine-agents">
        <div className="engine-source recon">
          <Icon name="scan" />
          <span>
            Agent Recon<small>Claims investigation</small>
          </span>
        </div>
        <div className="engine-source sentinel">
          <Icon name="shield" />
          <span>
            Agent Sentinel<small>Underwriting verification</small>
          </span>
        </div>
      </div>
      <svg
        className="engine-paths"
        viewBox="0 0 800 80"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path className="recon-path" d="M200 0 V25 Q200 40 220 40 H380 Q400 40 400 60 V80" />
        <path className="sentinel-path" d="M600 0 V25 Q600 40 580 40 H420 Q400 40 400 60 V80" />
      </svg>
      <div className="engine-core">
        <div className="engine-core-mark">
          <Icon name="layers" size={30} />
        </div>
        <span className="eyebrow">One shared intelligence engine</span>
        <h3>Evidence becomes intelligence.</h3>
        <div className="engine-core-layers">
          <span>Deterministic Evidence Battery</span>
          <Icon name="arrow" size={18} />
          <span>Agentic Adjudication</span>
        </div>
        <div className="engine-memory">
          <Icon name="layers" size={16} /> Case Memory <span>Shared across both agents</span>
        </div>
      </div>
      <div className="engine-domains">
        {["Identity", "History", "Provenance", "Context", "Economic"].map((x) => (
          <span key={x}>{x}</span>
        ))}
      </div>
      <div className="engine-human">
        <Icon name="file" size={19} />
        <span>Explained findings</span>
        <Icon name="arrow" size={16} />
        <span>Agent recommendation</span>
        <Icon name="arrow" size={16} />
        <strong>
          <Icon name="user" size={19} /> Human decision
        </strong>
      </div>
    </div>
  );
}
