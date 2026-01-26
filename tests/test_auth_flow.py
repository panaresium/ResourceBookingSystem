import unittest
from unittest.mock import patch, MagicMock
from flask import Flask, url_for
from auth import get_google_link_flow, auth_bp

class AuthFlowTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SERVER_NAME'] = 'localhost:5000'
        self.app.config['PREFERRED_URL_SCHEME'] = 'http'
        self.app.config['GOOGLE_CLIENT_ID'] = 'dummy_id'
        self.app.config['GOOGLE_CLIENT_SECRET'] = 'dummy_secret'
        self.app.register_blueprint(auth_bp)
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.request_context = self.app.test_request_context()
        self.request_context.push()

    def tearDown(self):
        self.request_context.pop()
        self.app_context.pop()

    @patch('auth.Flow')
    def test_get_google_link_flow_redirect_uri(self, mock_flow):
        # We want to verify that the redirect_uri passed to Flow.from_client_config
        # uses the correct scheme (http for localhost) and not forced https.

        # Call the function
        get_google_link_flow()

        # Get the call args
        args, kwargs = mock_flow.from_client_config.call_args
        client_config = kwargs['client_config']
        redirect_uri = kwargs['redirect_uri']

        # Check that redirect_uri starts with http:// because PREFERRED_URL_SCHEME is http
        # and we are in a test request context which defaults to http
        self.assertTrue(redirect_uri.startswith('http://'), f"Redirect URI should start with http://, got {redirect_uri}")
        self.assertIn('/profile/link/google/callback', redirect_uri)

        # Verify it matches what's in client_config
        self.assertEqual(client_config['web']['redirect_uris'][0], redirect_uri)

if __name__ == '__main__':
    unittest.main()
