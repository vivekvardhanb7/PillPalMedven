import time
import unittest
from uuid import uuid4

from pydantic import ValidationError

from src.session_store import InMemorySessionStore, RateLimitExceeded, SessionError
from src.state import AssessmentState, ClinicalFact, FactStatus


class SessionStoreTests(unittest.TestCase):
    def test_unknown_fact_is_not_a_denial(self):
        fact = ClinicalFact()

        self.assertIsNone(fact.value)
        self.assertEqual(fact.status, FactStatus.NOT_ASKED)
        self.assertNotEqual(fact.status, FactStatus.DENIED)

    def test_assessment_state_rejects_unmodeled_fields(self):
        with self.assertRaises(ValidationError):
            AssessmentState(
                session_id=uuid4(),
                expires_at="2026-11-09T12:00:00Z",
                client_supplied_decision="MEDICINE_OPTION",
            )

    def test_expired_session_cannot_be_used(self):
        store = InMemorySessionStore(ttl_seconds=1)
        session_id, token, _ = store.create()
        time.sleep(1.05)

        with self.assertRaises(SessionError):
            store.reset(session_id, token)

    def test_per_session_turn_limit(self):
        store = InMemorySessionStore(max_turns_per_minute=1)
        session_id, token, _ = store.create()
        response_builder = lambda _state: {"action": "UNSUPPORTED"}
        store.process_turn(session_id, token, str(uuid4()), 0, response_builder)

        with self.assertRaises(RateLimitExceeded):
            store.process_turn(session_id, token, str(uuid4()), 1, response_builder)

    def test_failed_turn_does_not_advance_the_session_revision(self):
        store = InMemorySessionStore()
        session_id, token, _ = store.create()

        def fail(_state):
            raise RuntimeError("response failed")

        with self.assertRaises(RuntimeError):
            store.process_turn(
                session_id,
                token,
                str(uuid4()),
                0,
                fail,
            )

        response = store.process_turn(
            session_id,
            token,
            str(uuid4()),
            0,
            lambda _state: {"action": "UNSUPPORTED"},
        )
        self.assertEqual(response["session_revision"], 1)


if __name__ == "__main__":
    unittest.main()
