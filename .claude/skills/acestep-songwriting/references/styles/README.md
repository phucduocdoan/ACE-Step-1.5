# Style Patterns

One sheet per style, each decomposing a sound into the instruments, production and
vocal treatment that go in a caption. Read the sheet for the style you are chasing;
you do not need the others.

**Never put an artist's name in a caption.** The model does not reliably know who
they are, and a name that half-lands pulls in whatever else shares it. Spend the
words on what the model actually conditions on. Every sheet here is that
decomposition.

## Index

| Style | Shape | Lead instrument | Status | Sheet |
|---|---|---|---|---|
| Men I Trust | dream pop, bass-led, warm lo-fi haze | picked electric bass | **measured** — 8 tracks shipped, 6-seed study on the "funk" trap | `men-i-trust.md` |
| Joji | bedroom trip-hop / alt R&B, negative space | layered falsetto in deep reverb | **unverified** — written from listening, never rendered | `joji.md` |

**Status is the column that matters.** *Measured* means captions in that sheet have
been rendered and run through `scripts/audio_qc.py`, and the numbers quoted are from
those runs. *Unverified* means the decomposition is plausible and nothing more — the
captions may well render badly, and no trap section exists because no trap has been
hit yet. Do not treat the two as equally load-bearing.

## Worked sets

Complete, reproducible runs. Useful as a whole example of caption plus lyrics plus
parameters, or to extend.

| Set | Style | Script |
|---|---|---|
| Eight-track nocturne playlist, English | Men I Trust | `../playlist-mit8.sh` |
| Same eight, Vietnamese lyrics | Men I Trust | `../playlist-mit8-vi.sh` |

## Writing a new sheet

Follow the same six sections, in this order. The order is deliberate: everything
above *Traps* is what you need to write a first caption, everything below is what
you only learn by rendering.

1. **One-line identity.** What the genre is and the single structural fact that
   defines it — usually which instrument carries the hook.
2. **Dimension table.** One row per element (bass, keys, guitar, drums, vocal,
   production), and in each row *the words to actually write*, not a description of
   the sound. The table is a caption kit, not an essay.
3. **Tempo and key.** A range, flagged as approximate. Note where the real range is
   wider than the act's reputation, because that is where playlist variety comes from.
4. **Captions that have been measured.** Verbatim, with what each one is for. An
   unrendered caption does not belong in this section — put it under a heading that
   says so, or leave it out.
5. **Traps.** Only things that have measurably gone wrong, with the numbers. A trap
   without a measurement is a hunch; say so or omit it.
6. **Worked sets.** Links to the playlist scripts that used this sheet, if any.

Start a new sheet at *unverified* and say so in the index. Promote it to *measured*
only after its captions have actually been rendered and QC'd — the same rule that
governs the md5 headers on the playlist scripts.
