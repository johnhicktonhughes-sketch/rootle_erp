"""Deliver Attio valuation creation events to Slack."""

import hashlib
from datetime import datetime

import requests
from flask import current_app
from sqlalchemy import text

from database import db
from models import IntegrationLog


def _related_person_phone(record_id):
    from attio import _attio_request

    response = _attio_request(
        "GET", f"objects/{record_id['object_id']}/records/{record_id['record_id']}"
    )
    response.raise_for_status()
    people = response.json()["data"].get("values", {}).get("person", [])
    phones = []
    for person in people:
        person_id = person.get("target_record_id")
        if not person_id:
            continue
        response = _attio_request("GET", f"objects/people/records/{person_id}")
        response.raise_for_status()
        for phone in response.json()["data"].get("values", {}).get("phone_numbers", []):
            number = phone.get("phone_number") or phone.get("original_phone_number")
            if number and number not in phones:
                phones.append(number)
    return ", ".join(phones) or "Not provided"


def _escape_slack(value):
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def notify_valuation_request_created(record_id):
    token = current_app.config.get("SLACK_BOT_TOKEN")
    channel = current_app.config.get("SLACK_VALUATION_REQUEST_CHANNEL_ID")
    webhook = current_app.config.get("SLACK_VALUATION_REQUEST_WEBHOOK_URL")
    if not webhook and (not token or not channel):
        raise RuntimeError("Slack notification credentials are not configured")

    external_id = ":".join(record_id[key] for key in ("workspace_id", "object_id", "record_id"))
    # Serialize duplicate deliveries across production workers.
    if db.engine.dialect.name == "postgresql":
        lock_id = int.from_bytes(hashlib.sha256(external_id.encode()).digest()[:8], signed=True)
        db.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
    if IntegrationLog.query.filter_by(
        system="slack", entity_type="valuation_request_created",
        external_id=external_id, status="sent",
    ).first():
        return False

    phone = _escape_slack(_related_person_phone(record_id))
    message = {
            "channel": channel,
            "text": (
                "<!channel> New valuation request created in Attio.\n"
                f"Phone: {phone}\nRecord ID: {_escape_slack(record_id['record_id'])}"
            ),
            "mrkdwn": True,
            "unfurl_links": False,
            "unfurl_media": False,
        }
    if webhook:
        # Incoming webhooks use the channel selected when they were installed.
        message.pop("channel")
        response = requests.post(webhook, json=message, timeout=10)
    else:
        response = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}"},
            json=message, timeout=10,
        )
    response.raise_for_status()
    result = {} if webhook else response.json()
    if webhook and response.text.strip() != "ok":
        raise RuntimeError("Slack rejected the webhook notification")
    if not webhook and not result.get("ok"):
        raise RuntimeError("Slack rejected the notification")
    db.session.add(IntegrationLog(
        system="slack", entity_type="valuation_request_created",
        external_id=external_id, status="sent", processed_at=datetime.utcnow(),
        payload={"channel": channel, "ts": result.get("ts")},
    ))
    # Persist each success before another event in the batch can fail.
    db.session.commit()
    return True
