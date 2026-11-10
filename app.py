import hmac
from io import BytesIO
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, send_file

from src.catalog import (
    ClinicalStatus,
    ProductRecord,
    SOURCE_URLS,
    VendingStatus,
    load_product_catalog,
    persist_product_catalog,
)
from src.book_medicines import catalog_medicine_search_terms, match_book_mentions
from src.config import AppConfig
from src.inventory import InventoryClient, InventoryUnavailable, SupabaseInventoryClient
from src.llm import FactExtraction, GeminiLanguageAdapter
from src.protocols import ReviewedProtocol, load_reviewed_protocols
from src.recommendations import (
    CheckOutcome,
    MedicineCheck,
    catalog_record_missing_fields,
    catalog_record_ready,
    evaluate_options,
    evaluate_patient_checks,
)
from src.retrieval import ApprovedPineconeRetriever, create_pinecone_retriever
from src.session_store import (
    InMemorySessionStore,
    RateLimitExceeded,
    RevisionConflict,
    SessionError,
)
from src.state import AssessmentState, ClinicalFact, FactStatus
from src.voice import LocalVoiceService, VoiceService, VoiceServiceError


LANGUAGES = {"en", "de"}
MAX_MESSAGE_LENGTH = 4000
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_AUDIO_BYTES + 64 * 1024
AUDIO_EXTENSIONS = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".mp4",
    "audio/mpeg": ".mp3",
}
FACT_IDS = {
    "subject_relationship",
    "age",
    "symptoms",
    "symptom_duration",
    "onset",
    "severity",
    "associated_symptoms",
    "allergies",
    "current_medications",
    "conditions",
    "pregnancy",
    "request_medicine",
}
PERSONAL_CUES = (
    "what medicine should i take",
    "what can i take",
    "what should i take",
    "which medicine",
    "which medication",
    "which tablet",
    "which pill",
    "which cream",
    "can i take",
    "welches medikament",
    "welche tablett",
    "welche tablette",
    "welche arznei",
    "was kann ich nehmen",
    "was soll ich nehmen",
    "gib mir ein medikament",
)


class ExternalServiceError(RuntimeError):
    def __init__(self, service: str, reason_code: str) -> None:
        super().__init__(f"{service} is unavailable.")
        self.service = service
        self.reason_code = reason_code


