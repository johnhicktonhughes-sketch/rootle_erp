from datetime import datetime
import os

from flask import current_app, has_app_context
import requests

from database import db
from models import IntegrationLog


class KlaviyoError(RuntimeError):
    pass


KLAVIYO_MARKETING_CONSENT_LIST_ID = "Ub3nHY"
KLAVIYO_ROOTLE_CONTACT_LIST_ID = "RWb2ew"
KLAVIYO_STAGE_PROPERTY = "rootle_stage"
KLAVIYO_STAGE_INDICATIVE_OFFER_STARTED = "indicative_offer_started"
KLAVIYO_STAGE_INDICATIVE_OFFER_COMPLETED = "indicative_offer_completed"


def _config_value(key: str, default: str | None = None) -> str | None:
    if has_app_context():
        return current_app.config.get(key, default)
    return os.getenv(key, default)


def _api_key() -> str | None:
    return _config_value("KLAVIYO_API_KEY")


def _base_url() -> str:
    return (
        _config_value("KLAVIYO_API_BASE_URL", "https://a.klaviyo.com") or ""
    ).rstrip("/")


def _revision() -> str:
    return _config_value("KLAVIYO_API_REVISION", "2026-04-15") or "2026-04-15"


def _headers() -> dict:
    api_key = _api_key()
    if not api_key:
        raise KlaviyoError("Klaviyo configuration is missing. Set KLAVIYO_API_KEY.")

    return {
        "Authorization": f"Klaviyo-API-Key {api_key}",
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
        "revision": _revision(),
    }


def _record_klaviyo_result(
    *,
    entity_type: str,
    external_id: str | None,
    payload: dict,
    response: requests.Response | None = None,
    status: str | None = None,
    message: str | None = None,
) -> IntegrationLog:
    log_payload = {"request": payload}
    if response is not None:
        log_payload.update(
            {
                "response_status": response.status_code,
                "response_text": response.text,
            }
        )
    if message:
        log_payload["message"] = message

    log = IntegrationLog(
        system="klaviyo",
        entity_type=entity_type,
        external_id=external_id,
        payload=log_payload,
        status=status
        or ("success" if response is not None and response.ok else "failed"),
        processed_at=datetime.utcnow(),
    )
    db.session.add(log)
    db.session.commit()
    return log


def _profile_payload(
    *,
    email: str | None = None,
    attio_person_record_id: str,
    phone_number: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    properties: dict | None = None,
) -> dict:
    attributes = {
        "external_id": attio_person_record_id,
        "properties": {
            "attio_person_record_id": attio_person_record_id,
            "source": "attio",
            **(properties or {}),
        },
    }

    optional_attributes = {
        "email": email,
        "phone_number": phone_number,
        "first_name": first_name,
        "last_name": last_name,
    }
    attributes.update(
        {key: value for key, value in optional_attributes.items() if value}
    )

    return {"data": {"type": "profile", "attributes": attributes}}


def _profile_id_from_response(response: requests.Response) -> str | None:
    try:
        return response.json().get("data", {}).get("id")
    except ValueError:
        return None


def _list_relationship_payload(profile_id: str) -> dict:
    return {"data": [{"type": "profile", "id": profile_id}]}


def _email_subscription_payload(*, email: str, list_id: str) -> dict:
    return {
        "data": {
            "type": "profile-subscription-bulk-create-job",
            "attributes": {
                "profiles": {
                    "data": [
                        {
                            "type": "profile",
                            "attributes": {
                                "email": email,
                                "subscriptions": {
                                    "email": {
                                        "marketing": {
                                            "consent": "SUBSCRIBED",
                                        }
                                    }
                                },
                            },
                        }
                    ]
                }
            },
            "relationships": {
                "list": {
                    "data": {
                        "type": "list",
                        "id": list_id,
                    }
                }
            },
        }
    }


def add_profile_to_list(
    *,
    profile_id: str,
    list_id: str,
    external_id: str | None = None,
) -> dict:
    payload = _list_relationship_payload(profile_id)
    response = requests.post(
        f"{_base_url()}/api/lists/{list_id}/relationships/profiles",
        json=payload,
        headers=_headers(),
        timeout=15,
    )
    log = _record_klaviyo_result(
        entity_type="list_membership",
        external_id=external_id or profile_id,
        payload={"list_id": list_id, **payload},
        response=response,
    )

    if not response.ok:
        raise KlaviyoError(
            f"Klaviyo API returned {response.status_code}: {response.text}"
        )

    return {
        "list_id": list_id,
        "status": "success",
        "integration_log_id": log.id,
        "response_status": response.status_code,
    }


