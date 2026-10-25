import type { ComponentChildren } from "preact";
import { usePendant, useShell } from "../shellState";
import { InsightsIcon, SidebarIcon } from "./icons";
import { PendantPill } from "./PendantPill";
import { Popover } from "./Popover";
import { SearchBox } from "./SearchBox";

export interface ToolbarProps {
  title?: string;
  subtitle?: string;
  /** The page's controls, after the title group (a segmented control). */
  children?: ComponentChildren;
  /** The page's actions, right of the spacer. */
  actions?: ComponentChildren;
  /** Where the search field goes: at the right (default), in the title group (the Search page), or nowhere. */
  search?: "right" | "title" | "none";
}

interface Props extends ToolbarProps {
  /** The inspector is folded away at this width: draw its toggle, and the popover when it is open. */
  inspectorToggle?: boolean;
  inspectorPopover?: ComponentChildren;
}

/** The 52 px bar over the panes: the sidebar toggle, the title group (236 px, over the list column), the
 * page's controls, a spacer, its actions, the search field, the inspector toggle when folded, the pendant pill. */
export function Toolbar({ title, subtitle, children, actions, search = "right", inspectorToggle, inspectorPopover }: Props) {
  const shell = useShell();
  const pendant = usePendant();
  return (
    <div class="toolbar" role="toolbar" aria-label="Toolbar">
      <button type="button" class="tb" aria-label={shell.sidebarShown ? "Hide sidebar" : "Show sidebar"}
        onClick={shell.toggleSidebar}><SidebarIcon /></button>
      {search === "title" && <SearchBox route={shell.route} wide />}
      {search !== "title" && (title || subtitle) && (
        <div class="tb-title">
          {title && <span class="tb-name">{title}</span>}
          {subtitle && <span class="tb-sub">{subtitle}</span>}
        </div>
      )}
      {children}
      <div class="tb-spacer" />
      {actions}
      {search === "right" && <SearchBox route={shell.route} />}
      {inspectorToggle && (
        <div class="popover-anchor">
          <button type="button" class="tb" aria-label={shell.inspectorShown ? "Hide inspector" : "Show inspector"}
            aria-expanded={shell.inspectorShown} onClick={shell.toggleInspector}><InsightsIcon /></button>
          <Popover open={shell.inspectorShown} onClose={shell.closeInspector} class="inspector-popover">{inspectorPopover}</Popover>
        </div>
      )}
      {pendant && <PendantPill pendant={pendant} />}
    </div>
  );
}
