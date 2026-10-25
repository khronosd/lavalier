import { useEffect, useRef, useState } from "preact/hooks";
import { api, pollJob, type AskResult } from "../api";
import { actionError, pollError } from "../insights";

type Reply = { phase: "idle" } | { phase: "thinking" } | { phase: "answer" | "error"; text: string };

/** "Ask about this day": one question at a time, the answer in the reading face under it. The question
 *  stays in the field, and a new one replaces the answer. */
export function QuestionBox({ day }: { day: string }) {
  const [question, setQuestion] = useState("");
  const [reply, setReply] = useState<Reply>({ phase: "idle" });
  const running = useRef<AbortController | null>(null);
  useEffect(() => () => running.current?.abort(), []);

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
      ({ job } = await api<{ job: string }>("POST", "/api/ask", { day, question: q }));
    } catch (err) {
      if (!ctl.signal.aborted) setReply({ phase: "error", text: actionError(err) });
      return;
    }
    try {
      const done = await pollJob(job, { signal: ctl.signal });
      setReply({ phase: "answer", text: (done.result as AskResult).answer });
    } catch (err) {
      if (!ctl.signal.aborted) setReply({ phase: "error", text: pollError(err) });
    }
  }

  return (
    <section class="ins-block ask">
      <form class="ask-form" onSubmit={ask}>
        <label class="section-title" for="ask-input">Ask about this day</label>
        <div class="ask-row">
          <input id="ask-input" class="ask-input" type="text" autocomplete="off" value={question}
            placeholder={'For example, "what did I decide about retention?"'}
            onInput={(e) => setQuestion(e.currentTarget.value)} />
          <button class="btn" type="submit" disabled={!q || thinking}>Ask</button>
        </div>
      </form>
      {reply.phase === "thinking" && <p class="ins-quiet" role="status">Thinking…</p>}
      {reply.phase === "answer" && <p class="reading ask-answer">{reply.text}</p>}
      {reply.phase === "error" && <p class="ins-error" role="alert">{reply.text}</p>}
    </section>
  );
}
