// tokens.css is the one place colours live. Every token a stylesheet reads must exist in both themes
// (or on :root), and the dark theme is design E (web/reference/design-e.md).

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "vitest";

const dir = join(__dirname, "styles");
const tokens = readFileSync(join(dir, "tokens.css"), "utf8");

/** The declarations inside the first block whose selector starts with `selector`. */
function block(selector: string): string {
  const at = tokens.indexOf(selector);
  expect(at, `a block for ${selector}`).toBeGreaterThanOrEqual(0);
  const open = tokens.indexOf("{", at);
  return tokens.slice(open + 1, tokens.indexOf("}", open));
}

const defined = (body: string) => new Set([...body.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]));
const value = (body: string, name: string) => new RegExp(`${name}\\s*:\\s*([^;]+);`).exec(body)?.[1].trim();

const light = block(':root[data-theme="light"]');
const dark = block(':root[data-theme="dark"]');
const shared = block(":root {");

/** Custom properties set on an element, not tokens: a calendar's colour dot. */
const LOCAL = new Set(["--dot"]);

test("every token the stylesheets read is defined for both themes", () => {
  const used = new Set<string>();
  for (const name of readdirSync(dir)) {
    for (const m of readFileSync(join(dir, name), "utf8").matchAll(/var\((--[\w-]+)/g)) used.add(m[1]);
  }
  const both = new Set([...defined(light)].filter((t) => defined(dark).has(t)));
  const missing = [...used].filter((t) => !LOCAL.has(t) && !defined(shared).has(t) && !both.has(t)).sort();
  expect(missing).toEqual([]);
});

test("the dark theme is design E", () => {
  expect(value(dark, "--bg")).toBe("#15151A");
  expect(value(dark, "--sidebar")).toBe("#202026");
  expect(value(dark, "--accent")).toBe("#F2B340");
  expect(value(dark, "--on-accent")).toBe("#1C1A14");
  expect(value(dark, "--text-3")).toBe("#8E8E99");
  expect(value(dark, "--star")).toBe("var(--accent)");
  expect(value(shared, "--radius-xl")).toBe("14px");
});

test("the light theme keeps its palette", () => {
  expect(value(light, "--bg")).toBe("#F5F5F7");
  expect(value(light, "--accent")).toBe("#2F6FDE");
  expect(value(light, "--star")).toBe("#B7791F");
});
