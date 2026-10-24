import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "vitest/config";
import preact from "@preact/preset-vite";

// The dev server proxies /api to a running `lavalier app`; its port is in <root>/.server.json.
function appPort(): number | null {
  const root = process.env.PENDANT_ROOT ?? join(homedir(), "Pendant");
  try {
    return JSON.parse(readFileSync(join(root, ".server.json"), "utf8")).port;
  } catch {
    return null;
  }
}

export default defineConfig(({ command }) => {
  const port = command === "serve" && !process.env.VITEST ? appPort() : null;
  return {
    plugins: [preact()],
    base: "/",
    build: { outDir: "../src/lavalier/web/dist", emptyOutDir: true },
    server: port
      ? {
          proxy: {
            "/api": {
              target: `http://127.0.0.1:${port}`,
              // the app refuses a foreign Origin; the dev page's origin is not its own
              configure: (proxy) => proxy.on("proxyReq", (req) => req.removeHeader("origin")),
            },
          },
        }
      : {},
    test: { environment: "jsdom", globals: true },
  };
});
