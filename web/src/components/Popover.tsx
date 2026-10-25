import type { ComponentChildren } from "preact";
import { useEffect, useRef } from "preact/hooks";

interface Props {
  open: boolean;
  onClose: () => void;
  /** "dialog" for a panel with its own controls (the pendant card); none for a folded column. */
  role?: "dialog";
  label?: string;
  class?: string;
  children: ComponentChildren;
}

/** A panel anchored under its `.popover-anchor` parent, right-aligned. Escape, or a click anywhere outside
 * (a clear scrim takes it), closes it. Nothing animates. */
export function Popover({ open, onClose, role, label, class: cls, children }: Props) {
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close.current(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);
  if (!open) return null;
  return (
    <>
      <div class="scrim clear" onClick={() => close.current()} />
      <div class={cls ? `popover ${cls}` : "popover"} role={role} aria-label={label}>{children}</div>
    </>
  );
}
