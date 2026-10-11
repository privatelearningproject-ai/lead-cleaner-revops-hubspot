# Lead-Cleaner Agent Master Specification & Implementation Plan

This document serves as the system instruction set, architectural reference, and step-by-step roadmap for building the `lead-cleaner` tool in IntelliJ using the coding agent.

---

## 1. Project Summary & Core Principles

- **Project Name:** `lead-cleaner`
- **Objective:** Private CLI & Streamlit application tailored for Indian SMB lead hygiene. Ingests messy Excel/CSV files, normalizes fields (Indian phone formats, PIN codes, state lookup, GST validation, deduplication), generates audit trails, and pushes validated contacts into HubSpot.
- **Safety First:**
  - `DRY_RUN=True` by default. Never perform real HubSpot API mutations unless explicitly overridden.
  - Never discard input data: preserve all original inputs in prefixed `raw_*` columns.
  - No blind guessing on unmapped cities/states or weak deduplication matches; route ambiguous cases directly to `review.csv`.

---

## 2. Directory Layout

Ensure the project layout matches this structure:

```text
lead-cleaner/
├── .env.example
├── requirements.txt
├── config/
│   ├── mappings.yaml         # Client column aliases -> canonical schema
│   └── rules.yaml            # India city/state mappings, PIN prefixes, GST codes
├── cleaner/
│   ├── __init__.py
│   ├── loader.py             # File ingestion, encoding detection (UTF-8 / Windows-1252)
│   ├── normalize.py          # Field-level normalization (Phone, Name, Email, PIN, GST)
│   ├── validate.py           # Integrity rules, missing required fields, issue tagging
│   ├── dedupe.py             # Hierarchy: Phone -> Email -> Fuzzy Name+City (>90)
│   ├── enrich.py             # Optional local LLM extraction (Ollama Qwen 14B)
│   ├── hubspot.py            # HubSpot v3 API upsert, search, backoff & dry-run handlers
│   ├── report.py             # Lead scoring (0-100), report.md, cleaned.csv, review.csv
│   ├── pipeline.py           # Core orchestrator running steps 1 through 6/7
│   └── db.py                 # SQLite run logs & immutable audit events
├── app.py                    # Streamlit UI: review, interactive audit, push approval
└── tests/
    ├── fixtures/
    │   └── messy_leads.csv   # 50 realistic Indian lead variations
    ├── test_normalize.py
    ├── test_dedupe.py
    └── test_validate.py
```

---

## 3. Configuration & Schema Specifications

### 3.1 Standard Canonical Schema
Every row passed through the pipeline must preserve its original values while producing standard output columns:

| Output Column | Type | Normalization Rule |
| :--- | :--- | :--- |
| `raw_*` | string | Untouched copies of all loaded incoming columns |
| `first_name` | string | Stripped, title-cased. No spelling adjustments or transliteration |
| `last_name` | string | Stripped, title-cased |
| `email` | string | Stripped, lowercased, validated against RFC 5322 regex. If invalid, flag for review |
| `phone` | string | E.164 standard (`+91XXXXXXXXXX`), 10-digit mobile starting with 6–9 |
| `company` | string | Stripped, trimmed excess whitespace |
| `city` | string | Normalized against `rules.yaml`. Unknowns flagged for review |
| `state` | string | Normalized against `rules.yaml` or inferred from valid PIN prefix |
| `pin_code` | string | 6 digits, first digit 1–9 |
| `gst_number` | string | 15 alphanumeric characters. First 2 digits match state code |
| `consent_source` | string | Source identifier or tagged as `consent_missing` |
| `consent_date` | string | ISO format `YYYY-MM-DD` |
| `source` | string | Originating filename |
| `notes_raw` | string | Unprocessed user notes |
| `notes_structured`| JSON string | Optional LLM extracted payload (budget, intent, etc.) |

---

## 4. Phase-by-Phase Build Instructions for Agent

Follow these sequential steps. **Do not begin a subsequent step until the current step passes all unit and integration tests.**

### Step 1: Normalizer (`cleaner/normalize.py` & `tests/test_normalize.py`)
- **Phone Normalization:**
  - Strip spaces, parentheses, hyphens, and leading zero.
  - Drop leading `91` or `+91`.
  - Validate exact 10 digits starting with digits `6, 7, 8, 9`.
  - Valid output: `+91` followed by 10 digits. Else mark `phone_invalid` -> review.
- **PIN Code & State Lookup:**
  - Regex: `^[1-9][0-9]{5}$`.
  - If `state` is empty, query first 2 digits against `pin_prefixes` in `rules.yaml`.
- **GST Validation:**
  - Regex: `^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$`.
  - Verify state code digits match `gst_state_codes` in `rules.yaml`.

### Step 2: Loader & Column Mapping (`cleaner/loader.py`, `config/mappings.yaml`)
- Read `.csv` or `.xlsx`.
- Encodings: Try `utf-8` first; fall back to `windows-1252` (common for Excel CSV exports).
- Prefix all source columns with `raw_`.
- Match client column variations to canonical fields using case-insensitive lookup in `mappings.yaml`.

### Step 3: Validation & Reporting (`cleaner/validate.py`, `cleaner/report.py`, `cleaner/db.py`)
- Calculate quality score ($0 \le \text{Score} \le 100$):
  - Deduct points for missing email/phone, invalid GST, missing consent, or unmapped city.
- Flag leads with missing `consent_source` as `consent_missing` (do not drop, but flag for marketing exclusion).
- `db.py`: SQLite audit logging recording run timestamps, rows processed, error counters, and user actions.
- Produce `cleaned.csv`, `review.csv`, and an analytical markdown summary `report.md`.

