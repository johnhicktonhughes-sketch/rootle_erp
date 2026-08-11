import os
import hashlib
import hmac
import json
import sys
import types
import unittest
from datetime import datetime
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
    PRICING_API_BASE_URL = "https://pricing.example.test"
    PRICING_API_KEY = "pricing-test-key"
    PRICING_DEFAULT_MARGIN = "0.3000"
    KLAVIYO_API_KEY = None
    KLAVIYO_API_BASE_URL = "https://klaviyo.example.test"
    KLAVIYO_API_REVISION = "2026-04-15"


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

    def test_contact_details_do_not_send_invalid_attio_location_and_mark_stage_3(self):
        person_updates = []
        stage_updates = []

        def update_attio_person_contact_details(**kwargs):
            person_updates.append(kwargs)
            return kwargs["person_record_id"]

        def update_attio_valuation_request_stage_3(**kwargs):
            stage_updates.append(kwargs)
            return kwargs["valuation_request_id"]

        attio = types.SimpleNamespace(
            create_attio_valuation_request=lambda **kwargs: "vr_contact",
            update_attio_person_contact_details=update_attio_person_contact_details,
            update_attio_valuation_request_stage_3=update_attio_valuation_request_stage_3,
        )
        klaviyo = types.SimpleNamespace(
            upsert_profile_properties_by_attio_person=lambda **kwargs: {
                "status": "success",
                "kwargs": kwargs,
            },
        )

        with patch.dict(sys.modules, {"attio": attio, "klaviyo": klaviyo}):
            create_response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_contact",
                    "items": ["gold"],
                    "picture_url": "https://example.com/item.jpg",
                    "rootle_request_id": "request_contact",
                },
            )
            contact_response = self.client.post(
                "/api/crm/contact-details",
                json={
                    "attio_id": "person_contact",
                    "address_line_1": "1 Test Street",
                    "postcode": "TS42QN",
                    "attio_valuation_request_id": "vr_contact",
                    "marketing_consent": False,
                },
            )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(contact_response.status_code, 200)
        self.assertNotIn("email", person_updates[0])
        self.assertEqual(person_updates[0]["address_line_1"], "1 Test Street")
        self.assertEqual(person_updates[0]["postcode"], "TS42QN")
        self.assertIs(person_updates[0]["marketing_consent"], False)
        self.assertEqual(stage_updates[0]["valuation_request_id"], "vr_contact")

        data = contact_response.get_json()
        self.assertIs(data["marketing_consent"], False)
        self.assertEqual(
            data["updated_erp_valuations"][0]["status"],
            "customer_details_received",
        )
        self.assertEqual(data["updated_erp_valuations"][0]["postcode"], "TS42QN")
        self.assertIs(data["updated_erp_valuations"][0]["marketing_consent"], False)
        self.assertEqual(data["klaviyo_sync"]["status"], "success")
        self.assertEqual(
            data["klaviyo_sync"]["kwargs"],
            {
                "attio_person_record_id": "person_contact",
                "properties": {"rootle_stage": "indicative_offer_completed"},
            },
        )

    def test_contact_details_require_address_not_email(self):
        def update_attio_person_contact_details(**kwargs):
            return kwargs["person_record_id"]

        attio = types.SimpleNamespace(
            update_attio_person_contact_details=update_attio_person_contact_details,
        )

        with patch.dict(sys.modules, {"attio": attio}):
            response = self.client.post(
                "/api/crm/contact-details",
                json={
                    "attio_id": "person_contact",
                    "email": "customer@example.com",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["fields"], ["address"])

    def test_klaviyo_profile_payload_uses_attio_external_id(self):
        from klaviyo import _profile_payload

        payload = _profile_payload(
            email="customer@example.com",
            attio_person_record_id="person_123",
            properties={"rootle_stage": "address_available"},
        )

        self.assertEqual(payload["data"]["type"], "profile")
        attributes = payload["data"]["attributes"]
        self.assertEqual(attributes["email"], "customer@example.com")
        self.assertEqual(attributes["external_id"], "person_123")
        self.assertEqual(attributes["properties"]["source"], "attio")
        self.assertEqual(
            attributes["properties"]["rootle_stage"],
            "address_available",
        )
        external_id_payload = _profile_payload(
            attio_person_record_id="person_456",
            properties={"rootle_stage": "indicative_offer_completed"},
        )
        external_id_attributes = external_id_payload["data"]["attributes"]
        self.assertEqual(external_id_attributes["external_id"], "person_456")
        self.assertNotIn("email", external_id_attributes)
        self.assertEqual(
            external_id_attributes["properties"]["rootle_stage"],
            "indicative_offer_completed",
        )

    def test_klaviyo_mev_event_payload_uses_attio_external_id(self):
        from klaviyo import _event_payload

        calculated_at = datetime(2026, 6, 20, 12, 0, 0)
        payload = _event_payload(
            metric_name="Rootle MEV Calculated",
            attio_person_record_id="person_mev",
            properties={"rootle_request_id": "request_mev"},
            value=90.0,
            value_currency="GBP",
            time=calculated_at,
            unique_id="rootle-mev-calculation-1-2026-06-20T12:00:00",
        )

        self.assertEqual(payload["data"]["type"], "event")
        attributes = payload["data"]["attributes"]
        self.assertEqual(
            attributes["metric"]["data"]["attributes"]["name"],
            "Rootle MEV Calculated",
        )
        self.assertEqual(
            attributes["profile"]["data"]["attributes"]["external_id"],
            "person_mev",
        )
        self.assertEqual(attributes["value"], 90.0)
        self.assertEqual(attributes["value_currency"], "GBP")
        self.assertEqual(attributes["time"], "2026-06-20T12:00:00")
        self.assertEqual(
            attributes["unique_id"],
            "rootle-mev-calculation-1-2026-06-20T12:00:00",
        )

    def test_klaviyo_subscribes_consented_profile_and_adds_contact_list(self):
        from klaviyo import upsert_profile_from_attio_contact

        calls = []

        class FakeResponse:
            ok = True
            status_code = 200
            text = "{}"

            def __init__(self, profile_id=None, status_code=200):
                self.profile_id = profile_id
                self.status_code = status_code

            def json(self):
                return {"data": {"id": self.profile_id}}

        def fake_post(url, json, headers, timeout):
            calls.append({"url": url, "json": json})
            if url.endswith("/api/profile-import"):
                return FakeResponse(profile_id="profile_123", status_code=201)
            if url.endswith("/api/profile-subscription-bulk-create-jobs"):
                return FakeResponse(status_code=202)
            return FakeResponse(status_code=204)

        with patch("klaviyo._api_key", lambda: "test-key"), patch(
            "klaviyo._headers", lambda: {}
        ), patch("klaviyo.requests.post", fake_post):
            result = upsert_profile_from_attio_contact(
                email="customer@example.com",
                attio_person_record_id="person_123",
                properties={"marketing_consent": True},
            )

        self.assertEqual(result["profile_id"], "profile_123")
        self.assertEqual(
            [sync["list_id"] for sync in result["consent_sync"]],
            ["Ub3nHY"],
        )
        self.assertEqual(
            [sync["list_id"] for sync in result["list_sync"]],
            ["RWb2ew"],
        )
        self.assertEqual(
            [call["url"] for call in calls[1:]],
            [
                "https://klaviyo.example.test/api/profile-subscription-bulk-create-jobs",
                "https://klaviyo.example.test/api/lists/RWb2ew/relationships/profiles",
            ],
        )
        self.assertEqual(
            calls[1]["json"]["data"]["relationships"]["list"]["data"],
            {"type": "list", "id": "Ub3nHY"},
        )
        subscribed_profile = calls[1]["json"]["data"]["attributes"]["profiles"]["data"][0]
        self.assertEqual(subscribed_profile["attributes"]["email"], "customer@example.com")
        self.assertEqual(
            subscribed_profile["attributes"]["subscriptions"]["email"]["marketing"],
            {"consent": "SUBSCRIBED"},
        )
        self.assertEqual(
            calls[2]["json"],
            {"data": [{"type": "profile", "id": "profile_123"}]},
        )

    def test_klaviyo_adds_non_consented_profile_to_contact_list_only(self):
        from klaviyo import upsert_profile_from_attio_contact

        list_urls = []

        class FakeResponse:
            ok = True
            status_code = 200
            text = "{}"

            def __init__(self, profile_id=None, status_code=200):
                self.profile_id = profile_id
                self.status_code = status_code

            def json(self):
                return {"data": {"id": self.profile_id}}

        def fake_post(url, json, headers, timeout):
            if url.endswith("/relationships/profiles"):
                list_urls.append(url)
                return FakeResponse(status_code=204)
            return FakeResponse(profile_id="profile_456", status_code=200)

        with patch("klaviyo._api_key", lambda: "test-key"), patch(
            "klaviyo._headers", lambda: {}
        ), patch("klaviyo.requests.post", fake_post):
            result = upsert_profile_from_attio_contact(
                email="customer@example.com",
                attio_person_record_id="person_456",
                properties={"marketing_consent": False},
            )

        self.assertEqual(
            result["consent_sync"],
            [],
        )
        self.assertEqual(
            [sync["list_id"] for sync in result["list_sync"]],
            ["RWb2ew"],
        )
        self.assertEqual(
            list_urls,
            ["https://klaviyo.example.test/api/lists/RWb2ew/relationships/profiles"],
        )

    def test_attio_person_contact_values_use_rootle_address_fields(self):
        from attio import (
            _person_contact_values,
            _stage_1_values,
            _valuation_request_values,
            update_attio_valuation_request_stage_3,
        )

        values = _person_contact_values(
            email="customer@example.com",
            address_line_1="1 Test Street",
            city="Middlesbrough",
            postcode="TS42QN",
            country="GB",
        )

        self.assertEqual(values["email_addresses"], ["customer@example.com"])
        self.assertEqual(values["rootle_address_line_1"], "1 Test Street")
        self.assertEqual(values["rootle_city"], "Middlesbrough")
        self.assertEqual(values["rootle_postcode"], "TS42QN")
        self.assertEqual(values["rootle_country"], "GB")
        self.assertNotIn("primary_location", values)

        self.assertEqual(
            _stage_1_values(
                name="Jane Smith",
                phone_number="+447123456789",
                email="customer@example.com",
                posthog_distinct_id="ph_123",
            )["rootle_stage"],
            "contact_details",
        )
        self.assertEqual(
            _stage_1_values(
                name="Jane Smith",
                phone_number="+447123456789",
                email="customer@example.com",
                posthog_distinct_id="ph_123",
            )["email_addresses"],
            ["customer@example.com"],
        )
        self.assertEqual(
            _valuation_request_values(
                person_record_id="person_123",
                rootle_request_id="request_123",
                item_categories=["gold"],
                item_photo_url="https://example.com/item.jpg",
            )["rootle_stage"],
            "item_details_available",
        )

        stage_payloads = []

        class FakeResponse:
            ok = True
            status_code = 200
            text = "{}"

            def json(self):
                return {"data": {"id": {"record_id": "vr_mev_attio"}}}

            def json(self):
                return {"data": {"id": {"record_id": "vr_stage"}}}

        def fake_patch(url, json, headers, timeout):
            stage_payloads.append(json)
            return FakeResponse()

        with patch("attio.ensure_valuation_request_object", lambda: {}), patch(
            "attio.requests.patch",
            fake_patch,
        ), patch("attio._headers", lambda: {}):
            update_attio_valuation_request_stage_3(
                valuation_request_id="vr_stage",
                stage_3_completed_at=datetime.utcnow(),
            )

        self.assertEqual(
            stage_payloads[0]["data"]["values"]["rootle_stage"],
            "address_available",
        )

    def test_attio_mev_update_pushes_range_and_pricing_request_id(self):
        from attio import update_attio_valuation_request_mev

        payloads = []

        class FakeResponse:
            ok = True
            status_code = 200
            text = "{}"

            def json(self):
                return {"data": {"id": {"record_id": "vr_mev_attio"}}}

        def fake_patch(url, json, headers, timeout):
            payloads.append(json)
            return FakeResponse()

        with patch("attio.ensure_valuation_request_object", lambda: {}), patch(
            "attio.requests.patch",
            fake_patch,
        ), patch("attio._headers", lambda: {}):
            update_attio_valuation_request_mev(
                valuation_request_id="vr_mev_attio",
                amount="333.52",
                currency="GBP",
                margin="0.3000",
                calculated_at=datetime(2026, 6, 20, 12, 0, 0),
                mev_low="150.00",
                mev_high="701.87",
                pricing_request_id="8",
            )

        values = payloads[0]["data"]["values"]
        self.assertEqual(values["latest_mev_amount"], 333.52)
        self.assertEqual(values["latest_mev_currency"], "GBP")
        self.assertEqual(values["latest_mev_margin"], 0.3)
        self.assertEqual(values["latest_mev_calculated_at"], "2026-06-20T12:00:00")
        self.assertEqual(values["mev_low"], 150.0)
        self.assertEqual(values["mev_high"], 701.87)
        self.assertEqual(values["pricing_request_id"], "8")

    def test_existing_stage_1_person_gets_descriptive_stage_label(self):
        import attio

        calls = []

        with patch("attio.find_attio_person_by_phone", lambda phone_number: "person_existing"), patch(
            "attio.update_attio_person_rootle_stage",
            lambda **kwargs: calls.append(("stage", kwargs)),
        ), patch(
            "attio.update_attio_person_posthog_distinct_id",
            lambda **kwargs: calls.append(("posthog", kwargs)),
        ), patch(
            "attio.update_attio_person_contact_details",
            lambda **kwargs: calls.append(("contact", kwargs)),
        ):
            result = attio.get_or_create_attio_stage_1_lead(
                name="Jane Smith",
                phone_number="+447123456789",
                email="customer@example.com",
                posthog_distinct_id="ph_existing",
            )

        self.assertEqual(result, {"record_id": "person_existing", "created": False})
        self.assertEqual(
            calls[0],
            (
                "stage",
                {
                    "person_record_id": "person_existing",
                    "rootle_stage": "contact_details",
                },
            ),
        )
        self.assertEqual(calls[1][0], "posthog")
        self.assertEqual(
            calls[2],
            (
                "contact",
                {
                    "person_record_id": "person_existing",
                    "email": "customer@example.com",
                },
            ),
        )

    def test_stage_1_requires_email(self):
        response = self.client.post(
            "/api/crm/leads/stage-1",
            json={
                "name": "Jane Smith",
                "phone_number": "+447123456789",
                "posthog_distinct_id": "ph_missing_email",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["fields"], ["email"])

    def test_stage_1_syncs_klaviyo_profile_with_contact_details_stage(self):
        klaviyo_calls = []

        attio = types.SimpleNamespace(
            get_or_create_attio_stage_1_lead=lambda **kwargs: {
                "record_id": "person_stage_1",
                "created": True,
            },
        )
        klaviyo = types.SimpleNamespace(
            upsert_profile_from_attio_contact=lambda **kwargs: klaviyo_calls.append(
                kwargs
            )
            or {"status": "success", "integration_log_id": 42}
        )

        with patch.dict(sys.modules, {"attio": attio, "klaviyo": klaviyo}):
            response = self.client.post(
                "/api/crm/leads/stage-1",
                json={
                    "name": "Jane Smith",
                    "phone_number": "+447123456789",
                    "email": "jane@example.com",
                    "posthog_distinct_id": "ph_stage_1",
                    "marketing_consent": True,
                },
            )

        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertEqual(data["stage"], "contact_details")
        self.assertIs(data["marketing_consent"], True)
        self.assertEqual(data["klaviyo_sync"]["status"], "success")
        self.assertEqual(
            klaviyo_calls[0],
            {
                "email": "jane@example.com",
                "attio_person_record_id": "person_stage_1",
                "phone_number": "+447123456789",
                "first_name": "Jane",
                "last_name": "Smith",
                "properties": {
                    "rootle_stage": "indicative_offer_started",
                    "posthog_distinct_id": "ph_stage_1",
                    "marketing_consent": True,
                },
            },
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

    def test_attio_valuation_create_skips_schema_setup_by_default(self):
        import attio

        schema_calls = []
        record_posts = []

        class FakeResponse:
            ok = True
            status_code = 200
            text = "{}"

            def json(self):
                return {"data": {"id": {"record_id": "vr_fast"}}}

        def fake_attio_request(method, path, **kwargs):
            schema_calls.append((method, path))
            return FakeResponse()

        def fake_post(url, json, headers, timeout):
            record_posts.append(json)
            return FakeResponse()

        with patch.dict(os.environ, {"ATTIO_SYNC_SCHEMA_ON_WRITE": ""}), patch(
            "attio._attio_request",
            fake_attio_request,
        ), patch("attio.requests.post", fake_post), patch("attio._headers", lambda: {}):
            record_id = attio.create_attio_valuation_request(
                person_record_id="person_fast",
                rootle_request_id="request_fast",
                item_categories=["gold"],
                item_photo_url="https://example.com/gold.jpg",
            )

        self.assertEqual(record_id, "vr_fast")
        self.assertEqual(len(record_posts), 1)
        self.assertEqual(schema_calls, [])

    def test_attio_valuation_create_caches_schema_setup_when_enabled(self):
        import attio

        attio.ensure_valuation_request_object.cache_clear()
        attio._ensure_select_option.cache_clear()
        schema_calls = []
        record_posts = []

        class FakeResponse:
            ok = True
            status_code = 200
            text = "{}"

            def __init__(self, record_id=None):
                self.record_id = record_id

            def json(self):
                return {"data": {"id": {"record_id": self.record_id or "schema_id"}}}

        def fake_attio_request(method, path, **kwargs):
            schema_calls.append((method, path))
            return FakeResponse()

        def fake_post(url, json, headers, timeout):
            record_posts.append(json)
            return FakeResponse(record_id=f"vr_{len(record_posts)}")

        with patch.dict(os.environ, {"ATTIO_SYNC_SCHEMA_ON_WRITE": "true"}), patch(
            "attio._attio_request",
            fake_attio_request,
        ), patch("attio.requests.post", fake_post), patch("attio._headers", lambda: {}):
            first_record_id = attio.create_attio_valuation_request(
                person_record_id="person_cache",
                rootle_request_id="request_cache_1",
                item_categories=["gold"],
                item_photo_url="https://example.com/gold.jpg",
            )
            schema_call_count = len(schema_calls)
            second_record_id = attio.create_attio_valuation_request(
                person_record_id="person_cache",
                rootle_request_id="request_cache_2",
                item_categories=["gold"],
                item_photo_url="https://example.com/gold.jpg",
            )

        self.assertEqual(first_record_id, "vr_1")
        self.assertEqual(second_record_id, "vr_2")
        self.assertEqual(len(record_posts), 2)
        self.assertGreater(schema_call_count, 0)
        self.assertEqual(len(schema_calls), schema_call_count)

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
        klaviyo_mev_events = []

        def update_attio_valuation_request_mev(**kwargs):
            attio_mev_updates.append(kwargs)
            return kwargs["valuation_request_id"]

        attio = types.SimpleNamespace(
            create_attio_valuation_request=lambda **kwargs: "vr_mev",
            update_attio_valuation_request_mev=update_attio_valuation_request_mev,
        )
        klaviyo = types.SimpleNamespace(
            create_mev_calculated_event=lambda **kwargs: klaviyo_mev_events.append(
                kwargs
            )
            or {"status": "success", "metric": "Rootle MEV Calculated"},
        )

        with patch.dict(sys.modules, {"attio": attio, "klaviyo": klaviyo}):
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
                    "mev_low": "80.00",
                    "mev_high": "120.00",
                    "pricing_request_id": "price_req_1",
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
                    "low_total_prediction": "70.00",
                    "high_total_prediction": "140.00",
                    "pricing_result_id": 8,
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
        self.assertEqual(data["valuation"]["mev_low"], "70.00")
        self.assertEqual(data["valuation"]["mev_high"], "140.00")
        self.assertEqual(data["valuation"]["pricing_request_id"], "8")
        self.assertEqual(data["valuation"]["status"], "mev_calculated")
        self.assertEqual(data["valuation"]["pricing_status"], "mev_calculated")
        self.assertEqual(len(data["valuation"]["mev_calculations"]), 2)
        self.assertEqual(data["mev_calculation"]["mev_low"], "70.00")
        self.assertEqual(data["mev_calculation"]["mev_high"], "140.00")
        self.assertEqual(data["mev_calculation"]["pricing_request_id"], "8")
        self.assertEqual(len(attio_mev_updates), 2)
        self.assertEqual(attio_mev_updates[-1]["valuation_request_id"], "vr_mev")
        self.assertEqual(str(attio_mev_updates[-1]["amount"]), "90.00")
        self.assertEqual(attio_mev_updates[-1]["currency"], "GBP")
        self.assertEqual(str(attio_mev_updates[-1]["margin"]), "0.3500")
        self.assertEqual(str(attio_mev_updates[-1]["mev_low"]), "70.00")
        self.assertEqual(str(attio_mev_updates[-1]["mev_high"]), "140.00")
        self.assertEqual(attio_mev_updates[-1]["pricing_request_id"], "8")
        self.assertEqual(attio_mev_updates[-1]["pricing_status"], "mev_calculated")
        self.assertEqual(len(klaviyo_mev_events), 2)
        self.assertEqual(klaviyo_mev_events[-1]["attio_person_record_id"], "person_mev")
        self.assertEqual(klaviyo_mev_events[-1]["rootle_request_id"], "request_mev")
        self.assertEqual(str(klaviyo_mev_events[-1]["amount"]), "90.00")
        self.assertEqual(str(klaviyo_mev_events[-1]["mev_low"]), "70.00")
        self.assertEqual(str(klaviyo_mev_events[-1]["mev_high"]), "140.00")
        self.assertEqual(klaviyo_mev_events[-1]["pricing_request_id"], "8")
        self.assertEqual(klaviyo_mev_events[-1]["pricing_status"], "mev_calculated")
        self.assertEqual(
            data["klaviyo_sync"],
            {"status": "success", "metric": "Rootle MEV Calculated"},
        )

    def test_mev_calculation_requires_amount_and_range(self):
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
            json={"currency": "GBP"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["fields"], ["amount", "mev_low", "mev_high"])

    def test_mev_calculation_defaults_margin_when_omitted(self):
        attio = types.SimpleNamespace(
            create_attio_valuation_request=lambda **kwargs: "vr_mev_default_margin",
            update_attio_valuation_request_mev=lambda **kwargs: kwargs[
                "valuation_request_id"
            ],
        )

        with patch.dict(sys.modules, {"attio": attio}):
            create_response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_mev_default_margin",
                    "items": ["gold"],
                    "picture_url": "https://example.com/item.jpg",
                    "rootle_request_id": "request_mev_default_margin",
                },
            )

            valuation_id = create_response.get_json()["valuation"]["id"]
            response = self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/mev-calculations",
                json={
                    "amount": "100.00",
                    "currency": "GBP",
                    "mev_low": "80.00",
                    "mev_high": "120.00",
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["valuation"]["latest_mev_margin"], "0.3000")

    def test_mev_calculation_accepts_pricing_api_response_shape(self):
        attio = types.SimpleNamespace(
            create_attio_valuation_request=lambda **kwargs: "vr_mev_shape",
            update_attio_valuation_request_mev=lambda **kwargs: kwargs[
                "valuation_request_id"
            ],
        )

        with patch.dict(sys.modules, {"attio": attio}):
            create_response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_mev_shape",
                    "items": ["gold"],
                    "picture_url": "https://example.com/item.jpg",
                    "rootle_request_id": "request_mev_shape",
                },
            )

            valuation_id = create_response.get_json()["valuation"]["id"]
            response = self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/mev-calculations",
                json={
                    "confidence": {
                        "category_uncertainty_percent": 74.22,
                        "low_confidence": True,
                        "model_deviation_percent": 1.87,
                        "reason": "Models deviate by 1.9%; category uncertainty spans 74.2% (threshold: 25.0%)",
                    },
                    "ensemble_remainder_prediction": 183.52,
                    "ensemble_total_prediction": 333.52,
                    "high_remainder_prediction": 551.87,
                    "high_total_prediction": 701.87,
                    "low_remainder_prediction": 0,
                    "low_total_prediction": 150,
                    "prediction_interval": {
                        "coverage": 0.8,
                        "high_total_prediction": 701.87,
                        "low_total_prediction": 150,
                        "method": "Holdout residual 10th/90th percentile calibration",
                    },
                    "pricing_result_id": 8,
                    "range": {
                        "coverage": 0.8,
                        "method": "Holdout residual 10th/90th percentile calibration",
                        "remainder": {
                            "high": 551.87,
                            "low": 0,
                        },
                        "total": {
                            "high": 701.87,
                            "low": 150,
                        },
                    },
                    "raw_prediction": {
                        "calibration_groups": [
                            "value_band:150-175",
                        ],
                        "category_assumption": "Missing supporting categories were treated as unknown and marginalized over training scenarios.",
                        "category_scenarios_considered": 23,
                        "category_uncertainty_percent": 74.22,
                        "confidence_reason": "Models deviate by 1.9%; category uncertainty spans 74.2% (threshold: 25.0%)",
                        "diagnostic_high_total_prediction": 647.45,
                        "diagnostic_low_total_prediction": 166.9,
                        "ensemble_remainder_prediction": 183.52,
                        "ensemble_total_prediction": 333.52,
                        "gb_remainder_prediction": 186.67,
                        "gb_total_prediction": 336.67,
                        "high_remainder_prediction": 551.87,
                        "high_total_prediction": 701.87,
                        "knn_remainder_prediction": 180.36,
                        "knn_total_prediction": 330.36,
                        "low_confidence": True,
                        "low_remainder_prediction": 0,
                        "low_total_prediction": 150,
                        "max_category": "Costume Jewellery",
                        "max_value": 150,
                        "model_deviation_percent": 1.87,
                        "prediction_interval_coverage": 0.8,
                        "prediction_interval_method": "Holdout residual 10th/90th percentile calibration",
                        "supporting_categories": [
                            "Gold",
                        ],
                    },
                    "valuation_request_id": "05f8de32-791b-4635-a3b1-c7d6206a0eb5",
                },
            )

        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertEqual(data["valuation"]["latest_mev_amount"], "333.52")
        self.assertEqual(data["valuation"]["latest_mev_currency"], "GBP")
        self.assertEqual(data["valuation"]["latest_mev_margin"], "0.3000")
        self.assertEqual(data["valuation"]["mev_low"], "150.00")
        self.assertEqual(data["valuation"]["mev_high"], "701.87")
        self.assertEqual(data["valuation"]["pricing_request_id"], "8")
        self.assertEqual(data["mev_calculation"]["amount"], "333.52")
        self.assertEqual(data["mev_calculation"]["mev_low"], "150.00")
        self.assertEqual(data["mev_calculation"]["mev_high"], "701.87")
        self.assertEqual(data["mev_calculation"]["pricing_request_id"], "8")

    def test_attio_workflow_request_calls_pricing_api_and_stores_mev(self):
        attio_mev_updates = []

        def update_attio_valuation_request_mev(**kwargs):
            attio_mev_updates.append(kwargs)
            return kwargs["valuation_request_id"]

        attio = types.SimpleNamespace(
            create_attio_valuation_request=lambda **kwargs: "vr_price",
            update_attio_valuation_request_mev=update_attio_valuation_request_mev,
        )

        pricing_response = types.SimpleNamespace(
            ok=True,
            status_code=200,
            text='{"ensemble_total_prediction": 180.0}',
            json=lambda: {
                "valuation_request_id": "vr_price",
                "pricing_result_id": 99,
                "ensemble_total_prediction": 180.0,
                "range": {
                    "total": {
                        "low": 120.0,
                        "high": 220.0,
                    }
                },
            },
        )

        with patch.dict(sys.modules, {"attio": attio}):
            create_response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_price",
                    "items": ["gold"],
                    "picture_url": "https://example.com/gold.jpg",
                    "rootle_request_id": "request_price",
                },
            )
            with patch("routes.crm.requests.post", return_value=pricing_response) as post:
                workflow_response = self.client.post(
                    "/api/crm/valuation-requests/request-mev-calculation",
                    json={
                        "record_id": "vr_price",
                        "pricing_status": "requested_mev_calculation",
                        "max_category": "Gold",
                        "max_value": 250.0,
                        "other_categories": ["Silver"],
                    },
                )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(workflow_response.status_code, 201)
        post.assert_called_once()
        request_kwargs = post.call_args.kwargs
        self.assertEqual(request_kwargs["headers"]["X-API-Key"], "pricing-test-key")
        self.assertEqual(
            request_kwargs["json"],
            {
                "valuation_request_id": "vr_price",
                "max_category": "Gold",
                "max_value": 250.0,
                "other_categories": ["Silver"],
            },
        )

        data = workflow_response.get_json()
        self.assertEqual(data["valuation"]["latest_mev_amount"], "180.00")
        self.assertEqual(data["valuation"]["latest_mev_currency"], "GBP")
        self.assertEqual(data["valuation"]["latest_mev_margin"], "0.3000")
        self.assertEqual(data["valuation"]["mev_low"], "120.00")
        self.assertEqual(data["valuation"]["mev_high"], "220.00")
        self.assertEqual(data["valuation"]["pricing_request_id"], "99")
        self.assertEqual(data["valuation"]["pricing_status"], "mev_calculated")
        self.assertEqual(
            data["mev_calculation"]["calculation_method"],
            "rootle_pricing_api",
        )
        self.assertEqual(len(attio_mev_updates), 1)
        self.assertEqual(attio_mev_updates[0]["valuation_request_id"], "vr_price")
        self.assertEqual(str(attio_mev_updates[0]["amount"]), "180.0")
        self.assertEqual(str(attio_mev_updates[0]["mev_low"]), "120.0")
        self.assertEqual(str(attio_mev_updates[0]["mev_high"]), "220.0")
        self.assertEqual(attio_mev_updates[0]["pricing_request_id"], "99")

    def test_attio_workflow_pricing_request_ignores_other_statuses(self):
        response = self.client.post(
            "/api/crm/valuation-requests/request-mev-calculation",
            json={"pricing_status": "pricing_pending"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ignored"])

    def test_attio_workflow_pricing_request_returns_pricing_errors(self):
        attio = types.SimpleNamespace(
            create_attio_valuation_request=lambda **kwargs: "vr_price_error",
        )
        pricing_response = types.SimpleNamespace(
            ok=False,
            status_code=500,
            text="boom",
            json=lambda: {},
        )

        with patch.dict(sys.modules, {"attio": attio}):
            self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_price_error",
                    "items": ["gold"],
                    "picture_url": "https://example.com/gold.jpg",
                    "rootle_request_id": "request_price_error",
                },
            )
            with patch("routes.crm.requests.post", return_value=pricing_response):
                response = self.client.post(
                    "/api/crm/valuation-requests/request-mev-calculation",
                    json={
                        "crm_valuation_request_id": "vr_price_error",
                        "pricing_status": "requested_mev_calculation",
                        "max_category": "Gold",
                        "max_value": 250.0,
                    },
                )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["error"], "pricing_prediction_failed")

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
                json={
                    "amount": "100.00",
                    "currency": "GBP",
                    "margin": "0.2500",
                    "mev_low": "80.00",
                    "mev_high": "120.00",
                },
            )

        needs_mev_response = self.client.get(
            "/api/crm/valuation-requests?needs_mev=true&crm_person_record_id=person_queue"
        )
        detail_response = self.client.get(f"/api/crm/valuation-requests/{second_id}")

        self.assertEqual(needs_mev_response.status_code, 200)
        needs_mev_data = needs_mev_response.get_json()
        self.assertEqual(needs_mev_data["total"], 1)
        self.assertEqual(needs_mev_data["valuations"][0]["id"], second_id)
        self.assertIn("label_eligibility", needs_mev_data["valuations"][0])
        self.assertNotIn("mev_calculations", needs_mev_data["valuations"][0])
        self.assertNotIn("inbound_labels", needs_mev_data["valuations"][0])
        self.assertNotIn("postage_opportunities", needs_mev_data["valuations"][0])

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(
            detail_response.get_json()["valuation"]["rootle_request_id"],
            "request_queue_2",
        )
        self.assertIn("mev_calculations", detail_response.get_json()["valuation"])

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
                json={
                    "amount": "75.00",
                    "currency": "GBP",
                    "margin": "0.2000",
                    "mev_low": "60.00",
                    "mev_high": "90.00",
                },
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
        self.assertEqual(str(attio_mev_updates[-1]["mev_low"]), "60.00")
        self.assertEqual(str(attio_mev_updates[-1]["mev_high"]), "90.00")
        self.assertIsNone(attio_mev_updates[-1]["pricing_request_id"])
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
                    "mev_low": "120.00",
                    "mev_high": "180.00",
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

    def test_postage_opportunity_requires_mev_and_creates_attio_record(self):
        postage_payloads = []

        def create_attio_postage_opportunity(**kwargs):
            postage_payloads.append(kwargs)
            return {
                "record_id": "po_attio_123",
                "barcode_value": "po_attio_123",
                "qr_payload": "po_attio_123",
                "barcode_image": "data:image/svg+xml;base64,barcode",
                "qr_code_image": "data:image/svg+xml;base64,qr",
            }

        attio = types.SimpleNamespace(
            create_attio_valuation_request=lambda **kwargs: "vr_postage",
            update_attio_valuation_request_mev=lambda **kwargs: kwargs[
                "valuation_request_id"
            ],
            create_attio_postage_opportunity=create_attio_postage_opportunity,
        )

        with patch.dict(sys.modules, {"attio": attio}):
            create_response = self.client.post(
                "/api/crm/valuation-requests",
                json={
                    "attio_id": "person_postage",
                    "items": ["gold"],
                    "picture_url": "https://example.com/item.jpg",
                    "rootle_request_id": "request_postage",
                },
            )
            valuation_id = create_response.get_json()["valuation"]["id"]

            not_ready_response = self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/postage-opportunity",
                json={"triggered_by": "ops"},
            )

            self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/mev-calculations",
                json={
                    "amount": "150.00",
                    "currency": "GBP",
                    "margin": "0.2500",
                    "mev_low": "120.00",
                    "mev_high": "180.00",
                },
            )
            postage_response = self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/postage-opportunity",
                json={"triggered_by": "ops", "notes": "Manual promotion"},
            )
            duplicate_response = self.client.post(
                f"/api/crm/valuation-requests/{valuation_id}/postage-opportunity",
                json={"triggered_by": "ops"},
            )

        self.assertEqual(not_ready_response.status_code, 400)
        self.assertEqual(
            not_ready_response.get_json()["error"],
            "valuation_not_ready_for_postage_opportunity",
        )
        self.assertEqual(postage_response.status_code, 201)
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertEqual(len(postage_payloads), 1)
        self.assertEqual(postage_payloads[0]["person_record_id"], "person_postage")
        self.assertEqual(postage_payloads[0]["valuation_request_id"], "vr_postage")
        self.assertEqual(postage_payloads[0]["rootle_request_id"], "request_postage")
        self.assertNotIn("barcode_value", postage_payloads[0])
        self.assertNotIn("qr_payload", postage_payloads[0])

        postage_data = postage_response.get_json()["postage_opportunity"]
        self.assertEqual(postage_data["crm_postage_opportunity_id"], "po_attio_123")
        self.assertEqual(postage_data["crm_person_record_id"], "person_postage")
        self.assertEqual(postage_data["crm_valuation_request_id"], "vr_postage")
        self.assertEqual(postage_data["triggered_by"], "ops")
        self.assertEqual(postage_data["barcode_value"], "po_attio_123")
        self.assertEqual(postage_data["qr_payload"], "po_attio_123")
        self.assertTrue(postage_data["meta"]["barcode_image"].startswith("data:image/svg+xml"))
        self.assertTrue(postage_data["meta"]["qr_code_image"].startswith("data:image/svg+xml"))
        self.assertEqual(postage_data["valuation"]["id"], valuation_id)
        self.assertFalse(duplicate_response.get_json()["postage_opportunity_created"])

        scan_response = self.client.post(
            f"/api/crm/postage-opportunities/scan/{postage_data['barcode_value']}"
        )
        self.assertEqual(scan_response.status_code, 200)
        self.assertEqual(
            scan_response.get_json()["postage_opportunity"]["status"],
            "scanned",
        )

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
                    "mev_low": "9500.00",
                    "mev_high": "12000.00",
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