def create_app(
    session_store: InMemorySessionStore | None = None,
    config: AppConfig | None = None,
    candidate_catalog: list[ProductRecord] | None = None,
    *,
    llm_adapter: GeminiLanguageAdapter | None = None,
    retriever: ApprovedPineconeRetriever | None = None,
    inventory_client: InventoryClient | None = None,
    voice_service: VoiceService | None = None,
) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    settings = config or AppConfig.from_environment()
    store = session_store or InMemorySessionStore(
        ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", "1800"))
    )
    catalog = (
        candidate_catalog
        if candidate_catalog is not None
        else load_product_catalog(settings.product_catalog_path)
    )
    protocols = load_reviewed_protocols(settings.protocol_catalog_path)
    api_key = settings.gemini_api_key
    if llm_adapter is None and api_key:
        try:
            llm_adapter = GeminiLanguageAdapter(settings.gemini_model, api_key)
        except Exception as error:  # pragma: no cover - environment-specific dependency failure
            app.logger.warning(
                "Gemini adapter unavailable; continuing without cloud LLM support: %s",
                error,
            )
            llm_adapter = None
    source_retriever = retriever
    if source_retriever is None:
        source_retriever = create_pinecone_retriever(
            api_key=settings.pinecone_api_key or "",
            index_name=settings.pinecone_index_name or "",
            mode=settings.pinecone_retrieval_mode,
            source=settings.pinecone_book_source,
        )
    stock_client = inventory_client or (
        InventoryClient(settings.inventory_api_url, settings.inventory_api_token)
        if settings.inventory_api_url
        else SupabaseInventoryClient(settings.supabase_url, settings.supabase_service_role_key)
    )
    local_voice_service = voice_service or LocalVoiceService(
        settings.whisper_model,
        settings.piper_en_model_path,
        settings.piper_de_model_path,
    )
    catalog_lock = RLock()
    app.extensions["medassist_config"] = settings
    app.extensions["candidate_catalog"] = catalog
    app.extensions["reviewed_protocols"] = protocols
    app.extensions["llm_adapter"] = llm_adapter
    app.extensions["source_retriever"] = source_retriever
    app.extensions["inventory_client"] = stock_client
    app.extensions["voice_service"] = local_voice_service

    @app.get("/")
    def index():
        return render_template(
            "chat.html",
            voice_enabled=settings.voice_enabled,
            recommendations_enabled=settings.recommendations_enabled,
        )

    @app.get("/health/live")
    def health_live():
        return jsonify({"status": "live"})

    @app.get("/health/ready")
    def health_ready():
        return jsonify(
            {
                "status": "ready",
                "mode": settings.app_environment,
                "recommendations_enabled": settings.recommendations_enabled,
                "book_medicine_matching_enabled": settings.book_medicine_matching_enabled,
                "candidate_product_count": len(catalog),
                "planned_product_count": settings.planned_product_count,
                "catalog_ready_product_ids": [
                    product.product_id
                    for product in catalog
                    if catalog_record_ready(product)
                ],
                "catalog_data_pending": not any(
                    catalog_record_ready(product) for product in catalog
                ),
                "catalog_missing_fields": {
                    product.product_id: catalog_record_missing_fields(product)
                    for product in catalog
                    if not catalog_record_ready(product)
                },
                "active_protocol_count": len(protocols),
                "gemini_configured": llm_adapter is not None,
                "pinecone_configured": source_retriever.configured,
                "approved_source_retrieval": source_retriever.configured and settings.pinecone_retrieval_mode == "approved_sources",
                "pinecone_retrieval_mode": settings.pinecone_retrieval_mode,
                "medical_book_retrieval": source_retriever.configured and settings.pinecone_retrieval_mode == "medical_book",
                "inventory_configured": stock_client.configured,
                "voice_enabled": settings.voice_enabled,
                "voice_transcription": "local_whisper",
                "voice_synthesis": "local_piper",
                "piper_voice_files": {
                    "en": Path(settings.piper_en_model_path).is_file(),
                    "de": Path(settings.piper_de_model_path).is_file(),
                },
                "whisper_model": settings.whisper_model,
                "llm_provider": settings.llm_provider,
                "clinical_paths_ready": bool(protocols),
                "pharmaceutical_checks_wired_to_chat": True,
                "retrieval_enabled": source_retriever.configured,
                "clinical_readiness": "depends_on_reviewed_protocols_and_catalog",
            }
        )

    @app.get("/api/catalog")
    def product_catalog():
        return jsonify(
            {
                "catalog_status": "candidate_reference_only",
                "products": [
                    {
                        "product_id": product.product_id,
                        "name": product.name,
                        "category": product.category,
                        "broad_scope": product.broad_scope,
                        "evidence_level": product.evidence_level,
                        "source_ids": product.source_ids,
                        "source_versions": product.source_versions,
                        "source_urls": [
                            SOURCE_URLS[source_id]
                            for source_id in product.source_ids
                            if source_id in SOURCE_URLS
                        ],
                        "catalog_status": product.catalog_status,
                        "team_confirmed": product.team_confirmed,
                        "exact_stock_sku_confirmed": product.exact_stock_sku_confirmed,
                        "manufacturer": product.manufacturer,
                        "active_ingredients": product.active_ingredients,
                        "strength": product.strength,
                        "strength_unit": product.strength_unit,
                        "formulation": product.formulation,
                        "route": product.route,
                        "contraindications": product.contraindications,
                        "precautions": product.precautions,
                        "interaction_reference_ids": product.interaction_reference_ids,
                        "usage_instructions": product.usage_instructions,
                        "maximum_duration": product.maximum_duration,
                        "inventory_product_id": product.inventory_product_id,
                        "clinical_status": product.clinical_status.value,
                        "vending_eligibility_status": (
                            product.vending_eligibility_status.value
                        ),
                        "reviewed_by": product.reviewed_by,
                        "approval_date": (
                            product.approval_date.isoformat()
                            if product.approval_date
                            else None
                        ),
                        "missing_required_fields": catalog_record_missing_fields(product),
                    }
                    for product in catalog
                ],
            }
        )

    @app.post("/api/admin/products/<product_id>/withdraw")
    def withdraw_product(product_id: str):
        if not settings.catalog_admin_token:
            return _error(
                "CATALOG_ADMIN_NOT_CONFIGURED",
                "Product withdrawal is unavailable until an admin token is configured.",
                503,
            )
        admin_token = _bearer_token()
        if admin_token is None or not hmac.compare_digest(
            settings.catalog_admin_token.encode("utf-8"), admin_token.encode("utf-8")
        ):
            return _error("UNAUTHORIZED", "A catalog admin token is required.", 401)

        with catalog_lock:
            if not any(product.product_id == product_id for product in catalog):
                return _error("PRODUCT_NOT_FOUND", "The product ID was not found.", 404)
            updated_catalog = [
                product.model_copy(
                    update={
                        "catalog_status": "withdrawn",
                        "clinical_status": ClinicalStatus.WITHDRAWN,
                        "vending_eligibility_status": VendingStatus.INELIGIBLE,
                    }
                )
                if product.product_id == product_id
                else product
                for product in catalog
            ]
            try:
                persist_product_catalog(updated_catalog, settings.product_catalog_path)
            except RuntimeError as error:
                return _error("CATALOG_PERSISTENCE_FAILED", str(error), 503)
            catalog[:] = updated_catalog

        return jsonify(
            {
                "status": "withdrawn",
                "product_id": product_id,
                "recommendations_enabled": settings.recommendations_enabled,
            }
        )

    @app.post("/api/admin/products/<product_id>/activate")
    def activate_product_route(product_id: str):
        if not settings.catalog_admin_token:
            return _error(
                "CATALOG_ADMIN_NOT_CONFIGURED",
                "Product activation is unavailable until an admin token is configured.",
                503,
            )
        admin_token = _bearer_token()
        if admin_token is None or not hmac.compare_digest(
            settings.catalog_admin_token.encode("utf-8"), admin_token.encode("utf-8")
        ):
            return _error("UNAUTHORIZED", "A catalog admin token is required.", 401)

        if not any(product.product_id == product_id for product in catalog):
            return _error("PRODUCT_NOT_FOUND", "The product ID was not found.", 404)
        return _error(
            "CLINICAL_REVIEW_REQUIRED",
            "Activation is disabled until a responsible reviewer verifies the product evidence and approval record.",
            409,
        )

    @app.post("/api/admin/products/activate_all")
    def activate_all_pending_route():
        if not settings.catalog_admin_token:
            return _error(
                "CATALOG_ADMIN_NOT_CONFIGURED",
                "Product activation is unavailable until an admin token is configured.",
                503,
            )
        admin_token = _bearer_token()
        if admin_token is None or not hmac.compare_digest(
            settings.catalog_admin_token.encode("utf-8"), admin_token.encode("utf-8")
        ):
            return _error("UNAUTHORIZED", "A catalog admin token is required.", 401)

        return _error(
            "CLINICAL_REVIEW_REQUIRED",
            "Bulk activation is disabled until each product has a verified clinical review and approval record.",
            409,
        )

    @app.post("/api/sessions")
    def create_session():
        try:
            session_id, access_token, expires_in = store.create()
        except RateLimitExceeded as error:
            return _error("SESSION_LIMIT", str(error), 503)
        return jsonify(
            {
                "session_id": session_id,
                "access_token": access_token,
                "expires_in_seconds": expires_in,
                "session_revision": 0,
            }
        ), 201

    @app.post("/api/chat")
    def chat():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("INVALID_JSON", "Send a JSON request body.", 400)
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            return _error("INVALID_MESSAGE", "message must be a non-empty string.", 400)
        if len(message) > MAX_MESSAGE_LENGTH:
            return _error(
                "MESSAGE_TOO_LONG",
                f"message must be at most {MAX_MESSAGE_LENGTH} characters.",
                413,
            )
        session_id = _validated_uuid(payload.get("session_id"), "session_id")
        if not isinstance(session_id, str):
            return session_id
        request_id = _validated_uuid(payload.get("request_id"), "request_id")
        if not isinstance(request_id, str):
            return request_id
        revision = payload.get("session_revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            return _error(
                "INVALID_REVISION",
                "session_revision must be a non-negative integer.",
                400,
            )
        language = payload.get("language", "en")
        if not isinstance(language, str) or language not in LANGUAGES:
            return _error("INVALID_LANGUAGE", "language must be 'en' or 'de'.", 400)
        access_token = _bearer_token()
        if access_token is None:
            return _error("UNAUTHORIZED", "A session access token is required.", 401)

        response_id = str(uuid4())

        def build_response(state: AssessmentState) -> dict[str, object]:
            state.language = language
            state.response_id = UUID(response_id)
            return _conversation_response(
                message=message,
                language=language,
                settings=settings,
                catalog=catalog,
                protocols=protocols,
                state=state,
                response_id=response_id,
                llm_adapter=llm_adapter,
                retriever=source_retriever,
                inventory=stock_client,
                ai_processing_consent=True,
            )

        try:
            response = store.process_turn(
                session_id=session_id,
                access_token=access_token,
                request_id=request_id,
                expected_revision=revision,
                build_response=build_response,
            )
        except RevisionConflict as error:
            return jsonify(
                {
                    "error": {
                        "code": "REVISION_CONFLICT",
                        "message": str(error),
                        "current_revision": error.current_revision,
                    }
                }
            ), 409
        except RateLimitExceeded as error:
            return _error("RATE_LIMITED", str(error), 429)
        except SessionError as error:
            return _error("INVALID_SESSION", str(error), 404)
        except ExternalServiceError as error:
            cause_type = (
                type(error.__cause__).__name__
                if error.__cause__ is not None
                else "unknown"
            )
            app.logger.error(
                "%s request failed (%s; cause: %s).",
                error.service,
                error.reason_code,
                cause_type,
            )
            return _error(error.reason_code, str(error), 503)
        return jsonify(response)

    @app.post("/api/voice/transcribe")
    def transcribe_voice():
        if not settings.voice_enabled:
            return _error("VOICE_DISABLED", "Voice is disabled.", 404)
        session_id = _validated_uuid(request.form.get("session_id"), "session_id")
        if not isinstance(session_id, str):
            return session_id
        access_token = _bearer_token()
        if access_token is None:
            return _error("UNAUTHORIZED", "A session access token is required.", 401)
        try:
            store.consume_request(session_id, access_token)
        except RateLimitExceeded as error:
            return _error("RATE_LIMITED", str(error), 429)
        except SessionError as error:
            return _error("INVALID_SESSION", str(error), 404)

        audio = request.files.get("audio")
        if audio is None or not audio.filename:
            return _error("INVALID_AUDIO", "Attach an audio recording.", 400)
        content_type = (audio.content_type or "").split(";", 1)[0].strip().lower()
        suffix = AUDIO_EXTENSIONS.get(content_type)
        if suffix is None:
            return _error(
                "UNSUPPORTED_AUDIO",
                "Use a WebM, Ogg, WAV, MP4, or MP3 audio recording.",
                415,
            )
        language = request.form.get("language", "en")
        if not isinstance(language, str) or language not in LANGUAGES:
            return _error("INVALID_LANGUAGE", "language must be 'en' or 'de'.", 400)
        audio_data = audio.read(MAX_AUDIO_BYTES + 1)
        if not audio_data:
            return _error("INVALID_AUDIO", "The audio recording is empty.", 400)
        if len(audio_data) > MAX_AUDIO_BYTES:
            return _error("AUDIO_TOO_LARGE", "Audio must be 10 MB or smaller.", 413)

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_path = temp_file.name
            transcript = local_voice_service.transcribe(temp_path, language)
        except VoiceServiceError as error:
            return _error(error.code, str(error), error.status_code)
        except Exception:
            app.logger.exception("Local voice transcription failed.")
            return _error(
                "VOICE_TRANSCRIPTION_FAILED",
                "Local voice transcription failed. Please try again.",
                503,
            )
        finally:
            if temp_path is not None:
                Path(temp_path).unlink(missing_ok=True)
        if not isinstance(transcript, str) or not transcript.strip():
            return _error(
                "NO_SPEECH_DETECTED",
                "No speech was detected. Try speaking a little louder.",
                422,
            )
        if len(transcript) > MAX_MESSAGE_LENGTH:
            return _error(
                "TRANSCRIPT_TOO_LONG",
                f"The transcript exceeds the {MAX_MESSAGE_LENGTH}-character message limit.",
                413,
            )
        return jsonify({"transcript": transcript, "language": language})

    @app.post("/api/voice/synthesize")
    def synthesize_voice():
        if not settings.voice_enabled:
            return _error("VOICE_DISABLED", "Voice is disabled.", 404)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("INVALID_JSON", "Send a JSON request body.", 400)
        session_id = _validated_uuid(payload.get("session_id"), "session_id")
        if not isinstance(session_id, str):
            return session_id
        access_token = _bearer_token()
        if access_token is None:
            return _error("UNAUTHORIZED", "A session access token is required.", 401)
        try:
            store.consume_request(session_id, access_token)
        except RateLimitExceeded as error:
            return _error("RATE_LIMITED", str(error), 429)
        except SessionError as error:
            return _error("INVALID_SESSION", str(error), 404)
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            return _error("INVALID_MESSAGE", "text must be a non-empty string.", 400)
        if len(text) > MAX_MESSAGE_LENGTH:
            return _error(
                "MESSAGE_TOO_LONG",
                f"text must be at most {MAX_MESSAGE_LENGTH} characters.",
                413,
            )
        language = payload.get("language", "en")
        if not isinstance(language, str) or language not in LANGUAGES:
            return _error("INVALID_LANGUAGE", "language must be 'en' or 'de'.", 400)
        try:
            audio_data = local_voice_service.synthesize(text, language)
            if not audio_data:
                return _error(
                    "VOICE_SYNTHESIS_FAILED",
                    "Local voice playback produced no audio.",
                    503,
                )
        except VoiceServiceError as error:
            return _error(error.code, str(error), error.status_code)
        except Exception:
            app.logger.exception("Local voice synthesis failed.")
            return _error(
                "VOICE_SYNTHESIS_FAILED",
                "Local voice playback could not be generated. Please try again.",
                503,
            )
        return send_file(
            BytesIO(audio_data),
            mimetype="audio/wav",
            download_name="response.wav",
            max_age=0,
        )

    @app.post("/api/session/reset")
    def reset_session():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("INVALID_JSON", "Send a JSON request body.", 400)
        session_id = _validated_uuid(payload.get("session_id"), "session_id")
        if not isinstance(session_id, str):
            return session_id
        access_token = _bearer_token()
        if access_token is None:
            return _error("UNAUTHORIZED", "A session access token is required.", 401)
        try:
            store.reset(session_id, access_token)
        except SessionError as error:
            return _error("INVALID_SESSION", str(error), 404)
        return jsonify({"status": "reset"})

    @app.errorhandler(413)
    def request_too_large(_exception):
        return _error("REQUEST_TOO_LARGE", "The request body exceeds 10 MB.", 413)

    @app.after_request
    def prevent_sensitive_response_caching(response):
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    return app


