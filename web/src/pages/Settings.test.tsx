import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/preact";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Settings as SettingsData } from "../api";
import { status } from "../pendant.fixtures";
import { Settings } from "./Settings";

const json = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });

const saved: SettingsData = {
  pendant_address: "AAAA-BBBB", retention_days: 14, poll_interval_s: 300, drain_pages_threshold: 500,
  drain_after_hours: 6, require_firmware: "", whisper_language: "en", appearance: "system", window_size: "1120x720",
  readonly: { state_root: "/Users/me/Pendant", whisper_model: "small.en", bundle_id: "example.lavalier" },
};

let puts: unknown[];
let putReply: () => Response;

beforeEach(() => {
  puts = [];
  putReply = () => json({ ...saved });
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} }));
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      puts.push(JSON.parse(init.body as string));
      return putReply();
    }
    return url === "/api/status" ? json(status()) : json(saved);
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

test("Connectors and Model are honest placeholders with no controls", async () => {
  const { unmount } = render(<Settings tab="connectors" />);
  expect(await screen.findByText("Connectors arrive in a later release.")).toBeTruthy();
  expect(screen.getByText(/Audio never leaves this Mac\./)).toBeTruthy();
  expect(screen.queryAllByRole("switch").length + screen.queryAllByRole("checkbox").length).toBe(0);
  unmount();
  render(<Settings tab="model" />);
  expect(await screen.findByText("Insights arrive in a later release.")).toBeTruthy();
  expect(screen.getByText(/a cloud provider receives each day's transcript text, never audio\./)).toBeTruthy();
  expect(screen.queryAllByRole("textbox").length).toBe(0);
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
