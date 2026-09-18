"""
LaserForge Workshop Audio Alerts and Chime Generator.

Provides audible feedback for laser operations:
- Job Completed Chime (pleasant rising major triad: C5 -> E5 -> G5)
- Job Paused / Hold Warning (two-tone alert: A4 -> F4)
- Laser Alarm / Error Chime (descending warning: D5 -> C#5 -> C5)
- Auto-Focus / Probe Trigger Beep (crisp short high chime)

Generates clean synthesized 16-bit PCM audio waveforms without requiring
external binary audio asset dependencies. Supports PyQt6.QtMultimedia (QSoundEffect),
Linux native pulse/ALSA (paplay/aplay), and system fallback.
"""

import math
import os
import struct
import tempfile
import wave
import subprocess
import threading
from typing import Optional


class AudioChimeEngine:
    """Synthesizes and plays workshop notification chimes."""

    _cached_wavs = {}
    _lock = threading.Lock()

    @classmethod
    def _create_wav_data(cls, tones: list, sample_rate: int = 22050) -> bytes:
        """
        Synthesizes a multi-tone sequence with smooth ADSR envelope.
        tones format: [(freq_hz, duration_sec, volume_0_to_1)]
        """
        raw_samples = bytearray()
        for freq, duration, vol in tones:
            num_samples = int(sample_rate * duration)
            if num_samples <= 0:
                continue

            # ADSR parameters (in samples)
            attack = min(int(sample_rate * 0.015), num_samples // 4)
            decay = min(int(sample_rate * 0.03), num_samples // 4)
            release = min(int(sample_rate * 0.05), num_samples // 3)
            sustain_level = 0.7

            for i in range(num_samples):
                # Envelope multiplier [0.0, 1.0]
                if i < attack:
                    env = i / max(1, attack)
                elif i < attack + decay:
                    rel_d = (i - attack) / max(1, decay)
                    env = 1.0 - (1.0 - sustain_level) * rel_d
                elif i > num_samples - release:
                    rel_r = (num_samples - i) / max(1, release)
                    env = sustain_level * rel_r
                else:
                    env = sustain_level

                t = i / sample_rate
                # Harmonic blending for warmth (fundamental + soft 2nd harmonic)
                val = math.sin(2.0 * math.pi * freq * t) + 0.25 * math.sin(4.0 * math.pi * freq * t)
                sample = int(val * env * vol * 28000)
                sample = max(-32768, min(32767, sample))
                raw_samples.extend(struct.pack("<h", sample))

        # Pack into WAV container
        temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            with wave.open(temp_file.name, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(raw_samples)
            with open(temp_file.name, "rb") as f:
                data = f.read()
            return data
        finally:
            try:
                os.remove(temp_file.name)
            except Exception:
                pass

    @classmethod
    def get_wav_path(cls, chime_type: str) -> str:
        """Returns on-disk path to synthesized WAV file for given chime."""
        with cls._lock:
            if chime_type in cls._cached_wavs and os.path.exists(cls._cached_wavs[chime_type]):
                return cls._cached_wavs[chime_type]

            tmp = tempfile.NamedTemporaryFile(suffix=f"_{chime_type}.wav", delete=False)
            path = tmp.name
            tmp.close()

            if chime_type == "job_complete":
                # Upbeat rising C-Major arpeggio (C5: 523Hz, E5: 659Hz, G5: 784Hz, C6: 1046Hz)
                tones = [
                    (523.25, 0.12, 0.8),
                    (659.25, 0.12, 0.85),
                    (783.99, 0.14, 0.9),
                    (1046.50, 0.35, 1.0)
                ]
            elif chime_type == "probe_trigger":
                # Short crisp high blip (A5: 880Hz, E6: 1318Hz)
                tones = [
                    (880.0, 0.06, 0.7),
                    (1318.5, 0.12, 0.9)
                ]
            elif chime_type == "alarm":
                # Warning siren (F5 -> D5 descending)
                tones = [
                    (698.46, 0.18, 0.9),
                    (587.33, 0.28, 0.95)
                ]
            elif chime_type == "pause":
                # Soft attention two-tone
                tones = [
                    (440.0, 0.15, 0.6),
                    (349.23, 0.25, 0.6)
                ]
            else:
                tones = [(880.0, 0.15, 0.8)]

            wav_bytes = cls._create_wav_data(tones)
            with open(path, "wb") as f:
                f.write(wav_bytes)

            cls._cached_wavs[chime_type] = path
            return path

    @classmethod
    def play_chime(cls, chime_type: str = "job_complete", volume: float = 1.0):
        """Asynchronously plays the specified workshop chime."""
        if volume <= 0.0:
            return

        def _play():
            try:
                wav_path = cls.get_wav_path(chime_type)
                # Try paplay (PulseAudio / PipeWire standard on modern Linux)
                res = subprocess.run(["paplay", wav_path], capture_output=True)
                if res.returncode == 0:
                    return
            except Exception:
                pass

            try:
                # Fallback to aplay (ALSA standard)
                wav_path = cls.get_wav_path(chime_type)
                res = subprocess.run(["aplay", "-q", wav_path], capture_output=True)
                if res.returncode == 0:
                    return
            except Exception:
                pass

            # Terminal bell fallback if no audio daemon responding
            try:
                print("\a", end="", flush=True)
            except Exception:
                pass

        threading.Thread(target=_play, daemon=True).start()
