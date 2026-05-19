# Rootle ERP

A lightweight ERP backbone for CRM, pricing, website data, and Slack integration.

## What is included

- Flask API scaffold in `app.py`
- SQLAlchemy database setup in `database.py`
- ERP domain model in `models.py`
- CRM blueprint in `routes/crm.py`
- Configuration via `config.py`

## Initial database shape

The current schema includes:

- `Company`
- `Contact`
- `JourneyPhase`
- `OperationalDecision`
- `Opportunity`
- `Product`
- `Quote` / `QuoteItem`
- `Order`
- `WebsiteEvent`
- `SlackMessage`
- `IntegrationLog`

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql+psycopg://user:password@localhost:5432/erp"
python app.py
```

The API will start on `http://127.0.0.1:5000`.

## Example endpoints

- `GET /api/companies`
- `GET /api/companies/<id>`
- `POST /api/companies`
- `GET /api/journey-phases`
