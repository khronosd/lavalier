# Handoff spec: design E, the dark three-pane window

Design E is the direction chosen on the Lavalier canvas (`Lavalier Mac App Concepts`, artboards
E · day view, E · Search, E · Starred, E · Insights overview, E · Settings). The sources sit next to
this file as `e-day.dc.html`, `e-search.dc.html`, `e-starred.dc.html`, `e-insights.dc.html` and
`e-settings.dc.html`. Like `gui-v2b.html`, they are look and copy, not code: they use the canvas's
component format (`{{holes}}`, `<sc-for>`, `<sc-if>`) and will not render on their own. Read them
for the markup shape, the inline measurements and the colours; this document is the contract.

Everything here maps onto the existing window (`web/src/`): Preact, hash routes, the token file,
the Shell with its sidebar, and the routed pages. E is a palette change plus three new pieces of
layout (toolbar, list column, inspector) and one new component (the timeline band). The routes,
the API and the tests of behaviour stay as they are.

## Overview

The window is a Mac three-pane app in a dark material: a translucent sidebar on the left, a
52 px toolbar across the rest, and under it a 300 px list column, the content column, and a
260 px inspector on the right. The day view adds a band under the toolbar that carries the day's
name and a timeline of its conversations. The pendant moves out of the sidebar into a pill in
the toolbar. Audio plays from a floating mini-player at the bottom of the content column,
on every page, whenever something is playing.

What stays from the current window: the reading face for what people said, hairlines instead of
cards, no decorative animation, the lamp as the one live element, and every piece of copy that
describes what the recorder does to the pendant.

What is not in the mockups and should not be built: the desktop wallpaper behind the window
(mockup backdrop), the traffic lights (the native window draws them), and the sample data.

## Layout

Fixed-width columns, fluid content column. Measurements are the artboards' at 1x.

| Region | Size | Padding | Notes |
|---|---|---|---|
| Sidebar | 236 px wide, full height | 14 10 10 | Traffic-light space is 24 px tall at the top (the native title bar overlaps here; keep the first 38 px free of controls). Right hairline. |
| Toolbar | 52 px tall, spans list + content + inspector | 0 14 | Bottom hairline. Contents left to right: sidebar toggle, page title group (236 px wide, so it sits over the list column), page controls, spacer, actions, pendant pill. |
| Day band (day view only) | header row 32 px + 6 px + timeline 104 px, plus padding | 14 24 0 | Bottom hairline. See Timeline band. |
| List column | 300 px wide | 6 8 0 | Right hairline. Rows have `padding: 10px 12px`, radius 9, 2 px between rows. Section heads use the `hd` style with `padding: 8px 12px 4px`. |
| Content column | fluid, `min-width: 0` | 22 30 0 | Scrolls. Reading width is whatever is left; at the artboard size that is 464 px. Leave 84 px at the bottom for the mini-player. |
| Inspector | 260 px wide | 20 18 16 | Left hairline, column tint. Sections 16 px apart, the last element pinned to the bottom with `margin-top: auto`. |
| Mini-player | content column minus 16 px each side, 56 px tall, 14 px from the bottom | 0 12 0 10 | Floating, radius 14, glass. |

Window minimum: 236 + 300 + 420 + 260 = 1216 px wide. The window size is remembered in
`config.toml` already; clamp the saved width to this minimum.

### Responsive behaviour

The window is resized by the person, not by a device, so the breakpoints are window widths.

| Width | Changes |
|---|---|
| ≥ 1216 px | All four regions. |
| 1000 to 1215 px | The inspector collapses into a toolbar button (the sparkles icon) that opens it as a popover anchored to the button, same content, 300 px wide. |
| 760 to 999 px | The sidebar collapses too; the sidebar toggle in the toolbar opens it as an overlay over the list column (same markup, 236 px, with a scrim at 40% black). |
| < 760 px | The list column and the content column stack: the list is the page, and choosing a row pushes the content column over it with a back button in the toolbar. Do not build this until someone asks; it is noted so nothing in the layout forbids it. |

