# NAF MedAssist chat and voice test report

## Current implementation validation

### Root cause and routing

The original blanket fallback came from the old `/api/chat` route sending every
message through `_pending_catalog_response`; it checked recommendation/catalog
readiness before distinguishing greetings, information questions, and symptom
intake. In the current route, `_conversation_response` handles greetings first,
then separates general information from assessment and personal medicine
requests. A pending product record no longer blocks assessment questions.
In the old helper, `RECOMMENDATIONS_DISABLED` took precedence when the setting
was false; otherwise the incomplete 30-entry candidate catalog produced
`CATALOG_DATA_PENDING`. The stale service that displayed the reported refusal
had `recommendations_enabled=false`, but its response omitted `reason_codes`
and did not match the checked-out API schema, so its exact internal branch
cannot be proven from that response alone.

Observed route results in the local test configuration:

| Request | English/German | Chat/API and transcript replay | Actual result |
|---|---:|---:|---|
| Greeting | both | both | `GREETING`; welcome; no catalog fallback or emergency footer |
| General medicine information | both | both | `ASK_QUESTION` / `PINECONE_NOT_CONFIGURED`; no unsupported facts or sources are invented |
| Personal medicine request with no symptoms | both | both | `ASK_QUESTION`; asks about symptoms, not product approval |
| Potentially urgent presentation | both | both | `EMERGENCY` / `URGENT_SYMPTOMS_REPORTED`; immediate 112 guidance |
| Short answer and age correction | both | API multi-turn | Records symptom, accepts correction, advances to duration instead of repeating age |

With the actual default environment (Gemini and Pinecone configured), the same
general-information request stops at `AI_PROCESSING_CONSENT_REQUIRED` before
either provider is called. The `PINECONE_NOT_CONFIGURED` result above is from
the explicit no-provider unit-test configuration.

The transcript replay uses the same `/api/chat` endpoint; it is not an
audio-capture test. A follow-up general-information question does not consume
the pending symptom answer. Negated urgent signals do not trigger an emergency
response. No ordinary reply in the covered cases includes the emergency
footer.

### Results, providers, and remaining clinical dependencies

The full regression suite passed: **39 tests**. Coverage includes greeting and
conversation routing, English/German intake, corrections, urgent and negated
urgent presentations, 30 catalog entries, failed and indeterminate safety
checks, synthetic protocol-guidance routing, synthetic evaluator-only eligible
cases, out-of-stock handling, session isolation/reset, ingestion provenance,
and HTTP 413 for oversized requests. The default-config local smoke check
confirmed that both “I can't breathe” and “Ich bekomme keine Luft” return
emergency guidance.
The eligible/safety/stock evaluator cases use clearly identified synthetic
unit fixtures; they do not prove a real product is suitable or test the
end-to-end live recommendation path.

The actual default environment's readiness endpoint reports recommendations
enabled, 30 catalog candidates, Gemini and Pinecone configured, voice enabled,
inventory unconfigured, zero active reviewed protocols, `catalog_data_pending`,
and `clinical_paths_ready=false`. Configuration was observed without sending
any patient data. No live Gemini request, Pinecone search, inventory request,
or clinical-source request was made, so provider reachability and response
quality are **not verified**. Automated tests inject an empty `AppConfig` to
avoid network calls.

All 30 catalog entries have the same 22 missing or unverified required fields:
`active_ingredients`, `approval_date`, `catalog_status`, `clinical_status`,
`contraindications`, `exact_stock_sku_confirmed`, `formulation`,
`interaction_reference_ids`, `inventory_product_id`, `manufacturer`,
`patient_check_rules`, `precautions`, `required_check_ids`, `reviewed_by`,
`route`, `source_versions`, `strength`, `strength_unit`, `team_confirmed`,
`therapy_group`, `usage_instructions`, and `vending_eligibility_status`.
There are no active reviewed symptom protocols or approved-source records.
Consequently, a real symptom-specific decision, self-care plan, or product
recommendation must remain blocked until the clinical/product team supplies
and reviews those records. The app does not create reviewer identities or
clinical approvals.

The browser uses built-in `SpeechRecognition` and `speechSynthesis`; no
server-side Gemini voice provider is implemented. The rendered browser script
passed Node syntax validation, but no microphone capture, actual audio playback,
or live speech-provider test was performed. The Google client libraries also
warn that the configured Python 3.10.11 interpreter is no longer actively
supported; Python 3.11+ is recommended before production.

