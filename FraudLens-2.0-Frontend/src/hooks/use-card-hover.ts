import { useEffect } from "react";
const cards =
  ".hero-intelligence,.hero-video,.engine-source,.engine-core,.engine-domains>span,.agent-environment,.agent-card,.story-track,.decision-report,.safety,.trust,.trust-items>div,.category-panel,.category-tabs button,.step-grid article,.check-grid article,.mission,.values-grid article,.engine-layers article,.evidence-reference details,.upload-slot,.notice,.submitted,.tracker-result,.intake-form fieldset,.tracker form,.case-panel,.recommendation-panel,.action-panel,.admin-login,.admin-login form,.admin-preview,.case-table,.filter-box,.metric-grid article,.reference-row,.human-sign,.empty,.image-gallery button,.finding-group article,.trace article>div,.audit-list article,.ops-banner,.ops-metrics article,.ops-agent,.ops-assurance,.case-meta,.ud-panel,.ud-metrics article,.ud-agent,.ud-welcome,.ud-assurance,.ud-attention,.ud-connect form,.ud-faq";
export function useCardHover() {
  useEffect(() => {
    const tracked = new Set<HTMLElement>();
    const collect = () => {
      for (const el of tracked) if (!el.isConnected) tracked.delete(el);
      document.querySelectorAll<HTMLElement>(cards).forEach((el) => {
        if (tracked.has(el) || el.closest("header,footer")) return;
        tracked.add(el);
        el.setAttribute("data-card-hover", "");
        const context = el.closest(".recon,.sentinel,.claims,.underwriting");
        const blue = context?.matches(".sentinel,.underwriting");
        const red =
          context?.matches(".recon,.claims") || el.matches(".ops-agent:not(.underwriting)");
        el.style.setProperty("--card-hover", blue ? "var(--blue)" : red ? "var(--red)" : "#c4cbd6");
      });
    };
    collect();
    const mutation = new MutationObserver(collect);
    mutation.observe(document.body, { childList: true, subtree: true });
    return () => {
      mutation.disconnect();
      for (const el of tracked) {
        el.removeAttribute("data-card-hover");
        el.style.removeProperty("--card-hover");
      }
    };
  }, []);
}
