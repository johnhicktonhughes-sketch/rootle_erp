from datetime import datetime
from uuid import uuid4

from flask import Blueprint, jsonify, request

from database import db
from models import (
    Company,
    Contact,
    JourneyPhase,
    Lead,
    LeadBoxDetail,
    LeadBoxRevision,
    LeadEstimate,
    LeadValuation,
)

crm_bp = Blueprint("crm", __name__)


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
        if not isinstance(value, list):
            return None

        items = [str(item).strip() for item in value if str(item).strip()]
        return items or None

    return None


def _valuation_to_dict(valuation):
    return valuation.to_dict()


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

    unknown_categories = [
        category
        for category in item_categories
        if category not in {"gold", "silver", "coins"}
    ]
    if unknown_categories:
        return (
            jsonify(
                {
                    "error": "invalid_item_categories",
                    "allowed_values": ["gold", "silver", "coins"],
                    "values": unknown_categories,
                }
            ),
            400,
        )

    existing = LeadValuation.query.filter_by(rootle_request_id=rootle_request_id).first()
    if existing:
        return (
            jsonify(
                {
                    "valuation": _valuation_to_dict(existing),
                    "attio_valuation_request_id": existing.crm_valuation_request_id,
                    "erp_valuation_created": False,
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
