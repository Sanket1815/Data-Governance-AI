# Data Governance AI

An AI-powered healthcare insurance analytics portal on Google BigQuery, made of three
subsystems that share one FastAPI backend and one Next.js frontend:

| Subsystem | What it does |
|---|---|
| **NL2SQL Engine** | Natural language → GoogleSQL over BigQuery, using LlamaIndex + Gemini (or OpenAI), RAG schema retrieval, a Redis semantic cache, AST + dry-run SQL guardrails, and a self-healing retry loop with model fallback. |
| **Anomaly Engine (FWA)** | A feature store + IsolationForest + SHAP pipeline that scores insurance claims for Fraud/Waste/Abuse, with a review queue UI for analysts. |
| **Data Governance Catalog** | Built on Dataplex Catalog, Cloud DLP, and BigQuery Policy Tags: schema/table browsing, a business glossary linked to columns, governance tags (owner/PII level/retention) with full audit history, PII detection scans, data profiling, custom data quality rules, hand-derived pipeline lineage, and **real, BigQuery-enforced column-level access control** for HIGH-PII columns, gated behind a two-person approval workflow. |

```
backend/    FastAPI app (Python)
frontend/   Next.js 14 App Router app (TypeScript)
```

---

## 1. Prerequisites

- **Python 3.11+**
- **Node.js 18+** and npm
- **Docker** (or any local Redis instance) — used for the NL2SQL semantic cache
- A **Google Cloud project** with billing enabled and a BigQuery dataset to point at
- The [gcloud CLI](https://cloud.google.com/sdk/docs/install), signed in (`gcloud auth login`)

## 2. Google Cloud setup

### 2.1 Enable APIs

```bash
gcloud config set project YOUR_PROJECT_ID

gcloud services enable \
  bigquery.googleapis.com \
  dataplex.googleapis.com \
  datacatalog.googleapis.com \
  dlp.googleapis.com \
  storage.googleapis.com
```

### 2.2 Create a service account

```bash
gcloud iam service-accounts create data-governance-backend \
  --display-name "Data Governance AI backend"

gcloud iam service-accounts keys create service-account.json \
  --iam-account data-governance-backend@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

Grant it the roles the backend needs. These are project-level for simplicity in a dev
environment — scope them down (dataset/bucket-level, narrower Dataplex/Data Catalog
roles) before using this in production:

```bash
SA="data-governance-backend@YOUR_PROJECT_ID.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:$SA" --role="roles/bigquery.admin"
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:$SA" --role="roles/dataplex.admin"
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:$SA" --role="roles/datacatalog.categoryAdmin"
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:$SA" --role="roles/dlp.user"
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:$SA" --role="roles/storage.admin"
```

- `bigquery.admin` — run queries, create feature/audit/approval tables, and set/clear
  BigQuery Policy Tags on columns (`bigquery.tables.setCategory`, which plain
  `dataEditor` does not include).
- `dataplex.admin` — create/update governance aspects, glossary terms, and data
  profile/quality scans.
- `datacatalog.categoryAdmin` — create the PII policy tag taxonomy and grant/revoke
  column readers.
- `dlp.user` — run PII detection scans.
- `storage.admin` — read/write the anomaly model artifact bucket.

Move `service-account.json` into `backend/` (it's already in `.gitignore` — never
commit it).

### 2.3 Create the artifact bucket

```bash
gcloud storage buckets create gs://YOUR_PROJECT_ID-fwa-artifacts --location=US
```

### 2.4 Get an LLM API key

The NL2SQL engine defaults to Gemini. Get a key from
[Google AI Studio](https://aistudio.google.com/apikey) — no extra GCP API needs
enabling for this. (An OpenAI key works too; see `LLM_PROVIDER` below.)

### 2.5 BigQuery dataset

Point the app at an existing BigQuery dataset (healthcare/insurance claims data, or
any dataset — the NL2SQL and catalog subsystems work against whatever tables exist
there). The Anomaly Engine specifically expects `claims`/`claim_items`-shaped tables
(see `backend/feature_store.py` for the exact source schema it reads).

## 3. Clone and install

```bash
git clone <this-repo-url> Data-Governance-AI
cd Data-Governance-AI
```

**Backend:**

```bash
cd backend
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

**Frontend:**

```bash
cd frontend
npm install
```

## 4. Configure environment variables

**Backend** — copy the example and fill in your values:

```bash
cd backend
cp .env.example .env
```

Edit `.env`:

```ini
GCP_PROJECT_ID=your-project-id
BIGQUERY_DATASET=your_dataset
GOOGLE_APPLICATION_CREDENTIALS=./service-account.json
GOOGLE_API_KEY=your-google-ai-studio-key
GCS_ARTIFACT_BUCKET=your-project-id-fwa-artifacts
```

The rest of `backend/.env.example` has sensible defaults for the Redis cache, query
guardrails, and Dataplex/Data Catalog resource names — only change them if you need
non-default naming.

**Frontend** — copy the example:

```bash
cd frontend
cp .env.local.example .env.local
```

```ini
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## 5. Start Redis

The NL2SQL semantic cache needs a Redis instance reachable at `REDIS_URL`
(default `redis://localhost:6379`):

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

## 6. Run the backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

On first startup the backend builds a RAG index over your BigQuery schema (calls the
embedding API once) and persists it to `backend/.index_store/` — subsequent restarts
load it from disk instead of rebuilding. Health check: `GET http://localhost:8000/api/v1/health`.

## 7. Run the frontend

```bash
cd frontend
npm run dev
```

Open **http://localhost:3000**.

## 8. First-time data setup

- **NL2SQL** and **Data Governance Catalog** work immediately against whatever tables
  exist in your BigQuery dataset — no seeding step. The catalog's Dataplex aspect
  types, glossary, and PII policy tag taxonomy are created automatically (idempotently)
  the first time you use each feature.
- **Anomaly Engine** needs one pipeline run to build the feature store, train the
  IsolationForest model, and score claims. Trigger it from the "Anomaly Engine" page
  in the UI, or directly:

  ```bash
  curl -X POST http://localhost:8000/api/v1/pipeline/run
  ```

  This runs in the background; poll `GET /api/v1/metrics` or watch the UI for
  completion (typically well under a minute for a moderately sized dataset).

## App routes

| Route | Subsystem |
|---|---|
| `/` | NL2SQL query interface |
| `/anomaly-engine` | FWA anomaly review queue + pipeline controls |
| `/data-catalog` | Schema browser, glossary, PII scans, quality rules, lineage, access control |

## Notes on the approval workflow

There's no authentication system in this app. "Editing as" / "Reviewing as" names
throughout the Data Governance Catalog are self-reported free text, not verified
identities — the approval gate on HIGH-PII changes is a deliberate second-look
workflow, not real access control by itself. The access control it *does* enforce is
real: once a HIGH-PII restriction is approved, BigQuery itself blocks every principal
except the ones explicitly granted as readers, including project Owners.

## Troubleshooting

- **`FileNotFoundError: GOOGLE_APPLICATION_CREDENTIALS points to a non-existent file`**
  — check the path in `backend/.env` is correct relative to where you run `uvicorn`.
- **Redis connection refused** — make sure the container from step 5 is running
  (`docker ps`).
- **403 / permission denied from Dataplex or Data Catalog calls** — double check the
  IAM roles in step 2.2 were granted to the exact service account referenced by
  `GOOGLE_APPLICATION_CREDENTIALS`.
- **CORS errors in the browser** — `API_CORS_ORIGINS` in `backend/.env` must include
  the frontend's origin (`http://localhost:3000` by default).
