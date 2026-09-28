import { useEffect } from "react";
const units =
  ".hero-copy,.hero-intelligence,.intelligence-engine,.agent-environment,.agent-card,.story-track,.decision-report,.hero-video,.safety,.trust,.category-panel,.step-grid article,.check-grid article,.mission,.values-grid article,.engine-layers article,.evidence-reference details,.submitted,.tracker-result,.empty,.dual-cta,.agent-apply,.category-tabs";
export function useScrollReveal() {
  useEffect(() => {
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    const tracked = new Set<HTMLElement>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries)
          if (e.isIntersecting) {
            (e.target as HTMLElement).removeAttribute("data-reveal-pending");
            observer.unobserve(e.target);
          }
      },
      { threshold: 0.08, rootMargin: "0px 0px -28px 0px" },
    );
    const collect = () => {
      document
        .querySelectorAll<HTMLElement>(
          "main " +
            units.split(",").join(",main ") +
            ",main h1,main h2,main h3,main p,main .eyebrow",
        )
        .forEach((el) => {
          if (
            tracked.has(el) ||
            el.closest(".admin,.user-dashboard,header,footer,.intake-form,.tracker form") ||
            el.parentElement?.closest(units)
          )
            return;
          tracked.add(el);
          el.setAttribute("data-scroll-reveal", "");
          if (!reduced.matches && el.getBoundingClientRect().top > innerHeight * 0.9) {
            el.setAttribute("data-reveal-pending", "");
            observer.observe(el);
          }
        });
    };
    const show = () => {
      if (reduced.matches)
        for (const el of tracked) {
          el.removeAttribute("data-reveal-pending");
          observer.unobserve(el);
        }
    };
    collect();
    const mutation = new MutationObserver(collect);
    mutation.observe(document.body, { childList: true, subtree: true });
    reduced.addEventListener("change", show);
    return () => {
      observer.disconnect();
      mutation.disconnect();
      reduced.removeEventListener("change", show);
      for (const el of tracked) {
        el.removeAttribute("data-scroll-reveal");
        el.removeAttribute("data-reveal-pending");
      }
    };
  }, []);
}
