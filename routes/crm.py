from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import re
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request

from database import db
from models import (
    Company,
    Contact,
    JourneyPhase,
    InboundLabel,
    Lead,
    LeadBoxDetail,
    LeadBoxRevision,
    LeadEstimate,
    LeadValuation,
    LeadValuationMevCalculation,
    ValuationItemCategory,
)

crm_bp = Blueprint("crm", __name__)

DEFAULT_VALUATION_ITEMS = ("gold", "silver", "coins")
LABEL_MEV_THRESHOLD = Decimal("100.00")
WHITE_GLOVE_MEV_THRESHOLD = Decimal("10000.00")
LABEL_TERMINAL_STATUSES = {"cancelled", "expired", "received"}


def _required_string(payload, key):
    value = payload.get(key)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _string_list(payload, *keys):
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue

        if isinstance(value, list):
            raw_items = value
        else:
            raw_items = re.split(r"[,;]", str(value))

        items = []
        for item in raw_items:
            if isinstance(item, dict):
                item = (
                    item.get("name")
                    or item.get("value")
                    or item.get("slug")
                    or item.get("label")
                )
            item = str(item).strip()
            if item:
                items.append(item)
        return items or None

    return None


def _valuation_to_dict(valuation):
    data = valuation.to_dict()
    data["mev_calculations"] = [
        calculation.to_dict() for calculation in valuation.mev_calculations
    ]
    data["inbound_labels"] = [_label_to_dict(label) for label in valuation.inbound_labels]
    data["label_eligibility"] = _label_eligibility_for_valuation(valuation)
    return data


def _mev_calculation_to_dict(calculation):
    return calculation.to_dict()


def _label_to_dict(label, include_context=False):
    data = label.to_dict()
    if include_context:
        data["valuation"] = _valuation_to_dict(label.valuation)
        data["expected_items"] = label.valuation.item_categories
        data["item_photo_url"] = label.valuation.item_photo_url
    return data


def _decimal_value(payload, key):
    value = payload.get(key)
    if value is None or value == "":
        return None

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _category_slug(value):
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or None


def _category_label(name):
    return name.replace("_", " ").title()


def _merge_unique_values(existing_values, new_values):
    if isinstance(existing_values, str):
        existing_values = [existing_values]
    if isinstance(new_values, str):
        new_values = [new_values]

    values = []
    seen = set()
    for value in [*(existing_values or []), *(new_values or [])]:
        value = str(value).strip()
        if value and value not in seen:
            values.append(value)
            seen.add(value)
    return values


def _bool_value(payload, key):
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _active_label_for_valuation(valuation):
    return (
        InboundLabel.query.filter_by(lead_valuation_id=valuation.id)
        .filter(~InboundLabel.status.in_(LABEL_TERMINAL_STATUSES))
        .order_by(InboundLabel.created_at.desc())
        .first()
    )


def _label_eligibility_for_valuation(valuation):
    amount = valuation.latest_mev_amount
    currency = (valuation.latest_mev_currency or "").upper()
    if amount is None:
        return {
            "eligible": False,
            "reason": "missing_mev",
            "threshold_amount": str(LABEL_MEV_THRESHOLD),
            "threshold_currency": "GBP",
            "white_glove_required": False,
        }

    eligible = currency == "GBP" and amount > LABEL_MEV_THRESHOLD
    white_glove_required = currency == "GBP" and amount > WHITE_GLOVE_MEV_THRESHOLD
    reason = None if eligible else "below_threshold_or_unsupported_currency"
    return {
        "eligible": eligible,
        "reason": reason,
        "threshold_amount": str(LABEL_MEV_THRESHOLD),
        "threshold_currency": "GBP",
        "white_glove_threshold_amount": str(WHITE_GLOVE_MEV_THRESHOLD),
        "white_glove_required": white_glove_required,
    }


