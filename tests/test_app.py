import unittest
import json

from datetime import datetime, time, date, timedelta

from app import app, db, User, Resource, Booking, WaitlistEntry, FloorMap, email_log, teams_log


# from flask_login import current_user # Not directly used for assertions here

class AppTests(unittest.TestCase):

    def setUp(self):
        """Set up test variables."""
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for tests
        app.config['LOGIN_DISABLED'] = False # Ensure login is enabled for tests

        self.app_context = app.app_context()
        self.app_context.push() # Push app context for db operations

        db.drop_all()
        db.create_all()

        email_log.clear()
        teams_log.clear()


        # Create a test user
        user = User.query.filter_by(username='testuser').first()
        if not user:
            user = User(username='testuser', email='test@example.com', is_admin=False)
            user.set_password('password') # Standard password for test user
            db.session.add(user)
            db.session.commit()

        # Create a floor map and some resources for testing
        import uuid
        unique_name = f"Test Map {uuid.uuid4()}"
        unique_file = f"{uuid.uuid4()}.png"
        floor_map = FloorMap(name=unique_name, image_filename=unique_file)

        db.session.add(floor_map)
        db.session.commit()

        res1 = Resource(
            name='Room A',
            capacity=10,
            equipment='Projector,Whiteboard',
            tags='large',
            floor_map_id=floor_map.id,
            map_coordinates=json.dumps({'type': 'rect', 'x': 10, 'y': 20, 'w': 30, 'h': 30}),
            status='published'
        )
        res2 = Resource(
            name='Room B',
            capacity=4,
            equipment='Whiteboard',
            tags='small',
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

    def test_conflicting_booking_adds_waitlist(self):
        resource = Resource(name='Room1', status='published')
        db.session.add(resource)
        db.session.commit()

        start = datetime.combine(date.today(), time(9, 0))
        end = datetime.combine(date.today(), time(10, 0))
        existing = Booking(resource_id=resource.id, user_name='testuser', start_time=start, end_time=end, title='Existing')
        db.session.add(existing)
        db.session.commit()

        other = User(username='other', email='other@example.com', is_admin=False)
        other.set_password('password')
        db.session.add(other)
        db.session.commit()

        self.login('other', 'password')

        payload = {
            'resource_id': resource.id,
            'date_str': date.today().strftime('%Y-%m-%d'),
            'start_time_str': '09:00',
            'end_time_str': '10:00',
            'title': 'Conflict',
            'user_name': 'other'
        }
        resp = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 409)
        entries = WaitlistEntry.query.filter_by(resource_id=resource.id).all()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].user_id, other.id)

    def test_booking_blocked_when_resource_under_maintenance(self):
        resource = Resource(name='MaintRoom', status='published', is_under_maintenance=True,
                            maintenance_until=datetime.utcnow() + timedelta(days=1))
        db.session.add(resource)
        db.session.commit()

        self.login('testuser', 'password')
        payload = {
            'resource_id': resource.id,
            'date_str': date.today().strftime('%Y-%m-%d'),
            'start_time_str': '09:00',
            'end_time_str': '10:00',
            'title': 'test',
            'user_name': 'testuser'
        }
        resp = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 403)
        self.assertIn('maintenance', resp.get_json().get('error', '').lower())
        self.assertEqual(Booking.query.count(), 0)

    def test_cancellation_notifies_waitlisted_user(self):
        resource = Resource(name='Room1', status='published')
        db.session.add(resource)
        db.session.commit()

        start = datetime.combine(date.today(), time(9, 0))
        end = datetime.combine(date.today(), time(10, 0))
        booking = Booking(resource_id=resource.id, user_name='testuser', start_time=start, end_time=end, title='Existing')
        db.session.add(booking)
        db.session.commit()

        other = User(username='other', email='other@example.com', is_admin=False)
        other.set_password('password')
        db.session.add(other)
        db.session.commit()

        entry = WaitlistEntry(resource_id=resource.id, user_id=other.id)
        db.session.add(entry)
        db.session.commit()

        self.login('testuser', 'password')
        resp = self.client.delete(f'/api/bookings/{booking.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(WaitlistEntry.query.count(), 0)
        self.assertEqual(len(email_log), 1)
        self.assertEqual(email_log[0]['to'], other.email)
        self.assertEqual(len(teams_log), 2)
        self.assertTrue(any(entry['to'] == other.email for entry in teams_log))

    def test_analytics_dashboard_permissions(self):
        """Ensure analytics dashboard permissions are enforced."""
        # Unauthenticated request should redirect to login
        resp = self.client.get('/admin/analytics/', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.location)

        # Login as normal user without permissions
        self.login('testuser', 'password')
        resp_no_perm = self.client.get('/admin/analytics/', follow_redirects=False)
        self.assertEqual(resp_no_perm.status_code, 403)
        self.logout()

        # Create admin user with full permissions
        admin = User(username='adminuser', email='admin2@example.com', is_admin=True)
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()

        # Login as admin and access dashboard
        self.login('adminuser', 'password')
        resp_admin = self.client.get('/admin/analytics/', follow_redirects=False)
        self.assertEqual(resp_admin.status_code, 200)
        self.assertIn(b'Resource Usage Analytics', resp_admin.data)

    def test_analytics_bookings_data_endpoint(self):
        """Validate JSON structure returned by bookings data endpoint."""
        # Create admin user and login
        admin = User(username='adminuser', email='admin2@example.com', is_admin=True)
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()
        self.login('adminuser', 'password')

        # Create a booking for analytics data
        start = datetime.utcnow()
        end = start + timedelta(hours=1)
        booking = Booking(resource_id=self.resource1.id, user_name='adminuser', start_time=start, end_time=end, title='Analytics Test')
        db.session.add(booking)
        db.session.commit()

        resp = self.client.get('/admin/analytics/data/bookings')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn(self.resource1.name, data)
        self.assertIsInstance(data[self.resource1.name], list)
        first_entry = data[self.resource1.name][0]
        self.assertIsInstance(first_entry, dict)
        self.assertIn('date', first_entry)
        self.assertIn('count', first_entry)


    def test_calendar_page_and_api(self):
        """Calendar page requires login and returns events."""
        # Not logged in -> redirect
        resp = self.client.get('/calendar', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.location)

        self.login('testuser', 'password')

        start = datetime.utcnow()
        end = start + timedelta(hours=1)
        booking = Booking(resource_id=self.resource1.id, user_name='testuser', start_time=start, end_time=end, title='CalTest')
        db.session.add(booking)
        db.session.commit()

        resp_page = self.client.get('/calendar')
        self.assertEqual(resp_page.status_code, 200)

        resp_events = self.client.get('/api/bookings/calendar')
        self.assertEqual(resp_events.status_code, 200)
        events = resp_events.get_json()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['id'], booking.id)

    def test_update_booking_time_via_api(self):
        """Moving a booking updates its time."""
        self.login('testuser', 'password')
        start = datetime.utcnow()
        end = start + timedelta(hours=1)
        booking = Booking(resource_id=self.resource1.id, user_name='testuser', start_time=start, end_time=end, title='MoveMe')
        db.session.add(booking)
        db.session.commit()

        new_start = start + timedelta(hours=2)
        new_end = end + timedelta(hours=2)
        payload = {'start_time': new_start.isoformat(), 'end_time': new_end.isoformat()}
        resp = self.client.put(f'/api/bookings/{booking.id}', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        updated = Booking.query.get(booking.id)
        self.assertEqual(updated.start_time, new_start)
        self.assertEqual(updated.end_time, new_end)

    def test_map_details_includes_location_floor(self):
        """Map details endpoint returns location and floor info."""
        resp = self.client.get(f'/api/map_details/{self.floor_map.id}')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('map_details', data)
        details = data['map_details']
        self.assertEqual(details['location'], 'HQ')
        self.assertEqual(details['floor'], '1')


        self.login('testuser', 'password')
        payload = {
            'resource_id': res.id,
            'date_str': date.today().strftime('%Y-%m-%d'),
            'start_time_str': '10:00',
            'end_time_str': '11:00',
            'title': 'Needs Approval',
            'user_name': 'testuser'
        }
        resp_create = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp_create.status_code, 201)
        booking_id = resp_create.get_json()['id']
        booking = Booking.query.get(booking_id)
        self.assertEqual(booking.status, 'pending')
        self.logout()

        admin = User(username='adminapprove', email='adminapprove@example.com', is_admin=True)
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()
        self.login('adminapprove', 'password')

        resp_pending = self.client.get('/admin/bookings/pending')
        self.assertEqual(resp_pending.status_code, 200)
        self.assertEqual(len(resp_pending.get_json()), 1)

        resp_approve = self.client.post(f'/admin/bookings/{booking_id}/approve')
        self.assertEqual(resp_approve.status_code, 200)
        booking = Booking.query.get(booking_id)
        self.assertEqual(booking.status, 'approved')
        self.assertEqual(len(email_log), 1)
        self.assertEqual(email_log[0]['to'], 'test@example.com')
        self.assertEqual(len(slack_log), 1)

if __name__ == '__main__':
    unittest.main()
