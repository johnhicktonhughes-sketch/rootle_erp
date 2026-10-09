import hashlib
import hmac
import json
import unittest
from unittest.mock import Mock, patch

from test_valuation_requests import TestConfig
from app import create_app
from database import db
from models import IntegrationLog


class SlackNotificationTests(unittest.TestCase):
    def setUp(self):
        self.phone_lookup = patch('slack_notifications._related_person_phone', return_value='+447700900123')
        self.mock_phone = self.phone_lookup.start()
        self.addCleanup(self.phone_lookup.stop)
        self.app = create_app(TestConfig)
        self.app.config.update(
            ATTIO_VALUATION_REQUEST_OBJECT_ID='valuation-object',
            SLACK_BOT_TOKEN='test-token',
            SLACK_VALUATION_REQUEST_CHANNEL_ID='C0C87JUBQMS',
        )
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def deliver(self, object_id='valuation-object', record_id='record-1'):
        body = json.dumps({'events': [{'event_type': 'record.created', 'id': {
            'workspace_id': 'workspace', 'object_id': object_id, 'record_id': record_id,
        }}]}).encode()
        signature = hmac.new(b'test-secret', body, hashlib.sha256).hexdigest()
        return self.client.post('/api/webhooks/attio', data=body,
                                content_type='application/json',
                                headers={'Attio-Signature': signature})

    @patch('slack_notifications.requests.post')
    def test_delivery_filters_objects_and_suppresses_duplicates(self, post):
        post.return_value = Mock(json=lambda: {'ok': True, 'ts': '123'})
        self.assertEqual(self.deliver('people').status_code, 200)
        post.assert_not_called()
        self.assertEqual(self.deliver().get_json()['notified_attio_record_ids'], ['record-1'])
        self.assertEqual(self.deliver().get_json()['notified_attio_record_ids'], [])
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs['json']['channel'], 'C0C87JUBQMS')
        self.assertIn('<!channel>', post.call_args.kwargs['json']['text'])
        self.assertIn('Phone: +447700900123', post.call_args.kwargs['json']['text'])
        self.assertTrue(post.call_args.kwargs['json']['mrkdwn'])
        self.mock_phone.assert_called_once()
        self.assertEqual(IntegrationLog.query.count(), 1)

    @patch('slack_notifications.requests.post')
    def test_incoming_webhook_delivery(self, post):
        self.app.config['SLACK_BOT_TOKEN'] = None
        self.app.config['SLACK_VALUATION_REQUEST_WEBHOOK_URL'] = 'https://hooks.slack.com/test'
        post.return_value = Mock(text='ok')
        self.assertEqual(self.deliver().status_code, 200)
        self.assertEqual(post.call_args.args[0], 'https://hooks.slack.com/test')
        self.assertNotIn('channel', post.call_args.kwargs['json'])
        self.assertEqual(self.deliver().get_json()['notified_attio_record_ids'], [])
        post.assert_called_once()

    @patch('slack_notifications.requests.post')
    def test_slack_error_can_be_retried(self, post):
        post.return_value = Mock(json=lambda: {'ok': False, 'error': 'not_in_channel'})
        self.assertEqual(self.deliver().status_code, 503)
        self.assertEqual(IntegrationLog.query.count(), 0)
        post.return_value = Mock(json=lambda: {'ok': True, 'ts': '123'})
        self.assertEqual(self.deliver().status_code, 200)
        self.assertEqual(IntegrationLog.query.count(), 1)

    @patch('slack_notifications.requests.post')
    def test_missing_configuration_fails_closed(self, post):
        self.app.config['ATTIO_VALUATION_REQUEST_OBJECT_ID'] = None
        self.assertEqual(self.deliver().status_code, 503)
        self.app.config['ATTIO_VALUATION_REQUEST_OBJECT_ID'] = 'valuation-object'
        self.app.config['SLACK_BOT_TOKEN'] = None
        self.assertEqual(self.deliver().status_code, 503)
        post.assert_not_called()

    @patch('slack_notifications.requests.post')
    def test_person_lookup_failure_retries_without_sending(self, post):
        import requests
        self.mock_phone.side_effect = requests.ConnectionError('Attio unavailable')
        self.assertEqual(self.deliver().status_code, 503)
        post.assert_not_called()
        self.assertEqual(IntegrationLog.query.count(), 0)

    @patch('slack_notifications.requests.post')
    def test_invalid_signature_never_sends(self, post):
        response = self.client.post('/api/webhooks/attio', json={'events': []})
        self.assertEqual(response.status_code, 401)
        post.assert_not_called()


class RelatedPhoneTests(unittest.TestCase):
    @patch('attio._attio_request')
    def test_reads_linked_person_phone(self, get):
        from slack_notifications import _related_person_phone
        get.side_effect = [
            Mock(json=lambda: {'data': {'values': {'person': [{'target_record_id': 'person-1'}]}}}),
            Mock(json=lambda: {'data': {'values': {'phone_numbers': [{'phone_number': '+447700900123'}]}}}),
        ]
        self.assertEqual(_related_person_phone({'object_id': 'object-1', 'record_id': 'request-1'}), '+447700900123')
        self.assertEqual(get.call_args.args, ('GET', 'objects/people/records/person-1'))

    @patch('attio._attio_request')
    def test_missing_person_or_phone_is_explicit(self, get):
        from slack_notifications import _related_person_phone
        get.return_value = Mock(json=lambda: {'data': {'values': {}}})
        self.assertEqual(_related_person_phone({'object_id': 'object-1', 'record_id': 'request-1'}), 'Not provided')
