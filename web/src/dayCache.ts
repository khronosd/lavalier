// A day's view for a page that shows one conversation of it (Search, Starred): fetched once per day and kept
// while the data version stands; when it moves, the days are read again, the one on screen staying put
// until its new view arrives.

import { useEffect, useState } from "preact/hooks";
import { api, type DayView, explainError } from "./api";
import { useOnDataChange } from "./refresh";

const cache = new Map<string, DayView>();

export function forgetDays(): void {
  cache.clear();
}

type Load = { day: string | null; view: DayView | null; error: string | null };

export interface DayLoad {
  view: DayView | null;
  error: string | null;
  /** Keep a changed view (a pin) for this day. */
  update(view: DayView): void;
}

export function useDayView(day: string | null): DayLoad {
  const [state, setState] = useState<Load>({ day, view: null, error: null });
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    if (!day) {
      setState({ day, view: null, error: null });
      return;
    }
    const cached = cache.get(day);
    if (cached) {
      setState({ day, view: cached, error: null });
      return;
    }
    let live = true;
    // a read again after the data moved keeps the view on screen; a new day starts empty
    setState((s) => (s.day === day && s.view ? { ...s, error: null } : { day, view: null, error: null }));
    api<DayView>("GET", `/api/day/${day}`).then(
      (view) => {
        cache.set(day, view);
        if (live) setState({ day, view, error: null });
      },
      (e) => { if (live) setState({ day, view: null, error: explainError(e, "This day") }); },
    );
    return () => { live = false; };
  }, [day, generation]);

  useOnDataChange(() => {
    cache.clear();
    setGeneration((n) => n + 1);
  });

  return {
    view: state.day === day ? state.view : null,
    error: state.day === day ? state.error : null,
    update(view) {
      cache.set(view.day, view);
      setState((s) => (s.day === view.day ? { ...s, view } : s));
    },
  };
}
