# Rootle Handover API Spec

### THESE DOCS WILL ALSO LIVE IN THE KEEL PROJECT CONSOLE - SHARING WIP HERE

# Intro

How Rootle's backend hands a customer's box over to Keel: the endpoint, how to sign a request, the schema, and a TypeScript function that signs and sends it.

## What it does

When a customer accepts their indicative offer and needs a postage label, Rootle's backend sends Keel a handover with all the required info to generate the postage label.

Keel never turns a handover away for business reasons. A refusal only ever means that the request needs fixing.

## Overview

|  |  |
| --- | --- |
| Endpoint | `POST /rootle/handover`, JSON body, at most 256 KB |
| Base URL and secret | one of each per environment (staging, production), sent to you privately by Keel |
| Authentication | `x-rootle-timestamp` and `x-rootle-signature` headers, below |
| Idempotency | one box per `requestId`, however many times it is sent |
| Success | `200 {"status":"accepted"}` |

## Signing a request

**Endpoint and secret shared separately**

1. Serialise the body to a JSON string and send that string.
2. Compute the lowercase hex **HMAC-SHA256**, with the shared secret, of `<unix seconds>.<body>`.
3. Send the Unix seconds in `x-rootle-timestamp` and the signature in `x-rootle-signature`.

Keel refuses a timestamp more than 5 minutes from its own clock, so **sign every attempt afresh**, retries included.

To check your implementation: with the secret `test-secret`, the timestamp `1791100000` and this body,

```json
{"requestId":"req_8f2c","attioValuationRequestId":"vr_123","customer":{"id":"cust_42","name":"Pat Sender","email":"pat@example.com","attioPersonId":"p_789"},"address":{"line1":"1 Boar Lane","town":"Leeds","postcode":"LS1 5DA"},"photographedItem":{"category":"Watches","photoUrl":"<https://example.com/photo.jpg>"}}
```

the signature is `661a0c03c51f1f4445c6189ed36edfffec5148319d09ca7d31249d26ae1b5c12`.

## TypeScript implementation

```tsx
import { createHmac } from "node:crypto";

export type HandoverRequest = {
  requestId: string;
  attioValuationRequestId: string;
  customer: {
    id: string;
    name: string;
    email: string;
    phone?: string | null;
    attioPersonId: string;
  };
  address: {
    line1: string;
    line2?: string | null;
    town: string;
    postcode: string;
  };
  photographedItem: {
    category: string;
    photoUrl: string;
  };
  declaredCategories?: string[];
  mev?: {
    amount: number;
    low: number;
    high: number;
    currency: string;
    margin: number;
    pricingResultId: string;
  };
  labelMethod?: "qr" | "print_at_home" | "posted";
};

export type HandoverAnswer =
  | { status: "accepted" }
  | { status: "invalid"; errors: string[] }
  | { status: "rejected" | "too large" | "refused" | "error"; message: string };

export function signHandover(handover: HandoverRequest, secret: string, now: Date = new Date()) {
  // Serialise once: the bytes that are signed must be the bytes that are sent.
  const body = JSON.stringify(handover);
  const timestamp = String(Math.floor(now.getTime() / 1000));
  const signature = createHmac("sha256", secret).update(`${timestamp}.${body}`, "utf8").digest("hex");

  return {
    body,
    headers: {
      "Content-Type": "application/json",
      "x-rootle-timestamp": timestamp,
      "x-rootle-signature": signature,
    },
  };
}

export async function sendHandover(baseUrl: string, handover: HandoverRequest, secret: string) {
  const { body, headers } = signHandover(handover, secret);
  const response = await fetch(new URL("/rootle/handover", baseUrl), { method: "POST", headers, body });
  const answer = (await response.json()) as HandoverAnswer;
  return { statusCode: response.status, answer };
}
```

To retry after a network error or a `5xx`, call `sendHandover` again. It signs afresh each time, and the same `requestId` never opens a second box.

## Responses

| Status | `status` | Meaning | What to do |
| --- | --- | --- | --- |
| `200` | `accepted` | The box is open | Nothing more |
| `400` | `invalid` | Not JSON, or fields missing or the wrong type; `errors` lists every one | Fix them and send again under the same `requestId` |
| `401` | `rejected` | The timestamp is over 5 minutes out, or the signature is wrong; `message` says which | Check the secret and your clock; sign the exact bytes you send |
| `413` | `too large` | The body is over 256 KB | Send the photo as a link, not inside the body |
| `422` | `refused` | An unknown category name, or an MEV with `low` above `high` or a negative amount or margin | Fix the value and send again under the same `requestId` |
| `500` | `error` | Keel could not open the box | Send again; tell Keel if it keeps failing |

A corrected request under the same `requestId` is judged afresh, and still opens only one box.

## The photo asset

Send the photo as a link in `photographedItem.photoUrl`. Keel fetches it once and keeps its own copy, so the link must stay fetchable for **at least a day**. A signed link that expires within minutes will not work.

## Schema

