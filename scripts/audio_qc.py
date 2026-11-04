#!/usr/bin/env python3
"""Quality control for a batch of generated audio.

Measures level *and* spectral balance, then flags the renders that stand out
from the rest of the batch.

Written after a track shipped with 39% of its energy in the snare body band --
more than twice the batch median -- while passing every check we had at the
time: full length, no clipping, healthy crest factor. Level metrics alone are
blind to a mix that is simply unpleasant, so this adds two things they miss:
where the energy sits, and how much of the track is transient attack.

Flags are relative to the batch median, so no reference values need to be kept
up to date. A single file can only be checked for the absolute faults.

Usage:
    python scripts/audio_qc.py samples/playlist/*.mp3
    python scripts/audio_qc.py --sensitivity 3.0 some_output_dir/

Exits non-zero if anything is flagged, so it can gate a generation run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import stft

AUDIO_SUFFIXES = {".mp3", ".wav", ".flac", ".ogg", ".m4a"}

# Bands chosen for what goes audibly wrong, not for tidy octaves: the kick and
# bass fundamentals, the snare/low-mid body that drives listening fatigue, and
# the hat/air region.
BANDS = {"low": (50, 120), "lowmid": (180, 350), "high": (6000, 12000)}

# Metrics compared against the batch. Deviation in either direction matters:
# too little low end is as wrong as too much. These never constitute a fault on
# their own -- a sparse closer is legitimately quieter than the rest -- so they
# are reported for a human to listen to rather than used to fail the batch.
RELATIVE_METRICS = ("crest_db", "flux", "low_pct", "lowmid_pct")

CLIP_PCT_LIMIT = 0.01

# Renders land within a frame or two of the requested length, so anything more
# than this is a failed generation rather than rounding.
DURATION_TOLERANCE_SEC = 1.0


def measure(path: Path) -> dict:
    """Return level and spectral-balance metrics for one audio file."""
    x, sr = sf.read(str(path), dtype="float32")
    if x.ndim > 1:
        x = x.mean(axis=1)

    peak = float(np.abs(x).max())
    rms = float(np.sqrt((x**2).mean()))

    freqs, _, spec = stft(x, fs=sr, nperseg=2048, noverlap=1536)
    mag = np.abs(spec)

    # Positive spectral flux: how much of the track is repeated attack rather
    # than sustained tone. A drum-forward mix sits high here.
    rise = np.maximum(np.diff(mag, axis=1), 0).sum(axis=0)
    power = mag**2
    total = float(power.sum())

    metrics = {
        "duration": len(x) / sr,
        "peak": peak,
        "clip_pct": 100 * float(np.mean(np.abs(x) >= 0.999)),
        "crest_db": 20 * np.log10(peak / rms) if rms > 0 else 0.0,
        "flux": float(rise.mean()) / (float(mag.mean()) * mag.shape[0]),
    }
    for name, (lo, hi) in BANDS.items():
        band = power[(freqs >= lo) & (freqs < hi)]
        metrics[f"{name}_pct"] = 100 * float(band.sum()) / total
    return metrics


def deviations(values: list[float], sensitivity: float) -> list[float]:
    """Return each value's distance from the median in robust sigmas.

    Median absolute deviation rather than mean/stdev: with a handful of tracks
    one bad render would otherwise drag the threshold out far enough to excuse
    itself.
    """
    arr = np.asarray(values, dtype=float)
    median = np.median(arr)
    mad = np.median(np.abs(arr - median)) * 1.4826
    if mad <= 0:
        return [0.0] * len(arr)
    return list(np.abs(arr - median) / mad)


def collect(paths: list[str]) -> list[Path]:
    """Expand directories into the audio files they contain."""
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files += sorted(c for c in p.rglob("*") if c.suffix.lower() in AUDIO_SUFFIXES)
        else:
            files.append(p)
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="Audio files, or directories to scan")
    ap.add_argument(
        "--expect-duration",
        type=float,
        help="Requested length in seconds. A render that falls short of it is a failed "
        "generation (an out-of-memory fallback truncates silently). Without this the "
        "duration is only reported, since a batch may legitimately mix lengths.",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Also exit non-zero when a track merely stands out from the batch",
    )
    ap.add_argument(
        "--sensitivity",
        type=float,
        default=3.5,
        help="Robust sigmas from the batch median before a metric is flagged (default: 3.5)",
    )
    args = ap.parse_args()

    files = collect(args.paths)
    if not files:
        print("No audio files found.", file=sys.stderr)
        return 2

    rows = [(f, measure(f)) for f in files]

    width = max(len(f.stem) for f, _ in rows)
    header = f"{'track':{width}s} {'dur':>8s} {'peak':>6s} {'clip%':>6s} {'crest':>6s} {'flux':>6s} {'low%':>6s} {'lowmid%':>8s} {'high%':>6s}"
    print(header)
    print("-" * len(header))
    for f, m in rows:
        print(
            f"{f.stem:{width}s} {m['duration']:7.2f}s {m['peak']:6.3f} {m['clip_pct']:6.3f} "
            f"{m['crest_db']:6.1f} {m['flux']:6.3f} {m['low_pct']:6.2f} {m['lowmid_pct']:8.2f} {m['high_pct']:6.2f}"
        )

    # Faults are defects on the file's own terms. Standouts are only unusual
    # next to the rest of the batch, which is a reason to listen, not to fail.
    faults: dict[Path, list[str]] = {f: [] for f, _ in rows}
    standouts: dict[Path, list[str]] = {f: [] for f, _ in rows}

    for f, m in rows:
        if m["clip_pct"] > CLIP_PCT_LIMIT:
            faults[f].append(f"clipping: {m['clip_pct']:.3f}% of samples at full scale")
        if args.expect_duration and m["duration"] < args.expect_duration - DURATION_TOLERANCE_SEC:
            faults[f].append(
                f"truncated: {m['duration']:.1f}s of the {args.expect_duration:.0f}s requested"
            )

    if len(rows) >= 4:
        for metric in RELATIVE_METRICS:
            values = [m[metric] for _, m in rows]
            median = float(np.median(values))
            for (f, _), value, dev in zip(rows, values, deviations(values, args.sensitivity)):
                if dev > args.sensitivity:
                    direction = "high" if value > median else "low"
                    standouts[f].append(
                        f"{metric} {direction}: {value:.2f} against batch median {median:.2f} ({dev:.1f} sigma)"
                    )
    else:
        print(f"\nOnly {len(rows)} file(s): batch comparison needs at least 4, per-file checks only.")

    def report(title: str, found: dict[Path, list[str]]) -> int:
        found = {f: v for f, v in found.items() if v}
        if not found:
            return 0
        print(f"\n{title} ({len(found)} of {len(rows)}):")
        for f, reasons in found.items():
            print(f"  {f}")
            for r in reasons:
                print(f"    - {r}")
        return len(found)

    n_faults = report("FAULTS", faults)
    n_standouts = report("STANDS OUT -- listen to these", standouts)

    if not n_faults and not n_standouts:
        print(f"\nOK -- no faults, nothing stands out across {len(rows)} file(s).")
    return 1 if n_faults or (args.strict and n_standouts) else 0


if __name__ == "__main__":
    raise SystemExit(main())
