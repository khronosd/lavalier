import { useEffect, useRef, useState } from "preact/hooks";
import { navigate, replaceHash, type Route, toHash } from "../router";
import { CloseIcon, SearchIcon } from "./icons";

/** How long typing has to pause before the search runs. */
export const SEARCH_PAUSE_MS = 300;

interface Props {
  route: Route;
  /** The Search page's own field in the toolbar's title group: 420 px instead of 180. */
  wide?: boolean;
}

/** "Search every day": Enter or a short pause opens #/search?q=; the field follows the search page's query. */
export function SearchBox({ route, wide }: Props) {
  const routeQ = route.name === "search" ? route.query.q ?? "" : "";
  const [text, setText] = useState(routeQ);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const onSearch = route.name === "search";

  // Back, Forward and the links change the query; the field shows it (and empties off the search page)
  useEffect(() => setText(routeQ), [routeQ]);
  useEffect(() => () => clearTimeout(timer.current), []);

  function go(value: string) {
    clearTimeout(timer.current);
    const blank = value.trim() === "";
    if (blank && !onSearch) return;
    // the text as typed (the page trims it), so a pause after a space does not eat the space
    const hash = toHash({ name: "search", params: {}, query: { q: blank ? "" : value } });
    if (hash === window.location.hash) return;
    // refining a search replaces it; starting one from another page is a step Back can undo
    if (onSearch) replaceHash(hash);
    else navigate(hash);
  }

  function onInput(e: Event) {
    const value = (e.currentTarget as HTMLInputElement).value;
    setText(value);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => go(value), SEARCH_PAUSE_MS);
  }

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      go(text);
    } else if (e.key === "Escape" && text) {
      e.preventDefault();
      clear();
    }
  }

  function clear() {
    setText("");
    go("");
  }

  return (
    <div class={wide ? "search-box wide" : "search-box"} role="search">
      <SearchIcon />
      <input type="search" class="search-input" placeholder="Search every day" aria-label="Search every day"
        value={text} onInput={onInput} onKeyDown={onKeyDown} spellcheck={false} autoComplete="off" />
      {text && (
        <button type="button" class="search-clear" aria-label="Clear search" onClick={clear}><CloseIcon /></button>
      )}
    </div>
  );
}