OpenAPI 3.1, ready to paste into Swagger UI, Postman or a client generator.

[rootle-openapi.yaml](rootle-openapi.yaml)

```yaml
openapi: 3.1.0
info:
  title: Keel handover API for Rootle
  version: 1.0.0
servers:
  - url: "{baseUrl}"
    variables:
      baseUrl:
        default: <https://keel.example>
        description: The environment's base URL, sent by Keel.
security:
  - rootleSignature: []
paths:
  /rootle/handover:
    post:
      operationId: handOverBox
      summary: Hand a customer's box over to Keel
      parameters:
        - name: x-rootle-timestamp
          in: header
          required: true
          description: The time of sending as Unix seconds, within 5 minutes of Keel's clock.
          schema: { type: string, pattern: "^[0-9]+$" }
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: "#/components/schemas/Handover" }
            example:
              requestId: req_8f2c
              attioValuationRequestId: vr_123
              customer: { id: cust_42, name: Pat Sender, email: pat@example.com, phone: "+447700900123", attioPersonId: p_789 }
              address: { line1: 1 Boar Lane, line2: null, town: Leeds, postcode: LS1 5DA }
              photographedItem: { category: Watches, photoUrl: "<https://example.com/photo.jpg>" }
              declaredCategories: [Watches, Jewellery]
              mev: { amount: 400, low: 320, high: 480, currency: GBP, margin: 45, pricingResultId: pr_1 }
              labelMethod: print_at_home
      responses:
        "200": { description: Accepted, content: { application/json: { schema: { $ref: "#/components/schemas/Answer" } } } }
        "400": { description: Invalid, content: { application/json: { schema: { $ref: "#/components/schemas/Answer" } } } }
        "401": { description: Rejected, content: { application/json: { schema: { $ref: "#/components/schemas/Answer" } } } }
        "413": { description: Too large, content: { application/json: { schema: { $ref: "#/components/schemas/Answer" } } } }
        "422": { description: Refused, content: { application/json: { schema: { $ref: "#/components/schemas/Answer" } } } }
        "500": { description: Error, content: { application/json: { schema: { $ref: "#/components/schemas/Answer" } } } }
components:
  securitySchemes:
    rootleSignature:
      type: apiKey
      in: header
      name: x-rootle-signature
      description: Lowercase hex HMAC-SHA256 of the x-rootle-timestamp value, a full stop, then the raw body.
  schemas:
    Handover:
      type: object
      required: [requestId, attioValuationRequestId, customer, address, photographedItem]
      properties:
        requestId: { type: string, minLength: 1, description: "Your id for this handover; one box per requestId." }
        attioValuationRequestId: { type: string, minLength: 1, description: "Attio's record id for the valuation request." }
        customer:
          type: object
          required: [id, name, email, attioPersonId]
          properties:
            id: { type: string, minLength: 1, description: Your own id for the person. }
            name: { type: string, minLength: 1 }
            email: { type: string, minLength: 1 }
            phone: { type: [string, "null"] }
            attioPersonId: { type: string, minLength: 1, description: "Attio's record id for the person." }
        address:
          type: object
          description: A UK address.
          required: [line1, town, postcode]
          properties:
            line1: { type: string, minLength: 1 }
            line2: { type: [string, "null"] }
            town: { type: string, minLength: 1 }
            postcode: { type: string, minLength: 1 }
        photographedItem:
          type: object
          required: [category, photoUrl]
          properties:
            category: { $ref: "#/components/schemas/CategoryName" }
            photoUrl: { type: string, format: uri, description: "http or https; must stay fetchable for a day." }
        declaredCategories:
          type: array
          items: { $ref: "#/components/schemas/CategoryName" }
        mev:
          type: object
          description: The indicative valuation. All six fields, or leave it out.
          required: [amount, low, high, currency, margin, pricingResultId]
          properties:
            amount: { type: number, minimum: 0 }
            low: { type: number, description: At most high. }
            high: { type: number }
            currency: { type: string, minLength: 1 }
            margin: { type: number, minimum: 0 }
            pricingResultId: { type: string, minLength: 1 }
        labelMethod:
          type: string
          enum: [qr, print_at_home, posted]
          description: Optional; the office chooses if it is left out.
    CategoryName:
      type: string
      description: Matched exactly, including case and "&".
      enum:
        - Jewellery
        - Coins & Currency
        - War & Militaria
        - Camera & Optical
        - Metals
        - Watches
        - Timekeeping
        - Sporting Memorabilia
        - Collectibles & Memorabilia
        - Decorative Arts
        - Housewares & Kitchen
        - Furniture
        - Fashion
        - Toys & Games
        - Books
        - Electronic Devices
        - Other
    Answer:
      type: object
      required: [status]
      properties:
        status: { type: string, enum: [accepted, invalid, rejected, too large, refused, error] }
        errors: { type: array, items: { type: string }, description: "Sent with invalid: every field to fix." }
        message: { type: string, description: Sent with every other refusal. }
```