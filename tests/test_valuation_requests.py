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
    ROOTLE_RESET_TOKEN = "test-reset-token"


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
        self.assertEqual(data["valuation"]["pricing_status"], "pricing_pending")

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

    def test_failed_valuation_request_submission_is_stored_for_retry(self):
        def fail_create(**kwargs):
            raise RuntimeError("attio unavailable")

        attio = types.SimpleNamespace(create_attio_valuation_request=fail_create)

        with patch.dict(sys.modules, {"attio": attio}):
            response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_failed",
                    "items": ["gold"],
                    "picture_url": "https://example.com/item.jpg",
                    "posthog_distinct_id": "ph_failed",
                    "rootle_request_id": "request_failed",
                },
            )

        self.assertEqual(response.status_code, 502)
        data = response.get_json()
        self.assertEqual(data["error"], "crm_sync_failed")
        self.assertIn("attio unavailable", data["message"])
        self.assertEqual(
            data["failed_submission"]["rootle_request_id"],
            "request_failed",
        )
        self.assertEqual(data["failed_submission"]["status"], "pending_retry")

        from models import FailedValuationRequestSubmission, LeadValuation

        failed_submission = FailedValuationRequestSubmission.query.one()
        self.assertEqual(failed_submission.crm_person_record_id, "person_failed")
        self.assertEqual(failed_submission.posthog_distinct_id, "ph_failed")
        self.assertEqual(
            failed_submission.normalised_payload["item_categories"],
            ["gold"],
        )
        self.assertEqual(LeadValuation.query.count(), 0)

    def test_failed_valuation_request_submission_can_be_retried(self):
        def fail_create(**kwargs):
            raise RuntimeError("attio unavailable")

        attio = types.SimpleNamespace(create_attio_valuation_request=fail_create)

        with patch.dict(sys.modules, {"attio": attio}):
            failed_response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_retry_stage_2",
                    "items": ["gold"],
                    "picture_url": "https://example.com/item.jpg",
                    "posthog_distinct_id": "ph_retry",
                    "rootle_request_id": "request_retry_stage_2",
                },
            )

        failed_submission_id = failed_response.get_json()["failed_submission"]["id"]
        retry_payloads = []

        def create_attio_valuation_request(**kwargs):
            retry_payloads.append(kwargs)
            return "vr_replayed"

        attio = types.SimpleNamespace(
            create_attio_valuation_request=create_attio_valuation_request,
            update_attio_person_posthog_distinct_id=lambda **kwargs: None,
        )

        with patch.dict(sys.modules, {"attio": attio}):
            retry_response = self.client.post(
                f"/api/crm/valuation-request-failures/{failed_submission_id}/retry"
            )

        self.assertEqual(retry_response.status_code, 201)
        data = retry_response.get_json()
        self.assertTrue(data["replayed"])
        self.assertEqual(data["valuation"]["crm_valuation_request_id"], "vr_replayed")
        self.assertEqual(data["failed_submission"]["status"], "resolved")
        self.assertEqual(data["failed_submission"]["retry_count"], 1)
        self.assertEqual(retry_payloads[0]["rootle_request_id"], "request_retry_stage_2")

        from models import FailedValuationRequestSubmission, LeadValuation

        failed_submission = FailedValuationRequestSubmission.query.get(failed_submission_id)
        valuation = LeadValuation.query.one()
        self.assertEqual(failed_submission.valuation_request_id, valuation.id)

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
        self.assertEqual(data["valuation"]["pricing_status"], "mev_calculated")
        self.assertEqual(len(data["valuation"]["mev_calculations"]), 2)
        self.assertEqual(len(attio_mev_updates), 2)
        self.assertEqual(attio_mev_updates[-1]["valuation_request_id"], "vr_mev")
        self.assertEqual(str(attio_mev_updates[-1]["amount"]), "90.00")
        self.assertEqual(attio_mev_updates[-1]["currency"], "GBP")
        self.assertEqual(str(attio_mev_updates[-1]["margin"]), "0.3500")
        self.assertEqual(attio_mev_updates[-1]["pricing_status"], "mev_calculated")

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

    def test_list_and_get_valuation_requests_for_pricing_queue(self):
        attio = types.SimpleNamespace(
            create_attio_valuation_request=lambda **kwargs: f"vr_{kwargs['rootle_request_id']}",
            update_attio_valuation_request_mev=lambda **kwargs: kwargs[
                "valuation_request_id"
            ],
        )

        with patch.dict(sys.modules, {"attio": attio}):
            first_response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_queue",
                    "items": ["gold"],
                    "picture_url": "https://example.com/gold.jpg",
                    "rootle_request_id": "request_queue_1",
                },
            )
            second_response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_queue",
                    "items": ["coins"],
                    "picture_url": "https://example.com/coins.jpg",
                    "rootle_request_id": "request_queue_2",
                },
            )
            first_id = first_response.get_json()["valuation"]["id"]
            second_id = second_response.get_json()["valuation"]["id"]
            self.client.post(
                f"/api/crm/valuation-requests/{first_id}/mev-calculations",
                json={"amount": "100.00", "currency": "GBP", "margin": "0.2500"},
            )

        needs_mev_response = self.client.get(
            "/api/crm/valuation-requests?needs_mev=true&crm_person_record_id=person_queue"
        )
        detail_response = self.client.get(f"/api/crm/valuation-requests/{second_id}")

        self.assertEqual(needs_mev_response.status_code, 200)
        needs_mev_data = needs_mev_response.get_json()
        self.assertEqual(needs_mev_data["total"], 1)
        self.assertEqual(needs_mev_data["valuations"][0]["id"], second_id)

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(
            detail_response.get_json()["valuation"]["rootle_request_id"],
            "request_queue_2",
        )

    def test_mev_sync_retries_latest_snapshot_to_attio(self):
        attio_mev_updates = []

        def update_attio_valuation_request_mev(**kwargs):
            attio_mev_updates.append(kwargs)
            return kwargs["valuation_request_id"]

        attio = types.SimpleNamespace(
            create_attio_valuation_request=lambda **kwargs: "vr_retry",
            update_attio_valuation_request_mev=update_attio_valuation_request_mev,
        )

        with patch.dict(sys.modules, {"attio": attio}):
            create_response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_retry",
                    "items": ["silver"],
                    "picture_url": "https://example.com/silver.jpg",
                    "rootle_request_id": "request_retry",
                },
            )
            valuation_id = create_response.get_json()["valuation"]["id"]
            missing_mev_response = self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/mev-sync"
            )
            self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/mev-calculations",
                json={"amount": "75.00", "currency": "GBP", "margin": "0.2000"},
            )
            sync_response = self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/mev-sync"
            )

        self.assertEqual(missing_mev_response.status_code, 400)
        self.assertEqual(missing_mev_response.get_json()["error"], "missing_latest_mev")
        self.assertEqual(sync_response.status_code, 200)
        self.assertTrue(sync_response.get_json()["mev_synced"])
        self.assertEqual(len(attio_mev_updates), 2)
        self.assertEqual(attio_mev_updates[-1]["valuation_request_id"], "vr_retry")
        self.assertEqual(str(attio_mev_updates[-1]["amount"]), "75.00")
        self.assertEqual(attio_mev_updates[-1]["pricing_status"], "mev_calculated")

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

    def test_reset_data_requires_token_and_confirmation(self):
        from models import Company

        company = Company(name="Rootle Test")
        db.session.add(company)
        db.session.commit()

        missing_token_response = self.client.post(
            "/api/admin/reset-data",
            json={"confirmation": "DELETE ROOTLE ERP DATA"},
        )
        bad_confirmation_response = self.client.post(
            "/api/admin/reset-data",
            json={"confirmation": "delete it", "reset_token": "test-reset-token"},
        )

        self.assertEqual(missing_token_response.status_code, 401)
        self.assertEqual(bad_confirmation_response.status_code, 400)
        self.assertEqual(Company.query.count(), 1)

    def test_reset_data_deletes_attio_and_truncates_database(self):
        from models import Company, LeadValuation, ValuationItemCategory

        attio_calls = []

        def delete_all_attio_records():
            attio_calls.append(True)
            return {
                "deleted_record_count": 3,
                "objects": {
                    "valuation_requests": {"deleted_record_count": 2},
                    "people": {"deleted_record_count": 1},
                },
            }

        attio = types.SimpleNamespace(delete_all_attio_records=delete_all_attio_records)

        db.session.add(Company(name="Rootle Test"))
        db.session.add(
            ValuationItemCategory(
                name="watches",
                label="Watches",
                sort_order=10,
            )
        )
        db.session.add(
            LeadValuation(
                crm_person_record_id="person_reset",
                crm_valuation_request_id="vr_reset",
                rootle_request_id="request_reset",
                item_categories=["gold"],
                item_photo_url="https://example.com/item.jpg",
            )
        )
        db.session.commit()

        with patch.dict(sys.modules, {"attio": attio}):
            response = self.client.post(
                "/api/admin/reset-data",
                json={"confirmation": "DELETE ROOTLE ERP DATA"},
                headers={"X-Reset-Token": "test-reset-token"},
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["reset"])
        self.assertEqual(data["attio"]["deleted_record_count"], 3)
        self.assertEqual(len(attio_calls), 1)
        self.assertEqual(Company.query.count(), 0)
        self.assertEqual(LeadValuation.query.count(), 0)
        self.assertEqual(ValuationItemCategory.query.count(), 0)


if __name__ == "__main__":
    unittest.main()
