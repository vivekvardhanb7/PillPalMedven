from collections import OrderedDict, deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from threading import RLock
from typing import Callable
from uuid import UUID, uuid4

from src.state import AssessmentState


@dataclass
class _SessionRecord:
    token_hash: str
    state: AssessmentState
    responses: OrderedDict[str, dict[str, object]] = field(default_factory=OrderedDict)
    request_times: deque[datetime] = field(default_factory=deque)


class SessionError(Exception):
    pass


class RevisionConflict(SessionError):
    def __init__(self, message: str, current_revision: int) -> None:
        super().__init__(message)
        self.current_revision = current_revision


class RateLimitExceeded(SessionError):
    pass


class InMemorySessionStore:
    """Process-local development store; use a shared, reviewed store in deployment."""

    def __init__(
        self,
        ttl_seconds: int = 1800,
        max_turns_per_minute: int = 30,
        max_sessions: int = 10000,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        if max_turns_per_minute < 1 or max_sessions < 1:
            raise ValueError("session and request limits must be positive")
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_turns_per_minute = max_turns_per_minute
        self._max_sessions = max_sessions
        self._sessions: dict[str, _SessionRecord] = {}
        self._lock = RLock()

    def create(self) -> tuple[str, str, int]:
        with self._lock:
            self._purge_expired()
            if len(self._sessions) >= self._max_sessions:
                raise RateLimitExceeded("The prototype session limit has been reached.")

            session_id = str(uuid4())
            access_token = secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + self._ttl
            self._sessions[session_id] = _SessionRecord(
                token_hash=self._token_hash(access_token),
                state=AssessmentState(
                    session_id=UUID(session_id),
                    expires_at=expires_at,
                ),
            )
            return session_id, access_token, int(self._ttl.total_seconds())

    def process_turn(
        self,
        session_id: str,
        access_token: str,
        request_id: str,
        expected_revision: int,
        build_response: Callable[[AssessmentState], dict[str, object]],
    ) -> dict[str, object]:
        with self._lock:
            record = self._authorized_record(session_id, access_token)
            cached = record.responses.get(request_id)
            if cached is not None:
                return deepcopy(cached)

            state = record.state
            if state.revision != expected_revision:
                raise RevisionConflict(
                    "The session revision is stale; reload the conversation.",
                    current_revision=state.revision,
                )

            self._enforce_rate_limit(record)
            next_state = state.model_copy(deep=True)
            next_state.revision += 1
            next_state.expires_at = datetime.now(timezone.utc) + self._ttl
            response = build_response(next_state)
            response["session_revision"] = next_state.revision

            record.responses[request_id] = deepcopy(response)
            record.state = next_state
            while len(record.responses) > 100:
                record.responses.popitem(last=False)

            return response

    def snapshot(self, session_id: str, access_token: str) -> AssessmentState:
        with self._lock:
            record = self._authorized_record(session_id, access_token)
            return record.state.model_copy(deep=True)

    def consume_request(self, session_id: str, access_token: str) -> None:
        with self._lock:
            record = self._authorized_record(session_id, access_token)
            self._enforce_rate_limit(record)

    def reset(self, session_id: str, access_token: str) -> None:
        with self._lock:
            self._authorized_record(session_id, access_token)
            del self._sessions[session_id]

    def _authorized_record(self, session_id: str, access_token: str) -> _SessionRecord:
        self._purge_expired()
        record = self._sessions.get(session_id)
        if record is None:
            raise SessionError("The session is invalid or has expired.")

        submitted_hash = self._token_hash(access_token)
        if not hmac.compare_digest(record.token_hash, submitted_hash):
            raise SessionError("The session is invalid or has expired.")
        return record

    def _enforce_rate_limit(self, record: _SessionRecord) -> None:
        now = datetime.now(timezone.utc)
        request_times = record.request_times
        while request_times and now - request_times[0] >= timedelta(minutes=1):
            request_times.popleft()
        if len(request_times) >= self._max_turns_per_minute:
            raise RateLimitExceeded("Too many messages; wait before trying again.")
        request_times.append(now)

    def _purge_expired(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [
            session_id
            for session_id, record in self._sessions.items()
            if record.state.expires_at <= now
        ]
        for session_id in expired:
            del self._sessions[session_id]

    @staticmethod
    def _token_hash(access_token: str) -> str:
        return hashlib.sha256(access_token.encode("utf-8")).hexdigest()
