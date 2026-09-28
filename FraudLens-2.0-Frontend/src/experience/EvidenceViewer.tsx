import { useEffect, useRef, useState } from "react";
import { Icon } from "./shared";
export default function EvidenceViewer({
  image,
  onClose,
}: {
  image: { id: string; label: string; src?: string };
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const [zoom, setZoom] = useState(false);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    close.current?.focus();
    return () => {
      document.body.style.overflow = overflow;
      previous?.focus();
    };
  }, []);
  return (
    <div
      ref={dialog}
      className="evidence-viewer"
      role="dialog"
      aria-modal="true"
      aria-labelledby="evidence-viewer-title"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
        if (e.key === "Tab") {
          const controls = dialog.current?.querySelectorAll<HTMLButtonElement>("button");
          if (!controls?.length) return;
          const first = controls[0],
            last = controls[controls.length - 1];
          if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
          } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }}
    >
      <div className="evidence-viewer-toolbar">
        <div>
          <span>PRIVATE CASE EVIDENCE</span>
          <h2 id="evidence-viewer-title">{image.label}</h2>
        </div>
        <div>
          <button onClick={() => setZoom(!zoom)} aria-pressed={zoom}>
            {zoom ? "Fit image" : "Zoom image"}
            <Icon name="search" size={17} />
          </button>
          <button ref={close} onClick={onClose}>
            Close ×
          </button>
        </div>
      </div>
      <div className={"evidence-viewer-stage" + (zoom ? " zoomed" : "")}>
        <img src={image.src || ""} alt={image.label} />
      </div>
      <p>Original submitted photograph · No forensic annotations added</p>
    </div>
  );
}
