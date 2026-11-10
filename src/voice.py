from __future__ import annotations

from io import BytesIO
from pathlib import Path
from threading import RLock
from typing import Protocol
import wave


class VoiceServiceError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class VoiceService(Protocol):
    def transcribe(self, audio_path: str, language: str) -> str: ...

    def synthesize(self, text: str, language: str) -> bytes: ...


class LocalVoiceService:
    def __init__(
        self,
        whisper_model: str,
        piper_en_model_path: str,
        piper_de_model_path: str,
    ) -> None:
        self.whisper_model_name = whisper_model
        self.piper_model_paths = {
            "en": Path(piper_en_model_path),
            "de": Path(piper_de_model_path),
        }
        self._whisper_model = None
        self._piper_voices = {}
        self._model_lock = RLock()

    def transcribe(self, audio_path: str, language: str) -> str:
        with self._model_lock:
            if self._whisper_model is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as error:
                    raise VoiceServiceError(
                        "WHISPER_UNAVAILABLE",
                        "Install faster-whisper to enable local voice transcription.",
                    ) from error
                self._whisper_model = WhisperModel(
                    self.whisper_model_name,
                    device="cpu",
                    compute_type="int8",
                )
            model = self._whisper_model

        segments, _ = model.transcribe(
            audio_path,
            language=language,
            beam_size=3,
            vad_filter=True,
        )
        transcript = " ".join(
            segment.text.strip() for segment in segments if segment.text.strip()
        ).strip()
        if not transcript:
            raise VoiceServiceError(
                "NO_SPEECH_DETECTED",
                "No speech was detected. Try speaking a little louder.",
                422,
            )
        return transcript

    def synthesize(self, text: str, language: str) -> bytes:
        model_path = self.piper_model_paths[language]
        if not model_path.is_file():
            raise VoiceServiceError(
                "PIPER_VOICE_MISSING",
                f"The local Piper voice for '{language}' is not installed.",
            )
        with self._model_lock:
            voice = self._piper_voices.get(language)
            if voice is None:
                try:
                    from piper import PiperVoice
                except ImportError as error:
                    raise VoiceServiceError(
                        "PIPER_UNAVAILABLE",
                        "Install piper-tts to enable local voice playback.",
                    ) from error
                voice = PiperVoice.load(str(model_path))
                self._piper_voices[language] = voice

        output = BytesIO()
        with wave.open(output, "wb") as wav_file:
            voice.synthesize_wav(text, wav_file)
        return output.getvalue()