def _conversation_response(
    *,
    message: str,
    language: str,
    settings: AppConfig,
    catalog: list[ProductRecord],
    protocols: list[ReviewedProtocol],
    state: AssessmentState,
    response_id: str,
    llm_adapter: GeminiLanguageAdapter | None,
    retriever: ApprovedPineconeRetriever,
    inventory: InventoryClient,
    ai_processing_consent: bool,
) -> dict[str, object]:
    message = re.sub(r"\b(?:headche|hedache|headeche|headach)\b", "headache", message, flags=re.IGNORECASE)
    message = re.sub(r"\bi\s+(?:hava|hav)\b", "I have", message, flags=re.IGNORECASE)
    state.pending_ai_consent_message = None
    state.ai_processing_consent = True
    ai_processing_consent = True
    common = {
        "assessment_revision": state.revision,
        "response_id": response_id,
        "language": language,
        "recommendations_enabled": settings.recommendations_enabled,
        "catalog_candidate_count": len(catalog),
        "ai_processing_consent": state.ai_processing_consent,
        "options": [],
        "availability": [],
    }

    if _is_urgent_message(message):
        state.disposition = "emergency"
        state.pending_question_ids = []
        state.pending_question_fact_ids = {}
        state.recommendation_requested = False
        return {
            **common,
            "action": "EMERGENCY",
            "intent": "symptom_assessment",
            "reason_codes": ["URGENT_SYMPTOMS_REPORTED"],
            "message": (
                "These symptoms may be life-threatening. Call 112 now or ask "
                "someone nearby to call."
                if language == "en"
                else "Diese Symptome koennen lebensbedrohlich sein. Rufen Sie "
                "jetzt 112 an oder bitten Sie jemanden in Ihrer Naehe darum."
            ),
            "sources": [],
        }

    if _is_greeting(message):
        state.disposition = "unsupported"
        state.pending_ai_consent_message = None
        return {
            **common,
            "action": "GREETING",
            "intent": "greeting",
            "reason_codes": [],
            "message": (
                "Hello! I can help with general medicine information or ask "
                "about symptoms. How can I help?"
                if language == "en"
                else "Hallo! Ich kann allgemeine Arzneimittelinformationen "
                "geben oder nach Beschwerden fragen. Wie kann ich helfen?"
            ),
            "sources": [],
        }

    book_matching = settings.book_medicine_matching_enabled and settings.pinecone_retrieval_mode == "medical_book"
    if book_matching and re.search(r"\b(?:book|textbook|buch)\b", message, re.IGNORECASE) and re.search(
        r"medicin|drug|treatment|medikament|arznei", message, re.IGNORECASE
    ):
        return _book_catalog_response(
            topic=message, language=language, common=common, catalog=catalog,
            llm_adapter=llm_adapter, retriever=retriever,
        )

    intent = _classify_turn(message, state)
    if intent == "personal_medicine_recommendation":
        state.recommendation_requested = True
    if (
        intent != "general_information"
        and llm_adapter is not None
        and ai_processing_consent
    ):
        extraction = _extract_facts(llm_adapter, message, state)
        _apply_extraction(extraction, state, message)
        if (
            len(state.pending_question_ids) == 1
            and not _looks_like_new_question(message)
        ):
            _apply_direct_answer(message, state)
    elif (
        intent != "general_information"
        and state.pending_question_ids
        and not _looks_like_new_question(message)
    ):
        _apply_direct_answer(message, state)
    if _is_correction_message(message) and llm_adapter is None:
        _capture_explicit_facts(message, state)

    if intent == "general_information":
        return _general_information_response(
            message=message,
            language=language,
            common=common,
            state=state,
            llm_adapter=llm_adapter,
            retriever=retriever,
            ai_processing_consent=ai_processing_consent,
        )

    if intent in {"symptom_assessment", "personal_medicine_recommendation"}:
        protocol = _select_protocol(message, state, protocols)
        if protocol is not None:
            state.active_protocol_ids = [protocol.protocol_id]
            state.protocol_versions[protocol.protocol_id] = protocol.version
            state.candidate_product_ids = list(protocol.permitted_product_ids)
        else:
            state.active_protocol_ids = []
            state.candidate_product_ids = []
        assessment = _assessment_response(
            intent=intent,
            message=message,
            language=language,
            common=common,
            catalog=catalog,
            protocol=protocol,
            state=state,
            settings=settings,
            inventory=inventory,
        )
        if (
            book_matching
            and settings.recommendations_enabled
            and assessment.get("reason_codes") == ["NO_ACTIVE_REVIEWED_PROTOCOL"]
            and assessment["action"] == "PHARMACIST_REFERRAL"
        ):
            symptom = state.facts.get("symptoms")
            topic = str(symptom.value) if symptom and symptom.value else " ".join(
                str(complaint.value) for complaint in state.complaints if complaint.value
            )
            return _book_catalog_response(
                topic=topic or message, language=language, common=common, catalog=catalog,
                llm_adapter=llm_adapter, retriever=retriever, fallback=assessment,
            )
        return assessment

    return _general_information_response(
        message=message,
        language=language,
        common=common,
        state=state,
        llm_adapter=llm_adapter,
        retriever=retriever,
        ai_processing_consent=ai_processing_consent,
    )


