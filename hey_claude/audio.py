"""
audio.py - Microphone capture with Voice Activity Detection (VAD).

Two-stage approach:
1. Monitor audio energy (cheap RMS check) to spot when someone starts speaking.
2. Use webrtcvad (Google's VAD, runs on CPU, very lightweight) to detect silence
   and know when to stop recording.

webrtcvad works on 10ms, 20ms, or 30ms frames at 8000, 16000, or 32000 Hz.
We use 30ms frames at 16000Hz (Whisper's required sample rate).
"""

import collections
import time
from typing import Optional

import numpy as np
import sounddevice as sd
import webrtcvad


# Frame duration that webrtcvad accepts (10, 20, or 30 ms)
FRAME_MS = 30


class AudioCapture:
    """
    Listens on the default microphone and returns numpy arrays of speech audio.

    Usage:
        capture = AudioCapture(sample_rate=16000)
        audio = capture.capture_until_silence()  # blocks until utterance complete
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        vad_aggressiveness: int = 2,
        silence_duration: float = 1.5,
        max_duration: float = 30.0,
        energy_threshold: float = 0.01,
        device: Optional[int] = None,
    ) -> None:
        """
        Args:
            sample_rate:        Hz. Must be 16000 for Whisper + webrtcvad compat.
            vad_aggressiveness: 0-3. Higher = more aggressive filtering of non-speech.
                                2 is a good balance for indoor mic use.
            silence_duration:   Seconds of silence before we stop recording.
            max_duration:       Hard cap on recording length in seconds.
            energy_threshold:   RMS level above which we consider audio "active".
                                Prevents VAD from running on total silence.
            device:             sounddevice device index. None = system default.
        """
        self.sample_rate = sample_rate
        self.silence_duration = silence_duration
        self.max_duration = max_duration
        self.energy_threshold = energy_threshold
        self.device = device

        self._vad = webrtcvad.Vad(vad_aggressiveness)
        self._frame_samples = int(sample_rate * FRAME_MS / 1000)

    def _is_speech_frame(self, frame: np.ndarray) -> bool:
        """Run webrtcvad on a single 30ms frame. Returns True if speech detected."""
        # webrtcvad requires 16-bit PCM bytes
        pcm = (frame * 32767).astype(np.int16).tobytes()
        try:
            return self._vad.is_speech(pcm, self.sample_rate)
        except Exception:
            return False

    def capture_until_silence(self) -> Optional[np.ndarray]:
        """
        Record from the microphone until a pause in speech is detected.

        Blocks until:
        - `silence_duration` seconds of continuous silence after speech, OR
        - `max_duration` seconds total

        Returns:
            numpy float32 array at self.sample_rate, or None if nothing captured.
        """
        frames_collected: list[np.ndarray] = []
        speech_started = False
        silence_frames = 0
        silence_frames_threshold = int(self.silence_duration * 1000 / FRAME_MS)
        start_time = time.monotonic()

        # Ring buffer of recent frames for pre-roll (capture speech onset)
        # We keep 300ms of audio before the VAD triggers, so we don't clip the start.
        pre_roll_frames = collections.deque(maxlen=10)  # 10 * 30ms = 300ms

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self._frame_samples,
            device=self.device,
        ) as stream:
            while True:
                elapsed = time.monotonic() - start_time
                if elapsed > self.max_duration:
                    break

                frame, _ = stream.read(self._frame_samples)
                frame = frame.flatten()

                # Quick energy check - skip VAD on silence
                rms = float(np.sqrt(np.mean(frame**2)))
                if rms < self.energy_threshold:
                    if speech_started:
                        silence_frames += 1
                        frames_collected.append(frame)
                        if silence_frames >= silence_frames_threshold:
                            break
                    else:
                        pre_roll_frames.append(frame)
                    continue

                # Energy above threshold - run VAD
                is_speech = self._is_speech_frame(frame)

                if is_speech:
                    if not speech_started:
                        # Speech just started - include pre-roll
                        speech_started = True
                        frames_collected.extend(pre_roll_frames)
                    silence_frames = 0
                    frames_collected.append(frame)
                else:
                    if speech_started:
                        silence_frames += 1
                        frames_collected.append(frame)
                        if silence_frames >= silence_frames_threshold:
                            break
                    else:
                        pre_roll_frames.append(frame)

        if not frames_collected or not speech_started:
            return None

        return np.concatenate(frames_collected, axis=0)

    def wait_for_activity(self, timeout: float = 30.0) -> bool:
        """
        Block until audio energy is detected above threshold, or timeout expires.

        Returns True if activity detected, False if timed out.
        Used in session mode to check if the user is speaking before committing
        to a full capture_until_silence() call.
        """
        start = time.monotonic()
        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self._frame_samples,
            device=self.device,
        ) as stream:
            while time.monotonic() - start < timeout:
                frame, _ = stream.read(self._frame_samples)
                rms = float(np.sqrt(np.mean(frame.flatten() ** 2)))
                if rms > self.energy_threshold:
                    return True
        return False