Verification commands: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`,
`git diff --check`, and Node `--check` on the rendered inline browser script.

No deployment or push was performed. The historical baseline below records
the pre-integration state and must not be read as the current result. The CSV
file remains that earlier per-scenario baseline rather than a record of this
37-test run.

## Historical baseline validation (2026-11-09)

Test date: 2026-11-09  
Base commit: `8b168ba` (the tested worktree includes uncommitted source and test changes)  
Branch: `main`  
Environment: Windows, Python 3.10.11; Flask 3.1.1; Pydantic 2.14.3; langchain-google-genai 2.1.12; Waitress 3.0.2; python-dotenv 1.1.0  
Provider configuration: Gemini selected; local Gemini and Pinecone keys were present (values were not read into this report). No live Gemini, Pinecone, or clinical-source request was made.

## Summary

Part 2's development gates are enabled on the test server (`127.0.0.1:8081`): recommendations and voice are configured on, all 30 catalog entries remain candidates, and the readiness endpoint reports `catalog_data_pending=true`. The API returns no medicine option or evidence reference until verified product records and clinical workflows exist.

Part 3's 30 scenario openers were submitted in English and German through Flask's test client (60 one-turn requests). All stayed fail-closed with `UNSUPPORTED`, `CATALOG_DATA_PENDING`, no options, and no sources. This verifies the no-invention invariant, not the requested conversational assessment. The browser completed synthetic English and German typed turns and a session reset.

The tested implementation does not meet the intended conversational or clinical behavior. C02 (general medicine information) and C20/C21 (emergency red flags) fail their expected behavior. Other clinical journeys are blocked because no reviewed protocols, exact approved stock products, or coherent multi-turn patient fixtures are present. All clinical outcomes are `CLINICALLY_UNVERIFIED`.

No actual microphone capture or speech playback was initiated. The browser exposes SpeechRecognition and speechSynthesis, but this test had no user permission to capture audio and no prerecorded synthetic audio fixtures. A mocked SpeechRecognition instance verified that revoking consent and resetting abort capture, clear the transcript, and reset consent; this mock is not an audio-quality or end-to-end voice test. The 60 voice journey rows are `NOT_TESTED`; voice hardware, German speech recognition, latency, interruption, noise, echo, and stale-audio behavior remain unverified.

## Environment and commands

- `git rev-parse --short HEAD`: `8b168ba`; branch `main`; working tree not clean.
- `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`: passed after adding Part 3 opener coverage (28 tests).
- `.\.venv\Scripts\python.exe -m compileall -q app.py src tests`: passed.
- `.\.venv\Scripts\python.exe -m pip check`: no broken requirements found.
- `git diff --check`: passed.
- Node 24.13.1 parsed the inline browser script after rendering its Jinja boolean.
- Docker build/deployment was not run.
- A new Waitress test server on port 8081 reported recommendations enabled, voice enabled, 30 candidate products, and clinical paths not ready. An older app was already serving port 8080 and was left untouched.

No credentials, personal information, or audio were copied into the report or CSV. The local `.env` remains ignored by Git.

## Coverage and observed behavior

### Implementation review

- [`app.py`](./app.py) defines the HTTP/session API. `create_app` reports recommendation readiness, while `/api/chat` calls `_pending_catalog_response`; it does not run conversational fact extraction, triage, or `evaluate_options`.
- [`src/catalog.py`](./src/catalog.py) loads the 30 Part 2 candidate records and preserves separate catalog, clinical, vending, team-confirmation, exact-SKU, and source-version fields. The loaded live records remain pending.
- [`src/recommendations.py`](./src/recommendations.py) implements eligibility gates before availability and rejects unapproved, incomplete, source-version-mismatched, and non-test synthetic products.
- [`src/llm.py`](./src/llm.py) constrains Gemini to candidate-fact extraction, not treatment decisions; the chat route does not call this adapter.
- [`src/state.py`](./src/state.py) models subject, fact status, protocol and evidence state, but those facts are not populated by the current chat route.
- [`templates/chat.html`](./templates/chat.html) implements typed chat, optional one-shot browser recognition/synthesis, transcript confirmation, consent, and reset. Recognition is configured with `continuous=false`.
- [`tests/test_prompt3_chat.py`](./tests/test_prompt3_chat.py) submits all 30 guide openers in both languages and asserts the catalog-pending no-option/no-source result. [`tests/test_recommendations.py`](./tests/test_recommendations.py) exercises the recommendation evaluator with isolated synthetic fixtures.

| Area | Executed evidence | Result |
|---|---|---|
| Part 2 catalog | `GET /api/catalog` and readiness check | 30 candidate records; all team-unconfirmed, exact-stock-SKU-unconfirmed, and clinically pending |
| Recommendation guard | Existing evaluator tests with explicitly synthetic records | Passing eligible/failed/missing checks, stock separation, synthetic gating, and source-version mismatch tests |
| English and German chat | 30 Part 3 openers in both languages through Flask test client | 60 executed; all returned `UNSUPPORTED` / `CATALOG_DATA_PENDING`, with empty options and sources |
| Browser typed chat | Synthetic English C01 and German C02 requests on port 8081 | Returned the same pending-catalog response in the selected language |
| Reset and session isolation | Unit tests and browser reset | Test suite passed; browser transcript cleared and session restarted |
| Voice consent guard | Clicked Start voice without checking consent; mocked SpeechRecognition for revocation/reset | UI requested consent; revocation/reset aborted the mock, cleared transcript, and reset consent; no real audio was captured |
| Voice capability | Browser feature detection only | SpeechRecognition and speechSynthesis APIs are present; this is not an audio test |
| Gemini/Pinecone | Configuration inspected without revealing values | No provider call; Gemini fact extraction is not wired into chat, Pinecone retrieval remains disabled |

### Findings by channel and language

- **English chat:** typed UI/API works, but returns the same catalog-pending response for all inputs; C02 general-information behavior fails. Personal suitability and clinical accuracy are unverified.
- **German chat:** locale is passed to the response, but the same single pending response is returned; C02 general-information behavior fails. The page labels and voice disclosure remain English in German mode. German clinical accuracy is unverified.
- **English voice:** not tested with audio. Browser API presence and the no-consent guard were checked only.
- **German voice:** not tested with audio. Browser API presence does not establish German recognition quality.

### Prioritized defects and blockers

1. **HIGH — urgent presentations do not receive an explicit emergency disposition.** Reproduction: submit C20 or C21 in either language. The observed response is `UNSUPPORTED` with generic pharmacist/doctor wording and a conditional 112 sentence; it does not explicitly say to seek emergency help immediately or ask someone nearby to stay/help. This is not a clinically reviewed emergency workflow. Do not use for patient care until a clinician-approved emergency pathway is implemented and tested.
2. **HIGH — the requested assessment/recommendation conversation is not implemented.** The `/api/chat` route always builds a catalog-pending response; it does not extract or preserve reported symptoms, ask protocol questions, or run the recommendation evaluator. No exact product record is approved, so a valid real medicine-option positive case cannot be run.
3. **HIGH — voice is a one-shot browser transcription interface, not a tested spoken conversation.** Recognition is non-continuous (`continuous=false`); no actual audio, noise/echo, turn-taking, interruption, or provider recovery test was run. Speech is limited to the response text and was not played in this run.
4. **MEDIUM — general medicine information is blocked with personal advice.** Reproduction: submit C02. The user receives only the pending-catalog message rather than a limited general explanation. This fails the Part 3 requirement to avoid a full personal assessment for general information.
5. **MEDIUM — German mode does not localize the interface.** Reproduction: select Deutsch and submit C02. The assistant message is German, but the input, controls, status, and voice-privacy disclosure remain English.
6. **BLOCKER — clinical verification is unavailable.** No approved protocols, product-specific dosing/instructions, exact SKUs, review provenance, or multi-turn fixtures exist. Part 2 candidate sources are research references, not approval evidence.

The voice privacy controls were tightened so revoking consent, muting, or resetting aborts recognition and cancels speech playback. The consent guard and reset were exercised in the browser without granting microphone access. This does not constitute end-to-end voice validation.

## Required positive/negative recommendation checks

The evaluator's isolated synthetic tests cover an eligible product, failed and indeterminate checks, stale source versions, stock unavailability, and alternative products in the same therapy group. These tests are software contract tests only. They do not prove any real product, dose, source passage, protocol, or patient recommendation is clinically correct. There is no clinician-approved fixture for a live positive recommendation; no actual product recommendation was issued or reviewed.

## Artifacts and limitations

- `NAF_MedAssist_Test_Results.csv` contains 120 de-identified rows (30 scenarios × 2 languages × typed/voice). Typed openers were executed once per language; voice rows are explicitly `NOT_TESTED`. It also separates the fail-closed engineering invariant from journey execution and clinical verification.
- Test inputs are the guide's starting prompts only, not coherent multi-turn patient fixtures. No patient information was used.
- The current generic response's conditional emergency wording is not treated as an emergency-pathway pass.
- No clinical correctness, product/source passage support, deployment readiness, or patient readiness is certified.
- The browser page was left on the updated local test server at `http://127.0.0.1:8081/`; the prior port 8080 service was not modified.

Tested the listed text openers in the worktree based on the recorded commit. Engineering results are shown separately from clinical verification. Real voice hardware, external provider calls, multi-turn journeys, exact-product evidence, and clinical expected outcomes remain unverified.
