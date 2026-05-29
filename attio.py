import os
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from database import db
from models import IntegrationLog, Lead

load_dotenv(Path(__file__).resolve().parent / ".env")


def _normalise_attio_api_base_url(url: str | None) -> str:
    if not url:
        return "https://api.attio.com/v2"

    url = url.rstrip("/")
    if url == "https://api.attio.com/graphql" or url.startswith("https://app.attio.com/"):
        return "https://api.attio.com/v2"

    return url


ATTIO_API_KEY = os.getenv("ATTIO_API_KEY")
ATTIO_API_BASE_URL = _normalise_attio_api_base_url(
    os.getenv("ATTIO_API_BASE_URL") or os.getenv("ATTIO_API_URL")
)
ATTIO_OBJECT_SLUG = os.getenv("ATTIO_OBJECT_SLUG", "people")
ATTIO_STAGE_ATTRIBUTE_SLUG = os.getenv("ATTIO_STAGE_ATTRIBUTE_SLUG", "rootle_stage")
ATTIO_VALUATION_REQUEST_OBJECT_SLUG = os.getenv(
    "ATTIO_VALUATION_REQUEST_OBJECT_SLUG",
    "valuation_requests",
)
ROOTLE_STAGE_OPTIONS = ("stage-1", "stage-2", "stage-3")
VALUATION_REQUEST_STAGE_OPTIONS = ("stage-2", "stage-3", "closed")
VALUATION_REQUEST_ITEM_OPTIONS = ("gold", "silver", "coins")
VALUATION_REQUEST_ATTRIBUTES = (
    {
        "title": "Request Title",
        "api_slug": "request_title",
        "description": "Human-readable label for the valuation request.",
        "type": "text",
        "is_required": True,
        "is_unique": False,
        "is_multiselect": False,
        "config": {},
    },
    {
        "title": "Rootle Request ID",
        "api_slug": "rootle_request_id",
        "description": "Stable Rootle identifier for this valuation request.",
        "type": "text",
        "is_required": False,
        "is_unique": True,
        "is_multiselect": False,
        "config": {},
    },
    {
        "title": "Item Categories",
        "api_slug": "item_categories",
        "description": "Item categories submitted in Stage 2.",
        "type": "select",
        "is_required": True,
        "is_unique": False,
        "is_multiselect": True,
        "config": {},
    },
    {
        "title": "Item Photo URL",
        "api_slug": "item_photo_url",
        "description": "URL of the item photo submitted in Stage 2.",
        "type": "text",
        "is_required": True,
        "is_unique": False,
        "is_multiselect": False,
        "config": {},
    },
    {
        "title": "Rootle Stage",
        "api_slug": "rootle_stage",
        "description": "Current Rootle form stage for this valuation request.",
        "type": "select",
        "is_required": True,
        "is_unique": False,
        "is_multiselect": False,
        "config": {},
    },
    {
        "title": "Valuation Guide ID",
        "api_slug": "valuation_guide_id",
        "description": "Identifier for the unique valuation guide generated for this request.",
        "type": "text",
        "is_required": False,
        "is_unique": False,
        "is_multiselect": False,
        "config": {},
    },
    {
        "title": "Valuation Guide URL",
        "api_slug": "valuation_guide_url",
        "description": "URL of the unique valuation guide generated for this request.",
        "type": "text",
        "is_required": False,
        "is_unique": False,
        "is_multiselect": False,
        "config": {},
    },
    {
        "title": "Rootle PostHog Distinct ID",
        "api_slug": "rootle_posthog_distinct_id",
        "description": "PostHog distinct_id captured on form submission.",
        "type": "text",
        "is_required": False,
        "is_unique": False,
        "is_multiselect": False,
        "config": {},
    },
    {
        "title": "Source",
        "api_slug": "source",
        "description": "Submission source for this valuation request.",
        "type": "text",
        "is_required": False,
        "is_unique": False,
        "is_multiselect": False,
        "config": {},
    },
    {
        "title": "Stage 3 Completed At",
        "api_slug": "stage_3_completed_at",
        "description": "Timestamp when this valuation request completed Stage 3.",
        "type": "timestamp",
        "is_required": False,
        "is_unique": False,
        "is_multiselect": False,
        "config": {},
    },
)
MARKETING_ATTRIBUTION_ATTRIBUTES = (
    {
        "title": "Rootle Lead Source",
        "api_slug": "rootle_lead_source",
        "description": "Lead source captured by Rootle.",
    },
    {
        "title": "Rootle Original Source",
        "api_slug": "rootle_original_source",
        "description": "First known traffic source captured by Rootle.",
    },
    {
        "title": "Rootle Latest Source",
        "api_slug": "rootle_latest_source",
        "description": "Most recent traffic source captured by Rootle.",
    },
    {
        "title": "Rootle UTM Source",
        "api_slug": "rootle_utm_source",
        "description": "utm_source captured on form submission.",
    },
    {
        "title": "Rootle UTM Medium",
        "api_slug": "rootle_utm_medium",
        "description": "utm_medium captured on form submission.",
    },
    {
        "title": "Rootle UTM Campaign",
        "api_slug": "rootle_utm_campaign",
        "description": "utm_campaign captured on form submission.",
    },
    {
        "title": "Rootle UTM Content",
        "api_slug": "rootle_utm_content",
        "description": "utm_content captured on form submission.",
    },
    {
        "title": "Rootle UTM Term",
        "api_slug": "rootle_utm_term",
        "description": "utm_term captured on form submission.",
    },
    {
        "title": "Rootle GCLID",
        "api_slug": "rootle_gclid",
        "description": "Google Ads click ID captured on form submission.",
    },
    {
        "title": "Rootle FBCLID",
        "api_slug": "rootle_fbclid",
        "description": "Meta/Facebook click ID captured on form submission.",
    },
    {
        "title": "Rootle Landing Page",
        "api_slug": "rootle_landing_page",
        "description": "First landing page captured for this lead.",
    },
    {
        "title": "Rootle Referrer",
        "api_slug": "rootle_referrer",
        "description": "Referrer captured on form submission.",
    },
    {
        "title": "Rootle First Form Page",
        "api_slug": "rootle_first_form_page",
        "description": "Page where the first lead form was submitted.",
    },
    {
        "title": "Rootle PostHog Distinct ID",
        "api_slug": "rootle_posthog_distinct_id",
        "description": "PostHog distinct_id captured on form submission.",
    },
)
MARKETING_META_TO_ATTIO = {
    "lead_source": "rootle_lead_source",
    "original_source": "rootle_original_source",
    "latest_source": "rootle_latest_source",
    "utm_source": "rootle_utm_source",
    "utm_medium": "rootle_utm_medium",
    "utm_campaign": "rootle_utm_campaign",
    "utm_content": "rootle_utm_content",
    "utm_term": "rootle_utm_term",
    "gclid": "rootle_gclid",
    "fbclid": "rootle_fbclid",
    "landing_page": "rootle_landing_page",
    "referrer": "rootle_referrer",
    "first_form_page": "rootle_first_form_page",
    "form_page": "rootle_first_form_page",
    "posthog_distinct_id": "rootle_posthog_distinct_id",
}