## Design tokens

Add these to `src/styles/tokens.css` as the dark theme. They replace the current
`:root[data-theme="dark"]` values; the light theme keeps its values until a light variant of E is
designed. The amber accent is also the star colour in E, so `--star` becomes an alias of `--accent`
in the dark theme.

| Token | Value | Usage |
|---|---|---|
| `--bg` | `#15151A` | Window and content column background |
| `--sidebar` | `rgba(30,30,36,.74)` | Sidebar fill, over a 30 px blur with 1.6 saturation when the host window is transparent; solid fallback `#202026` |
| `--column` | `rgba(255,255,255,.025)` | List column and inspector tint over `--bg` |
| `--panel` | `rgba(255,255,255,.045)` | Grouped settings boxes, model card |
| `--hairline` | `rgba(255,255,255,.08)` | Every divider and column edge |
| `--hair2` | `rgba(255,255,255,.14)` | Stronger line: timeline axis, pill rings |
| `--text` | `#F2F2F5` | Titles, primary labels |
| `--text-reading` | `#E6E6EA` | Transcript lines, quotes, follow-up text |
| `--text-soft` | `#CFCFD6` | Summary paragraphs, secondary body |
| `--text-2` | `#A4A4AC` | Meta lines, subtitles, counts |
| `--text-3` | `#8E8E99` | Section heads, times in the gutter, placeholders, footnotes |
| `--accent` | `#F2B340` | Selection fill, follow-up chips, timeline selection, play button, switches on |
| `--on-accent` | `#1C1A14` | Text and icons on an accent fill. Never white on amber: it fails contrast. |
| `--accent-soft` | `rgba(242,179,64,.16)` | Chip backgrounds, "Open day" link fill, search focus ring at .28 |
| `--accent-tint` | `rgba(242,179,64,.10)` | Starred transcript line background, the matched line in Search |
| `--accent-glow` | `rgba(242,179,64,.45)` | Shadow under the selected timeline block (`0 0 22px`) |
| `--mark-bg` | `rgba(242,179,64,.22)` | Matched words in search results |
| `--select` | `rgba(255,255,255,.10)` | Current sidebar row |
| `--control` | `rgba(255,255,255,.06)` | Segmented track, toolbar fields, day-nav group |
| `--control-2` | `rgba(255,255,255,.10)` | Buttons (`.btn`), question bubbles |
| `--control-3` | `rgba(255,255,255,.14)` | Selected segment, timeline blocks (unselected), stepper |
| `--ring` | `rgba(255,255,255,.12)` | Inset `.5px` ring on pills, buttons and fields |
| `--field-deep` | `rgba(0,0,0,.35)` | The question box input |
| `--ok` | `#34C759` | Lamp while listening or recording, doctor checks |
| `--warn` | `#FF6B6B` | Error dots and error text |
| `--radius-s` | 7 px | Buttons, nav rows, segments, toolbar fields |
| `--radius-m` | 9 px | List rows |
| `--radius-l` | 12 px | Grouped boxes, pull quote |
| `--radius-xl` | 14 px | Mini-player; pills use `height / 2` |

Keep `--ui` and `--reading` as they are. Type scale used by E:

| Style | Size / weight / tracking | Where |
|---|---|---|
| Page title | 22 px / 700 / -0.02em, line 1.2 | Conversation title, "Friday, October 23" on Insights, "Pendant" on Settings |
| Band title | 26 px / 700 / -0.025em with the date beside it at 20 px / 400 in `--text-3` | Day band |
| Toolbar title | 13 px / 600 with an 11 px `--text-2` subtitle, line 1.2 | Toolbar title group |
| Section head (`.hd`) | 11 px / 600 / uppercase / 0.05em in `--text-3` | Every column section |
| Row title | 13 px / 600 | List rows |
| Meta | 12.5 px in `--text-2`, tabular numerals | Under titles |
| Small | 11.5 px | Times in the gutter, footnotes, list-row second lines |
| Reading | `--reading` 15.5 px / 1.6 in `--text-reading` | Transcript lines, quotes in lists |
| Lead | `--reading` 17 px / 1.55 | Insight summary on the overview |
| Pull quote | `--reading` 19 px / 1.45 on `--accent-soft`, radius 12, padding 16 20 | Starred moment |

