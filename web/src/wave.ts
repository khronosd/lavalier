// The small waveform beside a conversation row. Clips carry no loudness yet, so the bars are a placeholder
// drawn from the conversation's id, as the mockup draws them; a `loudness` array per clip would replace this.

/** `n` bar heights from `lo` to `hi`, the same for the same seed. */
export function waveBars(seed: number, n = 14, lo = 3, hi = 16): number[] {
  const out: number[] = [];
  for (let i = 0; i < n; i++) {
    const v = Math.abs(Math.sin(i * 0.9 + seed)) * 0.6 + Math.abs(Math.sin(i * 2.3 + seed * 1.7)) * 0.4;
    out.push(Math.round(lo + v * (hi - lo)));
  }
  return out;
}

/** A small stable number from an id, for the placeholder's seed. */
export function seedOf(id: string): number {
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) % 1000;
  return h;
}
