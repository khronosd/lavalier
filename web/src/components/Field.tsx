import { useEffect, useRef, useState } from "preact/hooks";

interface Props {
  name: string;
  label: string;
  /** The saved value as text. */
  value: string;
  help?: string;
  error?: string | null;
  number?: boolean;
  /** Save on blur or Enter only, never while typing (an endpoint or a model id is not worth saving half typed). */
  blurOnly?: boolean;
  /** Called with the typed text when it should be saved: on blur, on Enter, and 300 ms after typing stops (text only). */
  onCommit: (text: string) => Promise<boolean> | void;
  /** Called on every keystroke, for text elsewhere on the page that follows the field. */
  onInput?: (text: string) => void;
  /** Called on every keystroke, so a message about the previous value can go. */
  onEdit?: () => void;
  /** Called when the field leaves the page (a tab switch), so state kept for it can go. */
  onGone?: () => void;
}

const DEBOUNCE_MS = 300;

/** A labelled field that saves one value; the typed text stays until a save succeeds or the saved value changes. */
export function Field({ name, label, value, help, error, number, blurOnly, onCommit, onInput, onEdit, onGone }: Props) {
  const [text, setText] = useState(value);
  const last = useRef(value);
  const timer = useRef<number | undefined>(undefined);
  const shown = useRef(value);
  const typed = useRef(value);
  useEffect(() => {
    if (value === shown.current) return; // effects run late: do not undo text typed since the first render
    shown.current = value;
    if (typed.current !== last.current) return; // the person typed past what was saved: keep their text
    setText(value);
    typed.current = value;
    last.current = value;
  }, [value]);
  const gone = useRef(onGone);
  gone.current = onGone;
  useEffect(() => () => { window.clearTimeout(timer.current); gone.current?.(); }, []);

  const commit = (t: string) => {
    window.clearTimeout(timer.current);
    if (t === last.current) return;
    last.current = t;
    void Promise.resolve(onCommit(t)).then((ok) => {
      if (ok === false) last.current = value; // a refused save can be tried again
    });
  };
  const id = `f-${name}`;
  const describedBy = [help ? `${id}-help` : "", error ? `${id}-err` : ""].filter(Boolean).join(" ") || undefined;
  return (
    <div class="field">
      <label for={id}>{label}</label>
      <input id={id} type={number ? "number" : "text"} step={number ? "any" : undefined} value={text}
        aria-invalid={error ? "true" : undefined} aria-describedby={describedBy} autocomplete="off" spellcheck={false}
        onInput={(e) => {
          const t = (e.currentTarget as HTMLInputElement).value;
          setText(t);
          typed.current = t;
          onEdit?.();
          onInput?.(t);
          if (!number && !blurOnly) {
            window.clearTimeout(timer.current);
            timer.current = window.setTimeout(() => commit(t), DEBOUNCE_MS);
          }
        }}
        onBlur={(e) => commit(e.currentTarget.value)}
        onKeyDown={(e) => { if (e.key === "Enter") commit(e.currentTarget.value); }} />
      {help && <p class="field-help" id={`${id}-help`}>{help}</p>}
      {error && <p class="field-error" id={`${id}-err`} role="alert">{error}</p>}
    </div>
  );
}
