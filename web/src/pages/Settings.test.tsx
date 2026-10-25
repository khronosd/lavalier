import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/preact";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { ConnectorsState, ProviderFacts, Settings as SettingsData } from "../api";
import { anthropic, noProvider, ollama } from "../insights.fixtures";
import { MODEL_PRIVACY } from "../insights";
import { status } from "../pendant.fixtures";
import { Settings } from "./Settings";

const json = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });

const saved: SettingsData = {
  pendant_address: "AAAA-BBBB", retention_days: 14, poll_interval_s: 300, drain_pages_threshold: 500,
  drain_after_hours: 6, require_firmware: "", whisper_language: "en", appearance: "system", window_size: "1120x720",
  readonly: { state_root: "/Users/me/Pendant", whisper_model: "small.en", bundle_id: "example.lavalier" },
  insights_provider: "", insights_model: "", insights_base_url: "", insights_auto: true,
  notion_enabled: false, notion_database_id: "", calendar_enabled: false, calendar_ids: "",
};

const opus: ProviderFacts = {
  ...anthropic, model: "claude-opus-5-5", key_present: false,
  sentence: "Sends each day's transcript text to Anthropic once the day is complete, and whenever you press " +
    "Generate or ask a question. Audio is never sent.",
  facts: { sends: "each day's transcript text and your questions, never audio", to: "Anthropic",
    cost: "about $0.20 per 3-hour day" },
  models: [
    { id: "claude-opus-5-5", label: "Claude Opus 5.5", recommended: true, cost_per_day: "about $0.20 per 3-hour day" },
    { id: "claude-haiku-5-5", label: "Claude Haiku 5.5", recommended: false, cost_per_day: "about $0.005 per 3-hour day" },
  ],
};
const gpt: ProviderFacts = {
  ...opus, provider: "openai", model: "gpt-6.1-sol", display: "OpenAI",
  sentence: opus.sentence.replace("Anthropic", "OpenAI"),
  facts: { ...opus.facts!, to: "OpenAI", cost: "about $0.095 per 3-hour day" },
  models: [{ id: "gpt-6.1-sol", label: "GPT-6.1 Sol", recommended: true, cost_per_day: "about $0.095 per 3-hour day" }],
};

let puts: unknown[];
let putReply: () => Response;
let current: SettingsData;
let facts: ProviderFacts;
let others: { key: string; body: unknown }[]; // key, check and providers requests
let otherReply: (key: string) => Response | undefined;
let conn: ConnectorsState;

beforeEach(() => {
  puts = [];
  others = [];
  current = { ...saved };
  facts = noProvider;
  otherReply = () => undefined;
  conn = connectors();
  putReply = () => json(current);
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} }));
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const body = init?.body ? JSON.parse(init.body as string) : undefined;
    if (key === "PUT /api/settings") {
      puts.push(body);
      current = { ...current, ...body };
      return putReply();
    }
    if (url.startsWith("/api/insights") || url.startsWith("/api/keys") || url.startsWith("/api/connectors") ||
        url.startsWith("/api/jobs")) {
      others.push({ key, body });
      const special = otherReply(key);
      if (special) return special;
      if (key === "GET /api/insights/providers") return json(facts);
      if (key === "GET /api/connectors") return json(conn);
      if (key.startsWith("PUT /api/keys/") || key.startsWith("DELETE /api/keys/")) return new Response(null, { status: 204 });
      throw new Error(`unexpected ${key}`);
    }
    return url === "/api/status" ? json(status()) : json(current);
  }));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.theme;
});

test("General shows the state root and the poll interval in minutes", async () => {
  render(<Settings tab="general" />);
  expect(await screen.findByText("/Users/me/Pendant")).toBeTruthy();
  expect((screen.getByLabelText("Check the pendant every (minutes)") as HTMLInputElement).value).toBe("5");
});

test("a field saves on blur with only that field, in seconds, and a Saved toast appears", async () => {
  render(<Settings tab="general" />);
  const input = (await screen.findByLabelText("Check the pendant every (minutes)")) as HTMLInputElement;
  fireEvent.input(input, { target: { value: "10" } });
  fireEvent.blur(input);
  await screen.findByText("Saved");
  expect(puts).toEqual([{ poll_interval_s: 600 }]);
});

