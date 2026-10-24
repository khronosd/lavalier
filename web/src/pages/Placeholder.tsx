import type { ComponentChildren } from "preact";
import { Empty } from "../components/Empty";

interface Props {
  title: string;
  lead?: ComponentChildren;
  emptyTitle: string;
  children?: ComponentChildren;
}

/** A page whose content comes in a later task: its title and an empty state, so navigation works now. */
export function Placeholder({ title, lead, emptyTitle, children }: Props) {
  return (
    <div class="page">
      <h1 class="page-title">{title}</h1>
      {lead && <p class="page-lead">{lead}</p>}
      <Empty title={emptyTitle}>{children}</Empty>
    </div>
  );
}