class AttioError(Exception):
    pass


def _headers() -> dict[str, str]:
    if not ATTIO_API_KEY:
        raise AttioError("Attio configuration is missing. Set ATTIO_API_KEY.")

    return {
        "Authorization": f"Bearer {ATTIO_API_KEY}",
        "Content-Type": "application/json",
    }


def _attio_url(path: str) -> str:
    return f"{ATTIO_API_BASE_URL.rstrip('/')}/{path.lstrip('/')}"


def _lead_description(lead: Lead) -> str:
    lines = ["Rootle ERP lead"]
    if lead.stage:
        lines.append(f"Stage: {lead.stage}")
    if lead.source:
        lines.append(f"Source: {lead.source}")
    if lead.preferred_contact_method:
        lines.append(f"Preferred contact: {lead.preferred_contact_method}")
    if lead.notes:
        lines.extend(["", lead.notes])
    return "\n".join(lines)


def _lead_values(lead: Lead) -> dict:
    full_name = f"{lead.first_name or ''} {lead.last_name or ''}".strip()
    values = {
        "name": [
            {
                "first_name": lead.first_name,
                "last_name": lead.last_name,
                "full_name": full_name,
            }
        ],
        "description": _lead_description(lead),
    }

    if lead.stage:
        values[ATTIO_STAGE_ATTRIBUTE_SLUG] = lead.stage

    values.update(_lead_marketing_values(lead))

    if lead.email:
        values["email_addresses"] = [lead.email]

    if lead.phone:
        values["phone_numbers"] = [{"original_phone_number": lead.phone}]

    address = {
        "line_1": lead.address_line_1,
        "line_2": lead.address_line_2,
        "line_3": None,
        "line_4": None,
        "locality": lead.city,
        "region": None,
        "postcode": lead.postcode,
        "country_code": lead.country,
    }
    if any(address.values()):
        values["primary_location"] = [address]

    return values


