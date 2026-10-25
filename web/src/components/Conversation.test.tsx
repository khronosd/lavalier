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

test("the heading is the calendar label when there is one; the range and the speech total follow it", () => {
  render(<Conversation conv={{ ...conv, label: "Weekly sync" }} onPin={noop} onPlay={() => undefined} />);
  expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Weekly sync");
  expect(document.querySelector(".conv-dur")!.textContent).toBe("09:30 to 10:15 · 16 min speech");
  expect(screen.getByText("Shall we start?")).toBeTruthy();
});

test("the stars follow the speech total", () => {
  render(<Conversation conv={{ ...conv, label: "Weekly sync", star_ms: [at(9, 40), at(9, 50)] }} onPin={noop}
    onPlay={() => undefined} />);
  const head = screen.getByRole("heading", { level: 2 }).closest("header")!;
  expect(head.querySelector(".conv-dur")!.textContent).toBe("09:30 to 10:15 · 16 min speech ★★");
  expect(head.querySelector(".conv-stars")!.textContent).toBe("★★");
  expect(head.querySelector(".conv-stars")!.getAttribute("aria-label")).toBe("2 starred");
});

test("without a label the heading is the range and the meta line the speech total only", () => {
  render(<Conversation conv={conv} onPin={noop} onPlay={() => undefined} />);
  expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("09:30 to 10:15");
  const head = screen.getByRole("heading", { level: 2 }).closest("header")!;
  expect(head.querySelector(".conv-dur")!.textContent).toBe("16 min speech");
  expect(head.textContent).not.toContain("·");
});
