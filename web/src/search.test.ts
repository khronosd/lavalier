import { render } from "@testing-library/preact";
import { h } from "preact";
import { afterEach, expect, test } from "vitest";
import type { Hit } from "./api";
import { convStart, groupByDay, groupHits, renderSnippet, splitSnippet } from "./search";

const at = (d: number, hh: number, mm: number) => new Date(2026, 9, d, hh, mm).getTime();
const hit = (day: string, at_ms: number, seq = 0): Hit =>
  ({ day, conversation_id: null, clip_id: `clip_${at_ms}`, seq, at_ms, snippet: "x" });

test("groupHits puts the newest day first and each day's hits in time order", () => {
  const hits = [hit("2026-10-21", at(21, 9, 0)), hit("2026-10-23", at(23, 22, 56)), hit("2026-10-21", at(21, 8, 0)),
    hit("2026-10-23", at(23, 17, 33)), hit("2026-10-22", at(22, 12, 0))];
  const groups = groupHits(hits);
  expect(groups.map((g) => g.day)).toEqual(["2026-10-23", "2026-10-22", "2026-10-21"]);
  expect(groups[0].hits.map((x) => x.at_ms)).toEqual([at(23, 17, 33), at(23, 22, 56)]);
  expect(groups[2].hits.map((x) => x.at_ms)).toEqual([at(21, 8, 0), at(21, 9, 0)]);
  expect(groupHits([])).toEqual([]);
});

test("groupHits orders hits at the same moment by clip and seq", () => {
  const a = { ...hit("2026-10-23", 5, 1), clip_id: "clip_b" };
  const b = { ...hit("2026-10-23", 5, 0), clip_id: "clip_b" };
  expect(groupHits([a, b])[0].hits.map((x) => x.seq)).toEqual([0, 1]);
});

test("groupByDay keeps the newest day first for any dated items", () => {
  const groups = groupByDay([{ day: "2026-10-20", n: 1 }, { day: "2026-10-24", n: 2 }, { day: "2026-10-20", n: 3 }]);
  expect(groups).toEqual([{ day: "2026-10-24", items: [{ day: "2026-10-24", n: 2 }] },
    { day: "2026-10-20", items: [{ day: "2026-10-20", n: 1 }, { day: "2026-10-20", n: 3 }] }]);
});

test.each([
  ["plain text", [{ text: "plain text", marked: false }]],
  ["test <mark>one</mark> two <mark>three</mark>", [
    { text: "test ", marked: false }, { text: "one", marked: true }, { text: " two ", marked: false },
    { text: "three", marked: true }]],
  ["<mark>a <mark>b</mark> c</mark> d", [
    { text: "a ", marked: true }, { text: "b", marked: true }, { text: " c", marked: true }, { text: " d", marked: false }]],
  ["a</mark> b", [{ text: "a", marked: false }, { text: " b", marked: false }]],
  ["a <mark>b", [{ text: "a ", marked: false }, { text: "b", marked: true }]],
  ["", []],
])("splitSnippet %j", (snippet, parts) => expect(splitSnippet(snippet)).toEqual(parts));

afterEach(() => document.body.replaceChildren());

function rendered(snippet: string): HTMLElement {
  const { container } = render(h("p", null, renderSnippet(snippet)));
  return container.querySelector("p")!;
}

test("renderSnippet: text outside the markers is a text node, marked text is a <mark>", () => {
  const p = rendered("…test test <mark>one</mark> <mark>two</mark> three");
  const kinds = [...p.childNodes].map((n) => (n.nodeType === Node.TEXT_NODE ? `text:${n.textContent}` : `${n.nodeName}:${n.textContent}`));
  expect(kinds).toEqual(["text:…test test ", "MARK:one", "text: ", "MARK:two", "text: three"]);
});

test("renderSnippet: markup other than the two markers stays literal text", () => {
  const p = rendered(`<script>alert(1)</script> <b>bold</b> <mark><img src=x onerror=alert(1)></mark>`);
  expect(p.querySelector("script, b, img")).toBeNull();
  expect(p.querySelectorAll("mark")).toHaveLength(1);
  expect(p.querySelector("mark")!.textContent).toBe("<img src=x onerror=alert(1)>");
  expect(p.textContent).toBe("<script>alert(1)</script> <b>bold</b> <img src=x onerror=alert(1)>");
});

test("renderSnippet: nested or unbalanced markers do not throw", () => {
  expect(() => rendered("<mark><mark>a</mark>")).not.toThrow();
  expect(() => rendered("</mark></mark>b<mark>")).not.toThrow();
  expect(rendered("</mark></mark>b<mark>").textContent).toBe("b");
  expect(rendered("<mark><mark>a</mark>").querySelectorAll("mark")).toHaveLength(1);
});

test("convStart reads a conversation's local start from its id", () => {
  expect(convStart("c-20261023-225600")).toBe("22:56");
  expect(convStart("c-20261023-073314")).toBe("07:33");
  expect(convStart("conv_test")).toBeNull();
  expect(convStart("c-20261023-256000")).toBeNull();
});