Icons: 16 px, 1.6 px stroke, round caps and joins, `currentColor`, the same drawing style as
`components/icons.tsx`. New ones needed: sidebar toggle, pin, share, return key, clock, bluetooth,
link, drive, half-circle (appearance), checkmark, refresh, chevrons, ellipsis, waveform. Draw them
in `icons.tsx`; no icon font.

## Components

| Component | File | Variant / props | Notes |
|---|---|---|---|
| Sidebar | `components/Sidebar.tsx` (existing) | unchanged props | Drop the SearchBox and the pendant slot. Order: Today, Starred, Search, Insights; then the "October" head and the days; Earlier…; Settings pinned to the bottom above a hairline. Day rows are indented 36 px so names align with the labels above. Count on the right in `--text-3`, stars as a 10 px filled star in `--accent` before the count. |
| Toolbar | new `components/Toolbar.tsx` | `title`, `subtitle`, `children` (page controls), `actions` | Rendered by Shell. The title group is 236 px wide and `flex: none` so it covers the list column. |
| PendantPill | new `components/PendantPill.tsx` | `status` from `usePendantStatus` | A 28 px pill: 8 px lamp with a glow (`0 0 0 3px` at .2 and `0 0 12px` at .75 of the lamp colour), state word, a 1 px divider, battery glyph with a fill proportional to `soc`, percentage. Click opens a popover (anchored, 320 px) whose body is the existing `PendantCard` restyled on `--panel`. The pill's `aria-label` reads the whole state. Lamp colours: listening and recording `--ok`, muted `--text-3` with no glow, unknown an outline. |
| Segmented | `components/Tabs.tsx` (existing) | unchanged | Track `--control` radius 8, 2 px padding; segment 24 px tall, 12.5 px, `--text-2`; selected `--control-3`, `--text`, 600, shadow `0 1px 2px rgba(0,0,0,.3)`. It moves from the day header into the toolbar. |
| TimelineBand | new `components/TimelineBand.tsx` | `view: DayView`, `selected: conversation_id`, `onPick` | See below. |
| ListColumn | new per page, under `pages/` | `children` | The 300 px column with its heads and rows. Row selection fill is `--accent` with `--on-accent` text, meta at `rgba(28,26,20,.72)`. |
| ConversationRow | new `components/ConversationRow.tsx` | `conv`, `selected` | Title and time range on line one, snippet (first line of the first transcript line, one line, ellipsis) and a 14-bar mini waveform on line two, duration and star count on line three. The waveform is decorative (`aria-hidden`): bars 2 px wide, 2 px apart, 3 to 16 px tall from the clips' loudness if the API grows it, else from a seeded sine as the mockup does. |
| Inspector | new `components/Inspector.tsx` | `label`, `children` | The 260 px column. The day view's inspector is the current `InsightsTab` content with the day's summary, follow-ups as 20 px chips plus text, people and topics as 24 px chips on `--control-2`, and the QuestionBox at the bottom on `--field-deep`. |
| MiniPlayer | new `components/MiniPlayer.tsx`, lifted from `Player.tsx` | the playlist state | 34 px accent play/pause button with `--on-accent` icon, a 118 px title block (title, then "9:15 · starred moment" in `--text-2`), a 28 px scrubber of 3 px bars (played in `--accent`, the rest `rgba(255,255,255,.22)`), elapsed / total, a speed button. The Audio tab keeps the full playlist; this one follows the playing clip. |
| GroupBox / Row | new in `styles/settings.css` | `.group`, `.row` | Box on `--panel` with an inset `.5px` ring, radius 12; rows 46 px minimum, `padding: 8px 16px`, hairline between rows. Controls on the right: `.btn` 24 px in rows, stepper 16 × 22 with two 8 px chevrons, switch 38 × 22 with an 18 px white knob. |
| DoctorPanel | new, Settings inspector | checks list | Needs a read-only `GET /api/doctor` that returns the same checks as `lavalier doctor --no-device` plus the last pendant read. Until that route exists, show the last `status` facts instead and leave the button out. |