def _default_label_routing(valuation, payload):
    destination_country = (
        _required_string(payload, "destination_country")
        or valuation.country
        or "GB"
    )
    currency = (valuation.latest_mev_currency or "").upper() or None
    amount = valuation.latest_mev_amount or Decimal("0")
    white_glove_required = currency == "GBP" and amount > WHITE_GLOVE_MEV_THRESHOLD

    if white_glove_required:
        dispatch_method = "white_glove"
        courier = "rootle_white_glove"
        service_level = "concierge_intake"
    elif str(destination_country).strip().upper() in {"GB", "UK", "UNITED KINGDOM"}:
        dispatch_method = "email"
        courier = "royal_mail"
        service_level = "tracked_return"
    else:
        dispatch_method = "email"
        courier = "international_courier"
        service_level = "standard_inbound"

    return {
        "destination_country": destination_country,
        "dispatch_method": _required_string(payload, "dispatch_method") or dispatch_method,
        "courier": _required_string(payload, "courier") or courier,
        "service_level": _required_string(payload, "service_level") or service_level,
        "white_glove_required": white_glove_required,
    }


def _scan_payload_for_label(rootle_label_id):
    path = f"/api/crm/inbound-labels/scan/{rootle_label_id}"
    base_url = request.url_root.rstrip("/") if request else ""
    return f"{base_url}{path}" if base_url else path


def _attio_webhook_signature_is_valid(raw_body):
    secret = current_app.config.get("ATTIO_WEBHOOK_SECRET")
    if not secret:
        return False

    signature = (
        request.headers.get("Attio-Signature")
        or request.headers.get("X-Attio-Signature")
        or ""
    ).strip()
    if not signature:
        return False

    expected_signature = hmac.new(
        str(secret).encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected_signature)


def _attio_webhook_events(payload):
    events = payload.get("events")
    if isinstance(events, list):
        return [event for event in events if isinstance(event, dict)]

    if payload.get("event_type"):
        return [payload]

    return []


def _attio_deleted_record_id(event):
    event_id = event.get("id")
    if isinstance(event_id, dict):
        return event_id.get("record_id")

    return event.get("record_id")


def _attio_event_matches_valuation_request_object(event):
    expected_object_id = current_app.config.get("ATTIO_VALUATION_REQUEST_OBJECT_ID")
    if not expected_object_id:
        return True

    event_id = event.get("id")
    if not isinstance(event_id, dict):
        return False

    return event_id.get("object_id") == expected_object_id


def _ensure_default_valuation_items():
    existing_count = ValuationItemCategory.query.count()
    if existing_count:
        return

    for index, name in enumerate(DEFAULT_VALUATION_ITEMS):
        db.session.add(
            ValuationItemCategory(
                name=name,
                label=_category_label(name),
                sort_order=index,
            )
        )
    db.session.commit()


def _active_valuation_item_names():
    _ensure_default_valuation_items()
    return [
        item.name
        for item in ValuationItemCategory.query.filter_by(active=True)
        .order_by(ValuationItemCategory.sort_order, ValuationItemCategory.label)
        .all()
    ]


def _valuation_item_to_dict(item):
    return item.to_dict()


@crm_bp.route("/companies", methods=["GET"])
def list_companies():
    companies = Company.query.all()
    return jsonify([company.to_dict() for company in companies])


@crm_bp.route("/companies/<int:company_id>", methods=["GET"])
def get_company(company_id):
    company = Company.query.get_or_404(company_id)
    data = company.to_dict()
    data["contacts"] = [contact.to_dict() for contact in company.contacts]
    data["opportunities"] = [opportunity.to_dict() for opportunity in company.opportunities]
    return jsonify(data)


@crm_bp.route("/companies", methods=["POST"])
def create_company():
    payload = request.get_json() or {}
    company = Company(
        name=payload.get("name"),
        domain=payload.get("domain"),
        website=payload.get("website"),
        industry=payload.get("industry"),
        status=payload.get("status", "prospect"),
        source=payload.get("source"),
        crm_external_id=payload.get("crm_external_id"),
        description=payload.get("description"),
    )
    db.session.add(company)
    db.session.commit()
    return jsonify(company.to_dict()), 201


