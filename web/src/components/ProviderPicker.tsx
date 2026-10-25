import { useEffect, useRef, useState } from "preact/hooks";
import {
  api, ApiError, explainError, type ModelInfo, type ProviderCheck, type ProviderFacts, type Settings, type SettingsPatch,
} from "../api";
import { actionError } from "../insights";
import { Field } from "./Field";
import { KeyField } from "./KeyField";

export const PROVIDER_CHOICES = [
  { id: "", label: "None" },
  { id: "ollama", label: "Ollama on this Mac" },
  { id: "anthropic", label: "Anthropic" },
  { id: "openai", label: "OpenAI" },
  { id: "google", label: "Google" },
] as const;
const KEYED = ["anthropic", "openai", "google"];

export const TOO_SLOW = "The provider took too long to answer";
const PRESS_TEST = "Press Test to list the models Ollama has pulled";
const BASE_URL_HELP = "Leave empty for OpenAI. Any OpenAI-compatible endpoint works here.";
const AUTO_LABEL = "Generate automatically once a day is complete";
const AUTO_HELP = "A day is complete at 04:00 the next morning. Days before you chose a model are never sent unless you ask.";

interface Props {
  settings: Settings;
  setSettings: (update: (s: Settings | null) => Settings | null) => void;
  save: (patch: SettingsPatch) => Promise<boolean>;
  errors: Record<string, string>;
  clearError: (field: string) => void;
}

type TestResult = { ok: boolean; text: string };

/** One model as a radio: its name, whether it is the recommended one, and what a day costs. */
function ModelRadio({ m, checked, onChoose }: { m: ModelInfo; checked: boolean; onChoose: () => void }) {
  const id = `m-${m.id}`;
  return (
    <label class="radio model-radio" for={id}>
      <input type="radio" id={id} name="insights_model" checked={checked} onChange={onChoose} />
      <span class="model-name">{m.label}</span>
      {m.recommended && <>{" "}<span class="model-rec">recommended</span></>}
      {m.cost_per_day && <>{" "}<span class="model-cost">{m.cost_per_day}</span></>}
    </label>
  );
}

/** Settings › Model below its lead: the provider, then for the chosen one its sentence and cost, the model,
 *  the key or the endpoint, Test, and whether to generate on its own. */
