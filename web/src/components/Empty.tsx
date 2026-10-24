import type { ComponentChildren } from "preact";

interface Props {
  title: string;
  children?: ComponentChildren;
}

/** The one way a page says it has nothing to show, and what will fill it. */
export function Empty({ title, children }: Props) {
  return (
    <div class="empty" role="status">
      <p class="empty-title">{title}</p>
      {children && <p class="empty-text">{children}</p>}
    </div>
  );
}