@crm_bp.route("/journey-phases", methods=["GET"])
def list_journey_phases():
    phases = JourneyPhase.query.order_by(JourneyPhase.order).all()
    return jsonify([phase.to_dict() for phase in phases])


@crm_bp.route("/crm/valuation-items", methods=["GET"])
def list_valuation_items():
    _ensure_default_valuation_items()
    include_inactive = request.args.get("include_inactive", "").lower() in {
        "1",
        "true",
        "yes",
    }
    query = ValuationItemCategory.query
    if not include_inactive:
        query = query.filter_by(active=True)
    items = query.order_by(
        ValuationItemCategory.sort_order,
        ValuationItemCategory.label,
    ).all()
    return jsonify([_valuation_item_to_dict(item) for item in items])


@crm_bp.route("/webhooks/attio", methods=["POST"])
def handle_attio_webhook():
    raw_body = request.get_data()
    if not _attio_webhook_signature_is_valid(raw_body):
        return jsonify({"error": "invalid_webhook_signature"}), 401

    payload = request.get_json(silent=True) or {}
    deleted_record_ids = []
    deleted_valuations = []
    ignored_events = 0

    for event in _attio_webhook_events(payload):
        if event.get("event_type") != "record.deleted":
            ignored_events += 1
            continue

        if not _attio_event_matches_valuation_request_object(event):
            ignored_events += 1
            continue

        record_id = _attio_deleted_record_id(event)
        if not record_id:
            ignored_events += 1
            continue

        deleted_record_ids.append(record_id)
        valuation = LeadValuation.query.filter_by(
            crm_valuation_request_id=record_id,
        ).first()
        if not valuation:
            continue

        deleted_valuations.append(_valuation_to_dict(valuation))
        db.session.delete(valuation)

    db.session.commit()

    return jsonify(
        {
            "deleted_attio_record_ids": deleted_record_ids,
            "deleted_erp_valuations": deleted_valuations,
            "deleted_erp_valuation_count": len(deleted_valuations),
            "ignored_event_count": ignored_events,
        }
    )


@crm_bp.route("/crm/valuation-items", methods=["POST"])
def add_valuation_item():
    payload = request.get_json() or {}
    name = _category_slug(payload.get("name") or payload.get("item") or payload.get("slug"))
    label = _required_string(payload, "label")
    description = _required_string(payload, "description")
    sort_order = payload.get("sort_order")

    if not name:
        return jsonify({"error": "missing_required_fields", "fields": ["name"]}), 400

    item = ValuationItemCategory.query.filter_by(name=name).first()
    status_code = 200
    if not item:
        last_item = ValuationItemCategory.query.order_by(
            ValuationItemCategory.sort_order.desc()
        ).first()
        next_sort_order = (last_item.sort_order + 1) if last_item else 0
        item = ValuationItemCategory(
            name=name,
            label=label or _category_label(name),
            sort_order=next_sort_order,
        )
        db.session.add(item)
        status_code = 201

    item.label = label or item.label or _category_label(name)
    item.description = description if description is not None else item.description
    item.active = True
    if sort_order is not None:
        try:
            item.sort_order = int(sort_order)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid_sort_order"}), 400

    try:
        from attio import ensure_valuation_request_item_options

        ensure_valuation_request_item_options([item.name])
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": "attio_option_sync_failed",
                    "message": str(exc),
                }
            ),
            502,
        )

    db.session.commit()

    return jsonify({"item": _valuation_item_to_dict(item)}), status_code