def _lead_marketing_values(lead: Lead) -> dict:
    marketing_values = {}

    if lead.source:
        marketing_values["rootle_lead_source"] = lead.source

    if not isinstance(lead.meta, dict):
        return marketing_values

    for meta_key, attio_slug in MARKETING_META_TO_ATTIO.items():
        value = lead.meta.get(meta_key)
        if value:
            marketing_values[attio_slug] = str(value)

    return marketing_values


def _split_name(name: str) -> tuple[str, str | None]:
    parts = name.strip().split()
    if not parts:
        return "", None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _stage_1_values(
    *,
    name: str,
    phone_number: str,
    posthog_distinct_id: str,
) -> dict:
    first_name, last_name = _split_name(name)
    return {
        "name": [
            {
                "first_name": first_name,
                "last_name": last_name,
                "full_name": name.strip(),
            }
        ],
        "phone_numbers": [{"original_phone_number": phone_number.strip()}],
        "description": "Rootle website lead\nStage: stage-1",
        ATTIO_STAGE_ATTRIBUTE_SLUG: "stage-1",
        "rootle_posthog_distinct_id": posthog_distinct_id.strip(),
    }


def _valuation_request_values(
    *,
    person_record_id: str,
    rootle_request_id: str,
    item_categories: list[str],
    item_photo_url: str,
    posthog_distinct_id: str | None = None,
    valuation_guide_id: str | None = None,
    valuation_guide_url: str | None = None,
    source: str | None = None,
) -> dict:
    values = {
        "request_title": f"Valuation request {rootle_request_id}",
        "rootle_request_id": rootle_request_id,
        "item_categories": item_categories,
        "item_photo_url": item_photo_url,
        "rootle_stage": "stage-2",
        "person": [
            {
                "target_object": ATTIO_OBJECT_SLUG,
                "target_record_id": person_record_id,
            }
        ],
    }

    optional_values = {
        "rootle_posthog_distinct_id": posthog_distinct_id,
        "valuation_guide_id": valuation_guide_id,
        "valuation_guide_url": valuation_guide_url,
        "source": source,
    }
    values.update(
        {
            key: value
            for key, value in optional_values.items()
            if value is not None and str(value).strip()
        }
    )
    return values


def _person_contact_values(
    *,
    email: str | None = None,
    address_line_1: str | None = None,
    address_line_2: str | None = None,
    city: str | None = None,
    postcode: str | None = None,
    country: str | None = None,
) -> dict:
    values = {}
    if email:
        values["email_addresses"] = [email]

    address = {
        "line_1": address_line_1,
        "line_2": address_line_2,
        "line_3": None,
        "line_4": None,
        "locality": city,
        "region": None,
        "postcode": postcode,
        "country_code": country,
    }
    if any(address.values()):
        values["primary_location"] = [address]

    return values


