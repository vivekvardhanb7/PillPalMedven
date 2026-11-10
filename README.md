# Build-a-Complete-Medical-Chatbot-with-LLMs-LangChain-Pinecone-Flask-AWS

# Run locally (Windows PowerShell)

Requirements: Python 3.10 or later. Gemini, Pinecone, and inventory credentials
are optional for startup; the corresponding integrations report unavailable
until configured. Create keys at [Pinecone](https://app.pinecone.io/) and
[Google AI Studio](https://aistudio.google.com/apikey).

1. From the repository root, create and activate a virtual environment and install
   the dependencies:

   ```powershell
   py -3.10 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

2. If you do not already have `.env`, create it from the example; then enter
   your keys locally. Preserve existing key values when editing it. Keep secrets
   out of Git.

   ```powershell
   if (-not (Test-Path .env)) { Copy-Item .env.example .env }
   notepad .env
   ```

3. Configure `.env` and start the local application:

   ```powershell
   python app.py
   ```

   Open [http://127.0.0.1:8080](http://127.0.0.1:8080).

### Run the checks

Use the same virtual environment as the application. The Python tests use
stubbed integrations and do not require live Gemini, Pinecone, inventory, or
speech-model access:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

With Node.js 18 or later installed, also run the chat UI regression check:

```powershell
node --test tests/test_chat_ui.cjs
```

### Connected workflow and clinical data

The application loads all 30 catalog entries, routes greetings and bilingual
requests, stores facts and corrections in isolated expiring sessions, and uses
the same `/api/chat` workflow for typed and voice-transcribed messages. When
configured, it sends chat text to Gemini for structured fact extraction and
source-grounded general information. In `medical_book` mode, Pinecone searches
only the configured book's exact `source` metadata and returns passages with
book/chunk citations. In `approved_sources` mode, retrieval requires explicitly
approved German sources. Inventory is queried
only after the clinical/product evaluator determines an option is suitable.
Voice audio is transcribed locally with Whisper and replies are generated
locally with Piper; only the resulting transcript is sent through the chat
workflow. Voice is turn-based, not a continuous Gemini Live stream.

The repository's 30 catalog rows are reference candidates, not approved
products. Their manufacturer/SKU fields, source versions, clinical and vending
approvals, patient-check rules, and inventory IDs are not complete. There is
also no active reviewed protocol or approved-source manifest in the checkout.
Accordingly, current real-data readiness does **not** include symptom protocols
or medicine recommendations. The application asks non-diagnostic intake
questions and then blocks unsupported decisions, listing exact missing fields
per product. It never treats a pending product as approved. Do not add approval
fields until the responsible clinical/product reviewers verify them.

The chat page persistently discloses that chat text, including local voice
transcripts, is sent to Gemini when configured; audio remains on the local
server for Whisper transcription. There is no consent checkbox. The microphone
starts only after the user clicks it and grants browser permission. Do not
enter identifying patient information. Session facts are held in process
memory until reset/expiry; use a reviewed shared store before running multiple
workers.

Copy the example configuration, add credentials locally, and keep `.env` out
of Git:

```ini
PINECONE_API_KEY=your-pinecone-api-key
GEMINI_API_KEY=your-gemini-api-key
PINECONE_INDEX_NAME=medical-chatbot
PINECONE_RETRIEVAL_MODE=medical_book
PINECONE_BOOK_SOURCE='data\Medical_book.pdf'
APPROVED_SOURCE_MANIFEST=instance/approved_source_manifest.json
RECOMMENDATIONS_ENABLED=true
BOOK_MEDICINE_MATCHING_ENABLED=true
PRODUCT_SCOPE_MODE=team_confirmed_catalog
PLANNED_PRODUCT_COUNT=30
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-2.5-flash
VOICE_ENABLED=true
WHISPER_MODEL=base
PIPER_EN_MODEL_PATH=models/piper/en_US-lessac-medium.onnx
PIPER_DE_MODEL_PATH=models/piper/de_DE-thorsten-medium.onnx
CATALOG_ADMIN_TOKEN=replace-with-a-long-random-secret
PRODUCT_CATALOG_PATH=instance/product_catalog.json
PROTOCOL_CATALOG_PATH=instance/protocols.json
INVENTORY_API_URL=https://inventory.example.invalid/api
INVENTORY_API_TOKEN=replace-with-a-local-secret
RAW_HEALTH_LOGGING_ENABLED=false
```

`GET /health/ready` reports provider configuration, protocol count, ready
product IDs, and missing product fields. `GET /api/catalog` returns the complete
30-entry catalog and its current review state.

The catalog seeder and activation endpoints cannot create clinical approvals.
The activation routes return `409 CLINICAL_REVIEW_REQUIRED`; verified reviewer
records must come from the responsible clinical/product review process. On
startup, records carrying the seeder's placeholder reviewer identity are
replaced in memory with the pending candidate definitions.

Pinecone ingestion remains staging-index-only. `store_index.py` marks documents
unreviewed by default. To make reviewed documents retrievable, the responsible
source reviewer must create the local `APPROVED_SOURCE_MANIFEST` JSON file with
entries like:

```json
[
  {
    "source_file": "reviewed-label.pdf",
    "source_id": "REVIEWED-LABEL-001",
    "source_version": "2026-01",
    "approved": true,
    "review_status": "approved",
    "approved_by": "Reviewer identity supplied by the responsible team",
    "jurisdiction": "DE",
    "language": "de"
  }
]
```

In `PINECONE_RETRIEVAL_MODE=approved_sources`, only indexed chunks marked approved, with the approved review status, DE
jurisdiction, source ID, and source version are eligible for retrieval. Re-run
the ingestion script after review; never mark sources approved just to make
retrieval work. The ingestion utility requires a Pinecone index name ending in
`-staging`; production retrieval should point to a separately governed approved
index populated from reviewed sources.

For the existing `medical-chatbot` index, use `medical_book` mode and set
`PINECONE_BOOK_SOURCE` to the exact source value stored on its vectors (currently
`data\Medical_book.pdf`). This mode reads the existing book without reindexing
or changing its metadata. Book passages support educational answers only;
they do not supply clinical/product approval. Their citation version is
`unversioned` because the existing vectors do not store an edition or page
number. The UI shows the filename and stable passage IDs with each answer.
If no matching passage is returned, the app reports that it cannot support
an answer. Restart the application after editing `.env`.

`BOOK_MEDICINE_MATCHING_ENABLED=true` enables AI-assisted comparisons between
treatment mentions in retrieved book passages and ingredient names in the
catalog. Ask, for example, "Which medicines does the book mention for headache?"
The comparison also runs after a personal medicine request finishes intake
without an active reviewed protocol. AI must supply an exact medicine name,
source ID, and verbatim supporting quote. The application verifies the quote
and name against the retrieved text (normalizing PDF line wrapping and
punctuation while preserving words and their order) and matches known name aliases against
the catalog; invented evidence, withdrawn products, and synthetic entries are
excluded. The model's interpretation of treatment context remains unreviewed.
Matches return as `book_catalog_matches`, separately from eligible `options`.
A name match does not confirm strength, formulation, exact product equivalence,
patient suitability, stock, or clinical approval. Catalog records are not
activated by this feature, and unmatched names remain unconfirmed.

`PROTOCOL_CATALOG_PATH` is an optional JSON array of reviewed protocol records.
Every active protocol needs `approved: true`, `status: "active"`, an identified
reviewer, versioned source IDs, symptom terms, English/German question text,
and protocol-permitted product IDs. Assessment-only requests also require
reviewed English/German assessment guidance; they return that guidance without
making a medicine recommendation. If it is absent, the assessment stays
blocked. Invalid protocol records fail app startup; unapproved/draft/withdrawn
protocols are not activated. No clinically reviewed protocol is included in
this repository.

Product-specific `patient_check_rules` must be reviewed, complete, and cite the
same source versions as the product record. Supported deterministic rules
compare explicit age/allergy/condition/current-medication facts to those
reviewed rules. Missing or conflicting patient facts, stale evidence, or
incomplete product fields block that product. `RECOMMENDATIONS_ENABLED` only
enables the feature path; it does not make candidates eligible.

The inventory connector uses
`GET {INVENTORY_API_URL}/products/{inventory_product_id}/availability`, accepts
only JSON of the form `{"available": true}` or `{"available": false}`, and
requires a bearer token when `INVENTORY_API_TOKEN` is configured. An unknown or
unreachable inventory result does not change suitability.

Alternatively, configure `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in the
local `.env` (the existing custom inventory URL takes precedence). Run
`supabase/medassist_inventory.sql` once in the intended project's SQL Editor.
The script creates only its dedicated table, fails if that name exists, and
revokes browser-role access. Keep the service key on the server. Enter only
verified, real inventory IDs, names, and quantities in that table, then map each
reviewed catalog product's `inventory_product_id` to the corresponding inventory
ID. A missing row, null quantity, inaccessible table, or failed request is
reported as unknown; zero is out of stock. This does not approve or activate
any product. Book-reference matches still have unknown stock because an
ingredient-name match does not confirm an exact stocked SKU.

The app exposes `POST /api/admin/products/<product_id>/withdraw`, protected by
`CATALOG_ADMIN_TOKEN`. It persists a product withdrawal to
`PRODUCT_CATALOG_PATH` and does not disable unrelated product paths or the global
feature. Configure a strong secret locally; never commit it. The default local
catalog file is ignored by Git. In containers, mount a persistent volume at
`/app/instance` before relying on catalog changes.

The eligibility service requires an active exact SKU, team confirmation,
clinical approval, separate vending eligibility, audit provenance, complete
reviewed check rules, and passing patient-specific checks. Only then is stock
queried. Inventory never makes an unsuitable product eligible.

```powershell
python store_index.py
```

The API exposes `POST /api/sessions`, `POST /api/chat`,
`POST /api/voice/transcribe`, `POST /api/voice/synthesize`,
`POST /api/session/reset`, `GET /health/live` and `GET /health/ready`.
Health readiness distinguishes configured integrations from clinical
readiness. Configured credentials do not prove network connectivity, approved
source coverage, or clinical validation.

### Local voice assistant

The microphone remains off until the user clicks it and grants browser
permission. Speech is captured in short turns, locally transcribed by
faster-whisper, sent as text through the existing Gemini chat flow, and spoken
locally by Piper. The microphone resumes after each spoken reply; click it
again to stop. The browser must support `MediaRecorder` and `getUserMedia`.
Voice is turn-based rather than a streaming Gemini Live connection. The first
use of the default Whisper model may download model files; subsequent
transcription runs locally. No speech models are bundled in the repository.

The runtime voice services use `VOICE_ENABLED=true`. After installing the
Python dependencies, download the English and German Piper voices:

```powershell
python -m piper.download_voices --download-dir models/piper en_US-lessac-medium de_DE-thorsten-medium
```

Voice audio is held only in the active request and deleted after transcription.
Piper output is generated per response and is not retained. Configure
`WHISPER_MODEL` to an installed faster-whisper model name or local model
directory, and configure the Piper paths if voices are stored elsewhere. The
app reports local model errors instead of falling back to browser/cloud
speech. Check each Piper voice's license before redistribution; voice licensing
is separate from the application code license.


### Techstack Used:

- Python
- LangChain
- Flask
- Pydantic
- Waitress
- Gemini structured fact-extraction adapter (not called while catalog data is pending)
- Local Whisper transcription and Piper text-to-speech (optional; model and
  voice files are downloaded separately)
- Pinecone



# AWS-CICD-Deployment-with-Github-Actions

## 1. Login to AWS console.

## 2. Create IAM user for deployment

	#with specific access

	1. EC2 access : It is virtual machine

	2. ECR: Elastic Container registry to save your docker image in aws


	#Description: About the deployment

	1. Build docker image of the source code

	2. Push your docker image to ECR

	3. Launch Your EC2 

	4. Pull Your image from ECR in EC2

	5. Lauch your docker image in EC2

	#Policy:

	1. AmazonEC2ContainerRegistryFullAccess

	2. AmazonEC2FullAccess

	
## 3. Create ECR repo to store/save docker image
    - Save the URI: 315865595366.dkr.ecr.us-east-1.amazonaws.com/medicalbot

	
## 4. Create EC2 machine (Ubuntu) 

## 5. Open EC2 and Install docker in EC2 Machine:
	
	
	#optinal

	sudo apt-get update -y

	sudo apt-get upgrade
	
	#required

	curl -fsSL https://get.docker.com -o get-docker.sh

	sudo sh get-docker.sh

	sudo usermod -aG docker ubuntu

	newgrp docker
	
# 6. Configure EC2 as self-hosted runner:
    setting>actions>runner>new self hosted runner> choose os> then run command one by one


# 7. Setup github secrets:

   - AWS_ACCESS_KEY_ID
   - AWS_SECRET_ACCESS_KEY
   - AWS_DEFAULT_REGION
   - ECR_REPO

The Docker image uses Waitress rather than Flask's development server. Do not
deploy it as a patient-facing service: the guide's clinical, pharmaceutical,
privacy, regulatory and multi-process session-store milestones remain incomplete.
