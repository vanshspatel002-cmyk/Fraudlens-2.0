import { useEffect } from "react";
const targets =
  ".ud-agent,.ud-panel,.ud-metrics article,.ops-agent,.ops-metrics article,.agent-card,.story-track,.decision-report,.hero-video,.safety,.trust,.category-panel,.step-grid article,.check-grid article,.mission,.values-grid article,.engine-layers article,.evidence-reference details,.upload-slot,.notice,.submitted,.tracker-result,.case-panel,.recommendation-panel,.action-panel,.admin-login,.admin-preview,.case-table,.filter-box,.metric-grid article,.reference-row,.human-sign,.empty,.dual-cta a,.agent-apply,.submit-case,.track-submit,.track-nav,.category-tabs button,.image-gallery button,.admin-signin,.record-action,.admin-sidebar button,.field input,.field select,.field textarea,.case-table tbody tr";
export function useTouchHighlight() {
  useEffect(() => {
    let active: Element | null = null;
    let finger: {
      id: number;
      x: number;
      y: number;
      startX: number;
      startY: number;
      scrollY: number;
      sliding: boolean;
      cancelled: boolean;
    } | null = null;
    let frame = 0;
    let settle: ReturnType<typeof setTimeout> | undefined;
    const highlight = (next: Element | null) => {
      if (next === active) return;
      active?.removeAttribute("data-touch-highlight");
      if (active instanceof HTMLElement) {
        active.style.removeProperty("--touch-x");
        active.style.removeProperty("--touch-y");
      }
      active = next;
      active?.setAttribute("data-touch-highlight", "");
    };
    const clear = () => {
      cancelAnimationFrame(frame);
      frame = 0;
      clearTimeout(settle);
      finger = null;
      highlight(null);
    };
    const paint = () => {
      frame = 0;
      if (!finger?.sliding) return;
      let next: Element | null = null;
      for (const element of document.elementsFromPoint(finger.x, finger.y)) {
        const card = element.closest(targets);
        if (card && !card.matches(':disabled,[aria-disabled="true"]')) {
          next = card;
          break;
        }
      }
      highlight(next);
      if (next instanceof HTMLElement) {
        const rect = next.getBoundingClientRect();
        next.style.setProperty("--touch-x", `${finger.x - rect.left}px`);
        next.style.setProperty("--touch-y", `${finger.y - rect.top}px`);
      }
      // Continue hit testing as the compositor scrolls beneath a stationary finger.
      if (finger && !finger.cancelled) frame = requestAnimationFrame(paint);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(paint);
    };
    const start = (e: TouchEvent) => {
      clear();
      if (e.touches.length !== 1) return;
      const t = e.touches[0];
      finger = {
        id: t.identifier,
        x: t.clientX,
        y: t.clientY,
        startX: t.clientX,
        startY: t.clientY,
        scrollY: window.scrollY,
        sliding: false,
        cancelled: false,
      };
    };
    const move = (e: TouchEvent) => {
      if (!finger) return;
      if (e.touches.length !== 1) {
        clear();
        return;
      }
      const t = Array.from(e.touches).find((t) => t.identifier === finger?.id);
      if (!t) return;
      finger.x = t.clientX;
      finger.y = t.clientY;
      if (Math.hypot(t.clientX - finger.startX, t.clientY - finger.startY) > 6)
        finger.sliding = true;
      if (finger.sliding) schedule();
    };
    const scroll = () => {
      if (!finger) return;
      // Native scrolling can take over before another touchmove is delivered.
      if (Math.abs(window.scrollY - finger.scrollY) > 2) finger.sliding = true;
      if (finger.sliding) schedule();
      if (finger.cancelled) {
        clearTimeout(settle);
        settle = setTimeout(clear, 180);
      }
    };
    const cancel = () => {
      if (!finger) return;
      finger.cancelled = true;
      clearTimeout(settle);
      settle = setTimeout(clear, 180);
    };
    const options = { passive: true, capture: true };
    document.addEventListener("touchstart", start, options);
    document.addEventListener("touchmove", move, options);
    document.addEventListener("touchend", clear, options);
    document.addEventListener("touchcancel", cancel, options);
    document.addEventListener("scroll", scroll, options);
    window.addEventListener("blur", clear);
    return () => {
      clear();
      document.removeEventListener("touchstart", start, true);
      document.removeEventListener("touchmove", move, true);
      document.removeEventListener("touchend", clear, true);
      document.removeEventListener("touchcancel", cancel, true);
      document.removeEventListener("scroll", scroll, true);
      window.removeEventListener("blur", clear);
    };
  }, []);
}
