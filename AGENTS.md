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

## Current schema coverage

- Company / Contact
- Lead / LeadBoxDetail / LeadBoxRevision / LeadEstimate
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

## New lead flow support

- Stage 1: initial lead capture with name and phone
- Stage 2: box/item details, photos, and notes
- Stage 2 revision: follow-up record for additional photos or improved offer details
- Stage 3: final contact and delivery address collection after estimate
- Lead estimates linked to initial details or revision requests

## Next planned steps

- Refine the customer journey and decision model from your sketch
- Add pricing agent and quote automation support
- Build Slack event ingestion and messaging integration
- Add website analytics/lead capture models and API endpoints
- Expand API coverage, validation, and authentication