def _book_catalog_response(
    *,
    topic: str,
    language: str,
    common: dict[str, object],
    catalog: list[ProductRecord],
    llm_adapter: GeminiLanguageAdapter | None,
    retriever: ApprovedPineconeRetriever,
    fallback: dict[str, object] | None = None,
) -> dict[str, object]:
    response = fallback or {
        **common, "action": "GENERAL_INFORMATION", "intent": "general_information",
        "sources": [], "reason_codes": [],
        "message": (
            "This comparison checks names in the book against the catalog. "
            "It does not establish which medicine is suitable for you."
            if language == "en" else
            "Dieser Vergleich prueft Arzneimittelnamen im Buch gegen den Katalog. "
            "Er bestimmt nicht, welches Arzneimittel fuer Sie geeignet ist."
        ),
    }
    if not retriever.configured or llm_adapter is None:
        return {**response, "reason_codes": [*response["reason_codes"], "BOOK_MATCHING_UNAVAILABLE"],
                "book_catalog_matches": []}
    try:
        topic_match = re.search(r"\b(?:for|bei|gegen)\s+(.+?)[?.!]*$", topic, re.IGNORECASE)
        search_topic = topic_match.group(1).rstrip("?.!") if topic_match else topic
        documents = retriever.search(f"{search_topic} treatment medicines", k=8)
        terms = catalog_medicine_search_terms(catalog)
        # Small groups keep a long catalog from overwhelming the symptom query.
        for start in range(0, len(terms), 6):
            documents += retriever.search(f"{search_topic} {' '.join(terms[start:start + 6])}", k=3)
    except Exception as error:
        raise ExternalServiceError("Pinecone", "PINECONE_RETRIEVAL_FAILED") from error
    unique_documents = {doc.metadata["source_id"]: doc for doc in documents}
    passages = [{
        "source_id": str(doc.metadata["source_id"]),
        "source_version": str(doc.metadata["source_version"]),
        "title": str(doc.metadata.get("title", "Medical book")),
        "text": doc.page_content[:4000],
    } for doc in unique_documents.values()]
    if passages:
        try:
            extraction = llm_adapter.extract_book_medicines(topic, passages, catalog_terms=terms)
        except Exception as error:
            raise ExternalServiceError("Gemini", "GEMINI_BOOK_MATCHING_FAILED") from error
        matches = match_book_mentions(extraction, passages, catalog)
    else:
        matches = []
    if not matches:
        return {
            **response, "book_catalog_matches": [],
            "reason_codes": [*response["reason_codes"], "NO_EVIDENCED_CATALOG_MATCH"],
            "message": response["message"] + (" No catalog medicine match could be verified in the retrieved book passages."
                if language == "en" else " In den gefundenen Buchpassagen konnte kein Katalogtreffer belegt werden."),
        }
    used_sources = {match["source_id"] for match in matches}
    entries = "\n".join(
        f"- {match['book_medicine_name']} — {match['catalog_name']} [{match['source_id']}]"
        for match in matches
    )
    explanation = (
        "The AI found treatment mentions in the book with ingredient names matching these catalog entries. "
        "These are reference matches only; the exact product, strength, formulation, and suitability "
        "for you are unconfirmed. They appear in the candidate catalog; stock availability is unknown. "
        "Ask a pharmacist to check before choosing a medicine."
        if language == "en" else
        "Die KI hat Behandlungsnennungen im Buch mit passenden Wirkstoffnamen im Katalog gefunden. "
        "Dies sind nur Referenztreffer; Produkt, Staerke, Darreichungsform und persoenliche Eignung "
        "sind nicht bestaetigt. Sie stehen im Kandidatenkatalog; der Bestand ist unbekannt. "
        "Fragen Sie vor der Auswahl in einer Apotheke nach."
    )
    return {
        **response, "action": "BOOK_CATALOG_MATCHES", "message": explanation + "\n\n" + entries,
        "reason_codes": [*response["reason_codes"], "BOOK_REFERENCE_MATCH_ONLY"],
        "book_catalog_matches": matches, "options": [], "availability": [],
        "sources": [{"source_id": source["source_id"], "source_version": source["source_version"],
                     "title": source["title"], "source_type": "medical_book_reference"}
                    for source in passages if source["source_id"] in used_sources],
    }