### Timeline band

The band shows one day as a horizontal axis with a block per conversation.

- Range: from the start of the hour of the first conversation to the end of the hour of the
  last one, never shorter than 6 hours; an empty day shows 8:00 to 20:00 with no blocks.
- Hour lines every hour at `--hairline`, from 16 px below the top to 24 px above the bottom;
  labels (`11px`, `--text-3`, tabular, "8:00") centred under each line. If labels would be closer
  than 56 px, label every second hour.
- Axis: 1 px `--hair2` at 24 px from the bottom.
- Blocks: `<a>` to the conversation (`?at=c-<id>`), positioned by `start_ms` and `end_ms` as
  percentages of the range, bottom 28 px, radius 6, minimum width 6 px. Height 26 to 52 px from
  speech density (`speech_ms / (end_ms - start_ms)`), linear. Unselected `--control-3`; selected
  `--accent` with `0 0 22px var(--accent-glow)`.
- Block label: the conversation's label, else its time range; 11 px, centred over the block
  7 px above its top, `--text-2`, 600 and `--text` when selected. Drop a label whose centre is
  within 90 px of the previous drawn label's centre and put the text in the block's `title`.
- Stars: 6 px dots in `--accent` centred on the axis at each `star_ms`, with a 8 px glow.
- The band's header row: day name 26 px, date 20 px, then the summary line (conversations,
  speech, starred moments, audio-until) at 12.5 px `--text-2`; on the right the previous / Today /
  next group (`DayNav`, restyled as a 24 px segmented group on `--control`).

## States and interactions

| Element | State | Behaviour |
|---|---|---|
| List row | Hover | `rgba(255,255,255,.05)` fill. |
| List row | Selected | `--accent` fill, `--on-accent` text, meta at 72% black, stars and waveform bars in `--on-accent`. One row is always selected when the list has rows: the one the route names, else the first. |
| List row | Focus | 2 px `--accent` outline, 1 px offset (keep the current `:focus-visible` rule). |
| Sidebar row | Current | `--select` fill, 600 weight, icon in `--text`. |
| Toolbar icon button (`.tb`) | Hover | `rgba(255,255,255,.08)` fill, radius 7, 30 × 28. |
| Pendant pill | Busy (`aria-busy`) | Lamp keeps its colour, the state word becomes "Syncing…" or "Muting…", buttons in the popover disabled. No spinner. |
| Pendant pill | No address | State word "Not set", lamp outline, popover body says where to set it. |
| Pendant pill | Unmute pending | A small `--accent` dot after the state word; the popover shows the pending line as today. |
| Segmented | Selected | As in the tokens table. Each segment is a link, as now. |
| Timeline block | Hover | Label shown if it was dropped; cursor default. |
| Timeline block | Click | Navigates to the conversation and selects its row. |
| Transcript line | Starred | `--accent-tint` fill, radius 8, 8 px side padding pulled 8 px out with negative margins; filled 10 px star before the time. |
| Transcript line | Jump target (`?at=`) | The current flash rule, with `--accent-tint` as the flash colour. |
| Quiet gap | Between lines more than 5 minutes apart | A centred "6 minutes quiet" at 11.5 px `--text-3` between two hairlines, 8 px margin. Only in the transcript, never in search results. |
| Mini-player | Playing | Pause glyph; the played part of the scrubber fills left to right once a second. |
| Mini-player | Audio gone (outside retention) | The player does not appear; the conversation header's play button is disabled with the "audio deleted" title, as today. |
| Mini-player | Error | The player stays, the title block's second line shows the reason in `--warn`. |
| Search field (toolbar) | Focus | `0 0 0 3px` ring in `--accent-soft` at .28 alpha. |
| Search field | Has text | A 18 px clear button on the right, `rgba(255,255,255,.18)` disc with a dark × . |
| Search result | Match | `<mark>` on `--mark-bg`, radius 3, `0 2px` padding; in the selected row the mark is `rgba(0,0,0,.16)`. |
| Insights day row | Done | 8 px `--ok` dot; second line "Done at 04:10"; follow-up count on the right. |
| Insights day row | Generating | `--accent` dot with the lamp's glow rule; second line "Generating…". No pulse. |
| Insights day row | Not generated | `rgba(255,255,255,.25)` dot; a "Generate" link on the right in `--accent`, 600. |
| Insights day row | Error | `--warn` dot; second line "Could not generate · <reason>". |
| Switch | On | `--accent` track, knob at the right. Off: `--control-3` track, knob at the left. |
| Button (`.btn`) | Default | `--control-2` fill, inset ring, 28 px, 12.5 px 500. In rows: 24 px, 12 px. |
| Button | Primary | `--accent` fill, `--on-accent` text, 600, no ring. Only Sync now in the popover and the Ask button use it. |
| Button | Disabled | 45% opacity, as today. |

