interface Props {
  id: string;
  label: string;
  sentence: string;
  checked: boolean;
  error?: string;
  onChange: (on: boolean) => void;
}

/** A connector's on/off switch with the sentence that says what turning it on moves, and where. */
export function ConnectorSwitch({ id, label, sentence, checked, error, onChange }: Props) {
  return (
    <div class="switch-field">
      <label class="switch-row" for={id}>
        <input type="checkbox" role="switch" id={id} class="switch" checked={checked}
          aria-describedby={`${id}-help`} onChange={(e) => onChange(e.currentTarget.checked)} />
        {label}
      </label>
      <p class="field-help" id={`${id}-help`}>{sentence}</p>
      {error && <p class="field-error" role="alert">{error}</p>}
    </div>
  );
}