def _general_information_response(
    *,
    message: str,
    language: str,
    common: dict[str, object],
    state: AssessmentState,
    llm_adapter: GeminiLanguageAdapter | None,
    retriever: ApprovedPineconeRetriever,
    ai_processing_consent: bool,
) -> dict[str, object]:
    if not retriever.configured:
        return {
            **common,
            "action": "ASK_QUESTION",
            "intent": "general_information",
            "reason_codes": ["PINECONE_NOT_CONFIGURED"],
            "message": (
                "I can answer general medicine questions when reference source "
                "documents are connected. That source service is not configured."
                if language == "en"
                else "Allgemeine Arzneimittelfragen kann ich beantworten, wenn "
                "gepruefte Quellen verbunden sind. Der Quelldienst ist nicht "
                "konfiguriert."
            ),
            "sources": [],
        }
    try:
        documents = retriever.search(message, k=5)
    except Exception as error:
        raise ExternalServiceError("Pinecone", "PINECONE_RETRIEVAL_FAILED") from error
    if not documents:
        return {
            **common,
            "action": "ASK_QUESTION",
            "intent": "general_information",
            "reason_codes": ["NO_SOURCE_MATCH"],
            "message": (
                "I couldn't find a source passage that supports an answer to "
                "that question."
                if language == "en"
                else "Ich habe keine gepruefte Quelle gefunden, die eine "
                "belegte Antwort auf diese Frage ermoeglicht."
            ),
            "sources": [],
        }

    excerpts = [
        {
            "source_id": str(document.metadata["source_id"]),
            "source_version": str(document.metadata["source_version"]),
            "text": document.page_content[:4000],
            "source_type": str(document.metadata.get("source_type", "approved_source")),
            "title": str(document.metadata.get("title", document.metadata.get("source", ""))),
        }
        for document in documents
    ]
    sources = [
        {
            "source_id": item["source_id"],
            "source_version": item["source_version"],
            "title": item["title"],
            "source_type": item["source_type"],
        }
        for item in excerpts
    ]
    if llm_adapter is not None:
        try:
            answer = llm_adapter.answer_general_information(message, excerpts)
        except Exception as error:
            raise ExternalServiceError("Gemini", "GEMINI_ANSWER_FAILED") from error
    else:
        answer = "\n\n".join(
            f"[{item['source_id']}] {item['text']}" for item in excerpts[:2]
        )
    return {
        **common,
        "action": "GENERAL_INFORMATION",
        "intent": "general_information",
        "reason_codes": [],
        "message": answer,
        "sources": sources,
    }


def _assessment_response(
    *,
    intent: str,
    message: str,
    language: str,
    common: dict[str, object],
    catalog: list[ProductRecord],
    protocol: ReviewedProtocol | None,
    state: AssessmentState,
    settings: AppConfig,
    inventory: InventoryClient,
) -> dict[str, object]:
    _capture_explicit_symptom(message, state)
    _capture_explicit_facts(message, state)
    if not state.complaints and "symptoms" not in state.facts:
        state.pending_question_ids = ["symptoms"]
        state.disposition = "assessment_incomplete"
        return _ask_for_fact(
            "symptoms",
            language,
            common,
            "What symptom or concern would you like help with?",
            "Welche Beschwerden oder welches Anliegen haben Sie?",
            intent=intent,
        )

    if protocol is not None:
        required_questions = [
            question
            for question in protocol.questions
            if question.required
            and not _fact_is_known(state.facts.get(question.fact_id))
        ]
        if required_questions:
            selected = required_questions[:2]
            state.pending_question_ids = [
                question.question_id for question in selected
            ]
            state.pending_question_fact_ids = {
                question.question_id: question.fact_id for question in selected
            }
            state.disposition = "assessment_incomplete"
            prompts = [
                question.prompt_en if language == "en" else question.prompt_de
                for question in selected
            ]
            return {
                **common,
                "action": "ASK_QUESTION",
                "intent": intent,
                "reason_codes": [],
                "message": " ".join(prompts),
                "sources": _protocol_sources(protocol),
                "pending_question_ids": state.pending_question_ids,
                "assessment_status": "in_progress",
            }
        state.pending_question_ids = []
        if intent != "personal_medicine_recommendation":
            guidance = (
                protocol.assessment_guidance_en
                if language == "en"
                else protocol.assessment_guidance_de
            )
            if guidance and guidance.strip():
                state.disposition = "self_care"
                return {
                    **common,
                    "action": "SELF_CARE",
                    "intent": "symptom_assessment",
                    "reason_codes": [],
                    "message": guidance.strip(),
                    "sources": _protocol_sources(protocol),
                    "assessment_status": "complete",
                }
            state.disposition = "unsupported"
            return {
                **common,
                "action": "PHARMACIST_REFERRAL",
                "intent": "symptom_assessment",
                "reason_codes": ["PROTOCOL_ASSESSMENT_OUTCOME_MISSING"],
                "message": (
                    "The reviewed follow-up is complete, but this protocol has "
                    "no reviewed assessment guidance. I can't assess the cause "
                    "or recommend treatment. Please contact a pharmacist or a "
                    "nearby doctor or clinic."
                    if language == "en"
                    else "Die geprueften Rueckfragen sind abgeschlossen, aber "
                    "dieses Protokoll enthaelt keine gepruefte Beurteilung. Ich "
                    "kann die Ursache nicht beurteilen und keine Behandlung "
                    "empfehlen. Bitte wenden Sie sich an eine Apotheke oder "
                    "Arztpraxis."
                ),
                "sources": _protocol_sources(protocol),
                "assessment_status": "outcome_unavailable",
            }
        if intent == "personal_medicine_recommendation" and not settings.recommendations_enabled:
            state.disposition = "unsupported"
            state.recommendation_requested = False
            return {
                **common,
                "action": "UNSUPPORTED",
                "intent": intent,
                "reason_codes": ["RECOMMENDATIONS_DISABLED"],
                "message": (
                    "Personal medicine recommendations are disabled. I can still "
                    "provide supported general information."
                    if language == "en"
                    else "Persoenliche Arzneimittelempfehlungen sind deaktiviert. "
                    "Belegte allgemeine Informationen kann ich weiterhin geben."
                ),
                "sources": [],
            }
        state.recommendation_requested = False
        return _recommendation_response(
            language=language,
            common=common,
            catalog=catalog,
            protocol=protocol,
            state=state,
            inventory=inventory,
        )

    missing = [
        fact_id
        for fact_id in ("age", "symptom_duration", "allergies", "current_medications")
        if not _fact_is_known(state.facts.get(fact_id))
    ]
    if missing:
        prompts = {
            "age": (
                "Who are these symptoms for, and how old is the person?",
                "Um wen geht es, und wie alt ist die Person?",
            ),
            "symptom_duration": (
                "When did this symptom begin, and how long has it been present?",
                "Wann hat dieses Symptom begonnen, und wie lange besteht es schon?",
            ),
            "allergies": (
                "Are there any medicine allergies? If none, please say “no allergies.”",
                "Bestehen Arzneimittelallergien? Wenn nicht, sagen Sie bitte „keine Allergien“.",
            ),
            "current_medications": (
                "What medicines is the person currently taking? If none, say “none.”",
                "Welche Arzneimittel nimmt die Person derzeit ein? Wenn keine, sagen Sie „keine“.",
            ),
        }
        selected = missing[:1]
        state.pending_question_ids = selected
        state.pending_question_fact_ids = {
            question_id: question_id for question_id in selected
        }
        state.disposition = "assessment_incomplete"
        return {
            **common,
            "action": "ASK_QUESTION",
            "intent": intent,
            "reason_codes": ["NO_ACTIVE_REVIEWED_PROTOCOL"],
            "message": " ".join(
                prompts[fact_id][0 if language == "en" else 1]
                for fact_id in selected
            ),
            "sources": [],
            "pending_question_ids": selected,
            "assessment_status": "intake_in_progress",
        }

    state.pending_question_ids = []
    state.pending_question_fact_ids = {}
    state.recommendation_requested = False
    state.disposition = "unsupported"
    return {
        **common,
        "action": "PHARMACIST_REFERRAL",
        "intent": intent,
        "reason_codes": ["NO_ACTIVE_REVIEWED_PROTOCOL"],
        "message": (
            "I have recorded the details, but no reviewed assessment protocol "
            "is active for these symptoms. I can't assess the cause or recommend "
            "treatment. Please contact a pharmacist or a nearby doctor or clinic."
            if language == "en"
            else "Ich habe die Angaben aufgenommen, aber fuer diese Beschwerden "
            "ist kein geprueftes Beurteilungsprotokoll aktiv. Ich kann die "
            "Ursache nicht beurteilen und keine Behandlung empfehlen. Bitte "
            "wenden Sie sich an eine Apotheke oder eine Arztpraxis."
        ),
        "sources": [],
        "assessment_status": "protocol_unavailable",
    }