def _attio_request(method: str, path: str, **kwargs) -> requests.Response:
    return requests.request(
        method,
        _attio_url(path),
        headers=_headers(),
        timeout=15,
        **kwargs,
    )


def _create_attio_object(api_slug: str, singular_noun: str, plural_noun: str) -> dict:
    response = _attio_request(
        "POST",
        "objects",
        json={
            "data": {
                "api_slug": api_slug,
                "singular_noun": singular_noun,
                "plural_noun": plural_noun,
            }
        },
    )
    if response.status_code == 409:
        return get_attio_object(api_slug)
    if not response.ok:
        raise AttioError(f"Attio API returned {response.status_code}: {response.text}")
    return response.json()["data"]


def get_attio_object(api_slug: str) -> dict:
    response = _attio_request("GET", f"objects/{api_slug}")
    if not response.ok:
        raise AttioError(f"Attio API returned {response.status_code}: {response.text}")
    return response.json()["data"]


def _extract_record_id(data: dict) -> str | None:
    try:
        return data["data"]["id"]["record_id"]
    except (KeyError, TypeError):
        return None


def _extract_record_id_from_record(record: dict) -> str | None:
    try:
        return record["id"]["record_id"]
    except (KeyError, TypeError):
        return None


def _record_attio_result(
    *,
    entity_type: str,
    payload: dict | None,
    response: requests.Response,
) -> IntegrationLog:
    log = IntegrationLog(
        system="attio",
        entity_type=entity_type,
        external_id=None,
        payload={
            "request": payload,
            "response_status": response.status_code,
            "response_text": response.text,
        },
        status="success" if response.ok else "failed",
        processed_at=datetime.utcnow(),
    )

    if response.ok:
        record_id = _extract_record_id(response.json())
        if record_id:
            log.external_id = record_id
        else:
            log.status = "failed"

    db.session.add(log)
    db.session.commit()
    return log


def check_attio_connection() -> dict:
    response = _attio_request(
        "POST",
        f"objects/{ATTIO_OBJECT_SLUG}/records/query",
        json={"limit": 1},
    )
    if not response.ok:
        raise AttioError(f"Attio API returned {response.status_code}: {response.text}")
    return response.json()


def find_attio_person_by_phone(phone_number: str) -> str | None:
    response = _attio_request(
        "POST",
        f"objects/{ATTIO_OBJECT_SLUG}/records/query",
        json={"filter": {"phone_numbers": phone_number.strip()}, "limit": 1},
    )
    if not response.ok:
        raise AttioError(f"Attio API returned {response.status_code}: {response.text}")

    records = response.json().get("data", [])
    if not records:
        return None

    return _extract_record_id_from_record(records[0])


def _list_attio_attributes() -> list[dict]:
    response = _attio_request(
        "GET",
        f"objects/{ATTIO_OBJECT_SLUG}/attributes",
    )
    if not response.ok:
        raise AttioError(
            f"Attio API returned {response.status_code}: {response.text}"
        )
    return response.json().get("data", [])


def _list_object_attributes(object_slug: str) -> list[dict]:
    response = _attio_request("GET", f"objects/{object_slug}/attributes")
    if not response.ok:
        raise AttioError(f"Attio API returned {response.status_code}: {response.text}")
    return response.json().get("data", [])


def _create_text_attribute(attribute: dict) -> dict:
    response = _attio_request(
        "POST",
        f"objects/{ATTIO_OBJECT_SLUG}/attributes",
        json={
            "data": {
                "title": attribute["title"],
                "description": attribute["description"],
                "api_slug": attribute["api_slug"],
                "type": "text",
                "is_required": False,
                "is_unique": False,
                "is_multiselect": False,
                "config": {},
            }
        },
    )
    if not response.ok:
        raise AttioError(f"Attio API returned {response.status_code}: {response.text}")
    return response.json()["data"]


