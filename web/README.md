# The window

The lavalier window is a small Preact + TypeScript app built with Vite. The background app
(`lavalier app`) serves the built page from `src/lavalier/web/dist/` on its loopback port, together
with the token-protected `/api/` routes; the native window shows that page.

`src/lavalier/web/dist/` is committed: the Python package ships it as package data, so installing
lavalier needs no Node. Rebuild and commit it whenever anything under `web/src/` changes.

## Install

Node 25 and npm 11 (Homebrew). Versions are pinned exactly in `package.json`; `package-lock.json`
is committed.

    cd web
    npm ci

## Build, check and test

    npm run typecheck   # tsc --noEmit
    npm test            # Vitest, jsdom
    npm run build       # writes ../src/lavalier/web/dist (emptied first)

The built page references only `/assets/...` and nothing outside the app;
`tests/test_web_dist.py` checks that from the Python side.

## Dev server

Start the app first (`lavalier app`, or `PENDANT_ROOT=<root> lavalier app` for a scratch root). It
writes its port and token to `<root>/.server.json`. Then:

    cd web
    PENDANT_ROOT=<root> npm run dev   # root defaults to ~/Pendant

Vite proxies `/api` to the port in `.server.json` (read when the dev server starts, so restart it
after restarting the app) and drops the browser's `Origin` header, which the app would otherwise
refuse. The API needs the token, so open the page with it once:

    http://localhost:5173/?token=<token from .server.json>

The page keeps the token in memory and removes it from the address bar; reloading without it
leaves the window signed out, so open the `?token=` URL again.

## Layout

- `src/api.ts`: the token, `api()`, `fetchAudioBlobUrl()` and the types of the server's JSON
- `src/router.ts`: hash routes `#/today`, `#/day/<date>`, `#/starred`, `#/search?q=`, `#/insights`, `#/settings/<tab>`;
  a day keeps `?tab=`, `?conv=` and `?at=`, Search `&hit=`, Starred `?star=`, Insights `?day=` (the selected row)
- `src/theme.ts`: `applyAppearance("system" | "light" | "dark")`
- `src/format.ts`: times, durations and day titles, in fixed English
- `src/styles/tokens.css`: colours for light and dark (dark is design E); `src/styles/base.css`: base rules and
  the sidebar; `src/styles/shell.css`: the toolbar, the panes, the pendant pill and the popovers
- `src/shellState.ts`: what the shell shares with the frames under it (route, pendant status, which panes show)
- `src/playback.tsx`: the window's one `<audio>` element and what the mini-player draws; `src/dayCache.ts`: a day's view
  for the pages that show one conversation of it (Search, Starred, Insights)
- `src/day.ts`, `src/selection.ts`, `src/timeline.ts`, `src/wave.ts`, `src/search.ts`, `src/insights.ts`, `src/pendant.ts`:
  pure helpers with their tests (the band's line, which conversation is selected, the timeline's geometry, the
  placeholder waveform, word marking and recent searches, the days' insight states, the pendant's words)
- `src/components/`: `Shell` (sidebar + frame), `Frame` (a page's toolbar, band, list column, content and inspector),
  `Toolbar`, `PendantPill`, `TimelineBand`, `MiniPlayer`, `ConversationRow`, the sidebar, the empty state;
  `src/pages/`: the routed pages, each rendering a `Frame`; `src/styles/`: one sheet per region or page
- `reference/`: the design the window follows: `design-e.md` is the contract, the `e-*.dc.html` files and the two
  earlier mockups are look and copy, not specs
