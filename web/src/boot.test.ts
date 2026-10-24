import { afterEach, expect, test, vi } from "vitest";
import { start } from "./boot";

const json = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });

afterEach(() => {
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.theme;
});

function media() {
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} }));
}

test("the saved appearance is applied before the shell is mounted", async () => {
  media();
  vi.stubGlobal("fetch", vi.fn(async () => json({ appearance: "dark" })));
  let seen = "";
  await start(() => { seen = document.documentElement.dataset.theme ?? ""; });
  expect(seen).toBe("dark");
});

test("without settings the window follows the system and still mounts", async () => {
  media();
  vi.stubGlobal("fetch", vi.fn(async () => json({ error: "no" }, 503)));
  let seen = "";
  await start(() => { seen = document.documentElement.dataset.theme ?? ""; });
  expect(seen).toBe("light");
});