def _recommendation_response(
    *,
    language: str,
    common: dict[str, object],
    catalog: list[ProductRecord],
    protocol: ReviewedProtocol,
    state: AssessmentState,
    inventory: InventoryClient,
) -> dict[str, object]:
    permitted = [
        product
        for product in catalog
        if product.product_id in protocol.permitted_product_ids
    ]
    missing_fields = {
        product.product_id: catalog_record_missing_fields(product)
        for product in permitted
        if not catalog_record_ready(product)
    }
    ready = [product for product in permitted if catalog_record_ready(product)]
    if not ready:
        state.disposition = "pharmacist_referral"
        code = "CATALOG_DATA_PENDING" if not permitted else "PRODUCT_DATA_INCOMPLETE"
        return {
            **common,
            "action": "PHARMACIST_REFERRAL",
            "intent": "personal_medicine_recommendation",
            "reason_codes": [code],
            "message": (
                "No protocol-permitted product has a complete reviewed record. "
                "The affected product records are blocked; contact a pharmacist "
                "or nearby doctor or clinic."
                if language == "en"
                else "Kein vom Protokoll zugelassenes Produkt hat einen "
                "vollstaendigen geprueften Datensatz. Die betroffenen "
                "Produkte bleiben gesperrt; wenden Sie sich an eine Apotheke "
                "oder Arztpraxis."
            ),
            "sources": _protocol_sources(protocol),
            "missing_product_fields": missing_fields,
        }

    patient_checks: dict[str, list[MedicineCheck]] = {
        product.product_id: evaluate_patient_checks(product, state.facts)
        for product in ready
    }
    checked_products = [
        product.model_copy(
            update={
                "patient_eligibility_status": (
                    "eligible"
                    if patient_checks[product.product_id]
                    and all(
                        check.outcome == CheckOutcome.PASS
                        for check in patient_checks[product.product_id]
                    )
                    else "not_assessed"
                )
            }
        )
        for product in ready
    ]
    decision = evaluate_options(
        checked_products,
        patient_checks,
        {},
        permitted_product_ids={product.product_id for product in checked_products},
    )
    if decision.action != "MEDICINE_OPTION":
        state.disposition = "pharmacist_referral"
        return {
            **common,
            "action": decision.action,
            "intent": "personal_medicine_recommendation",
            "reason_codes": decision.reason_codes,
            "message": (
                "The available patient and product checks do not support a "
                "medicine option. Please contact a pharmacist or nearby doctor "
                "or clinic."
                if language == "en"
                else "Die verfuegbaren Patienten- und Produktpruefungen stuetzen "
                "keine Arzneimitteloption. Bitte wenden Sie sich an eine "
                "Apotheke oder Arztpraxis."
            ),
            "sources": _protocol_sources(protocol),
            "check_results": {
                product_id: [check.model_dump(mode="json") for check in checks]
                for product_id, checks in patient_checks.items()
            },
        }

    availability: dict[str, bool | None] = {}
    inventory_errors: list[str] = []
    for option in decision.options:
        product = next(item for item in checked_products if item.product_id == option.product_id)
        if product.inventory_product_id is None:
            availability[product.product_id] = None
            inventory_errors.append("INVENTORY_PRODUCT_ID_MISSING")
            continue
        try:
            availability[product.inventory_product_id] = inventory.availability(
                product.inventory_product_id
            )
        except InventoryUnavailable:
            availability[product.inventory_product_id] = None
            inventory_errors.append("INVENTORY_UNAVAILABLE")
    final_decision = evaluate_options(
        checked_products,
        patient_checks,
        availability,
        permitted_product_ids={product.product_id for product in checked_products},
    )
    state.disposition = "medicine_option"
    return {
        **common,
        "action": final_decision.action,
        "intent": "personal_medicine_recommendation",
        "reason_codes": sorted(set(final_decision.reason_codes + inventory_errors)),
        "message": (
            "The reviewed protocol and required checks support the listed option. "
            "Please follow the reviewed product information and confirm stock "
            "with the pharmacist."
            if language == "en"
            else "Das gepruefte Protokoll und die erforderlichen Pruefungen "
            "stuetzen die aufgefuehrte Option. Bitte beachten Sie die geprueften "
            "Produktinformationen und bestaetigen Sie den Bestand in der Apotheke."
        ),
        "sources": _protocol_sources(protocol),
        "options": [option.model_dump(mode="json") for option in final_decision.options],
        "availability": [
            {"product_id": option.product_id, "status": option.availability}
            for option in final_decision.options
        ],
        "check_results": {
            product_id: [check.model_dump(mode="json") for check in checks]
            for product_id, checks in patient_checks.items()
        },
    }


def _extract_facts(
    adapter: GeminiLanguageAdapter,
    message: str,
    state: AssessmentState,
) -> FactExtraction:
    summary = json.dumps(
        {
            "language": state.language,
            "subject": state.subject.model_dump(mode="json"),
            "facts": {
                key: value.model_dump(mode="json")
                for key, value in state.facts.items()
            },
            "complaints": [
                complaint.model_dump(mode="json")
                for complaint in state.complaints
            ],
            "pending_question_ids": state.pending_question_ids,
            "pending_question_fact_ids": state.pending_question_fact_ids,
        },
        ensure_ascii=False,
    )
    try:
        return adapter.extract_facts(message, summary)
    except Exception as error:
        raise ExternalServiceError("Gemini", "GEMINI_FACT_EXTRACTION_FAILED") from error