Hover states do not transition. The only motion in the window is the scrubber advancing and the
flash on a jump target; both exist today.

## Content rules

- Conversation titles: the calendar label when there is one, else the time range as now.
  The mockups show invented titles; do not synthesise titles from transcript text.
- Snippets in list rows: the first transcript line, one line, ellipsis. Never two lines.
- Long titles in rows and the mini-player: one line, ellipsis. Timeline labels: `title` on the
  block holds the full text.
- Star quotes in the Starred list: the starred line, in the reading face, up to three lines
  then ellipsis. A star with no quote (`quote: null`) shows "No words at this moment" in
  `--text-3`, as the current `.no-quote`.
- Counts: "7 conversations · 3 h 1 m of speech · 4 starred moments · audio kept until 22 Nov";
  singulars and the missing parts follow `day.ts` (`summarySentence`).
- Empty states keep the current `Empty` component, centred in the content column: no days yet,
  no matches, nothing starred, no insights without a provider. The list column shows its section
  head and nothing else.
- Loading: the content column shows the title and a `--text-3` "Loading…" subtitle, as today;
  no skeletons.
- Errors: the current `.notice.warn` inside the content column, in `--warn` with a 3 px left
  border; the only left-border element in the window.

## Edge cases

- A day with one conversation: one block, one label, the range still at least 6 hours.
- Fifty conversations in a day: blocks overlap at 1248 px; let them, with later ones on top,
  and rely on the list column. Labels thin themselves by the 90 px rule.
- A conversation spanning midnight: clamp the block to the range; the next day draws nothing.
- Pages waiting above 9,999: the pill shows "10k pages".
- Search for a word that appears many times in one line: mark every occurrence; the "n of m"
  control counts lines, not words.
- Insights without a provider: the overview's list column lists the days with the grey dot and
  no Generate link; the inspector shows the provider picker's "Choose a model" instead of the
  model card.
- Window narrower than 1216 px: see Responsive behaviour. Never let the content column drop
  below 420 px while the inspector is open.

## Accessibility

- Landmarks: `<nav aria-label="Sidebar">`, the toolbar as a `<div role="toolbar">`, the list
  column a `<section>` with a label, the content column `<article>` or `<main>`, the inspector
  `<aside>` with a label. Focus order: sidebar, toolbar left to right, list, content, inspector.
- Every list row is an `<a href>` to a route, so the list is keyboard-navigable with Tab and the
  arrow keys are not needed. Selection follows the route.
