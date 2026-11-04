# Publishing AI-generated music on YouTube

Policy notes, not craft notes. Read before the first upload, not while writing a song.

**Checked 2026-11-04.** Two of the claims below were read directly off Google's own Help
Center pages on that date; the rest is secondary reporting and is labelled as such. This
area moves — the monetization policy was rewritten in July 2025 and clarified again in
July 2026. Re-verify before betting anything on it.

## 1. Disclosure is required. Yes, even for music.

`support.google.com/youtube/answer/14328491` lists **"AI generated music"** outright as
an example of content that must be disclosed with the *Altered or synthetic content*
setting in YouTube Studio.

This is the one thing most people get wrong, because the disclosure was introduced for
deepfakes and everyone assumes it only covers realistic depictions of real people. It
does not. Music with no person in it still triggers it.

Three facts worth having straight, all verbatim from that page:

- **It costs nothing to disclose.** "Disclosing AI content alone won't limit a video's
  audience or impact its eligibility to earn money."
- **Not disclosing has teeth.** "Creators who consistently choose not to disclose this
  information may be subject to manual application of a label, or penalties from YouTube,
  including removal of content or suspension from the YouTube Partner Program."
- **YouTube may label it anyway**, without asking, if the upload carries C2PA metadata or
  its own detection fires.

So the asymmetry is total: disclosing is documented to cost nothing, not disclosing risks
the whole channel. **Tick the box on every upload.** There is no judgement call here.

One documented exception, not relevant to us: cloning *your own* voice for voiceover or
dubbing needs no disclosure.

## 2. Monetization: AI as a tool is fine. Volume without a voice is not.

`support.google.com/youtube/answer/1311392`, last updated 15 July 2025. The policy
previously called "repetitious content" is now "inauthentic content". It is written to be
medium-agnostic — it never singles out music.

Not eligible:

> "AI-generated content made with generic or unoriginal templates giving the impression of
> mass production"

> "Songs modified to change the pitch or speed, but otherwise identical"

Explicitly eligible:

> "Content that expresses your unique creative voice using AI tools"

> "Content utilizing creative tools to assist in delivering unique narrative"

That second pair is the part to hold on to. The rule is not "AI content is suspect". The
rule is **template plus volume** — same shape, different seed, uploaded in bulk. Writing
the captions and lyrics by hand, choosing the key and arc per track, and listening to each
one before it ships is exactly the "unique creative voice" the policy carves out.

The practical reading: the risk is not using the model. The risk is uploading forty tracks
that are recognisably one caption with the numbers changed.

## 3. Things that are inference, not policy

Separated deliberately. Do not quote these as rules.

- **Re-using our own tracks in a later compilation.** No official text covers it. The
  reused-content wording targets material "copied from another online source" and clips
  "with little or no narrative" — neither describes a compilation of your own catalogue
  with a deliberate running order. Low risk by reading, but unconfirmed.
- **Whether AI music is enforced against more harshly than AI narration.** Every named
  enforcement story is about faceless narration and slideshow channels. Claims that music
  channels are the primary target appear only in SEO blogs with no primary source.
- **The "16 channels terminated" statistic** doing the rounds since Jan 2026. Could not be
  traced to an official YouTube statement, and could not be confirmed to involve any music
  channel. Treat as folklore.
- **Content ID false positives** against our own original audio, because another
  registered reference came out of the same model. Plausible, reported only secondhand.
  Cheap insurance: keep the generation logs and the seed. `references/playlist-mit8.sh` is
  already proof of authorship for the first eight tracks.

## 4. Not our problem, but worth recognising

Since Nov 2023 YouTube has let participating labels request removal of AI content that
"mimics an artist's unique singing or rapping voice". This does not touch original vocals
that imitate nobody. It is one more reason the no-artist-names rule in
`references/artist-styles.md` matters: it keeps us out of a category we have no business
being in. Keep artist names out of titles, tags and descriptions too, not just captions.

## Sources

| Claim | Source | Verified |
|---|---|---|
| "AI generated music" requires disclosure; no reach/monetization penalty; penalties for not disclosing | support.google.com/youtube/answer/14328491 | read directly, 2026-11-04 |
| Inauthentic-content wording, eligible and ineligible examples, page dated 15 Jul 2025 | support.google.com/youtube/answer/1311392 | read directly, 2026-11-04 |
| July 2025 rename from "repetitious" to "inauthentic" | YouTube Help + Social Media Today, Jul 2025 | secondary |
| July 2026 clarification naming three categories of inauthentic content | Creator Insider interview, via TechCrunch 20 Jul 2026 | secondary, not read directly |
| Artist-voice removal requests | blog.youtube, 14 Nov 2023 | secondary |
