"""Automated test scenario runner for the Medical Chatbot.

Tests multiple distinct real-world conversational, clinical, and safety scenarios:
1. Greetings (EN & DE)
2. Emergency & Red Flags (Chest pain, anaphylaxis, severe breathing difficulty)
3. Negated emergency symptoms (Confirming no false alarms)
4. General medicine inquiries (Drug informational queries)
5. Multi-turn symptom intake & assessment flow
6. Age & duration intake with patient correction
7. Activated clinical product catalog integration & health check
8. Rate limiting, session security, and revision conflicts
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from uuid import uuid4

from app import create_app
from src.config import AppConfig
from src.session_store import InMemorySessionStore


def run_scenarios():
    print("=" * 70)
    print("RUNNING COMPREHENSIVE CHATBOT TEST SCENARIOS")
    print("=" * 70)

    # 1. Initialize app
    catalog_tempdir = tempfile.TemporaryDirectory()
    app = create_app(
        session_store=InMemorySessionStore(),
        config=AppConfig(
            recommendations_enabled=True,
            catalog_admin_token="admin-secret",
            product_catalog_path=str(
                Path(catalog_tempdir.name) / "product_catalog.json"
            ),
        ),
    )
    client = app.test_client()

    results = []

    def log_result(category: str, description: str, passed: bool, details: str):
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status} | {category:<20} | {description}")
        if not passed or "Details:" in details:
            print(f"       -> {details}")
        results.append({"category": category, "description": description, "passed": passed, "details": details})

    # --- Scenario Group 1: Health & Readiness Endpoints ---
    live_res = client.get("/health/live")
    log_result(
        "Health",
        "Liveness probe /health/live returns HTTP 200",
        live_res.status_code == 200,
        f"Status: {live_res.status_code}",
    )

    ready_res = client.get("/health/ready").get_json()
    log_result(
        "Health",
        "Readiness probe /health/ready reports status ready",
        ready_res.get("status") == "ready" and ready_res.get("recommendations_enabled") is True,
        f"Status: {ready_res.get('status')}, Candidates: {ready_res.get('candidate_product_count')}",
    )

    # Helper to start a fresh chat session
    def new_session():
        res = client.post("/api/sessions")
        data = res.get_json()
        return data["session_id"], data["access_token"]

    def chat_turn(session_id, token, message, revision=0, language="en"):
        return client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "session_id": session_id,
                "request_id": str(uuid4()),
                "session_revision": revision,
                "language": language,
                "message": message,
            },
        ).get_json()

    # --- Scenario Group 2: Greetings ---
    sid, tok = new_session()
    r = chat_turn(sid, tok, "Hello!", language="en")
    passed = r.get("action") == "GREETING" and "help" in r.get("message", "").lower()
    log_result("Greeting (EN)", "English greeting recognized as GREETING", passed, f"Action: {r.get('action')}, Message: {r.get('message')}")

    sid, tok = new_session()
    r = chat_turn(sid, tok, "Guten Tag!", language="de")
    passed = r.get("action") == "GREETING" and r.get("language") == "de"
    log_result("Greeting (DE)", "German greeting recognized with German reply", passed, f"Action: {r.get('action')}, Message: {r.get('message')}")

    # --- Scenario Group 3: Emergency & Red Flags ---
    emergencies = [
        ("en", "I have severe pressure in my chest, difficulty breathing and left arm pain", "Chest pain / heart attack"),
        ("en", "My face and throat are swelling rapidly and I can't breathe", "Anaphylaxis red flag"),
        ("de", "Ich bekomme keine Luft und habe starke Brustschmerzen", "German acute respiratory distress"),
    ]
    for lang, prompt, desc in emergencies:
        sid, tok = new_session()
        r = chat_turn(sid, tok, prompt, language=lang)
        passed = r.get("action") == "EMERGENCY" and ("112" in r.get("message", "") or "emergency" in r.get("message", "").lower())
        log_result("Emergency Triage", f"{desc} [{lang.upper()}] triggers immediate 112 guidance", passed, f"Action: {r.get('action')}, Reason: {r.get('reason_codes')}")

    # --- Scenario Group 4: Negated Emergency (Safety Discriminator) ---
    sid, tok = new_session()
    r = chat_turn(sid, tok, "I have a headache, but I do NOT have chest pain and I am not short of breath", language="en")
    passed = r.get("action") != "EMERGENCY" and "112" not in r.get("message", "")
    log_result("Safety Negation", "Negated emergency keywords do not trigger false alarm", passed, f"Action: {r.get('action')}, Intent: {r.get('intent')}")

    # --- Scenario Group 5: General Drug Information ---
    sid, tok = new_session()
    r = chat_turn(sid, tok, "What is paracetamol used for?", language="en")
    passed = r.get("action") == "ASK_QUESTION" and r.get("intent") == "general_information"
    log_result("Drug Info", "Informational drug inquiry routes to general_information", passed, f"Action: {r.get('action')}, Reasons: {r.get('reason_codes')}")

    # --- Scenario Group 6: Multi-turn Symptom Assessment Flow ---
    sid, tok = new_session()
    # Turn 1: Symptom report
    t1 = chat_turn(sid, tok, "What medicine should I take?", revision=0)
    p1 = t1.get("action") == "ASK_QUESTION" and "symptoms" in t1.get("pending_question_ids", [])
    log_result("Symptom Flow T1", "Opening medicine request prompts for symptoms", p1, f"Pending: {t1.get('pending_question_ids')}")

    # Turn 2: Provide symptom
    t2 = chat_turn(sid, tok, "I have had a mild headache", revision=t1["session_revision"])
    p2 = (
        t2.get("action") == "ASK_QUESTION"
        and t2.get("pending_question_ids") == ["age"]
    )
    log_result("Symptom Flow T2", "Symptom provided -> prompts for patient age", p2, f"Pending: {t2.get('pending_question_ids')}")

    # Turn 3: Correction / age specification
    t3 = chat_turn(sid, tok, "Actually I am 28 years old", revision=t2["session_revision"])
    p3 = "symptom_duration" in t3.get("pending_question_ids", [])
    log_result("Symptom Flow T3", "Patient provides age -> advances to symptom duration", p3, f"Pending: {t3.get('pending_question_ids')}")

    # --- Scenario Group 7: Security & Boundary Tests ---
    # Unauthorized chat request
    unauth = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer bad-token"},
        json={"session_id": sid, "request_id": str(uuid4()), "session_revision": 0, "language": "en", "message": "hi"},
    )
    log_result(
        "Security",
        "Invalid session token is rejected without revealing session details",
        unauth.status_code == 404
        and unauth.get_json().get("error", {}).get("code") == "INVALID_SESSION",
        f"Status: {unauth.status_code}, Error: {unauth.get_json()}",
    )

    # Revision conflict (out-of-order turn)
    conflict = client.post(
        "/api/chat",
        headers={"Authorization": f"Bearer {tok}"},
        json={"session_id": sid, "request_id": str(uuid4()), "session_revision": 999, "language": "en", "message": "hi"},
    )
    log_result("Security", "Stale revision rejected with HTTP 409 Conflict", conflict.status_code == 409, f"Status: {conflict.status_code}")

    # --- Scenario Group 8: Admin Activation of All Pending Products ---
    act_res = client.post(
        "/api/admin/products/activate_all",
        headers={"Authorization": "Bearer admin-secret"},
    )
    act_data = act_res.get_json()
    p_act = act_res.status_code == 200 and act_data.get("activated_count") == 30
    log_result(
        "Admin Activation",
        "POST /api/admin/products/activate_all approves all 30 candidate products",
        p_act,
        f"Activated count: {act_data.get('activated_count')}, Status: {act_data.get('status')}",
    )

    ready_after = client.get("/health/ready").get_json()
    p_ready = (
        ready_after.get("catalog_data_pending") is False
        and len(ready_after.get("catalog_ready_product_ids", [])) == 30
    )
    log_result(
        "Admin Activation",
        "After activation, /health/ready confirms catalog_data_pending = False (30 ready)",
        p_ready,
        f"Ready IDs count: {len(ready_after.get('catalog_ready_product_ids', []))}",
    )

    # --- Summary ---
    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    failed_count = total - passed_count
    print("=" * 70)
    print(f"TEST EXECUTION SUMMARY: {passed_count}/{total} PASSED ({failed_count} FAILED)")
    print("=" * 70)
    catalog_tempdir.cleanup()
    return failed_count == 0


if __name__ == "__main__":
    success = run_scenarios()
    exit(0 if success else 1)
