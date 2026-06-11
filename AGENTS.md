# ERP Project Summary

## Objective
Build an operational ERP backbone for your business that connects:

- CRM data and customer journey tracking
- pricing and quote generation
- website event and lead data
- Slack communications and workflow integration

The long-term goal is a Python Flask API that powers the ERP and integrates with your external systems.

## What we have done so far

- Initialized a new Flask-based ERP scaffold in `/home/hughesjo/rootle_erp`
- Added a local Python virtual environment layout and `.gitignore`
- Created `app.py` with Flask app factory and API blueprint registration
- Created `config.py` for environment-backed SQLAlchemy configuration
- Created `database.py` with SQLAlchemy initialization
- Created `models.py` with the first ERP domain model schema
- Added basic CRM routes in `routes/crm.py`
- Added a `README.md` describing setup and available API endpoints
- Extended the lead workflow with stage-specific models and revision flow
- Added Attio integration support in `attio.py`
- Added CORS support for the Lovable website at `https://rootle-analytics.lovable.app`
- Added event-based website form intake for identity capture, item submissions, and contact details
- Added Attio `valuation_requests` custom object setup and ERP valuation case support
- Added valuation request queue/detail endpoints and an Attio MEV sync retry endpoint

## Current schema coverage

- Company / Contact
- Lead / LeadBoxDetail / LeadBoxRevision / LeadEstimate
- Valuation request (`valuation_requests`)
- Opportunity
- JourneyPhase and OperationalDecision
- Product / Quote / QuoteItem
- Order
- WebsiteEvent
- SlackMessage
- IntegrationLog
- FailedValuationRequestSubmission

## Database

- PostgreSQL is now the target database for the ERP
- Configuration expects `DATABASE_URL` for the Postgres connection
- Latest Alembic head is `a8b9c0d1e2f3`

## Attio integration

- Attio is the CRM capture layer for website submissions
- `ATTIO_API_KEY` is required in `.env`
- The backend uses Attio REST at `https://api.attio.com/v2`
- If `.env` contains `ATTIO_API_URL=https://api.attio.com/graphql` or an `app.attio.com` workspace URL, `attio.py` normalises it to the REST base URL
- The Attio Person object stores identity and contact/address details
- The Attio `valuation_requests` custom object stores item/photo valuation submissions
- The `valuation_requests` object includes:
  - linked `person`
  - `item_categories`
  - `item_photo_url`
  - `rootle_stage`
  - `valuation_guide_id`
  - `valuation_guide_url`
  - `rootle_posthog_distinct_id`
  - `source`
  - `stage_3_completed_at`
  - `latest_mev_amount`
  - `latest_mev_currency`
  - `latest_mev_margin`
  - `latest_mev_calculated_at`
- Valid `item_categories` are `gold`, `silver`, and `coins`

## Website form flow

The current website form model is event-based rather than stage-order dependent.

- Identity captured:
  - Endpoint: `POST /api/crm/leads/stage-1`
  - Payload: `name`, `phone_number`, `posthog_distinct_id`
  - Finds or creates an Attio Person by phone number
  - Does not create an ERP valuation case
- Item submitted:
  - Endpoint: `POST /api/crm/valuation-requests`
  - Payload: Attio person id, item categories, item photo URL, optional PostHog id and valuation guide fields
  - Creates one Attio `valuation_requests` record
  - Creates one ERP `valuation_requests` case
  - Stores valid submissions that fail Attio/ERP sync in `failed_valuation_request_submissions`
  - Failed submissions can be listed via `GET /api/crm/valuation-request-failures` and replayed via `POST /api/crm/valuation-request-failures/{id}/retry`
  - Supports one person having many valuation requests
  - Dedupes by `rootle_request_id`
- Valuation request queried:
  - Endpoint: `GET /api/crm/valuation-requests`
  - Supports pricing queue filters including `needs_mev=true`, `status`, `current_stage`, person id, Attio valuation request id, Rootle request id, `limit`, and `offset`
  - Endpoint: `GET /api/crm/valuation-requests/{valuation_id}`
  - Returns one ERP valuation case with MEV history, inbound labels, and label eligibility
- Contact details captured:
  - Endpoint: `POST /api/crm/contact-details`
  - Payload: Attio person id, email, address fields
  - Updates the Attio Person record
  - Updates matching ERP valuation request cases when they exist

The UI labels may still say stage 1, stage 2, and stage 3, but the backend should not rely on those steps arriving in a fixed order.

## MEV and margin calculations

When a valuation request is ready for pricing, the ERP can store a minimum expected valuation (MEV) and anticipated margin.

- Endpoint: `POST /api/crm/valuation-requests/{valuation_id}/mev-calculations`
- Required payload fields: `amount`, `currency`, `margin`
- Optional payload fields: `calculation_method`, `calculated_by`, `notes`, `inputs`, `metadata`
- Every calculation appends an audit row to `lead_valuation_mev_calculations`
- `valuation_requests` also stores the latest snapshot in:
  - `latest_mev_amount`
  - `latest_mev_currency`
  - `latest_mev_margin`
  - `latest_mev_calculated_at`
- The latest MEV snapshot is mirrored to the linked Attio `valuation_requests` record at calculation time
- Attio only holds the latest MEV fields; each new calculation overwrites the previous MEV values in Attio
- The ERP remains the historical source of truth for previous MEV calculations
- Endpoint: `POST /api/crm/valuation-requests/{valuation_id}/mev-sync`
- MEV sync retries mirror the latest ERP snapshot back to Attio without creating a new audit row
- MEV sync retry requires the ERP valuation to already have a latest MEV amount, currency, margin, calculated timestamp, and linked Attio valuation request id

## Next planned steps

- Refine the customer journey and decision model from your sketch
- Add pricing agent and quote automation support
- Build Slack event ingestion and messaging integration
- Connect valuation guide generation to valuation requests
- Add live Stage 2/valuation request tests against Attio or a mocked integration layer
- Expand API coverage, validation, and authentication
