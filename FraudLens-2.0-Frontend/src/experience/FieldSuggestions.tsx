import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import type { SampleSuggestion } from "./sampleSuggestions";
import "./field-suggestions.css";

type Props = {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
  options?: string[];
  min?: string;
  max?: string;
  maxLength?: number;
  multiline?: boolean;
  rows?: number;
  full?: boolean;
  suggestions?: SampleSuggestion[];
  onValueChange?: (value: string) => void;
  warning?: string;
};

const enabled = !["false", "0", "off"].includes(
  String(import.meta.env.VITE_SAMPLE_SUGGESTIONS ?? "true").toLowerCase(),
);
// Removing a portal can expose another field under the stationary pointer.
// Suppress that synthetic hover so selecting one value really closes its list.
let resumeHoverAt = 0;

/** One controlled field in the existing native FormData form. Portals keep the
 * list clear of fieldset clipping; no suggestion is selected automatically. */
export default function FieldSuggestions({
  name,
  label,
  type = "text",
  required = true,
  options,
  min,
  max,
  maxLength,
  multiline,
  rows,
  full,
  suggestions = [],
  onValueChange,
  warning,
}: Props) {
  const id = useId(),
    listId = `${id}-samples`,
    hintId = `${id}-hint`,
    warningId = `${id}-warning`;
  const [value, setValue] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [announcement, setAnnouncement] = useState("");
  const [position, setPosition] = useState({ left: 0, top: 0, width: 0, maxHeight: 260 });
  const control = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null);
  const wrapper = useRef<HTMLDivElement | null>(null),
    popup = useRef<HTMLDivElement | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const canSuggest = enabled && !options && suggestions.length > 0;
  const filtered = suggestions.filter((suggestion) =>
    `${suggestion.value} ${suggestion.label || ""}`
      .toLowerCase()
      .includes(value.trim().toLowerCase()),
  );
  const visible = open && canSuggest;
  const textCombobox = multiline || ["text", "email", "tel", "search", "url"].includes(type);

  function cancelClose() {
    clearTimeout(closeTimer.current);
  }
  function close() {
    cancelClose();
    setOpen(false);
    setActive(-1);
  }
  function reveal() {
    if (!canSuggest) return;
    cancelClose();
    window.dispatchEvent(new CustomEvent("fraudlens:suggestions-open", { detail: id }));
    setOpen(true);
  }
  function scheduleClose() {
    cancelClose();
    closeTimer.current = setTimeout(() => {
      if (
        !wrapper.current?.contains(document.activeElement) &&
        !popup.current?.contains(document.activeElement)
      )
        close();
    }, 180);
  }
  function select(suggestion: SampleSuggestion) {
    resumeHoverAt = Date.now() + 350;
    setValue(suggestion.value);
    onValueChange?.(suggestion.value);
    setAnnouncement(`Sample selected for ${label}. You can edit it.`);
    control.current?.focus({ preventScroll: true });
    close();
  }
  function navigate(event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) {
    if (!canSuggest) return;
    if (event.key === "Escape" && visible) {
      event.preventDefault();
      event.stopPropagation();
      close();
    } else if (event.key === "Tab") close();
    else if (["ArrowDown", "ArrowUp"].includes(event.key) && !event.nativeEvent.isComposing) {
      event.preventDefault();
      reveal();
      if (filtered.length)
        setActive((previous) =>
          event.key === "ArrowDown"
            ? (previous + 1) % filtered.length
            : previous <= 0
              ? filtered.length - 1
              : previous - 1,
        );
    } else if (
      event.key === "Enter" &&
      visible &&
      active >= 0 &&
      filtered[active] &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      select(filtered[active]);
    }
  }

  useEffect(() => () => clearTimeout(closeTimer.current), []);
  useEffect(() => {
    function otherOpened(event: Event) {
      if ((event as CustomEvent).detail !== id) close();
    }
    window.addEventListener("fraudlens:suggestions-open", otherOpened);
    return () => window.removeEventListener("fraudlens:suggestions-open", otherOpened);
  }, [id]);
  useEffect(() => {
    if (!visible) return;
    function positionList() {
      const rect = control.current?.getBoundingClientRect();
      if (!rect) return;
      const viewport = window.visualViewport;
      const topEdge = viewport?.offsetTop || 0,
        leftEdge = viewport?.offsetLeft || 0;
      const bottomEdge = topEdge + (viewport?.height || window.innerHeight);
      const rightEdge = leftEdge + (viewport?.width || window.innerWidth);
      const availableBelow = bottomEdge - rect.bottom - 12,
        availableAbove = rect.top - topEdge - 12;
      const above = availableBelow < 200 && availableAbove > availableBelow;
      const maxHeight = Math.max(80, Math.min(300, above ? availableAbove : availableBelow));
      const width = Math.min(Math.max(rect.width, 270), rightEdge - leftEdge - 16);
      const measuredHeight = Math.min(popup.current?.scrollHeight || 260, maxHeight);
      setPosition({
        left: Math.max(leftEdge + 8, Math.min(rect.left, rightEdge - width - 8)),
        top: above ? Math.max(topEdge + 8, rect.top - measuredHeight - 4) : rect.bottom + 4,
        width,
        maxHeight,
      });
    }
    function outside(event: PointerEvent) {
      if (
        !wrapper.current?.contains(event.target as Node) &&
        !popup.current?.contains(event.target as Node)
      )
        close();
    }
    positionList();
    window.addEventListener("resize", positionList);
    window.addEventListener("scroll", positionList, true);
    window.visualViewport?.addEventListener("resize", positionList);
    window.visualViewport?.addEventListener("scroll", positionList);
    document.addEventListener("pointerdown", outside);
    return () => {
      window.removeEventListener("resize", positionList);
      window.removeEventListener("scroll", positionList, true);
      window.visualViewport?.removeEventListener("resize", positionList);
      window.visualViewport?.removeEventListener("scroll", positionList);
      document.removeEventListener("pointerdown", outside);
    };
  }, [visible, filtered.length]);
  useEffect(() => {
    if (active >= filtered.length) setActive(-1);
  }, [filtered.length, active]);
  useEffect(() => {
    if (active >= 0)
      document.getElementById(`${listId}-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [active, listId]);

  const props = {
    id,
    name,
    required,
    value,
    maxLength: maxLength ?? (type === "text" ? 160 : undefined),
    onChange: (event: { target: { value: string } }) => {
      setValue(event.target.value);
      onValueChange?.(event.target.value);
      setActive(-1);
      reveal();
    },
    onFocus: reveal,
    onClick: reveal,
    onBlur: scheduleClose,
    onKeyDown: navigate,
    role: canSuggest && textCombobox ? "combobox" : undefined,
    "aria-autocomplete": canSuggest && textCombobox ? ("list" as const) : undefined,
    "aria-expanded": canSuggest && textCombobox ? visible : undefined,
    "aria-controls": visible ? listId : undefined,
    "aria-haspopup": canSuggest ? ("listbox" as const) : undefined,
    "aria-activedescendant": visible && active >= 0 ? `${listId}-${active}` : undefined,
    "aria-describedby":
      [canSuggest ? hintId : "", warning ? warningId : ""].filter(Boolean).join(" ") || undefined,
  };
  return (
    <div
      ref={wrapper}
      className={`field sample-field${full ? " full" : ""}`}
      onPointerEnter={(event) => {
        if (event.pointerType === "mouse" && Date.now() >= resumeHoverAt) reveal();
      }}
      onPointerLeave={scheduleClose}
    >
      <label htmlFor={id}>
        {label}
        {required ? " *" : ""}
      </label>
      {options ? (
        <select id={id} name={name} required={required} defaultValue="">
          <option value="" disabled>
            Select an option
          </option>
          {options.map((option) => (
            <option key={option}>{option}</option>
          ))}
        </select>
      ) : multiline ? (
        <textarea
          {...props}
          rows={rows}
          ref={(element) => {
            control.current = element;
          }}
        />
      ) : (
        <input
          {...props}
          type={type}
          min={min}
          max={max}
          ref={(element) => {
            control.current = element;
          }}
        />
      )}
      {canSuggest && (
        <span className="sample-sr-only" id={hintId}>
          Fictional sample suggestions available. Use arrow keys and Enter to select, or Escape to
          close. Keep or edit your own entry.
        </span>
      )}
      {warning && (
        <span className="sample-field-warning" id={warningId} role="status">
          {warning}
        </span>
      )}
      <span className="sample-sr-only" role="status" aria-live="polite">
        {announcement}
      </span>
      {visible &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            ref={popup}
            className="sample-popover"
            style={{ position: "fixed", ...position }}
            onPointerEnter={cancelClose}
            onPointerLeave={scheduleClose}
          >
            <div className="sample-popover-heading">
              Sample suggestions <span>Fictional · select one field</span>
            </div>
            <span className="sample-sr-only" role="status" aria-live="polite">
              {filtered.length} sample suggestions available for {label}.
            </span>
            <ul id={listId} role="listbox" aria-label={`Sample suggestions for ${label}`}>
              {filtered.map((suggestion, index) => (
                <li
                  key={suggestion.value}
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={index === active}
                  className={index === active ? "sample-option-active" : ""}
                  onPointerMove={() => setActive(index)}
                  onPointerDown={(event) => event.preventDefault()}
                  onClick={() => select(suggestion)}
                >
                  {suggestion.label || suggestion.value}
                </li>
              ))}
            </ul>
            {!filtered.length && (
              <p className="sample-no-matches" role="status">
                No matching samples. Keep typing your own value.
              </p>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}