def _create_object_attribute(object_slug: str, attribute: dict) -> dict:
    response = _attio_request(
        "POST",
        f"objects/{object_slug}/attributes",
        json={"data": attribute},
    )
    if response.status_code == 409:
        attributes = _list_object_attributes(object_slug)
        existing = next(
            (
                item
                for item in attributes
                if item.get("api_slug") == attribute["api_slug"]
            ),
            None,
        )
        if existing:
            return existing
    if not response.ok:
        raise AttioError(f"Attio API returned {response.status_code}: {response.text}")
    return response.json()["data"]


def _ensure_select_options(object_slug: str, attribute_slug: str, options: tuple[str, ...]) -> None:
    for option in options:
        response = _attio_request(
            "POST",
            f"objects/{object_slug}/attributes/{attribute_slug}/options",
            json={"data": {"title": option}},
        )
        if response.status_code == 409:
            continue
        if not response.ok:
            raise AttioError(f"Attio API returned {response.status_code}: {response.text}")


def ensure_marketing_attribution_attributes() -> list[dict]:
    attributes = _list_attio_attributes()
    existing_by_slug = {attribute.get("api_slug"): attribute for attribute in attributes}
    ensured = []

    for attribute in MARKETING_ATTRIBUTION_ATTRIBUTES:
        existing = existing_by_slug.get(attribute["api_slug"])
        if existing:
            ensured.append(existing)
            continue

        ensured.append(_create_text_attribute(attribute))

    return ensured


def ensure_valuation_request_object() -> dict:
    valuation_request_object = _create_attio_object(
        ATTIO_VALUATION_REQUEST_OBJECT_SLUG,
        "Valuation Request",
        "Valuation Requests",
    )

    ensured_attributes = []
    for attribute in VALUATION_REQUEST_ATTRIBUTES:
        ensured_attributes.append(
            _create_object_attribute(ATTIO_VALUATION_REQUEST_OBJECT_SLUG, attribute)
        )

    person_attribute = {
        "title": "Person",
        "api_slug": "person",
        "description": "Person who submitted this valuation request.",
        "type": "record-reference",
        "is_required": True,
        "is_unique": False,
        "is_multiselect": False,
        "config": {},
        "relationship": {
            "object": ATTIO_OBJECT_SLUG,
            "title": "Valuation Requests",
            "api_slug": "valuation_requests",
            "is_multiselect": True,
        },
    }
    ensured_attributes.append(
        _create_object_attribute(ATTIO_VALUATION_REQUEST_OBJECT_SLUG, person_attribute)
    )

    _ensure_select_options(
        ATTIO_VALUATION_REQUEST_OBJECT_SLUG,
        "item_categories",
        VALUATION_REQUEST_ITEM_OPTIONS,
    )
    _ensure_select_options(
        ATTIO_VALUATION_REQUEST_OBJECT_SLUG,
        "rootle_stage",
        VALUATION_REQUEST_STAGE_OPTIONS,
    )

    return {
        "object": valuation_request_object,
        "attributes": ensured_attributes,
    }


def ensure_valuation_request_item_options(item_categories: list[str]) -> None:
    ensure_valuation_request_object()
    options = tuple(
        str(category).strip()
        for category in item_categories
        if str(category).strip()
    )
    _ensure_select_options(
        ATTIO_VALUATION_REQUEST_OBJECT_SLUG,
        "item_categories",
        options,
    )


