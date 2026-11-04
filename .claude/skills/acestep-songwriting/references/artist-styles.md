# Artist Style Decompositions

Reference sheets for captions that chase a specific act's sound.

**Never put an artist's name in a caption.** The model does not reliably know
who they are, and a name that half-lands pulls in whatever else shares it. Spend
the words on instruments, production and vocal treatment instead — that is what
the model actually conditions on. Each sheet below is that decomposition, plus
the captions that have been generated and measured.

Tempos and keys are per-song approximations, useful as a starting range rather
than as facts to defend.

---

## Men I Trust

Montreal trio, self-produced. Dream pop where the **bass is the lead instrument**
— the hook is almost always the bassline, not the vocal or the guitar.

| Dimension | What to write |
|---|---|
| Bass | DI'd Jazz or P-Bass **played with a pick**, flatwound strings, round and warm, carries the melody, loudest thing in the mix |
| Keys | Yamaha DX7 — FM electric piano, bell-like, slightly glassy. The band has credited this synth with defining their sound |
| Guitar | Clean, out-of-phase pickup positions, through chorus / flanger / phaser. Thin and watery, sits behind the bass |
| Drums | Vintage drum machine (TR-707, Oberheim DMX). Snare is fat but **dampened and tucked back**, not cracking |
| Vocal | Breathy female, mixed **low and close**, almost conversational, never belted |
| Production | Warm analog haze, lo-fi but not distorted, generous empty space, self-produced indie studio |

Tempo range is wider than the reputation suggests: *Tailwhip* ~114 BPM A minor,
*Numb* ~139 BPM E major. They also release a lot of fully instrumental tracks,
which is worth using for variety across a playlist.

### Captions that have been measured

Mid-tempo, bass-led (the default):

> dreamy indie pop, soft breathy female vocal mixed low and close, melodic electric bass played with a pick carrying the main hook, clean electric guitar through chorus and flanger, warm FM electric piano, vintage drum machine with a fat snare, nostalgic and patient, warm lo-fi haze, unhurried groove, lots of space in the arrangement, self-produced indie studio

Fast and bright, the *Numb* end:

> upbeat dream pop with a driving groove, soft breathy female vocal mixed low, bright FM synthesizer lead line, punchy picked electric bass carrying the hook, clean electric guitar with chorus, crisp drum machine with a fat snare and tight hi-hat, bright and euphoric, warm analog sheen, eighties synth pop influence, self-produced indie studio

Instrumental:

> instrumental dream pop, no vocals, melodic picked electric bass carrying the entire melody, clean electric guitar with chorus and flanger trading phrases, warm FM electric piano, soft vintage drum machine with a fat snare, hypnotic and looping, warm lo-fi haze, patient and spacious, self-produced indie studio

Groove track, **after** the drum-forward fix (see the warning below):

> mellow dream pop with a gliding mid-tempo groove, soft breathy female vocal mixed low and close, warm round picked electric bass carrying the melody and sitting loudest in the mix, out-of-phase clean electric guitar with phaser and chorus, soft FM electric piano chords held long, muffled dampened drum machine tucked quietly behind the bass, soft brushed snare on a simple steady pattern, gentle and understated, warm analog haze, relaxed and spacious, self-produced indie studio

### Warning: do not reach for "funk"

An earlier version of that last caption read *"funky dream pop … tight drum
machine with a fat snare and crisp closed hi-hat … laid-back funk feel"*. It
rendered with 39% of its energy in the 180–350 Hz snare body against a batch
median of 19% — audibly fatiguing, and it passed every level check.

Measured across six seeds, the word does two things:

| Caption | flux | kick 50–120 Hz | snare 180–350 Hz |
|---|---|---|---|
| with "funk" | 0.166–0.186 | 32–42% | **16 → 35%** |
| without | 0.153–0.159 | 41–48% | 18–19% |

It raises percussion, and — more dangerous — it makes the result **unstable**.
With it, the snare band swings more than twofold across seeds, so one good take
says nothing about the next. Men I Trust's own groove comes from the bass line,
not from a forward backbeat, so the word is not needed to get there.

---

## Joji

Bedroom trip-hop / alternative R&B. Defined by negative space and reverb depth.

| Dimension | What to write |
|---|---|
| Vocal | Light airy male falsetto, 2–3 layered takes mixing a normal and a deeper tone |
| Reverb | Plate or hall, 2.5–4 s decay, 50–100 ms pre-delay, on a **bus** rather than an insert — the vocal sits inside the space, not in front of it |
| Keys | Soft muted upright or felt piano |
| Bass | Deep sub bass, felt more than heard |
| Drums | Sparse lo-fi, distant clap or rimshot, often nearly absent |
| Texture | Warped tape, vinyl crackle, saturation |
| Arrangement | Minimal, lots of silence — the space is the point |

*Glimpse of Us* ~85 BPM A♭, *Slow Dancing in the Dark* ~89 BPM E♭.

> melancholic bedroom trip hop, light airy male falsetto drenched in deep plate reverb, soft muted upright piano, sparse deep sub bass, soft electronic drums with a distant clap, warped lo-fi tape texture, saturated and hazy, intimate and sad, minimal arrangement with lots of negative space, modern alternative R&B production

For the slowest, sparsest end of it:

> very slow melancholic bedroom ballad, fragile male falsetto layered in deep hall reverb, sparse muted piano, deep sub bass felt more than heard, almost no drums, faint vinyl crackle and tape warble, desolate and resigned, extreme negative space, nearly ambient, lo-fi alternative R&B production
