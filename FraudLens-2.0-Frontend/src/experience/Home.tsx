import IntelligenceEngine from "./IntelligenceEngine";
import IntroVideo from "./IntroVideo";
import { useState } from "react";
import { Shell, Mark, Icon, DualCTA, Closing, Safety, categories } from "./shared";
export default function Home() {
  const [category, setCategory] = useState("Identity");
  const descriptions: Record<string, string> = {
    Identity:
      "Does the vehicle match the record? Registration details are compared with the visible plate and policy declaration.",
    History:
      "Has this evidence appeared before? Case Memory connects earlier photographs, repeat claims and related entities.",
    Provenance:
      "What can the file tell us? Available metadata and content credentials are examined. Missing metadata stays neutral.",
    Context:
      "Does the scene support the story? Shadows, sun position, historical weather and inspection views provide context.",
    Economic:
      "Does the amount fit the evidence? Repair plausibility and garage-level Threshold Gaming patterns inform review.",
  };
  return (
    <Shell active="Home">
      <section className="hero wrap">
        <div className="hero-copy">
          <div className="eyebrow">
            <Icon name="scan" size={16} /> Insurance evidence intelligence
          </div>
          <h1>
            Investigate the evidence.
            <br />
            <span>Before money moves.</span>
          </h1>
          <p>
            Photographs trigger financial decisions. FraudLens 2.0 helps you understand the evidence
            behind them.
          </p>
          <DualCTA />
          <div className="hero-assurance">
            <Icon name="shield" size={17} />
            <span>Agents recommend. Humans decide.</span>
          </div>
        </div>
        <div className="hero-intelligence">
          <div className="visual-heading">
            <span>FRAUDLENS / EVIDENCE INTELLIGENCE</span>
            <span>INTRODUCTION</span>
          </div>
          <IntroVideo />
          <div className="visual-agent-row">
            <span className="recon">
              <i />
              Recon <small>Claims</small>
            </span>
            <span className="sentinel">
              <i />
              Sentinel <small>Underwriting</small>
            </span>
          </div>
          <div className="visual-caption">
            <Icon name="layers" size={17} /> Two specialized agents. One shared engine.
          </div>
        </div>
      </section>
      <div className="principle-strip">
        <span>
          <Icon name="shield" size={18} /> Human decisions
        </span>
        <span>
          <Icon name="file" size={18} /> Explainable findings
        </span>
        <span>
          <Icon name="layers" size={18} /> Shared Case Memory
        </span>
      </div>
      <section className="story wrap">
        <div className="section-heading">
          <span className="eyebrow">From a photograph to a decision</span>
          <h2>One image. More than one story.</h2>
          <p>A photograph is a starting point. Its context is what makes it useful.</p>
        </div>
        <IntelligenceEngine />
        <Safety />
      </section>
      <section className="agents wrap">
        <div className="section-heading">
          <h2>Two agents. One shared engine.</h2>
          <p>Different questions. The same commitment to explainable evidence.</p>
        </div>
        <div className="agent-grid">
          <article className="agent-card recon">
            <div className="agent-label">
              <span>CLAIMS INVESTIGATION</span>
              <Icon name="scan" size={19} />
            </div>
            <Mark />
            <div className="agent-capabilities">
              <span>Case Memory</span>
              <span>Scene consistency</span>
              <span>Threshold Gaming</span>
            </div>
            <div className="agent-copy">
              <h3>Agent Recon</h3>
              <p>
                Investigates damage photographs at First Notice of Loss. Connects the scene, the
                history and the claim.
              </p>
              <a href="/claims">
                Meet Agent Recon <Icon name="arrow" size={19} />
              </a>
            </div>
          </article>
          <article className="agent-card sentinel">
            <div className="agent-label">
              <span>UNDERWRITING VERIFICATION</span>
              <Icon name="shield" size={19} />
            </div>
            <Mark kind="sentinel" />
            <div className="agent-capabilities">
              <span>Plate verification</span>
              <span>View completeness</span>
              <span>Vehicle baseline</span>
            </div>
            <div className="agent-copy">
              <h3>Agent Sentinel</h3>
              <p>
                Verifies a vehicle before policy issuance or renewal. Builds a trustworthy baseline
                for everything that follows.
              </p>
              <a href="/underwriting">
                Meet Agent Sentinel <Icon name="arrow" size={19} />
              </a>
            </div>
          </article>
        </div>
      </section>
      <section className="how wrap" id="how-it-works">
        <div className="section-heading">
          <h2>A clear path to a considered decision.</h2>
          <p>Every finding is explained. Every final action is accountable.</p>
        </div>
        <div className="step-grid">
          {[
            [
              "upload",
              "Submit evidence",
              "Provide the details and vehicle photographs for your claim or inspection.",
            ],
            [
              "scan",
              "Agents investigate",
              "The Evidence Battery runs. The agent interprets findings and follows up.",
            ],
            [
              "file",
              "Findings are explained",
              "A readable report connects each recommendation to its evidence.",
            ],
            [
              "user",
              "A human decides",
              "An adjuster reviews the case and records the final action.",
            ],
          ].map(([icon, title, text], i) => (
            <article key={title}>
              <div className="step-top">
                <Icon name={icon} size={28} />
                <span>0{i + 1}</span>
              </div>
              <h3>{title}</h3>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </section>
      <section className="trust wrap">
        <div className="trust-intro">
          <Icon name="shield" size={29} />
          <h2>
            Designed for trust.
            <br />
            Accountable by design.
          </h2>
        </div>
        <div className="trust-items">
          <div>
            <strong>No autonomous rejection</strong>
            <p>Rejection is absent from the agent's action space.</p>
          </div>
          <div>
            <strong>Evidence with attribution</strong>
            <p>A garage pattern never becomes a claimant accusation.</p>
          </div>
          <div>
            <strong>An auditable process</strong>
            <p>Findings, recommendations and human actions stay distinct.</p>
          </div>
        </div>
        <small>
          Automated findings support human review. Detection depends on evidence quality and
          available checks; inconclusive results require further review.
        </small>
      </section>
      <section className="finding-section wrap">
        <div className="section-heading">
          <h2>Five perspectives. One complete picture.</h2>
          <p>Understand what a Finding means, and who or what it relates to.</p>
        </div>
        <div className="category-tabs" role="tablist" aria-label="Finding categories">
          {categories.map((c, i) => (
            <button
              id={"tab-" + c}
              aria-controls={"panel-" + c}
              aria-selected={category === c}
              tabIndex={category === c ? 0 : -1}
              role="tab"
              key={c}
              onKeyDown={(e) => {
                if (["ArrowLeft", "ArrowRight"].includes(e.key)) {
                  e.preventDefault();
                  const next = categories[(i + (e.key === "ArrowRight" ? 1 : 4)) % 5];
                  setCategory(next);
                  document.getElementById("tab-" + next)?.focus();
                }
              }}
              onClick={() => setCategory(c)}
            >
              <Icon name={["car", "clock", "file", "sun", "layers"][i]} />
              {c}
            </button>
          ))}
        </div>
        <div
          className="category-panel"
          id={"panel-" + category}
          role="tabpanel"
          aria-labelledby={"tab-" + category}
        >
          <h3>{category}</h3>
          <p>{descriptions[category]}</p>
          <a href="/about#evidence">
            Explore the Evidence Battery <Icon name="arrow" size={17} />
          </a>
        </div>
      </section>
      <Closing />
    </Shell>
  );
}
