"""
stt.py - Speech-to-text using openai-whisper.

openai-whisper runs Whisper locally using PyTorch.
Models download from Azure CDN on first use (not HuggingFace), then cache
in ~/.cache/whisper/. On Apple Silicon the MPS (Metal) backend accelerates
inference, though CPU + FP32 is also perfectly fast for conversational use.

We use two models:
- tiny  (72MB):  Fast, cheap. Used for wake-word detection on short clips.
- small (461MB): More accurate. Used for full command transcription.

Both are loaded once at startup and kept in memory.
"""

from __future__ import annotations

import warnings
import numpy as np
import whisper


class STT:
    """
    Speech-to-text engine backed by openai-whisper.

    Loads the tiny and small models once, keeps them in memory
    to avoid the ~500ms reload overhead on every transcription.
    """

    def __init__(
        self,
        wake_model: str = "tiny",
        command_model: str = "small",
        language: str = "en",
    ) -> None:
        """
        Args:
            wake_model:    Whisper model for wake-phrase detection.
                           "tiny" is fast enough and cheap on CPU.
            command_model: Whisper model for full command transcription.
                           "small" gives good accuracy at reasonable speed.
            language:      Language code for transcription (speeds up inference).
        """
        self.language = language
        self._wake_model_name = wake_model
        self._command_model_name = command_model
        self._models: dict[str, whisper.Whisper] = {}

    def _get_model(self, name: str) -> whisper.Whisper:
        """Load and cache a whisper model by name."""
        if name not in self._models:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self._models[name] = whisper.load_model(name)
        return self._models[name]

    def preload(self) -> None:
        """Load both models into memory now (call at startup to avoid first-use lag)."""
        self._get_model(self._wake_model_name)
        self._get_model(self._command_model_name)

    def transcribe(self, audio: np.ndarray, model: str = "command") -> str:
        """
        Transcribe audio to text.

        Args:
            audio: float32 numpy array at 16000Hz mono.
            model: "wake" for tiny model, "command" for small model,
                   or a whisper model name string ("tiny", "base", "small", etc.)

        Returns:
            Transcribed text, stripped of leading/trailing whitespace.
        """
        if audio is None or len(audio) == 0:
            return ""

        if model == "wake":
            model_name = self._wake_model_name
        elif model == "command":
            model_name = self._command_model_name
        else:
            model_name = model

        m = self._get_model(model_name)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = m.transcribe(
                audio,
                language=self.language,
                fp16=False,      # CPU-safe (Metal would use fp16 automatically)
                verbose=False,
            )

        return result.get("text", "").strip()

    def contains_wake_phrase(self, text: str, phrase: str = "hey claude") -> bool:
        """
        Check if transcribed text contains the wake phrase.

        Uses fuzzy matching to handle common Whisper transcription quirks:
        - "hey cloud" instead of "hey claude"
        - "hey clod" / "hay claude" etc.
        """
        text_lower = text.lower().strip()

        if not text_lower:
            return False

        alternates = [
            "hey claude",
            "hey cloud",
            "hey clod",
            "hey claud",
            "a claude",
            "hey claw",
            "hay claude",
            "hey klod",
            "hey clawed",
        ]
        return any(alt in text_lower for alt in alternates)

    def strip_wake_phrase(self, text: str, phrase: str = "hey claude") -> str:
        """
        Remove the wake phrase from the start of a transcription.

        Example:
            "hey claude what's the weather" -> "what's the weather"
            "hey claude" -> ""
        """
        text_lower = text.lower()

        alternates = [
            "hey claude",
            "hey cloud",
            "hey clod",
            "hey claud",
            "a claude",
            "hey claw",
            "hay claude",
            "hey klod",
            "hey clawed",
        ]

        for alt in alternates:
            if text_lower.startswith(alt):
                remainder = text[len(alt):].strip()
                remainder = remainder.lstrip(",.!? ")
                return remainder

        return text
