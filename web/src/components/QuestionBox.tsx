import { useEffect, useRef, useState } from "preact/hooks";
import { api, type AskResult, type AskSource, pollJob } from "../api";
import { dayMonth, hms } from "../format";
import { actionError, pollError } from "../insights";
import { jumpHref } from "../search";

type Reply = { phase: "idle" } | { phase: "thinking" } | { phase: "answer"; text: string; sources: AskSource[] } | { phase: "error"; text: string };

interface Props {
  /** The day to ask about; without one the question goes across every day. */
  day?: string;
}

/** "Ask about this day", or "Ask across every day": one question at a time, the answer in the reading face
 *  under it and, across days, the moments it drew on as links. The question stays in the field, and a new
 *  one replaces the answer. */
export function QuestionBox({ day }: Props) {
  const [question, setQuestion] = useState("");
  const [reply, setReply] = useState<Reply>({ phase: "idle" });
  const running = useRef<AbortController | null>(null);
  useEffect(() => () => running.current?.abort(), []);

  const across = day === undefined;
  const thinking = reply.phase === "thinking";
  const q = question.trim();

  async function ask(e: Event) {
    e.preventDefault();
    if (!q || thinking) return;
    const ctl = new AbortController();
    running.current = ctl;
    setReply({ phase: "thinking" });
    let job: string;
    try {
      ({ job } = across
        ? await api<{ job: string }>("POST", "/api/ask-days", { question: q })
        : await api<{ job: string }>("POST", "/api/ask", { day, question: q }));
    } catch (err) {
      if (!ctl.signal.aborted) setReply({ phase: "error", text: actionError(err) });
      return;
    }
    try {
      const done = await pollJob(job, { signal: ctl.signal });
      const result = done.result as AskResult;
      setReply({ phase: "answer", text: result.answer, sources: result.sources ?? [] });
    } catch (err) {
      if (!ctl.signal.aborted) setReply({ phase: "error", text: pollError(err) });
    }
  }

  const label = across ? "Ask across every day" : "Ask about this day";
  const placeholder = across ? 'For example, "when did I last talk about retention?"' : 'For example, "what did I decide about retention?"';
  return (
    <section class="ins-block ask">
      <form class="ask-form" onSubmit={ask}>
        <label class="section-title" for="ask-input">{label}</label>
        <div class="ask-row">
          <input id="ask-input" class="ask-input" type="text" autocomplete="off" value={question}
            placeholder={placeholder} onInput={(e) => setQuestion(e.currentTarget.value)} />
          <button class="btn primary" type="submit" disabled={!q || thinking}>Ask</button>
        </div>
      </form>
      {reply.phase === "thinking" && <p class="ins-quiet" role="status">Thinking…</p>}
      {reply.phase === "answer" && <p class="reading ask-answer">{reply.text}</p>}
      {reply.phase === "answer" && reply.sources.length > 0 && (
        <p class="ask-sources">
          {reply.sources.map((s) => (
            <a key={s.line_id} class="chip-time" href={jumpHref(s.day, s.line_id)}>{`${dayMonth(s.day)} ${hms(s.at_ms)}`}</a>
          ))}
        </p>
      )}
      {reply.phase === "error" && <p class="ins-error" role="alert">{reply.text}</p>}
    </section>
  );
}