def ensure_stage_attribute() -> dict:
    attributes = _list_attio_attributes()
    attribute = next(
        (
            item
            for item in attributes
            if item.get("api_slug") == ATTIO_STAGE_ATTRIBUTE_SLUG
        ),
        None,
    )

    if not attribute:
        create_response = _attio_request(
            "POST",
            f"objects/{ATTIO_OBJECT_SLUG}/attributes",
            json={
                "data": {
                    "title": "Rootle Stage",
                    "description": "ERP lead stage mirrored from Rootle.",
                    "api_slug": ATTIO_STAGE_ATTRIBUTE_SLUG,
                    "type": "select",
                    "is_required": False,
                    "is_unique": False,
                    "is_multiselect": False,
                    "config": {},
                }
            },
        )
        if create_response.status_code == 409:
            return ensure_stage_attribute()
        if not create_response.ok:
            raise AttioError(
                f"Attio API returned {create_response.status_code}: "
                f"{create_response.text}"
            )
        attribute = create_response.json()["data"]

    for stage in ROOTLE_STAGE_OPTIONS:
        option_response = _attio_request(
            "POST",
            f"objects/{ATTIO_OBJECT_SLUG}/attributes/{ATTIO_STAGE_ATTRIBUTE_SLUG}/options",
            json={"data": {"title": stage}},
        )
        if option_response.status_code == 409:
            continue
        if not option_response.ok:
            raise AttioError(
                f"Attio API returned {option_response.status_code}: "
                f"{option_response.text}"
            )

    return attribute


def create_attio_lead(lead: Lead) -> str:
    ensure_stage_attribute()
    ensure_marketing_attribution_attributes()
    payload = {"data": {"values": _lead_values(lead)}}
    url = _attio_url(f"objects/{ATTIO_OBJECT_SLUG}/records")

    if lead.email:
        response = requests.put(
            url,
            params={"matching_attribute": "email_addresses"},
            json=payload,
            headers=_headers(),
            timeout=15,
        )
    else:
        response = requests.post(url, json=payload, headers=_headers(), timeout=15)

    log = _record_attio_result(entity_type="lead", payload=payload, response=response)

    if not response.ok:
        raise AttioError(f"Attio API returned {response.status_code}: {response.text}")

    if not log.external_id:
        raise AttioError("Attio did not return a record id.")

    return log.external_id


def create_attio_stage_1_lead(
    *,
    name: str,
    phone_number: str,
    posthog_distinct_id: str,
) -> str:
    ensure_stage_attribute()
    ensure_marketing_attribution_attributes()

    payload = {
        "data": {
            "values": _stage_1_values(
                name=name,
                phone_number=phone_number,
                posthog_distinct_id=posthog_distinct_id,
            )
        }
    }
    response = requests.post(
        _attio_url(f"objects/{ATTIO_OBJECT_SLUG}/records"),
        json=payload,
        headers=_headers(),
        timeout=15,
    )
    log = _record_attio_result(entity_type="lead_stage_1", payload=payload, response=response)

    if not response.ok:
        raise AttioError(f"Attio API returned {response.status_code}: {response.text}")

    if not log.external_id:
        raise AttioError("Attio did not return a record id.")

    return log.external_id


def get_or_create_attio_stage_1_lead(
    *,
    name: str,
    phone_number: str,
    posthog_distinct_id: str,
) -> dict:
    existing_record_id = find_attio_person_by_phone(phone_number)
    if existing_record_id:
        return {"record_id": existing_record_id, "created": False}

    record_id = create_attio_stage_1_lead(
        name=name,
        phone_number=phone_number,
        posthog_distinct_id=posthog_distinct_id,
    )
    return {"record_id": record_id, "created": True}


def update_attio_lead(lead: Lead) -> str:
    ensure_stage_attribute()
    ensure_marketing_attribution_attributes()

    if not lead.crm_record_id:
        return create_attio_lead(lead)

    payload = {"data": {"values": _lead_values(lead)}}
    response = requests.patch(
        _attio_url(f"objects/{ATTIO_OBJECT_SLUG}/records/{lead.crm_record_id}"),
        json=payload,
        headers=_headers(),
        timeout=15,
    )

    log = _record_attio_result(entity_type="lead", payload=payload, response=response)

    if not response.ok:
        raise AttioError(f"Attio API returned {response.status_code}: {response.text}")

    return log.external_id or lead.crm_record_id