export function ProviderPicker({ settings, setSettings, save, errors, clearError }: Props) {
  const [facts, setFacts] = useState<ProviderFacts | null>(null);
  const [factsError, setFactsError] = useState<string | null>(null);
  const [check, setCheck] = useState<ProviderCheck | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const live = useRef(true);
  const lastFetch = useRef(0);
  useEffect(() => () => { live.current = false; }, []);

  /** The facts of the saved provider; latest wins. */
  function readFacts() {
    const n = ++lastFetch.current;
    api<ProviderFacts>("GET", "/api/insights/providers").then(
      (f) => { if (live.current && n === lastFetch.current) { setFacts(f); setFactsError(null); } },
      (e) => { if (live.current && n === lastFetch.current) setFactsError(explainError(e, "The provider")); },
    );
  }
  useEffect(readFacts, []);

  const provider = settings.insights_provider;

  /** Saved at once; the model chosen belongs to the provider before, so it goes back to the new one's default. */
  async function chooseProvider(id: string) {
    const before = { insights_provider: provider, insights_model: settings.insights_model };
    setSettings((s) => (s ? { ...s, insights_provider: id, insights_model: "" } : s));
    setCheck(null);
    setTest(null);
    if (await save({ insights_provider: id, insights_model: "" })) readFacts();
    else setSettings((s) => (s ? { ...s, ...before } : s));
  }

  async function saveAndRead(patch: SettingsPatch): Promise<boolean> {
    const ok = await save(patch);
    if (ok) readFacts();
    return ok;
  }

  async function runTest() {
    setTesting(true);
    setTest(null);
    try {
      const r = await api<ProviderCheck>("POST", "/api/insights/check");
      if (!live.current) return;
      setCheck(r);
      setTest({ ok: r.ok, text: r.detail });
    } catch (e) {
      if (!live.current) return;
      setTest({ ok: false, text: e instanceof ApiError && e.status === 504 ? TOO_SLOW : actionError(e) });
    } finally {
      if (live.current) setTesting(false);
    }
  }

  async function setAuto(on: boolean) {
    setSettings((s) => (s ? { ...s, insights_auto: on } : s));
    if (!(await save({ insights_auto: on }))) setSettings((s) => (s ? { ...s, insights_auto: !on } : s));
  }

  // the facts are for the saved provider: until they are read again after a change, show no details
  const shown = facts && provider && facts.provider === provider ? facts : null;
  const chosen = settings.insights_model || shown?.model || "";

  let picker = null;
  if (shown && provider === "ollama") {
    // Ollama's models are only known from a check; a "Pull …" detail is said by the picker instead
    const listed = check !== null && (check.models.length > 0 || check.detail.startsWith("Pull "));
    picker = (
      <fieldset class="radios model-picker">
        <legend>Model</legend>
        {!listed && <p class="field-help">{PRESS_TEST}</p>}
        {listed && check!.models.map((m) => (
          <ModelRadio key={m.id} m={{ ...m, cost_per_day: null }} checked={chosen === m.id}
            onChoose={() => saveAndRead({ insights_model: m.id })} />
        ))}
        {listed && !check!.models.some((m) => m.id === chosen) && (
          <p class="field-error" role="alert">{`Pull ${chosen} in Ollama first`}</p>
        )}
      </fieldset>
    );
  } else if (shown) {
    const known = shown.models.some((m) => m.id === settings.insights_model);
    picker = (
      <>
        {shown.models.length > 0 && (
          <fieldset class="radios model-picker">
            <legend>Model</legend>
            {shown.models.map((m) => (
              <ModelRadio key={m.id} m={m} checked={chosen === m.id}
                onChoose={() => saveAndRead({ insights_model: m.id })} />
            ))}
          </fieldset>
        )}
        <Field key={`model-${provider}`} name="insights_model" label="Another model id"
          value={known ? "" : settings.insights_model} error={errors.insights_model}
          onEdit={() => clearError("insights_model")} onCommit={(t) => saveAndRead({ insights_model: t.trim() })} />
      </>
    );
  }

  const hideTestDetail = provider === "ollama" && test !== null && test.text.startsWith("Pull ");
  return (
    <>
      <fieldset class="radios providers">
        <legend>Provider</legend>
        {PROVIDER_CHOICES.map((p) => (
          <div class="prov-option" key={p.id || "none"}>
            <label class="radio" for={`p-${p.id || "none"}`}>
              <input type="radio" id={`p-${p.id || "none"}`} name="insights_provider" checked={provider === p.id}
                onChange={() => chooseProvider(p.id)} />
              {p.label}
            </label>
            {p.id && p.id === provider && shown && (
              <div class="prov-facts">
                <p class="prov-sentence">{shown.sentence}</p>
                {shown.facts && (
                  <p class="prov-cost-line"><span class="set-fact-label">Cost</span><span class="prov-cost">{shown.facts.cost}</span></p>
                )}
              </div>
            )}
          </div>
        ))}
      </fieldset>
      {errors.insights_provider && <p class="field-error" role="alert">{errors.insights_provider}</p>}
      {factsError && <p class="notice warn" role="alert">{factsError}</p>}

      {shown && (
        <div class="prov-detail">
          {picker}
          {KEYED.includes(provider) && (
            <KeyField key={provider} provider={provider} present={shown.key_present} keychainError={shown.keychain_error}
              onChanged={readFacts} />
          )}
          {provider === "openai" && (
            <Field key="insights_base_url" name="insights_base_url" label="Base URL" value={settings.insights_base_url}
              help={BASE_URL_HELP} error={errors.insights_base_url} onEdit={() => clearError("insights_base_url")}
              onCommit={(t) => saveAndRead({ insights_base_url: t.trim() })} />
          )}
          <div class="ins-action prov-test">
            <button class="btn" type="button" disabled={testing} onClick={runTest}>Test</button>
            {testing && <span class="ins-help" role="status">Testing…</span>}
            {test && !hideTestDetail && (
              <span class={test.ok ? "ins-help" : "ins-help prov-bad"} role={test.ok ? "status" : "alert"}>{test.text}</span>
            )}
          </div>
          <div class="switch-field">
            <label class="switch-row" for="insights_auto">
              <input type="checkbox" role="switch" id="insights_auto" class="switch" checked={settings.insights_auto}
                aria-describedby="insights_auto-help" onChange={(e) => setAuto(e.currentTarget.checked)} />
              {AUTO_LABEL}
            </label>
            <p class="field-help" id="insights_auto-help">{AUTO_HELP}</p>
            {errors.insights_auto && <p class="field-error" role="alert">{errors.insights_auto}</p>}
          </div>
        </div>
      )}
    </>
  );
}
