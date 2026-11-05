# Joji

**Status: unverified.** Written from listening. No caption below has been rendered
or measured, so there is no trap section — not because the style has none, but
because none has been hit yet. Treat every claim here as a starting guess.

Bedroom trip-hop / alternative R&B. Defined by negative space and reverb depth: the
arrangement is mostly silence, and the vocal sits *inside* a room rather than in
front of one.

## Dimension table

| Dimension | What to write |
|---|---|
| Vocal | Light airy male falsetto, 2–3 layered takes mixing a normal and a deeper tone |
| Reverb | Plate or hall, 2.5–4 s decay, 50–100 ms pre-delay, on a **bus** rather than an insert — the vocal sits inside the space, not in front of it |
| Keys | Soft muted upright or felt piano |
| Bass | Deep sub bass, felt more than heard |
| Drums | Sparse lo-fi, distant clap or rimshot, often nearly absent |
| Texture | Warped tape, vinyl crackle, saturation |
| Arrangement | Minimal, lots of silence — the space is the point |

## Tempo and key

Approximate. *Glimpse of Us* ~85 BPM A♭, *Slow Dancing in the Dark* ~89 BPM E♭.

## Captions (not yet rendered)

Default:

> melancholic bedroom trip hop, light airy male falsetto drenched in deep plate reverb, soft muted upright piano, sparse deep sub bass, soft electronic drums with a distant clap, warped lo-fi tape texture, saturated and hazy, intimate and sad, minimal arrangement with lots of negative space, modern alternative R&B production

Slowest, sparsest end:

> very slow melancholic bedroom ballad, fragile male falsetto layered in deep hall reverb, sparse muted piano, deep sub bass felt more than heard, almost no drums, faint vinyl crackle and tape warble, desolate and resigned, extreme negative space, nearly ambient, lo-fi alternative R&B production

## What to watch when this is first rendered

Not traps — nothing has gone wrong yet, because nothing has been tried. These are
the two places this decomposition is most likely to fail, worth checking first:

- **"almost no drums" / "nearly ambient" are negations and absences.** `../../SKILL.md`
  warns the model reads the noun, not the negation. These may produce drums anyway.
  If so, rewrite as a positive: name something else that fills the space.
- **Deep sub bass "felt more than heard" is a mix instruction, not an instrument.**
  Caption word count sets loudness, so this phrasing may yield a sub that is simply
  absent. Compare the low-band share against a Men I Trust render before judging it.

Run `scripts/audio_qc.py` over the first batch and move the real findings into a
*Traps* section. Then update the status in `README.md`.