test("a value that breaks a rule is refused before any request", async () => {
  render(<Settings tab="general" />);
  const input = (await screen.findByLabelText("Check the pendant every (minutes)")) as HTMLInputElement;
  fireEvent.input(input, { target: { value: "0.5" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(await screen.findByText("The poll interval must be at least 1 minute.")).toBeTruthy();
  expect(puts).toEqual([]);
  expect(input.value).toBe("0.5");
});

test("a 400 shows the server's message beside the field it names and keeps the typed value", async () => {
  putReply = () => json({ error: "retention_days must be 0 or more", field: "retention_days" }, 400);
  render(<Settings tab="retention" />);
  const input = (await screen.findByLabelText("Keep audio for (days)")) as HTMLInputElement;
  fireEvent.input(input, { target: { value: "30" } });
  fireEvent.blur(input);
  const msg = await screen.findByText("retention_days must be 0 or more");
  expect(input.closest(".field")!.contains(msg)).toBe(true);
  expect(input.value).toBe("30");
  expect(screen.queryByText("Saved")).toBeNull();
});

test("a 503 says the save failed", async () => {
  putReply = () => json({ error: "The app is stopping" }, 503);
  render(<Settings tab="pendant" />);
  const input = (await screen.findByLabelText("Pendant address")) as HTMLInputElement;
  fireEvent.input(input, { target: { value: "CCCC" } });
  fireEvent.blur(input);
  expect(await screen.findByText("Could not save: The app is stopping")).toBeTruthy();
  expect(input.value).toBe("CCCC");
});

test("the retention sentence follows the field as it is typed", async () => {
  render(<Settings tab="retention" />);
  const input = await screen.findByLabelText("Keep audio for (days)");
  expect(screen.getByText(/Audio is deleted 14 days after it was recorded/)).toBeTruthy();
  fireEvent.input(input, { target: { value: "21" } });
  expect(screen.getByText(/Audio is deleted 21 days after it was recorded; starred and pinned conversations are kept\. Text is kept for good\./)).toBeTruthy();
});

test("Appearance applies at once and saves", async () => {
  render(<Settings tab="appearance" />);
  const dark = await screen.findByLabelText("Dark");
  fireEvent.click(dark);
  expect(document.documentElement.dataset.theme).toBe("dark");
  await waitFor(() => expect(puts).toEqual([{ appearance: "dark" }]));
  await screen.findByText("Saved");
});

test("Appearance reverts and says why when the save fails", async () => {
  putReply = () => json({ error: "The app is stopping" }, 503);
  render(<Settings tab="appearance" />);
  fireEvent.click(await screen.findByLabelText("Dark"));
  expect(await screen.findByText("Could not save: The app is stopping")).toBeTruthy();
  expect(document.documentElement.dataset.theme).toBe("light");
  expect((screen.getByLabelText("System") as HTMLInputElement).checked).toBe(true);
});

test("the tab list names six tabs in order and marks the open one", async () => {
  render(<Settings tab="retention" />);
  await screen.findByLabelText("Keep audio for (days)");
  const links = screen.getAllByRole("link");
  expect(links.map((l) => l.textContent)).toEqual(["General", "Pendant", "Retention", "Connectors", "Model", "Appearance"]);
  expect(links[2].getAttribute("aria-current")).toBe("page");
});

test("Pendant shows the last read line", async () => {
  render(<Settings tab="pendant" />);
  expect(await screen.findByText("Listening just now, battery 94%")).toBeTruthy();
});

test("a save response does not overwrite text typed after the save began", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let release: (r: Response) => void = () => undefined;
  const base = vi.mocked(fetch).getMockImplementation()!;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      puts.push(JSON.parse(init.body as string));
      return new Promise<Response>((res) => { release = res; });
    }
    return base(url, init);
  }));
  render(<Settings tab="pendant" />);
  const input = (await screen.findByLabelText("Pendant address")) as HTMLInputElement;
  fireEvent.input(input, { target: { value: "CC" } });
  await act(async () => { await vi.advanceTimersByTimeAsync(350); });
  expect(puts).toEqual([{ pendant_address: "CC" }]);
  fireEvent.input(input, { target: { value: "CCC" } });
  await act(async () => { release(json({ ...saved, pendant_address: "CC" })); });
  await screen.findByText("Saved");
  expect(input.value).toBe("CCC");
  vi.useRealTimers();
});

test("an unchanged value is not saved, and Enter then blur saves once", async () => {
  render(<Settings tab="pendant" />);
  const input = (await screen.findByLabelText("Pendant address")) as HTMLInputElement;
  fireEvent.blur(input);
  expect(puts).toEqual([]);
  fireEvent.input(input, { target: { value: "DDDD" } });
  fireEvent.keyDown(input, { key: "Enter" });
  fireEvent.blur(input);
  await screen.findByText("Saved");
  expect(puts).toEqual([{ pendant_address: "DDDD" }]);
});

