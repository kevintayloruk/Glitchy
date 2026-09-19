#!/usr/bin/env python3
"""
Core glitch-detection engine for recorded test-tone WAV files. Importable
module used by both the CLI (detect_glitch.py) and the desktop GUI.

Flags:
  - clicks/pops       : large sample-to-sample deltas
  - flatline/stuck     : signal frozen longer than a sine can naturally sit still
  - distortion bursts  : energy outside the fundamental (residual after notch)
  - phase glitches     : instantaneous frequency deviating from the fundamental
                         (via zero-crossing period, not Hilbert transform --
                         chunk-safe, no boundary artifacts)

Processes files in bounded-size chunks (with a small overlap between chunks
to avoid missing/double-counting glitches at chunk boundaries), so memory use
stays flat regardless of file length. Uses soundfile (libsndfile) for reading,
which handles broadcast-WAV metadata chunks (bext/iXML) that scipy's WAV
reader chokes on.
"""
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import iirnotch, filtfilt

BLOCK_SECONDS = 30.0     # chunk size processed at a time (bounds memory use)
OVERLAP_SECONDS = 0.2    # overlap between chunks so boundary glitches aren't missed
AUTO_DETECT_SECONDS = 3.0  # how much audio to sample when auto-detecting frequency


def auto_detect_frequency(path, sample_seconds=AUTO_DETECT_SECONDS,
                           search_window_seconds=60.0, min_rms=1e-4):
    """
    Estimate the fundamental tone frequency in a WAV file: scans the first
    `search_window_seconds` for a `sample_seconds`-long chunk with enough
    energy to analyze (skipping lead-in silence/room tone), then finds the
    dominant FFT peak with parabolic sub-bin interpolation for sub-Hz
    accuracy. Returns None if the file is too short/quiet to tell.
    """
    with sf.SoundFile(str(path)) as f:
        sr = f.samplerate
        total_frames = f.frames
        chunk_frames = int(sr * sample_seconds)
        search_frames = min(total_frames, int(sr * search_window_seconds))

        pos = 0
        x = None
        while pos + chunk_frames <= search_frames:
            f.seek(pos)
            block = f.read(chunk_frames, dtype='float64', always_2d=False)
            if block.ndim > 1:
                block = block.mean(axis=1)
            if np.sqrt(np.mean(block ** 2)) > min_rms:
                x = block
                break
            pos += chunk_frames

        if x is None:
            # nothing loud enough found -- fall back to whatever's at the
            # very start, even if quiet, rather than giving up entirely
            f.seek(0)
            x = f.read(min(chunk_frames, total_frames), dtype='float64', always_2d=False)
            if x.ndim > 1:
                x = x.mean(axis=1)

    if len(x) < 64:
        return None

    window = np.hanning(len(x))
    spectrum = np.abs(np.fft.rfft(x * window))
    freqs = np.fft.rfftfreq(len(x), d=1.0 / sr)

    valid = freqs > 20  # ignore DC/rumble
    if not np.any(valid):
        return None
    peak_idx = int(np.argmax(spectrum * valid))

    # parabolic interpolation across the peak and its neighbors, for
    # sub-bin accuracy beyond the raw FFT resolution
    if 0 < peak_idx < len(spectrum) - 1:
        y0, y1, y2 = spectrum[peak_idx - 1], spectrum[peak_idx], spectrum[peak_idx + 1]
        denom = (y0 - 2 * y1 + y2)
        offset = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
    else:
        offset = 0.0

    bin_width = freqs[1] - freqs[0]
    return float(round(freqs[peak_idx] + offset * bin_width, 2))


