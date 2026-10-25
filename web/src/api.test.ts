import { afterEach, expect, test, vi } from "vitest";
import { api, ApiError, explainError, fetchAudioBlobUrl, initToken, pollJob } from "./api";

afterEach(() => vi.unstubAllGlobals());

function reply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

test("initToken reads ?token and strips it from the URL", () => {
  window.history.replaceState({}, "", "/?token=abc123&x=1");
  expect(initToken()).toBe("abc123");
  expect(window.location.search).toBe("?x=1");
});

test("initToken without a token in the URL keeps the one it has", () => {
  window.history.replaceState({}, "", "/?token=kept");
  initToken();
  window.history.replaceState({}, "", "/#/today");
  expect(initToken()).toBe("kept");
  expect(window.location.hash).toBe("#/today");
});

test("api adds the bearer header and throws ApiError on 4xx", async () => {
  window.history.replaceState({}, "", "/?token=abc123");
  initToken();
  const fetchMock = vi.fn().mockResolvedValueOnce(reply(200, [])).mockResolvedValueOnce(reply(409, { error: "busy" }));
  vi.stubGlobal("fetch", fetchMock);

  await expect(api("GET", "/api/days")).resolves.toEqual([]);
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/days");
  expect(init.method).toBe("GET");
  expect(new Headers(init.headers).get("Authorization")).toBe("Bearer abc123");
  expect(init.body).toBeUndefined();

  const err = (await api("POST", "/api/sync").catch((e) => e)) as ApiError;
  expect(err).toBeInstanceOf(ApiError);
  expect(err.status).toBe(409);
  expect(err.message).toBe("busy");
});

test("api sends a JSON body with its content type", async () => {
  const fetchMock = vi.fn().mockResolvedValue(reply(200, { appearance: "dark" }));
  vi.stubGlobal("fetch", fetchMock);
  await api("PUT", "/api/settings", { appearance: "dark" });
  const [, init] = fetchMock.mock.calls[0];
  expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
  expect(init.body).toBe(JSON.stringify({ appearance: "dark" }));
});

test("ApiError without an error field in the body names the status", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("oops", { status: 500 })));
  const err = (await api("GET", "/api/status").catch((e) => e)) as ApiError;
  expect(err).toBeInstanceOf(ApiError);
  expect(err.status).toBe(500);
  expect(err.message).toBe("HTTP 500");
});

test("fetchAudioBlobUrl fetches the clip with the token and returns an object URL", async () => {
  window.history.replaceState({}, "", "/?token=abc123");
  initToken();
  const fetchMock = vi.fn().mockResolvedValue(new Response(new Blob(["m4a"]), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const create = vi.fn().mockReturnValue("blob:x");
  const original = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
  Object.defineProperty(URL, "createObjectURL", { value: create, configurable: true, writable: true });
  try {
    expect(await fetchAudioBlobUrl("clip_1")).toBe("blob:x");
  } finally {
    if (original) Object.defineProperty(URL, "createObjectURL", original);
    else delete (URL as { createObjectURL?: unknown }).createObjectURL;
  }
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/audio/clip_1.m4a");
  expect(new Headers(init.headers).get("Authorization")).toBe("Bearer abc123");
  expect(create).toHaveBeenCalledOnce();
});

test("fetchAudioBlobUrl throws ApiError when the audio is gone", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(410, { error: "audio expired" })));
  const err = (await fetchAudioBlobUrl("clip_1").catch((e) => e)) as ApiError;
  expect(err).toBeInstanceOf(ApiError);
  expect(err.status).toBe(410);
  expect(err.message).toBe("audio expired");
});

test("api returns undefined for an empty 2xx body", async () => {
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(new Response(null, { status: 204 }))
    .mockResolvedValueOnce(new Response("", { status: 200 })));
  await expect(api("POST", "/api/pin/conv_1")).resolves.toBeUndefined();
  await expect(api("POST", "/api/pin/conv_1")).resolves.toBeUndefined();
});

test("the createObjectURL stub does not outlive its test", () => {
  expect(vi.isMockFunction(URL.createObjectURL)).toBe(false);
});

test("a 401 says how to get a window with its key, and no explanation says reload", () => {
  expect(explainError(new ApiError(401, "unauthorised"), "The days"))
    .toBe("The window was opened without its key. Close it and run lavalier window again.");
  for (const e of [new ApiError(500, "boom"), new TypeError("Failed to fetch")]) {
    const text = explainError(e, "The days");
    expect(text).toMatch(/^The days could not be loaded \(/);
    expect(text.toLowerCase()).not.toContain("reload");
  }
});

// --- jobs ---

function job(state: "running" | "done" | "error", extra: Record<string, unknown> = {}) {
  return { id: "j1", kind: "ask", key: "ask:1", state, result: null, error: null, started_ms: 1, finished_ms: null, ...extra };
}

test("pollJob asks every second until the job is done, and resolves with it", async () => {
  vi.useFakeTimers();
  try {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(reply(200, job("running")))
      .mockResolvedValueOnce(reply(200, job("running")))
      .mockResolvedValueOnce(reply(200, job("done", { result: { answer: "yes" } })));
    vi.stubGlobal("fetch", fetchMock);
    const done = pollJob("j1");
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(999);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1000);
    await expect(done).resolves.toMatchObject({ state: "done", result: { answer: "yes" } });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/jobs/j1");
  } finally {
    vi.useRealTimers();
  }
});

test("pollJob rejects with the job's error text", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(200, job("error", { error: "No key saved." }))));
  await expect(pollJob("j1")).rejects.toThrow("No key saved.");
});

test("pollJob stops asking once cancelled", async () => {
  vi.useFakeTimers();
  try {
    const fetchMock = vi.fn().mockImplementation(async () => reply(200, job("running")));
    vi.stubGlobal("fetch", fetchMock);
    const ctl = new AbortController();
    const done = pollJob("j1", { signal: ctl.signal });
    const outcome = done.then(() => "resolved", (e: Error) => e.name);
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    ctl.abort();
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(await outcome).toBe("AbortError");
  } finally {
    vi.useRealTimers();
  }
});

test("pollJob gives up after 30 minutes", async () => {
  vi.useFakeTimers();
  try {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => reply(200, job("running"))));
    const outcome = pollJob("j1", { every: 60_000 }).then(() => "resolved", (e: Error) => e.message);
    await vi.advanceTimersByTimeAsync(31 * 60_000);
    expect(await outcome).toBe("The job did not finish within 30 minutes.");
  } finally {
    vi.useRealTimers();
  }
});