def subscribe_profile_to_email_marketing(
    *,
    email: str,
    list_id: str,
    external_id: str | None = None,
) -> dict:
    payload = _email_subscription_payload(email=email, list_id=list_id)
    response = requests.post(
        f"{_base_url()}/api/profile-subscription-bulk-create-jobs",
        json=payload,
        headers=_headers(),
        timeout=15,
    )
    log = _record_klaviyo_result(
        entity_type="email_subscription",
        external_id=external_id or email,
        payload=payload,
        response=response,
    )

    if not response.ok:
        raise KlaviyoError(
            f"Klaviyo API returned {response.status_code}: {response.text}"
        )

    return {
        "list_id": list_id,
        "status": "success",
        "integration_log_id": log.id,
        "response_status": response.status_code,
    }


def upsert_profile_properties_by_attio_person(
    *,
    attio_person_record_id: str,
    properties: dict,
) -> dict:
    payload = _profile_payload(
        attio_person_record_id=attio_person_record_id,
        properties=properties,
    )

    if not _api_key():
        _record_klaviyo_result(
            entity_type="profile",
            external_id=attio_person_record_id,
            payload=payload,
            status="skipped",
            message="KLAVIYO_API_KEY is not configured.",
        )
        return {"status": "skipped", "reason": "missing_api_key"}

    response = requests.post(
        f"{_base_url()}/api/profile-import",
        json=payload,
        headers=_headers(),
        timeout=15,
    )
    log = _record_klaviyo_result(
        entity_type="profile",
        external_id=attio_person_record_id,
        payload=payload,
        response=response,
    )

    if not response.ok:
        raise KlaviyoError(
            f"Klaviyo API returned {response.status_code}: {response.text}"
        )

    return {
        "status": "success",
        "integration_log_id": log.id,
        "response_status": response.status_code,
        "profile_id": _profile_id_from_response(response),
    }


def upsert_profile_from_attio_contact(
    *,
    email: str | None,
    attio_person_record_id: str,
    phone_number: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    properties: dict | None = None,
) -> dict:
    if not email:
        return {"status": "skipped", "reason": "missing_email"}

    payload = _profile_payload(
        email=email,
        attio_person_record_id=attio_person_record_id,
        phone_number=phone_number,
        first_name=first_name,
        last_name=last_name,
        properties=properties,
    )

    if not _api_key():
        _record_klaviyo_result(
            entity_type="profile",
            external_id=attio_person_record_id,
            payload=payload,
            status="skipped",
            message="KLAVIYO_API_KEY is not configured.",
        )
        return {"status": "skipped", "reason": "missing_api_key"}

    response = requests.post(
        f"{_base_url()}/api/profile-import",
        json=payload,
        headers=_headers(),
        timeout=15,
    )
    log = _record_klaviyo_result(
        entity_type="profile",
        external_id=attio_person_record_id,
        payload=payload,
        response=response,
    )

    if not response.ok:
        raise KlaviyoError(
            f"Klaviyo API returned {response.status_code}: {response.text}"
        )

    profile_id = _profile_id_from_response(response)
    if not profile_id:
        raise KlaviyoError("Klaviyo profile import did not return a profile id.")

    consent_sync = []
    if (properties or {}).get("marketing_consent") is True:
        consent_sync.append(
            subscribe_profile_to_email_marketing(
                email=email,
                list_id=KLAVIYO_MARKETING_CONSENT_LIST_ID,
                external_id=attio_person_record_id,
            )
        )

    list_sync = [
        add_profile_to_list(
            profile_id=profile_id,
            list_id=list_id,
            external_id=attio_person_record_id,
        )
        for list_id in [KLAVIYO_ROOTLE_CONTACT_LIST_ID]
    ]

    return {
        "status": "success",
        "integration_log_id": log.id,
        "response_status": response.status_code,
        "profile_id": profile_id,
        "consent_sync": consent_sync,
        "list_sync": list_sync,
    }
