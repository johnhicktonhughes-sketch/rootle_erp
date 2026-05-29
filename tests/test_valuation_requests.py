import os
import hashlib
import hmac
import json
import sys
import types
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite://")

from app import create_app
from database import db


class TestConfig:
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False
    JSONIFY_PRETTYPRINT_REGULAR = False
    ROOTLE_API_KEY = None
    CORS_ALLOWED_ORIGINS = []
    ATTIO_WEBHOOK_SECRET = "test-secret"
    ATTIO_VALUATION_REQUEST_OBJECT_ID = None


class ValuationRequestTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_duplicate_request_merges_item_categories(self):
        attio = types.SimpleNamespace(
            create_attio_valuation_request=lambda **kwargs: "vr_123",
            update_attio_valuation_request=lambda **kwargs: "vr_123",
        )

        with patch.dict(sys.modules, {"attio": attio}):
            first_response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_123",
                    "items": ["gold"],
                    "picture_url": "https://example.com/item.jpg",
                    "rootle_request_id": "request_123",
                },
            )
            second_response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_123",
                    "items": ["coins", "silver"],
                    "picture_url": "https://example.com/item.jpg",
                    "rootle_request_id": "request_123",
                },
            )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)

        data = second_response.get_json()
        self.assertFalse(data["erp_valuation_created"])
        self.assertTrue(data["erp_valuation_updated"])
        self.assertEqual(data["valuation"]["item_categories"], ["gold", "coins", "silver"])

    def test_item_categories_accept_comma_separated_string(self):
        attio = types.SimpleNamespace(
            create_attio_valuation_request=lambda **kwargs: "vr_456",
        )

        with patch.dict(sys.modules, {"attio": attio}):
            response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_456",
                    "items": "gold, coins",
                    "picture_url": "https://example.com/item.jpg",
                    "rootle_request_id": "request_456",
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.get_json()["valuation"]["item_categories"],
            ["gold", "coins"],
        )

    def test_attio_record_deleted_webhook_deletes_matching_valuation(self):
        attio = types.SimpleNamespace(
            create_attio_valuation_request=lambda **kwargs: "vr_deleted",
        )

        with patch.dict(sys.modules, {"attio": attio}):
            create_response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_deleted",
                    "items": ["gold"],
                    "picture_url": "https://example.com/item.jpg",
                    "rootle_request_id": "request_deleted",
                },
            )

        self.assertEqual(create_response.status_code, 201)

        payload = {
            "webhook_id": "webhook_123",
            "events": [
                {
                    "event_type": "record.deleted",
                    "id": {
                        "workspace_id": "workspace_123",
                        "object_id": "object_123",
                        "record_id": "vr_deleted",
                    },
                    "actor": {
                        "type": "workspace-member",
                        "id": "member_123",
                    },
                }
            ],
        }
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(
            TestConfig.ATTIO_WEBHOOK_SECRET.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        webhook_response = self.client.post(
            "/api/webhooks/attio",
            data=raw_body,
            content_type="application/json",
            headers={"Attio-Signature": signature},
        )

        self.assertEqual(webhook_response.status_code, 200)
        data = webhook_response.get_json()
        self.assertEqual(data["deleted_attio_record_ids"], ["vr_deleted"])
        self.assertEqual(data["deleted_erp_valuation_count"], 1)

        from models import LeadValuation

        self.assertIsNone(
            LeadValuation.query.filter_by(
                crm_valuation_request_id="vr_deleted",
            ).first()
        )

    def test_attio_webhook_rejects_invalid_signature(self):
        response = self.client.post(
            "/api/webhooks/attio",
            json={
                "events": [
                    {
                        "event_type": "record.deleted",
                        "id": {"record_id": "vr_123"},
                    }
                ]
            },
            headers={"Attio-Signature": "bad-signature"},
        )

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
