from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import re
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import text

from database import db
from models import (
    Company,
    Contact,
    FailedValuationRequestSubmission,
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
RESET_CONFIRMATION = "DELETE ROOTLE ERP DATA"


def _required_string(payload, key):
    value = payload.get(key)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _sync_person_posthog_distinct_id(*, person_record_id, posthog_distinct_id):
    if not person_record_id or not posthog_distinct_id:
        return

    import attio

    sync = getattr(attio, "update_attio_person_posthog_distinct_id", None)
    if sync:
        sync(
            person_record_id=person_record_id,
            posthog_distinct_id=posthog_distinct_id,
        )


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


def _failed_valuation_request_submission_to_dict(submission):
    return submission.to_dict()


def _record_failed_valuation_request_submission(
    *,
    payload,
    normalised_payload,
    error_type,
    error_message,
):
    db.session.rollback()
    submission = FailedValuationRequestSubmission(
        rootle_request_id=(normalised_payload or {}).get("rootle_request_id"),
        crm_person_record_id=(normalised_payload or {}).get("crm_person_record_id"),
        posthog_distinct_id=(normalised_payload or {}).get("posthog_distinct_id"),
        payload=payload or {},
        normalised_payload=normalised_payload,
        error_type=error_type,
        error_message=str(error_message),
    )
    db.session.add(submission)
    db.session.commit()
    return submission


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


def _reset_token_is_valid(payload):
    expected_token = current_app.config.get("ROOTLE_RESET_TOKEN")
    if not expected_token:
        return False

    provided_token = (
        request.headers.get("X-Reset-Token")
        or request.headers.get("X-Rootle-Reset-Token")
        or _required_string(payload, "reset_token")
        or ""
    ).strip()
    return bool(provided_token) and hmac.compare_digest(provided_token, expected_token)


def _truncate_application_tables():
    tables = list(reversed(db.metadata.sorted_tables))
    table_names = [table.name for table in tables]
    dialect_name = db.engine.dialect.name

    if dialect_name == "postgresql":
        preparer = db.engine.dialect.identifier_preparer
        quoted_table_names = [
            (
                f"{preparer.quote_schema(table.schema)}.{preparer.quote(table.name)}"
                if table.schema
                else preparer.quote(table.name)
            )
            for table in tables
        ]
        if quoted_table_names:
            db.session.execute(
                text(
                    "TRUNCATE TABLE "
                    + ", ".join(quoted_table_names)
                    + " RESTART IDENTITY CASCADE"
                )
            )
    else:
        for table in tables:
            db.session.execute(table.delete())

    db.session.commit()
    return table_names


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


@crm_bp.route("/admin/reset-data", methods=["POST"])
def reset_all_data():
    payload = request.get_json(silent=True) or {}
    if not _reset_token_is_valid(payload):
        return (
            jsonify(
                {
                    "error": "reset_unauthorized",
                    "message": "A valid reset token is required.",
                }
            ),
            401,
        )

    if _required_string(payload, "confirmation") != RESET_CONFIRMATION:
        return (
            jsonify(
                {
                    "error": "confirmation_required",
                    "confirmation": RESET_CONFIRMATION,
                }
            ),
            400,
        )

    include_attio = not _bool_value(payload, "skip_attio")
    attio_result = None
    if include_attio:
        try:
            from attio import delete_all_attio_records

            attio_result = delete_all_attio_records()
        except Exception as exc:
            return jsonify({"error": "attio_reset_failed", "message": str(exc)}), 502

    truncated_tables = _truncate_application_tables()

    return jsonify(
        {
            "reset": True,
            "attio_deleted": include_attio,
            "attio": attio_result,
            "database": {
                "truncated_table_count": len(truncated_tables),
                "truncated_tables": truncated_tables,
            },
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
    normalised_payload = {
        "crm_person_record_id": person_record_id,
        "item_categories": item_categories,
        "item_photo_url": item_photo_url,
        "posthog_distinct_id": posthog_distinct_id,
        "rootle_request_id": rootle_request_id,
        "source": source,
        "valuation_guide_id": valuation_guide_id,
        "valuation_guide_url": valuation_guide_url,
        "metadata": payload.get("metadata"),
    }

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
    normalised_payload["item_categories"] = item_categories
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
        posthog_valuation_updated = bool(posthog_distinct_id and not existing.posthog_distinct_id)
        if posthog_distinct_id and not existing.posthog_distinct_id:
            existing.posthog_distinct_id = posthog_distinct_id
        erp_valuation_updated = (
            merged_categories != (existing.item_categories or [])
            or posthog_valuation_updated
        )
        if erp_valuation_updated or posthog_distinct_id:
            try:
                from attio import update_attio_valuation_request

                update_attio_valuation_request(
                    valuation_request_id=existing.crm_valuation_request_id,
                    person_record_id=existing.crm_person_record_id,
                    rootle_request_id=existing.rootle_request_id,
                    item_categories=merged_categories,
                    item_photo_url=existing.item_photo_url,
                    posthog_distinct_id=existing.posthog_distinct_id or posthog_distinct_id,
                    valuation_guide_id=existing.valuation_guide_id,
                    valuation_guide_url=existing.valuation_guide_url,
                    source=existing.source,
                )
                _sync_person_posthog_distinct_id(
                    person_record_id=existing.crm_person_record_id,
                    posthog_distinct_id=existing.posthog_distinct_id or posthog_distinct_id,
                )
            except Exception as exc:
                failed_submission = _record_failed_valuation_request_submission(
                    payload=payload,
                    normalised_payload=normalised_payload,
                    error_type="crm_sync_failed",
                    error_message=exc,
                )
                return (
                    jsonify(
                        {
                            "error": "crm_sync_failed",
                            "message": str(exc),
                            "failed_submission": _failed_valuation_request_submission_to_dict(
                                failed_submission
                            ),
                        }
                    ),
                    502,
                )

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

        _sync_person_posthog_distinct_id(
            person_record_id=person_record_id,
            posthog_distinct_id=posthog_distinct_id,
        )
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
        failed_submission = _record_failed_valuation_request_submission(
            payload=payload,
            normalised_payload=normalised_payload,
            error_type="crm_sync_failed",
            error_message=exc,
        )
        return (
            jsonify(
                {
                    "error": "crm_sync_failed",
                    "message": str(exc),
                    "failed_submission": _failed_valuation_request_submission_to_dict(
                        failed_submission
                    ),
                }
            ),
            502,
        )

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


@crm_bp.route("/crm/valuation-requests", methods=["GET"])
def list_valuation_requests():
    query = LeadValuation.query

    status = _required_string(request.args, "status")
    current_stage = _required_string(request.args, "current_stage")
    pricing_status = _required_string(request.args, "pricing_status")
    person_record_id = (
        _required_string(request.args, "attio_id")
        or _required_string(request.args, "crm_person_record_id")
        or _required_string(request.args, "crm_record_id")
    )
    crm_valuation_request_id = (
        _required_string(request.args, "attio_valuation_request_id")
        or _required_string(request.args, "crm_valuation_request_id")
    )
    rootle_request_id = _required_string(request.args, "rootle_request_id")
    needs_mev = _bool_value(request.args, "needs_mev")

    if status:
        query = query.filter_by(status=status)
    if current_stage:
        query = query.filter_by(current_stage=current_stage)
    if pricing_status:
        query = query.filter_by(pricing_status=pricing_status)
    if person_record_id:
        query = query.filter_by(crm_person_record_id=person_record_id)
    if crm_valuation_request_id:
        query = query.filter_by(crm_valuation_request_id=crm_valuation_request_id)
    if rootle_request_id:
        query = query.filter_by(rootle_request_id=rootle_request_id)
    if needs_mev:
        query = query.filter(LeadValuation.latest_mev_amount.is_(None))

    try:
        limit = min(int(request.args.get("limit", 50)), 100)
        offset = max(int(request.args.get("offset", 0)), 0)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_pagination"}), 400

    total = query.count()
    valuations = (
        query.order_by(LeadValuation.created_at.desc(), LeadValuation.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    return jsonify(
        {
            "valuations": [_valuation_to_dict(valuation) for valuation in valuations],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    )


@crm_bp.route("/crm/valuation-request-failures", methods=["GET"])
def list_failed_valuation_request_submissions():
    query = FailedValuationRequestSubmission.query

    status = _required_string(request.args, "status")
    rootle_request_id = _required_string(request.args, "rootle_request_id")
    person_record_id = (
        _required_string(request.args, "attio_id")
        or _required_string(request.args, "crm_person_record_id")
        or _required_string(request.args, "crm_record_id")
    )

    if status:
        query = query.filter_by(status=status)
    if rootle_request_id:
        query = query.filter_by(rootle_request_id=rootle_request_id)
    if person_record_id:
        query = query.filter_by(crm_person_record_id=person_record_id)

    try:
        limit = min(int(request.args.get("limit", 50)), 100)
        offset = max(int(request.args.get("offset", 0)), 0)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_pagination"}), 400

    total = query.count()
    submissions = (
        query.order_by(
            FailedValuationRequestSubmission.created_at.desc(),
            FailedValuationRequestSubmission.id.desc(),
        )
        .limit(limit)
        .offset(offset)
        .all()
    )

    return jsonify(
        {
            "failed_submissions": [
                _failed_valuation_request_submission_to_dict(submission)
                for submission in submissions
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    )


@crm_bp.route("/crm/valuation-request-failures/<int:submission_id>", methods=["GET"])
def get_failed_valuation_request_submission(submission_id):
    submission = FailedValuationRequestSubmission.query.get_or_404(submission_id)
    return jsonify(
        {
            "failed_submission": _failed_valuation_request_submission_to_dict(
                submission
            )
        }
    )


@crm_bp.route("/crm/valuation-request-failures/<int:submission_id>/retry", methods=["POST"])
def retry_failed_valuation_request_submission(submission_id):
    submission = FailedValuationRequestSubmission.query.get_or_404(submission_id)
    if submission.status == "resolved":
        return (
            jsonify(
                {
                    "error": "failed_submission_already_resolved",
                    "failed_submission": _failed_valuation_request_submission_to_dict(
                        submission
                    ),
                }
            ),
            409,
        )

    normalised_payload = submission.normalised_payload or {}
    required_fields = [
        "crm_person_record_id",
        "item_categories",
        "item_photo_url",
        "rootle_request_id",
    ]
    missing_fields = [
        field for field in required_fields if not normalised_payload.get(field)
    ]
    if missing_fields:
        submission.status = "invalid_payload"
        submission.error_type = "missing_required_fields"
        submission.error_message = f"Missing replay fields: {', '.join(missing_fields)}"
        submission.retry_count += 1
        submission.last_retry_at = datetime.utcnow()
        db.session.commit()
        return (
            jsonify(
                {
                    "error": "missing_required_fields",
                    "fields": missing_fields,
                    "failed_submission": _failed_valuation_request_submission_to_dict(
                        submission
                    ),
                }
            ),
            400,
        )

    existing = LeadValuation.query.filter_by(
        rootle_request_id=normalised_payload["rootle_request_id"]
    ).first()
    if existing:
        submission.status = "resolved"
        submission.resolved_at = datetime.utcnow()
        submission.valuation_request_id = existing.id
        submission.crm_valuation_request_id = existing.crm_valuation_request_id
        db.session.commit()
        return jsonify(
            {
                "valuation": _valuation_to_dict(existing),
                "failed_submission": _failed_valuation_request_submission_to_dict(
                    submission
                ),
                "replayed": False,
                "reason": "valuation_request_already_exists",
            }
        )

    submission.retry_count += 1
    submission.last_retry_at = datetime.utcnow()
    submission.status = "retrying"
    db.session.commit()

    try:
        from attio import create_attio_valuation_request

        _sync_person_posthog_distinct_id(
            person_record_id=normalised_payload["crm_person_record_id"],
            posthog_distinct_id=normalised_payload.get("posthog_distinct_id"),
        )
        crm_valuation_request_id = create_attio_valuation_request(
            person_record_id=normalised_payload["crm_person_record_id"],
            rootle_request_id=normalised_payload["rootle_request_id"],
            item_categories=normalised_payload["item_categories"],
            item_photo_url=normalised_payload["item_photo_url"],
            posthog_distinct_id=normalised_payload.get("posthog_distinct_id"),
            valuation_guide_id=normalised_payload.get("valuation_guide_id"),
            valuation_guide_url=normalised_payload.get("valuation_guide_url"),
            source=normalised_payload.get("source"),
        )
    except Exception as exc:
        db.session.rollback()
        submission = FailedValuationRequestSubmission.query.get_or_404(submission_id)
        submission.status = "pending_retry"
        submission.error_type = "crm_sync_failed"
        submission.error_message = str(exc)
        db.session.commit()
        return (
            jsonify(
                {
                    "error": "crm_sync_failed",
                    "message": str(exc),
                    "failed_submission": _failed_valuation_request_submission_to_dict(
                        submission
                    ),
                }
            ),
            502,
        )

    valuation = LeadValuation(
        crm_person_record_id=normalised_payload["crm_person_record_id"],
        crm_valuation_request_id=crm_valuation_request_id,
        rootle_request_id=normalised_payload["rootle_request_id"],
        posthog_distinct_id=normalised_payload.get("posthog_distinct_id"),
        item_categories=normalised_payload["item_categories"],
        item_photo_url=normalised_payload["item_photo_url"],
        valuation_guide_id=normalised_payload.get("valuation_guide_id"),
        valuation_guide_url=normalised_payload.get("valuation_guide_url"),
        source=normalised_payload.get("source"),
        meta=normalised_payload.get("metadata"),
    )
    db.session.add(valuation)
    db.session.flush()

    submission.status = "resolved"
    submission.resolved_at = datetime.utcnow()
    submission.valuation_request_id = valuation.id
    submission.crm_valuation_request_id = crm_valuation_request_id
    db.session.commit()

    return jsonify(
        {
            "valuation": _valuation_to_dict(valuation),
            "failed_submission": _failed_valuation_request_submission_to_dict(
                submission
            ),
            "replayed": True,
        }
    ), 201


@crm_bp.route("/crm/valuation-requests/<int:valuation_id>", methods=["GET"])
def get_valuation_request(valuation_id):
    valuation = LeadValuation.query.get_or_404(valuation_id)
    return jsonify({"valuation": _valuation_to_dict(valuation)})


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
    valuation.pricing_status = "mev_calculated"
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
            pricing_status=valuation.pricing_status,
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


@crm_bp.route("/crm/valuation-requests/<int:valuation_id>/mev-sync", methods=["POST"])
def sync_valuation_mev_to_attio(valuation_id):
    valuation = LeadValuation.query.get_or_404(valuation_id)

    missing_fields = [
        field
        for field, value in (
            ("latest_mev_amount", valuation.latest_mev_amount),
            ("latest_mev_currency", valuation.latest_mev_currency),
            ("latest_mev_margin", valuation.latest_mev_margin),
            ("latest_mev_calculated_at", valuation.latest_mev_calculated_at),
        )
        if value is None or value == ""
    ]
    if missing_fields:
        return jsonify({"error": "missing_latest_mev", "fields": missing_fields}), 400

    if not valuation.crm_valuation_request_id:
        return (
            jsonify(
                {
                    "error": "missing_crm_valuation_request_id",
                    "message": "Valuation is not linked to an Attio valuation request.",
                }
            ),
            400,
        )

    try:
        from attio import update_attio_valuation_request_mev

        update_attio_valuation_request_mev(
            valuation_request_id=valuation.crm_valuation_request_id,
            amount=valuation.latest_mev_amount,
            currency=valuation.latest_mev_currency,
            margin=valuation.latest_mev_margin,
            calculated_at=valuation.latest_mev_calculated_at,
            pricing_status=valuation.pricing_status,
        )
    except Exception as exc:
        return jsonify({"error": "crm_sync_failed", "message": str(exc)}), 502

    return jsonify(
        {
            "valuation": _valuation_to_dict(valuation),
            "attio_valuation_request_id": valuation.crm_valuation_request_id,
            "mev_synced": True,
        }
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
