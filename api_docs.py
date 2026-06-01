API_TITLE = "Rootle ERP API"
API_VERSION = "0.2.0"


SWAGGER_UI_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Rootle ERP API Docs</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
  <style>
    html {
      box-sizing: border-box;
      overflow-y: scroll;
    }
    *, *::before, *::after {
      box-sizing: inherit;
    }
    body {
      margin: 0;
      background: #f7f8fa;
    }
    .swagger-ui .topbar {
      display: none;
    }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
  <script>
    window.addEventListener("load", function () {
      window.ui = SwaggerUIBundle({
        url: "/openapi.json",
        dom_id: "#swagger-ui",
        deepLinking: true,
        displayRequestDuration: true,
        filter: true,
        persistAuthorization: true,
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIStandalonePreset
        ],
        layout: "StandaloneLayout"
      });
    });
  </script>
</body>
</html>
"""


OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": API_TITLE,
        "version": API_VERSION,
        "description": (
            "Operational ERP API for CRM capture, valuation requests, "
            "customer contact details, and early internal ERP records."
        ),
    },
    "servers": [{"url": "/"}],
    "components": {
        "securitySchemes": {
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
            },
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
            },
        },
        "schemas": {
            "Error": {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                    "message": {"type": "string"},
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
    },
    "security": [{"ApiKeyAuth": []}, {"BearerAuth": []}],
    "paths": {
        "/": {
            "get": {
                "summary": "Health check",
                "security": [],
                "responses": {"200": {"description": "Service status"}},
            }
        },
        "/api/companies": {
            "get": {
                "summary": "List companies",
                "responses": {"200": {"description": "Company list"}},
            },
            "post": {
                "summary": "Create a company",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name"],
                                "properties": {
                                    "name": {"type": "string"},
                                    "domain": {"type": "string"},
                                    "website": {"type": "string"},
                                    "industry": {"type": "string"},
                                    "status": {"type": "string"},
                                    "source": {"type": "string"},
                                    "crm_external_id": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                            }
                        }
                    },
                },
                "responses": {"201": {"description": "Company created"}},
            },
        },
        "/api/companies/{company_id}": {
            "get": {
                "summary": "Get a company with contacts and opportunities",
                "parameters": [
                    {
                        "name": "company_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {"200": {"description": "Company details"}},
            }
        },
        "/api/journey-phases": {
            "get": {
                "summary": "List customer journey phases",
                "responses": {"200": {"description": "Journey phase list"}},
            }
        },
        "/api/leads": {
            "get": {
                "summary": "List legacy ERP leads",
                "responses": {"200": {"description": "Lead list"}},
            },
            "post": {
                "summary": "Create a legacy ERP lead",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "first_name": {"type": "string"},
                                    "last_name": {"type": "string"},
                                    "phone": {"type": "string"},
                                    "email": {"type": "string"},
                                    "source": {"type": "string"},
                                    "preferred_contact_method": {"type": "string"},
                                    "crm_record_id": {"type": "string"},
                                    "metadata": {"type": "object"},
                                    "status": {"type": "string"},
                                    "stage": {"type": "string"},
                                },
                            }
                        }
                    },
                },
                "responses": {"201": {"description": "Lead created"}},
            },
        },
        "/api/leads/{lead_id}": {
            "get": {
                "summary": "Get a legacy ERP lead",
                "parameters": [
                    {
                        "name": "lead_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {"200": {"description": "Lead details"}},
            }
        },
        "/api/crm/leads/stage-1": {
            "post": {
                "summary": "Capture website identity details in Attio",
                "description": "Finds or creates an Attio Person by phone number. Does not create an ERP lead.",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name", "phone_number", "posthog_distinct_id"],
                                "properties": {
                                    "name": {"type": "string"},
                                    "phone_number": {"type": "string"},
                                    "posthog_distinct_id": {"type": "string"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Existing Attio person found"},
                    "201": {"description": "Attio person created"},
                    "400": {"description": "Missing required fields"},
                    "502": {"description": "Attio sync failed"},
                },
            }
        },
        "/api/crm/valuation-requests": {
            "post": {
                "summary": "Create a valuation request",
                "description": "Creates one ERP LeadValuation and one linked Attio valuation_requests record. Valid item values come from GET /api/crm/valuation-items.",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["attio_id", "items", "picture_url"],
                                "properties": {
                                    "attio_id": {"type": "string"},
                                    "crm_person_record_id": {"type": "string"},
                                    "crm_record_id": {"type": "string"},
                                    "items": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "item_categories": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "picture_url": {"type": "string"},
                                    "item_photo_url": {"type": "string"},
                                    "photo_url": {"type": "string"},
                                    "posthog_distinct_id": {"type": "string"},
                                    "rootle_request_id": {"type": "string"},
                                    "source": {"type": "string"},
                                    "valuation_guide_id": {"type": "string"},
                                    "valuation_guide_url": {"type": "string"},
                                    "metadata": {"type": "object"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Duplicate request id returned existing valuation"},
                    "201": {"description": "Valuation request created"},
                    "400": {"description": "Invalid payload"},
                    "502": {"description": "Attio sync failed"},
                },
            }
        },
        "/api/crm/valuation-requests/{valuation_id}/mev-calculations": {
            "post": {
                "summary": "Create an MEV calculation",
                "description": "Stores an auditable MEV calculation, updates the latest MEV snapshot on the ERP valuation, and mirrors the latest values to Attio.",
                "parameters": [
                    {
                        "name": "valuation_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["amount", "currency", "margin"],
                                "properties": {
                                    "amount": {"type": "number"},
                                    "currency": {"type": "string"},
                                    "margin": {"type": "number"},
                                    "calculation_method": {"type": "string"},
                                    "calculated_by": {"type": "string"},
                                    "notes": {"type": "string"},
                                    "inputs": {"type": "object"},
                                    "metadata": {"type": "object"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "201": {"description": "MEV calculation created"},
                    "400": {"description": "Invalid payload"},
                    "404": {"description": "Valuation not found"},
                    "502": {"description": "Attio sync failed"},
                },
            }
        },
        "/api/crm/valuation-requests/{valuation_id}/inbound-labels": {
            "post": {
                "summary": "Create an inbound label",
                "description": "Creates or returns the active ERP inbound label for a valuation. Requires latest GBP MEV above 100 unless force=true is supplied.",
                "parameters": [
                    {
                        "name": "valuation_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "requestBody": {
                    "required": False,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "label_url": {"type": "string"},
                                    "tracking_number": {"type": "string"},
                                    "courier": {"type": "string"},
                                    "service_level": {"type": "string"},
                                    "dispatch_method": {"type": "string"},
                                    "destination_country": {"type": "string"},
                                    "force": {"type": "boolean"},
                                    "metadata": {"type": "object"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Existing active label returned"},
                    "201": {"description": "Inbound label created"},
                    "400": {"description": "Valuation not eligible for a label"},
                    "404": {"description": "Valuation not found"},
                },
            }
        },
        "/api/crm/inbound-labels/{rootle_label_id}": {
            "get": {
                "summary": "Get an inbound label",
                "parameters": [
                    {
                        "name": "rootle_label_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {"200": {"description": "Inbound label details"}},
            },
            "patch": {
                "summary": "Update an inbound label",
                "parameters": [
                    {
                        "name": "rootle_label_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {"200": {"description": "Inbound label updated"}},
            },
        },
        "/api/crm/inbound-labels/scan/{barcode_value}": {
            "get": {
                "summary": "Resolve an inbound label scan",
                "parameters": [
                    {
                        "name": "barcode_value",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {"200": {"description": "Label and valuation context"}},
            },
            "post": {
                "summary": "Mark an inbound label as scanned",
                "parameters": [
                    {
                        "name": "barcode_value",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {"200": {"description": "Label scan recorded"}},
            },
        },
        "/api/crm/valuation-items": {
            "get": {
                "summary": "List valid valuation item categories",
                "parameters": [
                    {
                        "name": "include_inactive",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "boolean"},
                    }
                ],
                "responses": {"200": {"description": "Valuation item category list"}},
            },
            "post": {
                "summary": "Add or reactivate a valuation item category",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name"],
                                "properties": {
                                    "name": {"type": "string"},
                                    "label": {"type": "string"},
                                    "description": {"type": "string"},
                                    "sort_order": {"type": "integer"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Existing item reactivated or updated"},
                    "201": {"description": "Item created"},
                    "400": {"description": "Invalid payload"},
                    "502": {"description": "Attio item category option sync failed"},
                },
            },
        },
        "/api/crm/valuation-items/{item_name}": {
            "delete": {
                "summary": "Remove a valuation item category from the active list",
                "parameters": [
                    {
                        "name": "item_name",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {"200": {"description": "Item removed"}},
            }
        },
        "/api/crm/contact-details": {
            "post": {
                "summary": "Capture customer contact details",
                "description": "Updates Attio Person details and matching ERP valuation cases.",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["attio_id"],
                                "properties": {
                                    "attio_id": {"type": "string"},
                                    "crm_person_record_id": {"type": "string"},
                                    "crm_record_id": {"type": "string"},
                                    "attio_valuation_request_id": {"type": "string"},
                                    "crm_valuation_request_id": {"type": "string"},
                                    "email": {"type": "string"},
                                    "address_line_1": {"type": "string"},
                                    "address_line_2": {"type": "string"},
                                    "city": {"type": "string"},
                                    "postcode": {"type": "string"},
                                    "country": {"type": "string"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Contact details updated"},
                    "400": {"description": "Invalid payload"},
                    "502": {"description": "Attio sync failed"},
                },
            }
        },
        "/api/webhooks/attio": {
            "post": {
                "summary": "Receive Attio webhook events",
                "description": "Deletes matching ERP LeadValuation rows when Attio sends record.deleted events for valuation_requests records.",
                "security": [],
                "parameters": [
                    {
                        "name": "Attio-Signature",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {
                    "200": {"description": "Webhook processed"},
                    "401": {"description": "Invalid webhook signature"},
                },
            }
        },
        "/api/leads/{lead_id}/box-details": {
            "post": {
                "summary": "Add legacy box details to a lead",
                "parameters": [
                    {
                        "name": "lead_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {"201": {"description": "Box detail created"}},
            }
        },
        "/api/leads/{lead_id}/box-details/{box_detail_id}/revisions": {
            "post": {
                "summary": "Add a legacy box detail revision",
                "parameters": [
                    {
                        "name": "lead_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    },
                    {
                        "name": "box_detail_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    },
                ],
                "responses": {"201": {"description": "Revision created"}},
            }
        },
        "/api/leads/{lead_id}/estimates": {
            "post": {
                "summary": "Create a legacy lead estimate",
                "parameters": [
                    {
                        "name": "lead_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {"201": {"description": "Estimate created"}},
            }
        },
    },
}


DOCS_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Rootle ERP API Docs</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17201d;
      --muted: #5f6f69;
      --line: #d9e2de;
      --panel: #f7faf8;
      --accent: #1f7a5a;
      --warn: #a14921;
      --code: #10231d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: #ffffff;
      line-height: 1.55;
    }
    header {
      border-bottom: 1px solid var(--line);
      background: #f3f7f5;
    }
    .wrap {
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
    }
    header .wrap {
      padding: 28px 0 22px;
    }
    h1 {
      margin: 0 0 8px;
      font-size: clamp(28px, 5vw, 44px);
      line-height: 1.05;
      letter-spacing: 0;
    }
    h2 {
      margin: 34px 0 14px;
      font-size: 24px;
      letter-spacing: 0;
    }
    h3 {
      margin: 0;
      font-size: 18px;
      letter-spacing: 0;
    }
    p {
      margin: 0 0 14px;
      color: var(--muted);
    }
    main {
      padding: 26px 0 52px;
    }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-top: 18px;
    }
    .button {
      display: inline-flex;
      align-items: center;
      min-height: 38px;
      padding: 8px 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      color: var(--ink);
      background: #fff;
      text-decoration: none;
      font-weight: 650;
    }
    .button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }
    .note {
      padding: 14px 16px;
      border: 1px solid #f1d0be;
      border-left: 4px solid var(--warn);
      border-radius: 6px;
      background: #fff8f4;
      color: #5c2c18;
      margin: 18px 0 8px;
    }
    .endpoint {
      border-top: 1px solid var(--line);
      padding: 18px 0;
      display: grid;
      grid-template-columns: 116px minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }
    .method {
      display: inline-flex;
      justify-content: center;
      align-items: center;
      width: 76px;
      min-height: 32px;
      border-radius: 4px;
      font-weight: 800;
      font-size: 13px;
      color: #fff;
      background: #51615c;
    }
    .get { background: #2670a8; }
    .post { background: #1f7a5a; }
    .delete { background: #a14921; }
    code, pre {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      color: var(--code);
    }
    code {
      overflow-wrap: anywhere;
    }
    pre {
      margin: 12px 0 0;
      padding: 12px;
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      font-size: 13px;
    }
    .path {
      font-weight: 750;
      overflow-wrap: anywhere;
    }
    .meta {
      color: var(--muted);
      margin-top: 4px;
    }
    @media (max-width: 700px) {
      .endpoint {
        grid-template-columns: 1fr;
        gap: 8px;
      }
    }
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <h1>Rootle ERP API</h1>
      <p>CRM capture, valuation requests, contact details, and early ERP records.</p>
      <div class="toolbar">
        <a class="button primary" href="/openapi.json">OpenAPI JSON</a>
        <a class="button" href="/">Health Check</a>
      </div>
    </div>
  </header>
  <main class="wrap">
    <section>
      <h2>Authentication</h2>
      <p>Operational API routes under <code>/api</code> require an API key when <code>ROOTLE_API_KEY</code> is configured.</p>
      <pre>X-API-Key: your-api-key</pre>
      <p>Bearer tokens are also accepted:</p>
      <pre>Authorization: Bearer your-api-key</pre>
      <div class="note">Do not put live credentials in browser-visible code. Website calls should use a server-side proxy or a narrowly scoped public intake key strategy before broad production use.</div>
    </section>

    <section>
      <h2>Website Flow</h2>
      <article class="endpoint">
        <span class="method post">POST</span>
        <div>
          <h3><code>/api/crm/leads/stage-1</code></h3>
          <p class="meta">Capture name, phone number, and PostHog ID in Attio. Does not create an ERP lead.</p>
          <pre>{
  "name": "Jane Smith",
  "phone_number": "+447123456789",
  "posthog_distinct_id": "0192..."
}</pre>
        </div>
      </article>
      <article class="endpoint">
        <span class="method post">POST</span>
        <div>
          <h3><code>/api/crm/valuation-requests</code></h3>
          <p class="meta">Create a linked Attio valuation request and ERP LeadValuation. Valid items come from <code>/api/crm/valuation-items</code>.</p>
          <pre>{
  "attio_id": "person-record-id",
  "items": ["gold", "coins"],
  "picture_url": "https://example.com/item.jpg",
  "posthog_distinct_id": "0192...",
  "rootle_request_id": "optional-client-id"
}</pre>
        </div>
      </article>
      <article class="endpoint">
        <span class="method post">POST</span>
        <div>
          <h3><code>/api/crm/valuation-requests/{valuation_id}/mev-calculations</code></h3>
          <p class="meta">Store an audited MEV calculation and mirror the latest amount, currency, margin, and timestamp to Attio.</p>
          <pre>{
  "amount": 100.00,
  "currency": "GBP",
  "margin": 0.25,
  "calculation_method": "manual",
  "calculated_by": "pricing-agent"
}</pre>
        </div>
      </article>
      <article class="endpoint">
        <span class="method post">POST</span>
        <div>
          <h3><code>/api/crm/valuation-requests/{valuation_id}/inbound-labels</code></h3>
          <p class="meta">Create or return the active ERP inbound label for a valuation with latest GBP MEV above 100.</p>
          <pre>{
  "label_url": "https://example.com/label.pdf",
  "tracking_number": "AA123456789GB"
}</pre>
        </div>
      </article>
      <article class="endpoint">
        <span class="method post">POST</span>
        <div>
          <h3><code>/api/crm/inbound-labels/scan/{barcode_value}</code></h3>
          <p class="meta">Record a label scan and resolve the person, valuation, expected items, and submitted photo.</p>
        </div>
      </article>
      <article class="endpoint">
        <span class="method get">GET</span>
        <div>
          <h3><code>/api/crm/inbound-labels/{rootle_label_id}</code></h3>
          <p class="meta">Get inbound label details and linked valuation context. Use PATCH on the same path to update status or courier fields.</p>
        </div>
      </article>
      <article class="endpoint">
        <span class="method get">GET</span>
        <div>
          <h3><code>/api/crm/valuation-items</code></h3>
          <p class="meta">List active item categories that can be submitted for valuation.</p>
        </div>
      </article>
      <article class="endpoint">
        <span class="method post">POST</span>
        <div>
          <h3><code>/api/crm/valuation-items</code></h3>
          <p class="meta">Add or reactivate an item category.</p>
          <pre>{
  "name": "watches",
  "label": "Watches",
  "sort_order": 3
}</pre>
        </div>
      </article>
      <article class="endpoint">
        <span class="method delete">DELETE</span>
        <div>
          <h3><code>/api/crm/valuation-items/{item_name}</code></h3>
          <p class="meta">Remove an item category from the active submission list.</p>
        </div>
      </article>
      <article class="endpoint">
        <span class="method post">POST</span>
        <div>
          <h3><code>/api/webhooks/attio</code></h3>
          <p class="meta">Receive Attio <code>record.deleted</code> events and delete matching ERP valuation cases. Requires <code>ATTIO_WEBHOOK_SECRET</code>.</p>
        </div>
      </article>
      <article class="endpoint">
        <span class="method post">POST</span>
        <div>
          <h3><code>/api/crm/contact-details</code></h3>
          <p class="meta">Update the Attio Person and matching ERP valuation cases with email and address details.</p>
          <pre>{
  "attio_id": "person-record-id",
  "email": "jane@example.com",
  "address_line_1": "1 Street",
  "city": "London",
  "postcode": "SW1A 1AA",
  "country": "GB"
}</pre>
        </div>
      </article>
    </section>

    <section>
      <h2>ERP Records</h2>
      <article class="endpoint"><span class="method get">GET</span><div><h3><code>/api/companies</code></h3><p class="meta">List companies.</p></div></article>
      <article class="endpoint"><span class="method post">POST</span><div><h3><code>/api/companies</code></h3><p class="meta">Create a company.</p></div></article>
      <article class="endpoint"><span class="method get">GET</span><div><h3><code>/api/companies/{id}</code></h3><p class="meta">Get a company with contacts and opportunities.</p></div></article>
      <article class="endpoint"><span class="method get">GET</span><div><h3><code>/api/journey-phases</code></h3><p class="meta">List journey phases.</p></div></article>
      <article class="endpoint"><span class="method get">GET</span><div><h3><code>/api/leads</code></h3><p class="meta">List legacy ERP leads.</p></div></article>
      <article class="endpoint"><span class="method post">POST</span><div><h3><code>/api/leads</code></h3><p class="meta">Create a legacy ERP lead.</p></div></article>
      <article class="endpoint"><span class="method get">GET</span><div><h3><code>/api/leads/{id}</code></h3><p class="meta">Get a legacy ERP lead with box details and estimates.</p></div></article>
    </section>
  </main>
</body>
</html>
"""
