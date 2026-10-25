import type { RefObject } from "preact";
import { useEffect, useState } from "preact/hooks";

/** The element's width in px, followed as it changes; 0 until it is measured (jsdom never measures).
 * `enabled` false skips measuring (the element is not mounted); a change to it measures again. */
export function useWidth(ref: RefObject<HTMLElement>, enabled = true): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!enabled || !el) return;
    const read = () => setWidth(el.clientWidth);
    read();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", read);
      return () => window.removeEventListener("resize", read);
    }
    const observer = new ResizeObserver(read);
    observer.observe(el);
    return () => observer.disconnect();
  }, [enabled]);
  return width;
}
