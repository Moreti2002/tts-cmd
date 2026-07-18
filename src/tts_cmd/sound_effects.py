"""Tech-style activation sound generation.

The activation cue is a three-blip ascending arpeggio with metallic
harmonic content — designed to read as a sci-fi UI "system armed"
notification. Pre-generated once and cached as ``assets/activation.wav``.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 44_100


def _envelope(num_samples: int, attack_s: float = 0.003, release_s: float = 0.06) -> np.ndarray:
    """Fast-attack / exponential-release amplitude envelope."""
    env = np.ones(num_samples, dtype=np.float32)
    attack_n = max(1, int(attack_s * SAMPLE_RATE))
    release_n = max(1, int(release_s * SAMPLE_RATE))
    env[:attack_n] = np.linspace(0.0, 1.0, attack_n, dtype=np.float32)
    if release_n < num_samples:
        env[-release_n:] = np.exp(-np.linspace(0.0, 6.0, release_n, dtype=np.float32))
    return env


def _blip(freq: float, duration_s: float, release_s: float = 0.06) -> np.ndarray:
    """A metallic blip: stacked odd harmonics with sharp envelope."""
    n = int(duration_s * SAMPLE_RATE)
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    # Fundamental + 3rd + 5th gives a clean digital "bleep" colour.
    wave_buf = (
        1.00 * np.sin(2.0 * np.pi * freq * t)
        + 0.42 * np.sin(2.0 * np.pi * 3.0 * freq * t)
        + 0.18 * np.sin(2.0 * np.pi * 5.0 * freq * t)
    )
    wave_buf /= max(1.0, float(np.max(np.abs(wave_buf))))
    return wave_buf * _envelope(n, release_s=release_s)


def _silence(duration_s: float) -> np.ndarray:
    return np.zeros(int(duration_s * SAMPLE_RATE), dtype=np.float32)


def _click(duration_s: float = 0.006) -> np.ndarray:
    """A high-frequency burst that gives the cue a tactile 'tick' on the front."""
    n = int(duration_s * SAMPLE_RATE)
    rng = np.random.default_rng(seed=1337)
    noise = rng.standard_normal(n).astype(np.float32)
    return noise * np.linspace(1.0, 0.0, n, dtype=np.float32) * 0.6


def _finalize(parts: list[np.ndarray]) -> np.ndarray:
    signal = np.concatenate(parts)
    # Master gain — clearly audible without clipping.
    signal *= 0.85
    peak = float(np.max(np.abs(signal)))
    if peak > 0.99:
        signal *= 0.99 / peak
    return signal


def build_activation_sound() -> np.ndarray:
    """Tactile click + three-tone ascending arpeggio with overtones."""
    return _finalize([
        _click(),
        _blip(660.0, 0.07, release_s=0.05),
        _silence(0.018),
        _blip(990.0, 0.07, release_s=0.05),
        _silence(0.018),
        _blip(1480.0, 0.13, release_s=0.10),
    ])


def build_deactivation_sound() -> np.ndarray:
    """Descending mirror of the activation cue — reads as "system disarmed"."""
    return _finalize([
        _click(),
        _blip(1480.0, 0.07, release_s=0.05),
        _silence(0.018),
        _blip(990.0, 0.07, release_s=0.05),
        _silence(0.018),
        _blip(660.0, 0.13, release_s=0.10),
    ])


def write_wav(path: Path, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(samples, -1.0, 1.0)
    pcm_int = (pcm * 32_767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_int.tobytes())


def generate_activation_sound(target: Path) -> Path:
    write_wav(target, build_activation_sound())
    return target


def generate_deactivation_sound(target: Path) -> Path:
    write_wav(target, build_deactivation_sound())
    return target