@crm_bp.route("/crm/valuation-items/<item_name>", methods=["DELETE"])
def remove_valuation_item(item_name):
    name = _category_slug(item_name)
    item = ValuationItemCategory.query.filter_by(name=name).first()
    if not item:
        return jsonify({"error": "valuation_item_not_found", "item": name}), 404

    item.active = False
    db.session.commit()
    return jsonify({"item": _valuation_item_to_dict(item), "removed": True})


@crm_bp.route("/leads", methods=["GET"])
def list_leads():
    leads = Lead.query.all()
    return jsonify([lead.to_dict() for lead in leads])


@crm_bp.route("/leads/<int:lead_id>", methods=["GET"])
def get_lead(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    data = lead.to_dict()
    data["box_details"] = [detail.to_dict() for detail in lead.box_details]
    data["estimates"] = [estimate.to_dict() for estimate in lead.estimates]
    return jsonify(data)


@crm_bp.route("/crm/leads/stage-1", methods=["POST"])
def submit_stage_1_crm_lead():
    payload = request.get_json() or {}
    name = _required_string(payload, "name")
    phone_number = _required_string(payload, "phone_number")
    posthog_distinct_id = _required_string(payload, "posthog_distinct_id")

    missing_fields = [
        field
        for field, value in (
            ("name", name),
            ("phone_number", phone_number),
            ("posthog_distinct_id", posthog_distinct_id),
        )
        if not value
    ]
    if missing_fields:
        return jsonify({"error": "missing_required_fields", "fields": missing_fields}), 400

    try:
        from attio import get_or_create_attio_stage_1_lead

        crm_result = get_or_create_attio_stage_1_lead(
            name=name,
            phone_number=phone_number,
            posthog_distinct_id=posthog_distinct_id,
        )
    except Exception as exc:
        return jsonify({"error": "crm_sync_failed", "message": str(exc)}), 502

    status_code = 201 if crm_result["created"] else 200
    return jsonify(
        {
            "crm_system": "attio",
            "attio_id": crm_result["record_id"],
            "crm_record_id": crm_result["record_id"],
            "stage": "stage-1",
            "erp_lead_created": False,
            "attio_record_created": crm_result["created"],
        }
    ), status_code


@crm_bp.route("/crm/valuation-requests", methods=["POST"])
def submit_item_for_valuation():
    payload = request.get_json() or {}
    person_record_id = (
        _required_string(payload, "attio_id")
        or _required_string(payload, "crm_person_record_id")
        or _required_string(payload, "crm_record_id")
    )
    item_categories = _string_list(payload, "item_categories", "items")
    item_photo_url = (
        _required_string(payload, "item_photo_url")
        or _required_string(payload, "picture_url")
        or _required_string(payload, "photo_url")
    )
    posthog_distinct_id = _required_string(payload, "posthog_distinct_id")
    rootle_request_id = _required_string(payload, "rootle_request_id") or f"rv-{uuid4().hex}"
    source = _required_string(payload, "source") or "lovable"
    valuation_guide_id = _required_string(payload, "valuation_guide_id")
    valuation_guide_url = _required_string(payload, "valuation_guide_url")

    missing_fields = [
        field
        for field, value in (
            ("attio_id", person_record_id),
            ("item_categories", item_categories),
            ("item_photo_url", item_photo_url),
        )
        if not value
    ]
    if missing_fields:
        return jsonify({"error": "missing_required_fields", "fields": missing_fields}), 400

    item_categories = [_category_slug(category) for category in item_categories]
    item_categories = [category for category in item_categories if category]
    item_categories = _merge_unique_values([], item_categories)
    if not item_categories:
        return jsonify({"error": "missing_required_fields", "fields": ["item_categories"]}), 400

    allowed_categories = _active_valuation_item_names()
    unknown_categories = [
        category for category in item_categories if category not in allowed_categories
    ]
    if unknown_categories:
        return (
            jsonify(
                {
                    "error": "invalid_item_categories",
                    "allowed_values": allowed_categories,
                    "values": unknown_categories,
                }
            ),
            400,
        )

    existing = LeadValuation.query.filter_by(rootle_request_id=rootle_request_id).first()
    if existing:
        merged_categories = _merge_unique_values(existing.item_categories, item_categories)
        erp_valuation_updated = merged_categories != (existing.item_categories or [])
        if erp_valuation_updated:
            try:
                from attio import update_attio_valuation_request

                update_attio_valuation_request(
                    valuation_request_id=existing.crm_valuation_request_id,
                    person_record_id=existing.crm_person_record_id,
                    rootle_request_id=existing.rootle_request_id,
                    item_categories=merged_categories,
                    item_photo_url=existing.item_photo_url,
                    posthog_distinct_id=existing.posthog_distinct_id,
                    valuation_guide_id=existing.valuation_guide_id,
                    valuation_guide_url=existing.valuation_guide_url,
                    source=existing.source,
                )
            except Exception as exc:
                return jsonify({"error": "crm_sync_failed", "message": str(exc)}), 502

            existing.item_categories = merged_categories
            db.session.commit()

        return (
            jsonify(
                {
                    "valuation": _valuation_to_dict(existing),
                    "attio_valuation_request_id": existing.crm_valuation_request_id,
                    "erp_valuation_created": False,
                    "erp_valuation_updated": erp_valuation_updated,
                }
            ),
            200,
        )

    try:
        from attio import create_attio_valuation_request

        crm_valuation_request_id = create_attio_valuation_request(
            person_record_id=person_record_id,
            rootle_request_id=rootle_request_id,
            item_categories=item_categories,
            item_photo_url=item_photo_url,
            posthog_distinct_id=posthog_distinct_id,
            valuation_guide_id=valuation_guide_id,
            valuation_guide_url=valuation_guide_url,
            source=source,
        )
    except Exception as exc:
        return jsonify({"error": "crm_sync_failed", "message": str(exc)}), 502

    valuation = LeadValuation(
        crm_person_record_id=person_record_id,
        crm_valuation_request_id=crm_valuation_request_id,
        rootle_request_id=rootle_request_id,
        posthog_distinct_id=posthog_distinct_id,
        item_categories=item_categories,
        item_photo_url=item_photo_url,
        valuation_guide_id=valuation_guide_id,
        valuation_guide_url=valuation_guide_url,
        source=source,
        meta=payload.get("metadata"),
    )
    db.session.add(valuation)
    db.session.commit()

    return (
        jsonify(
            {
                "valuation": _valuation_to_dict(valuation),
                "attio_valuation_request_id": crm_valuation_request_id,
                "erp_valuation_created": True,
            }
        ),
        201,
    )


@crm_bp.route("/crm/valuation-requests/<int:valuation_id>/mev-calculations", methods=["POST"])
def add_valuation_mev_calculation(valuation_id):
    valuation = LeadValuation.query.get_or_404(valuation_id)
    payload = request.get_json() or {}
    amount = _decimal_value(payload, "amount")
    currency = (_required_string(payload, "currency") or "").upper()
    margin = _decimal_value(payload, "margin")
    calculation_method = _required_string(payload, "calculation_method")
    calculated_by = _required_string(payload, "calculated_by")
    notes = _required_string(payload, "notes")
    calculated_at = datetime.utcnow()

    missing_fields = [
        field
        for field, value in (
            ("amount", amount),
            ("currency", currency),
            ("margin", margin),
        )
        if value is None or value == ""
    ]
    if missing_fields:
        return jsonify({"error": "missing_required_fields", "fields": missing_fields}), 400

    if amount < 0:
        return jsonify({"error": "invalid_amount", "message": "amount must be zero or greater"}), 400

    if len(currency) != 3 or not currency.isalpha():
        return jsonify({"error": "invalid_currency", "message": "currency must be a 3-letter ISO code"}), 400

    if margin < 0:
        return jsonify({"error": "invalid_margin", "message": "margin must be zero or greater"}), 400

    calculation = LeadValuationMevCalculation(
        valuation=valuation,
        amount=amount,
        currency=currency,
        margin=margin,
        calculation_method=calculation_method,
        calculated_by=calculated_by,
        calculated_at=calculated_at,
        notes=notes,
        inputs=payload.get("inputs"),
        meta=payload.get("metadata"),
    )
    valuation.latest_mev_amount = amount
    valuation.latest_mev_currency = currency
    valuation.latest_mev_margin = margin
    valuation.latest_mev_calculated_at = calculated_at
    valuation.status = "mev_calculated"

    db.session.add(calculation)
    db.session.flush()

    try:
        from attio import update_attio_valuation_request_mev

        update_attio_valuation_request_mev(
            valuation_request_id=valuation.crm_valuation_request_id,
            amount=amount,
            currency=currency,
            margin=margin,
            calculated_at=calculated_at,
        )
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": "crm_sync_failed", "message": str(exc)}), 502

    db.session.commit()

    return (
        jsonify(
            {
                "valuation": _valuation_to_dict(valuation),
                "mev_calculation": _mev_calculation_to_dict(calculation),
            }
        ),
        201,
    )


@crm_bp.route("/crm/valuation-requests/<int:valuation_id>/inbound-labels", methods=["POST"])
def create_inbound_label(valuation_id):
    valuation = LeadValuation.query.get_or_404(valuation_id)
    payload = request.get_json() or {}
    eligibility = _label_eligibility_for_valuation(valuation)
    force_create = _bool_value(payload, "force")

    if not eligibility["eligible"] and not force_create:
        return (
            jsonify(
                {
                    "error": "valuation_not_label_eligible",
                    "label_eligibility": eligibility,
                }
            ),
            400,
        )

    existing_label = _active_label_for_valuation(valuation)
    if existing_label:
        return (
            jsonify(
                {
                    "label": _label_to_dict(existing_label, include_context=True),
                    "label_created": False,
                    "label_eligibility": eligibility,
                }
            ),
            200,
        )

    rootle_label_id = _required_string(payload, "rootle_label_id") or f"lbl-{uuid4().hex}"
    routing = _default_label_routing(valuation, payload)
    now = datetime.utcnow()
    generated_at = now if payload.get("label_url") else None
    sent_at = now if _bool_value(payload, "mark_sent") else None
    status = _required_string(payload, "status")
    if not status:
        status = "sent" if sent_at else "generated" if generated_at else "label_requested"

    label = InboundLabel(
        rootle_label_id=rootle_label_id,
        lead_valuation_id=valuation.id,
        crm_person_record_id=valuation.crm_person_record_id,
        crm_valuation_request_id=valuation.crm_valuation_request_id,
        rootle_request_id=valuation.rootle_request_id,
        status=status,
        dispatch_method=routing["dispatch_method"],
        courier=routing["courier"],
        service_level=routing["service_level"],
        tracking_number=_required_string(payload, "tracking_number"),
        label_url=_required_string(payload, "label_url"),
        barcode_value=rootle_label_id,
        qr_payload=_scan_payload_for_label(rootle_label_id),
        destination_country=routing["destination_country"],
        currency=valuation.latest_mev_currency,
        mev_amount=valuation.latest_mev_amount,
        white_glove_required=routing["white_glove_required"],
        requested_at=now,
        generated_at=generated_at,
        sent_at=sent_at,
        expires_at=now + timedelta(days=30),
        meta=payload.get("metadata"),
    )
    db.session.add(label)
    valuation.current_stage = "inbound_label_created"
    valuation.status = "inbound_label_created"
    db.session.commit()

    return (
        jsonify(
            {
                "label": _label_to_dict(label, include_context=True),
                "label_created": True,
                "label_eligibility": eligibility,
            }
        ),
        201,
    )


@crm_bp.route("/crm/inbound-labels/<rootle_label_id>", methods=["GET", "PATCH"])
def manage_inbound_label(rootle_label_id):
    label = InboundLabel.query.filter_by(rootle_label_id=rootle_label_id).first_or_404()

    if request.method == "GET":
        return jsonify({"label": _label_to_dict(label, include_context=True)})

    payload = request.get_json() or {}
    status = _required_string(payload, "status")
    now = datetime.utcnow()

    if status:
        label.status = status
        if status == "generated":
            label.generated_at = label.generated_at or now
        elif status == "sent":
            label.sent_at = label.sent_at or now
        elif status in {"used", "label_scanned"}:
            label.used_at = label.used_at or now
            label.status = "label_scanned"
        elif status == "received":
            label.received_at = label.received_at or now
        elif status == "cancelled":
            label.cancelled_at = label.cancelled_at or now

    for key in ("courier", "service_level", "tracking_number", "label_url"):
        value = _required_string(payload, key)
        if value:
            setattr(label, key, value)

    if payload.get("metadata") is not None:
        label.meta = payload.get("metadata")

    if label.label_url and not label.generated_at:
        label.generated_at = now

    db.session.commit()
    return jsonify({"label": _label_to_dict(label, include_context=True)})


@crm_bp.route("/crm/inbound-labels/scan/<barcode_value>", methods=["GET", "POST"])
def scan_inbound_label(barcode_value):
    label = InboundLabel.query.filter_by(barcode_value=barcode_value).first_or_404()

    if request.method == "POST":
        label.used_at = label.used_at or datetime.utcnow()
        if label.status not in {"received", "cancelled", "expired"}:
            label.status = "label_scanned"
        db.session.commit()

    return jsonify({"label": _label_to_dict(label, include_context=True)})


@crm_bp.route("/crm/contact-details", methods=["POST"])
def submit_contact_details():
    payload = request.get_json() or {}
    person_record_id = (
        _required_string(payload, "attio_id")
        or _required_string(payload, "crm_person_record_id")
        or _required_string(payload, "crm_record_id")
    )
    email = _required_string(payload, "email")
    address_line_1 = _required_string(payload, "address_line_1")
    address_line_2 = _required_string(payload, "address_line_2")
    city = _required_string(payload, "city")
    postcode = _required_string(payload, "postcode")
    country = _required_string(payload, "country")
    crm_valuation_request_id = (
        _required_string(payload, "attio_valuation_request_id")
        or _required_string(payload, "crm_valuation_request_id")
    )
    now = datetime.utcnow()

    if not person_record_id:
        return jsonify({"error": "missing_required_fields", "fields": ["attio_id"]}), 400

    if not email and not any([address_line_1, address_line_2, city, postcode, country]):
        return (
            jsonify(
                {
                    "error": "missing_required_fields",
                    "fields": ["email_or_address"],
                }
            ),
            400,
        )

    try:
        from attio import update_attio_person_contact_details

        update_attio_person_contact_details(
            person_record_id=person_record_id,
            email=email,
            address_line_1=address_line_1,
            address_line_2=address_line_2,
            city=city,
            postcode=postcode,
            country=country,
        )
    except Exception as exc:
        return jsonify({"error": "crm_sync_failed", "message": str(exc)}), 502

    query = LeadValuation.query.filter_by(crm_person_record_id=person_record_id)
    if crm_valuation_request_id:
        query = query.filter_by(crm_valuation_request_id=crm_valuation_request_id)
    valuations = query.all()

    for valuation in valuations:
        valuation.customer_email = email or valuation.customer_email
        valuation.address_line_1 = address_line_1 or valuation.address_line_1
        valuation.address_line_2 = address_line_2 or valuation.address_line_2
        valuation.city = city or valuation.city
        valuation.postcode = postcode or valuation.postcode
        valuation.country = country or valuation.country
        valuation.contact_details_received_at = now
        valuation.stage_3_completed_at = now
        valuation.current_stage = "contact_details_received"
        valuation.status = "customer_details_received"

    db.session.commit()

    return jsonify(
        {
            "attio_id": person_record_id,
            "crm_person_record_id": person_record_id,
            "updated_erp_valuations": [_valuation_to_dict(item) for item in valuations],
        }
    )


@crm_bp.route("/leads", methods=["POST"])
def create_lead():
    payload = request.get_json() or {}
    lead = Lead(
        first_name=payload.get("first_name"),
        last_name=payload.get("last_name"),
        phone=payload.get("phone"),
        email=payload.get("email"),
        source=payload.get("source"),
        preferred_contact_method=payload.get("preferred_contact_method"),
        crm_system=payload.get("crm_system", "attio"),
        crm_record_id=payload.get("crm_record_id") or payload.get("attio_record_id"),
        meta=payload.get("metadata"),
        status=payload.get("status", "open"),
        stage=payload.get("stage", "stage-1"),
    )
    db.session.add(lead)
    db.session.commit()

    if lead.stage == "stage-1" and lead.crm_system == "attio" and not lead.crm_record_id:
        try:
            from attio import create_attio_lead

            crm_record_id = create_attio_lead(lead)
            lead.crm_record_id = crm_record_id
            db.session.commit()
        except Exception as exc:
            # Attio failures should not block lead creation
            print(f"Attio integration failed: {exc}")

    return jsonify(lead.to_dict()), 201


@crm_bp.route("/leads/<int:lead_id>/box-details", methods=["POST"])
def add_lead_box_detail(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    payload = request.get_json() or {}
    detail = LeadBoxDetail(
        lead=lead,
        box_type=payload.get("box_type"),
        condition=payload.get("condition"),
        item_description=payload.get("item_description"),
        photo_urls=payload.get("photo_urls"),
        attachments=payload.get("attachments"),
        notes=payload.get("notes"),
        source=payload.get("source"),
    )
    lead.stage = "stage-2"
    db.session.add(detail)
    db.session.commit()

    try:
        from attio import update_attio_lead

        crm_record_id = update_attio_lead(lead)
        lead.crm_system = "attio"
        lead.crm_record_id = crm_record_id
        db.session.commit()
    except Exception as exc:
        # Attio failures should not block lead workflow progress
        print(f"Attio integration failed: {exc}")

    return jsonify(detail.to_dict()), 201


@crm_bp.route("/leads/<int:lead_id>/box-details/<int:box_detail_id>/revisions", methods=["POST"])
def add_lead_box_revision(lead_id, box_detail_id):
    lead = Lead.query.get_or_404(lead_id)
    box_detail = LeadBoxDetail.query.filter_by(id=box_detail_id, lead_id=lead.id).first_or_404()
    payload = request.get_json() or {}
    revision = LeadBoxRevision(
        lead=lead,
        box_detail=box_detail,
        revision_type=payload.get("revision_type", "more_photos"),
        additional_description=payload.get("additional_description"),
        photo_urls=payload.get("photo_urls"),
        attachments=payload.get("attachments"),
        notes=payload.get("notes"),
        status=payload.get("status", "pending"),
    )
    db.session.add(revision)
    db.session.commit()
    return jsonify(revision.to_dict()), 201


@crm_bp.route("/leads/<int:lead_id>/estimates", methods=["POST"])
def create_lead_estimate(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    payload = request.get_json() or {}
    estimate = LeadEstimate(
        lead=lead,
        box_detail_id=payload.get("box_detail_id"),
        box_revision_id=payload.get("box_revision_id"),
        estimated_value=payload.get("estimated_value", 0.0),
        estimate_status=payload.get("estimate_status", "pending"),
        pricing_metadata=payload.get("pricing_metadata"),
        accepted=payload.get("accepted", False),
        expires_at=payload.get("expires_at"),
    )
    db.session.add(estimate)
    db.session.commit()
    return jsonify(estimate.to_dict()), 201
