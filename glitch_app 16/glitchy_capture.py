"""
Live capture engine for Glitchy's Live Monitor mode.

Two source types feed the same detection pipeline:
  - SoundCardSource: reads from a local audio device via sounddevice/PortAudio
  - NetworkSource: reads decoded PCM from an ffmpeg subprocess pointed at an
    SDP file (ffmpeg handles the RTP/AES67 receive and decode)

Both push raw float64 mono samples into a RollingBuffer, which is drained by
LiveDetector using the exact same detect_array() chunking logic as the batch
file engine, so live and recorded analysis behave identically. The rolling
buffer also serves as the "pre-roll" for clip extraction: when a glitch
fires, LiveDetector already has the audio from before the trigger sitting in
the buffer, and it waits out the post-issue window before writing the clip.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np
import soundfile as sf

import glitchy_core as gc


class RollingBuffer:
    """Thread-safe rolling audio buffer. Keeps the last `retain_seconds` of
    audio (plus a little slack) as small chunks, and knows the absolute
    sample count ever pushed (for indexing into the detection stream)."""

    def __init__(self, sample_rate, retain_seconds):
        self.sr = sample_rate
        self.retain_samples = int(sample_rate * retain_seconds)
        self._chunks = deque()   # each item: (start_sample, np.ndarray)
        self._total_pushed = 0
        self._lock = threading.Lock()

    def push(self, samples):
        with self._lock:
            start = self._total_pushed
            self._chunks.append((start, np.asarray(samples, dtype=np.float64)))
            self._total_pushed += len(samples)
            # drop chunks older than what we need to retain
            cutoff = self._total_pushed - self.retain_samples
            while self._chunks and (self._chunks[0][0] + len(self._chunks[0][1])) < cutoff:
                self._chunks.popleft()

    @property
    def total_pushed(self):
        with self._lock:
            return self._total_pushed

    def get_range(self, start_sample, end_sample):
        """Returns the samples in [start_sample, end_sample), or as much of
        that range as is still retained (may be shorter at the start of a
        session, or if the range has already aged out)."""
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float64)
            chunks = list(self._chunks)

        out = []
        for chunk_start, arr in chunks:
            chunk_end = chunk_start + len(arr)
            lo = max(start_sample, chunk_start)
            hi = min(end_sample, chunk_end)
            if lo < hi:
                out.append(arr[lo - chunk_start: hi - chunk_start])
        if not out:
            return np.zeros(0, dtype=np.float64)
        return np.concatenate(out)


class LiveDetector:
    """
    Drives the same chunked detection used for files, but sourced from a
    RollingBuffer that's being filled live. Call `poll()` periodically (e.g.
    from a GUI timer); it processes whatever new audio has accumulated and
    invokes `on_glitch(timestamp_seconds, kinds_str)` for each one found.

    Clip extraction: when a glitch fires, this waits until `post_issue_s`
    more seconds have accumulated in the buffer, then calls
    `on_clip_saved(path)` with the written clip (pre-roll pulled from the
    buffer's history, post-issue from what accumulates after the trigger).
    """

    def __init__(self, sample_rate, tone_hz, on_glitch=None, on_clip_saved=None,
                 extract_clips=False, clip_pre_roll=5.0, clip_post_issue=5.0,
                 clip_dir=None):
        self.sr = sample_rate
        self.tone_hz = tone_hz
        self.on_glitch = on_glitch
        self.on_clip_saved = on_clip_saved
        self.extract_clips = extract_clips
        self.clip_pre_roll = clip_pre_roll
        self.clip_post_issue = clip_post_issue
        self.clip_dir = Path(clip_dir) if clip_dir else Path.cwd() / "glitch_clips"

        retain = max(clip_pre_roll, gc.BLOCK_SECONDS) + clip_post_issue + gc.BLOCK_SECONDS
        self.buffer = RollingBuffer(sample_rate, retain_seconds=retain)

        self.block = int(sample_rate * gc.BLOCK_SECONDS)
        self.overlap = int(sample_rate * gc.OVERLAP_SECONDS)
        self.step = self.block - self.overlap

        self._cursor = 0          # absolute sample position already processed up to
        self._first_block = True
        self._pending_clips = []  # glitches awaiting their post-issue window

    def push_audio(self, samples):
        self.buffer.push(samples)

    def poll(self):
        """Call periodically. Processes any newly available full block(s)
        and finalizes any clips whose post-issue window has now elapsed."""
        total = self.buffer.total_pushed

        while self._cursor + self.block <= total:
            x = self.buffer.get_range(self._cursor, self._cursor + self.block)
            if len(x) < self.block:
                break  # aged out of the buffer already, nothing more to do

            skip_start = 0.05 if self._first_block else 0.0
            results = gc.detect_array(x, self.sr, tone_hz=self.tone_hz,
                                       skip_start=skip_start)
            self._first_block = False

            accept_start = 0.0 if self._cursor == 0 else (self.overlap / self.sr)
            accept_end = self.block / self.sr
            merged = gc.merge_events(results)
            for _, t_rel, kinds in merged:
                if accept_start <= t_rel < accept_end:
                    abs_sample = self._cursor + int(t_rel * self.sr)
                    kinds_str = ",".join(sorted(kinds))
                    if self.on_glitch:
                        self.on_glitch(abs_sample / self.sr, kinds_str)
                    if self.extract_clips:
                        self._pending_clips.append((abs_sample, kinds_str))

            self._cursor += self.step

        self._finalize_ready_clips(total)

    def _finalize_ready_clips(self, total_pushed):
        still_pending = []
        for abs_sample, kinds_str in self._pending_clips:
            ready_sample = abs_sample + int(self.clip_post_issue * self.sr)
            if total_pushed >= ready_sample:
                self._write_clip(abs_sample, kinds_str)
            else:
                still_pending.append((abs_sample, kinds_str))
        self._pending_clips = still_pending

    def _write_clip(self, abs_sample, kinds_str):
        start = max(0, abs_sample - int(self.clip_pre_roll * self.sr))
        end = abs_sample + int(self.clip_post_issue * self.sr)
        data = self.buffer.get_range(start, end)
        if len(data) == 0:
            return
        self.clip_dir.mkdir(parents=True, exist_ok=True)
        center_t = abs_sample / self.sr
        ts_tag = gc.format_timestamp_for_filename(center_t)
        safe_kinds = kinds_str.replace(",", "+")
        out_path = self.clip_dir / f"live__{ts_tag}__{safe_kinds}.wav"
        sf.write(str(out_path), data, self.sr, subtype='PCM_24')
        if self.on_clip_saved:
            self.on_clip_saved(str(out_path))


class SoundCardSource:
    """Captures from a local input device via sounddevice (PortAudio)."""

    def __init__(self, device=None, sample_rate=48000, channels=1, blocksize=4800):
        import sounddevice as sd
        self._sd = sd
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self.blocksize = blocksize
        self._stream = None
        self._on_audio = None

    def start(self, on_audio):
        self._on_audio = on_audio

        def callback(indata, frames, time_info, status):
            mono = indata.mean(axis=1) if indata.ndim > 1 else indata
            self._on_audio(mono.astype(np.float64))

        self._stream = self._sd.InputStream(
            device=self.device, channels=self.channels, samplerate=self.sample_rate,
            blocksize=self.blocksize, dtype='float32', callback=callback,
        )
        self._stream.start()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    @staticmethod
    def list_devices():
        import sounddevice as sd
        devices = sd.query_devices()
        return [d for d in devices if d.get('max_input_channels', 0) > 0]


def find_ffmpeg():
    """
    Locates an ffmpeg binary reliably, without assuming PATH is usable.

    Checked in order:
    1. Bundled inside the packaged app itself (ffmpeg_bundle/ next to the
       executable) -- present when built via build_mac.sh/build_windows.bat,
       and means end users don't need ffmpeg installed at all.
    2. Whatever `ffmpeg` resolves to on PATH.
    3. Common install locations directly -- a packaged macOS .app launched
       by double-clicking (or via Finder's right-click-Open bypass for an
       unsigned app) does NOT inherit the user's shell PATH, so a
       Homebrew-installed ffmpeg that works fine in Terminal can still be
       "not found" here even though it's genuinely installed.
    """
    if getattr(sys, "frozen", False):
        bundle_dir = os.path.dirname(sys.executable)
        for name in ("ffmpeg", "ffmpeg.exe"):
            bundled = os.path.join(bundle_dir, "ffmpeg_bundle", name)
            if os.path.isfile(bundled):
                return bundled

    found = shutil.which("ffmpeg")
    if found:
        return found

    candidates = [
        "/opt/homebrew/bin/ffmpeg",   # Homebrew on Apple Silicon
        "/usr/local/bin/ffmpeg",      # Homebrew on Intel Mac
        "/usr/bin/ffmpeg",            # system package managers (Linux)
        "/opt/local/bin/ffmpeg",      # MacPorts
        r"C:\ffmpeg\bin\ffmpeg.exe",  # common manual Windows install
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


class NetworkSource:
    """
    Reads a network audio stream via an SDP file, using ffmpeg as the
    RTP/AES67 receiver and decoder. ffmpeg is given `-i stream.sdp` and
    told to output raw signed 16-bit PCM on stdout, which is read in a
    background thread and pushed to the same on_audio callback interface
    as SoundCardSource.
    """

    def __init__(self, sdp_path, sample_rate=48000, channels=1, read_chunk_frames=4800):
        self.sdp_path = str(sdp_path)
        self.sample_rate = sample_rate
        self.channels = channels
        self.read_chunk_frames = read_chunk_frames
        self._proc = None
        self._reader_thread = None
        self._stop_flag = threading.Event()

    def start(self, on_audio):
        self._stop_flag.clear()
        ffmpeg_path = find_ffmpeg()
        if ffmpeg_path is None:
            raise RuntimeError(
                "Could not find ffmpeg. It needs to be installed for Network "
                "Stream mode to work -- on a Mac, open Terminal and run: "
                "brew install ffmpeg"
            )
        cmd = [
            ffmpeg_path, "-loglevel", "error",
            "-protocol_whitelist", "file,udp,rtp",
            "-i", self.sdp_path,
            "-f", "s16le", "-acodec", "pcm_s16le",
            "-ar", str(self.sample_rate), "-ac", str(self.channels),
            "-",
        ]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        bytes_per_frame = 2 * self.channels  # s16le
        read_bytes = self.read_chunk_frames * bytes_per_frame

        def reader():
            while not self._stop_flag.is_set():
                chunk = self._proc.stdout.read(read_bytes)
                if not chunk:
                    break
                arr = np.frombuffer(chunk, dtype='<i2').astype(np.float64) / 32768.0
                if self.channels > 1:
                    arr = arr.reshape(-1, self.channels).mean(axis=1)
                on_audio(arr)

        self._reader_thread = threading.Thread(target=reader, daemon=True)
        self._reader_thread.start()

    def stop(self):
        self._stop_flag.set()
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=2)
            self._reader_thread = None


def parse_sdp_summary(sdp_text):
    """Pulls out the handful of fields worth showing the user as a sanity
    check after loading/pasting an SDP file: multicast address, port,
    codec/rate/channels from the rtpmap line. Returns a dict, or None if it
    doesn't look like a parseable audio SDP."""
    address, port, rtpmap = None, None, None
    for line in sdp_text.splitlines():
        line = line.strip()
        if line.startswith("c=") and "IN IP4" in line:
            parts = line.split()
            if len(parts) >= 3:
                address = parts[2].split("/")[0]
        elif line.startswith("m=audio"):
            parts = line.split()
            if len(parts) >= 2:
                port = parts[1]
        elif line.startswith("a=rtpmap"):
            rtpmap = line.split(":", 1)[1].strip() if ":" in line else line

    if address is None or port is None:
        return None
    return {"address": address, "port": port, "rtpmap": rtpmap}
