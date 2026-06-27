from datetime import datetime
import os

from flask import current_app, has_app_context
import requests

from database import db
from models import IntegrationLog


class KlaviyoError(RuntimeError):
    pass


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
    email: str,
    attio_person_record_id: str,
    phone_number: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    properties: dict | None = None,
) -> dict:
    attributes = {
        "email": email,
        "external_id": attio_person_record_id,
        "properties": {
            "attio_person_record_id": attio_person_record_id,
            "source": "attio",
            **(properties or {}),
        },
    }

    optional_attributes = {
        "phone_number": phone_number,
        "first_name": first_name,
        "last_name": last_name,
    }
    attributes.update(
        {key: value for key, value in optional_attributes.items() if value}
    )

    return {"data": {"type": "profile", "attributes": attributes}}


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

    return {
        "status": "success",
        "integration_log_id": log.id,
        "response_status": response.status_code,
    }