test("a field's error goes when the person edits it", async () => {
  putReply = () => json({ error: "retention_days must be 0 or more", field: "retention_days" }, 400);
  render(<Settings tab="retention" />);
  const input = await screen.findByLabelText("Keep audio for (days)");
  fireEvent.input(input, { target: { value: "30" } });
  fireEvent.blur(input);
  await screen.findByText("retention_days must be 0 or more");
  fireEvent.input(input, { target: { value: "31" } });
  await waitFor(() => expect(screen.queryByText("retention_days must be 0 or more")).toBeNull());
});

test("the retention preview does not come back after a tab round trip", async () => {
  const { rerender } = render(<Settings tab="retention" />);
  const input = await screen.findByLabelText("Keep audio for (days)");
  fireEvent.input(input, { target: { value: "30" } });
  expect(screen.getByText(/deleted 30 days/)).toBeTruthy();
  rerender(<Settings tab="pendant" />);
  await screen.findByLabelText("Pendant address");
  rerender(<Settings tab="retention" />);
  await screen.findByLabelText("Keep audio for (days)");
  expect(screen.getByText(/deleted 14 days/)).toBeTruthy();
  expect((screen.getByLabelText("Keep audio for (days)") as HTMLInputElement).value).toBe("14");
});

// --- Settings › Model ---

const count = (key: string) => others.filter((o) => o.key === key).length;
const radio = (name: string) => screen.getByRole("radio", { name }) as HTMLInputElement;

async function model(provider = "anthropic", f: ProviderFacts = opus) {
  current = { ...current, insights_provider: provider, insights_model: f.provider ? f.model : "" };
  facts = f;
  const r = render(<Settings tab="model" />);
  await screen.findByRole("radio", { name: "None" });
  await waitFor(() => expect(count("GET /api/insights/providers")).toBe(1));
  return r;
}

test("Model: the privacy lead, five providers, and the chosen one's sentence and cost", async () => {
  const { container } = await model();
  expect(screen.getByText(MODEL_PRIVACY)).toBeTruthy();
  const names = screen.getAllByRole("radio").slice(0, 5).map((r) => (r as HTMLInputElement).labels![0].textContent);
  expect(names).toEqual(["None", "Ollama on this Mac", "Anthropic", "OpenAI", "Google"]);
  expect(radio("Anthropic").checked).toBe(true);
  expect(await screen.findByText(opus.sentence)).toBeTruthy();
  expect(screen.getByText("about $0.20 per 3-hour day", { selector: ".prov-cost" })).toBeTruthy();
  // the known models with their cost per day, the recommended one marked, and the saved one chosen
  expect(radio("Claude Opus 5.5 recommended about $0.20 per 3-hour day").checked).toBe(true);
  expect(radio("Claude Haiku 5.5 about $0.005 per 3-hour day").checked).toBe(false);
  expect(screen.getByLabelText("Another model id")).toBeTruthy();
  expect(container.querySelector("[style]")).toBeNull();
});

test("Model: None shows no provider details", async () => {
  await model("", noProvider);
  expect(radio("None").checked).toBe(true);
  expect(screen.queryByText(/Audio is never sent/)).toBeNull();
  expect(screen.queryByRole("button", { name: "Test" })).toBeNull();
  expect(screen.queryByRole("switch")).toBeNull();
});

test("Model: choosing a provider saves it at once and reads its facts again", async () => {
  await model();
  facts = gpt;
  fireEvent.click(radio("OpenAI"));
  // the model chosen was Anthropic's: the new provider starts from its own default
  await waitFor(() => expect(puts).toEqual([{ insights_provider: "openai", insights_model: "" }]));
  await waitFor(() => expect(count("GET /api/insights/providers")).toBe(2));
  expect(await screen.findByText(gpt.sentence)).toBeTruthy();
  expect(radio("OpenAI").checked).toBe(true);
  const base = screen.getByLabelText("Base URL");
  expect(base.closest(".field")!.textContent).toContain("Leave empty for OpenAI. Any OpenAI-compatible endpoint works here.");
});

test("Model: a cloud model is chosen by its radio, another by its id", async () => {
  await model();
  fireEvent.click(radio("Claude Haiku 5.5 about $0.005 per 3-hour day"));
  await waitFor(() => expect(puts).toEqual([{ insights_model: "claude-haiku-5-5" }]));
  await waitFor(() => expect(count("GET /api/insights/providers")).toBe(2));
  const other = screen.getByLabelText("Another model id") as HTMLInputElement;
  fireEvent.input(other, { target: { value: "claude-next" } });
  fireEvent.blur(other);
  await waitFor(() => expect(puts).toEqual([{ insights_model: "claude-haiku-5-5" }, { insights_model: "claude-next" }]));
});