### Step 4: Deduplication Engine (`cleaner/dedupe.py`, `tests/test_dedupe.py`)
- Execute matching strictly in this order:
  1. Exact match on normalized `phone`.
  2. Exact match on normalized `email`.
  3. Fuzzy match: Name similarity + identical city using `rapidfuzz.fuzz.token_sort_ratio > 90`.
- **Crucial Rule:** Fuzzy matches must always go to `review.csv` as proposed merges. Never auto-merge on name alone.

### Step 5: Pipeline Integration (`cleaner/pipeline.py`)
- Orchestrate loader -> mapper -> normalizer -> validator -> dedupe -> reporter.
- Verify end-to-end processing against `tests/fixtures/messy_leads.csv`.

### Step 6: HubSpot CRM Integration (`cleaner/hubspot.py`)
- Read `HUBSPOT_TOKEN` from `.env`.
- Implement exponential backoff for HTTP 429 and 5xx responses.
- Upsert logic:
  1. Search contact by `email`.
  2. If not found, search by `phone`.
  3. If exists: **Fill empty properties only**. Never overwrite existing non-null HubSpot properties unless `OVERWRITE_EXISTING=True`.
  4. If new: Create record with `lead_source` set to the input filename.
- If `dry_run=True`, log payload and simulate call without network writes.

### Step 7: Streamlit User Interface (`app.py`)
- Allow file drag-and-drop (`.csv`, `.xlsx`).
- Show data quality score, summary metrics, and review warnings.
- Interactive table to review merge proposals and manual overrides.
- Explicit "Push to HubSpot" action with a safety toggle requiring the user to disable dry-run.

### Step 8: Optional Enrichment (`cleaner/enrich.py`)
- Feature-flagged (`ENRICHMENT_ENABLED=False` default).
- Calls local Ollama endpoint (`http://localhost:11434/api/generate`) targeting Qwen 14B.
- Extracts `budget`, `product_interest`, `city` from `notes_raw`. Validates JSON output strictly.

---

## 5. Sample Test Fixture (`tests/fixtures/messy_leads.csv`)

Create this fixture file to test against Indian edge cases:

```csv
Full Name,Contact Number,Email Address,Town,State Name,Pincode,GSTIN,Consent Source,Notes
Aarav Sharma,09820012345,aarav.sharma@example.com,Bombay,MH,400001,27ABCDE1234F1Z5,Website Form,Looking for enterprise plan under 5 lakhs
Aarav Sharma,+91 98200 12345,aarav.s@work.com,Mumbai,Maharashtra,400001,27ABCDE1234F1Z5,,Duplicate contact with different email
Priya Patel,98765-43210,priya.patel@test.co.in,GGN,,122002,06AAAAA0000A1Z5,Event booth,Met at Delhi Expo
Priya Patel,9876543210,priyap@gmail.com,Gurgaon,Haryana,122002,,Inbound WhatsApp,Urgent inquiry for software licenses
Vikram Malhotra,8123456789,VIKRAM@VENTURES.COM,Bangalore,Karnataka,560001,29ABCDE1234F1Z5,Cold Call,Interested in 10 user seats
Vikram Malhotra,8123456789,vikram@ventures.com,Bengaluru,KA,560001,,,Duplicate lead
Ananya Gupta,919123456780,ananya.g@guptafoods.com,Calcutta,West Bengal,700001,19AAAAA1111A1Z5,Meta Lead Ad,Budget around 2L
Rajesh Kumar,12345,bad-email,Patna,Bihar,800001,,,Invalid phone and email test
Sunita Rao,9988776655,sunita@hyderabadtech.in,Secunderabad,Telangana,500003,36AAAAA1234A1Z5,Organic Search,Needs quote
Deepak Verma,+91-7890123456,deepak.verma@domain.com,Noida,UP,201301,09AAAAA9999A1Z5,Referral,Wants product demo next Monday
```

---

## 6. Default Rules Reference (`config/rules.yaml`)

```yaml
city_aliases:
  bombay: "Mumbai"
  mumbai: "Mumbai"
  ggn: "Gurugram"
  gurgaon: "Gurugram"
  gurugram: "Gurugram"
  bangalore: "Bengaluru"
  bengaluru: "Bengaluru"
  calcutta: "Kolkata"
  kolkata: "Kolkata"
  madras: "Chennai"
  chennai: "Chennai"
  secunderabad: "Hyderabad"
  hyderabad: "Hyderabad"

state_aliases:
  mh: "Maharashtra"
  up: "Uttar Pradesh"
  ka: "Karnataka"
  wb: "West Bengal"
  dl: "Delhi"
  hr: "Haryana"
  ts: "Telangana"

pin_prefixes:
  "11": "Delhi"
  "12": "Haryana"
  "13": "Haryana"
  "20": "Uttar Pradesh"
  "21": "Uttar Pradesh"
  "22": "Uttar Pradesh"
  "27": "Maharashtra"
  "40": "Maharashtra"
  "56": "Karnataka"
  "70": "West Bengal"
  "50": "Telangana"
  "80": "Bihar"

gst_state_codes:
  "06": "Haryana"
  "07": "Delhi"
  "09": "Uttar Pradesh"
  "19": "West Bengal"
  "27": "Maharashtra"
  "29": "Karnataka"
  "36": "Telangana"
```

---

## 7. Verification Checklist Before Step Approval

- [ ] All phone inputs standardize to `+91` followed by 10 digits starting with 6–9.
- [ ] Unknown cities/states remain unchanged in `raw_*` and flag the row into `review.csv` rather than being blindly guessed.
- [ ] No external API requests are sent when `DRY_RUN=True`.
- [ ] In-memory merges never discard raw attributes.
- [ ] SQLite audit table logs every transformation and push event.