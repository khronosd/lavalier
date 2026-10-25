import { useEffect, useRef, useState } from "preact/hooks";
import { api } from "../api";
import { actionError } from "../insights";

interface Props {
  /** The Keychain account the key routes act on: a provider, or "notion". */
  provider: string;
  /** Whether the Keychain holds a key for the provider; null when it could not be read. */
  present: boolean | null;
  /** Why the Keychain could not be read, from the provider facts. */
  keychainError: string | null;
  /** Called after a key was saved or removed, so the facts can be read again. */
  onChanged: () => void;
  /** The words of the field; an API key's by default. */
  label?: string;
  saveLabel?: string;
  noneText?: string;
  help?: string;
}

/** The provider's API key: a password field whose text is sent to the Keychain and then cleared. The key
 *  is never kept in state and never shown; only whether one is saved. Keyed by provider by its parent. */
export function KeyField({ provider, present, keychainError, onChanged, label = "API key", saveLabel = "Save key",
  noneText = "No key saved", help }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [hasText, setHasText] = useState(false);
  const [saved, setSaved] = useState(present);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setSaved(present), [present]);

  async function change(method: "PUT" | "DELETE") {
    const el = input.current;
    if (!el || busy) return;
    if (method === "PUT" && !el.value) return;
    setBusy(true);
    setError(null);
    try {
      const path = `/api/keys/${encodeURIComponent(provider)}`;
      if (method === "PUT") await api<void>("PUT", path, { key: el.value });
      else await api<void>("DELETE", path);
      el.value = "";
      setHasText(false);
      setSaved(method === "PUT");
      onChanged();
    } catch (e) {
      setError(actionError(e));
    } finally {
      setBusy(false);
    }
  }

  const id = `key-${provider}`;
  return (
    <div class="field key-field">
      <label for={id}>{label}</label>
      <form class="key-row" onSubmit={(e) => { e.preventDefault(); void change("PUT"); }}>
        <input id={id} ref={input} type="password" autocomplete="new-password" spellcheck={false}
          aria-describedby={[saved !== null ? `${id}-state` : "", help ? `${id}-help` : ""].filter(Boolean).join(" ") || undefined}
          onInput={(e) => { setHasText(e.currentTarget.value !== ""); setError(null); }} />
        <button class="btn" type="submit" disabled={!hasText || busy}>{saveLabel}</button>
      </form>
      <p class="field-help key-state">
        {saved !== null && <span id={`${id}-state`}>{saved ? "Saved in your Keychain" : noneText}</span>}
        {saved === true && (
          <button class="btn key-remove" type="button" disabled={busy} onClick={() => change("DELETE")}>Remove</button>
        )}
      </p>
      {help && <p class="field-help" id={`${id}-help`}>{help}</p>}
      {keychainError && <p class="field-error" role="alert">{keychainError}</p>}
      {error && <p class="field-error" role="alert">{error}</p>}
    </div>
  );
}
