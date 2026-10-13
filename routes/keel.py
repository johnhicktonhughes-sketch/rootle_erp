"""Explicit handover after a customer accepts their indicative offer."""

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request
import requests

from database import db
from keel import (
    HandoverTooLarge, InvalidHandover, MAX_BODY_BYTES, build_handover, send_handover,
)
from models import IntegrationLog, LeadValuation


keel_bp = Blueprint("keel", __name__)


@keel_bp.post("/crm/valuation-requests/<int:valuation_id>/keel-handover")
def hand_over_valuation(valuation_id):
    valuation = db.get_or_404(LeadValuation, valuation_id)
    if request.content_length and request.content_length > MAX_BODY_BYTES:
        return jsonify({"error": "handover_too_large", "retryable": False}), 413
    payload = request.get_json(silent=True)
    try:
        handover = build_handover(valuation, payload)
    except InvalidHandover as exc:
        return jsonify({"error": "invalid_handover", "errors": exc.errors, "retryable": False}), 400

    if not current_app.config.get("KEEL_HANDOVER_URL") or not current_app.config.get("KEEL_API_KEY"):
        return jsonify({"error": "keel_not_configured", "retryable": False}), 503

    response_status = None
    answer = None
    error = None
    retryable = False
    try:
        response = send_handover(handover)
        response_status = response.status_code
        try:
            answer = response.json()
        except ValueError:
            pass
        if response_status == 200 and isinstance(answer, dict) and answer.get("status") == "accepted":
            status_code = 200
        elif response_status in {400, 413, 422}:
            error, status_code = "keel_handover_refused", response_status
        elif response_status == 401:
            # This is the ERP's Keel signature, not the caller's ERP authentication.
            error, status_code = "keel_authentication_failed", 502
        else:
            error = "keel_handover_failed"
            status_code = 503 if response_status >= 500 else 502
            retryable = True
    except HandoverTooLarge:
        return jsonify({"error": "handover_too_large", "retryable": False}), 413
    except requests.Timeout:
        error, status_code, retryable = "keel_timeout", 504, True
    except requests.RequestException:
        error, status_code, retryable = "keel_unavailable", 503, True

    # No signing secret or signature headers are included in the audit trail.
    db.session.add(IntegrationLog(
        system="keel", entity_type="valuation_handover",
        external_id=valuation.rootle_request_id,
        payload={
            "valuation_id": valuation.id, "request": handover,
            "response_status": response_status, "response": answer,
            "error": error, "retryable": retryable,
        },
        status="failed" if error else "accepted", processed_at=datetime.utcnow(),
    ))
    db.session.commit()
    result = {
        "valuation_id": valuation.id, "request_id": valuation.rootle_request_id,
        "status": "failed" if error else "accepted", "retryable": retryable,
    }
    if answer is not None:
        result["keel"] = answer
    if response_status is not None:
        result["keel_status_code"] = response_status
    if error:
        result["error"] = error
    return jsonify(result), status_code
