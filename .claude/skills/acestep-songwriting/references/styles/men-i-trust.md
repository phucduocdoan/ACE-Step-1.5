# Men I Trust

**Status: measured.** Eight tracks shipped from this sheet; the trap section below
comes from a six-seed study, not from listening.

Montreal trio, self-produced. Dream pop where the **bass is the lead instrument** —
the hook is almost always the bassline, not the vocal or the guitar. Get that one
fact into the caption and the rest follows; miss it and you get generic dream pop.

## Dimension table

| Dimension | What to write |
|---|---|
| Bass | DI'd Jazz or P-Bass **played with a pick**, flatwound strings, round and warm, carries the melody, loudest thing in the mix |
| Keys | Yamaha DX7 — FM electric piano, bell-like, slightly glassy. The band has credited this synth with defining their sound |
| Guitar | Clean, out-of-phase pickup positions, through chorus / flanger / phaser. Thin and watery, sits behind the bass |
| Drums | Vintage drum machine (TR-707, Oberheim DMX). Snare is fat but **dampened and tucked back**, not cracking |
| Vocal | Breathy female, mixed **low and close**, almost conversational, never belted |
| Production | Warm analog haze, lo-fi but not distorted, generous empty space, self-produced indie studio |

## Tempo and key

Approximate, a starting range rather than facts to defend. The range is wider than
the reputation suggests: *Tailwhip* ~114 BPM A minor, *Numb* ~139 BPM E major. They
also release a lot of fully instrumental tracks, which is worth using for variety
across a playlist — see the instrumental caption below and the `[Instrumental]`
handling in `../../SKILL.md`.

## Captions that have been measured

Mid-tempo, bass-led (the default):

> dreamy indie pop, soft breathy female vocal mixed low and close, melodic electric bass played with a pick carrying the main hook, clean electric guitar through chorus and flanger, warm FM electric piano, vintage drum machine with a fat snare, nostalgic and patient, warm lo-fi haze, unhurried groove, lots of space in the arrangement, self-produced indie studio

Fast and bright, the *Numb* end:

> upbeat dream pop with a driving groove, soft breathy female vocal mixed low, bright FM synthesizer lead line, punchy picked electric bass carrying the hook, clean electric guitar with chorus, crisp drum machine with a fat snare and tight hi-hat, bright and euphoric, warm analog sheen, eighties synth pop influence, self-produced indie studio

Instrumental:

> instrumental dream pop, no vocals, melodic picked electric bass carrying the entire melody, clean electric guitar with chorus and flanger trading phrases, warm FM electric piano, soft vintage drum machine with a fat snare, hypnotic and looping, warm lo-fi haze, patient and spacious, self-produced indie studio

Groove track, **after** the drum-forward fix:

> mellow dream pop with a gliding mid-tempo groove, soft breathy female vocal mixed low and close, warm round picked electric bass carrying the melody and sitting loudest in the mix, out-of-phase clean electric guitar with phaser and chorus, soft FM electric piano chords held long, muffled dampened drum machine tucked quietly behind the bass, soft brushed snare on a simple steady pattern, gentle and understated, warm analog haze, relaxed and spacious, self-produced indie studio

## Traps

### Do not reach for "funk"

An earlier version of that last caption read *"funky dream pop … tight drum machine
with a fat snare and crisp closed hi-hat … laid-back funk feel"*. It rendered with
39% of its energy in the 180–350 Hz snare body against a batch median of 19% —
audibly fatiguing, and it passed every level check.

Measured across six seeds, the word does two things:

| Caption | flux | kick 50–120 Hz | snare 180–350 Hz |
|---|---|---|---|
| with "funk" | 0.166–0.186 | 32–42% | **16 → 35%** |
| without | 0.153–0.159 | 41–48% | 18–19% |

It raises percussion, and — more dangerous — it makes the result **unstable**. With
it, the snare band swings more than twofold across seeds, so one good take says
nothing about the next. Men I Trust's own groove comes from the bass line, not from
a forward backbeat, so the word is not needed to get there.

### Vietnamese lyrics lose low-end share

Rendering the same eight captions and seeds with `--vocal-language vi` dropped the
low-band share on **7 of 7** vocal tracks, worst on the slowest material: `08_sun_up`
54.5% → 43.6%, `05_pump_four` 46.3% → 39.0%. Measured, but the cause is not
established — a proportion falls either because the bass got quieter or because the
vocal got louder, and Vietnamese is tonal with longer sustained vowels. Since the
bass is the hook in this style, check it by ear before shipping a non-English set.
See `../playlist-mit8-vi.sh`.

## Worked sets

| Set | Script |
|---|---|
| Eight-track nocturne playlist, English — verified by md5 | `../playlist-mit8.sh` |
| Same eight, Vietnamese lyrics, seeds and captions unchanged | `../playlist-mit8-vi.sh` |
