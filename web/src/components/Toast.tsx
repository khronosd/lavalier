/** A short confirmation at the bottom of the main area; it fades in and out, nothing else moves. */
export function Toast({ text, on }: { text: string; on: boolean }) {
  return (
    <div class="toast-row" role="status">
      {text && <span class={on ? "toast on" : "toast"}>{text}</span>}
    </div>
  );
}
