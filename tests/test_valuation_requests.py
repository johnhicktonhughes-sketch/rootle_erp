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

    def test_add_valuation_item_syncs_attio_option(self):
        synced_options = []

        attio = types.SimpleNamespace(
            ensure_valuation_request_item_options=lambda options: synced_options.extend(
                options
            ),
        )

        with patch.dict(sys.modules, {"attio": attio}):
            response = self.client.post(
                "/api/crm/valuation-items",
                json={"name": "Watches", "label": "Watches"},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(synced_options, ["watches"])
        self.assertEqual(response.get_json()["item"]["name"], "watches")

    def test_add_valuation_item_rolls_back_when_attio_sync_fails(self):
        def fail_sync(options):
            raise RuntimeError("attio unavailable")

        attio = types.SimpleNamespace(ensure_valuation_request_item_options=fail_sync)

        with patch.dict(sys.modules, {"attio": attio}):
            response = self.client.post(
                "/api/crm/valuation-items",
                json={"name": "Watches", "label": "Watches"},
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["error"], "attio_option_sync_failed")

        list_response = self.client.get("/api/crm/valuation-items")
        item_names = [item["name"] for item in list_response.get_json()]
        self.assertNotIn("watches", item_names)

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

    def test_mev_calculation_updates_latest_snapshot_and_keeps_history(self):
        attio_mev_updates = []

        def update_attio_valuation_request_mev(**kwargs):
            attio_mev_updates.append(kwargs)
            return kwargs["valuation_request_id"]

        attio = types.SimpleNamespace(
            create_attio_valuation_request=lambda **kwargs: "vr_mev",
            update_attio_valuation_request_mev=update_attio_valuation_request_mev,
        )

        with patch.dict(sys.modules, {"attio": attio}):
            create_response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_mev",
                    "items": ["gold"],
                    "picture_url": "https://example.com/item.jpg",
                    "rootle_request_id": "request_mev",
                },
            )

            valuation_id = create_response.get_json()["valuation"]["id"]
            first_mev_response = self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/mev-calculations",
                json={
                    "amount": "100.00",
                    "currency": "gbp",
                    "margin": "0.2500",
                    "calculation_method": "manual",
                    "calculated_by": "pricing-agent",
                    "inputs": {"guide_price": "125.00"},
                },
            )
            second_mev_response = self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/mev-calculations",
                json={
                    "amount": "90.00",
                    "currency": "GBP",
                    "margin": "0.3500",
                    "calculation_method": "margin_reprice",
                    "calculated_by": "pricing-agent",
                },
            )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(first_mev_response.status_code, 201)
        self.assertEqual(second_mev_response.status_code, 201)

        data = second_mev_response.get_json()
        self.assertEqual(data["valuation"]["latest_mev_amount"], "90.00")
        self.assertEqual(data["valuation"]["latest_mev_currency"], "GBP")
        self.assertEqual(data["valuation"]["latest_mev_margin"], "0.3500")
        self.assertEqual(data["valuation"]["status"], "mev_calculated")
        self.assertEqual(len(data["valuation"]["mev_calculations"]), 2)
        self.assertEqual(len(attio_mev_updates), 2)
        self.assertEqual(attio_mev_updates[-1]["valuation_request_id"], "vr_mev")
        self.assertEqual(str(attio_mev_updates[-1]["amount"]), "90.00")
        self.assertEqual(attio_mev_updates[-1]["currency"], "GBP")
        self.assertEqual(str(attio_mev_updates[-1]["margin"]), "0.3500")

    def test_mev_calculation_requires_amount_currency_and_margin(self):
        attio = types.SimpleNamespace(
            create_attio_valuation_request=lambda **kwargs: "vr_mev_invalid",
        )

        with patch.dict(sys.modules, {"attio": attio}):
            create_response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_mev_invalid",
                    "items": ["gold"],
                    "picture_url": "https://example.com/item.jpg",
                    "rootle_request_id": "request_mev_invalid",
                },
            )

        valuation_id = create_response.get_json()["valuation"]["id"]
        response = self.client.post(
            f"/api/crm/valuation-requests/{valuation_id}/mev-calculations",
            json={"amount": "100.00", "currency": "GBP"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["fields"], ["margin"])

    def test_inbound_label_requires_eligible_mev_and_returns_scan_context(self):
        attio = types.SimpleNamespace(
            create_attio_valuation_request=lambda **kwargs: "vr_label",
            update_attio_valuation_request_mev=lambda **kwargs: kwargs[
                "valuation_request_id"
            ],
        )

        with patch.dict(sys.modules, {"attio": attio}):
            create_response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_label",
                    "items": ["gold"],
                    "picture_url": "https://example.com/item.jpg",
                    "rootle_request_id": "request_label",
                },
            )
            valuation_id = create_response.get_json()["valuation"]["id"]

            ineligible_response = self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/inbound-labels",
                json={},
            )

            self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/mev-calculations",
                json={
                    "amount": "150.00",
                    "currency": "GBP",
                    "margin": "0.2500",
                },
            )
            label_response = self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/inbound-labels",
                json={"label_url": "https://example.com/label.pdf"},
            )
            duplicate_response = self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/inbound-labels",
                json={},
            )

        self.assertEqual(ineligible_response.status_code, 400)
        self.assertEqual(label_response.status_code, 201)
        self.assertEqual(duplicate_response.status_code, 200)

        label_data = label_response.get_json()["label"]
        self.assertEqual(label_data["crm_person_record_id"], "person_label")
        self.assertEqual(label_data["rootle_request_id"], "request_label")
        self.assertEqual(label_data["courier"], "royal_mail")
        self.assertEqual(label_data["service_level"], "tracked_return")
        self.assertEqual(label_data["expected_items"], ["gold"])
        self.assertEqual(label_data["item_photo_url"], "https://example.com/item.jpg")

        scan_response = self.client.post(
            f"/api/crm/inbound-labels/scan/{label_data['barcode_value']}"
        )
        scan_data = scan_response.get_json()["label"]
        self.assertEqual(scan_response.status_code, 200)
        self.assertEqual(scan_data["status"], "label_scanned")
        self.assertEqual(scan_data["valuation"]["id"], valuation_id)
        self.assertEqual(scan_data["valuation"]["item_photo_url"], "https://example.com/item.jpg")

    def test_high_value_inbound_label_defaults_to_white_glove(self):
        attio = types.SimpleNamespace(
            create_attio_valuation_request=lambda **kwargs: "vr_white_glove",
            update_attio_valuation_request_mev=lambda **kwargs: kwargs[
                "valuation_request_id"
            ],
        )

        with patch.dict(sys.modules, {"attio": attio}):
            create_response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_white_glove",
                    "items": ["coins"],
                    "picture_url": "https://example.com/coin.jpg",
                    "rootle_request_id": "request_white_glove",
                },
            )
            valuation_id = create_response.get_json()["valuation"]["id"]
            self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/mev-calculations",
                json={
                    "amount": "10001.00",
                    "currency": "GBP",
                    "margin": "0.4000",
                },
            )
            label_response = self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/inbound-labels",
                json={},
            )

        self.assertEqual(label_response.status_code, 201)
        label_data = label_response.get_json()["label"]
        self.assertTrue(label_data["white_glove_required"])
        self.assertEqual(label_data["dispatch_method"], "white_glove")
        self.assertEqual(label_data["courier"], "rootle_white_glove")


if __name__ == "__main__":
    unittest.main()
