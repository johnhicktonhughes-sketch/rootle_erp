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
- `POST /api/crm/leads/stage-1`
- `GET /api/crm/valuation-requests`
- `POST /api/crm/valuation-requests`
- `GET /api/crm/valuation-requests/<id>`
- `POST /api/crm/contact-details`
- `POST /api/webhooks/attio`

### Website form stage 1

The website form should send stage 1 submissions to Attio through the ERP API, without
creating an ERP lead record yet.

```http
POST /api/crm/leads/stage-1
```

```json
{
  "name": "Jane Smith",
  "phone_number": "+447123456789",
  "posthog_distinct_id": "0192..."
}
```

The response includes the Attio record id and confirms that no ERP lead was created:

```json
{
  "crm_system": "attio",
  "attio_id": "record-id",
  "crm_record_id": "record-id",
  "stage": "stage-1",
  "erp_lead_created": false,
  "attio_record_created": false
}
```

If a person already exists in Attio with the submitted phone number, the API returns
the existing `crm_record_id` with a `200` response and does not create or update a
duplicate record. New Attio records return `201`.

### Attio valuation request object

Stage 2 submissions should be stored in a custom Attio object called
`valuation_requests`. The repo includes an idempotent setup helper:

```bash
python -c "from attio import ensure_valuation_request_object; print(ensure_valuation_request_object())"
```

It creates the `Valuation Request` object with attributes for:

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

### Item submission / valuation request

When the customer submits item categories and a photo, the ERP creates a valuation
case and Attio gets a linked `valuation_requests` record.

```http
POST /api/crm/valuation-requests
```

```json
{
  "attio_id": "person-record-id",
  "items": ["gold", "coins"],
  "picture_url": "https://example.com/item.jpg",
  "posthog_distinct_id": "0192...",
  "rootle_request_id": "optional-client-id"
}
```

Aliases are accepted:

- `item_categories` or `items`
- `item_photo_url`, `picture_url`, or `photo_url`
- `attio_id`, `crm_person_record_id`, or `crm_record_id`

Each item submission creates its own ERP `lead_valuations` record and its own Attio
`valuation_requests` record. Reusing the same `rootle_request_id` merges any newly
submitted item categories into the existing ERP valuation instead of creating a
duplicate.

### Attio deletion sync

Configure an Attio `record.deleted` webhook with this target URL:

```http
POST /api/webhooks/attio
```

Set `ATTIO_WEBHOOK_SECRET` in `.env` to the webhook secret from Attio. When a
deleted Attio record id matches `lead_valuations.crm_valuation_request_id`, the
ERP deletes the matching `lead_valuations` row. Optionally set
`ATTIO_VALUATION_REQUEST_OBJECT_ID` to the Attio object id for
`valuation_requests` so unrelated Attio record deletes are ignored before the
database lookup.

### Contact details

Email and address can arrive before or after item submission. These details update
the Attio person record and any matching ERP valuation cases.

```http
POST /api/crm/contact-details
```

```json
{
  "attio_id": "person-record-id",
  "email": "jane@example.com",
  "address_line_1": "1 Street",
  "city": "London",
  "postcode": "SW1A 1AA",
  "country": "GB"
}
```

### MEV calculations

After an item submission creates a `lead_valuations` row, pricing can store an MEV
calculation against that valuation:

```http
POST /api/crm/valuation-requests/{valuation_id}/mev-calculations
```

```json
{
  "amount": 100.00,
  "currency": "GBP",
  "margin": 0.25,
  "calculation_method": "manual",
  "calculated_by": "pricing-agent",
  "inputs": {
    "guide_price": 125.00
  }
}
```

Every call appends a row to `lead_valuation_mev_calculations`. The latest amount,
currency, margin, and calculation timestamp are also stored on `lead_valuations`
and mirrored to the linked Attio `valuation_requests` record.

Pricing workers can list ERP valuation cases that are waiting for an MEV:

```http
GET /api/crm/valuation-requests?needs_mev=true
```

Supported filters include `status`, `current_stage`, `needs_mev`,
`attio_id`/`crm_person_record_id`, `crm_valuation_request_id`,
`rootle_request_id`, `limit`, and `offset`.

One valuation case can be fetched with:

```http
GET /api/crm/valuation-requests/{valuation_id}
```

If the latest ERP MEV snapshot needs to be sent to Attio again without creating a
new audit calculation row, call:

```http
POST /api/crm/valuation-requests/{valuation_id}/mev-sync
```

The sync retry requires `latest_mev_amount`, `latest_mev_currency`,
`latest_mev_margin`, and `latest_mev_calculated_at` to already exist on the ERP
valuation.

### Inbound labels

When a valuation has a latest GBP MEV above 100.00, the ERP can create one active
inbound label for that valuation. Labels are local ERP records first; Attio label
sync can be added later as a projection.

```http
POST /api/crm/valuation-requests/{valuation_id}/inbound-labels
```

```json
{
  "label_url": "https://example.com/label.pdf",
  "tracking_number": "AA123456789GB"
}
```

The response includes a `barcode_value` and `qr_payload`. The QR payload points at
the scan endpoint and resolves back to the person, valuation request, expected
item categories, and submitted item photo:

```http
POST /api/crm/inbound-labels/scan/{barcode_value}
```

MEV above 10000.00 GBP defaults to a `white_glove` dispatch method with
`white_glove_required=true`. Courier and service values can be overridden in the
label creation payload while the policy layer is still simple.
