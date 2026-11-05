---
name: acestep-publishing
description: Publish model-generated music to YouTube - required AI disclosure, monetization policy, Content ID, and writing titles and descriptions that do not read as AI-written. Use when uploading a finished track or music video, writing video metadata, or deciding about distribution to Spotify and other stores.
allowed-tools: Read, Write, Edit, Bash
---

# Publishing AI-Generated Music

Everything after the track is finished. Songwriting is `acestep-songwriting`.

## References

- **`references/youtube-policy.md`** — what YouTube actually requires, read off
  Google's own pages and labelled where it is secondary reporting. Disclosure,
  the inauthentic-content rules, Content ID, and why Spotify comes later.
- **`references/description-voice.md`** — how to write the title and description so
  they do not read as generated, and the honesty constraint that rules out the
  easy fix.

## The two rules that are not judgement calls

**1. Tick the synthetic-content disclosure on every upload.** Google's help page
lists "AI generated music" by name. Disclosing is documented to cost nothing — no
reach penalty, no monetization penalty. Not disclosing risks the channel. There is
no tradeoff to weigh here. `scripts/youtube_upload.py` hard-codes
`containsSyntheticMedia: True` so it cannot be forgotten; if you upload by hand,
set it in Studio.

**2. Never claim the music was recorded.** No studio, no room, no take that was
kept. A fabricated recording session sits in the same upload as a true synthetic
disclosure and contradicts it. `references/description-voice.md` covers what to
write instead.

## Content ID: not yet, and the order matters

Content ID is not self-serve — it needs an agreement with YouTube, and the
realistic route for an individual is a distributor. That route is the trap: the
distributor pushes the release into Content ID, which then claims the videos you
uploaded by hand on your own channel.

It protects against other people monetizing your music. On a track nobody has heard
there is nothing to protect, so the cost is immediate and the benefit hypothetical.
Upload first, decide about distribution later, and if you ever do distribute, turn
the Content ID option off or whitelist the channel. Nothing is lost by waiting.

What to keep instead, as proof of authorship: the generation script with its seeds.
`acestep-songwriting/references/playlist-mit8.sh` is exactly that.

## Uploading

```bash
python3 scripts/youtube_upload.py --list-channels

python3 scripts/youtube_upload.py \
    --video out.mp4 \
    --title "No One's Behind Me - Green Light" \
    --description-file desc.txt \
    --tags "dream pop,indie pop,bedroom pop" \
    --thumbnail thumb.jpg \
    --privacy private --dry-run
```

`--list-channels` first, always: the upload scope is write-only, so without
`youtube.readonly` you cannot see which channel the token points at before
committing a video to it.

Then `--dry-run`, then `--privacy private`, then look at the live page, and only
then public. Uploading is outward-facing and not cleanly reversible — a deleted
video does not un-publish from anyone who already saw it.

Credentials live in `<repo>/.youtube/` (gitignored). **Do not reuse the token from
`anime-short-generator`** — a daily cron depends on it and overwriting it breaks
that job.
