# Writing Titles and Descriptions That Do Not Read as AI

Craft notes. The policy side is `youtube-policy.md`.

The problem this solves is narrow and real: a description can be accurate, well
organised and completely correct, and still make a listener close the tab, because
it reads like it was generated. On a channel whose music *is* generated, that
impression is expensive.

## The four tells

Taken from a first draft that was rejected, with what was wrong with each line.

| Line that was cut | Why it read as AI |
|---|---|
| `Dream pop. 95 BPM, A minor.` as the opening | A spec sheet. Nobody introduces their own song with metadata. Moving it to the bottom does not fix it - see the worked example |
| `Chorus pedal on everything, an old drum machine, vocals mixed too low` | Copied down from the channel's About tab. Pasting the bio into every video is exactly what a template channel does, and `youtube-policy.md` §2 is about template plus volume |
| `Best heard late, on headphones` | A cliché. It appears in thousands of descriptions and signals nothing |
| `-- Ding` | Nobody signs a YouTube description |

A fifth, subtler one: the draft said vocals were mixed too low **"on purpose"**.
Explaining a mix decision is defensive. A person who meant it does not justify it.

## The constraint that makes this hard

The obvious fix is specificity — "recorded in my room in August, the bass is out of
tune on the second verse and I left it". That reads unmistakably human.

**It is also a lie, and not a harmless one.** The track was generated. Inventing a
recording session contradicts the *Altered or synthetic content* disclosure ticked on
the same upload, in the same Studio session. It is a false claim about provenance
sitting next to a true one.

So the register cannot be *more vivid*. It has to be **less**. Say little, and make
the little that is said true.

## What is left

Three moves, in order of how much they buy:

1. **Lowercase.** Changes the tone instantly and costs nothing.
2. **One true specific that only the maker would know.** Not about the recording —
   about the *decisions*. A running order, a key relationship, why a track is where
   it is. "first of eight. they get slower as they go." is true (95 → 76 BPM across
   the set) and could not have been written by someone who had not sequenced it.
3. **Full lyrics, and end there.** Honest, useful when the vocal is mixed low by
   design, and it gives search real text to index without a keyword paragraph.
   Nothing goes underneath them.

Cut everything else. The bio belongs on the About tab, once.

### Worked example

```
dream pop. first of eight, and they get slower as they go.

the light turns green at midnight
no one's behind me anyway
...
```

The first draft of this kept `dream pop. 95 bpm, a minor.` as a last line, on the
theory that moving the spec sheet to the bottom defused it. It does not. The reader
objected to it there too, and they were right: the problem is the *form*, not the
position. A row of fields is a row of fields wherever it sits, and the only people
who publish their own BPM and key are beat sellers, whose grammar this is
(`Type Beat | 140 BPM | Am`). An artist releasing a song does not.

So the genre stays and the numbers go. One word, folded into a sentence that was
already there, carrying no data the maker would not say out loud.

**Nothing after the lyrics.** The last line is the last line of the song.

## Titles

Use the artist convention, `Artist - Track`:

```
No One's Behind Me - Green Light
```

Not `Track [genre] chill mix` — that is playlist-channel grammar and it undercuts
the artist positioning the rest of the page is trying to establish.

**The objection, and the answer.** On a channel with no subscribers nobody searches
the artist name, so the title carries no discovery weight. True — but music on a cold
channel gets its traffic from suggested video, which keys off watch behaviour rather
than keywords, not from search. Genre keywords belong in the tags, where they cost
nothing and are invisible. This reasoning is not measured; it is the stated tradeoff,
and worth revisiting if the first few uploads show search impressions in Studio.

## First-upload checklist

| | |
|---|---|
| Category | Music |
| Altered or synthetic content | **Yes** — required, see `youtube-policy.md` §1 |
| Made for kids | No |
| Thumbnail | **Needs a phone-verified account.** Without it YouTube picks a frame |
| Visibility | unlisted first, review the live page, then public |
| Playlist | create the set's playlist on the first upload, not the last |

The thumbnail row is the one that actually bites. If the videos carry no on-screen
text — which is the case for the nocturne set — an auto-picked frame is a dark image
with no title on it, and it goes out looking broken.
