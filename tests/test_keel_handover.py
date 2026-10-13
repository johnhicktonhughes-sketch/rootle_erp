import hashlib
import hmac
import json
import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

import requests

from test_valuation_requests import TestConfig
from app import create_app
from database import db
from keel import sign_handover
from models import IntegrationLog, LeadValuation


class SigningTests(unittest.TestCase):
    @patch("keel.time.time", return_value=1791100000)
    def test_keel_documented_signature_vector(self, clock):
        # The YAML has the correct URL; Markdown mistakenly wraps it in < >.
        handover = {
            "requestId": "req_8f2c", "attioValuationRequestId": "vr_123",
            "customer": {"id": "cust_42", "name": "Pat Sender", "email": "pat@example.com", "attioPersonId": "p_789"},
            "address": {"line1": "1 Boar Lane", "town": "Leeds", "postcode": "LS1 5DA"},
            "photographedItem": {"category": "Watches", "photoUrl": "https://example.com/photo.jpg"},
        }
        body, headers = sign_handover(handover, "test-secret")
        self.assertEqual(headers["x-rootle-timestamp"], "1791100000")
        self.assertEqual(headers["x-rootle-signature"], "661a0c03c51f1f4445c6189ed36edfffec5148319d09ca7d31249d26ae1b5c12")
        self.assertEqual(json.loads(body), handover)


class KeelHandoverTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app.config.update(
            KEEL_HANDOVER_URL="https://keel.example.test/rootle/handover",
            KEEL_API_KEY="test-secret", ROOTLE_API_KEY="erp-test-key",
        )
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.addCleanup(self.cleanup)
        self.client = self.app.test_client()
        self.valuation = LeadValuation(
            crm_person_record_id="person-1", crm_valuation_request_id="vr-1",
            rootle_request_id="request-1", item_categories=["gold", "coins"],
            item_photo_url="https://example.com/photo.jpg", customer_email="pat@example.com",
            address_line_1="1 Boar Lane", city="Leeds", postcode="LS1 5DA", country="GB",
            latest_mev_amount=Decimal("400"), latest_mev_currency="GBP",
            latest_mev_margin=Decimal("0.45"), mev_low=Decimal("320"),
            mev_high=Decimal("480"), pricing_request_id="pricing-1",
        )
        db.session.add(self.valuation)
        db.session.commit()
        self.path = f"/api/crm/valuation-requests/{self.valuation.id}/keel-handover"
        self.payload = {
            "customer": {"name": "Pat Sender"},
            "photographedItem": {"category": "Jewellery"},
            "declaredCategories": ["Jewellery", "Coins & Currency"],
            "labelMethod": "qr",
        }
        self.post = patch("keel.requests.post").start()
        self.addCleanup(patch.stopall)
        self.post.return_value = Mock(status_code=200, json=lambda: {"status": "accepted"})

    def cleanup(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def deliver(self, payload=None):
        return self.client.post(self.path, json=self.payload if payload is None else payload,
                                headers={"X-API-Key": "erp-test-key"})

    def test_acceptance_builds_snapshot_and_signs_exact_utf8_bytes(self):
        self.payload["customer"]["name"] = "Zoë Sender"
        response = self.deliver()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "accepted")
        call = self.post.call_args
        self.assertEqual(call.args[0], "https://keel.example.test/rootle/handover")
        body, headers = call.kwargs["data"], call.kwargs["headers"]
        expected = hmac.new(b"test-secret", headers["x-rootle-timestamp"].encode() + b"." + body, hashlib.sha256).hexdigest()
        self.assertEqual(headers["x-rootle-signature"], expected)
        self.assertFalse(call.kwargs["allow_redirects"])
        self.assertNotIn("json", call.kwargs)
        handover = json.loads(body)
        self.assertEqual(handover["requestId"], "request-1")
        self.assertEqual(handover["attioValuationRequestId"], "vr-1")
        self.assertEqual(handover["customer"], {"id": "person-1", "attioPersonId": "person-1", "name": "Zoë Sender", "email": "pat@example.com"})
        self.assertEqual(handover["address"]["town"], "Leeds")
        self.assertEqual(handover["mev"], {"amount": 400, "low": 320, "high": 480, "currency": "GBP", "margin": 0.45, "pricingResultId": "pricing-1"})
        audit = IntegrationLog.query.one()
        self.assertEqual(audit.status, "accepted")
        self.assertEqual(audit.external_id, "request-1")
        self.assertNotIn("test-secret", json.dumps(audit.payload))
        self.assertNotIn("x-rootle-signature", json.dumps(audit.payload))

    @patch("keel.time.time", side_effect=[1791100000, 1791100010])
    def test_timeout_retry_preserves_request_id_and_resigns(self, clock):
        self.post.side_effect = [requests.Timeout(), Mock(status_code=200, json=lambda: {"status": "accepted"})]
        first = self.deliver()
        self.assertEqual(first.status_code, 504)
        self.assertTrue(first.json["retryable"])
        second = self.deliver()
        self.assertEqual(second.status_code, 200)
        calls = self.post.call_args_list
        self.assertEqual(calls[0].kwargs["data"], calls[1].kwargs["data"])
        self.assertNotEqual(calls[0].kwargs["headers"]["x-rootle-signature"], calls[1].kwargs["headers"]["x-rootle-signature"])
        self.assertEqual([row.status for row in IntegrationLog.query.order_by(IntegrationLog.id)], ["failed", "accepted"])

    def test_repeated_success_is_sent_with_same_id_for_keel_to_dedupe(self):
        self.assertEqual(self.deliver().status_code, 200)
        self.assertEqual(self.deliver().status_code, 200)
        self.assertEqual(self.post.call_count, 2)
        self.assertEqual(len({json.loads(call.kwargs["data"])["requestId"] for call in self.post.call_args_list}), 1)

    def test_keel_refusals_and_outages(self):
        for upstream, status, retryable in [(400, 400, False), (401, 502, False), (413, 413, False), (422, 422, False), (500, 503, True), (503, 503, True)]:
            with self.subTest(upstream=upstream):
                self.post.return_value = Mock(status_code=upstream, json=lambda: {"status": "invalid", "errors": ["Fix field"]})
                response = self.deliver()
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json["retryable"], retryable)
                self.assertEqual(response.json["keel"]["errors"], ["Fix field"])

    def test_invalid_or_unexpected_success_response_is_not_accepted(self):
        for answer in [[], {"status": "error"}, None]:
            with self.subTest(answer=answer):
                self.post.return_value = Mock(status_code=200, json=lambda: answer)
                self.assertEqual(self.deliver().status_code, 502)
        self.post.return_value = Mock(status_code=200)
        self.post.return_value.json.side_effect = ValueError("not json")
        self.assertEqual(self.deliver().status_code, 502)
        self.assertEqual(IntegrationLog.query.filter_by(status="accepted").count(), 0)

    def test_invalid_payloads_never_send(self):
        invalid = [[], {}, {"customer": []}, {"mev": None},
                   {"requestId": "new-id"}, {"customer": {"attioPersonId": "another-person"}},
                   {"photographedItem": {"category": "gold"}},
                   {"photographedItem": {"photoUrl": "data:image/png;base64,abc"}},
                   {"declaredCategories": "Jewellery"}, {"declaredCategories": ["gold"]},
                   {"labelMethod": "email"}, {"mev": {"amount": True}},
                   {"mev": {"amount": -1, "low": 500, "high": 400, "currency": "GBP", "margin": -1, "pricingResultId": "p"}}]
        for invalid_payload in invalid:
            with self.subTest(payload=invalid_payload):
                payload = {**self.payload, **invalid_payload} if isinstance(invalid_payload, dict) else invalid_payload
                if invalid_payload == {}:
                    payload = {}
                self.assertEqual(self.deliver(payload).status_code, 400)
        self.post.assert_not_called()

    def test_missing_link_address_and_non_uk_address(self):
        for field, value in [("crm_valuation_request_id", None), ("address_line_1", None), ("country", "France")]:
            with self.subTest(field=field):
                original = getattr(self.valuation, field)
                setattr(self.valuation, field, value)
                db.session.commit()
                self.assertEqual(self.deliver().status_code, 400)
                setattr(self.valuation, field, original)
        self.post.assert_not_called()

    def test_optional_mev_omitted_when_snapshot_incomplete(self):
        self.valuation.pricing_request_id = None
        db.session.commit()
        self.assertEqual(self.deliver().status_code, 200)
        self.assertNotIn("mev", json.loads(self.post.call_args.kwargs["data"]))

    def test_contact_corrections_and_complete_mev_override(self):
        self.payload["customer"].update(id="erp-customer-1", phone="+447700900123", email="new@example.com")
        self.payload["address"] = {"line1": "2 Boar Lane", "line2": "Flat 1"}
        self.payload["mev"] = {"amount": 100, "low": 80, "high": 120, "currency": "GBP", "margin": 45, "pricingResultId": "p-2"}
        self.assertEqual(self.deliver().status_code, 200)
        sent = json.loads(self.post.call_args.kwargs["data"])
        self.assertEqual(sent["customer"]["id"], "erp-customer-1")
        self.assertEqual(sent["address"]["line1"], "2 Boar Lane")
        self.assertEqual(sent["mev"]["margin"], 45)

    def test_body_limit_no_network_call(self):
        self.payload["customer"]["name"] = "x" * (256 * 1024)
        self.assertEqual(self.deliver().status_code, 413)
        self.post.assert_not_called()

    def test_outbound_utf8_size_limit(self):
        self.valuation.item_photo_url = "https://example.com/" + "x" * (256 * 1024)
        db.session.commit()
        self.assertEqual(self.deliver().status_code, 413)
        self.post.assert_not_called()

    def test_auth_configuration_and_missing_valuation(self):
        self.assertEqual(self.client.post(self.path, json=self.payload).status_code, 401)
        self.assertEqual(self.client.post("/api/crm/valuation-requests/999/keel-handover", json=self.payload, headers={"X-API-Key": "erp-test-key"}).status_code, 404)
        self.app.config["KEEL_API_KEY"] = None
        self.assertEqual(self.deliver().status_code, 503)
        self.post.assert_not_called()