def _apply_extraction(extraction: FactExtraction, state: AssessmentState, message: str) -> None:
    now = datetime.now(timezone.utc)
    if extraction.language in LANGUAGES:
        state.language = extraction.language
    for extracted in extraction.facts:
        if extracted.name not in FACT_IDS or extracted.status in {
            FactStatus.NOT_ASKED,
            FactStatus.UNKNOWN,
        }:
            continue
        if extracted.name in {"symptoms", "associated_symptoms"}:
            if not isinstance(extracted.value, str) or not extracted.value.strip():
                continue
            pending_facts = {
                state.pending_question_fact_ids.get(question_id, question_id)
                for question_id in state.pending_question_ids
            }
            if (
                pending_facts
                and not pending_facts.intersection({"symptoms", "associated_symptoms"})
                and not _is_symptom_message(message)
                and not _is_correction_message(message)
            ):
                continue
        fact = ClinicalFact(
            value=extracted.value,
            status=extracted.status,
            subject_id=extracted.subject,
            supporting_text=extracted.supporting_text,
            recorded_at=now,
        )
        state.facts[extracted.name] = fact
        if extracted.name == "age" and isinstance(extracted.value, int):
            state.subject.age = extracted.value
        elif extracted.name == "subject_relationship" and isinstance(extracted.value, str):
            state.subject.relationship = extracted.value
        elif extracted.name in {"symptoms", "associated_symptoms"} and extracted.value:
            state.complaints = []
            state.complaints.append(fact)
    known_question_ids = {
        question_id
        for question_id in state.pending_question_ids
        if _fact_is_known(
            state.facts.get(state.pending_question_fact_ids.get(question_id, question_id))
        )
    }
    state.pending_question_ids = [
        fact_id
        for fact_id in state.pending_question_ids
        if fact_id not in known_question_ids
    ]
    for question_id in known_question_ids:
        state.pending_question_fact_ids.pop(question_id, None)


def _apply_direct_answer(message: str, state: AssessmentState) -> None:
    value = message.strip()
    for question_id in state.pending_question_ids:
        fact_id = state.pending_question_fact_ids.get(question_id, question_id)
        normalized = value.casefold()
        if fact_id == "age":
            match = re.search(r"\b(\d{1,3})\b", value)
            if match and int(match.group(1)) <= 130:
                state.subject.age = int(match.group(1))
                _set_fact(state, "age", int(match.group(1)), FactStatus.REPORTED, value)
        elif fact_id == "symptoms":
            state.complaints = [
                ClinicalFact(
                    value=value,
                    status=FactStatus.REPORTED,
                    subject_id=state.subject.relationship,
                )
            ]
            _set_fact(state, "symptoms", value, FactStatus.REPORTED, value)
        elif fact_id in {"allergies", "current_medications", "conditions"}:
            if normalized in {"no", "none", "nope", "nein", "keine", "keine."}:
                _set_fact(state, fact_id, False, FactStatus.DENIED, value)
            else:
                _set_fact(state, fact_id, value, FactStatus.REPORTED, value)
        elif fact_id in {"symptom_duration", "onset", "severity"}:
            _set_fact(state, fact_id, value, FactStatus.REPORTED, value)
    state.pending_question_ids = [
        question_id
        for question_id in state.pending_question_ids
        if not _fact_is_known(
            state.facts.get(state.pending_question_fact_ids.get(question_id, question_id))
        )
    ]
    state.pending_question_fact_ids = {
        question_id: fact_id
        for question_id, fact_id in state.pending_question_fact_ids.items()
        if question_id in state.pending_question_ids
    }


def _set_fact(
    state: AssessmentState,
    fact_id: str,
    value: str | int | bool,
    status: FactStatus,
    source_text: str,
) -> None:
    state.facts[fact_id] = ClinicalFact(
        value=value,
        status=status,
        subject_id=state.subject.relationship,
        supporting_text=source_text,
    )


def _capture_explicit_symptom(message: str, state: AssessmentState) -> None:
    if state.complaints:
        symptom_terms = (
            "headache",
            "fever",
            "rash",
            "sore throat",
            "stomach pain",
            "nausea",
            "cough",
            "kopfschmerz",
            "fieber",
            "ausschlag",
            "halsschmerzen",
            "bauchschmerzen",
            "uebelkeit",
            "übelkeit",
            "husten",
            "pain",
            "schmerz",
        )
        if _is_correction_message(message) and any(
            term in message.casefold() for term in symptom_terms
        ):
            fact = ClinicalFact(
                value=message.strip(),
                status=FactStatus.REPORTED,
                subject_id=state.subject.relationship,
            )
            state.complaints = [fact]
            state.facts["symptoms"] = fact
        return
    if _is_symptom_message(message):
        fact = ClinicalFact(
            value=message.strip(),
            status=FactStatus.REPORTED,
            subject_id=state.subject.relationship,
        )
        state.complaints.append(fact)
        state.facts.setdefault("symptoms", fact)


def _capture_explicit_facts(message: str, state: AssessmentState) -> None:
    if re.search(
        r"\b(?:actually|correction|i meant|sorry|eigentlich|korrektur|"
        r"ich meinte|entschuldigung)\b",
        message,
        re.IGNORECASE,
    ):
        age_correction = re.search(r"\b(\d{1,3})\b", message)
        if age_correction and state.subject.age is not None:
            age = int(age_correction.group(1))
            if age <= 130:
                state.subject.age = age
                _set_fact(state, "age", age, FactStatus.REPORTED, message)

    age_match = re.search(
        r"\b(?:i am|i'm|age(?:d)?|aged|ich bin|alter(?: ist)?)\s*(\d{1,3})\b|"
        r"\b(\d{1,3})\s*(?:years? old|jahre alt)\b",
        message,
        re.IGNORECASE,
    )
    if age_match:
        age = int(next(value for value in age_match.groups() if value is not None))
        if age <= 130:
            state.subject.age = age
            _set_fact(state, "age", age, FactStatus.REPORTED, message)

    relationship = re.search(
        r"\b(my child|my son|my daughter|for my child|myself|for me|"
        r"mein kind|meine tochter|mein sohn|ich selbst|fuer mich|für mich)\b",
        message,
        re.IGNORECASE,
    )
    if relationship:
        value = relationship.group(1).casefold()
        relationship_value = (
            "child"
            if value in {"my child", "my son", "my daughter", "for my child", "mein kind", "meine tochter", "mein sohn"}
            else "self"
        )
        state.subject.relationship = relationship_value
        _set_fact(
            state,
            "subject_relationship",
            relationship_value,
            FactStatus.REPORTED,
            message,
        )

    duration_match = re.search(
        r"\b(?:since|for)\s+(?:about\s+)?[\w-]+\s+"
        r"(?:hours?|days?|weeks?|months?)\b|"
        r"\b(?:since|from)\s+(?:yesterday|today|last night|this morning)\b|"
        r"\bseit\s+(?:gestern|heute|letzter nacht|\d+\s+"
        r"(?:stunden?|tagen?|wochen|monaten?))\b",
        message,
        re.IGNORECASE,
    )
    if duration_match:
        _set_fact(
            state,
            "symptom_duration",
            duration_match.group(0),
            FactStatus.REPORTED,
            message,
        )

    normalized = message.casefold()
    if re.search(
        r"\b(no allergies|no known allergies|no medicine allergies|"
        r"keine allergien|keine bekannten allergien|keine arzneimittelallergien)\b",
        normalized,
    ):
        _set_fact(state, "allergies", False, FactStatus.DENIED, message)
    elif "allerg" in normalized:
        _set_fact(state, "allergies", message.strip(), FactStatus.REPORTED, message)

    if re.search(
        r"\b(no medicines|no medication|not taking any|keine medikamente|"
        r"nehme keine|keine arzneimittel)\b",
        normalized,
    ):
        _set_fact(
            state,
            "current_medications",
            False,
            FactStatus.DENIED,
            message,
        )
    elif re.search(r"\b(i take|i am taking|ich nehme|nehme derzeit)\b", normalized):
        _set_fact(
            state,
            "current_medications",
            message.strip(),
            FactStatus.REPORTED,
            message,
        )