def format_timestamp_for_filename(t):
    """Seconds -> a filesystem-safe timestamp fragment, e.g. 0h05m32s847"""
    hours = int(t // 3600)
    minutes = int((t % 3600) // 60)
    secs = t % 60
    return f"{hours}h{minutes:02d}m{secs:06.3f}s".replace(".", "_")


def extract_clip(src_path, out_dir, filename_stem, subtype, sr, total_frames,
                  center_t, pre_roll_s, post_issue_s, kinds_str):
    start_t = max(0.0, center_t - pre_roll_s)
    end_t = min(total_frames / sr, center_t + post_issue_s)
    start_frame = int(start_t * sr)
    n_frames = int((end_t - start_t) * sr)
    if n_frames <= 0:
        return None

    with sf.SoundFile(str(src_path)) as f:
        f.seek(start_frame)
        data = f.read(n_frames, dtype='float64', always_2d=False)

    safe_kinds = kinds_str.replace(",", "+")
    ts_tag = format_timestamp_for_filename(center_t)
    out_name = f"{filename_stem}__{ts_tag}__{safe_kinds}.wav"
    out_path = Path(out_dir) / out_name
    sf.write(str(out_path), data, sr, subtype=subtype)
    return out_path


def find_wav_files(path, recursive=False):
    p = Path(path)
    if p.is_file():
        return [p]
    pattern = "**/*.wav" if recursive else "*.wav"
    return sorted(p.glob(pattern))


def detect_flatline(x, sr, tone_hz, flat_frac=0.05, min_flat_frac_of_period=0.15):
    """
    Flags stretches where the signal stops moving for longer than a sine
    could naturally sit still (a sine is only instantaneously flat at its
    peaks). Catches dropped half-cycles / sample-and-hold freezes.
    """
    period_samples = sr / tone_hz
    roll_win = max(3, int(period_samples * 0.1))  # ~10% of a period
    min_run = int(period_samples * min_flat_frac_of_period)

    x2 = x ** 2
    kernel = np.ones(roll_win) / roll_win
    mean = np.convolve(x, kernel, mode='same')
    mean_sq = np.convolve(x2, kernel, mode='same')
    local_std = np.sqrt(np.maximum(mean_sq - mean ** 2, 0))

    overall_rms = np.sqrt(np.mean(x ** 2)) if len(x) else 0.0
    flat_thresh = flat_frac * overall_rms
    is_flat = local_std < flat_thresh

    events = []
    start = None
    for i, f in enumerate(is_flat):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if i - start >= min_run:
                events.append(start / sr)
            start = None
    if start is not None and len(is_flat) - start >= min_run:
        events.append(start / sr)
    return events


def detect_freq_deviation(x, sr, tone_hz, freq_dev_hz=15.0):
    """
    Instantaneous-frequency check via zero-crossing period measurement,
    NOT a Hilbert transform. A Hilbert transform is FFT-based and treats
    the whole array as implicitly periodic -- when run per-chunk, the
    discontinuity at each chunk's edge creates a spurious "frequency
    deviation" ringing right at every chunk boundary. Zero-crossing timing
    is purely local (like the click detector), so it has no such artifact
    and chunks cleanly.
    """
    signs = np.sign(x)
    signs[signs == 0] = 1
    rising = np.where((signs[:-1] < 0) & (signs[1:] >= 0))[0]
    if len(rising) < 2:
        return []
    # sub-sample interpolation of the exact crossing time
    x0, x1 = x[rising], x[rising + 1]
    frac = -x0 / (x1 - x0)
    cross_times = (rising + frac) / sr

    periods = np.diff(cross_times)
    freqs = 1.0 / periods
    dev_idx = np.where(np.abs(freqs - tone_hz) > freq_dev_hz)[0]
    return [cross_times[i] for i in dev_idx]


def detect_array(x, sr, tone_hz=1000.0, win_ms=2.0, click_sigma=8.0,
                  residual_sigma=6.0, freq_dev_hz=15.0, skip_start=0.0):
    """Run all detectors on an in-memory array. Returns dict of time lists,
    relative to the start of `x`. `skip_start` (seconds) ignores detections
    in that leading window (used to skip filter startup transients at the
    true start of a file, not at every chunk boundary)."""
    n = len(x)
    win = max(1, int(sr * win_ms / 1000))
    hop = max(1, win // 2)

    results = {"clicks": [], "residual": [], "freq_dev": [], "flatline": []}
    if n < win * 2:
        return results

    results["flatline"] = detect_flatline(x, sr, tone_hz)

    # --- Click/pop detection ---
    d = np.diff(x)
    thresh = np.median(np.abs(d)) + click_sigma * np.std(d)
    click_idx = np.where(np.abs(d) > thresh)[0]
    if len(click_idx):
        groups = np.split(click_idx, np.where(np.diff(click_idx) > sr * 0.001)[0] + 1)
        results["clicks"] = [g[0] / sr for g in groups]

    # --- Residual energy after notching out the fundamental ---
    Q = 30.0
    b, a = iirnotch(tone_hz, Q, sr)
    residual = filtfilt(b, a, x)
    rms_per_win, times = [], []
    for s in range(0, n - win, hop):
        e = s + win
        rms_per_win.append(np.sqrt(np.mean(residual[s:e] ** 2)))
        times.append(s / sr)
    if rms_per_win:
        rms_per_win = np.array(rms_per_win)
        noise_floor = np.median(rms_per_win)
        r_thresh = noise_floor + residual_sigma * np.std(rms_per_win)
        for t, r in zip(times, rms_per_win):
            if r > r_thresh:
                results["residual"].append(t)

    # --- Instantaneous frequency via zero-crossing periods ---
    results["freq_dev"] = detect_freq_deviation(x, sr, tone_hz, freq_dev_hz)

    if skip_start > 0:
        for k in results:
            results[k] = [t for t in results[k] if t >= skip_start]

    return results


def detect_file_streaming(path, tone_hz=1000.0, progress_bar=None, **kwargs):
    """Process a file in bounded-size, overlapping chunks so memory use stays
    flat regardless of file length. Returns (sample_rate, results_dict) with
    all timestamps absolute (seconds from file start)."""
    with sf.SoundFile(str(path)) as f:
        sr = f.samplerate
        total_frames = f.frames
        block = int(sr * BLOCK_SECONDS)
        overlap = int(sr * OVERLAP_SECONDS)
        step = block - overlap

        all_results = {"clicks": [], "residual": [], "freq_dev": [], "flatline": []}
        pos = 0
        while pos < total_frames:
            f.seek(pos)
            x = f.read(block, dtype='float64', always_2d=False)
            if x.ndim > 1:
                x = x.mean(axis=1)  # downmix to mono
            if len(x) == 0:
                break

            is_last = (pos + len(x) >= total_frames)
            skip_start = 0.05 if pos == 0 else 0.0  # true file start only
            chunk_results = detect_array(x, sr, tone_hz=tone_hz,
                                          skip_start=skip_start, **kwargs)

            # Each chunk's leading `overlap` seconds duplicate the previous
            # chunk's tail (giving filters room to settle before we trust
            # the output), so skip that region except on the very first
            # chunk. Otherwise each chunk owns all the way to its own end --
            # trimming to `step` here would leave a gap between chunks that
            # silently drops any glitch that falls in it.
            accept_start = 0.0 if pos == 0 else (overlap / sr)
            accept_end = len(x) / sr
            for kind, times in chunk_results.items():
                for t in times:
                    if accept_start <= t < accept_end:
                        all_results[kind].append(round(t + pos / sr, 4))

            advanced = len(x) - (0 if pos == 0 else overlap)
            if progress_bar is not None:
                progress_bar.update(advanced)
            pos += step

        return sr, all_results


def merge_events(results, merge_window=0.01):
    all_t = sorted(set(
        [("click", t) for t in results["clicks"]] +
        [("residual", t) for t in results["residual"]] +
        [("freq_dev", t) for t in results["freq_dev"]] +
        [("flatline", t) for t in results["flatline"]]
    ), key=lambda x: x[1])
    merged = []
    for kind, t in all_t:
        if merged and t - merged[-1][1] < merge_window:
            merged[-1][2].add(kind)
        else:
            merged.append([kind, t, {kind}])
    return merged


def format_timestamp(t):
    """Seconds -> H:MM:SS.mmm"""
    hours = int(t // 3600)
    minutes = int((t % 3600) // 60)
    secs = t % 60
    return f"{hours}:{minutes:02d}:{secs:06.3f}"


def analyze_file(path, tone_hz=None, extract_clips=False, clip_pre_roll=5.0,
                  clip_post_issue=5.0, clip_dir=None, progress_cb=None):
    """
    One-call entry point for a worker process: detects glitches in `path`
    (auto-detecting the tone frequency first if tone_hz is None), optionally
    extracts clips, and returns a plain dict (safe to pass back across a
    process boundary) rather than raising -- callers should check "error".

    progress_cb(frames_advanced): called periodically during detection;
    must be picklable if this runs in a separate process (a
    multiprocessing.Queue.put wrapper works well -- see glitchy_gui.py).
    """
    path = Path(path)
    result = {
        "file": path.name,
        "path": str(path),
        "error": None,
        "tone_hz": tone_hz,
        "glitches": [],       # list of (timestamp_seconds, kinds_str)
        "clip_paths": [],
    }
    try:
        if tone_hz is None:
            detected = auto_detect_frequency(path)
            if detected is None:
                result["error"] = "Could not auto-detect a tone frequency (file too short or silent)"
                return result
            tone_hz = detected
            result["tone_hz"] = tone_hz

        class _CbProgress:
            def update(self, n):
                if progress_cb is not None:
                    progress_cb(n)

        sr, results = detect_file_streaming(str(path), tone_hz=tone_hz,
                                             progress_bar=_CbProgress())
        merged = merge_events(results)
        result["glitches"] = [(t, ",".join(sorted(kinds))) for _, t, kinds in merged]

        if extract_clips and merged:
            out_dir = Path(clip_dir) if clip_dir else (path.parent / "glitch_clips")
            out_dir.mkdir(parents=True, exist_ok=True)
            subtype = sf.info(str(path)).subtype
            total_frames = sf.info(str(path)).frames
            for _, t, kinds in merged:
                try:
                    clip_path = extract_clip(path, out_dir, path.stem, subtype, sr,
                                              total_frames, t, clip_pre_roll,
                                              clip_post_issue, ",".join(sorted(kinds)))
                    if clip_path:
                        result["clip_paths"].append(str(clip_path))
                except Exception as e:
                    result["clip_paths"].append(f"[ERROR at {t:.3f}s: {e}]")

    except Exception as e:
        result["error"] = str(e)

    return result
