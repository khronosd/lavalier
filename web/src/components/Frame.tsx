import type { ComponentChildren } from "preact";
import { useEffect, useRef } from "preact/hooks";
import { useShell } from "../shellState";
import { Toolbar, type ToolbarProps } from "./Toolbar";

interface Props {
  toolbar: ToolbarProps;
  /** The 300 px list column's content; a page without one leaves it out. */
  list?: ComponentChildren;
  listLabel?: string;
  /** The 260 px inspector's content; a page without one leaves it out. */
  inspector?: ComponentChildren;
  inspectorLabel?: string;
  /** When this takes a new value the inspector opens (if folded away) and takes focus: `?tab=insights`. */
  focusInspector?: string;
  children: ComponentChildren;
}

/** A page's frame: the toolbar, then the list column, the content column and the inspector. Below 1216 px
 * the inspector is a popover behind the toolbar's sparkles button; the page's markup is the same. */
export function Frame({ toolbar, list, listLabel = "List", inspector, inspectorLabel = "Inspector", focusInspector, children }: Props) {
  const shell = useShell();
  const aside = useRef<HTMLElement>(null);
  const hasInspector = inspector != null && inspector !== false;
  const folded = shell.compact && hasInspector;
  const shown = hasInspector && shell.inspectorShown;
  const open = useRef(shell.openInspector);
  open.current = shell.openInspector;
  useEffect(() => { if (focusInspector && hasInspector) open.current(); }, [focusInspector]);
  useEffect(() => { if (focusInspector && shown) aside.current?.focus(); }, [focusInspector, shown]);

  const asideEl = shown && (
    <aside class="inspector" aria-label={inspectorLabel} tabIndex={-1} ref={aside}>{inspector}</aside>
  );
  return (
    <>
      <Toolbar {...toolbar} inspectorToggle={folded} inspectorPopover={folded ? asideEl : undefined} />
      <div class="panes">
        {list != null && <section class="list-col" aria-label={listLabel}>{list}</section>}
        <main class="content">{children}</main>
        {!folded && asideEl}
      </div>
    </>
  );
}