def create_attio_valuation_request(
    *,
    person_record_id: str,
    rootle_request_id: str,
    item_categories: list[str],
    item_photo_url: str,
    posthog_distinct_id: str | None = None,
    valuation_guide_id: str | None = None,
    valuation_guide_url: str | None = None,
    source: str | None = None,
) -> str:
    ensure_valuation_request_item_options(item_categories)
    payload = {
        "data": {
            "values": _valuation_request_values(
                person_record_id=person_record_id,
                rootle_request_id=rootle_request_id,
                item_categories=item_categories,
                item_photo_url=item_photo_url,
                posthog_distinct_id=posthog_distinct_id,
                valuation_guide_id=valuation_guide_id,
                valuation_guide_url=valuation_guide_url,
                source=source,
            )
        }
    }
    response = requests.post(
        _attio_url(f"objects/{ATTIO_VALUATION_REQUEST_OBJECT_SLUG}/records"),
        json=payload,
        headers=_headers(),
        timeout=15,
    )
    log = _record_attio_result(
        entity_type="valuation_request",
        payload=payload,
        response=response,
    )

    if not response.ok:
        raise AttioError(f"Attio API returned {response.status_code}: {response.text}")

    if not log.external_id:
        raise AttioError("Attio did not return a valuation request record id.")

    return log.external_id


def update_attio_valuation_request(
    *,
    valuation_request_id: str | None,
    person_record_id: str,
    rootle_request_id: str,
    item_categories: list[str],
    item_photo_url: str,
    posthog_distinct_id: str | None = None,
    valuation_guide_id: str | None = None,
    valuation_guide_url: str | None = None,
    source: str | None = None,
) -> str | None:
    if not valuation_request_id:
        return valuation_request_id

    ensure_valuation_request_item_options(item_categories)
    payload = {
        "data": {
            "values": _valuation_request_values(
                person_record_id=person_record_id,
                rootle_request_id=rootle_request_id,
                item_categories=item_categories,
                item_photo_url=item_photo_url,
                posthog_distinct_id=posthog_distinct_id,
                valuation_guide_id=valuation_guide_id,
                valuation_guide_url=valuation_guide_url,
                source=source,
            )
        }
    }
    response = requests.patch(
        _attio_url(
            f"objects/{ATTIO_VALUATION_REQUEST_OBJECT_SLUG}/records/{valuation_request_id}"
        ),
        json=payload,
        headers=_headers(),
        timeout=15,
    )
    _record_attio_result(
        entity_type="valuation_request",
        payload=payload,
        response=response,
    )

    if not response.ok:
        raise AttioError(f"Attio API returned {response.status_code}: {response.text}")

    return valuation_request_id


def update_attio_person_contact_details(
    *,
    person_record_id: str,
    email: str | None = None,
    address_line_1: str | None = None,
    address_line_2: str | None = None,
    city: str | None = None,
    postcode: str | None = None,
    country: str | None = None,
) -> str:
    values = _person_contact_values(
        email=email,
        address_line_1=address_line_1,
        address_line_2=address_line_2,
        city=city,
        postcode=postcode,
        country=country,
    )
    if not values:
        return person_record_id

    payload = {"data": {"values": values}}
    response = requests.patch(
        _attio_url(f"objects/{ATTIO_OBJECT_SLUG}/records/{person_record_id}"),
        json=payload,
        headers=_headers(),
        timeout=15,
    )
    _record_attio_result(
        entity_type="person_contact_details",
        payload=payload,
        response=response,
    )

    if not response.ok:
        raise AttioError(f"Attio API returned {response.status_code}: {response.text}")

    return person_record_id
