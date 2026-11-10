from io import BytesIO
from pathlib import Path
import unittest
from uuid import uuid4

from app import create_app
from src.config import AppConfig
from src.session_store import InMemorySessionStore


class StubVoiceService:
    def __init__(self):
        self.transcription_calls = []
        self.synthesis_calls = []

    def transcribe(self, audio_path, language):
        self.transcription_calls.append((audio_path, language, Path(audio_path).read_bytes()))
        return "I have a headache."

    def synthesize(self, text, language):
        self.synthesis_calls.append((text, language))
        return b"RIFF-test-wave-data"


class VoiceApiTests(unittest.TestCase):
    def setUp(self):
        self.voice_service = StubVoiceService()
        self.client = create_app(
            session_store=InMemorySessionStore(),
            config=AppConfig(),
            voice_service=self.voice_service,
        ).test_client()
        response = self.client.post("/api/sessions")
        self.assertEqual(response.status_code, 201)
        self.session = response.get_json()
        self.headers = {"Authorization": f"Bearer {self.session['access_token']}"}

    def test_transcription_is_authenticated_and_audio_is_removed_after_processing(self):
        response = self.client.post(
            "/api/voice/transcribe",
            headers=self.headers,
            data={
                "session_id": self.session["session_id"],
                "language": "de",
                "audio": (BytesIO(b"local audio bytes"), "turn.webm", "audio/webm;codecs=opus"),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"transcript": "I have a headache.", "language": "de"},
        )
        audio_path, language, audio_data = self.voice_service.transcription_calls[0]
        self.assertEqual(language, "de")
        self.assertEqual(audio_data, b"local audio bytes")
        self.assertFalse(Path(audio_path).exists())

    def test_transcription_requires_session_authentication(self):
        response = self.client.post(
            "/api/voice/transcribe",
            data={
                "session_id": self.session["session_id"],
                "audio": (BytesIO(b"audio"), "turn.webm", "audio/webm"),
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"]["code"], "UNAUTHORIZED")

    def test_transcription_rejects_unsupported_audio_type(self):
        response = self.client.post(
            "/api/voice/transcribe",
            headers=self.headers,
            data={
                "session_id": self.session["session_id"],
                "audio": (BytesIO(b"audio"), "turn.txt", "text/plain"),
            },
        )

        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.get_json()["error"]["code"], "UNSUPPORTED_AUDIO")
        self.assertEqual(self.voice_service.transcription_calls, [])

    def test_transcription_rejects_oversized_audio(self):
        response = self.client.post(
            "/api/voice/transcribe",
            headers=self.headers,
            data={
                "session_id": self.session["session_id"],
                "audio": (BytesIO(b"x" * (10 * 1024 * 1024 + 1)), "turn.webm", "audio/webm"),
            },
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["error"]["code"], "AUDIO_TOO_LARGE")
        self.assertEqual(self.voice_service.transcription_calls, [])

    def test_synthesis_is_authenticated_and_returns_wav_audio(self):
        response = self.client.post(
            "/api/voice/synthesize",
            headers=self.headers,
            json={
                "session_id": self.session["session_id"],
                "language": "de",
                "text": "Guten Tag.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "audio/wav")
        self.assertEqual(response.data, b"RIFF-test-wave-data")
        self.assertEqual(self.voice_service.synthesis_calls, [("Guten Tag.", "de")])

    def test_synthesis_rejects_invalid_language(self):
        response = self.client.post(
            "/api/voice/synthesize",
            headers=self.headers,
            json={
                "session_id": self.session["session_id"],
                "language": "fr",
                "text": "Hello.",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "INVALID_LANGUAGE")
        self.assertEqual(self.voice_service.synthesis_calls, [])

    def test_voice_routes_reject_invalid_sessions(self):
        response = self.client.post(
            "/api/voice/synthesize",
            headers={"Authorization": f"Bearer {uuid4()}"},
            json={
                "session_id": self.session["session_id"],
                "language": "en",
                "text": "Hello.",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "INVALID_SESSION")

    def test_synthesis_rejects_non_string_languages(self):
        for language in ([], {}, None, True, 1):
            with self.subTest(language=language):
                response = self.client.post(
                    "/api/voice/synthesize", headers=self.headers,
                    json={"session_id": self.session["session_id"],
                          "language": language, "text": "Hello."},
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["error"]["code"], "INVALID_LANGUAGE")
        self.assertEqual(self.voice_service.synthesis_calls, [])
