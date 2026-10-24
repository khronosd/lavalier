import { afterEach, expect, test, vi } from "vitest";
import { api, ApiError, fetchAudioBlobUrl, initToken } from "./api";

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
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create }));

  expect(await fetchAudioBlobUrl("clip_1")).toBe("blob:x");
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
