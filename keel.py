"""Build and sign box handovers using Keel's Rootle API contract."""

import hashlib
import hmac
import json
import math
import time
from urllib.parse import urlsplit

import requests
from flask import current_app


MAX_BODY_BYTES = 256 * 1024
KEEL_CATEGORIES = (
    "Jewellery", "Coins & Currency", "War & Militaria", "Camera & Optical",
    "Metals", "Watches", "Timekeeping", "Sporting Memorabilia",
    "Collectibles & Memorabilia", "Decorative Arts", "Housewares & Kitchen",
    "Furniture", "Fashion", "Toys & Games", "Books", "Electronic Devices", "Other",
)
LABEL_METHODS = ("qr", "print_at_home", "posted")


class InvalidHandover(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("Invalid Keel handover")


class HandoverTooLarge(ValueError):
    pass


def build_handover(valuation, payload):
    """Use ERP identities and defaults, with explicit caller-supplied corrections."""
    errors = []
    if not isinstance(payload, dict):
        raise InvalidHandover(["Request body must be an object."])
    allowed = {"customer", "address", "photographedItem", "declaredCategories", "mev", "labelMethod"}
    errors.extend(f"Unknown field: {key}." for key in payload.keys() - allowed)
    for key in ("customer", "address", "photographedItem", "mev"):
        if key in payload and not isinstance(payload[key], dict):
            errors.append(f"{key} must be an object.")
    if errors:
        raise InvalidHandover(errors)

    customer = {
        "id": valuation.crm_person_record_id,
        "email": valuation.customer_email,
        **payload.get("customer", {}),
    }
    # The linkage and idempotency key belong to the ERP, not the caller.
    person_id = customer.get("attioPersonId", valuation.crm_person_record_id)
    if person_id != valuation.crm_person_record_id:
        errors.append("customer.attioPersonId must match the valuation's Attio person.")
    customer["attioPersonId"] = valuation.crm_person_record_id
    handover = {
        "requestId": valuation.rootle_request_id,
        "attioValuationRequestId": valuation.crm_valuation_request_id,
        "customer": customer,
        "address": {
            "line1": valuation.address_line_1,
            "line2": valuation.address_line_2,
            "town": valuation.city,
            "postcode": valuation.postcode,
            **payload.get("address", {}),
        },
        "photographedItem": {
            "photoUrl": valuation.item_photo_url,
            **payload.get("photographedItem", {}),
        },
    }
    if valuation.country and valuation.country.strip().lower() not in {
        "uk", "gb", "gbr", "united kingdom", "great britain",
    }:
        errors.append("The valuation must have a UK address for Keel handover.")

    if "mev" in payload:
        handover["mev"] = payload["mev"]
    else:
        snapshot = {
            "amount": valuation.latest_mev_amount,
            "low": valuation.mev_low,
            "high": valuation.mev_high,
            "currency": valuation.latest_mev_currency,
            "margin": valuation.latest_mev_margin,
            "pricingResultId": valuation.pricing_request_id,
        }
        if all(value is not None for value in snapshot.values()):
            handover["mev"] = {
                key: float(value) if key in {"amount", "low", "high", "margin"} else value
                for key, value in snapshot.items()
            }
    for key in ("declaredCategories", "labelMethod"):
        if key in payload:
            handover[key] = payload[key]

    errors.extend(validate_handover(handover))
    if errors:
        raise InvalidHandover(errors)
    return handover


def validate_handover(handover):
    errors = []

    def strings(obj, prefix, required, optional=()):
        for key in required:
            value = obj.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}{key} must be a non-empty string.")
        for key in optional:
            if key in obj and obj[key] is not None and not isinstance(obj[key], str):
                errors.append(f"{prefix}{key} must be a string or null.")
        unknown = obj.keys() - set(required) - set(optional)
        errors.extend(f"Unknown field: {prefix}{key}." for key in unknown)

    for key in ("requestId", "attioValuationRequestId"):
        if not isinstance(handover[key], str) or not handover[key].strip():
            errors.append(f"{key} must be a non-empty string.")
    strings(handover["customer"], "customer.", ("id", "name", "email", "attioPersonId"), ("phone",))
    strings(handover["address"], "address.", ("line1", "town", "postcode"), ("line2",))
    item = handover["photographedItem"]
    strings(item, "photographedItem.", ("category", "photoUrl"))
    if item.get("category") not in KEEL_CATEGORIES:
        errors.append("photographedItem.category must be an exact Keel category name.")
    try:
        url = urlsplit(item.get("photoUrl") or "")
        if url.scheme not in {"http", "https"} or not url.netloc or url.username or url.password:
            errors.append("photographedItem.photoUrl must be an HTTP(S) URL without credentials.")
    except (ValueError, TypeError, AttributeError):
        errors.append("photographedItem.photoUrl must be an HTTP(S) URL.")
    if "declaredCategories" in handover:
        categories = handover["declaredCategories"]
        if not isinstance(categories, list) or any(category not in KEEL_CATEGORIES for category in categories):
            errors.append("declaredCategories must be an array of exact Keel category names.")
    if "labelMethod" in handover and handover["labelMethod"] not in LABEL_METHODS:
        errors.append("labelMethod must be qr, print_at_home, or posted.")
    if "mev" in handover:
        mev = handover["mev"]
        unknown = mev.keys() - {"amount", "low", "high", "currency", "margin", "pricingResultId"}
        errors.extend(f"Unknown field: mev.{key}." for key in unknown)
        for key in ("amount", "low", "high", "margin"):
            value = mev.get(key)
            try:
                finite = type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                errors.append(f"mev.{key} must be a finite number.")
            elif key in {"amount", "margin"} and value < 0:
                errors.append(f"mev.{key} must be non-negative.")
        for key in ("currency", "pricingResultId"):
            if not isinstance(mev.get(key), str) or not mev[key].strip():
                errors.append(f"mev.{key} must be a non-empty string.")
        if not errors and mev["low"] > mev["high"]:
            errors.append("mev.low must not exceed mev.high.")
    return errors


def sign_handover(handover, secret):
    # Serialize exactly once. requests must send these bytes, not re-encode JSON.
    body = json.dumps(handover, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(body) > MAX_BODY_BYTES:
        raise HandoverTooLarge("Keel handover exceeds 256 KB.")
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256,
    ).hexdigest()
    return body, {
        "Content-Type": "application/json",
        "x-rootle-timestamp": timestamp,
        "x-rootle-signature": signature,
    }


def send_handover(handover):
    body, headers = sign_handover(handover, current_app.config["KEEL_API_KEY"])
    return requests.post(
        current_app.config["KEEL_HANDOVER_URL"], data=body, headers=headers,
        timeout=(5, 20), allow_redirects=False,
    )
