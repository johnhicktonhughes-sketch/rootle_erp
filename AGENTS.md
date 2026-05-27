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

## Current schema coverage

- Company / Contact
- Lead / LeadBoxDetail / LeadBoxRevision / LeadEstimate
- LeadValuation
- Opportunity
- JourneyPhase and OperationalDecision
- Product / Quote / QuoteItem
- Order
- WebsiteEvent
- SlackMessage
- IntegrationLog

## Database

- PostgreSQL is now the target database for the ERP
- Configuration expects `DATABASE_URL` for the Postgres connection
- Latest Alembic head is `a1b2c3d4e5f6`

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
  - Creates one ERP `LeadValuation` case
  - Supports one person having many valuation requests
  - Dedupes by `rootle_request_id`
- Contact details captured:
  - Endpoint: `POST /api/crm/contact-details`
  - Payload: Attio person id, email, address fields
  - Updates the Attio Person record
  - Updates matching ERP `LeadValuation` cases when they exist

The UI labels may still say stage 1, stage 2, and stage 3, but the backend should not rely on those steps arriving in a fixed order.

## Next planned steps

- Refine the customer journey and decision model from your sketch
- Add pricing agent and quote automation support
- Build Slack event ingestion and messaging integration
- Connect valuation guide generation to `LeadValuation`
- Add live Stage 2/valuation request tests against Attio or a mocked integration layer
- Expand API coverage, validation, and authentication
