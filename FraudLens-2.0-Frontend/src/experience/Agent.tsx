import { claimsAfterApply, underwritingAfterApply } from "./after-apply";
import { reconEvidence, sentinelEvidence } from "./agent-evidence";
import { Shell, Mark, Icon, Safety } from "./shared";
export default function Agent({ kind }: { kind: "claims" | "underwriting" }) {
  const claims = kind === "claims";
  const name = claims ? "Recon" : "Sentinel";
  return (
    <Shell active={claims ? "Claims" : "Underwriting"}>
      <div className={claims ? "agent-page recon" : "agent-page sentinel"}>
        <section className="agent-hero wrap">
          <div>
            <span className="eyebrow">
              {claims ? "First Notice of Loss" : "Policy issuance · Renewal · Break-in Inspection"}
            </span>
            <h1>Agent {name}</h1>
            <h2>
              {claims
                ? "Investigate the claim. Understand the evidence."
                : "Verify the vehicle. Protect the baseline."}
            </h2>
            <p>
              {claims
                ? "Did this loss happen as described? Recon connects damage photographs with case history, physical context and the declared claim."
                : "Is this the vehicle as it is today? Sentinel verifies current condition before a policy is issued or renewed."}
            </p>
            <a className="agent-apply" href={"/apply/" + kind}>
              Apply for {claims ? "Claims" : "Underwriting"} <Icon name="arrow" size={19} />
            </a>
          </div>
          <div className="agent-environment">
            <div className="agent-environment-top">
              <Icon name={claims ? "scan" : "shield"} size={18} />
              <span>{claims ? "CLAIMS INTELLIGENCE" : "UNDERWRITING INTELLIGENCE"}</span>
            </div>
            <Mark kind={claims ? "recon" : "sentinel"} />
            <div className="agent-environment-bottom">
              <span>Agent {name}</span>
              <small>One shared evidence engine</small>
            </div>
            <div className="agent-capabilities">
              {(claims
                ? ["Case Memory", "Scene consistency", "Garage patterns"]
                : ["Plate verification", "View completeness", "Vehicle baseline"]
              ).map((x) => (
                <span key={x}>{x}</span>
              ))}
            </div>
          </div>
        </section>
        <div className="wrap">
          <Safety />
        </div>
        <section className="agent-explanation wrap">
          <h2>
            {claims
              ? "The photograph never lies. But it doesn't always tell the truth either."
              : "Before a policy exists, the truth about the vehicle already does."}
          </h2>
          <div>
            {claims ? (
              <>
                <p>
                  Every claim begins with an image — a dent, a scratch, a shattered light. Recon
                  looks closer.
                </p>
                <p>
                  It checks if this exact photo has been seen before. It calculates where the sun
                  actually stood at the hour the claim describes, and reads the shadows against it.
                  It watches for claims that quietly settle just below the line where a human
                  inspector would have to step in.
                </p>
                <p>
                  Recon builds the case. It never closes it. Every finding is handed to a person,
                  with the evidence laid bare.
                </p>
                <p>
                  <strong>Recon investigates. A human decides.</strong>
                </p>
              </>
            ) : (
              <>
                <p>
                  Sentinel stands at the door. Before a policy is issued or a lapsed one renewed, it
                  looks at what's actually there — every angle, every panel, the odometer, the
                  plate.
                </p>
                <p>
                  A hidden dent today becomes an impossible claim tomorrow. Sentinel exists to make
                  sure the baseline is real, because everything the policy protects is built on it.
                </p>
                <p>
                  When something's unclear, Sentinel doesn't accuse. It asks for one more
                  photograph.
                </p>
                <p>
                  <strong>Sentinel verifies. Nothing moves forward on a lie.</strong>
                </p>
              </>
            )}
          </div>
        </section>
        <section className="agent-checks wrap">
          <div className="section-heading">
            <h2>
              {claims ? "The evidence Recon investigates." : "The evidence Sentinel verifies."}
            </h2>
            <p>Pass. Inconclusive. Concern. Genuine uncertainty is never treated as suspicious.</p>
          </div>
          <div className="check-grid">
            {(claims ? reconEvidence : sentinelEvidence).map(([title, cat, desc, limit]) => (
              <article key={title}>
                <div>
                  <Icon
                    name={
                      cat === "Context"
                        ? "sun"
                        : cat === "Identity"
                          ? "car"
                          : cat === "History"
                            ? "layers"
                            : "file"
                    }
                  />
                  <span>{cat}</span>
                </div>
                <h3>{title}</h3>
                <p>{desc}</p>
                <small>{limit}</small>
              </article>
            ))}
          </div>
        </section>
        <section className="next-section wrap">
          <h2>What happens after you apply?</h2>
          <p className="after-apply-copy">{claims ? claimsAfterApply : underwritingAfterApply}</p>
          <a className="agent-apply track-case-button" href="/track">
            Track a case <Icon name="arrow" size={20} />
          </a>
        </section>
      </div>
    </Shell>
  );
}
