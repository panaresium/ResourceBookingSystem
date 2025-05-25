import unittest
import json
from app import app, db, User # Removed Booking as it's not used in these tests
# from flask_login import current_user # Not directly used for assertions here

class AppTests(unittest.TestCase):

    def setUp(self):
        """Set up test variables."""
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for tests
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        app.config['LOGIN_DISABLED'] = False # Ensure login is enabled for tests
        
        self.app_context = app.app_context()
        self.app_context.push() # Push app context for db operations
        
        db.create_all()
        
        # Create a test user
        user = User.query.filter_by(username='testuser').first()
        if not user:
            user = User(username='testuser', email='test@example.com', is_admin=False)
            user.set_password('password') # Standard password for test user
            db.session.add(user)
            db.session.commit()
        
        self.client = app.test_client() # Use this single client instance for all requests

    def tearDown(self):
        """Tear down test variables."""
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def login(self, username, password):
        """Helper function to log in a user via API and check success."""
        response = self.client.post('/api/auth/login',
                                    data=json.dumps(dict(username=username, password=password)),
                                    content_type='application/json',
                                    follow_redirects=True)
        return response

    def logout(self):
        """Helper function to log out a user via API."""
        return self.client.post('/api/auth/logout', follow_redirects=True)

    def test_my_bookings_page_rendering(self):
        """Test rendering of the my_bookings page after login."""
        # Log in the test user
        login_response = self.login('testuser', 'password')
        self.assertEqual(login_response.status_code, 200)
        login_data = login_response.get_json()
        self.assertTrue(login_data.get('success'), "Login should be successful")

        # Verify authentication status
        auth_status_response = self.client.get('/api/auth/status')
        self.assertEqual(auth_status_response.status_code, 200)
        auth_status_data = auth_status_response.get_json()
        self.assertTrue(auth_status_data.get('logged_in'), "User should be logged in after login")
        self.assertEqual(auth_status_data.get('user').get('username'), 'testuser')

        # Make a GET request to /my_bookings
        response = self.client.get('/my_bookings')
        self.assertEqual(response.status_code, 200, "My Bookings page should load successfully.")
        
        response_data_str = response.data.decode('utf-8')
        self.assertIn("<h2>My Bookings</h2>", response_data_str) # Adjusted to actual output (translation might not run in tests by default)
        self.assertIn("<footer>", response_data_str) 
        self.assertIn("id=\"my-bookings-list\"", response_data_str)
        self.assertIn("Smart Resource Booking", response_data_str) # From base.html title

    def test_logout_functionality(self):
        """Test user logout functionality via API."""
        # Log in a test user
        login_response = self.login('testuser', 'password')
        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(login_response.get_json().get('success'), "Login failed during setup for logout test")

        # Verify user is authenticated before logout
        auth_status_before_logout = self.client.get('/api/auth/status').get_json()
        self.assertTrue(auth_status_before_logout.get('logged_in'), "User should be logged in before logout")

        # Make a POST request to /api/auth/logout
        response_logout = self.logout()
        self.assertEqual(response_logout.status_code, 200)
        json_response_logout = response_logout.get_json()
        self.assertTrue(json_response_logout.get('success'))
        self.assertEqual(json_response_logout.get('message'), 'Logout successful.')

        # Verify user is no longer authenticated
        auth_status_after_logout = self.client.get('/api/auth/status').get_json()
        self.assertFalse(auth_status_after_logout.get('logged_in'), "User should be logged out")
        self.assertIsNone(auth_status_after_logout.get('user'), "User data should be None after logout")

        # Check /my_bookings (should redirect to login)
        response_my_bookings = self.client.get('/my_bookings', follow_redirects=False)
        self.assertEqual(response_my_bookings.status_code, 302, "Accessing /my_bookings after logout should redirect.")
        self.assertTrue('/login' in response_my_bookings.location, "Should redirect to login page.")
        
        # Check /profile (should redirect to login)
        response_profile = self.client.get('/profile', follow_redirects=False)
        self.assertEqual(response_profile.status_code, 302)
        self.assertTrue('/login' in response_profile.location)

if __name__ == '__main__':
    unittest.main()
