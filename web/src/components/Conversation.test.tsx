import { cleanup, render, screen } from "@testing-library/preact";
import { afterEach, expect, test } from "vitest";
import type { ConversationView } from "../api";
import { Conversation } from "./Conversation";

const at = (h: number, m: number) => new Date(2026, 9, 23, h, m).getTime();
const conv: ConversationView = {
  conversation_id: "c1", start_ms: at(9, 30), end_ms: at(10, 15), speech_ms: 16 * 60_000, star_ms: [],
  pinned: false, label: null, clip_ids: ["clip_a"], audio_available: true,
  lines: [{ at_ms: at(9, 30), text: "Shall we start?", clip_id: "clip_a", seq: 0 }],
};
const noop = async () => undefined;

afterEach(cleanup);

test("the heading names the overlapping event after the speech total", () => {
  render(<Conversation conv={{ ...conv, label: "Weekly sync" }} onPin={noop} onPlay={() => undefined} />);
  const head = screen.getByRole("heading", { level: 2 }).closest("header")!;
  expect(head.textContent).toContain("16 min speech · Weekly sync");
  const label = screen.getByText("· Weekly sync", { exact: false });
  expect(label.classList.contains("conv-label")).toBe(true);
  expect(screen.getByText("Shall we start?")).toBeTruthy();
});

test("without a label the heading shows the speech total only", () => {
  render(<Conversation conv={conv} onPin={noop} onPlay={() => undefined} />);
  const head = screen.getByRole("heading", { level: 2 }).closest("header")!;
  expect(head.textContent).toContain("16 min speech");
  expect(head.textContent).not.toContain("·");
  expect(document.querySelector(".conv-label")).toBeNull();
});