- Icon-only buttons carry `aria-label`; the pendant pill's label states lamp, battery and pages.
- Decorative SVGs (waveforms, timeline lines, dots) are `aria-hidden`; the timeline's blocks are
  links with the conversation's name and time in their label.
- Switches are `<button role="switch" aria-checked>`; steppers are two labelled buttons.
- Contrast: `--text-3` on `--bg` is 4.6:1, `--text-2` 7.3:1, `--on-accent` on `--accent` 11:1,
  `--accent` as text on `--bg` 9.8:1. Do not lighten `--bg` without rechecking `--text-3`.
- `prefers-reduced-motion` changes nothing, because nothing moves.

## Mapping onto the code

| Today | In E |
|---|---|
| `styles/tokens.css` dark values | Replaced by the token table. Light values untouched. |
| `components/Shell.tsx` | Renders Sidebar, then a column with Toolbar and the page; the page supplies its list column, content and inspector through props or slots. |
| `components/Sidebar.tsx` | Loses SearchBox and the pendant slot; row order as above. |
| `components/PendantCard.tsx` | Becomes the popover body of PendantPill; `usePendantStatus` stays in App. |
| `pages/Journal.tsx`, `pages/Day.tsx` | Day keeps its fetch and tabs. The Tabs move to the toolbar, DayHeader becomes the band header, `TimelineBand` goes under it, the conversation list becomes the list column, `Conversation` renders only the selected one in the content column (the transcript tab), `InsightsTab` content becomes the inspector. |
| `?tab=insights` | Still parsed; it focuses the inspector (or opens it when collapsed). The segmented control shows Transcript and Audio. If keeping three segments is preferred, the Insights tab shows the full insight in the content column and the inspector shows it condensed; decide before building. |
| `pages/Search.tsx` | The search field renders in the toolbar on this page (the sidebar's SearchBox is gone). Hits group by day in the list column; the content column fetches `/api/day/<date>` for the selected hit and renders its conversation with the hit line marked; the inspector shows the counts, where it comes up, and recent searches (keep the last five queries in memory). |
| `pages/Starred.tsx` | The list column groups `/api/starred` by day; the content column shows the pull quote and the conversation lines around the star; the inspector shows the star's time, the audio-until date, pin and copy buttons, and the other stars of that conversation. |
| `pages/Insights.tsx` | The list column is the days with their insight state from `/api/insights`; the content column is the selected day's insight with the question box in the floating bar; the inspector is the model card, the automatic switch and the two catch-up buttons with their estimates. |
| `pages/Settings.tsx`, `SettingsTabs.tsx` | Six sections in the list column with 26 px coloured icon tiles (General, Pendant, Retention shown as "Storage", Model, Connectors, Appearance); the mockup shows five and omits General, keep General first. The content column renders the section as group boxes; the inspector is the doctor panel. |
| `components/Player.tsx` | Split: the clip-feeding logic stays, the chrome becomes MiniPlayer at Shell level and the Audio tab's list. |

Build order that keeps the window usable at each step: tokens, Shell with Toolbar and the
pendant pill, the day view's list column and inspector, the timeline band, the mini-player, then
Search, Starred, Insights, Settings. Rebuild and commit `src/lavalier/web/dist/` after each step,
as `web/README.md` says.

## Open questions

1. Insights tab versus inspector on the day view (see the mapping table). Recommendation: two
   segments, inspector carries the insight.
2. `GET /api/doctor` does not exist. Either add it (read-only, same checks as the CLI with
   `--no-device` plus the last pendant read) or ship Settings without the doctor panel.
3. Vibrancy needs a transparent native window. If the host cannot do that, the sidebar is solid
   `#202026` and nothing else changes.
4. Per-clip loudness for the mini waveforms is not in `DayView`. The seeded placeholder is fine
   for a first build; a `loudness` array per clip would make it honest.
