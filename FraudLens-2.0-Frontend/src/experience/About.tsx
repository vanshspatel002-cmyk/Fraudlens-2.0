import IntelligenceEngine from "./IntelligenceEngine";
import { Shell, Icon, Safety, Closing, checks, categories } from "./shared";
export default function About() {
  return (
    <Shell active="About">
      <section className="page-title wrap">
        <span className="eyebrow">Inside FraudLens 2.0</span>
        <h1>
          Evidence you can question.
          <br />
          Decisions you can explain.
        </h1>
        <p>An investigation and triage layer for photo-based motor insurance decisions in India.</p>
      </section>
      <section className="mission wrap">
        <h2>Our mission</h2>
        <p>
          Photographs increasingly stand in for physical inspection. But an image alone cannot
          establish when damage occurred, whether it is new, or whether the same photograph has
          appeared in another case.
        </p>
        <p>
          FraudLens 2.0 is designed to reduce repetitive photo review and help honest claimants move
          forward. It investigates evidence, explains uncertainty and gives the human reviewer a
          clear basis for a decision.
        </p>
        <Safety />
      </section>
      <section className="values wrap">
        <h2>The principles behind every case.</h2>
        <div className="values-grid">
          {[
            [
              "shield",
              "Human accountability",
              "The AI has no rejection option. Approve, Reject and Request More Evidence belong to a human adjuster.",
            ],
            [
              "file",
              "Explainability",
              "Each Finding includes a Verdict, confidence, evidence, a plain-language explanation and attributed_to.",
            ],
            [
              "eye",
              "Honest uncertainty",
              "Pass / Inconclusive / Concern keeps missing or uncertain evidence from becoming an accusation.",
            ],
            [
              "lock",
              "Appropriate access",
              "The public tracker shows only status, final outcome and a public explanation. Private evidence stays in the admin workspace.",
            ],
          ].map(([icon, title, text]) => (
            <article key={title}>
              <Icon name={icon} size={27} />
              <h3>{title}</h3>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </section>
      <section className="engine wrap">
        <h2>One engine. Two policies.</h2>
        <IntelligenceEngine />
        <div className="engine-layers">
          <article>
            <span>01 / SHARED FOUNDATION</span>
            <h3>Deterministic Evidence Battery</h3>
            <p>
              A fixed battery of checks for each case type produces structured findings. The same
              inputs follow the same checks.
            </p>
          </article>
          <Icon name="arrow" />
          <article>
            <span>02 / REASONING LAYER</span>
            <h3>Agentic Adjudication</h3>
            <p>
              The agent interprets findings, resolves contradictions and chooses follow-up tools
              within a bounded number of steps.
            </p>
          </article>
        </div>
        <p>
          Both agents share Case Memory and a Perception Record for each unique image. Recon favors
          investigation when evidence is ambiguous; Sentinel favors a targeted request for more
          photographs. If reasoning cannot converge, the safe recommendation is Desk Review.
        </p>
      </section>
      <section className="evidence-reference wrap" id="evidence">
        <h2>What the evidence can tell us.</h2>
        <p>
          Five finding categories organize the Evidence Battery. Check weights and measured
          reliability are not published until evaluated.
        </p>
        {categories.map((c) => (
          <details key={c}>
            <summary>
              {c}
              <span>+</span>
            </summary>
            {checks
              .filter((x) => x[1] === c)
              .map(([title, , , desc, limit]) => (
                <div className="reference-row" key={title}>
                  <h3>{title}</h3>
                  <p>{desc}</p>
                  <small>{limit}</small>
                </div>
              ))}
          </details>
        ))}
      </section>
      <section className="india wrap">
        <h2>Built around the Indian insurance context.</h2>
        <p>
          The research focuses on photo-led cases, including a preserved ₹50,000 billing
          benchmark and garage-level Threshold Gaming. It explores documentation and
          auditability needs; regulatory applicability remains unverified.
        </p>
        <p>
          This is a research context, not a claim of regulatory certification. Applicable survey
          requirements and insurer procedures must be verified for each deployment.
        </p>
      </section>
      <Closing />
    </Shell>
  );
}
