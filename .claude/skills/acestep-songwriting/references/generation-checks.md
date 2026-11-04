# Verifying a Generation Run

The API is cheerful. Three separate defects have been hit that all returned
HTTP 200 with a playable file, and none of them printed an error:

| What went wrong | How it looked | How it actually surfaced |
|---|---|---|
| DCW settings dropped by the request builder | normal audio, no haze | log never mentioned the scalers |
| CUDA OOM mid-render | a short file | duration quietly truncated |
| Asked for a model that was not loaded | normal audio, wrong character | server fell back to the primary model |

So "no error in the output" proves nothing. Check the server log directly.

## After every run

With `$LOG` as the server log for that run:

```bash
grep -c "not found in"        "$LOG"   # model fallback; expect 0
grep -o "mode=xl_turbo"       "$LOG" | wc -l   # expect one per job
grep -c "exceeds maximum"     "$LOG"   # silent parameter clamp; expect 0
grep -A3 "# Languages"        "$LOG"   # confirm the language you asked for
```

Then the audio itself:

```bash
python scripts/audio_qc.py <outdir>                     # relative outliers
python scripts/audio_qc.py --expect-duration 195 <dir>  # catches truncation
```

`audio_qc.py` reports two kinds of thing. **FAULTS** (clipping, truncation
against an expected duration) exit 1 and are always real. **STANDS OUT** is
informational: it means a track sits more than 3.5 robust sigmas from the
batch median on crest, transient density or band balance. That is not the
same as "bad" - a deliberately sparse closer will stand out too. It needs
at least 4 files to compare.

Neither check replaces listening. QC caught the track-05 snare problem at
5.1 sigma *after* a person had already noticed it by ear; it has never
caught anything first.

## Choosing the model

There is no `--model` flag on the server. The primary model comes from the
environment, and asking the client for a different one is the case that
silently falls back:

```bash
ACESTEP_CONFIG_PATH=acestep-v15-xl-turbo .venv/bin/python acestep/api_server.py \
    --host 127.0.0.1 --port 8001
```

## Shared machine

This box has other people's jobs on it. Never kill by name or pattern -
resolve the pid bound to your own port and read its cmdline before killing:

```bash
PID=$(ss -lptnH 'sport = :8001' | grep -oP 'pid=\K[0-9]+' | head -1)
tr '\0' ' ' < /proc/$PID/cmdline    # confirm it is yours
kill $PID
```

Check `nvidia-smi --query-compute-apps=pid,used_memory --format=csv` before
and after, and leave no server running when finished.

## Bash gotcha

`cd x && S=y && nohup cmd &` backgrounds the *entire* list, so `$S` is never
set in the parent. Use absolute paths, or wrap the background job: `( cmd & )`.