test("Model: a key is saved to the Keychain and never echoed or kept", async () => {
  await model();
  expect(screen.getByText("No key saved")).toBeTruthy();
  const input = screen.getByLabelText("API key") as HTMLInputElement;
  expect(input.type).toBe("password");
  expect(input.getAttribute("autocomplete")).toBe("new-password");
  expect((screen.getByRole("button", { name: "Save key" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
  fireEvent.input(input, { target: { value: "sk-secret-1" } });
  facts = { ...opus, key_present: true };
  fireEvent.click(screen.getByRole("button", { name: "Save key" }));
  await screen.findByText("Saved in your Keychain");
  expect(others.filter((o) => o.key.startsWith("PUT /api/keys"))).toEqual([
    { key: "PUT /api/keys/anthropic", body: { key: "sk-secret-1" } }]);
  expect(input.value).toBe("");
  expect(document.body.innerHTML).not.toContain("sk-secret-1");
  expect(puts).toEqual([]); // a key is never a setting
  await waitFor(() => expect(count("GET /api/insights/providers")).toBe(2));
});

test("Model: Remove deletes the saved key", async () => {
  await model("anthropic", { ...opus, key_present: true });
  expect(screen.getByText("Saved in your Keychain")).toBeTruthy();
  facts = { ...opus, key_present: false };
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  await screen.findByText("No key saved");
  expect(count("DELETE /api/keys/anthropic")).toBe(1);
});

test("Model: a Keychain refusal is shown beside the key, and so is one the facts carry", async () => {
  await model("anthropic", { ...opus, key_present: null, keychain_error: "The Keychain is locked." });
  expect(screen.getByText("The Keychain is locked.")).toBeTruthy();
  otherReply = (key) => key === "PUT /api/keys/anthropic"
    ? json({ error: "The Keychain refused the change." }, 503) : undefined;
  const input = screen.getByLabelText("API key") as HTMLInputElement;
  fireEvent.input(input, { target: { value: "sk-secret-2" } });
  fireEvent.click(screen.getByRole("button", { name: "Save key" }));
  const alert = await screen.findByText("The Keychain refused the change.");
  expect(input.closest(".key-field")!.contains(alert)).toBe(true);
  expect(document.body.innerHTML).not.toContain("sk-secret-2");
});

test("Model: Test shows the provider's detail, and a slow provider says so", async () => {
  await model("anthropic", { ...opus, key_present: true });
  otherReply = (key) => key === "POST /api/insights/check"
    ? json({ ok: true, detail: "Anthropic answered; claude-opus-5-5 is available", models: [] }) : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Test" }));
  expect(await screen.findByText("Anthropic answered; claude-opus-5-5 is available")).toBeTruthy();
  otherReply = (key) => key === "POST /api/insights/check" ? json({ error: "timeout" }, 504) : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Test" }));
  expect(await screen.findByText("The provider took too long to answer")).toBeTruthy();
  expect(screen.queryByText(/Anthropic answered/)).toBeNull();
});

test("Model: Ollama lists its pulled models only after Test, the recommended one marked", async () => {
  await model("ollama", ollama);
  expect(screen.getByText("Press Test to list the models Ollama has pulled")).toBeTruthy();
  expect(screen.queryByLabelText("API key")).toBeNull();
  expect(screen.queryByLabelText("Base URL")).toBeNull();
  otherReply = (key) => key === "POST /api/insights/check" ? json({
    ok: false, detail: "Pull qwen3:8b in Ollama first",
    models: [
      { id: "llama3:8b", label: "llama3:8b", recommended: false, cost_per_day: "free, runs on this Mac" },
      { id: "qwen3:14b", label: "qwen3:14b", recommended: true, cost_per_day: "free, runs on this Mac" },
    ],
  }) : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Test" }));
  await screen.findByRole("radio", { name: "qwen3:14b recommended" });
  expect(screen.queryByText("Press Test to list the models Ollama has pulled")).toBeNull();
  expect(radio("llama3:8b").checked).toBe(false);
  expect(screen.getAllByText("Pull qwen3:8b in Ollama first")).toHaveLength(1);
  facts = { ...ollama, model: "qwen3:14b" };
  fireEvent.click(radio("qwen3:14b recommended"));
  await waitFor(() => expect(puts).toEqual([{ insights_model: "qwen3:14b" }]));
  await waitFor(() => expect(radio("qwen3:14b recommended").checked).toBe(true));
  expect(screen.queryByText("Pull qwen3:8b in Ollama first")).toBeNull();
});

test("Model: the base URL must be empty or http(s), checked before any request", async () => {
  await model("openai", gpt);
  const base = screen.getByLabelText("Base URL") as HTMLInputElement;
  fireEvent.input(base, { target: { value: "localhost:1234" } });
  fireEvent.blur(base);
  expect(await screen.findByText("The base URL must be empty or start with http:// or https://.")).toBeTruthy();
  expect(puts).toEqual([]);
  fireEvent.input(base, { target: { value: "http://localhost:1234/v1" } });
  fireEvent.blur(base);
  await waitFor(() => expect(puts).toEqual([{ insights_base_url: "http://localhost:1234/v1" }]));
});

test("Model: the automatic switch saves insights_auto and says when a day is complete", async () => {
  await model("ollama", ollama);
  const sw = screen.getByRole("switch", { name: "Generate automatically once a day is complete" }) as HTMLInputElement;
  expect(sw.checked).toBe(true);
  expect(screen.getByText(
    "A day is complete at 04:00 the next morning and is sent once its audio has come in from the pendant. Days from before you chose a model, saved its key or turned this on are never sent unless you ask.")).toBeTruthy();
  fireEvent.click(sw);
  await waitFor(() => expect(puts).toEqual([{ insights_auto: false }]));
  expect(sw.checked).toBe(false);
});

test("Model: the base URL and another model id save on blur or Enter, never half typed", async () => {
  await model("openai", gpt);
  const base = screen.getByLabelText("Base URL") as HTMLInputElement;
  fireEvent.input(base, { target: { value: "http://local" } });
  await new Promise((r) => setTimeout(r, 400)); // past the 300 ms a plain field waits
  expect(puts).toEqual([]);
  fireEvent.keyDown(base, { key: "Enter" });
  await waitFor(() => expect(puts).toEqual([{ insights_base_url: "http://local" }]));
  const other = screen.getByLabelText("Another model id") as HTMLInputElement;
  fireEvent.input(other, { target: { value: "gpt-x" } });
  await new Promise((r) => setTimeout(r, 400));
  expect(puts).toHaveLength(1);
  fireEvent.blur(other);
  await waitFor(() => expect(puts).toEqual([{ insights_base_url: "http://local" }, { insights_model: "gpt-x" }]));
});

test("Model: a failed Ollama Test replaces the hint with its error, said once", async () => {
  await model("ollama", ollama);
  otherReply = (key) => key === "POST /api/insights/check"
    ? json({ ok: false, detail: "Ollama did not answer. Start it and try again.", models: [] }) : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Test" }));
  await screen.findByText("Ollama did not answer. Start it and try again.");
  expect(screen.getAllByText("Ollama did not answer. Start it and try again.")).toHaveLength(1);
  expect(screen.queryByText("Press Test to list the models Ollama has pulled")).toBeNull();
  otherReply = (key) => key === "POST /api/insights/check" ? json({ error: "timeout" }, 504) : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Test" }));
  await screen.findByText("The provider took too long to answer");
  expect(screen.getAllByText("The provider took too long to answer")).toHaveLength(1);
  expect(screen.queryByText("Press Test to list the models Ollama has pulled")).toBeNull();
});


// --- final fix wave: one key per endpoint, and an unencrypted endpoint said plainly (R24)

const endpoint: ProviderFacts = {
  ...gpt, base_url: "http://llm.example.net:8000/v1", display: "the endpoint at llm.example.net:8000", key_present: false,
  sentence: gpt.sentence.replace("OpenAI", "the endpoint at llm.example.net:8000"),
};
const CLEAR = "This endpoint is not encrypted: the key and the text travel in the clear.";

test("Model: after the base URL changes the key field shows the new endpoint's key, not OpenAI's", async () => {
  await model("openai", { ...gpt, key_present: true });
  expect(screen.getByText("Saved in your Keychain")).toBeTruthy();
  facts = endpoint;
  const base = screen.getByLabelText("Base URL") as HTMLInputElement;
  fireEvent.input(base, { target: { value: "http://llm.example.net:8000/v1" } });
  fireEvent.blur(base);
  await waitFor(() => expect(count("GET /api/insights/providers")).toBe(2));
  expect(await screen.findByText("No key saved")).toBeTruthy();
  expect(screen.queryByText("Saved in your Keychain")).toBeNull();
  expect(screen.getByText(endpoint.sentence)).toBeTruthy();
});

test("Model: an http:// base URL warns that it is not encrypted, and is allowed", async () => {
  current = { ...current, insights_base_url: "http://llm.example.net:8000/v1" };
  await model("openai", endpoint);
  expect(screen.getByText(CLEAR)).toBeTruthy();
  cleanup();
  others = [];
  current = { ...current, insights_base_url: "https://llm.example.net/v1" };
  await model("openai", { ...endpoint, base_url: "https://llm.example.net/v1" });
  expect(screen.queryByText(CLEAR)).toBeNull();
});

test("Model: the warning follows a base URL saved as http://", async () => {
  await model("openai", gpt);
  expect(screen.queryByText(CLEAR)).toBeNull();
  const base = screen.getByLabelText("Base URL") as HTMLInputElement;
  fireEvent.input(base, { target: { value: "http://localhost:1234/v1" } });
  fireEvent.blur(base);
  await waitFor(() => expect(puts).toEqual([{ insights_base_url: "http://localhost:1234/v1" }]));
  expect(await screen.findByText(CLEAR)).toBeTruthy();
});

// --- Settings › Connectors ---

const DB = "0123456789abcdef0123456789abcdef";

function connectors(over: { notion?: Partial<ConnectorsState["notion"]>; calendar?: Partial<ConnectorsState["calendar"]> } = {}): ConnectorsState {
  return {
    notion: { enabled: false, database_id: "", token_present: false, last: [], exporting: false, ...over.notion },
    calendar: { enabled: false, authorization: "not-asked", calendars: [], chosen: [], ...over.calendar },
  };
}

const exportRow = (day: string, state: "done" | "stopped" | "error", error: string | null = null) => ({
  day, connector: "notion", page_id: "p", block_id: "b", content_hash: "h",
  exported_ms: new Date(2026, 9, 23, 14, 2).getTime(), state, error,
});

async function connectorsTab() {
  const r = render(<Settings tab="connectors" />);
  await screen.findByRole("switch", { name: "Send days to Notion" });
  await waitFor(() => expect(count("GET /api/connectors")).toBe(1));
  await waitFor(() => expect(document.querySelector(".con-auth")!.textContent).not.toBe("Reading…")); // the state is shown
  return r;
}

const NOTION_SENTENCE = "Sends each day's text, and its Insights once generated, to the Notion database you choose. Audio is never sent.";
const CALENDAR_SENTENCE = "Reads the calendars you pick on this Mac to name conversations after the event they overlap. Nothing leaves this Mac.";

test("Connectors: the lead, then two switches, each with its sentence, saved and read again", async () => {
  const { container } = await connectorsTab();
  expect(screen.getByText(/Audio never leaves this Mac\./)).toBeTruthy();
  const notion = screen.getByRole("switch", { name: "Send days to Notion" }) as HTMLInputElement;
  const calendar = screen.getByRole("switch", { name: "Label conversations from Calendar" }) as HTMLInputElement;
  expect(document.getElementById(notion.getAttribute("aria-describedby")!)!.textContent).toBe(NOTION_SENTENCE);
  expect(document.getElementById(calendar.getAttribute("aria-describedby")!)!.textContent).toBe(CALENDAR_SENTENCE);
  expect(notion.checked).toBe(false);
  conn = connectors({ notion: { enabled: true } });
  fireEvent.click(notion);
  await waitFor(() => expect(puts).toEqual([{ notion_enabled: true }]));
  await waitFor(() => expect(count("GET /api/connectors")).toBe(2));
  expect(notion.checked).toBe(true);
  fireEvent.click(calendar);
  await waitFor(() => expect(puts).toEqual([{ notion_enabled: true }, { calendar_enabled: true }]));
  await waitFor(() => expect(count("GET /api/connectors")).toBe(3));
  expect(container.querySelector("[style]")).toBeNull();
});

test("Connectors: the token is saved to the Keychain under notion and never echoed or kept", async () => {
  await connectorsTab();
  expect(await screen.findByText("No token saved")).toBeTruthy();
  expect(screen.getByText("Create an internal integration in Notion, share your database with it, and paste its secret here.")).toBeTruthy();
  const input = screen.getByLabelText("Integration token") as HTMLInputElement;
  expect(input.type).toBe("password");
  expect(input.getAttribute("autocomplete")).toBe("new-password");
  fireEvent.input(input, { target: { value: "ntn_secret_1" } });
  conn = connectors({ notion: { token_present: true } });
  fireEvent.click(screen.getByRole("button", { name: "Save token" }));
  await screen.findByText("Saved in your Keychain");
  expect(others.filter((o) => o.key.startsWith("PUT /api/keys"))).toEqual([
    { key: "PUT /api/keys/notion", body: { key: "ntn_secret_1" } }]);
  expect(input.value).toBe("");
  expect(document.body.innerHTML).not.toContain("ntn_secret_1");
  expect(puts).toEqual([]);
  await waitFor(() => expect(count("GET /api/connectors")).toBe(2));
});

test("Connectors: the database takes a URL, saved normalised on blur, and a bad one is refused locally", async () => {
  await connectorsTab();
  expect(screen.getByText("The database that gets one page per day. Share it with the integration first.")).toBeTruthy();
  const input = screen.getByLabelText("Database") as HTMLInputElement;
  fireEvent.input(input, { target: { value: "journal" } });
  expect(puts).toEqual([]); // never saved while typing
  fireEvent.blur(input);
  expect(await screen.findByText("Paste the database's link from Notion, or its 32-character id.")).toBeTruthy();
  expect(puts).toEqual([]);
  fireEvent.input(input, { target: { value: `https://www.notion.so/me/Journal-${DB.toUpperCase()}?v=1` } });
  fireEvent.blur(input);
  await waitFor(() => expect(puts).toEqual([{ notion_database_id: DB }]));
  await waitFor(() => expect(input.value).toBe(DB));
  await waitFor(() => expect(count("GET /api/connectors")).toBe(2));
});

test("Connectors: Test names the database and the properties it will add, or says what went wrong", async () => {
  await connectorsTab();
  otherReply = (key) => key === "POST /api/connectors/notion/check"
    ? json({ database_id: DB, data_source_id: "ds", title: "Journal <b>", missing_properties: ["Date", "Speech"],
      title_property: "Name", mistyped_properties: [] }) : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Test" }));
  expect(await screen.findByText("Connected to Journal <b>")).toBeTruthy();
  expect(screen.getByText("Missing properties will be added: Date, Speech")).toBeTruthy();
  await waitFor(() => expect(count("GET /api/connectors")).toBe(2));
  otherReply = (key) => key === "POST /api/connectors/notion/check"
    ? json({ error: "No Notion token is saved." }, 400) : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Test" }));
  expect(await screen.findByText("No Notion token is saved.")).toBeTruthy();
  expect(screen.queryByText(/Connected to/)).toBeNull();
  expect(screen.queryByText(/Missing properties/)).toBeNull();
});

test("Connectors: Export the last 7 days follows the job and says what it did", async () => {
  await connectorsTab();
  otherReply = (key) => {
    if (key === "POST /api/connectors/notion/export") return json({ job: "j1" }, 202);
    if (key === "GET /api/jobs/j1") {
      return json({ id: "j1", kind: "export", key: "notion", state: "done", error: null, started_ms: 0, finished_ms: 1,
        result: { done: 5, unchanged: 1, stopped: ["2026-10-20"], errors: [], days: [] } });
    }
    return undefined;
  };
  conn = connectors({ notion: { last: [exportRow("2026-10-20", "stopped", "edited by hand")] } });
  fireEvent.click(screen.getByRole("button", { name: "Export the last 7 days" }));
  expect(await screen.findByText("Exported 5 days, 1 unchanged; 1 stopped: 20 October was edited by hand")).toBeTruthy();
  expect(others.find((o) => o.key === "POST /api/connectors/notion/export")!.body).toEqual({ days: 7 });
  await screen.findByText("stopped: edited by hand");
});

test("Connectors: a refused export says why", async () => {
  await connectorsTab();
  otherReply = (key) => key === "POST /api/connectors/notion/export"
    ? json({ error: "Turn Notion on first." }, 400) : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Export the last 7 days" }));
  expect(await screen.findByText("Turn Notion on first.")).toBeTruthy();
});

test("Connectors: the export list, newest first, with Export again on a stopped or failed day", async () => {
  conn = connectors({ notion: { enabled: true, last: [
    exportRow("2026-10-21", "error", "Notion is rate limiting"),
    exportRow("2026-10-23", "done"),
    exportRow("2026-10-22", "stopped", "edited by hand"),
  ] } });
  await connectorsTab();
  const rows = [...document.querySelectorAll(".exp-row")].map((r) => r.querySelector(".exp-day")!.textContent);
  expect(rows).toEqual(["Friday, 23 October", "Thursday, 22 October", "Wednesday, 21 October"]);
  expect(screen.getByText("exported 14:02")).toBeTruthy();
  expect(screen.getByText("stopped: edited by hand")).toBeTruthy();
  expect(screen.getByText("error: Notion is rate limiting")).toBeTruthy();
  const again = screen.getAllByRole("button", { name: "Export again" });
  expect(again.length).toBe(2);
  expect(document.querySelectorAll(".exp-row")[0].querySelector("button")).toBeNull();
  otherReply = (key) => {
    if (key === "POST /api/connectors/notion/export") return json({ job: "j2" }, 202);
    if (key === "GET /api/jobs/j2") {
      return json({ id: "j2", kind: "export", key: "notion", state: "done", error: null, started_ms: 0, finished_ms: 1,
        result: { done: 1, unchanged: 0, stopped: [], errors: [], days: [] } });
    }
    return undefined;
  };
  conn = connectors({ notion: { enabled: true, last: [exportRow("2026-10-23", "done"), exportRow("2026-10-22", "done"),
    exportRow("2026-10-21", "error", "Notion is rate limiting")] } });
  fireEvent.click(again[0]);
  await waitFor(() => expect(screen.queryByText("stopped: edited by hand")).toBeNull());
  expect(others.find((o) => o.key === "POST /api/connectors/notion/export")!.body).toEqual({ day: "2026-10-22", force: true });
  expect(screen.getAllByRole("button", { name: "Export again" }).length).toBe(1);
  conn = connectors({ notion: { enabled: true, last: [exportRow("2026-10-23", "done"), exportRow("2026-10-22", "done"),
    exportRow("2026-10-21", "done")] } });
  fireEvent.click(screen.getByRole("button", { name: "Export again" }));      // the failed day: retried, not forced
  await waitFor(() => expect(screen.queryByRole("button", { name: "Export again" })).toBeNull());
  const posts = others.filter((o) => o.key === "POST /api/connectors/notion/export");
  expect(posts.map((p) => p.body)).toEqual([{ day: "2026-10-22", force: true }, { day: "2026-10-21" }]);
});

test("Connectors: the calendar authorisation states", async () => {
  const lines: [ConnectorsState["calendar"]["authorization"], string][] = [
    ["allowed", "Allowed"],
    ["denied", "Denied: open System Settings › Privacy & Security › Calendars to allow it"],
    ["restricted", "Restricted on this Mac"],
    ["unavailable", "Calendar access is not available on this Mac"],
  ];
  for (const [auth, text] of lines) {
    conn = connectors({ calendar: { authorization: auth } });
    render(<Settings tab="connectors" />);
    expect(await screen.findByText(text)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Allow access" })).toBeNull();
    cleanup();
  }
});

test("Connectors: Allow access asks once and reads the state again", async () => {
  await connectorsTab();
  expect(screen.getByText("Not asked yet")).toBeTruthy();
  otherReply = (key) => key === "POST /api/connectors/calendar/access" ? json({ authorization: "allowed" }) : undefined;
  conn = connectors({ calendar: { authorization: "allowed", calendars: [{ identifier: "work", title: "Work", colour: null }] } });
  fireEvent.click(screen.getByRole("button", { name: "Allow access" }));
  expect(await screen.findByText("Allowed")).toBeTruthy();
  expect(count("POST /api/connectors/calendar/access")).toBe(1);
  expect(screen.getByRole("checkbox", { name: "Work" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Allow access" })).toBeNull();
});

test("Connectors: the calendars are checkboxes saving a comma-separated list; none means all", async () => {
  conn = connectors({ calendar: { enabled: true, authorization: "allowed", calendars: [
    { identifier: "work", title: "Work", colour: "#1badf8" }, { identifier: "home", title: "Home", colour: null }] } });
  await connectorsTab();
  expect(screen.getByText("All calendars are read until you pick some.")).toBeTruthy();
  const work = screen.getByRole("checkbox", { name: "Work" }) as HTMLInputElement;
  const home = screen.getByRole("checkbox", { name: "Home" }) as HTMLInputElement;
  expect(work.checked || home.checked).toBe(false);
  // the colour is a custom property only, never an inline style beyond it
  const dot = work.closest("label")!.querySelector(".cal-dot") as HTMLElement;
  expect(dot.style.getPropertyValue("--dot")).toBe("#1badf8");
  expect(home.closest("label")!.querySelector(".cal-dot")).toBeNull();
  fireEvent.click(work);
  await waitFor(() => expect(puts).toEqual([{ calendar_ids: "work" }]));
  await waitFor(() => expect(work.checked).toBe(true));
  expect(screen.queryByText("All calendars are read until you pick some.")).toBeNull();
  fireEvent.click(home);
  await waitFor(() => expect(puts).toEqual([{ calendar_ids: "work" }, { calendar_ids: "work,home" }]));
  await waitFor(() => expect(count("GET /api/connectors")).toBe(3));
});
