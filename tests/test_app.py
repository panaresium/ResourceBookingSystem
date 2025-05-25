import unittest
import json
from datetime import datetime, date, time
from app import app, db, User, FloorMap, Resource, Booking
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

        # Create a floor map and some resources for testing
        floor_map = FloorMap(name='Test Map', image_filename='map.png')
        db.session.add(floor_map)
        db.session.commit()

        res1 = Resource(
            name='Room A',
            floor_map_id=floor_map.id,
            map_coordinates=json.dumps({'type': 'rect', 'x': 10, 'y': 20, 'w': 30, 'h': 30}),
            status='published'
        )
        res2 = Resource(
            name='Room B',
            floor_map_id=floor_map.id,
            map_coordinates=json.dumps({'type': 'rect', 'x': 50, 'y': 20, 'w': 30, 'h': 30}),
            status='published'
        )
        db.session.add_all([res1, res2])
        db.session.commit()

        # Store for use in tests
        self.floor_map = floor_map
        self.resource1 = res1
        self.resource2 = res2
        
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

    def test_new_booking_requires_login(self):
        """Ensure new booking page requires authentication."""
        # Without logging in, should redirect to login
        response = self.client.get('/new_booking', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.location)

        # After login, should access successfully
        login_response = self.login('testuser', 'password')
        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(login_response.get_json().get('success'))

        auth_status = self.client.get('/api/auth/status').get_json()
        self.assertTrue(auth_status.get('logged_in'))

        response_logged_in = self.client.get('/new_booking')
        self.assertEqual(response_logged_in.status_code, 200)
        self.assertIn('<h1', response_logged_in.data.decode('utf-8'))

    def test_map_details_includes_resources_and_bookings(self):
        """Ensure map details endpoint returns resources and bookings."""
        booking_date = date.today()
        booking = Booking(
            resource_id=self.resource1.id,
            user_name='someone',
            start_time=datetime.combine(booking_date, time(9, 0)),
            end_time=datetime.combine(booking_date, time(10, 0)),
            title='Morning'
        )
        db.session.add(booking)
        db.session.commit()

        resp = self.client.get(
            f'/api/map_details/{self.floor_map.id}?date={booking_date.isoformat()}'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['map_details']['id'], self.floor_map.id)
        self.assertEqual(len(data['mapped_resources']), 2)
        res = next(r for r in data['mapped_resources'] if r['id'] == self.resource1.id)
        self.assertEqual(len(res['bookings_on_date']), 1)
        self.assertEqual(res['bookings_on_date'][0]['title'], 'Morning')

    def test_booking_creation_success(self):
        """Booking creation returns 201 and persists to DB."""
        self.login('testuser', 'password')
        payload = {
            'resource_id': self.resource1.id,
            'date_str': date.today().isoformat(),
            'start_time_str': '11:00',
            'end_time_str': '12:00',
            'title': 'Test',
            'user_name': 'testuser'
        }
        resp = self.client.post(
            '/api/bookings', data=json.dumps(payload), content_type='application/json'
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data['resource_id'], self.resource1.id)
        self.assertIsNotNone(Booking.query.get(data['id']))

    def test_booking_creation_conflict(self):
        """Overlapping booking should return HTTP 409."""
        self.login('testuser', 'password')
        booking_date = date.today()
        existing = Booking(
            resource_id=self.resource1.id,
            user_name='someone',
            start_time=datetime.combine(booking_date, time(9, 0)),
            end_time=datetime.combine(booking_date, time(10, 0)),
            title='Existing'
        )
        db.session.add(existing)
        db.session.commit()

        payload = {
            'resource_id': self.resource1.id,
            'date_str': booking_date.isoformat(),
            'start_time_str': '09:30',
            'end_time_str': '10:30',
            'title': 'Conflict',
            'user_name': 'testuser'
        }
        resp = self.client.post(
            '/api/bookings', data=json.dumps(payload), content_type='application/json'
        )
        self.assertEqual(resp.status_code, 409)

    def test_booking_cancellation(self):
        """User can cancel own booking via API."""
        self.login('testuser', 'password')
        booking_date = date.today()
        booking = Booking(
            resource_id=self.resource1.id,
            user_name='testuser',
            start_time=datetime.combine(booking_date, time(13, 0)),
            end_time=datetime.combine(booking_date, time(14, 0)),
            title='To cancel'
        )
        db.session.add(booking)
        db.session.commit()

        resp = self.client.delete(f'/api/bookings/{booking.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(Booking.query.get(booking.id))

if __name__ == '__main__':
    unittest.main()
