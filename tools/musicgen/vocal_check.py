"""Vocal sequence checker — alignment-based, replacing fixed windows.

Lesson (M1, 2026-07-13): three rounds of phantom bug-chasing (portamento,
register, host params) were caused by the METER — fixed measurement
windows drifting against the render. The honest instrument extracts the
SUNG pitch sequence from the audio (stable-pitch runs) and aligns it to
the written score. Delay Lama's strophe scored ~24/27 correct with one
short-neume merge once measured this way.

    uv run python tools/musicgen/vocal_check.py out/m1_dies_irae_dry.wav
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

D3 = 146.83
SR = 44100


def sung_runs(audio: np.ndarray, sr: int = SR, min_frames: int = 12,
              split_semis: float = 0.7):
    import parselmouth
    snd = parselmouth.Sound(audio, sampling_frequency=sr)
    f0 = snd.to_pitch(time_step=0.01, pitch_floor=80,
                      pitch_ceiling=350).selected_array["frequency"]
    runs, cur = [], []
    for v in f0:
        if v > 0:
            s = 12 * np.log2(v / D3)
            if cur and abs(s - np.median(cur)) > split_semis:
                if len(cur) >= min_frames:
                    runs.append(round(float(np.median(cur))))
                cur = []
            cur.append(s)
        else:
            if len(cur) >= min_frames:
                runs.append(round(float(np.median(cur))))
            cur = []
    if len(cur) >= min_frames:
        runs.append(round(float(np.median(cur))))
    return runs


def align_score(written, runs):
    """Needleman-Wunsch alignment; returns (matches, len(written))."""
    W, R = len(written), len(runs)
    gap = -1
    dp = np.zeros((W + 1, R + 1))
    dp[:, 0] = np.arange(W + 1) * gap
    dp[0, :] = np.arange(R + 1) * gap
    for i in range(1, W + 1):
        for j in range(1, R + 1):
            m = 2 if written[i - 1] == runs[j - 1] else -1
            dp[i, j] = max(dp[i-1, j-1] + m, dp[i-1, j] + gap,
                           dp[i, j-1] + gap)
    # traceback counting matches
    i, j, matches = W, R, 0
    while i > 0 and j > 0:
        m = 2 if written[i-1] == runs[j-1] else -1
        if dp[i, j] == dp[i-1, j-1] + m:
            matches += written[i-1] == runs[j-1]
            i, j = i-1, j-1
        elif dp[i, j] == dp[i-1, j] + gap:
            i -= 1
        else:
            j -= 1
    return matches, W


def check(audio, events, sr: int = SR) -> dict:
    written = [sv for sv, _ in events if sv is not None]
    wc = [written[0]] + [w for k, w in enumerate(written[1:], 1)
                         if w != written[k-1]]
    runs = sung_runs(audio, sr)
    matches, total = align_score(wc, runs)
    return {"written_collapsed": wc, "sung_runs": runs,
            "aligned_matches": matches, "score_len": total,
            "sequence_accuracy": round(matches / total, 3)}


if __name__ == "__main__":
    import soundfile as sf
    from chants import DIES_IRAE_STROPHE
    x, sr = sf.read(sys.argv[1])
    if x.ndim == 2:
        x = x.mean(axis=1)
    import json
    print(json.dumps(check(x, DIES_IRAE_STROPHE, sr), indent=1))
