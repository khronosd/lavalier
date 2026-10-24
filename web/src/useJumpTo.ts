import { useEffect } from "preact/hooks";
import { parseHash, replaceHash, toHash } from "./router";

/** How long a jumped-to line keeps its highlight before it fades. */
export const FLASH_MS = 1500;

/** Once the page is ready, bring the element with id `at` into view, flash it, and drop ?at= from the
 *  hash (in place, so a reload or Back does not jump again). An id not on the page only drops ?at=. */
export function useJumpTo(at: string | undefined, ready: boolean): void {
  useEffect(() => {
    if (!at || !ready) return;
    const target = document.getElementById(at);
    if (target) {
      target.scrollIntoView?.({ block: "center" });
      target.classList.add("flash");
      // not undone by an effect cleanup: dropping ?at= below re-renders with at undefined, and the
      // highlight must outlive that; on a detached element the removal is harmless
      setTimeout(() => target.classList.remove("flash"), FLASH_MS);
    }
    const current = parseHash(window.location.hash);
    if (current.query.at === at) {
      const query = Object.fromEntries(Object.entries(current.query).filter(([k]) => k !== "at"));
      replaceHash(toHash({ ...current, query }));
    }
  }, [at, ready]);
}