def _fact_is_known(fact: ClinicalFact | None) -> bool:
    return fact is not None and fact.status not in {
        FactStatus.NOT_ASKED,
        FactStatus.UNKNOWN,
        FactStatus.CONFLICTING,
    }


def _ask_for_fact(
    fact_id: str,
    language: str,
    common: dict[str, object],
    english: str,
    german: str,
    *,
    intent: str,
) -> dict[str, object]:
    return {
        **common,
        "action": "ASK_QUESTION",
        "intent": intent,
        "reason_codes": [],
        "message": english if language == "en" else german,
        "sources": [],
        "pending_question_ids": [fact_id],
        "assessment_status": "in_progress",
    }


def _select_protocol(
    message: str,
    state: AssessmentState,
    protocols: list[ReviewedProtocol],
) -> ReviewedProtocol | None:
    prior = next(
        (
            protocol
            for protocol in protocols
            if protocol.protocol_id in state.active_protocol_ids
        ),
        None,
    )
    if prior is not None:
        return prior
    text = " ".join(
        [message]
        + [
            str(complaint.value)
            for complaint in state.complaints
            if complaint.value is not None
        ]
    ).casefold()
    return next(
        (
            protocol
            for protocol in protocols
            if any(term.casefold() in text for term in protocol.symptom_terms)
        ),
        None,
    )


def _recommendation_sources(protocol: ReviewedProtocol) -> list[dict[str, str]]:
    return [
        {"source_id": source_id, "source_version": protocol.source_versions[source_id]}
        for source_id in protocol.source_ids
    ]


def _protocol_sources(protocol: ReviewedProtocol) -> list[dict[str, str]]:
    return _recommendation_sources(protocol)


def _classify_message(message: str, state: AssessmentState) -> str:
    normalized = message.casefold()
    if any(cue in normalized for cue in PERSONAL_CUES):
        return "personal_medicine_recommendation"
    if normalized.endswith("?") or any(
        cue in normalized
        for cue in (
            "what is",
            "tell me about",
            "how does",
            "what does",
            "was ist",
            "erklaer",
            "erklär",
            "wie wirkt",
            "wofuer",
            "wofür",
        )
    ):
        return "general_information"
    if (
        state.pending_question_ids
        or _is_correction_message(message)
        or _is_symptom_message(message)
    ):
        return "symptom_assessment"
    return "general_information"


def _classify_turn(message: str, state: AssessmentState) -> str:
    intent = _classify_message(message, state)
    if state.recommendation_requested and intent == "symptom_assessment":
        return "personal_medicine_recommendation"
    return intent


def _looks_like_new_question(message: str) -> bool:
    return bool(
        re.match(
            r"^\s*(?:what|which|when|where|why|how|can i|should i|"
            r"was|welche|welcher|welches|wann|wo|warum|wie|kann ich|soll ich)\b",
            message,
            re.IGNORECASE,
        )
    )


def _is_correction_message(message: str) -> bool:
    return bool(
        re.search(
            r"\b(?:actually|correction|i meant|sorry|eigentlich|korrektur|"
            r"ich meinte|entschuldigung)\b",
            message,
            re.IGNORECASE,
        )
    )


def _is_greeting(message: str) -> bool:
    return bool(
        re.fullmatch(
            r"\s*(?:hi|hello|hey|greetings|good morning|good afternoon|"
            r"good evening|hallo|guten morgen|guten tag|guten abend|moin|"
            r"servus)\s*[!.?]*\s*",
            message,
            flags=re.IGNORECASE,
        )
    )


def _is_consent_affirmation(message: str) -> bool:
    normalized = re.sub(r"\s+", " ", message.casefold()).strip(" \t\r\n.!?,")
    return normalized in {
        "yes",
        "yes please",
        "ok",
        "okay",
        "i agree",
        "i agree to that",
        "i consent",
        "go ahead",
        "sure",
        "ja",
        "ja bitte",
        "ok bitte",
        "okay bitte",
        "einverstanden",
        "ich stimme zu",
        "ich bin einverstanden",
        "ich willige ein",
    }


def _is_consent_decline(message: str) -> bool:
    normalized = re.sub(r"\s+", " ", message.casefold()).strip(" \t\r\n.!?,")
    return normalized in {
        "no",
        "no thanks",
        "no thank you",
        "don't",
        "do not",
        "nein",
        "nein danke",
    }


def _is_symptom_message(message: str) -> bool:
    normalized = message.casefold()
    return any(
        cue in normalized
        for cue in (
            "i have ",
            "i've had ",
            "i am ",
            "i'm ",
            "i feel ",
            "my ",
            "ich habe ",
            "ich bin ",
            "mir ist ",
            "mir wird ",
            "meine ",
            "mein ",
            "headache",
            "fever",
            "rash",
            "sore throat",
            "stomach pain",
            "nausea",
            "cough",
            "kopfschmerz",
            "fieber",
            "ausschlag",
            "halsschmerzen",
            "bauchschmerzen",
            "uebelkeit",
            "übelkeit",
            "husten",
        )
    )


def _is_urgent_message(message: str) -> bool:
    normalized = message.casefold()
    urgent_phrases = (
        "can't breathe",
        "cannot breathe",
        "stopped breathing",
        "severe chest pain",
        "crushing chest pain",
        "pressure in my chest",
        "pressure on my chest",
        "trouble breathing",
        "difficulty breathing",
        "shortness of breath",
        "chest pressure",
        "pressure on my chest",
        "druck auf der brust",
        "brustdruck",
        "kann nicht atmen",
        "keine luft bekommen",
        "bekomme keine luft",
        "krieg keine luft",
        "kriege keine luft",
        "atemnot",
        "starke brustschmerzen",
        "massive brustschmerzen",
        "gesicht hängt",
        "gesichtshaelfte haengt",
    )
    return any(
        phrase in normalized
        and not re.search(
            r"\b(?:no|not|without|kein|keine|nicht)\b(?:\s+\w+){0,4}\s+$",
            normalized[: normalized.find(phrase)],
        )
        for phrase in urgent_phrases
    )


def _validated_uuid(value: object, field: str) -> str | tuple[Response, int]:
    if not isinstance(value, str):
        return _error("INVALID_REQUEST", f"{field} must be a UUID.", 400)
    try:
        return str(UUID(value))
    except ValueError:
        return _error("INVALID_REQUEST", f"{field} must be a UUID.", 400)


def _bearer_token() -> str | None:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        return None
    return token.strip()


def _error(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


load_dotenv()
app = create_app()


if __name__ == "__main__":
    from waitress import serve

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8080"))
    serve(app, host=host, port=port)
