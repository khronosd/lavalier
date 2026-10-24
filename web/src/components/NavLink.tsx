import type { ComponentChildren } from "preact";
import { type Route, toHash } from "../router";

interface Props {
  to: Route;
  /** "page" for the open page; "true" for the section the open page belongs to. */
  current?: "page" | "true";
  icon?: ComponentChildren;
  label: ComponentChildren;
  count?: ComponentChildren;
  class?: string;
}

export function NavLink({ to, current, icon, label, count, class: cls }: Props) {
  return (
    <li>
      <a class={cls ? `nav-item ${cls}` : "nav-item"} href={toHash(to)} aria-current={current}>
        {icon}
        <span>{label}</span>
        {count !== undefined && <span class="nav-count">{count}</span>}
      </a>
    </li>
  );
}
