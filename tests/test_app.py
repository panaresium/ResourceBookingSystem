import unittest
import unittest.mock
import json
import urllib.parse
from sqlalchemy import text

from datetime import datetime, time, date, timedelta, timezone as timezone_original
from datetime import datetime as datetime_original, timedelta as timedelta_original # For mocking

from app import app # app object
from extensions import db # db object
from models import User, Resource, Booking, WaitlistEntry, FloorMap, AuditLog, BookingSettings, ResourcePIN, Role # Models
from utils import email_log, teams_log, slack_log # Test log lists
from unittest.mock import patch # For mocking datetime
from datetime import datetime, timedelta, time as dt_time # Added for new test

# from flask_login import current_user # Not directly used for assertions here

class AppTests(unittest.TestCase):

    def setUp(self):
        """Set up test variables."""
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for tests
        app.config['LOGIN_DISABLED'] = False # Ensure login is enabled for tests

        self.app_context = app.app_context()
        self.app_context.push()  # Push app context for db operations

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
            map_coordinates=json.dumps({'type': 'rect', 'x': 10, 'y': 20, 'width': 30, 'height': 30}),
            status='published'
        )
        res2 = Resource(
            name='Room B',
            capacity=4,
            equipment='Whiteboard',
            tags='small',
            floor_map_id=floor_map.id,
            map_coordinates=json.dumps({'type': 'rect', 'x': 50, 'y': 20, 'width': 30, 'height': 30}),
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

    def _create_booking(self, user_name, resource_id, start_offset_hours, duration_hours=1, title="Test Booking"):
        """Helper to create a booking for tests."""
        start_time = datetime.utcnow() + timedelta(hours=start_offset_hours)
        end_time = start_time + timedelta(hours=duration_hours)
        booking = Booking(
            user_name=user_name,
            resource_id=resource_id,
            start_time=start_time,
            end_time=end_time,
            title=title
        )
        db.session.add(booking)
        db.session.commit()
        return booking

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
        self.assertEqual(len(teams_log), 2) # One for booking cancellation, one for waitlist notification
        self.assertTrue(any(entry['to'] == other.email and "Waitlist Slot Released" in entry['title'] for entry in teams_log))
        self.assertTrue(any(entry['to'] == 'test@example.com' and "Booking Cancelled" in entry['title'] for entry in teams_log))


# --- Test Classes for Specific Functionalities ---

class TestAuthAPI(AppTests): # Inherit from AppTests for setup/teardown
    def test_logout_api_and_audit(self):
        """Test API logout, session invalidation, and audit logging."""
        # Login a user
        login_resp = self.login('testuser', 'password')
        self.assertEqual(login_resp.status_code, 200)
        self.assertTrue(login_resp.get_json().get('success'))

        user_id = User.query.filter_by(username='testuser').first().id

        # Perform logout
        logout_resp = self.client.post('/api/auth/logout')
        self.assertEqual(logout_resp.status_code, 200)
        self.assertTrue(logout_resp.get_json().get('success'))

        # Verify user is logged out (e.g., accessing a protected route)
        profile_resp = self.client.get('/profile', follow_redirects=False)
        self.assertEqual(profile_resp.status_code, 302) # Should redirect to login
        self.assertIn('/login', profile_resp.location)

        # Verify audit log
        logout_log = AuditLog.query.filter_by(user_id=user_id, action="LOGOUT_SUCCESS").first()
        self.assertIsNotNone(logout_log)
        self.assertIn("User 'testuser' logged out", logout_log.details)

    def test_logout_route_redirects(self):
        """Ensure /logout logs out the user and redirects to the resources page."""
        login_resp = self.login('testuser', 'password')
        self.assertEqual(login_resp.status_code, 200)

        response = self.client.get('/logout', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/resources', response.location)

        auth_status = self.client.get('/api/auth/status').get_json()
        self.assertFalse(auth_status.get('logged_in'))


class TestBookingUserActions(AppTests):

    def helper_set_checkin_window(self, minutes_before, minutes_after):
        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings()
            db.session.add(settings)
        settings.check_in_minutes_before = minutes_before
        settings.check_in_minutes_after = minutes_after
        # Ensure enable_check_in_out is True for these tests to be meaningful
        settings.enable_check_in_out = True
        db.session.commit()
        return settings

    def helper_create_user_and_login(self, username="testuser_checkin_logic", password="password"):
        user = User.query.filter_by(username=username).first()
        if not user:
            user = User(username=username, email=f'{username}@example.com', is_admin=False)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()

        # Use the class's login method that posts to /api/auth/login
        login_resp = self.login(user.username, password)
        self.assertEqual(login_resp.status_code, 200, f"Login failed in test setup for {username}: {login_resp.get_data(as_text=True)}")
        self.assertTrue(login_resp.get_json().get('success'), f"Login API call was not successful for {username}")
        return user

    def helper_create_resource(self, name="Test Resource Checkin Logic"):
        resource = Resource.query.filter_by(name=name).first()
        if not resource:
            resource = Resource(name=name, capacity=1, status='published') # Ensure status is published
            db.session.add(resource)
            db.session.commit()
        return resource

    def test_update_booking_success_all_fields(self):
        """Test successfully updating title, start_time, and end_time of a booking."""
        self.login('testuser', 'password')
        booking = self._create_booking('testuser', self.resource1.id, start_offset_hours=2)
        
        new_title = "Updated Title for Test"
        new_start_time = booking.start_time + timedelta(hours=1)
        new_end_time = booking.end_time + timedelta(hours=1)

        payload = {
            "title": new_title,
            "start_time": new_start_time.isoformat(),
            "end_time": new_end_time.isoformat()
        }
        
        response = self.client.put(f'/api/bookings/{booking.id}', json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['title'], new_title)
        self.assertEqual(datetime.fromisoformat(data['start_time']).replace(tzinfo=None), new_start_time)
        self.assertEqual(datetime.fromisoformat(data['end_time']).replace(tzinfo=None), new_end_time)

        updated_booking_db = Booking.query.get(booking.id)
        self.assertEqual(updated_booking_db.title, new_title)
        self.assertEqual(updated_booking_db.start_time, new_start_time)
        self.assertEqual(updated_booking_db.end_time, new_end_time)

        # Check audit log
        audit_log = AuditLog.query.filter_by(action="UPDATE_BOOKING_USER").order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log)
        self.assertIn(f"booking ID: {booking.id}", audit_log.details)
        self.assertIn(new_title, audit_log.details)
        self.assertIn(new_start_time.isoformat(), audit_log.details)

    def _run_get_my_bookings_check_in_out_test(self, check_in_out_enabled_setting):
        """Helper function to test get_my_bookings with specific check_in_out setting."""
        # Setup BookingSettings
        BookingSettings.query.delete()
        db.session.add(BookingSettings(enable_check_in_out=check_in_out_enabled_setting))
        db.session.commit()

        # User is already logged in from the calling test
        user = User.query.filter_by(username='testuser').first()

        # Create an active booking for the user
        active_booking = self._create_booking(user.username, self.resource1.id, start_offset_hours=2, title="Active Booking")

        # Create an admin-cancelled booking for the user
        admin_cancelled_booking = self._create_booking(user.username, self.resource2.id, start_offset_hours=3, title="Admin Cancelled Booking")
        admin_cancelled_booking.status = 'cancelled_by_admin'
        admin_cancelled_booking.admin_deleted_message = "Cancelled by an administrator for testing."
        db.session.commit()

        # Action: User makes a GET request to /api/bookings/my_bookings
        response = self.client.get('/api/bookings/my_bookings')

        # Assertions
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        self.assertIsInstance(data, dict)
        self.assertIn('check_in_out_enabled', data)
        self.assertEqual(data['check_in_out_enabled'], check_in_out_enabled_setting)

        self.assertIn('bookings', data)
        self.assertIsInstance(data['bookings'], list)
        self.assertEqual(len(data['bookings']), 2) # Expecting both bookings

        active_booking_data = next((b for b in data['bookings'] if b['id'] == active_booking.id), None)
        self.assertIsNotNone(active_booking_data)
        self.assertEqual(active_booking_data['title'], "Active Booking")
        self.assertIsNone(active_booking_data.get('admin_deleted_message')) # Should not have this message

        admin_cancelled_booking_data = next((b for b in data['bookings'] if b['id'] == admin_cancelled_booking.id), None)
        self.assertIsNotNone(admin_cancelled_booking_data)
        self.assertEqual(admin_cancelled_booking_data['title'], "Admin Cancelled Booking")
        self.assertEqual(admin_cancelled_booking_data['status'], 'cancelled_by_admin')
        self.assertEqual(admin_cancelled_booking_data['admin_deleted_message'], "Cancelled by an administrator for testing.")

        # Clean up bookings for subsequent runs if any
        Booking.query.filter_by(user_name=user.username).delete()
        db.session.commit()

    def test_get_my_bookings_includes_check_in_out_setting(self):
        """Test /api/bookings/my_bookings returns categorized, sorted, and filtered bookings."""
        self.login('testuser', 'password')
        user = User.query.filter_by(username='testuser').first()

        for check_in_out_setting in [True, False]:
            with self.subTest(check_in_out_enabled=check_in_out_setting):
                BookingSettings.query.delete()
                db.session.add(BookingSettings(enable_check_in_out=check_in_out_setting))
                db.session.commit()

                Booking.query.filter_by(user_name=user.username).delete()
                db.session.commit()

                now = datetime.utcnow()
                today_date = now.date()
                tomorrow_date = today_date + timedelta(days=1)
                yesterday_date = today_date - timedelta(days=1)
                specific_future_date = today_date + timedelta(days=5)

                # Create bookings
                bookings_setup = {
                    "upcoming_approved_today": Booking(user_name=user.username, resource_id=self.resource1.id, title="Upcoming Approved Today", status="approved", start_time=now + timedelta(hours=2), end_time=now + timedelta(hours=3)),
                    "upcoming_pending_tomorrow": Booking(user_name=user.username, resource_id=self.resource1.id, title="Tomorrow Pending", status="pending", start_time=datetime.combine(tomorrow_date, dt_time(10,0)), end_time=datetime.combine(tomorrow_date, dt_time(11,0))),
                    "past_completed_yesterday": Booking(user_name=user.username, resource_id=self.resource2.id, title="Yesterday Completed", status="completed", start_time=datetime.combine(yesterday_date, dt_time(10,0)), end_time=datetime.combine(yesterday_date, dt_time(11,0))),
                    "past_cancelled_today": Booking(user_name=user.username, resource_id=self.resource2.id, title="Past Cancelled Today", status="cancelled_by_admin", start_time=now - timedelta(hours=3), end_time=now - timedelta(hours=2)),
                    "specific_date_approved": Booking(user_name=user.username, resource_id=self.resource1.id, title="Specific Date Approved", status="approved", start_time=datetime.combine(specific_future_date, dt_time(9,0)), end_time=datetime.combine(specific_future_date, dt_time(10,0))),
                    "specific_date_pending": Booking(user_name=user.username, resource_id=self.resource1.id, title="Specific Date Pending", status="pending", start_time=datetime.combine(specific_future_date, dt_time(11,0)), end_time=datetime.combine(specific_future_date, dt_time(12,0))),
                    "another_upcoming_approved": Booking(user_name=user.username, resource_id=self.resource2.id, title="Another Upcoming Approved", status="approved", start_time=now + timedelta(hours=5), end_time=now + timedelta(hours=6))
                }
                for b in bookings_setup.values(): db.session.add(b)
                db.session.commit()
                # Store IDs for assertions
                b_ids = {name: b.id for name, b in bookings_setup.items()}

                # --- Test Case 1: No Filters ---
                response_no_filter = self.client.get('/api/bookings/my_bookings')
                self.assertEqual(response_no_filter.status_code, 200)
                data_no_filter = response_no_filter.get_json()
                self.assertEqual(data_no_filter['check_in_out_enabled'], check_in_out_setting)

                # Expected: 4 upcoming (approved_today, pending_tomorrow, specific_date_approved, specific_date_pending, another_upcoming_approved)
                # Note: self._create_booking from parent class creates approved bookings.
                # The exact number of upcoming/past depends on precise timing of "now" vs start_offset_hours.
                # Let's verify based on the titles we expect.
                upcoming_titles_no_filter = {b['title'] for b in data_no_filter['upcoming_bookings']}
                past_titles_no_filter = {b['title'] for b in data_no_filter['past_bookings']}

                self.assertIn("Upcoming Approved Today", upcoming_titles_no_filter)
                self.assertIn("Tomorrow Pending", upcoming_titles_no_filter)
                self.assertIn("Specific Date Approved", upcoming_titles_no_filter)
                self.assertIn("Specific Date Pending", upcoming_titles_no_filter)
                self.assertIn("Another Upcoming Approved", upcoming_titles_no_filter)
                self.assertEqual(len(data_no_filter['upcoming_bookings']), 5)


                self.assertIn("Yesterday Completed", past_titles_no_filter)
                self.assertIn("Past Cancelled Today", past_titles_no_filter)
                self.assertEqual(len(data_no_filter['past_bookings']), 2)

                # Check sorting (example for upcoming)
                if len(data_no_filter['upcoming_bookings']) > 1:
                    upcoming_times = [b['start_time'] for b in data_no_filter['upcoming_bookings']]
                    self.assertEqual(upcoming_times, sorted(upcoming_times))

                # --- Test Case 2: Filter by Status ---
                status_test_cases = {
                    "approved": {"upcoming": [b_ids["upcoming_approved_today"], b_ids["specific_date_approved"], b_ids["another_upcoming_approved"]], "past": []},
                    "pending": {"upcoming": [b_ids["upcoming_pending_tomorrow"], b_ids["specific_date_pending"]], "past": []},
                    "completed": {"upcoming": [], "past": [b_ids["past_completed_yesterday"]]},
                    "cancelled_by_admin": {"upcoming": [], "past": [b_ids["past_cancelled_today"]]}
                }
                for status, expected_ids in status_test_cases.items():
                    with self.subTest(status_filter=status):
                        resp_status = self.client.get(f'/api/bookings/my_bookings?status_filter={status}')
                        self.assertEqual(resp_status.status_code, 200)
                        data_status = resp_status.get_json()

                        upcoming_ids_status = {b['id'] for b in data_status['upcoming_bookings']}
                        past_ids_status = {b['id'] for b in data_status['past_bookings']}

                        self.assertSetEqual(upcoming_ids_status, set(expected_ids["upcoming"]))
                        self.assertSetEqual(past_ids_status, set(expected_ids["past"]))
                        if len(data_status['upcoming_bookings']) > 1:
                             self.assertEqual([b['id'] for b in data_status['upcoming_bookings']], sorted([b_ids[name] for name, b_obj in bookings_setup.items() if b_obj.id in expected_ids["upcoming"]], key=lambda bid: bookings_setup[[n for n,oid in b_ids.items() if oid==bid][0]].start_time))
                        if len(data_status['past_bookings']) > 1:
                             self.assertEqual([b['id'] for b in data_status['past_bookings']], sorted([b_ids[name] for name, b_obj in bookings_setup.items() if b_obj.id in expected_ids["past"]], key=lambda bid: bookings_setup[[n for n,oid in b_ids.items() if oid==bid][0]].start_time, reverse=True))


                # --- Test Case 3: Filter by Date ---
                resp_date_specific = self.client.get(f'/api/bookings/my_bookings?date_filter_value={specific_future_date.strftime("%Y-%m-%d")}')
                self.assertEqual(resp_date_specific.status_code, 200)
                data_date_specific = resp_date_specific.get_json()
                upcoming_ids_date = {b['id'] for b in data_date_specific['upcoming_bookings']}
                self.assertSetEqual(upcoming_ids_date, {b_ids["specific_date_approved"], b_ids["specific_date_pending"]})
                self.assertEqual(len(data_date_specific['past_bookings']), 0)

                # --- Test Case 4: Filter by Status AND Date ---
                resp_status_date = self.client.get(f'/api/bookings/my_bookings?status_filter=approved&date_filter_value={specific_future_date.strftime("%Y-%m-%d")}')
                self.assertEqual(resp_status_date.status_code, 200)
                data_status_date = resp_status_date.get_json()
                upcoming_ids_status_date = {b['id'] for b in data_status_date['upcoming_bookings']}
                self.assertSetEqual(upcoming_ids_status_date, {b_ids["specific_date_approved"]})
                self.assertEqual(len(data_status_date['past_bookings']), 0)

                # Clean up bookings for this sub-test iteration
                Booking.query.filter(Booking.id.in_(b_ids.values())).delete()
                db.session.commit()

        BookingSettings.query.delete()
        db.session.commit()

    def test_update_booking_invalid_time_range(self):
        """Test error when start_time is not before end_time during booking update."""
        self.login('testuser', 'password')
        booking = self._create_booking('testuser', self.resource1.id, start_offset_hours=2)
        
        payload = {
            "start_time": (booking.end_time + timedelta(hours=1)).isoformat(), # Start after original end
            "end_time": booking.start_time.isoformat() # End at original start
        }
        response = self.client.put(f'/api/bookings/{booking.id}', json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Start time must be before end time", response.get_json().get('error', ''))

    def test_update_booking_conflict_existing_booking(self):
        """Test conflict (409) when updated times overlap with another booking."""
        self.login('testuser', 'password')
        booking1 = self._create_booking('testuser', self.resource1.id, start_offset_hours=2, title="Booking One")
        booking2 = self._create_booking('another_user', self.resource1.id, start_offset_hours=4, title="Booking Two") # Different user, same resource

        payload = {
            "start_time": booking2.start_time.isoformat(), # Try to move booking1 to booking2's time
            "end_time": booking2.end_time.isoformat()
        }
        response = self.client.put(f'/api/bookings/{booking1.id}', json=payload)
        self.assertEqual(response.status_code, 409)
        self.assertIn("conflicts with an existing booking", response.get_json().get('error', ''))

    def test_update_booking_conflict_maintenance_period(self):
        """Test error (403) when updated times fall into resource maintenance."""
        self.login('testuser', 'password')
        booking = self._create_booking('testuser', self.resource1.id, start_offset_hours=24) # Booking far in future

        # Set resource under maintenance for a period that would conflict with an update
        maintenance_start = datetime.utcnow() + timedelta(hours=48)
        maintenance_end = maintenance_start + timedelta(hours=5)
        self.resource1.is_under_maintenance = True
        self.resource1.maintenance_until = maintenance_end
        db.session.commit()

        payload = {
            "start_time": maintenance_start.isoformat(),
            "end_time": (maintenance_start + timedelta(hours=1)).isoformat()
        }
        response = self.client.put(f'/api/bookings/{booking.id}', json=payload)
        self.assertEqual(response.status_code, 403)
        self.assertIn("Resource is under maintenance", response.get_json().get('error', ''))

    def test_update_booking_title_only_during_maintenance(self):
        """Test that title can be updated if booking is already in maintenance, but time cannot be."""
        self.login('testuser', 'password')
        
        maintenance_start = datetime.utcnow() + timedelta(hours=1)
        maintenance_end = maintenance_start + timedelta(hours=5)
        self.resource1.is_under_maintenance = True
        self.resource1.maintenance_until = maintenance_end
        db.session.commit()

        # Create a booking *within* the maintenance period
        booking_start_in_maint = maintenance_start + timedelta(hours=1)
        booking_end_in_maint = booking_start_in_maint + timedelta(hours=1)
        booking = self._create_booking('testuser', self.resource1.id, start_offset_hours=0) # Temp values, will update
        booking.start_time = booking_start_in_maint
        booking.end_time = booking_end_in_maint
        db.session.commit()

        # Update title only
        payload_title = {"title": "New Title During Maintenance"}
        response_title = self.client.put(f'/api/bookings/{booking.id}', json=payload_title)
        self.assertEqual(response_title.status_code, 200)
        self.assertEqual(Booking.query.get(booking.id).title, "New Title During Maintenance")

        # Try to update time (even to another slot within maintenance) - current logic might prevent this
        # Depending on exact backend logic, this might be 403 or 200.
        # The current backend logic: if time_changed and resource.is_under_maintenance and new_time_in_maintenance -> 403
        # This means even shifting within maintenance is denied if time changes.
        payload_time_shift = {
            "start_time": (booking_start_in_maint + timedelta(minutes=30)).isoformat(),
            "end_time": (booking_end_in_maint + timedelta(minutes=30)).isoformat()
        }
        response_time_shift = self.client.put(f'/api/bookings/{booking.id}', json=payload_time_shift)
        self.assertEqual(response_time_shift.status_code, 403) # Expecting 403 as time changed.

    def test_get_my_bookings_with_check_in_token(self):
        # 1. Create user
        user = User(username='testuser_token', email='testuser_token@example.com', is_admin=False)
        user.set_password('password')
        # user.is_active = True # Add if AttributeError: 'User' object has no attribute 'is_active' occurs
        db.session.add(user)
        db.session.commit()

        # 2. Create resource
        resource = Resource(name='Test Resource Token', capacity=10, status='published') # Ensure status is published
        db.session.add(resource)
        db.session.commit()

        # 3. Login
        # Use self.login helper which uses /api/auth/login
        login_resp = self.login('testuser_token', 'password')
        self.assertEqual(login_resp.status_code, 200, f"Login failed: {login_resp.get_data(as_text=True)}")
        self.assertTrue(login_resp.get_json().get('success'), "Login API call was not successful")


        # 4. Create a booking (ensure it's in the future)
        # Ensure datetime and timedelta are imported: from datetime import datetime, timedelta
        future_start_dt = datetime.utcnow() + timedelta(days=1, hours=2) # Booking tomorrow 2 hours from now UTC
        future_end_dt = future_start_dt + timedelta(hours=1)

        booking_payload = {
            'resource_id': resource.id,
            # Using direct datetime objects for payload to /api/bookings might not be standard.
            # The API route /api/bookings expects 'date_str', 'start_time_str', 'end_time_str'.
            'date_str': future_start_dt.strftime('%Y-%m-%d'),
            'start_time_str': future_start_dt.strftime('%H:%M'),
            'end_time_str': future_end_dt.strftime('%H:%M'),
            'title': 'Booking with Token Test',
            'user_name': 'testuser_token' # Pass username, route will get current_user if not admin
        }
        response_create = self.client.post('/api/bookings', json=booking_payload)
        self.assertEqual(response_create.status_code, 201, f"Booking creation failed: {response_create.get_data(as_text=True)}")

        created_booking_data_list = response_create.get_json().get('bookings')
        self.assertIsNotNone(created_booking_data_list, "No 'bookings' list in creation response")
        self.assertTrue(len(created_booking_data_list) > 0, "Booking list is empty in creation response")
        created_booking_data = created_booking_data_list[0]
        booking_id = created_booking_data['id']

        # 5. Call /api/bookings/my_bookings
        response_my_bookings = self.client.get('/api/bookings/my_bookings')

        # 6. Assert status code
        self.assertEqual(response_my_bookings.status_code, 200, f"Fetching my_bookings failed: {response_my_bookings.get_data(as_text=True)}")

        # 7. Assert booking is present
        my_bookings_data = response_my_bookings.get_json()
        self.assertIn('bookings', my_bookings_data)

        found_booking_json = None # Renamed to avoid conflict with model name 'Booking'
        for b_json in my_bookings_data['bookings']:
            if b_json['id'] == booking_id:
                found_booking_json = b_json
                break

        self.assertIsNotNone(found_booking_json, "Created booking not found in my_bookings response")

        # 8. Assert check_in_token is present and not empty
        self.assertIn('check_in_token', found_booking_json)

        # Verify booking conditions for token presence based on logic in routes/api_bookings.py get_my_bookings
        # The token should be present if:
        # - settings.enable_check_in_out is True (let's assume it is for this test, or set it)
        # - booking.status == 'approved'
        # - not booking.checked_in_at
        # - booking.start_time > datetime.utcnow() (it's a future booking)
        # - OR (booking.start_time <= datetime.utcnow() < booking.end_time) (it's current)
        # For this test, it's a future, approved, not-checked-in booking.

        # Ensure enable_check_in_out is True for this test
        current_settings = BookingSettings.query.first()
        original_check_in_out_setting = None
        if current_settings:
            original_check_in_out_setting = current_settings.enable_check_in_out
            current_settings.enable_check_in_out = True
        else:
            current_settings = BookingSettings(enable_check_in_out=True)
            db.session.add(current_settings)
        db.session.commit()

        # Re-fetch my_bookings if the setting change affects token generation logic server-side for the response
        response_my_bookings_after_setting = self.client.get('/api/bookings/my_bookings')
        self.assertEqual(response_my_bookings_after_setting.status_code, 200)
        my_bookings_data_after_setting = response_my_bookings_after_setting.get_json()
        found_booking_json_after_setting = None
        for b_json in my_bookings_data_after_setting['bookings']:
            if b_json['id'] == booking_id:
                found_booking_json_after_setting = b_json
                break
        self.assertIsNotNone(found_booking_json_after_setting, "Booking not found after ensuring check-in setting.")
        self.assertIn('check_in_token', found_booking_json_after_setting)


        # The token can be None if conditions are not met.
        # For a new, future, approved, non-checked-in booking, it should be a string.
        is_future_booking = datetime.fromisoformat(found_booking_json_after_setting['start_time'].replace('Z', '+00:00')) > datetime.utcnow()
        is_approved = found_booking_json_after_setting['status'] == 'approved'
        is_not_checked_in = not found_booking_json_after_setting['checked_in_at']

        if is_future_booking and is_approved and is_not_checked_in:
            self.assertIsInstance(found_booking_json_after_setting['check_in_token'], str, "check_in_token should be a string for future, approved, non-checked-in bookings")
            self.assertTrue(len(found_booking_json_after_setting['check_in_token']) > 0, "check_in_token should be a non-empty string")
        else:
            # This else branch indicates a potential issue with test setup or understanding of token generation logic
            self.fail(f"Booking did not meet conditions for check_in_token generation: is_future={is_future_booking}, is_approved={is_approved}, is_not_checked_in={is_not_checked_in}")

        # Clean up: logout
        self.logout() # Use helper for API logout

        # Restore original BookingSettings if changed
        if original_check_in_out_setting is not None:
            current_settings.enable_check_in_out = original_check_in_out_setting
            db.session.commit()
        elif current_settings: # if it was created new
            db.session.delete(current_settings)
            db.session.commit()

    def test_check_in_with_custom_window_success(self):
        self.helper_set_checkin_window(minutes_before=10, minutes_after=5)
        user = self.helper_create_user_and_login(username="user_checkin_success")
        resource = self.helper_create_resource(name="Resource Checkin Success")

        # Booking start_time is 3 minutes ago, current time is within 10min before / 5min after window.
        # We simulate this by creating a booking as if its start_time was 3 minutes ago from "now".
        # The check_in_booking API uses datetime.now(timezone.utc) internally.
        # So, the booking's start_time must be relative to that internal 'now'.
        # To make it deterministic, we'd ideally mock 'now' in the route, but that's more complex.
        # Alternative: create booking that *will be* in window when check_in is called.
        # For this test, let's make the booking start slightly in the past relative to the call.

        # Simulate current time is 3 minutes after booking start.
        # So, booking_start_dt should be now - 3 minutes.
        # This means when the API call is made, 'now' will be roughly booking_start_dt + 3 minutes.
        # This falls within the -10 to +5 minute window.

        # To simplify and make it less dependent on exact execution speed of test lines:
        # Let's set a booking that starts *now* (or a few seconds in the past due to execution)
        # and check in immediately. This should be within the 10 min before window.
        booking_start_dt = datetime.utcnow() - timedelta(minutes=2) # Start 2 mins ago
        booking_end_dt = booking_start_dt + timedelta(hours=1)

        booking_payload = {
            'resource_id': resource.id,
            'date_str': booking_start_dt.strftime('%Y-%m-%d'),
            'start_time_str': booking_start_dt.strftime('%H:%M'),
            'end_time_str': booking_end_dt.strftime('%H:%M'),
            'title': 'Test Check-in Success Custom Window',
            'user_name': user.username
        }
        create_resp = self.client.post('/api/bookings', json=booking_payload)
        self.assertEqual(create_resp.status_code, 201, f"Booking creation failed: {create_resp.get_data(as_text=True)}")
        booking_id = create_resp.get_json()['bookings'][0]['id']

        check_in_resp = self.client.post(f'/api/bookings/{booking_id}/check_in')
        self.assertEqual(check_in_resp.status_code, 200, f"Check-in failed: {check_in_resp.get_data(as_text=True)}")
        self.assertIn('Check-in successful', check_in_resp.get_data(as_text=True))

        booking = Booking.query.get(booking_id)
        self.assertIsNotNone(booking.checked_in_at)
        self.logout() # Use the class's logout method

    def test_check_in_too_early_custom_window(self):
        settings = self.helper_set_checkin_window(minutes_before=10, minutes_after=5)
        user = self.helper_create_user_and_login(username="user_checkin_early")
        resource = self.helper_create_resource(name="Resource Checkin Early")

        # Booking starts 15 minutes from now. Check-in allowed 10 mins before. So, this is too early.
        # To make test robust, we ensure booking_start_dt is relative to mocked 'now' if we mock it,
        # or sufficiently in future if using real 'now'.
        booking_start_dt = datetime.utcnow() + timedelta(minutes=15)
        booking_end_dt = booking_start_dt + timedelta(hours=1)

        booking_payload = {
            'resource_id': resource.id,
            'date_str': booking_start_dt.strftime('%Y-%m-%d'),
            'start_time_str': booking_start_dt.strftime('%H:%M'),
            'end_time_str': booking_end_dt.strftime('%H:%M'),
            'title': 'Test Check-in Too Early Custom',
            'user_name': user.username
        }
        create_resp = self.client.post('/api/bookings', json=booking_payload)
        self.assertEqual(create_resp.status_code, 201, f"Booking creation failed: {create_resp.get_data(as_text=True)}")
        booking_id = create_resp.get_json()['bookings'][0]['id']

        check_in_resp = self.client.post(f'/api/bookings/{booking_id}/check_in')
        self.assertEqual(check_in_resp.status_code, 403, f"Check-in should have failed (too early): {check_in_resp.get_data(as_text=True)}")
        expected_error_msg_part = f"Check-in is only allowed from {settings.check_in_minutes_before} minutes before to {settings.check_in_minutes_after} minutes after"
        self.assertIn(expected_error_msg_part, check_in_resp.get_json().get('error', ''))
        self.logout()

    def test_check_in_too_late_custom_window(self):
        settings = self.helper_set_checkin_window(minutes_before=10, minutes_after=5)
        user = self.helper_create_user_and_login(username="user_checkin_late")
        resource = self.helper_create_resource(name="Resource Checkin Late")

        # Booking started 10 minutes ago. Check-in allowed up to 5 mins after. So, this is too late.
        booking_start_dt = datetime.utcnow() - timedelta(minutes=10)
        booking_end_dt = booking_start_dt + timedelta(hours=1)

        booking_payload = {
            'resource_id': resource.id,
            'date_str': booking_start_dt.strftime('%Y-%m-%d'),
            'start_time_str': booking_start_dt.strftime('%H:%M'),
            'end_time_str': booking_end_dt.strftime('%H:%M'),
            'title': 'Test Check-in Too Late Custom',
            'user_name': user.username
        }
        create_resp = self.client.post('/api/bookings', json=booking_payload)
        self.assertEqual(create_resp.status_code, 201, f"Booking creation failed: {create_resp.get_data(as_text=True)}")
        booking_id = create_resp.get_json()['bookings'][0]['id']

        check_in_resp = self.client.post(f'/api/bookings/{booking_id}/check_in')
        self.assertEqual(check_in_resp.status_code, 403, f"Check-in should have failed (too late): {check_in_resp.get_data(as_text=True)}")
        expected_error_msg_part = f"Check-in is only allowed from {settings.check_in_minutes_before} minutes before to {settings.check_in_minutes_after} minutes after"
        self.assertIn(expected_error_msg_part, check_in_resp.get_json().get('error', ''))
        self.logout()

    def _create_pin_for_resource(self, resource_id, pin_value="VALIDPIN4TEST", is_active=True):
        """Helper to create a ResourcePIN for a resource."""
        pin = ResourcePIN.query.filter_by(resource_id=resource_id, pin_value=pin_value).first()
        if not pin:
            pin = ResourcePIN(resource_id=resource_id, pin_value=pin_value, is_active=is_active)
            db.session.add(pin)
            db.session.commit()
        else: # Ensure it's in the desired state
            pin.is_active = is_active
            db.session.commit()

        # Update resource.current_pin if this is the first active one or becomes active
        resource = Resource.query.get(resource_id)
        if is_active and (not resource.current_pin or resource.current_pin != pin_value):
            # This simplified logic might need adjustment if multiple active PINs are handled differently for current_pin
            resource.current_pin = pin_value
            db.session.commit()
        elif not is_active and resource.current_pin == pin_value:
            resource.current_pin = None # Clear it if the deactivated PIN was current
            # Optionally, find another active PIN to set as current if business logic requires
            db.session.commit()
        return pin

    @patch('routes.api_bookings.datetime')
    def test_direct_checkin_with_valid_pin(self, mock_datetime_obj):
        user = self.helper_create_user_and_login(username="user_direct_pin_valid")
        resource = self.helper_create_resource(name="ResourceDirectPinValid")
        pin = self._create_pin_for_resource(resource.id, "DPIN001")
        booking_settings = self.helper_set_checkin_window(minutes_before=15, minutes_after=15)

        # Create a booking that starts "now" according to mock time
        mocked_now_dt = datetime_original(2024, 7, 15, 12, 0, 0) # Fixed reference for "now"
        mock_datetime_obj.now.return_value = mocked_now_dt.replace(tzinfo=timezone_original.utc)
        mock_datetime_obj.utcnow.return_value = mocked_now_dt # if utcnow is used
        mock_datetime_obj.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs)

        # Booking starts exactly at mocked_now, so it's within check-in window
        booking = self._create_booking(user.username, resource.id, start_offset_hours=0) # This uses datetime.utcnow()
        # Adjust booking time to be relative to mocked_now for test consistency
        booking.start_time = mocked_now_dt
        booking.end_time = mocked_now_dt + timedelta_original(hours=1)
        db.session.commit()

        response = self.client.post(f'/api/bookings/{booking.id}/check_in', json={'pin': pin.pin_value})
        self.assertEqual(response.status_code, 200, f"Direct PIN check-in failed: {response.get_json()}")
        self.assertIn("Check-in successful", response.get_json().get('message'))

        db.session.refresh(booking)
        self.assertIsNotNone(booking.checked_in_at)

        audit_log = AuditLog.query.filter_by(action="USER_CHECK_IN_BOOKING").order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log.user_id, user.id)
        self.assertIn(f"Booking ID {booking.id} checked in.", audit_log.details)
        self.assertIn(f"PIN {pin.pin_value} used for check-in.", audit_log.details)
        self.logout()

    @patch('routes.api_bookings.datetime')
    def test_direct_checkin_with_invalid_pin(self, mock_datetime_obj):
        user = self.helper_create_user_and_login(username="user_direct_pin_invalid")
        resource = self.helper_create_resource(name="ResourceDirectPinInvalid")
        self.helper_set_checkin_window(minutes_before=15, minutes_after=15)

        mocked_now_dt = datetime_original(2024, 7, 15, 12, 0, 0)
        mock_datetime_obj.now.return_value = mocked_now_dt.replace(tzinfo=timezone_original.utc)
        mock_datetime_obj.utcnow.return_value = mocked_now_dt
        mock_datetime_obj.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs)

        booking = self._create_booking(user.username, resource.id, start_offset_hours=0)
        booking.start_time = mocked_now_dt; booking.end_time = mocked_now_dt + timedelta_original(hours=1); db.session.commit()

        response = self.client.post(f'/api/bookings/{booking.id}/check_in', json={'pin': 'INVALIDPIN123'})
        self.assertEqual(response.status_code, 403, f"Response: {response.get_json()}")
        self.assertIn("Invalid PIN provided for resource.", response.get_json().get('error'))

        db.session.refresh(booking)
        self.assertIsNone(booking.checked_in_at)

        audit_log = AuditLog.query.filter_by(action="USER_CHECK_IN_FAIL_INVALID_PIN").order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log.user_id, user.id)
        self.assertIn(f"Booking ID {booking.id}", audit_log.details)
        self.assertIn("Attempted PIN: INVALIDPIN123", audit_log.details)
        self.logout()

    @patch('routes.api_bookings.datetime')
    def test_direct_checkin_with_inactive_pin(self, mock_datetime_obj):
        user = self.helper_create_user_and_login(username="user_direct_pin_inactive")
        resource = self.helper_create_resource(name="ResourceDirectPinInactive")
        pin = self._create_pin_for_resource(resource.id, "INACTIVE00", is_active=False)
        self.helper_set_checkin_window(minutes_before=15, minutes_after=15)

        mocked_now_dt = datetime_original(2024, 7, 15, 12, 0, 0)
        mock_datetime_obj.now.return_value = mocked_now_dt.replace(tzinfo=timezone_original.utc)
        mock_datetime_obj.utcnow.return_value = mocked_now_dt
        mock_datetime_obj.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs)

        booking = self._create_booking(user.username, resource.id, start_offset_hours=0)
        booking.start_time = mocked_now_dt; booking.end_time = mocked_now_dt + timedelta_original(hours=1); db.session.commit()


        response = self.client.post(f'/api/bookings/{booking.id}/check_in', json={'pin': pin.pin_value})
        self.assertEqual(response.status_code, 403, f"Response: {response.get_json()}")
        self.assertIn("PIN is not active.", response.get_json().get('error'))

        db.session.refresh(booking)
        self.assertIsNone(booking.checked_in_at)
        self.logout()

    @patch('routes.api_bookings.datetime')
    def test_direct_checkin_without_pin_success(self, mock_datetime_obj):
        user = self.helper_create_user_and_login(username="user_direct_nopin")
        resource = self.helper_create_resource(name="ResourceDirectNoPin")
        # No PIN created for this resource, or at least not provided
        self.helper_set_checkin_window(minutes_before=15, minutes_after=15)

        mocked_now_dt = datetime_original(2024, 7, 15, 12, 0, 0)
        mock_datetime_obj.now.return_value = mocked_now_dt.replace(tzinfo=timezone_original.utc)
        mock_datetime_obj.utcnow.return_value = mocked_now_dt
        mock_datetime_obj.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs)

        booking = self._create_booking(user.username, resource.id, start_offset_hours=0)
        booking.start_time = mocked_now_dt; booking.end_time = mocked_now_dt + timedelta_original(hours=1); db.session.commit()

        response = self.client.post(f'/api/bookings/{booking.id}/check_in', json={}) # Empty JSON, no PIN
        self.assertEqual(response.status_code, 200, f"Direct check-in without PIN failed: {response.get_json()}")
        self.assertIn("Check-in successful", response.get_json().get('message'))

        db.session.refresh(booking)
        self.assertIsNotNone(booking.checked_in_at)

        audit_log = AuditLog.query.filter_by(action="USER_CHECK_IN_BOOKING").order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log)
        self.assertNotIn("PIN", audit_log.details, "Audit log should not mention PIN if none was used.")
        self.logout()

    @patch('routes.api_bookings.datetime')
    def test_direct_checkin_with_pin_outside_window(self, mock_datetime_obj):
        user = self.helper_create_user_and_login(username="user_direct_pin_outside")
        resource = self.helper_create_resource(name="ResourceDirectPinOutside")
        pin = self._create_pin_for_resource(resource.id, "DPIN002")
        booking_settings = self.helper_set_checkin_window(minutes_before=15, minutes_after=15) # Window is +/- 15 mins around start

        # Mock time to be 30 minutes BEFORE booking start_time (outside window)
        mocked_now_dt = datetime_original(2024, 7, 15, 10, 0, 0) # Reference "now"
        booking_start_dt = mocked_now_dt + timedelta_original(minutes=30 + booking_settings.check_in_minutes_before + 1) # Booking starts far enough

        mock_datetime_obj.now.return_value = mocked_now_dt.replace(tzinfo=timezone_original.utc)
        mock_datetime_obj.utcnow.return_value = mocked_now_dt
        mock_datetime_obj.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs)

        booking = self._create_booking(user.username, resource.id, start_offset_hours=0) # Create booking first
        booking.start_time = booking_start_dt # Now align its start time
        booking.end_time = booking_start_dt + timedelta_original(hours=1)
        db.session.commit()

        response = self.client.post(f'/api/bookings/{booking.id}/check_in', json={'pin': pin.pin_value})
        self.assertEqual(response.status_code, 403, f"Response: {response.get_json()}")
        # Expected error message comes from the check_in_booking function's window validation
        expected_error_msg_part = f"Check-in is only allowed from {booking_settings.check_in_minutes_before} minutes before to {booking_settings.check_in_minutes_after} minutes after the booking start time."
        self.assertIn(expected_error_msg_part, response.get_json().get('error', ''))

        db.session.refresh(booking)
        self.assertIsNone(booking.checked_in_at)
        self.logout()


class TestAdminFunctionality(AppTests): # Renamed from AppTests to avoid confusion
    def _create_admin_user(self, username="testadmin", email_ext="admin"):
        admin_user = User(username=username, email=f"{email_ext}@example.com", is_admin=True)
        admin_user.set_password("adminpass")
        db.session.add(admin_user)
        db.session.commit()
        return admin_user

    def test_update_resource_status_direct_and_published_at(self):
        """Test direct update of resource status and published_at behavior."""
        admin = self._create_admin_user()
        self.login(admin.username, "adminpass")

        resource = Resource(name="Status Test Resource", status="draft")
        db.session.add(resource)
        db.session.commit()
        self.assertIsNone(resource.published_at)

        # Update to published
        response = self.client.put(f'/api/admin/resources/{resource.id}', json={"status": "published"})
        self.assertEqual(response.status_code, 200)
        updated_resource = Resource.query.get(resource.id)
        self.assertEqual(updated_resource.status, "published")
        self.assertIsNotNone(updated_resource.published_at)
        first_published_at = updated_resource.published_at

        # Update to archived
        response = self.client.put(f'/api/admin/resources/{resource.id}', json={"status": "archived"})
        self.assertEqual(response.status_code, 200)
        updated_resource = Resource.query.get(resource.id)
        self.assertEqual(updated_resource.status, "archived")
        self.assertEqual(updated_resource.published_at, first_published_at) # Should not change

        # Update back to draft
        response = self.client.put(f'/api/admin/resources/{resource.id}', json={"status": "draft"})
        self.assertEqual(response.status_code, 200)
        updated_resource = Resource.query.get(resource.id)
        self.assertEqual(updated_resource.status, "draft")
        self.assertEqual(updated_resource.published_at, first_published_at) # Should still not change

    def test_schedule_resource_status_change_api(self):
        """Test setting scheduled_status and scheduled_status_at via API."""
        admin = self._create_admin_user(username="scheduleadmin", email_ext="schedule")
        self.login(admin.username, "adminpass")

        resource = Resource(name="Sched Test Resource", status="draft")
        db.session.add(resource)
        db.session.commit()

        future_time = datetime.utcnow() + timedelta(days=1)
        payload = {
            "scheduled_status": "published",
            "scheduled_status_at": future_time.isoformat()
        }
        
        response = self.client.put(f'/api/admin/resources/{resource.id}', json=payload)
        self.assertEqual(response.status_code, 200)
        
        updated_resource = Resource.query.get(resource.id)
        self.assertEqual(updated_resource.scheduled_status, "published")
        # Compare datetimes by first ensuring they are both offset-naive if needed, or by converting to same timezone
        # For ISO format strings from API vs. naive datetime from DB:
        self.assertEqual(updated_resource.scheduled_status_at.replace(tzinfo=None), future_time.replace(tzinfo=None))


    def test_schedule_resource_status_validation(self):
        """Test validation for scheduled_status and scheduled_status_at."""
        admin = self._create_admin_user(username="schedulevalidation", email_ext="schedval")
        self.login(admin.username, "adminpass")
        resource = Resource(name="Sched Valid Resource", status="draft")
        db.session.add(resource)
        db.session.commit()

        # Invalid scheduled_status
        payload_invalid_status = {
            "scheduled_status": "pending_approval", # Not a valid status
            "scheduled_status_at": (datetime.utcnow() + timedelta(days=1)).isoformat()
        }
        response_invalid_status = self.client.put(f'/api/admin/resources/{resource.id}', json=payload_invalid_status)
        self.assertEqual(response_invalid_status.status_code, 400)
        self.assertIn("Invalid scheduled_status value", response_invalid_status.get_json().get('error', ''))

        # Invalid scheduled_status_at format
        payload_invalid_date = {
            "scheduled_status": "published",
            "scheduled_status_at": "not-a-valid-datetime-string"
        }
        response_invalid_date = self.client.put(f'/api/admin/resources/{resource.id}', json=payload_invalid_date)
        self.assertEqual(response_invalid_date.status_code, 400)
        self.assertIn("Invalid scheduled_status_at format", response_invalid_date.get_json().get('error', ''))

    @unittest.mock.patch('app.datetime') # Mock datetime in the 'app' module where the scheduler job uses it
    def test_apply_scheduled_status_change_job(self, mock_datetime):
        """Test the APScheduler job for applying scheduled status changes."""
        from app import apply_scheduled_resource_status_changes # Import here to use the mocked datetime

        admin = self._create_admin_user(username="scheduleradmin", email_ext="scheduler")
        self.login(admin.username, "adminpass") # Login might not be strictly necessary if job is system-level

        # Scenario 1: Draft to Published
        past_schedule_time = datetime.utcnow() - timedelta(minutes=5) # Time in the past
        # Ensure consistent timezone awareness or lack thereof. DB stores naive, Python may use aware.
        # If app.datetime.utcnow() is mocked, ensure it returns naive if DB is naive.
        # For this test, we'll assume utcnow() returns naive or that comparison handles it.
        
        resource_draft_to_pub = Resource(
            name="DraftToPublishedScheduled", 
            status="draft",
            scheduled_status="published",
            scheduled_status_at=past_schedule_time
        )
        db.session.add(resource_draft_to_pub)
        db.session.commit()
        resource_id_1 = resource_draft_to_pub.id
        self.assertIsNone(resource_draft_to_pub.published_at)

        # Set the mocked 'now' to be after the scheduled time
        mock_datetime.utcnow.return_value = datetime.utcnow() # This 'now' is after past_schedule_time

        apply_scheduled_resource_status_changes() # Call the job function
        db.session.expire_all()  # Refresh session state after job commits


        db.session.expire_all()  # Refresh session state after job commits

        updated_res1 = Resource.query.get(resource_id_1)
        self.assertEqual(updated_res1.status, "published")
        self.assertIsNotNone(updated_res1.published_at)
        # Check if published_at is set to the scheduled time or mocked 'now'
        # The current implementation in app.py uses `resource.scheduled_status_at`
        self.assertEqual(updated_res1.published_at, past_schedule_time)
        self.assertIsNone(updated_res1.scheduled_status)
        self.assertIsNone(updated_res1.scheduled_status_at)
        
        audit_log1 = AuditLog.query.filter_by(action="SYSTEM_APPLY_SCHEDULED_STATUS", username="System").order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log1)
        self.assertIn(f"Resource {resource_id_1}", audit_log1.details)
        self.assertIn("to 'published'", audit_log1.details)


        # Scenario 2: Published to Archived (published_at should not change)
        initial_published_at = datetime.utcnow() - timedelta(days=2) # Already published
        past_schedule_time_2 = datetime.utcnow() - timedelta(minutes=10)
        resource_pub_to_arc = Resource(
            name="PublishedToArchivedScheduled",
            status="published",
            published_at=initial_published_at,
            scheduled_status="archived",
            scheduled_status_at=past_schedule_time_2
        )
        db.session.add(resource_pub_to_arc)
        db.session.commit()
        resource_id_2 = resource_pub_to_arc.id

        mock_datetime.utcnow.return_value = datetime.utcnow() # Mock 'now' again

        apply_scheduled_resource_status_changes()
        db.session.expire_all()  # Refresh after second job

        db.session.expire_all()  # Refresh after second job

        updated_res2 = Resource.query.get(resource_id_2)
        self.assertEqual(updated_res2.status, "archived")
        self.assertEqual(updated_res2.published_at, initial_published_at) # Should remain unchanged
        self.assertIsNone(updated_res2.scheduled_status)
        self.assertIsNone(updated_res2.scheduled_status_at)

        audit_log2 = AuditLog.query.filter_by(action="SYSTEM_APPLY_SCHEDULED_STATUS", username="System").order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log2) # This will be a new log after the first one
        self.assertIn(f"Resource {resource_id_2}", audit_log2.details)
        self.assertIn("to 'archived'", audit_log2.details)

    def test_analytics_dashboard_permissions(self):
        """Ensure analytics dashboard permissions are enforced."""
        # Unauthenticated request should redirect to login
        resp = self.client.get('/admin/analytics/', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.location)

        # Login as normal user (testuser is not admin by default)
        self.login('testuser', 'password')
        resp_no_perm = self.client.get('/admin/analytics/', follow_redirects=False)
        self.assertEqual(resp_no_perm.status_code, 403) # Regular user should get 403
        self.logout()

        # Create admin user with permissions
        admin_user = self._create_admin_user(username="analyticsadmin", email_ext="analytics")
        # Login as admin and access dashboard
        self.login(admin_user.username, 'adminpass')
        resp_admin = self.client.get('/admin/analytics/', follow_redirects=False)
        self.assertEqual(resp_admin.status_code, 200)
        self.assertIn(b'Analytics Dashboard', resp_admin.data) # Updated title
        # Further checks for new elements can be added in a dedicated page rendering test

    # test_view_db_raw_top100_all_tables has been removed as the endpoint's primary purpose
    # is now covered by the new /api/admin/db/table_data endpoint and its tests.
    # The old endpoint /api/admin/view_db_raw_top100 still exists but its detailed testing might be redundant
    # or could be simplified to just check if it returns data for known models if kept.
    # For now, removing it as per instruction.

    def test_get_db_table_names(self):
        """Test GET /api/admin/db/table_names returns a list of all table names."""
        admin_role = Role.query.filter_by(name="Administrator").first()
        if not admin_role:
            admin_role = Role(name="Administrator", permissions="all_permissions") # Assumes 'manage_system'
            db.session.add(admin_role)
            db.session.commit()

        admin_user = User(username="dbadmin_tables", email="dbtables@example.com", is_admin=True)
        admin_user.set_password("adminpass")
        admin_user.roles.append(admin_role)
        db.session.add(admin_user)
        db.session.commit()
        self.login(admin_user.username, "adminpass")

        response = self.client.get('/api/admin/db/table_names')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertIn('tables', data)
        self.assertIsInstance(data['tables'], list)

        # Verify structure of each item and extract names
        response_table_names = []
        if data['tables']:
            self.assertIsInstance(data['tables'][0], dict)
            for item in data['tables']:
                self.assertIn('name', item)
                self.assertIsInstance(item['name'], str)
                self.assertIn('count', item)
                self.assertIsInstance(item['count'], int)
                self.assertTrue(item['count'] >= -1) # -1 for error, 0 or more for actual count
                response_table_names.append(item['name'])

        actual_table_names = list(db.metadata.tables.keys())
        self.assertCountEqual(response_table_names, actual_table_names)
        self.logout()

    def test_get_db_table_info_valid_table(self):
        """Test GET /api/admin/db/table_info/<table_name> for a valid table."""
        admin_role = Role.query.filter_by(name="Administrator").first()
        if not admin_role:
            admin_role = Role(name="Administrator", permissions="all_permissions")
            db.session.add(admin_role)
            db.session.commit()
        admin_user = User(username="dbadmin_info", email="dbinfo@example.com", is_admin=True)
        admin_user.set_password("adminpass")
        admin_user.roles.append(admin_role)
        db.session.add(admin_user)
        db.session.commit()
        self.login(admin_user.username, "adminpass")

        # Assuming 'user' table exists
        table_to_test = 'user'
        if table_to_test not in db.metadata.tables.keys():
            self.skipTest(f"Table '{table_to_test}' does not exist in metadata, skipping info test.")

        response = self.client.get(f'/api/admin/db/table_info/{table_to_test}')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['table_name'], table_to_test)
        self.assertIn('columns', data)
        self.assertIsInstance(data['columns'], list)
        if len(data['columns']) > 0:
            self.assertIn('name', data['columns'][0])
            self.assertIn('type', data['columns'][0])
            self.assertIn('nullable', data['columns'][0])
            self.assertIn('primary_key', data['columns'][0])
        self.logout()

    def test_get_db_table_info_invalid_table(self):
        """Test GET /api/admin/db/table_info/<table_name> for a non-existent table."""
        admin_role = Role.query.filter_by(name="Administrator").first()
        if not admin_role:
            admin_role = Role(name="Administrator", permissions="all_permissions")
            db.session.add(admin_role)
            db.session.commit()
        admin_user = User(username="dbadmin_info_invalid", email="dbinfoinvalid@example.com", is_admin=True)
        admin_user.set_password("adminpass")
        admin_user.roles.append(admin_role)
        db.session.add(admin_user)
        db.session.commit()
        self.login(admin_user.username, "adminpass")

        response = self.client.get('/api/admin/db/table_info/non_existent_table_blah_blah')
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertFalse(data['success'])
        self.assertEqual(data['message'], 'Table not found.')
        self.logout()

    @unittest.mock.patch('routes.admin_ui.db.session')
    def test_admin_analytics_data_endpoint_new_structure(self, mock_db_session):
        """Validate the new JSON structure and aggregations from /admin/analytics/data."""
        admin_user = self._create_admin_user(username="analyticsadmin_new", email_ext="analytics_new")
        self.login(admin_user.username, 'adminpass')

        # --- Mock Data Setup ---
        # Users
        user1 = User(id=101, username='user_alpha')
        user2 = User(id=102, username='user_beta')

        # FloorMaps
        fm1 = FloorMap(id=201, name="Main Building", image_filename="main.png", location="Campus A", floor="1")
        fm2 = FloorMap(id=202, name="Annex B", image_filename="annex.png", location="Campus A", floor="2")
        
        # Resources
        # Resource 1: On FloorMap 1, specific equipment, tags, status
        res1 = Resource(id=301, name='Room 101', capacity=10, equipment='Projector,Whiteboard', tags='meeting,large', status='published', floor_map_id=fm1.id)
        # Resource 2: On FloorMap 2, different attributes
        res2 = Resource(id=302, name='Room 202', capacity=4, equipment='TV', tags='small,focus', status='maintenance', floor_map_id=fm2.id)
        # Resource 3: Not on any map
        res3 = Resource(id=303, name='Standalone Booth', capacity=1, equipment='Phone', tags='focus', status='published', floor_map_id=None)

        # Bookings
        # Booking 1: User1, Res1. Start: today 10:00 for 1 hr. (For hour, DOW, month aggregation)
        # Let's fix 'today' for predictable DOW/Month. Say, 2023-10-26 (Thursday)
        fixed_today = datetime(2023, 10, 26) # A Thursday

        booking1_start = fixed_today.replace(hour=10, minute=0, second=0, microsecond=0)
        booking1_end = booking1_start + timedelta(hours=1)
        b1 = Booking(id=1, user_name=user1.username, resource_id=res1.id, start_time=booking1_start, end_time=booking1_end, title='Morning Meeting')

        # Booking 2: User2, Res1. Start: today 14:00 for 2 hrs. (Same resource, different user/time)
        booking2_start = fixed_today.replace(hour=14, minute=0, second=0, microsecond=0)
        booking2_end = booking2_start + timedelta(hours=2)
        b2 = Booking(id=2, user_name=user2.username, resource_id=res1.id, start_time=booking2_start, end_time=booking2_end, title='Afternoon Session')

        # Booking 3: User1, Res2. Start: tomorrow 09:00 for 1.5 hrs. (Different resource, map, day)
        booking3_start = (fixed_today + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        booking3_end = booking3_start + timedelta(hours=1, minutes=30)
        b3 = Booking(id=3, user_name=user1.username, resource_id=res2.id, start_time=booking3_start, end_time=booking3_end, title='Focus Work')

        # Booking 4: User1, Res3 (no map). Start: 2 days ago, 11:00 for 1 hr.
        booking4_start = (fixed_today - timedelta(days=2)).replace(hour=11, minute=0, second=0, microsecond=0)
        booking4_end = booking4_start + timedelta(hours=1)
        b4 = Booking(id=4, user_name=user1.username, resource_id=res3.id, start_time=booking4_start, end_time=booking4_end, title='Quick Call')


        # --- Mocking DB Query Results ---
        # 1. For `daily_counts_query`
        # Simulates: Resource.name, func.date(Booking.start_time), func.count(Booking.id)
        # For the last 30 days from 'fixed_today' (our reference 'now' for the endpoint)
        # Let's assume the endpoint calculates 'thirty_days_ago' based on a mocked datetime.utcnow()

        # Mock for `datetime.utcnow()` used in the route to determine `thirty_days_ago`
        with unittest.mock.patch('routes.admin_ui.datetime') as mock_route_datetime:
            mock_route_datetime.utcnow.return_value = fixed_today # Endpoint will calculate based on this 'now'
            mock_route_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw) # Allow other datetime uses

            # Expected results for daily_counts_query (simplified for this example)
            # Booking 1: Res1, fixed_today
            # Booking 2: Res1, fixed_today
            # Booking 3: Res2, fixed_today + 1 day
            # Booking 4: Res3, fixed_today - 2 days
            # So, Res1 has 2 bookings on fixed_today. Res2 has 1 on fixed_today+1. Res3 has 1 on fixed_today-2.

            mock_daily_counts_results = [
                unittest.mock.Mock(resource_name=res1.name, booking_date=fixed_today.date(), booking_count=2),
                unittest.mock.Mock(resource_name=res2.name, booking_date=(fixed_today + timedelta(days=1)).date(), booking_count=1),
                # Booking 4 is > 30 days ago if fixed_today is recent, let's assume it's within 30 days for simplicity
                unittest.mock.Mock(resource_name=res3.name, booking_date=(fixed_today - timedelta(days=2)).date(), booking_count=1),
            ]

            # 2. For `base_query` (all_bookings_for_aggregation)
            # Simulates joined data: Booking.*, Resource.*, FloorMap.*, User.*, time extracts
            mock_base_query_results = []

            # For b1 (User1, Res1 on FM1, 2023-10-26 10:00, Thursday, October)
            mock_base_query_results.append(unittest.mock.Mock(
                id=b1.id, start_time=b1.start_time, end_time=b1.end_time,
                resource_name=res1.name, resource_capacity=res1.capacity, resource_equipment=res1.equipment, resource_tags=res1.tags, resource_status=res1.status,
                floor_location=fm1.location, floor_number=fm1.floor,
                user_username=user1.username,
                booking_hour=10, booking_day_of_week=3, booking_month=10 # Thursday is 3 for dow if Sunday is 0
            ))
            # For b2 (User2, Res1 on FM1, 2023-10-26 14:00, Thursday, October)
            mock_base_query_results.append(unittest.mock.Mock(
                id=b2.id, start_time=b2.start_time, end_time=b2.end_time,
                resource_name=res1.name, resource_capacity=res1.capacity, resource_equipment=res1.equipment, resource_tags=res1.tags, resource_status=res1.status,
                floor_location=fm1.location, floor_number=fm1.floor,
                user_username=user2.username,
                booking_hour=14, booking_day_of_week=3, booking_month=10
            ))
            # For b3 (User1, Res2 on FM2, 2023-10-27 09:00, Friday, October)
            mock_base_query_results.append(unittest.mock.Mock(
                id=b3.id, start_time=b3.start_time, end_time=b3.end_time,
                resource_name=res2.name, resource_capacity=res2.capacity, resource_equipment=res2.equipment, resource_tags=res2.tags, resource_status=res2.status,
                floor_location=fm2.location, floor_number=fm2.floor,
                user_username=user1.username,
                booking_hour=9, booking_day_of_week=4, booking_month=10 # Friday is 4
            ))
            # For b4 (User1, Res3 no map, 2023-10-24 11:00, Tuesday, October)
            mock_base_query_results.append(unittest.mock.Mock(
                id=b4.id, start_time=b4.start_time, end_time=b4.end_time,
                resource_name=res3.name, resource_capacity=res3.capacity, resource_equipment=res3.equipment, resource_tags=res3.tags, resource_status=res3.status,
                floor_location=None, floor_number=None, # No map
                user_username=user1.username,
                booking_hour=11, booking_day_of_week=1, booking_month=10 # Tuesday is 1
            ))

            # Configure the mock session query chain
            # This needs to differentiate between the two queries made in the route.
            # We can use side_effect if the query objects are distinct enough, or inspect args.
            # For simplicity, let's assume the first query is daily_counts, second is base_query.
            mock_query_obj = unittest.mock.Mock()
            mock_query_obj.join.return_value = mock_query_obj
            mock_query_obj.outerjoin.return_value = mock_query_obj
            mock_query_obj.filter.return_value = mock_query_obj
            mock_query_obj.group_by.return_value = mock_query_obj
            mock_query_obj.order_by.return_value = mock_query_obj

            # Use side_effect to return different results for the two `.all()` calls
            mock_query_obj.all.side_effect = [mock_daily_counts_results, mock_base_query_results]
            mock_db_session.query.return_value = mock_query_obj

            # --- Make Request ---
            response = self.client.get('/admin/analytics/data') # New URL

            # --- Assertions ---
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content_type, 'application/json')
            data = response.get_json()

            self.assertIn('daily_counts_last_30_days', data)
            self.assertIn('aggregations', data)

            # Validate daily_counts_last_30_days (basic check)
            daily_counts = data['daily_counts_last_30_days']
            self.assertIn(res1.name, daily_counts)
            self.assertEqual(len(daily_counts[res1.name]), 1) # One entry for fixed_today.date()
            self.assertEqual(daily_counts[res1.name][0]['count'], 2)
            self.assertEqual(daily_counts[res1.name][0]['date'], fixed_today.strftime('%Y-%m-%d'))

            # Validate aggregations
            aggs = data['aggregations']

            # by_resource_attributes
            self.assertIn('by_resource_attributes', aggs)
            self.assertIn(res1.name, aggs['by_resource_attributes'])
            self.assertEqual(aggs['by_resource_attributes'][res1.name]['count'], 2) # b1, b2
            self.assertAlmostEqual(aggs['by_resource_attributes'][res1.name]['total_duration_hours'], 1.0 + 2.0)
            self.assertIn(res3.name, aggs['by_resource_attributes']) # Res3 from b4
            self.assertEqual(aggs['by_resource_attributes'][res3.name]['count'], 1)
            self.assertAlmostEqual(aggs['by_resource_attributes'][res3.name]['total_duration_hours'], 1.0)


            # by_floor_attributes
            self.assertIn('by_floor_attributes', aggs)
            fm1_key = f"Floor: {fm1.floor}, Location: {fm1.location}"
            fm2_key = f"Floor: {fm2.floor}, Location: {fm2.location}"
            self.assertIn(fm1_key, aggs['by_floor_attributes'])
            self.assertEqual(aggs['by_floor_attributes'][fm1_key]['count'], 2) # b1, b2 on FM1
            self.assertAlmostEqual(aggs['by_floor_attributes'][fm1_key]['total_duration_hours'], 1.0 + 2.0)
            self.assertIn(fm2_key, aggs['by_floor_attributes'])
            self.assertEqual(aggs['by_floor_attributes'][fm2_key]['count'], 1) # b3 on FM2
            self.assertAlmostEqual(aggs['by_floor_attributes'][fm2_key]['total_duration_hours'], 1.5)

            # by_user
            self.assertIn('by_user', aggs)
            self.assertIn(user1.username, aggs['by_user'])
            self.assertEqual(aggs['by_user'][user1.username]['count'], 3) # b1, b3, b4
            self.assertAlmostEqual(aggs['by_user'][user1.username]['total_duration_hours'], 1.0 + 1.5 + 1.0)
            self.assertIn(user2.username, aggs['by_user'])
            self.assertEqual(aggs['by_user'][user2.username]['count'], 1) # b2
            self.assertAlmostEqual(aggs['by_user'][user2.username]['total_duration_hours'], 2.0)

            # by_time_attributes
            time_aggs = aggs['by_time_attributes']
            self.assertIn('hour_of_day', time_aggs)
            self.assertEqual(time_aggs['hour_of_day']['10']['count'], 1) # b1
            self.assertAlmostEqual(time_aggs['hour_of_day']['10']['total_duration_hours'], 1.0)
            self.assertEqual(time_aggs['hour_of_day']['14']['count'], 1) # b2
            self.assertAlmostEqual(time_aggs['hour_of_day']['14']['total_duration_hours'], 2.0)
            self.assertEqual(time_aggs['hour_of_day']['9']['count'], 1) # b3
            self.assertAlmostEqual(time_aggs['hour_of_day']['9']['total_duration_hours'], 1.5)


            self.assertIn('day_of_week', time_aggs)
            self.assertEqual(time_aggs['day_of_week']['Thursday']['count'], 2) # b1, b2
            self.assertAlmostEqual(time_aggs['day_of_week']['Thursday']['total_duration_hours'], 1.0 + 2.0)
            self.assertEqual(time_aggs['day_of_week']['Friday']['count'], 1) # b3
            self.assertAlmostEqual(time_aggs['day_of_week']['Friday']['total_duration_hours'], 1.5)
            self.assertEqual(time_aggs['day_of_week']['Tuesday']['count'], 1) # b4

            self.assertIn('month', time_aggs)
            self.assertEqual(time_aggs['month']['October']['count'], 4) # All bookings are in October
            self.assertAlmostEqual(time_aggs['month']['October']['total_duration_hours'], 1.0 + 2.0 + 1.5 + 1.0)

        self.logout()

    @unittest.mock.patch('routes.admin_ui.analytics_bookings_data') # Mock the data-providing function
    def test_admin_analytics_page_renders_new_elements(self, mock_analytics_data_func):
        """Test that the /admin/analytics/ page renders with new filter and chart elements."""
        admin_user = self._create_admin_user(username="analytics_page_admin", email_ext="analyticspage")
        self.login(admin_user.username, 'adminpass')

        # Define a minimal valid structure for the mocked data endpoint
        mock_analytics_data_func.return_value = jsonify({
            "daily_counts_last_30_days": {
                "SampleResource": [{"date": "2023-01-01", "count": 5}]
            },
            "aggregations": {
                "by_resource_attributes": {"SampleResource": {"count": 10, "total_duration_hours": 20}},
                "by_floor_attributes": {"Floor: 1, Location: Test": {"count": 5, "total_duration_hours": 10}},
                "by_user": {"testuser": {"count": 15, "total_duration_hours": 30}},
                "by_time_attributes": {
                    "hour_of_day": {"10": {"count": 3, "total_duration_hours": 3}},
                    "day_of_week": {"Monday": {"count": 4, "total_duration_hours": 8}},
                    "month": {"January": {"count": 20, "total_duration_hours": 40}}
                }
            }
        })

        response = self.client.get('/admin/analytics/')
        self.assertEqual(response.status_code, 200)
        html_content = response.data.decode('utf-8')

        self.assertIn("<h1>{{ _('Analytics Dashboard') }}</h1>", html_content) # Using raw string for template tag

        # Check for filter dropdowns
        self.assertIn('id="filterResourceTag"', html_content)
        self.assertIn('id="filterResourceStatus"', html_content)
        self.assertIn('id="filterUser"', html_content)
        self.assertIn('id="filterLocation"', html_content)
        self.assertIn('id="filterFloor"', html_content)
        self.assertIn('id="filterMonth"', html_content)
        self.assertIn('id="filterDayOfWeek"', html_content)
        self.assertIn('id="filterHourOfDay"', html_content)
        self.assertIn('id="applyFiltersBtn"', html_content)
        self.assertIn('id="resetFiltersBtn"', html_content)

        # Check for chart canvases
        self.assertIn('id="dailyUsageChart"', html_content)
        self.assertIn('id="bookingsPerUserChart"', html_content)
        self.assertIn('id="bookingsPerResourceChart"', html_content)
        self.assertIn('id="bookingsByHourChart"', html_content)
        self.assertIn('id="bookingsByDayOfWeekChart"', html_content)
        self.assertIn('id="bookingsByMonthChart"', html_content)
        self.assertIn('id="resourceDistributionChart"', html_content)

        self.logout()


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

    def test_recurrence_booking_creation(self):
        self.login('testuser', 'password')
        payload = {
            'resource_id': self.resource1.id,
            'date_str': date.today().strftime('%Y-%m-%d'),
            'start_time_str': '09:00',
            'end_time_str': '10:00',
            'title': 'Recurring',
            'user_name': 'testuser',
            'recurrence_rule': 'FREQ=DAILY;COUNT=3'
        }
        resp = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Booking.query.filter_by(user_name='testuser').count(), 3)

    def test_malformed_rrule_returns_400(self):
        self.login('testuser', 'password')
        payload = {
            'resource_id': self.resource1.id,
            'date_str': date.today().strftime('%Y-%m-%d'),
            'start_time_str': '09:00',
            'end_time_str': '10:00',
            'title': 'Bad Recurrence',
            'user_name': 'testuser',
            'recurrence_rule': 'FREQ=DAILY;COUNT=abc'
        }
        resp = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Booking.query.count(), 0)

    def test_get_my_booked_resources_api(self):
        """Test the /api/bookings/my_booked_resources endpoint."""
        # Create a third resource for more comprehensive testing
        resource3 = Resource(name='Room C - Bookable by testuser', status='published')
        db.session.add(resource3)
        db.session.commit()
        
        # Log in the default testuser
        login_response = self.login('testuser', 'password')
        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(login_response.get_json().get('success'))

        # Create bookings for 'testuser'
        # Booking 1: testuser books self.resource1
        self._create_booking(user_name='testuser', resource_id=self.resource1.id, start_offset_hours=1, title="Booking for Res1")
        # Booking 2: testuser books resource3
        self._create_booking(user_name='testuser', resource_id=resource3.id, start_offset_hours=2, title="Booking for Res3")
        # self.resource2 is NOT booked by testuser

        # Make GET request to /api/bookings/my_booked_resources
        response = self.client.get('/api/bookings/my_booked_resources')
        self.assertEqual(response.status_code, 200)
        
        data = response.get_json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2, "Should return only the 2 resources booked by the user.")

        returned_resource_ids = {r['id'] for r in data}
        expected_resource_ids = {self.resource1.id, resource3.id}
        
        self.assertEqual(returned_resource_ids, expected_resource_ids, "Returned resource IDs do not match expected.")
        self.assertNotIn(self.resource2.id, returned_resource_ids, "Resource2 should not be in the list as it was not booked by testuser.")

        # Test that different statuses of booked resources are returned (e.g., if one was archived after booking)
        resource3.status = 'archived'
        db.session.commit()
        
        response_after_status_change = self.client.get('/api/bookings/my_booked_resources')
        self.assertEqual(response_after_status_change.status_code, 200)
        data_after_status_change = response_after_status_change.get_json()
        self.assertEqual(len(data_after_status_change), 2) # Still 2, as it returns booked resources regardless of current status
        archived_resource_returned = any(r['id'] == resource3.id and r['status'] == 'archived' for r in data_after_status_change)
        self.assertTrue(archived_resource_returned, "Archived booked resource should be returned with its current status.")

        # Test unauthenticated access
        self.logout()
        unauthenticated_response = self.client.get('/api/bookings/my_booked_resources')
        self.assertEqual(unauthenticated_response.status_code, 401, "Unauthenticated access should be denied (401).")


    def test_sqlite_wal_mode_enabled(self):
        """Ensure WAL mode is set for SQLite databases."""
        admin = User(username='waladmin', email='wal@example.com', is_admin=True)
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()
        self.login('waladmin', 'password')

        start = datetime.utcnow()
        end = start + timedelta(hours=1)
        booking = Booking(resource_id=self.resource1.id, user_name='waladmin', start_time=start, end_time=end, title='Pending', status='pending')
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id

        self.client.get('/api/auth/status')
        result = db.session.execute(text("PRAGMA journal_mode")).scalar()
        self.assertEqual(result.lower(), 'wal')
        
        # Test pending bookings endpoint for admin
        resp_pending = self.client.get('/admin/bookings/pending')
        self.assertEqual(resp_pending.status_code, 200)
        json_data_pending = resp_pending.get_json()
        self.assertIsInstance(json_data_pending, list)
        
        # Check if the specific booking is in the list
        found_booking = any(b['id'] == booking_id for b in json_data_pending)
        self.assertTrue(found_booking, "Pending booking not found in admin list.")


        # Test approve booking endpoint
        resp_approve = self.client.post(f'/admin/bookings/{booking_id}/approve')
        self.assertEqual(resp_approve.status_code, 200)
        self.assertTrue(resp_approve.get_json().get('success'))
        
        booking_after_approve = Booking.query.get(booking_id)
        self.assertEqual(booking_after_approve.status, 'approved')
        self.assertEqual(len(email_log), 1) # Check email was sent
        self.assertEqual(len(slack_log), 1) # Check slack notification

    def test_init_db_does_not_wipe_without_force(self):
        """init_db should preserve data unless force=True."""
        from init_setup import init_db

        user = User(username='keepme', email='keep@example.com', is_admin=False)
        user.set_password('pass')
        db.session.add(user)
        db.session.commit()

        init_db()

        self.assertIsNotNone(User.query.filter_by(username='keepme').first())


class TestMapBookingAPI(AppTests):
    def setUp(self):
        super().setUp() # Call parent setUp
        # Create an admin user for map API tests if needed for specific endpoints
        self.admin_user = User(username='mapadmin', email='mapadmin@example.com', is_admin=True)
        self.admin_user.set_password('adminpass')
        db.session.add(self.admin_user)
        db.session.commit()

    def test_get_admin_maps_list(self):
        """Test GET /api/admin/maps returns a list of maps."""
        self.login(self.admin_user.username, 'adminpass')
        # self.floor_map is created in AppTests.setUp
        response = self.client.get('/api/admin/maps')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, list)
        self.assertTrue(len(data) >= 1) # At least the one from setup
        map_data = next((m for m in data if m['id'] == self.floor_map.id), None)
        self.assertIsNotNone(map_data)
        self.assertEqual(map_data['name'], self.floor_map.name)
        self.assertIn('image_filename', map_data)

    def test_get_admin_maps_no_maps(self):
        """Test GET /api/admin/maps with no maps present."""
        self.login(self.admin_user.username, 'adminpass')
        # Delete the map created in setUp
        map_id = self.floor_map.id
        db.session.delete(self.floor_map)
        # Also delete any resources associated with it to avoid FK constraint issues if not cascaded
        Resource.query.filter_by(floor_map_id=map_id).delete()
        db.session.commit()
        
        response = self.client.get('/api/admin/maps')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 0)

    def test_get_map_details_valid_map(self):
        """Test GET /api/map_details/<map_id> with a valid map ID."""
        # Login is not strictly required for this public endpoint, but good practice for consistency
        self.login('testuser', 'password')
        
        response = self.client.get(f'/api/map_details/{self.floor_map.id}')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        
        self.assertIn('map_details', data)
        self.assertEqual(data['map_details']['id'], self.floor_map.id)
        self.assertEqual(data['map_details']['name'], self.floor_map.name)
        self.assertIn('image_url', data['map_details'])

        self.assertIn('mapped_resources', data)
        self.assertIsInstance(data['mapped_resources'], list)
        
        # Check structure of a mapped resource (e.g., self.resource1 from setup)
        resource1_data = next((r for r in data['mapped_resources'] if r['id'] == self.resource1.id), None)
        self.assertIsNotNone(resource1_data)
        self.assertEqual(resource1_data['name'], self.resource1.name)
        self.assertIn('map_coordinates', resource1_data)
        self.assertIsInstance(resource1_data['map_coordinates'], dict)
        self.assertEqual(resource1_data['map_coordinates']['x'], 10)  # From setup
        self.assertIn('bookings_on_date', resource1_data) # Should be present, even if empty
        self.assertIsInstance(resource1_data['bookings_on_date'], list)

    def test_get_map_details_bookings_on_date_scenarios(self):
        """Test 'bookings_on_date' in /api/map_details for various booking scenarios."""
        self.login('testuser', 'password')
        test_date_str = date.today().strftime('%Y-%m-%d')

        # Scenario 1: Resource available (no bookings)
        response = self.client.get(f'/api/map_details/{self.floor_map.id}?date={test_date_str}')
        data = response.get_json()
        resource1_data = next(r for r in data['mapped_resources'] if r['id'] == self.resource1.id)
        self.assertEqual(len(resource1_data['bookings_on_date']), 0)

        # Scenario 2: Resource partially booked
        booking1_start = datetime.combine(date.today(), time(10, 0))
        booking1_end = datetime.combine(date.today(), time(11, 0))
        Booking.query.delete() # Clear any previous bookings for clean test
        db.session.commit()
        b1 = Booking(resource_id=self.resource1.id, user_name='testuser', start_time=booking1_start, end_time=booking1_end, title='Partial')
        db.session.add(b1)
        db.session.commit()

        response = self.client.get(f'/api/map_details/{self.floor_map.id}?date={test_date_str}')
        data = response.get_json()
        resource1_data = next(r for r in data['mapped_resources'] if r['id'] == self.resource1.id)
        self.assertEqual(len(resource1_data['bookings_on_date']), 1)
        self.assertEqual(resource1_data['bookings_on_date'][0]['title'], 'Partial')

        # Scenario 3: Resource fully booked (e.g., 8am-5pm for this test's purpose)
        # For simplicity, one long booking. More granular checks would be in JS or specific availability logic.
        booking2_start = datetime.combine(date.today(), time(8, 0))
        booking2_end = datetime.combine(date.today(), time(17, 0))
        # Create a new resource for this to avoid conflicts with res1's partial booking
        full_res = Resource(name='Full Room', floor_map_id=self.floor_map.id, map_coordinates=json.dumps({'type': 'rect', 'x':1, 'y':1, 'width':1, 'height':1}), status='published')
        db.session.add(full_res)
        db.session.commit()
        b2 = Booking(resource_id=full_res.id, user_name='testuser', start_time=booking2_start, end_time=booking2_end, title='Full Day')
        db.session.add(b2)
        db.session.commit()

        response = self.client.get(f'/api/map_details/{self.floor_map.id}?date={test_date_str}')
        data = response.get_json()
        full_res_data = next(r for r in data['mapped_resources'] if r['id'] == full_res.id)
        self.assertEqual(len(full_res_data['bookings_on_date']), 1)
        self.assertEqual(full_res_data['bookings_on_date'][0]['title'], 'Full Day')


    def test_get_map_details_invalid_map_id(self):
        """Test GET /api/map_details/<map_id> with an invalid map ID."""
        self.login('testuser', 'password')
        invalid_map_id = 99999
        response = self.client.get(f'/api/map_details/{invalid_map_id}')
        self.assertEqual(response.status_code, 404)
        self.assertIn('error', response.get_json())

    def test_get_map_details_no_resources_on_map(self):
        """Test GET /api/map_details/<map_id> for a map with no resources."""
        self.login('testuser', 'password')
        empty_map = FloorMap(name="Empty Map", image_filename="empty.png")
        db.session.add(empty_map)
        db.session.commit()
        
        response = self.client.get(f'/api/map_details/{empty_map.id}')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['map_details']['id'], empty_map.id)
        self.assertEqual(len(data['mapped_resources']), 0)

    def test_get_resource_availability(self):
        """Test GET /api/resources/<resource_id>/availability."""
        self.login('testuser', 'password')
        test_date_str = date.today().strftime('%Y-%m-%d')

        # Resource with no bookings
        response_no_bookings = self.client.get(f'/api/resources/{self.resource2.id}/availability?date={test_date_str}')
        self.assertEqual(response_no_bookings.status_code, 200)
        self.assertEqual(len(response_no_bookings.get_json()), 0)

        # Resource with bookings
        booking_start = datetime.combine(date.today(), time(14, 0))
        booking_end = datetime.combine(date.today(), time(15, 0))
        b = Booking(resource_id=self.resource1.id, user_name='testuser', start_time=booking_start, end_time=booking_end, title='Avail Test')
        db.session.add(b)
        db.session.commit()
        
        response_with_bookings = self.client.get(f'/api/resources/{self.resource1.id}/availability?date={test_date_str}')
        self.assertEqual(response_with_bookings.status_code, 200)
        data_bookings = response_with_bookings.get_json()
        self.assertEqual(len(data_bookings), 1)
        self.assertEqual(data_bookings[0]['title'], 'Avail Test')
        self.assertEqual(data_bookings[0]['start_time'], '14:00:00')

    def test_get_resource_availability_invalid_id(self):
        """Test GET /api/resources/<resource_id>/availability with an invalid resource ID."""
        self.login('testuser', 'password')
        invalid_resource_id = 99999
        test_date_str = date.today().strftime('%Y-%m-%d')
        response = self.client.get(f'/api/resources/{invalid_resource_id}/availability?date={test_date_str}')
        self.assertEqual(response.status_code, 404)

    def test_post_booking_from_map_modal_success(self):
        """Test POST /api/bookings for successful booking from map modal scenario."""
        self.login('testuser', 'password')
        payload = {
            'resource_id': self.resource1.id,
            'date_str': date.today().strftime('%Y-%m-%d'),
            'start_time_str': '10:00',
            'end_time_str': '11:00',
            'title': 'Map Modal Booking',
            'user_name': 'testuser' # Assuming user_name is correctly passed or derived
        }
        response = self.client.post('/api/bookings', json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertIn('bookings', data)
        self.assertEqual(len(data['bookings']), 1)
        booking_data = data['bookings'][0]
        self.assertEqual(booking_data['title'], 'Map Modal Booking')
        self.assertEqual(booking_data['resource_id'], self.resource1.id)
        self.assertTrue(Booking.query.filter_by(id=booking_data['id']).count() == 1)

    def test_post_booking_conflict_from_map_modal(self):
        """Test POST /api/bookings for conflict from map modal."""
        self.login('testuser', 'password')
        # Create an existing booking
        existing_start = datetime.combine(date.today(), time(10, 0))
        existing_end = datetime.combine(date.today(), time(11, 0))
        existing = Booking(resource_id=self.resource1.id, user_name='anotheruser', start_time=existing_start, end_time=existing_end, title='Existing')
        db.session.add(existing)
        db.session.commit()

        payload = {
            'resource_id': self.resource1.id,
            'date_str': date.today().strftime('%Y-%m-%d'),
            'start_time_str': '10:00', # Same time
            'end_time_str': '11:00',
            'title': 'Conflict Map Modal Booking',
            'user_name': 'testuser'
        }
        response = self.client.post('/api/bookings', json=payload)
        self.assertEqual(response.status_code, 409)  # Expect conflict
        self.assertIn('time slot is no longer available', response.get_json().get('error', '').lower())

    def test_post_booking_invalid_data_from_map_modal(self):
        """Test POST /api/bookings with invalid data from map modal."""
        self.login('testuser', 'password')
        # Missing resource_id
        payload_no_resource = {
            'date_str': date.today().strftime('%Y-%m-%d'),
            'start_time_str': '10:00',
            'end_time_str': '11:00',
            'title': 'No Resource Booking',
            'user_name': 'testuser'
        }
        response_no_res = self.client.post('/api/bookings', json=payload_no_resource)
        self.assertEqual(response_no_res.status_code, 400) # Expect Bad Request

        # Invalid time (end before start)
        payload_invalid_time = {
            'resource_id': self.resource1.id,
            'date_str': date.today().strftime('%Y-%m-%d'),
            'start_time_str': '11:00',
            'end_time_str': '10:00', # End before start
            'title': 'Invalid Time Booking',
            'user_name': 'testuser'
        }
        response_invalid_time = self.client.post('/api/bookings', json=payload_invalid_time)
        self.assertEqual(response_invalid_time.status_code, 400)

    def test_post_booking_non_existent_resource_from_map_modal(self):
        """Test POST /api/bookings for a non-existent resource."""
        self.login('testuser', 'password')
        payload = {
            'resource_id': 99999, # Non-existent
            'date_str': date.today().strftime('%Y-%m-%d'),
            'start_time_str': '10:00',
            'end_time_str': '11:00',
            'title': 'Ghost Resource Booking',
            'user_name': 'testuser'
        }
        response = self.client.post('/api/bookings', json=payload)
        self.assertEqual(response.status_code, 404) # Expect Not Found for resource
        self.assertIn('Resource not found', response.get_json().get('error', ''))

    # --- Integration Tests for Booking Workflow with Map Area Roles ---
    # These tests will be within TestMapBookingAPI or a new dedicated class.
    # For now, adding to TestMapBookingAPI.

    def _create_user_with_roles(self, username, password, role_names=None, is_admin=False):
        """Helper to create a user and assign them roles by name."""
        user = User.query.filter_by(username=username).first()
        if user: # Delete if exists to ensure clean state for roles
            db.session.delete(user)
            db.session.commit()

        user = User(username=username, email=f"{username}@example.com", is_admin=is_admin)
        user.set_password(password)
        if role_names:
            for role_name in role_names:
                role = Role.query.filter_by(name=role_name).first()
                if not role: # Create role if it doesn't exist (e.g. from TestFloorMapRoles setup)
                    role = Role(name=role_name, description=f"Role for {role_name}")
                    db.session.add(role)
                    db.session.commit()
                user.roles.append(role)
        db.session.add(user)
        db.session.commit()
        return user

    def _setup_booking_scenario(self, map_roles_names=None, resource_roles_names=None, resource_allowed_user_id=None, resource_on_map=True):
        """Helper to set up common elements for booking scenarios."""
        # Create a map (or use one from TestFloorMapRoles setup if applicable)
        test_scenario_map = FloorMap.query.filter_by(name="ScenarioMap").first()
        if not test_scenario_map:
            test_scenario_map = FloorMap(name="ScenarioMap", image_filename="scenario_map.png")
            db.session.add(test_scenario_map)
            db.session.commit()

        if map_roles_names:
            test_scenario_map.roles = [] # Clear existing
            for role_name in map_roles_names:
                role = Role.query.filter_by(name=role_name).first()
                if role: # Roles should be created by _create_user_with_roles or in TestFloorMapRoles.setUp
                    test_scenario_map.roles.append(role)
            db.session.commit()

        # Create a resource
        scenario_resource = Resource.query.filter_by(name="ScenarioResource").first()
        if scenario_resource:
            db.session.delete(scenario_resource) # Delete to reset its roles/map assignment
            db.session.commit()

        scenario_resource = Resource(name="ScenarioResource", status="published")
        if resource_on_map:
            scenario_resource.floor_map_id = test_scenario_map.id
        else:
            scenario_resource.floor_map_id = None

        if resource_roles_names:
            scenario_resource.roles = [] # Clear existing
            for role_name in resource_roles_names:
                role = Role.query.filter_by(name=role_name).first()
                if role:
                    scenario_resource.roles.append(role)

        if resource_allowed_user_id:
            scenario_resource.allowed_user_ids = str(resource_allowed_user_id)

        db.session.add(scenario_resource)
        db.session.commit()
        return test_scenario_map, scenario_resource

    def test_booking_map_roles_user_has_map_role(self):
        """Scenario 1: Resource on Map with Roles, User Has Map Role."""
        # Setup: Map M has RoleX. User U has RoleX. Resource R on Map M.
        map_role_name = "MapRoleX"
        user_u = self._create_user_with_roles("user_scenario1", "password", [map_role_name])
        _, resource_r = self._setup_booking_scenario(map_roles_names=[map_role_name])

        self.login(user_u.username, "password")
        payload = self._make_booking_payload(resource_r.id, user_name=user_u.username)
        response = self.client.post('/api/bookings', json=payload)

        self.assertEqual(response.status_code, 201, f"Booking failed: {response.get_json()}")
        self.logout()

    def test_booking_map_roles_user_lacks_map_role(self):
        """Scenario 2: Resource on Map with Roles, User Lacks Map Role."""
        map_role_name = "MapRoleX_S2" # Unique role name for this test
        user_y_role_name = "UserRoleY_S2"
        user_u = self._create_user_with_roles("user_scenario2", "password", [user_y_role_name])
        _, resource_r = self._setup_booking_scenario(map_roles_names=[map_role_name])

        self.login(user_u.username, "password")
        payload = self._make_booking_payload(resource_r.id, user_name=user_u.username)
        response = self.client.post('/api/bookings', json=payload)

        self.assertEqual(response.status_code, 403, f"Booking should be forbidden: {response.get_json()}")
        self.assertIn("Access to this resource via the map", response.get_json().get('error', ''))
        self.assertIn("is restricted by specific roles", response.get_json().get('error', ''))
        self.logout()

    def test_booking_map_roles_admin_lacks_map_role(self):
        """Scenario 3: Resource on Map with Roles, Admin User Lacks Map Role."""
        map_role_name = "MapRoleX_S3"
        admin_user = self._create_user_with_roles("admin_scenario3", "password", is_admin=True) # Admin, no specific map role
        _, resource_r = self._setup_booking_scenario(map_roles_names=[map_role_name])

        self.login(admin_user.username, "password")
        payload = self._make_booking_payload(resource_r.id, user_name=admin_user.username)
        response = self.client.post('/api/bookings', json=payload)

        self.assertEqual(response.status_code, 201, f"Admin booking failed: {response.get_json()}")
        self.logout()

    def test_booking_map_roles_user_specifically_allowed_bypasses_map_role(self):
        """Scenario 4: User in resource.allowed_user_ids bypasses map role check."""
        map_role_name = "MapRoleX_S4"
        user_lacks_map_role = "UserRoleY_S4"
        user_u = self._create_user_with_roles("user_scenario4", "password", [user_lacks_map_role])
        # User U is specifically allowed on the resource
        _, resource_r = self._setup_booking_scenario(map_roles_names=[map_role_name], resource_allowed_user_id=user_u.id)

        self.login(user_u.username, "password")
        payload = self._make_booking_payload(resource_r.id, user_name=user_u.username)
        response = self.client.post('/api/bookings', json=payload)

        self.assertEqual(response.status_code, 201, f"Booking failed for specifically allowed user: {response.get_json()}")
        self.logout()

    def test_booking_map_with_no_roles_assigned(self):
        """Scenario 5: Resource on Map with NO Roles Assigned."""
        # User has a general resource role or resource is open
        resource_role_name = "ResourceRoleGeneral_S5"
        user_u = self._create_user_with_roles("user_scenario5", "password", [resource_role_name])
        # Map has no roles. Resource R allows RoleGeneral_S5.
        _, resource_r = self._setup_booking_scenario(map_roles_names=[], resource_roles_names=[resource_role_name])

        self.login(user_u.username, "password")
        payload = self._make_booking_payload(resource_r.id, user_name=user_u.username)
        response = self.client.post('/api/bookings', json=payload)

        self.assertEqual(response.status_code, 201, f"Booking failed on map with no roles: {response.get_json()}")
        self.logout()

        # Also test for open resource on map with no roles
        user_no_specific_roles = self._create_user_with_roles("user_scenario5_open", "password")
        # Map has no roles. Resource R is open (no roles, no allowed_user_ids).
        _, resource_r_open = self._setup_booking_scenario(map_roles_names=[], resource_roles_names=None, resource_allowed_user_id=None)
        self.login(user_no_specific_roles.username, "password")
        payload_open = self._make_booking_payload(resource_r_open.id, user_name=user_no_specific_roles.username)
        response_open = self.client.post('/api/bookings', json=payload_open)
        self.assertEqual(response_open.status_code, 201, f"Booking for open resource on map with no roles failed: {response_open.get_json()}")
        self.logout()


    def test_booking_resource_not_on_any_map(self):
        """Scenario 6: Resource NOT on any Map."""
        resource_role_name = "ResourceRoleGeneral_S6"
        user_u = self._create_user_with_roles("user_scenario6", "password", [resource_role_name])
        # Resource R is not on a map. Resource R allows RoleGeneral_S6.
        _, resource_r = self._setup_booking_scenario(resource_on_map=False, resource_roles_names=[resource_role_name])

        self.login(user_u.username, "password")
        payload = self._make_booking_payload(resource_r.id, user_name=user_u.username)
        response = self.client.post('/api/bookings', json=payload)

        self.assertEqual(response.status_code, 201, f"Booking failed for resource not on map: {response.get_json()}")
        self.logout()

    def test_booking_map_roles_user_has_resource_role_not_map_role(self):
        """Scenario 7: Resource on Map, User has Resource Role but not Map Role."""
        map_role_x = "MapRoleX_S7"
        resource_role_y = "ResourceRoleY_S7"
        user_u = self._create_user_with_roles("user_scenario7", "password", [resource_role_y])
        # Map M allows RoleX. Resource R allows RoleY. User U has RoleY.
        _, resource_r = self._setup_booking_scenario(map_roles_names=[map_role_x], resource_roles_names=[resource_role_y])

        self.login(user_u.username, "password")
        payload = self._make_booking_payload(resource_r.id, user_name=user_u.username)
        response = self.client.post('/api/bookings', json=payload)

        self.assertEqual(response.status_code, 403, f"Booking should be forbidden: {response.get_json()}")
        self.assertIn("Access to this resource via the map", response.get_json().get('error', ''))
        self.logout()

    def test_booking_map_roles_user_has_map_role_not_resource_role(self):
        """Scenario 8: Resource on Map, User has Map Role but not Resource Role (and resource not open)."""
        map_role_x = "MapRoleX_S8"
        resource_role_y = "ResourceRoleY_S8" # Resource requires this role
        user_u = self._create_user_with_roles("user_scenario8", "password", [map_role_x])
        # Map M allows RoleX. Resource R requires RoleY. User U has RoleX.
        _, resource_r = self._setup_booking_scenario(map_roles_names=[map_role_x], resource_roles_names=[resource_role_y])

        self.login(user_u.username, "password")
        payload = self._make_booking_payload(resource_r.id, user_name=user_u.username)
        response = self.client.post('/api/bookings', json=payload)

        self.assertEqual(response.status_code, 403, f"Booking should be forbidden: {response.get_json()}")
        # Default message "You are not authorized to book this resource based on its permission settings." is expected
        # because the failure happens at the resource-level check, before map roles would be reconsidered to deny.
        self.assertNotIn("Access to this resource via the map", response.get_json().get('error', ''))
        self.assertIn("not authorized to book this resource based on its permission settings", response.get_json().get('error', ''))
        self.logout()


class TestBulkResourceCreation(AppTests):
    def test_bulk_resource_creation(self):
        admin = User(username='bulkadmin', email='bulkadmin@example.com', is_admin=True)
        admin.set_password('adminpass')
        db.session.add(admin)
        db.session.commit()

        self.login('bulkadmin', 'adminpass')

        payload = {
            'prefix': 'Room-',
            'start': 1,
            'count': 3,
            'padding': 2,
            'status': 'published'
        }
        resp = self.client.post('/api/admin/resources/bulk', json=payload)
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(len(data['created']), 3)
        names = [r['name'] for r in data['created']]
        self.assertEqual(names, ['Room-01', 'Room-02', 'Room-03'])
        for name in names:
            self.assertIsNotNone(Resource.query.filter_by(name=name).first())


class TestBulkResourceEditDelete(AppTests):
    def test_bulk_edit_resources(self):
        admin = User(username='bulkeditadmin', email='bulkedit@example.com', is_admin=True)
        admin.set_password('adminpass')
        db.session.add(admin)
        db.session.commit()
        self.login('bulkeditadmin', 'adminpass')

        r1 = Resource(name='BulkEdit1', status='draft')
        r2 = Resource(name='BulkEdit2', status='draft')
        db.session.add_all([r1, r2])
        db.session.commit()

        payload = {'ids': [r1.id, r2.id], 'fields': {'status': 'archived'}}
        resp = self.client.put('/api/admin/resources/bulk', json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Resource.query.get(r1.id).status, 'archived')
        self.assertEqual(Resource.query.get(r2.id).status, 'archived')

    def test_bulk_delete_resources(self):
        admin = User(username='bulkdeleteadmin', email='bulkdelete@example.com', is_admin=True)
        admin.set_password('adminpass')
        db.session.add(admin)
        db.session.commit()
        self.login('bulkdeleteadmin', 'adminpass')

        r1 = Resource(name='BulkDel1', status='draft')
        r2 = Resource(name='BulkDel2', status='draft')
        db.session.add_all([r1, r2])
        db.session.commit()

        payload = {'ids': [r1.id, r2.id]}
        resp = self.client.delete('/api/admin/resources/bulk', json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(Resource.query.get(r1.id))
        self.assertIsNone(Resource.query.get(r2.id))


class TestUserImportExport(AppTests):
    def test_export_users(self):
        admin = User(username='exportadmin', email='export@example.com', is_admin=True)
        admin.set_password('adminpass')
        db.session.add(admin)
        db.session.commit()
        self.login('exportadmin', 'adminpass')

        user = User(username='exportuser', email='exportuser@example.com', is_admin=False)
        user.set_password('pass')
        db.session.add(user)
        db.session.commit()

        resp = self.client.get('/api/admin/users/export')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        usernames = [u['username'] for u in data['users']]
        self.assertIn('exportuser', usernames)

    def test_import_users_and_bulk_delete(self):
        admin = User(username='importadmin', email='import@example.com', is_admin=True)
        admin.set_password('adminpass')
        db.session.add(admin)
        db.session.commit()
        self.login('importadmin', 'adminpass')

        payload = {
            'users': [
                {'username': 'imp1', 'email': 'imp1@example.com', 'password': 'p1'},
                {'username': 'imp2', 'email': 'imp2@example.com', 'password': 'p2'}
            ]
        }
        resp = self.client.post('/api/admin/users/import', json=payload)
        self.assertEqual(resp.status_code, 200)
        u1 = User.query.filter_by(username='imp1').first()
        u2 = User.query.filter_by(username='imp2').first()
        self.assertIsNotNone(u1)
        self.assertIsNotNone(u2)

        del_payload = {'ids': [u1.id, u2.id]}
        del_resp = self.client.delete('/api/admin/users/bulk', json=del_payload)
        self.assertEqual(del_resp.status_code, 200)
        self.assertIsNone(User.query.get(u1.id))
        self.assertIsNone(User.query.get(u2.id))


class TestResourceManagementImportExportAPI(AppTests):
    def setUp(self):
        super().setUp()
        # Create an admin user with manage_resources permission
        self.admin_user = User(username='resourcemgmtadmin', email='resourcemgmt@example.com', is_admin=True)
        self.admin_user.set_password('adminpass')

        # Create Administrator role with all_permissions if it doesn't exist
        admin_role = Role.query.filter_by(name="Administrator").first()
        if not admin_role:
            admin_role = Role(name="Administrator", permissions="all_permissions")
            db.session.add(admin_role)

        self.admin_user.roles.append(admin_role) # Assign role that has 'manage_resources' (via all_permissions)
        db.session.add(self.admin_user)

        # Create a standard user for allowed_user_ids tests
        self.standard_user = User(username='standarduser', email='standard@example.com')
        self.standard_user.set_password('userpass')
        db.session.add(self.standard_user)

        # Create some roles for testing role assignment
        self.role1 = Role(name='Test Role 1', permissions='can_book_special')
        self.role2 = Role(name='Test Role 2', permissions='can_view_reports')
        db.session.add_all([self.role1, self.role2])

        db.session.commit()

    def test_export_all_resources(self):
        """Test export all resources API endpoint."""
        self.login(self.admin_user.username, 'adminpass')

        # Create a sample resource with all fields populated
        resource_data = {
            'name': 'Export Test Resource 1',
            'capacity': 50,
            'equipment': 'Projector, Whiteboard, AV System',
            'status': 'published',
            'tags': 'meeting, large-group',
            'booking_restriction': 'admin_only',
            'allowed_user_ids': str(self.standard_user.id),
            'image_filename': 'test_image.jpg',
            'is_under_maintenance': True,
            'maintenance_until': datetime.utcnow() + timedelta(days=7),
            'max_recurrence_count': 10,
            'scheduled_status': 'archived',
            'scheduled_status_at': datetime.utcnow() + timedelta(days=14),
            'floor_map_id': self.floor_map.id,
            'map_coordinates': json.dumps({'type': 'rect', 'x': 100, 'y': 100, 'width': 50, 'height': 25})
        }
        export_resource = Resource(**resource_data)
        export_resource.roles.append(self.role1) # Add a role
        db.session.add(export_resource)
        db.session.commit()

        # Add another simpler resource from parent setUp (self.resource1)
        # self.resource1 already exists from AppTests.setUp

        response = self.client.get('/api/admin/resources/export')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, 'application/json')
        self.assertIn('attachment; filename=resources_export.json', response.headers['Content-Disposition'])

        data = json.loads(response.data.decode('utf-8'))
        self.assertIsInstance(data, list)

        # Find our test resource in the export
        exported_res_data = next((r for r in data if r['name'] == 'Export Test Resource 1'), None)
        self.assertIsNotNone(exported_res_data)

        self.assertEqual(exported_res_data['name'], resource_data['name'])
        self.assertEqual(exported_res_data['capacity'], resource_data['capacity'])
        self.assertEqual(exported_res_data['equipment'], resource_data['equipment'])
        self.assertEqual(exported_res_data['status'], resource_data['status'])
        self.assertEqual(exported_res_data['tags'], resource_data['tags'])
        self.assertEqual(exported_res_data['booking_restriction'], resource_data['booking_restriction'])
        self.assertEqual(exported_res_data['allowed_user_ids'], resource_data['allowed_user_ids'])
        self.assertIn(resource_data['image_filename'], exported_res_data['image_url']) # image_url is derived
        self.assertEqual(exported_res_data['is_under_maintenance'], resource_data['is_under_maintenance'])
        self.assertEqual(datetime.fromisoformat(exported_res_data['maintenance_until'].replace('Z', '+00:00')), resource_data['maintenance_until'].replace(tzinfo=None))
        self.assertEqual(exported_res_data['max_recurrence_count'], resource_data['max_recurrence_count'])
        self.assertEqual(exported_res_data['scheduled_status'], resource_data['scheduled_status'])
        self.assertEqual(datetime.fromisoformat(exported_res_data['scheduled_status_at'].replace('Z', '+00:00')), resource_data['scheduled_status_at'].replace(tzinfo=None))
        self.assertEqual(exported_res_data['floor_map_id'], resource_data['floor_map_id'])
        self.assertEqual(exported_res_data['map_coordinates'], json.loads(resource_data['map_coordinates']))

        self.assertIsInstance(exported_res_data['roles'], list)
        self.assertEqual(len(exported_res_data['roles']), 1)
        self.assertEqual(exported_res_data['roles'][0]['id'], self.role1.id)
        self.assertEqual(exported_res_data['roles'][0]['name'], self.role1.name)
        self.assertIsNotNone(exported_res_data['published_at']) # status is 'published'

        # Check if self.resource1 (from parent setUp) is also present
        parent_resource_data = next((r for r in data if r['id'] == self.resource1.id), None)
        self.assertIsNotNone(parent_resource_data)
        self.assertEqual(parent_resource_data['name'], self.resource1.name)

    def test_import_resources_create_and_update(self):
        """Test importing resources (create new and update existing)."""
        self.login(self.admin_user.username, 'adminpass')

        # Prepare initial resource to be updated by name
        initial_resource_name = "Resource To Update By Name"
        initial_res_by_name = Resource(name=initial_resource_name, capacity=10, status="draft")
        db.session.add(initial_res_by_name)
        db.session.commit()
        initial_res_by_name_id = initial_res_by_name.id

        # Prepare initial resource to be updated by ID (self.resource2 from AppTests.setUp)
        initial_res_by_id_id = self.resource2.id
        initial_res_by_id_original_name = self.resource2.name
        initial_res_by_id_original_capacity = self.resource2.capacity


        import_data = [
            { # New resource
                "name": "Imported Resource New",
                "capacity": 5,
                "equipment": "Laptop",
                "status": "published",
                "tags": "imported, new",
                "booking_restriction": None,
                "allowed_user_ids": f"{self.standard_user.id}",
                "roles": [{"id": self.role1.id}], # Test role assignment by ID
                "is_under_maintenance": False,
                "floor_map_id": self.floor_map.id, # Use existing map
                "map_coordinates": {"type": "rect", "x":10, "y":10, "width":10, "height":10}
            },
            { # Update existing resource (self.resource2) by its ID
                "id": initial_res_by_id_id,
                "name": "Updated Resource Name By ID", # Change name
                "capacity": 15, # Change capacity
                "status": "archived",
                "roles": [{"name": self.role2.name}] # Test role assignment by name
            },
            { # Update existing resource by its name
                "name": initial_resource_name, # Match by this name
                "capacity": 20, # Change capacity
                "equipment": "Updated Equipment",
                "tags": "updated, by-name"
            }
        ]

        # Simulate file upload
        from io import BytesIO
        file_content = json.dumps(import_data).encode('utf-8')
        data = {'file': (BytesIO(file_content), 'import_resources.json')}

        response = self.client.post('/api/admin/resources/import', data=data, content_type='multipart/form-data')

        self.assertEqual(response.status_code, 200) # Or 207 if there are partial errors we're not testing yet
        resp_json = response.get_json()

        self.assertEqual(resp_json.get('created'), 1)
        self.assertEqual(resp_json.get('updated'), 2)
        self.assertEqual(len(resp_json.get('errors', [])), 0)

        # Verify new resource
        new_res = Resource.query.filter_by(name="Imported Resource New").first()
        self.assertIsNotNone(new_res)
        self.assertEqual(new_res.capacity, 5)
        self.assertEqual(new_res.equipment, "Laptop")
        self.assertEqual(new_res.status, "published")
        self.assertEqual(new_res.tags, "imported, new")
        self.assertEqual(new_res.allowed_user_ids, str(self.standard_user.id))
        self.assertIn(self.role1, new_res.roles)
        self.assertEqual(new_res.floor_map_id, self.floor_map.id)
        self.assertIsNotNone(new_res.map_coordinates)
        self.assertFalse(new_res.is_under_maintenance)

        # Verify resource updated by ID (self.resource2)
        updated_res_by_id = Resource.query.get(initial_res_by_id_id)
        self.assertEqual(updated_res_by_id.name, "Updated Resource Name By ID")
        self.assertEqual(updated_res_by_id.capacity, 15)
        self.assertEqual(updated_res_by_id.status, "archived")
        self.assertIn(self.role2, updated_res_by_id.roles)

        # Verify resource updated by name
        updated_res_by_name = Resource.query.get(initial_res_by_name_id)
        self.assertEqual(updated_res_by_name.name, initial_resource_name) # Name should not change when matched by name unless explicitly in payload
        self.assertEqual(updated_res_by_name.capacity, 20)
        self.assertEqual(updated_res_by_name.equipment, "Updated Equipment")
        self.assertEqual(updated_res_by_name.tags, "updated, by-name")

    def test_import_resources_error_handling(self):
        """Test error handling during resource import."""
        self.login(self.admin_user.username, 'adminpass')

        import_data_errors = [
            { # Missing name for new resource
                "capacity": 10
            },
            { # Existing resource by name, but role not found
                "name": self.resource1.name, # self.resource1 is from AppTests.setUp
                "roles": [{"id": 999}] # Non-existent role ID
            },
            { # Invalid data type for capacity
                "name": "Resource Invalid Capacity",
                "capacity": "not-a-number"
            }
        ]
        file_content_errors = json.dumps(import_data_errors).encode('utf-8')
        data_errors = {'file': (BytesIO(file_content_errors), 'import_errors.json')}

        response_errors = self.client.post('/api/admin/resources/import', data=data_errors, content_type='multipart/form-data')
        self.assertEqual(response_errors.status_code, 207) # Multi-Status
        resp_json_errors = response_errors.get_json()

        self.assertEqual(resp_json_errors.get('created', 0), 0) # No new resources should be fully created if they have errors.
        self.assertEqual(resp_json_errors.get('updated', 0), 0) # No successful updates if the only changes are problematic.
        self.assertTrue(len(resp_json_errors.get('errors', [])) >= 2) # Expecting at least 2 errors (missing name, role not found)
                                                                    # The invalid capacity might be caught by setattr or type conversion

        # Check specific error messages (optional, but good for confirming error details)
        errors = resp_json_errors.get('errors')
        self.assertTrue(any("Missing name for new resource" in e['error'] for e in errors))
        self.assertTrue(any("Role not found" in e['error'] for e in errors))
        # The "not-a-number" for capacity might result in a more generic "Error processing resource" or a DB error if not caught early.
        # For now, checking the count of errors is the primary goal.


class TestMapConfigurationImportExportAPI(AppTests):
    def setUp(self):
        super().setUp()
        self.admin_user = User(username='mapconfigadmin', email='mapconfig@example.com', is_admin=True)
        self.admin_user.set_password('adminpass')

        admin_role = Role.query.filter_by(name="Administrator").first()
        if not admin_role: # Ensure Administrator role with all_permissions exists
            admin_role = Role(name="Administrator", permissions="all_permissions,manage_floor_maps") # Explicitly add manage_floor_maps
            db.session.add(admin_role)

        self.admin_user.roles.append(admin_role)
        db.session.add(self.admin_user)

        # Create a role and assign to one of the resources for export testing
        self.map_test_role = Role(name='Map Test Role')
        db.session.add(self.map_test_role)
        db.session.commit()

        self.resource1.roles.append(self.map_test_role)
        self.resource1.booking_restriction = "admin_only" # Example value
        self.resource1.allowed_user_ids = str(self.admin_user.id) # Example value
        db.session.commit()


    def test_export_map_configuration(self):
        """Test export map configuration API endpoint."""
        self.login(self.admin_user.username, 'adminpass')

        response = self.client.get('/api/admin/maps/export_configuration')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, 'application/json')
        self.assertIn('attachment; filename=map_configuration_export.json', response.headers['Content-Disposition'])

        data = json.loads(response.data.decode('utf-8'))
        self.assertIn('floor_maps', data)
        self.assertIn('mapped_resources', data)
        self.assertIsInstance(data['floor_maps'], list)
        self.assertIsInstance(data['mapped_resources'], list)

        # Verify FloorMap data (self.floor_map is from AppTests.setUp)
        fm_data = next((fm for fm in data['floor_maps'] if fm['id'] == self.floor_map.id), None)
        self.assertIsNotNone(fm_data)
        self.assertEqual(fm_data['name'], self.floor_map.name)
        self.assertEqual(fm_data['image_filename'], self.floor_map.image_filename)
        self.assertEqual(fm_data['location'], self.floor_map.location)
        self.assertEqual(fm_data['floor'], self.floor_map.floor)

        # Verify Mapped Resource data (self.resource1 is from AppTests.setUp and modified in this class's setUp)
        # Resource1 is mapped to self.floor_map in AppTests.setUp
        res_data = next((r for r in data['mapped_resources'] if r['id'] == self.resource1.id), None)
        self.assertIsNotNone(res_data)
        self.assertEqual(res_data['name'], self.resource1.name)
        self.assertEqual(res_data['floor_map_id'], self.floor_map.id)
        self.assertIsInstance(res_data['map_coordinates'], dict) # Should be parsed from JSON string
        self.assertEqual(res_data['map_coordinates']['x'], 10) # From AppTests.setUp
        self.assertEqual(res_data['booking_restriction'], "admin_only")
        self.assertEqual(res_data['allowed_user_ids'], str(self.admin_user.id))

        self.assertIsInstance(res_data['role_ids'], list)
        self.assertIn(self.map_test_role.id, res_data['role_ids'])

        # Ensure a resource NOT mapped is NOT in mapped_resources
        # Create a resource not mapped
        unmapped_res = Resource(name="Unmapped Export Test Res", status="published")
        db.session.add(unmapped_res)
        db.session.commit()
        unmapped_res_data = next((r for r in data['mapped_resources'] if r['id'] == unmapped_res.id), None)
        self.assertIsNone(unmapped_res_data)

    def test_import_map_configuration(self):
        """Test import map configuration API endpoint."""
        self.login(self.admin_user.username, 'adminpass')

        # Data for import
        new_map_name = f"Imported New Map {unittest.mock.ANY}" # Make name unique for creation
        new_map_image = "new_map_import.jpg"

        # Existing map to be updated (self.floor_map from AppTests.setUp)
        existing_map_id = self.floor_map.id
        updated_map_location = "Updated Location Main Campus"

        # Existing resource to be mapped/updated (self.resource2 from AppTests.setUp)
        # self.resource1 is already mapped in setup, we can try re-mapping it or updating its mapping.

        import_config_data = {
            "floor_maps": [
                { # Create new map
                    "name": new_map_name,
                    "image_filename": new_map_image,
                    "location": "New Building",
                    "floor": "5"
                },
                { # Update existing map (self.floor_map)
                    "id": existing_map_id,
                    "name": self.floor_map.name, # Keep name same or change it
                    "location": updated_map_location
                    # image_filename and floor could also be updated
                }
            ],
            "mapped_resources": [
                { # Map self.resource2 to the newly imported map (identified by name)
                  # For this to work, the new map must be processed first and its ID made available.
                  # The import logic should handle this by looking up map by name if ID from import isn't found yet.
                  # Or, better, process maps first, then map resources using the *actual* DB IDs of maps.
                  # The current export exports map ID. The import should try to use that ID.
                  # If a map in the import file has an ID that doesn't exist, it will be treated as new if name is unique.
                  # If a map in import has an ID that *does* exist, it's an update.
                  # For mapping resources, it's best if the import file uses *original* map IDs, and the import
                  # logic maps them to the *actual current* map IDs (which might be new if maps were re-created by name).
                  # For this test, we'll assume the 'floor_map_id' in mapped_resources refers to an ID that *will* exist after map import.

                    "id": self.resource2.id, # Target existing resource
                    # "floor_map_id": existing_map_id, # Let's map it to the *updated* existing_map_id first
                                                    # This map ID *should* be stable.
                    # For testing mapping to a *newly created* map, we'd need its ID.
                    # The import route currently uses `fm_data['processed_id']` to map.
                    # So, if the new map "Imported New Map" is processed and gets an ID, say 100,
                    # then a resource could refer to "floor_map_id": <original_id_of_new_map_if_it_had_one_in_json>
                    # OR, if the import JSON for the new map doesn't have an ID, we can't directly reference it
                    # by ID in the mapped_resources section of the *same* import file unless we assume order and lookup by name.
                    # Let's test mapping self.resource2 to the map that will be 'Imported New Map'
                    # We need to know what ID 'Imported New Map' will get, or modify import to allow name-based map linking for resources.
                    # The current import logic for maps stores 'processed_id' in fm_data.
                    # The resource mapping logic then tries to find the map using this 'processed_id' if the original map ID was in the file.
                    # This is a bit complex for a direct test without knowing the assigned ID.
                    # Let's simplify: map self.resource2 to the *existing* map (self.floor_map) but with new coords.
                    "floor_map_id": existing_map_id,
                    "map_coordinates": {"type": "rect", "x": 200, "y": 200, "width": 20, "height": 20},
                    "booking_restriction": "all_users",
                    "allowed_user_ids": "", # Clear allowed users
                    "role_ids": [self.map_test_role.id, self.role1.id] # Assign two roles
                },
                { # Update mapping for self.resource1 (already mapped in setUp)
                    "id": self.resource1.id,
                    "floor_map_id": existing_map_id, # Keep on same map
                    "map_coordinates": {"type": "rect", "x": 10, "y": 20, "width": 35, "height": 35}, # Change coords
                    "role_ids": [self.role2.id] # Change role
                }
            ]
        }

        from io import BytesIO
        file_content = json.dumps(import_config_data).encode('utf-8')
        data_file = {'file': (BytesIO(file_content), 'import_map_config.json')}

        response = self.client.post('/api/admin/maps/import_configuration', data=data_file, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 200) # Or 207 if expecting partial errors/reminders
        resp_json = response.get_json()

        self.assertEqual(resp_json.get('maps_created'), 1)
        self.assertEqual(resp_json.get('maps_updated'), 1)
        self.assertEqual(len(resp_json.get('maps_errors', [])), 0)
        self.assertEqual(resp_json.get('resource_mappings_updated'), 2)
        self.assertEqual(len(resp_json.get('resource_mapping_errors', [])), 0)
        self.assertTrue(any(new_map_image in reminder for reminder in resp_json.get('image_reminders', [])))

        # Verify new map
        imported_map = FloorMap.query.filter_by(name=new_map_name).first()
        self.assertIsNotNone(imported_map)
        self.assertEqual(imported_map.image_filename, new_map_image)
        self.assertEqual(imported_map.location, "New Building")

        # Verify updated map
        updated_map = FloorMap.query.get(existing_map_id)
        self.assertEqual(updated_map.location, updated_map_location)

        # Verify resource2 mapping
        res2_updated = Resource.query.get(self.resource2.id)
        self.assertEqual(res2_updated.floor_map_id, existing_map_id)
        self.assertIsNotNone(res2_updated.map_coordinates)
        coords_res2 = json.loads(res2_updated.map_coordinates)
        self.assertEqual(coords_res2['x'], 200)
        self.assertEqual(res2_updated.booking_restriction, "all_users")
        self.assertEqual(res2_updated.allowed_user_ids, "")
        self.assertIn(self.map_test_role, res2_updated.roles)
        self.assertIn(self.role1, res2_updated.roles)
        self.assertEqual(len(res2_updated.roles), 2)


        # Verify resource1 mapping update
        res1_updated = Resource.query.get(self.resource1.id)
        self.assertEqual(res1_updated.floor_map_id, existing_map_id)
        coords_res1 = json.loads(res1_updated.map_coordinates)
        self.assertEqual(coords_res1['width'], 35)
        self.assertNotIn(self.map_test_role, res1_updated.roles) # Original role should be replaced
        self.assertIn(self.role2, res1_updated.roles)
        self.assertEqual(len(res1_updated.roles), 1)


class TestAdminBookings(AppTests):
    def _create_admin_user(self, username="adminbookings", email_ext="adminbookings"):
        admin_user = User(username=username, email=f"{email_ext}@example.com", is_admin=True)
        admin_user.set_password("adminpass")
        # Add 'manage_bookings' permission to this admin user via a role
        admin_role = db.session.query(Role).filter_by(name="Administrator").first()
        if not admin_role:
            admin_role = Role(name="Administrator", permissions="all_permissions,manage_bookings")
            db.session.add(admin_role)
        admin_user.roles.append(admin_role)
        db.session.add(admin_user)
        db.session.commit()
        return admin_user

    def test_admin_bookings_page_access_permission(self):
        """Test access permissions for the admin bookings page."""
        # Unauthenticated
        response_unauth = self.client.get('/admin/bookings', follow_redirects=False)
        self.assertEqual(response_unauth.status_code, 302)
        self.assertIn('/login', response_unauth.location)

        # Non-admin login (testuser is not admin by default)
        self.login('testuser', 'password')
        response_non_admin = self.client.get('/admin/bookings', follow_redirects=False)
        self.assertEqual(response_non_admin.status_code, 403)
        self.logout()

        # Admin login
        admin = self._create_admin_user()
        self.login(admin.username, 'adminpass')
        response_admin = self.client.get('/admin/bookings')
        self.assertEqual(response_admin.status_code, 200)
        self.assertIn(b'Admin Bookings Management', response_admin.data) # Check for page title/heading
        self.logout()

    def test_admin_hard_delete_booking_success(self):
        """Test successful hard deletion of a booking by an admin."""
        admin_user = self._create_admin_user(username="adminharddeleteuser", email_ext="adminharddelete")
        self.login(admin_user.username, 'adminpass')

        booking_owner = User.query.filter_by(username='testuser').first()
        self.assertIsNotNone(booking_owner, "Test user 'testuser' not found for booking creation.")

        booking_to_delete = self._create_booking(
            user_name=booking_owner.username,
            resource_id=self.resource1.id,
            start_offset_hours=24,
            title="Booking To Be Hard Deleted"
        )
        booking_id_to_delete = booking_to_delete.id
        original_booking_title = booking_to_delete.title
        original_resource_name = self.resource1.name
        original_user_name = booking_owner.username

        self.assertIsNotNone(Booking.query.get(booking_id_to_delete), "Booking creation failed for hard delete test.")

        response = self.client.post(f'/api/admin/bookings/{booking_id_to_delete}/delete')

        self.assertEqual(response.status_code, 200, f"API call failed: {response.get_data(as_text=True)}")
        response_data = response.get_json()
        self.assertEqual(response_data.get('message'), 'Booking deleted successfully by admin.')
        self.assertEqual(response_data.get('booking_id'), booking_id_to_delete)

        self.assertIsNone(Booking.query.get(booking_id_to_delete), "Booking was not deleted from the database.")

        audit_log = AuditLog.query.filter_by(action="ADMIN_DELETE_BOOKING", user_id=admin_user.id).order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log, "ADMIN_DELETE_BOOKING audit log not found.")
        self.assertIn(f"Admin '{admin_user.username}' DELETED booking ID {booking_id_to_delete}", audit_log.details)
        self.assertIn(f"Booked by: '{original_user_name}'", audit_log.details)
        self.assertIn(f"Resource: '{original_resource_name}'", audit_log.details)
        self.assertIn(f"Title: '{original_booking_title}'", audit_log.details)
        self.assertNotIn("Deletion message:", audit_log.details) # Ensure no cancellation message part
        self.assertNotIn("cancelled booking", audit_log.details.lower()) # Ensure it says deleted, not cancelled

        self.logout()

    def test_admin_delete_booking_not_found(self):
        """Test admin deleting a non-existent booking."""
        admin_user = self._create_admin_user(username="admin_del_notfound", email_ext="admindelnotfound")
        self.login(admin_user.username, 'adminpass')

        non_existent_booking_id = 99999
        response = self.client.post(f'/api/admin/bookings/{non_existent_booking_id}/delete')
        self.assertEqual(response.status_code, 404)
        self.assertIn('Booking not found', response.get_json().get('error', ''))

        self.logout()

    def test_admin_delete_booking_no_permission(self):
        """Test non-admin (or admin without permission) attempting to delete a booking."""
        booking_to_delete = self._create_booking(user_name='testuser', resource_id=self.resource1.id, start_offset_hours=24)

        self.login('testuser', 'password')

        response = self.client.post(f'/api/admin/bookings/{booking_to_delete.id}/delete')
        self.assertEqual(response.status_code, 403, "Non-admin user should be forbidden to delete bookings via admin route.")

        self.assertIsNotNone(Booking.query.get(booking_to_delete.id))
        self.logout()

    def test_admin_delete_completed_booking_success(self):
        """Test admin deleting a booking that is already 'completed'."""
        admin_user = self._create_admin_user(username="admin_del_completed", email_ext="admindelcompleted")
        self.login(admin_user.username, 'adminpass')

        booking_owner = User.query.filter_by(username='testuser').first()
        booking = self._create_booking(user_name=booking_owner.username, resource_id=self.resource1.id, start_offset_hours=1, title="Completed Deletable Test")
        booking_id = booking.id
        booking.status = 'completed' # Set to a terminal status
        db.session.commit()

        original_booking_title = booking.title
        original_resource_name = self.resource1.name

        self.assertIsNotNone(Booking.query.get(booking_id), "Booking setup failed.")

        response = self.client.post(f'/api/admin/bookings/{booking_id}/delete')
        self.assertEqual(response.status_code, 200, f"API call failed: {response.get_data(as_text=True)}")
        response_data = response.get_json()
        self.assertEqual(response_data.get('message'), 'Booking deleted successfully by admin.')
        self.assertEqual(response_data.get('booking_id'), booking_id)

        self.assertIsNone(Booking.query.get(booking_id), "Completed booking was not deleted from the database.")

        audit_log = AuditLog.query.filter_by(action="ADMIN_DELETE_BOOKING", user_id=admin_user.id).order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log, "ADMIN_DELETE_BOOKING audit log not found for completed booking.")
        self.assertIn(f"Admin '{admin_user.username}' DELETED booking ID {booking_id}", audit_log.details)
        self.assertIn(f"Original status was: 'completed'", audit_log.details)
        self.assertIn(f"Booked by: '{booking_owner.username}'", audit_log.details)
        self.assertIn(f"Resource: '{original_resource_name}'", audit_log.details)
        self.assertIn(f"Title: '{original_booking_title}'", audit_log.details)

        self.logout()

    def test_admin_bookings_page_displays_bookings(self):
        """Test that the admin bookings page displays created bookings."""
        admin = self._create_admin_user()
        self.login(admin.username, 'adminpass')

        # Create a second user for variety
        user2 = User(username='testuser2', email='test2@example.com')
        user2.set_password('password2')
        db.session.add(user2)
        db.session.commit()

        booking1 = self._create_booking(user_name='testuser', resource_id=self.resource1.id, start_offset_hours=1, title="Booking Alpha")
        booking2 = self._create_booking(user_name='testuser2', resource_id=self.resource2.id, start_offset_hours=2, title="Booking Beta")

        response = self.client.get('/admin/bookings')
        self.assertEqual(response.status_code, 200)
        html_content = response.data.decode('utf-8')

        self.assertIn(booking1.title, html_content)
        self.assertIn(booking1.user_name, html_content) # testuser
        self.assertIn(self.resource1.name, html_content)

        self.assertIn(booking2.title, html_content)
        self.assertIn(booking2.user_name, html_content)
        self.assertIn(self.resource2.name, html_content)
        self.logout()

    def test_admin_delete_booking_permission(self):
        """Test permissions for the admin delete booking API endpoint."""
        booking = self._create_booking(user_name='testuser', resource_id=self.resource1.id, start_offset_hours=1)

        # Unauthenticated
        response_unauth = self.client.post(f'/api/admin/bookings/{booking.id}/delete')
        self.assertEqual(response_unauth.status_code, 401)

        # Non-admin login
        self.login('testuser', 'password')
        response_non_admin = self.client.post(f'/api/admin/bookings/{booking.id}/delete')
        self.assertEqual(response_non_admin.status_code, 403)
        self.logout()

        # Admin with permission is tested in test_admin_hard_delete_booking_success

    def test_admin_clear_booking_message_success(self):
        """Test admin clearing a 'cancelled_by_admin' booking's message."""
        admin_user = self._create_admin_user(username="admin_clear_msg_user", email_ext="adminclearmsg")
        self.login(admin_user.username, 'adminpass')

        regular_user = User.query.filter_by(username='testuser').first()
        booking = self._create_booking(
            user_name=regular_user.username,
            resource_id=self.resource1.id,
            start_offset_hours=24,
            title="Booking for Message Clear"
        )
        booking_id = booking.id
        booking.status = 'cancelled_by_admin'
        booking.admin_deleted_message = "Initial cancellation message."
        db.session.commit()

        response = self.client.post(f'/api/admin/bookings/{booking_id}/clear_admin_message')
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertEqual(json_data.get('message'), 'Admin message cleared and booking acknowledged.')
        self.assertEqual(json_data.get('new_status'), 'cancelled_admin_acknowledged')

        updated_booking = Booking.query.get(booking_id)
        self.assertIsNone(updated_booking.admin_deleted_message)
        self.assertEqual(updated_booking.status, 'cancelled_admin_acknowledged')

        audit_log = AuditLog.query.filter_by(action="ADMIN_CLEAR_BOOKING_MESSAGE", user_id=admin_user.id).order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log)
        self.assertIn(f"Admin '{admin_user.username}' cleared cancellation message for booking ID {booking_id}", audit_log.details)
        self.assertIn("Status changed to 'cancelled_admin_acknowledged'", audit_log.details)
        self.logout()

    def test_admin_clear_booking_message_booking_not_found(self):
        """Test admin clearing message for a non-existent booking."""
        admin_user = self._create_admin_user(username="admin_clear_notfound", email_ext="adminclearnf")
        self.login(admin_user.username, 'adminpass')
        non_existent_booking_id = 99999
        response = self.client.post(f'/api/admin/bookings/{non_existent_booking_id}/clear_admin_message')
        self.assertEqual(response.status_code, 404)
        self.assertIn('Booking not found', response.get_json().get('error', ''))
        self.logout()

    def test_admin_clear_booking_message_unauthorized(self):
        """Test non-admin attempting to clear admin message."""
        regular_user = User.query.filter_by(username='testuser').first()
        booking = self._create_booking(
            user_name=regular_user.username,
            resource_id=self.resource1.id,
            start_offset_hours=24
        )
        booking.status = 'cancelled_by_admin'
        booking.admin_deleted_message = "A message."
        db.session.commit()

        self.login(regular_user.username, 'password') # Log in as non-admin
        response = self.client.post(f'/api/admin/bookings/{booking.id}/clear_admin_message')
        self.assertEqual(response.status_code, 403)
        self.logout()

    def test_admin_clear_booking_message_not_cancelled_by_admin(self):
        """Test admin clearing message for a booking not in 'cancelled_by_admin' state."""
        admin_user = self._create_admin_user(username="admin_clear_wrong_status", email_ext="adminclearws")
        self.login(admin_user.username, 'adminpass')

        booking = self._create_booking(
            user_name='testuser',
            resource_id=self.resource1.id,
            start_offset_hours=24
        )
        booking.status = 'approved' # Not 'cancelled_by_admin'
        booking.admin_deleted_message = None # Should be None anyway for approved
        db.session.commit()
        booking_id = booking.id

        response = self.client.post(f'/api/admin/bookings/{booking_id}/clear_admin_message')
        self.assertEqual(response.status_code, 400)
        self.assertIn("Message can only be cleared for bookings cancelled by an admin.", response.get_json().get('error', ''))

        # Verify booking is unchanged
        unchanged_booking = Booking.query.get(booking_id)
        self.assertEqual(unchanged_booking.status, 'approved')
        self.assertIsNone(unchanged_booking.admin_deleted_message)
        self.logout()

    def test_admin_bookings_nav_link_visibility(self):
        """Test that the admin bookings nav link is rendered in base.html."""
        # Unauthenticated
        response_unauth = self.client.get('/')
        self.assertEqual(response_unauth.status_code, 200) # Home page should be accessible
        self.assertIn(b'<li id="admin-bookings-nav-link"', response_unauth.data)
        # We expect style="display: none;" due to JS, but testing exact style is tricky here.
        # The main check is that the element is part of the server-rendered HTML.

        # Non-admin login
        self.login('testuser', 'password')
        response_non_admin = self.client.get('/')
        self.assertEqual(response_non_admin.status_code, 200)
        self.assertIn(b'<li id="admin-bookings-nav-link"', response_non_admin.data)
        self.logout()

        # Admin login
        admin = self._create_admin_user()
        self.login(admin.username, 'adminpass')
        response_admin = self.client.get('/')
        self.assertEqual(response_admin.status_code, 200)
        self.assertIn(b'<li id="admin-bookings-nav-link"', response_admin.data)
        self.logout()

    def test_admin_menu_contains_booking_settings_link(self):
        """Test that the 'Booking Settings' link is present in the admin menu for admin users."""
        admin_user = self._create_admin_user(username="navtestadmin", email_ext="navtest")
        self.login(admin_user.username, "adminpass")

        # Access a page that includes the admin sidebar
        response = self.client.get('/admin/users_manage') # Using a known admin page
        self.assertEqual(response.status_code, 200)

        html_content = response.data.decode('utf-8')

        # Check for the link's href
        from flask import url_for # Import url_for if not already available at class/module level
        expected_href = url_for('admin_ui.serve_booking_settings_page')
        self.assertIn(f'href="{expected_href}"', html_content)

        # Check for the link's text
        self.assertIn(">Booking Settings<", html_content) # Simple string match

        # Check that the li element itself is present (JS might control display style)
        self.assertIn('id="booking-settings-nav-link"', html_content)

        self.logout()

    def test_admin_get_booking_settings_page_no_settings_exist(self):
        """Test GET /admin/booking_settings when no settings exist in DB."""
        admin = self._create_admin_user(username="settingsadmin1", email_ext="settings1")
        self.login(admin.username, 'adminpass')

        # Ensure no BookingSettings exist
        BookingSettings.query.delete()
        db.session.commit()

        response = self.client.get('/admin/booking_settings')
        self.assertEqual(response.status_code, 200)
        html_content = response.data.decode('utf-8')

        self.assertIn('<h1>Booking Settings</h1>', html_content) # Or translated version
        # Check for default values being reflected in the form (e.g., checkboxes not checked, specific default for numbers)
        self.assertIn('name="allow_past_bookings"', html_content)
        self.assertNotIn('name="allow_past_bookings" checked', html_content) # Default is False
        self.assertIn('name="max_booking_days_in_future" value="30"', html_content) # Default is 30 in route
        self.assertIn('name="enable_check_in_out"', html_content)
        self.logout()

    def test_admin_get_booking_settings_page_existing_settings(self):
        """Test GET /admin/booking_settings when settings exist in DB."""
        admin = self._create_admin_user(username="settingsadmin2", email_ext="settings2")
        self.login(admin.username, 'adminpass')

        # Create and save specific settings
        BookingSettings.query.delete() # Clear any previous
        settings = BookingSettings(
            allow_past_bookings=True,
            max_booking_days_in_future=45,
            allow_multiple_resources_same_time=True,
            max_bookings_per_user=10,
            enable_check_in_out=True
        )
        db.session.add(settings)
        db.session.commit()

        response = self.client.get('/admin/booking_settings')
        self.assertEqual(response.status_code, 200)
        html_content = response.data.decode('utf-8')

        self.assertIn('name="allow_past_bookings" checked', html_content)
        self.assertIn('name="max_booking_days_in_future" value="45"', html_content)
        self.assertIn('name="allow_multiple_resources_same_time" checked', html_content)
        self.assertIn('name="max_bookings_per_user" value="10"', html_content)
        self.assertIn('name="enable_check_in_out" checked', html_content)
        # Assuming past_booking_time_adjustment_hours was not set or default 0 for this existing setting
        # If it was set to a specific value, that value should be checked here.
        # For this test, let's assume it would be 0 if not set.
        if settings.past_booking_time_adjustment_hours is not None:
             self.assertIn(f'name="past_booking_time_adjustment_hours" value="{settings.past_booking_time_adjustment_hours}"', html_content)
        else:
             self.assertIn('name="past_booking_time_adjustment_hours" value="0"', html_content)
        self.logout()

    def test_admin_post_update_booking_settings_create_new(self):
        """Test POST /admin/booking_settings/update to create settings."""
        admin = self._create_admin_user(username="settingsadmin3", email_ext="settings3")
        self.login(admin.username, 'adminpass')

        BookingSettings.query.delete()
        db.session.commit()
        self.assertIsNone(BookingSettings.query.first())

        form_data = {
            'allow_past_bookings': 'on', # Checkbox 'on'
            'max_booking_days_in_future': '90',
            # allow_multiple_resources_same_time not sent (effectively False)
            'max_bookings_per_user': '5',
            'enable_check_in_out': 'on',
            'past_booking_time_adjustment_hours': '3'
        }
        response = self.client.post('/admin/booking_settings/update', data=form_data, follow_redirects=True)
        self.assertEqual(response.status_code, 200) # Should redirect to GET page
        self.assertIn(b'Booking settings updated successfully.', response.data) # Check flash message

        settings = BookingSettings.query.first()
        self.assertIsNotNone(settings)
        self.assertTrue(settings.allow_past_bookings)
        self.assertEqual(settings.max_booking_days_in_future, 90)
        self.assertFalse(settings.allow_multiple_resources_same_time) # Was not sent, so default False
        self.assertEqual(settings.max_bookings_per_user, 5)
        self.assertTrue(settings.enable_check_in_out)
        self.assertEqual(settings.past_booking_time_adjustment_hours, 3)
        self.logout()

    def test_admin_post_update_booking_settings_update_existing(self):
        """Test POST /admin/booking_settings/update to update existing settings."""
        admin = self._create_admin_user(username="settingsadmin4", email_ext="settings4")
        self.login(admin.username, 'adminpass')

        BookingSettings.query.delete()
        initial_settings = BookingSettings(allow_past_bookings=True, max_booking_days_in_future=30)
        db.session.add(initial_settings)
        db.session.commit()

        form_data = {
            # allow_past_bookings not sent (effectively False for checkbox)
            'max_booking_days_in_future': '15',
            'allow_multiple_resources_same_time': 'on',
            'max_bookings_per_user': '', # Empty string should be None
            'enable_check_in_out': 'on',
            'past_booking_time_adjustment_hours': '-2'
        }
        response = self.client.post('/admin/booking_settings/update', data=form_data, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Booking settings updated successfully.', response.data)

        settings = BookingSettings.query.first()
        self.assertIsNotNone(settings)
        self.assertFalse(settings.allow_past_bookings) # Checkbox not sent means False
        self.assertEqual(settings.max_booking_days_in_future, 15)
        self.assertTrue(settings.allow_multiple_resources_same_time)
        self.assertIsNone(settings.max_bookings_per_user) # Empty string becomes None
        self.assertTrue(settings.enable_check_in_out)
        self.assertEqual(settings.past_booking_time_adjustment_hours, -2)
        self.logout()

    def test_admin_post_update_booking_settings_specific_fields(self):
        """Test updating specific fields including past_booking_time_adjustment_hours, its persistence, and interaction with allow_past_bookings."""
        admin = self._create_admin_user(username="settingsadmin_specific", email_ext="settings_specific")
        self.login(admin.username, 'adminpass')

        BookingSettings.query.delete()
        # Initial state: allow_past_bookings=False, adjustment_hours=0
        settings = BookingSettings(allow_past_bookings=False, past_booking_time_adjustment_hours=0)
        db.session.add(settings)
        db.session.commit()

        # Case 1: allow_past_bookings is UNCHECKED (adjustment field is ENABLED and submitted)
        form_data_enabled = {
            # 'allow_past_bookings': 'off', # Not sending this key simulates checkbox being off
            'past_booking_time_adjustment_hours': '5',
            # Other fields not sent to keep test focused
        }
        self.client.post('/admin/booking_settings/update', data=form_data_enabled)
        settings_case1 = BookingSettings.query.first()
        self.assertFalse(settings_case1.allow_past_bookings)
        self.assertEqual(settings_case1.past_booking_time_adjustment_hours, 5)

        # Case 2: allow_past_bookings is CHECKED (adjustment field is DISABLED and NOT submitted by browser)
        # Value from Case 1 (5) should be preserved due to new backend logic.
        form_data_disabled = {
            'allow_past_bookings': 'on',
            # past_booking_time_adjustment_hours is NOT sent in the form data, simulating a disabled field
        }
        self.client.post('/admin/booking_settings/update', data=form_data_disabled)
        settings_case2 = BookingSettings.query.first()
        self.assertTrue(settings_case2.allow_past_bookings)
        self.assertEqual(settings_case2.past_booking_time_adjustment_hours, 5, "Value should be preserved from previous state as field was disabled")

        # Case 3: allow_past_bookings is UNCHECKED again, new value for adjustment hours
        # This ensures that if the field becomes enabled again, it can be updated.
        form_data_reenabled = {
            # allow_past_bookings not sent (effectively 'off')
            'past_booking_time_adjustment_hours': '-3',
        }
        self.client.post('/admin/booking_settings/update', data=form_data_reenabled)
        settings_case3 = BookingSettings.query.first()
        self.assertFalse(settings_case3.allow_past_bookings)
        self.assertEqual(settings_case3.past_booking_time_adjustment_hours, -3)

        # Case 4: Test empty string submission when field is enabled (allow_past_bookings is 'off')
        form_data_empty_enabled = {
            # allow_past_bookings not sent (effectively 'off')
            'past_booking_time_adjustment_hours': '',
        }
        self.client.post('/admin/booking_settings/update', data=form_data_empty_enabled)
        settings_case4 = BookingSettings.query.first()
        self.assertFalse(settings_case4.allow_past_bookings)
        self.assertEqual(settings_case4.past_booking_time_adjustment_hours, 0) # Should default to 0

        # Case 5: Test invalid (non-integer) when field is enabled (allow_past_bookings is 'off')
        initial_adj_val_before_invalid = settings_case4.past_booking_time_adjustment_hours # Should be 0
        form_data_invalid_enabled = {
            # allow_past_bookings not sent (effectively 'off')
            'past_booking_time_adjustment_hours': 'not-an-integer',
        }
        response_invalid = self.client.post('/admin/booking_settings/update', data=form_data_invalid_enabled, follow_redirects=True)
        self.assertIn(b'Invalid input for "Past booking time adjustment"', response_invalid.data)
        settings_case5 = BookingSettings.query.first()
        self.assertFalse(settings_case5.allow_past_bookings) # allow_past_bookings was not sent, so it should be False
        self.assertEqual(settings_case5.past_booking_time_adjustment_hours, initial_adj_val_before_invalid) # Should not change from last valid

        self.logout()

    def test_admin_post_update_booking_settings_invalid_data(self):
        """Test POST /admin/booking_settings/update with invalid data."""
        admin = self._create_admin_user(username="settingsadmin5", email_ext="settings5")
        self.login(admin.username, 'adminpass')

        BookingSettings.query.delete()
        initial_settings = BookingSettings(max_booking_days_in_future=30) # Keep a known state
        db.session.add(initial_settings)
        db.session.commit()

        form_data = {
            'max_booking_days_in_future': 'not-a-number',
        }
        response = self.client.post('/admin/booking_settings/update', data=form_data, follow_redirects=True)
        self.assertEqual(response.status_code, 200) # Still lands on the page
        self.assertIn(b'Invalid input for numeric field.', response.data) # Check flash error

        settings = BookingSettings.query.first()
        self.assertIsNotNone(settings)
        # Value should not have changed from initial
        self.assertEqual(settings.max_booking_days_in_future, 30)
        self.logout()

    def test_admin_booking_settings_field_state(self):
        """Test the HTML structure and JS setup for past booking adjustment field enabled/disabled state."""
        admin = self._create_admin_user(username="settingsadmin_fieldstate", email_ext="settings_fieldstate")
        self.login(admin.username, 'adminpass')

        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings()
            db.session.add(settings)

        # Scenario A: allow_past_bookings is False (adjustment input should be ENABLED)
        settings.allow_past_bookings = False
        settings.past_booking_time_adjustment_hours = 5 # This value should be present
        db.session.commit()

        response_a = self.client.get('/admin/booking_settings')
        self.assertEqual(response_a.status_code, 200)
        html_a = response_a.data.decode('utf-8')

        self.assertIn('id="allow_past_bookings"', html_a)
        self.assertNotIn('id="allow_past_bookings" checked', html_a)
        # Check that the input field for past_booking_time_adjustment_hours does NOT have 'disabled'
        self.assertIn('id="past_booking_time_adjustment_hours"', html_a)
        self.assertNotIn('id="past_booking_time_adjustment_hours" disabled', html_a.replace(' disabled=""', ' disabled'))
        self.assertIn('name="past_booking_time_adjustment_hours" value="5"', html_a)

        # Scenario B: allow_past_bookings is True (adjustment input should be DISABLED)
        settings.allow_past_bookings = True
        settings.past_booking_time_adjustment_hours = -2
        db.session.commit()

        response_b = self.client.get('/admin/booking_settings')
        self.assertEqual(response_b.status_code, 200)
        html_b = response_b.data.decode('utf-8')

        self.assertIn('id="allow_past_bookings" checked', html_b)
        # Check that the input field for past_booking_time_adjustment_hours HAS 'disabled'
        self.assertIn('id="past_booking_time_adjustment_hours" name="past_booking_time_adjustment_hours" value="-2" class="form-control" disabled', html_b.replace(' disabled=""', ' disabled'))

        # Verify JavaScript snippet for toggling 'disabled' property is present and seems correct
        self.assertIn("var allowPastBookingsCheckbox = document.getElementById('allow_past_bookings');", html_b)
        self.assertIn("var adjustmentInput = document.getElementById('past_booking_time_adjustment_hours');", html_b)
        self.assertIn("function updatePastBookingAdjustmentFieldState() {", html_b) # Renamed function
        self.assertIn("if (allowPastBookingsCheckbox.checked)", html_b)
        self.assertIn("adjustmentInput.disabled = true;", html_b)
        self.assertIn("} else {", html_b)
        self.assertIn("adjustmentInput.disabled = false;", html_b)
        self.assertIn("updatePastBookingAdjustmentFieldState();", html_b) # Initial call
        self.assertIn("allowPastBookingsCheckbox.addEventListener('change', updatePastBookingAdjustmentFieldState);", html_b)

        self.logout()


class TestAdminBookingCancellation(TestAdminBookings):
    def setUp(self):
        super().setUp()
        # The _create_admin_user from TestAdminBookings should be sufficient
        # as it creates an admin with 'Administrator' role which has 'all_permissions'
        # including 'manage_bookings'.
        self.admin_user = self._create_admin_user(username="cancel_admin", email_ext="cancel_admin")
        self.login(self.admin_user.username, "adminpass")

    def test_admin_cancel_booking_success(self):
        """Test successful cancellation of a booking by an admin with a reason."""
        # Create a regular user
        user_to_book = User.query.filter_by(username='testuser').first()
        if not user_to_book: # Should exist from AppTests.setUp
            user_to_book = User(username='testuser', email='test@example.com')
            user_to_book.set_password('password')
            db.session.add(user_to_book)
            db.session.commit()

        # Create a booking for the user
        booking = self._create_booking(
            user_name=user_to_book.username,
            resource_id=self.resource1.id,
            start_offset_hours=24, # Future booking
            title="Booking to be Cancelled by Admin"
        )
        booking_id = booking.id
        original_user_email = user_to_book.email

        # Admin cancels the booking
        cancellation_reason = "Admin cancelled for testing purposes."
        response = self.client.post(f'/api/admin/bookings/{booking_id}/cancel_by_admin',
                                     json={'reason': cancellation_reason})

        self.assertEqual(response.status_code, 200, f"API call failed: {response.get_data(as_text=True)}")
        response_data = response.get_json()
        self.assertEqual(response_data.get('message'), 'Booking cancelled successfully.')
        self.assertEqual(response_data.get('new_status'), 'cancelled_by_admin')
        self.assertEqual(response_data.get('admin_message'), cancellation_reason)

        # Fetch booking from DB and assert changes
        cancelled_booking_db = Booking.query.get(booking_id)
        self.assertIsNotNone(cancelled_booking_db)
        self.assertEqual(cancelled_booking_db.status, 'cancelled_by_admin')
        self.assertEqual(cancelled_booking_db.admin_deleted_message, cancellation_reason)

        # Check for AuditLog entry
        audit_log = AuditLog.query.filter_by(action="ADMIN_CANCEL_BOOKING", user_id=self.admin_user.id).order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log, "ADMIN_CANCEL_BOOKING audit log not found.")
        self.assertIn(f"Admin '{self.admin_user.username}' CANCELLED booking ID {booking_id}", audit_log.details)
        self.assertIn(f"Reason: '{cancellation_reason}'", audit_log.details) # Verify custom reason

        # Check for email notification (inspect utils.email_log)
        self.assertTrue(len(email_log) >= 1, "No email was logged.")
        last_email = email_log[-1]
        self.assertEqual(last_email['to'], original_user_email)
        self.assertEqual(last_email['subject'], 'Booking Cancelled by Admin')
        self.assertIn(f"Your booking for '{self.resource1.name}'", last_email['body'])
        self.assertIn(f"has been cancelled by an administrator. Reason: {cancellation_reason}", last_email['body']) # Verify custom reason

        # --- Enhancement: Call clear_admin_message and verify ---
        # Ensure email_log is cleared or count emails before this step if sensitive to new emails from clear_admin_message
        # For this test, we are primarily focused on the status and audit log of clear_admin_message.

        clear_message_response = self.client.post(f'/api/admin/bookings/{booking_id}/clear_admin_message')
        self.assertEqual(clear_message_response.status_code, 200, f"Clear admin message failed: {clear_message_response.get_data(as_text=True)}")
        clear_message_data = clear_message_response.get_json()
        self.assertEqual(clear_message_data.get('message'), 'Admin message cleared and booking acknowledged.')
        self.assertEqual(clear_message_data.get('new_status'), 'cancelled_admin_acknowledged')

        # Fetch booking from DB again and verify updated status and cleared message
        cleared_booking_db = Booking.query.get(booking_id)
        self.assertIsNotNone(cleared_booking_db)
        self.assertEqual(cleared_booking_db.status, 'cancelled_admin_acknowledged')
        self.assertIsNone(cleared_booking_db.admin_deleted_message)

        # Verify new audit log entry for "ADMIN_CLEAR_BOOKING_MESSAGE"
        clear_audit_log = AuditLog.query.filter_by(action="ADMIN_CLEAR_BOOKING_MESSAGE", user_id=self.admin_user.id).order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(clear_audit_log, "ADMIN_CLEAR_BOOKING_MESSAGE audit log not found.")
        self.assertIn(f"Admin '{self.admin_user.username}' cleared cancellation message for booking ID {booking_id}", clear_audit_log.details)
        self.assertIn("Status changed to 'cancelled_admin_acknowledged'", clear_audit_log.details)


    def test_admin_cancel_booking_success_default_reason(self):
        """Test successful cancellation with default reason."""
        user_to_book = User.query.filter_by(username='testuser').first()
        booking = self._create_booking(user_name=user_to_book.username, resource_id=self.resource1.id, start_offset_hours=24)
        booking_id = booking.id
        original_user_email = user_to_book.email # For email check

        response = self.client.post(f'/api/admin/bookings/{booking_id}/cancel_by_admin', json={}) # No reason in payload
        self.assertEqual(response.status_code, 200)
        response_data = response.get_json()
        self.assertEqual(response_data.get('new_status'), 'cancelled_by_admin')
        self.assertIsNone(response_data.get('admin_message')) # Should be None

        cancelled_booking_db = Booking.query.get(booking_id)
        self.assertIsNone(cancelled_booking_db.admin_deleted_message) # Should be None in DB

        # Audit Log Check
        audit_log = AuditLog.query.filter_by(action="ADMIN_CANCEL_BOOKING", user_id=self.admin_user.id).order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log, "ADMIN_CANCEL_BOOKING audit log not found.")
        self.assertIn(f"Admin '{self.admin_user.username}' CANCELLED booking ID {booking_id}", audit_log.details)
        self.assertIn("Reason: 'N/A'", audit_log.details) # Check for N/A placeholder

        # Email Log Check
        self.assertTrue(len(email_log) >= 1, "No email was logged for default reason cancellation.")
        last_email = email_log[-1]
        self.assertEqual(last_email['to'], original_user_email)
        self.assertEqual(last_email['subject'], 'Booking Cancelled by Admin')
        self.assertIn("No specific reason was provided.", last_email['body'])
        self.assertNotIn("Reason: Cancelled by admin.", last_email['body']) # Ensure old default isn't there
        self.assertNotIn("Reason: N/A", last_email['body']) # Ensure "N/A" isn't in email, but "No specific reason..."

    def test_admin_cancel_booking_already_terminal_status(self):
        """Test cancelling a booking that is already in a terminal state."""
        user_to_book = User.query.filter_by(username='testuser').first()
        booking = self._create_booking(user_name=user_to_book.username, resource_id=self.resource1.id, start_offset_hours=24)
        booking_id = booking.id

        # Set status to 'completed'
        booking.status = 'completed'
        db.session.commit()

        response = self.client.post(f'/api/admin/bookings/{booking_id}/cancel_by_admin', json={'reason': 'Test terminal'})
        self.assertEqual(response.status_code, 400)
        response_data = response.get_json()
        self.assertIn("already in a state ('completed') that cannot be cancelled by admin", response_data.get('error', ''))

        # Verify booking status remains unchanged
        db.session.refresh(booking)
        self.assertEqual(booking.status, 'completed')

    def test_admin_cancel_booking_not_found(self):
        """Test cancelling a non-existent booking."""
        non_existent_booking_id = 99999
        response = self.client.post(f'/api/admin/bookings/{non_existent_booking_id}/cancel_by_admin', json={'reason': 'Test not found'})
        self.assertEqual(response.status_code, 404)
        self.assertIn('Booking not found', response.get_json().get('error', ''))

    def test_admin_cancel_booking_no_permission(self):
        """Test cancelling a booking without 'manage_bookings' permission."""
        user_to_book = User.query.filter_by(username='testuser').first()
        booking = self._create_booking(user_name=user_to_book.username, resource_id=self.resource1.id, start_offset_hours=24)
        booking_id = booking.id

        # Log out admin, log in as non-admin
        self.logout()
        non_admin_user = User(username='nonadmin_cancel', email='nonadmin_cancel@example.com', is_admin=False)
        non_admin_user.set_password('password')
        db.session.add(non_admin_user)
        db.session.commit()
        self.login(non_admin_user.username, 'password')

        response = self.client.post(f'/api/admin/bookings/{booking_id}/cancel_by_admin', json={'reason': 'Test no permission'})
        self.assertEqual(response.status_code, 403) # Forbidden
        self.assertIn("You do not have the required permissions ('manage_bookings')", response.get_json().get('error', ''))

        # Log back in as admin for subsequent tests in this class
        self.logout()
        self.login(self.admin_user.username, "adminpass")


    def test_resource_availability_after_admin_cancellation(self):
        """Test that a resource becomes available after admin cancellation and can be booked by another user."""
        # Preamble: Isolate Resource and Reset BookingSettings
        unique_resource_name = f"TestResAvailability_{datetime.utcnow().timestamp()}"
        test_resource = Resource(name=unique_resource_name, capacity=1, status='published')
        db.session.add(test_resource)
        db.session.commit()

        BookingSettings.query.delete()
        db.session.add(BookingSettings()) # Add default settings
        db.session.commit()

        # Admin user is already logged in from setUp

        # Create user_A
        user_a = User.query.filter_by(username='user_a_avail_test').first()
        if not user_a:
            user_a = User(username='user_a_avail_test', email='usera_avail@example.com')
            user_a.set_password('password')
            db.session.add(user_a)
            db.session.commit()

        # Define precise booking time (2 days in the future)
        booking_date = date.today() + timedelta(days=2)
        booking_start_time_obj = time(10, 0) # 10:00 AM
        booking_end_time_obj = time(11, 0)   # 11:00 AM

        booking_start_dt = datetime.combine(booking_date, booking_start_time_obj)
        booking_end_dt = datetime.combine(booking_date, booking_end_time_obj)

        # Admin creates booking_A for user_A on the isolated resource
        # (Using direct model creation as admin is logged in, could also use API if preferred)
        booking_A = Booking(
            user_name=user_a.username,
            resource_id=test_resource.id,
            start_time=booking_start_dt,
            end_time=booking_end_dt,
            title="Booking A for Availability Test",
            status="approved"
        )
        db.session.add(booking_A)
        db.session.commit()
        booking_A_id = booking_A.id
        # Log details of Booking A for debugging if test fails
        booking_A_details_for_log = f"Booking A (ID: {booking_A.id}, Status: {booking_A.status}, Start: {booking_A.start_time}, End: {booking_A.end_time}, Resource: {booking_A.resource_id})"


        # Admin cancels user_A's booking
        cancel_reason = "Testing resource release after admin cancellation."
        cancel_response = self.client.post(f'/api/admin/bookings/{booking_A_id}/cancel_by_admin',
                                           json={'reason': cancel_reason})
        self.assertEqual(cancel_response.status_code, 200,
                         f"Admin cancellation of Booking A failed: {cancel_response.get_data(as_text=True)}")

        # Fetch booking_A from DB and assert its status
        db.session.refresh(booking_A) # Refresh from DB
        self.assertEqual(booking_A.status, 'cancelled_by_admin',
                         "Booking A status was not updated to 'cancelled_by_admin'.")
        app.logger.info(f"Admin Cancelled Booking A: {booking_A_details_for_log}, new status: {booking_A.status}")


        # Admin logs out
        logout_response = self.logout()
        self.assertEqual(logout_response.status_code, 200, "Admin logout failed.")
        auth_status_after_admin_logout = self.client.get('/api/auth/status').get_json()
        self.assertFalse(auth_status_after_admin_logout.get('logged_in'), "Admin user should be logged out.")

        # Create user_B
        user_b = User.query.filter_by(username='user_b_avail_test').first()
        if not user_b:
            user_b = User(username='user_b_avail_test', email='userb_avail@example.com')
            user_b.set_password('password')
            db.session.add(user_b)
            db.session.commit()

        # Log in user_B and verify
        login_resp_user_b = self.login(user_b.username, 'password')
        self.assertEqual(login_resp_user_b.status_code, 200,
                         f"Login for user_B failed: {login_resp_user_b.get_data(as_text=True)}")
        auth_status_user_b = self.client.get('/api/auth/status').get_json()
        self.assertTrue(auth_status_user_b.get('logged_in'), "User_B should be logged in.")
        self.assertEqual(auth_status_user_b.get('user', {}).get('username'), user_b.username, "Logged in user is not User_B.")

        # Detailed DB Query & Logging for active conflicting bookings
        non_terminal_statuses = ['pending', 'approved', 'confirmed', 'checked_in'] # Statuses considered active/blocking

        # Query for any bookings on the specific resource and time that are NOT in a terminal/cancelled state
        active_conflicting_bookings_query = Booking.query.filter(
            Booking.resource_id == test_resource.id,
            Booking.start_time < booking_end_dt,
            Booking.end_time > booking_start_dt,
            Booking.status.in_(non_terminal_statuses)
        )
        active_conflicting_bookings = active_conflicting_bookings_query.all()

        unexpected_active_bookings_details = []
        if active_conflicting_bookings:
            for b in active_conflicting_bookings:
                unexpected_active_bookings_details.append(
                    f"ID: {b.id}, Status: {b.status}, User: {b.user_name}, Start: {b.start_time}, End: {b.end_time}"
                )
            app.logger.info(f"Unexpected active bookings found before User B attempts re-booking: {unexpected_active_bookings_details}")

        self.assertEqual(len(active_conflicting_bookings), 0,
                         f"Resource slot should be free for User B. Found unexpected active/conflicting bookings: {unexpected_active_bookings_details}. Original Booking A details: {booking_A_details_for_log}")

        # User_B attempts to create a new booking (booking_B) on the isolated resource for the exact same time slot
        new_booking_payload = {
            'resource_id': test_resource.id,
            'date_str': booking_start_dt.strftime('%Y-%m-%d'),
            'start_time_str': booking_start_dt.strftime('%H:%M'),
            'end_time_str': booking_end_dt.strftime('%H:%M'),
            'title': "Booking B by User B After Admin Cancellation",
            'user_name': user_b.username
        }
        new_booking_response = self.client.post('/api/bookings', json=new_booking_payload)

        # Assertion for Re-booking
        response_json_on_fail = {}
        if new_booking_response.content_type == 'application/json':
            response_json_on_fail = new_booking_response.get_json()

        failure_message = (
            f"New booking creation by User B failed. Expected 201, Got: {new_booking_response.status_code}. "
            f"API Error: {response_json_on_fail.get('error', 'No JSON error message.')}. "
            f"Original Booking A details: {booking_A_details_for_log}. "
            f"Unexpected active bookings found before this attempt: {unexpected_active_bookings_details if unexpected_active_bookings_details else 'None'}."
        )
        self.assertEqual(new_booking_response.status_code, 201, failure_message)

        # Verify user_B's booking exists in the DB
        if new_booking_response.status_code == 201:
            booking_B_data = new_booking_response.get_json()['bookings'][0]
            booking_B_id = booking_B_data['id']
            booking_B_db = Booking.query.get(booking_B_id)
            self.assertIsNotNone(booking_B_db, "User B's booking (Booking B) was not found in DB after supposedly successful creation.")
            self.assertEqual(booking_B_db.user_name, user_b.username)
            self.assertEqual(booking_B_db.resource_id, test_resource.id)
            self.assertEqual(booking_B_db.start_time, booking_start_dt)
            self.assertEqual(booking_B_db.status, 'approved') # Default status for new bookings

        # Log back in as admin for subsequent tests in this class (if any, or for teardown consistency)
        self.logout()
        self.login(self.admin_user.username, "adminpass") # self.admin_user is from TestAdminBookingCancellation setUp

    def test_same_user_can_rebook_after_admin_cancellation(self):
        """Test if the same user can re-book a slot after their original booking for that slot was cancelled by an admin."""
        with self.app_context: # Ensure app context for DB operations
            # 1. Setup Resource and User A
            isolated_resource_name = f"SameUserRebookTestRes_{datetime.utcnow().timestamp()}"
            # Ensure status is published or whatever status allows booking by default in your app
            isolated_resource = Resource(name=isolated_resource_name, status='published')
            db.session.add(isolated_resource)
            db.session.commit()

            user_a_username = f"surb_user_{datetime.utcnow().timestamp()}"
            user_a_email = f"surb_{datetime.utcnow().timestamp()}@example.com"
            user_a = User(username=user_a_username, email=user_a_email, is_admin=False, is_active=True)
            user_a.set_password('password')
            db.session.add(user_a)
            db.session.commit()

            # 2. User A Books Slot
            login_response = self.login(user_a_username, 'password')
            self.assertEqual(login_response.status_code, 200, f"Failed to log in user_A. Response: {login_response.get_data(as_text=True)}")

            # Define a future, bookable slot
            booking_start_dt = datetime.utcnow().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=3)
            if booking_start_dt.weekday() >= 5: # Saturday (5) or Sunday (6)
                booking_start_dt += timedelta(days=(7 - booking_start_dt.weekday())) # Move to next Monday

            booking_end_dt = booking_start_dt + timedelta(hours=1)
            # Use correct keys for payload as expected by /api/bookings
            date_str = booking_start_dt.strftime('%Y-%m-%d')
            start_time_str = booking_start_dt.strftime('%H:%M')
            end_time_str = booking_end_dt.strftime('%H:%M')

            booking_payload_user_a = {
                'resource_id': isolated_resource.id,
                'date': date_str, # Corrected key
                'start_time': start_time_str, # Corrected key
                'end_time': end_time_str, # Corrected key
                'title': 'User A Initial Booking',
                'user_name': user_a_username
            }
            response_book_a = self.client.post('/api/bookings', json=booking_payload_user_a)
            # Check if booking was successful
            self.assertEqual(response_book_a.status_code, 201, f"User A initial booking failed. Response: {response_book_a.get_data(as_text=True)}, Payload: {booking_payload_user_a}")
            booking_a_id = response_book_a.json['bookings'][0]['id'] # Assuming API returns list of bookings
            self.logout()

            # 3. Admin Cancels User A's Booking
            admin_login_response = self.login(self.admin_user.username, 'adminpass') # Use self.admin_user
            self.assertEqual(admin_login_response.status_code, 200, "Admin login failed")

            cancel_response = self.client.post(f'/api/admin/bookings/{booking_a_id}/cancel_by_admin', json={}) # No reason needed
            self.assertEqual(cancel_response.status_code, 200, f"Admin cancellation failed. Response: {cancel_response.get_data(as_text=True)}")

            cancelled_booking = Booking.query.get(booking_a_id)
            self.assertIsNotNone(cancelled_booking, "Cancelled booking not found in DB")
            self.assertEqual(cancelled_booking.status, 'cancelled_by_admin')
            self.assertIsNone(cancelled_booking.admin_deleted_message) # Default reason is None
            self.logout()

            # 4. User A Attempts to Re-book Same Slot
            login_response_user_a_again = self.login(user_a_username, 'password')
            self.assertEqual(login_response_user_a_again.status_code, 200, "User A re-login failed")

            rebooking_payload_user_a = { # Use the same details
                'resource_id': isolated_resource.id,
                'date': date_str,
                'start_time': start_time_str,
                'end_time': end_time_str,
                'title': 'User A Re-Booking Attempt', # New title for clarity
                'user_name': user_a_username
            }
            response_rebook_a = self.client.post('/api/bookings', json=rebooking_payload_user_a)

            # 5. Assert Re-booking Success
            detailed_failure_message = (
                f"Re-booking failed with status {response_rebook_a.status_code}. Expected 201.\n"
                f"API Response: {response_rebook_a.get_data(as_text=True)}\n"
                f"Original booking ID {booking_a_id} was cancelled. Its status was '{cancelled_booking.status}'.\n"
                f"Attempted to re-book slot: Start={booking_start_dt.isoformat()}, End={booking_end_dt.isoformat()} "
                f"for User={user_a_username} on Resource={isolated_resource.id}"
            )
            self.assertEqual(response_rebook_a.status_code, 201, detailed_failure_message)

            if response_rebook_a.status_code == 201:
                new_booking_id = response_rebook_a.json['bookings'][0]['id']
                new_booking = Booking.query.get(new_booking_id)
                self.assertIsNotNone(new_booking, "New booking not found in DB after successful re-booking.")
                self.assertEqual(new_booking.user_id, user_a.id) # Check user_id association
                self.assertIn(new_booking.status, ['pending', 'approved'], "New booking status is not 'pending' or 'approved'.")
                self.assertNotEqual(new_booking.id, booking_a_id, "New booking ID should not be the same as the cancelled one.")

            self.logout()


class TestApiMapsAvailability(AppTests):
    def setUp(self):
        super().setUp()
        self.admin_user = User(username='map_avail_admin', email='map_avail_admin@example.com', is_admin=True)
        self.admin_user.set_password('adminpass')
        db.session.add(self.admin_user)

        self.test_booker = User(username='map_avail_booker', email='map_avail_booker@example.com', is_admin=False)
        self.test_booker.set_password('password')
        db.session.add(self.test_booker)

        self.test_map = FloorMap(name="Map Availability Test Map", image_filename="map_avail.png")
        db.session.add(self.test_map)
        db.session.commit() # Commit users and map to get IDs

        self.res1_on_map = Resource(name="Res1_MapAvail", status="published", floor_map_id=self.test_map.id, capacity=10)
        self.res2_on_map = Resource(name="Res2_MapAvail", status="published", floor_map_id=self.test_map.id, capacity=5)
        db.session.add_all([self.res1_on_map, self.res2_on_map])
        db.session.commit() # Commit resources to get IDs

        self.primary_slots = [(dt_time(8, 0), dt_time(12, 0)), (dt_time(13, 0), dt_time(17, 0))]

        self.login(self.admin_user.username, 'adminpass')

    def _create_booking_at_slot(self, resource_id, user_obj, target_date, time_slot, title, status='approved'):
        start_dt = datetime.combine(target_date, time_slot[0])
        end_dt = datetime.combine(target_date, time_slot[1])
        booking = Booking(
            resource_id=resource_id,
            user_name=user_obj.username,
            start_time=start_dt,
            end_time=end_dt,
            title=title,
            status=status
        )
        db.session.add(booking)
        # db.session.commit() # Commit is handled by the test method after all bookings for a scenario are added
        return booking

    def test_maps_availability_reflects_cancellations(self):
        target_date = date.today() + timedelta(days=7)
        target_date_str = target_date.strftime("%Y-%m-%d")

        # Scenario for self.res1_on_map
        self._create_booking_at_slot(self.res1_on_map.id, self.test_booker, target_date, self.primary_slots[0], "Approved Booking Res1", status='approved')
        self._create_booking_at_slot(self.res1_on_map.id, self.test_booker, target_date, self.primary_slots[1], "Admin Cancelled Res1", status='cancelled_by_admin')
        db.session.commit() # Commit bookings for res1

        # self.res2_on_map has no bookings for this date

        response = self.client.get(f'/api/maps-availability?date={target_date_str}')
        self.assertEqual(response.status_code, 200, f"API call failed: {response.get_data(as_text=True)}")

        data = response.get_json()
        map_data = next((m for m in data if m['id'] == self.test_map.id), None)
        self.assertIsNotNone(map_data, f"Test map ID {self.test_map.id} not found in API response: {data}")

        # Expected calculations:
        # res1: 2 total primary slots, 1 available (cancelled_by_admin slot is available)
        # res2: 2 total primary slots, 2 available (no bookings)
        # Total for map: 4 total primary slots, 3 available primary slots
        expected_total_slots = len(self.primary_slots) * 2 # 2 resources
        expected_available_slots = 1 + len(self.primary_slots) # 1 from res1, 2 from res2

        self.assertEqual(map_data.get('total_primary_slots'), expected_total_slots, "Mismatch in total_primary_slots")
        self.assertEqual(map_data.get('available_primary_slots_for_user'), expected_available_slots, "Mismatch in available_primary_slots_for_user")

        availability_percentage = (expected_available_slots / expected_total_slots) * 100 if expected_total_slots > 0 else 0
        expected_status = 'low'
        if availability_percentage >= 50:
            expected_status = 'high'
        elif availability_percentage > 0:
            expected_status = 'medium'

        self.assertEqual(map_data.get('availability_status'), expected_status, f"Expected status {expected_status} for {availability_percentage}% availability")

    def test_maps_availability_with_completed_bookings(self):
        target_date = date.today() + timedelta(days=8) # Different date for isolation
        target_date_str = target_date.strftime("%Y-%m-%d")

        # Scenario for self.res1_on_map
        self._create_booking_at_slot(self.res1_on_map.id, self.test_booker, target_date, self.primary_slots[0], "Approved Res1 Completed Test", status='approved')
        self._create_booking_at_slot(self.res1_on_map.id, self.test_booker, target_date, self.primary_slots[1], "Completed Res1", status='completed')
        db.session.commit() # Commit bookings for res1

        # self.res2_on_map has no bookings

        response = self.client.get(f'/api/maps-availability?date={target_date_str}')
        self.assertEqual(response.status_code, 200, f"API call failed: {response.get_data(as_text=True)}")

        data = response.get_json()
        map_data = next((m for m in data if m['id'] == self.test_map.id), None)
        self.assertIsNotNone(map_data, f"Test map ID {self.test_map.id} not found in API response: {data}")

        # Expected calculations:
        # res1: 2 total primary slots, 1 available (completed slot is available)
        # res2: 2 total primary slots, 2 available
        # Total for map: 4 total primary slots, 3 available
        expected_total_slots = len(self.primary_slots) * 2
        expected_available_slots = 1 + len(self.primary_slots)

        self.assertEqual(map_data.get('total_primary_slots'), expected_total_slots, "Mismatch in total_primary_slots for completed test")
        self.assertEqual(map_data.get('available_primary_slots_for_user'), expected_available_slots, "Mismatch in available_primary_slots_for_user for completed test")

        availability_percentage = (expected_available_slots / expected_total_slots) * 100 if expected_total_slots > 0 else 0
        expected_status = 'low'
        if availability_percentage >= 50:
            expected_status = 'high'
        elif availability_percentage > 0:
            expected_status = 'medium'

        self.assertEqual(map_data.get('availability_status'), expected_status, f"Expected status {expected_status} for {availability_percentage}% availability in completed test")

    def test_get_my_bookings_for_date_filters_statuses(self):
        """
        Tests that /api/bookings/my_bookings_for_date correctly filters bookings by active statuses.
        """
        self.logout() # Log out admin
        login_resp = self.login(self.test_booker.username, 'password') # Log in as test_booker
        self.assertEqual(login_resp.status_code, 200)

        target_date = date.today() + timedelta(days=12)
        target_date_str = target_date.strftime("%Y-%m-%d")

        # Bookings for self.test_booker
        b_approved = self._create_booking_at_slot(
            self.res1_on_map.id, self.test_booker, target_date, self.primary_slots[0],
            'Approved MyBookingDate', status='approved'
        )
        b_cancelled = self._create_booking_at_slot(
            self.res1_on_map.id, self.test_booker, target_date, self.primary_slots[1],
            'Cancelled MyBookingDate', status='cancelled_by_admin'
        )
        # Use res2_on_map for other statuses to avoid exact slot overlaps if helper doesn't vary times enough
        b_completed = self._create_booking_at_slot(
            self.res2_on_map.id, self.test_booker, target_date, self.primary_slots[0],
            'Completed MyBookingDate OtherRes', status='completed'
        )
        b_pending = self._create_booking_at_slot(
            self.res2_on_map.id, self.test_booker, target_date, self.primary_slots[1],
            'Pending MyBookingDate OtherRes', status='pending'
        )
        db.session.commit()

        response = self.client.get(f'/api/bookings/my_bookings_for_date?date={target_date_str}')
        self.assertEqual(response.status_code, 200, f"API call failed: {response.get_data(as_text=True)}")

        bookings_list = response.get_json()
        self.assertIsInstance(bookings_list, list, "Response should be a list of bookings.")

        # Expected: 'approved' and 'pending'
        self.assertEqual(len(bookings_list), 2, f"Expected 2 active bookings, got {len(bookings_list)}. Response: {bookings_list}")

        returned_titles = {b['title'] for b in bookings_list}
        self.assertIn(b_approved.title, returned_titles)
        self.assertIn(b_pending.title, returned_titles)
        self.assertNotIn(b_cancelled.title, returned_titles)
        self.assertNotIn(b_completed.title, returned_titles)

        self.logout() # Log out test_booker
        self.login(self.admin_user.username, 'adminpass') # Log admin back in for subsequent tests

    def test_get_resource_availability_filters_statuses(self):
        """
        Tests that /api/resources/<id>/availability correctly filters bookings by active statuses.
        """
        # Admin user is already logged in from setUp or previous test's logout/login sequence
        target_date = date.today() + timedelta(days=14)
        target_date_str = target_date.strftime("%Y-%m-%d")

        target_resource_id = self.res1_on_map.id

        # Create bookings with distinct times to ensure no overlap if helper doesn't guarantee it
        b_approved = Booking(resource_id=target_resource_id, user_name=self.test_booker.username, title='Approved ResAvail', status='approved', start_time=datetime.combine(target_date, dt_time(9,0)), end_time=datetime.combine(target_date, dt_time(10,0)))
        b_cancelled = Booking(resource_id=target_resource_id, user_name=self.test_booker.username, title='Cancelled ResAvail', status='cancelled_by_admin', start_time=datetime.combine(target_date, dt_time(10,0)), end_time=datetime.combine(target_date, dt_time(11,0)))
        b_completed = Booking(resource_id=target_resource_id, user_name=self.test_booker.username, title='Completed ResAvail', status='completed', start_time=datetime.combine(target_date, dt_time(11,0)), end_time=datetime.combine(target_date, dt_time(12,0)))
        b_pending = Booking(resource_id=target_resource_id, user_name=self.test_booker.username, title='Pending ResAvail', status='pending', start_time=datetime.combine(target_date, dt_time(13,0)), end_time=datetime.combine(target_date, dt_time(14,0)))
        db.session.add_all([b_approved, b_cancelled, b_completed, b_pending])
        db.session.commit()

        response = self.client.get(f'/api/resources/{target_resource_id}/availability?date={target_date_str}')
        self.assertEqual(response.status_code, 200, f"API call failed: {response.get_data(as_text=True)}")

        bookings_data = response.get_json()
        self.assertIsInstance(bookings_data, list, "Response should be a list of booking slots.")

        # Expected: 'approved' and 'pending'
        self.assertEqual(len(bookings_data), 2, f"Expected 2 active bookings, got {len(bookings_data)}. Response: {bookings_data}")

        returned_titles = {b['title'] for b in bookings_data}
        self.assertIn(b_approved.title, returned_titles)
        self.assertIn(b_pending.title, returned_titles)
        self.assertNotIn(b_cancelled.title, returned_titles)
        self.assertNotIn(b_completed.title, returned_titles)

    def test_get_map_details_filters_statuses_correctly(self):
        """
        Tests that the /api/map_details/<map_id> endpoint correctly filters bookings
        based on their status, only returning active ones.
        """
        target_date = date.today() + timedelta(days=10)
        target_date_str = target_date.strftime("%Y-%m-%d")

        test_resource_on_map = self.res1_on_map # Use one of the resources from setUp

        # Define booking times for clarity
        time_slot1 = (dt_time(9, 0), dt_time(10, 0))
        time_slot2 = (dt_time(10, 0), dt_time(11, 0))
        time_slot3 = (dt_time(11, 0), dt_time(12, 0))
        time_slot4 = (dt_time(13, 0), dt_time(14, 0))

        # Create bookings with various statuses
        booking_approved = self._create_booking_at_slot(
            test_resource_on_map.id, self.test_booker, target_date, time_slot1, "Approved Booking For Map Detail", status='approved'
        )
        booking_cancelled = self._create_booking_at_slot(
            test_resource_on_map.id, self.test_booker, target_date, time_slot2, "Cancelled By Admin For Map Detail", status='cancelled_by_admin'
        )
        booking_completed = self._create_booking_at_slot(
            test_resource_on_map.id, self.test_booker, target_date, time_slot3, "Completed Booking For Map Detail", status='completed'
        )
        booking_pending = self._create_booking_at_slot(
            test_resource_on_map.id, self.test_booker, target_date, time_slot4, "Pending Booking For Map Detail", status='pending'
        )
        db.session.commit()

        # API Call
        response = self.client.get(f'/api/map_details/{self.test_map.id}?date={target_date_str}')
        self.assertEqual(response.status_code, 200, f"API call failed: {response.get_data(as_text=True)}")

        # Assertions
        data = response.get_json()

        mapped_resources_data = data.get('mapped_resources', [])
        resource_data_from_api = next((r for r in mapped_resources_data if r['id'] == test_resource_on_map.id), None)

        self.assertIsNotNone(resource_data_from_api, f"Resource ID {test_resource_on_map.id} not found in mapped_resources.")

        bookings_on_date_api = resource_data_from_api.get('bookings_on_date', [])

        # active_booking_statuses_for_conflict_map_details = ['approved', 'pending', 'checked_in', 'confirmed']
        # Based on this, only 'approved' and 'pending' should be returned.
        self.assertEqual(len(bookings_on_date_api), 2,
                         f"Expected 2 active bookings, but got {len(bookings_on_date_api)}. API returned: {bookings_on_date_api}")

        returned_titles = [b['title'] for b in bookings_on_date_api]

        self.assertIn(booking_approved.title, returned_titles, "Approved booking should be present.")
        self.assertIn(booking_pending.title, returned_titles, "Pending booking should be present.")
        self.assertNotIn(booking_cancelled.title, returned_titles, "Cancelled by admin booking should NOT be present.")
        self.assertNotIn(booking_completed.title, returned_titles, "Completed booking should NOT be present.")


class TestAdminBookingSettingsPINConfig(AppTests):
    def _create_admin_user(self, username="settings_pin_admin", email_ext="settings_pin_admin"):
        """Helper to create an admin user for booking settings PIN config tests."""
        admin_user = User.query.filter_by(username=username).first()
        if not admin_user:
            admin_user = User(username=username, email=f"{email_ext}@example.com", is_admin=True)
            admin_user.set_password("adminpass")
            # Ensure admin has 'manage_system_settings' or equivalent permission if specific roles are used
            # For simplicity, is_admin=True is often enough for initial access checks in tests.
            # If your app uses granular role-based permissions for settings, assign the relevant role here.
            db.session.add(admin_user)
            db.session.commit()
        return admin_user

    def get_current_booking_settings(self):
        return BookingSettings.query.first()

    def _get_base_booking_settings_form_data(self):
        """Returns a dictionary with all existing booking settings fields with default/valid values."""
        # Fetch existing settings or use defaults if none exist
        settings = self.get_current_booking_settings()
        if not settings: # Default values if no settings exist
            return {
                'allow_past_bookings': '', # Not 'on' means False
                'max_booking_days_in_future': '30',
                'allow_multiple_resources_same_time': '',
                'max_bookings_per_user': '',
                'enable_check_in_out': '',
                'past_booking_time_adjustment_hours': '0',
                'check_in_minutes_before': '15',
                'check_in_minutes_after': '15',
                # PIN settings will be overlaid by tests
            }
        return {
            'allow_past_bookings': 'on' if settings.allow_past_bookings else '',
            'max_booking_days_in_future': str(settings.max_booking_days_in_future or ''),
            'allow_multiple_resources_same_time': 'on' if settings.allow_multiple_resources_same_time else '',
            'max_bookings_per_user': str(settings.max_bookings_per_user or ''),
            'enable_check_in_out': 'on' if settings.enable_check_in_out else '',
            'past_booking_time_adjustment_hours': str(settings.past_booking_time_adjustment_hours or '0'),
            'check_in_minutes_before': str(settings.check_in_minutes_before or '15'),
            'check_in_minutes_after': str(settings.check_in_minutes_after or '15'),
        }

    def test_update_global_pin_settings_success(self):
        """Test successfully updating all global PIN settings."""
        admin = self._create_admin_user()
        self.login(admin.username, "adminpass")

        # Ensure a BookingSettings row exists
        if not self.get_current_booking_settings():
            db.session.add(BookingSettings())
            db.session.commit()

        form_data = self._get_base_booking_settings_form_data()
        form_data.update({
            'pin_auto_generation_enabled': 'on',
            'pin_length': '8',
            'pin_allow_manual_override': 'on',
            'resource_checkin_url_requires_login': 'on',
        })

        response = self.client.post(url_for('admin_ui.update_booking_settings'), data=form_data, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Booking settings updated successfully.", response.data)

        settings = self.get_current_booking_settings()
        self.assertIsNotNone(settings)
        self.assertTrue(settings.pin_auto_generation_enabled)
        self.assertEqual(settings.pin_length, 8)
        self.assertTrue(settings.pin_allow_manual_override)
        self.assertTrue(settings.resource_checkin_url_requires_login)
        self.logout()

    def test_update_global_pin_settings_pin_length_validation(self):
        """Test validation for pin_length (too short, too long, non-integer)."""
        admin = self._create_admin_user()
        self.login(admin.username, "adminpass")

        initial_settings = self.get_current_booking_settings()
        if not initial_settings:
            initial_settings = BookingSettings(pin_length=6) # Default to a valid length
            db.session.add(initial_settings)
            db.session.commit()
        initial_pin_length = initial_settings.pin_length

        test_cases = [
            ('3', f"PIN length must be between {app.config.get('MIN_PIN_LENGTH', 4)} and {app.config.get('MAX_PIN_LENGTH', 32)}."), # Too short
            ('33', f"PIN length must be between {app.config.get('MIN_PIN_LENGTH', 4)} and {app.config.get('MAX_PIN_LENGTH', 32)}."), # Too long
            ('abc', "Invalid input for PIN length. Must be an integer.") # Non-integer
        ]

        for invalid_length, error_message_part in test_cases:
            with self.subTest(pin_length=invalid_length):
                form_data = self._get_base_booking_settings_form_data()
                form_data.update({
                    'pin_auto_generation_enabled': 'on',
                    'pin_length': invalid_length, # Invalid length
                    'pin_allow_manual_override': 'on',
                    'resource_checkin_url_requires_login': 'on',
                })
                response = self.client.post(url_for('admin_ui.update_booking_settings'), data=form_data, follow_redirects=True)
                self.assertEqual(response.status_code, 200) # Lands on page again
                self.assertIn(bytes(error_message_part, 'utf-8'), response.data)

                settings_after_error = self.get_current_booking_settings()
                self.assertEqual(settings_after_error.pin_length, initial_pin_length, "PIN length should not have updated on validation error.")
        self.logout()


class TestAPIResourcePINs(AppTests):
    def _create_admin_user_and_login(self, username="pin_api_admin", password="adminpass"):
        """Creates an admin user and logs them in."""
        admin_user = User.query.filter_by(username=username).first()
        if not admin_user:
            admin_user = User(username=username, email=f"{username}@example.com", is_admin=True)
            admin_user.set_password(password)
            # Assign manage_resources permission if your app uses granular roles
            # For simplicity, is_admin=True is often sufficient for tests.
            # admin_role = Role.query.filter_by(name="Administrator").first() # Assuming Administrator role has all_permissions
            # if admin_role and admin_role not in admin_user.roles:
            # admin_user.roles.append(admin_role)
            db.session.add(admin_user)
            db.session.commit()

        login_response = self.login(username, password)
        self.assertEqual(login_response.status_code, 200, "Admin login failed in test setup.")
        self.assertTrue(login_response.get_json().get('success'), "Admin login API call was not successful.")
        return admin_user

    def _create_test_resource(self, name="Test Resource for PINs"):
        """Creates a test resource."""
        resource = Resource.query.filter_by(name=name).first()
        if not resource:
            resource = Resource(name=name, capacity=1, status='published')
            db.session.add(resource)
            db.session.commit()
        return resource

    def _set_booking_pin_settings(self, auto_enabled=True, length=6, manual_allowed=True, checkin_url_requires_login=True):
        """Configures BookingSettings for PINs."""
        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings()
            db.session.add(settings)

        settings.pin_auto_generation_enabled = auto_enabled
        settings.pin_length = length
        settings.pin_allow_manual_override = manual_allowed
        settings.resource_checkin_url_requires_login = checkin_url_requires_login
        # Add other relevant settings if needed
        db.session.commit()
        return settings

    def _add_pin_via_api(self, resource_id, pin_value=None, notes=''):
        """Helper to make the POST request for adding a PIN."""
        payload = {'notes': notes}
        if pin_value is not None:
            payload['pin_value'] = pin_value

        response = self.client.post(url_for('api_resources.add_resource_pin', resource_id=resource_id), json=payload)
        return response

    def setUp(self):
        super().setUp()
        self.admin = self._create_admin_user_and_login()
        self.resource = self._create_test_resource()
        # Default BookingSettings for PINs, can be overridden in tests
        self._set_booking_pin_settings()

    def tearDown(self):
        # It's good practice to clean up specific test data,
        # but AppTests.tearDown() drops all tables, which handles it.
        # If specific cleanup before table drop is needed, add here.
        # For example, explicitly deleting ResourcePINs or Resources if they cause issues.
        # ResourcePIN.query.delete()
        # Resource.query.filter_by(name=self.resource.name).delete()
        # BookingSettings.query.delete()
        # User.query.filter_by(username=self.admin.username).delete()
        # db.session.commit()
        super().tearDown()


    def test_add_auto_generated_pin(self):
        """Test adding an auto-generated PIN to a resource."""
        pin_len = 7
        self._set_booking_pin_settings(auto_enabled=True, length=pin_len, manual_allowed=False)

        response = self._add_pin_via_api(self.resource.id, notes='Auto-gen test')

        self.assertEqual(response.status_code, 201, f"Failed to add auto-generated PIN: {response.get_json()}")
        pin_data = response.get_json()

        self.assertIsNotNone(pin_data.get('id'))
        self.assertIsNotNone(pin_data.get('pin_value'))
        self.assertEqual(len(pin_data['pin_value']), pin_len)
        self.assertTrue(pin_data.get('is_active'))
        self.assertEqual(pin_data.get('notes'), 'Auto-gen test')

        db_pin = ResourcePIN.query.get(pin_data['id'])
        self.assertIsNotNone(db_pin)
        self.assertEqual(db_pin.pin_value, pin_data['pin_value'])
        self.assertEqual(db_pin.resource_id, self.resource.id)

        db.session.refresh(self.resource) # Refresh resource from DB
        self.assertEqual(self.resource.current_pin, db_pin.pin_value, "Resource current_pin not set to the new auto-generated PIN.")

    def test_add_manual_pin_success(self):
        """Test adding a manual PIN successfully."""
        self._set_booking_pin_settings(manual_allowed=True, auto_enabled=False)
        manual_pin_value = "MANUAL123"

        response = self._add_pin_via_api(self.resource.id, pin_value=manual_pin_value, notes='Manual test success')
        self.assertEqual(response.status_code, 201, f"Failed to add manual PIN: {response.get_json()}")
        pin_data = response.get_json()

        self.assertEqual(pin_data.get('pin_value'), manual_pin_value)
        self.assertTrue(pin_data.get('is_active'))
        self.assertEqual(pin_data.get('notes'), 'Manual test success')

        db_pin = ResourcePIN.query.filter_by(pin_value=manual_pin_value, resource_id=self.resource.id).first()
        self.assertIsNotNone(db_pin)

        db.session.refresh(self.resource)
        self.assertEqual(self.resource.current_pin, manual_pin_value)

    def test_add_manual_pin_validation(self):
        """Test validation for manual PINs (duplicate, disallowed, length)."""
        # 1. Duplicate PIN for the same resource
        self._set_booking_pin_settings(manual_allowed=True)
        duplicate_pin = "DUPLICATE1"
        self._add_pin_via_api(self.resource.id, pin_value=duplicate_pin, notes='Initial duplicate') # Add first time

        response_duplicate = self._add_pin_via_api(self.resource.id, pin_value=duplicate_pin, notes='Attempt duplicate')
        self.assertEqual(response_duplicate.status_code, 400, "Duplicate PIN should result in 400.")
        self.assertIn("PIN value 'DUPLICATE1' already exists for this resource.", response_duplicate.get_json().get('error', ''))

        # 2. Disallowed manual PIN
        self._set_booking_pin_settings(manual_allowed=False, auto_enabled=True) # Disable manual, enable auto
        response_disallowed = self._add_pin_via_api(self.resource.id, pin_value="MANUALDISALLOWED", notes='Disallowed manual')
        self.assertEqual(response_disallowed.status_code, 403, "Disallowed manual PIN should result in 403.")
        self.assertIn("Manual PIN entry is not allowed by current settings.", response_disallowed.get_json().get('error', ''))

        # 3. PIN length validation (assuming manual PINs also check BookingSettings.pin_length)
        # The add_resource_pin route has its own MIN_PIN_LENGTH and MAX_PIN_LENGTH, but also checks BookingSettings.pin_length for auto-gen
        # Let's test against the general MIN/MAX length for manual pins.
        # If BookingSettings.pin_length is meant to apply to manual pins too, the route needs adjustment.
        # Based on current `add_resource_pin` logic, manual pins are checked against fixed MIN/MAX (4-32).
        self._set_booking_pin_settings(manual_allowed=True, length=6) # Set a specific length for settings

        # Too short (manual)
        response_short = self._add_pin_via_api(self.resource.id, pin_value="123", notes='Short manual')
        self.assertEqual(response_short.status_code, 400)
        # Error message depends on whether it's compared to BookingSettings.pin_length or fixed range.
        # Current `add_resource_pin` checks `MIN_PIN_LENGTH` (4) and `MAX_PIN_LENGTH` (32) for manual.
        self.assertIn(f"Manual PIN length must be between {app.config.get('MIN_PIN_LENGTH', 4)} and {app.config.get('MAX_PIN_LENGTH', 32)} characters.", response_short.get_json().get('error', ''))

        # Too long (manual)
        response_long = self._add_pin_via_api(self.resource.id, pin_value="A"*33, notes='Long manual')
        self.assertEqual(response_long.status_code, 400)
        self.assertIn(f"Manual PIN length must be between {app.config.get('MIN_PIN_LENGTH', 4)} and {app.config.get('MAX_PIN_LENGTH', 32)} characters.", response_long.get_json().get('error', ''))


    def test_update_pin_status_and_notes(self):
        """Test updating a PIN's active status and notes."""
        self._set_booking_pin_settings(manual_allowed=True)
        # Create an initial active PIN
        add_resp = self._add_pin_via_api(self.resource.id, pin_value="PINTOUPDATE", notes='Initial PIN')
        self.assertEqual(add_resp.status_code, 201)
        pin_id = add_resp.get_json()['id']

        db.session.refresh(self.resource)
        self.assertEqual(self.resource.current_pin, "PINTOUPDATE") # Should be current

        # Deactivate and update notes
        update_payload1 = {'is_active': False, 'notes': 'Updated notes, deactivated'}
        response_update1 = self.client.put(url_for('api_resources.update_resource_pin', resource_id=self.resource.id, pin_id=pin_id), json=update_payload1)
        self.assertEqual(response_update1.status_code, 200, f"Failed to update PIN: {response_update1.get_json()}")
        updated_data1 = response_update1.get_json()
        self.assertFalse(updated_data1['is_active'])
        self.assertEqual(updated_data1['notes'], 'Updated notes, deactivated')

        db_pin1 = ResourcePIN.query.get(pin_id)
        self.assertFalse(db_pin1.is_active)
        self.assertEqual(db_pin1.notes, 'Updated notes, deactivated')

        db.session.refresh(self.resource)
        self.assertIsNone(self.resource.current_pin, "Current PIN should be cleared when the only PIN is deactivated.")

        # Add another PIN, then reactivate the first one to see current_pin behavior
        add_resp2 = self._add_pin_via_api(self.resource.id, pin_value="OTHERPIN", notes='Another active PIN')
        self.assertEqual(add_resp2.status_code, 201)
        db.session.refresh(self.resource)
        self.assertEqual(self.resource.current_pin, "OTHERPIN")


        # Reactivate the first PIN
        update_payload2 = {'is_active': True, 'notes': 'Reactivated PIN'}
        response_update2 = self.client.put(url_for('api_resources.update_resource_pin', resource_id=self.resource.id, pin_id=pin_id), json=update_payload2)
        self.assertEqual(response_update2.status_code, 200)
        updated_data2 = response_update2.get_json()
        self.assertTrue(updated_data2['is_active'])

        db_pin2 = ResourcePIN.query.get(pin_id)
        self.assertTrue(db_pin2.is_active)

        db.session.refresh(self.resource)
        # When reactivating, if another PIN ('OTHERPIN') was already current, reactivating 'PINTOUPDATE'
        # should NOT automatically make 'PINTOUPDATE' the current_pin if the logic prioritizes existing current_pin.
        # The current logic in `update_resource_pin` is:
        # If activating a PIN and resource has no current_pin, set it.
        # If deactivating the current_pin, clear it and try to set a new one.
        # So, if 'OTHERPIN' is current, reactivating 'PINTOUPDATE' shouldn't change current_pin.
        self.assertEqual(self.resource.current_pin, "OTHERPIN", "Reactivating an older PIN should not make it current if another is already current.")

        # Now, deactivate 'OTHERPIN'. 'PINTOUPDATE' (which is active) should become current.
        other_pin_id = add_resp2.get_json()['id']
        self.client.put(url_for('api_resources.update_resource_pin', resource_id=self.resource.id, pin_id=other_pin_id), json={'is_active': False})
        db.session.refresh(self.resource)
        self.assertEqual(self.resource.current_pin, "PINTOUPDATE", "PINTOUPDATE should become current after OTHERPIN is deactivated.")


    def test_get_resource_details_includes_pins(self):
        """Test that admin resource details endpoint includes associated PINs."""
        self._set_booking_pin_settings(manual_allowed=True)
        pin1_resp = self._add_pin_via_api(self.resource.id, pin_value="DETAILPIN1", notes='Detail Test 1')
        pin2_resp = self._add_pin_via_api(self.resource.id, pin_value="DETAILPIN2", notes='Detail Test 2')
        self.assertEqual(pin1_resp.status_code, 201)
        self.assertEqual(pin2_resp.status_code, 201)

        # Deactivate one PIN to test that all are returned regardless of status
        pin1_id = pin1_resp.get_json()['id']
        self.client.put(url_for('api_resources.update_resource_pin', resource_id=self.resource.id, pin_id=pin1_id), json={'is_active': False})

        response = self.client.get(url_for('api_resources.get_resource_details_admin', resource_id=self.resource.id))
        self.assertEqual(response.status_code, 200, f"Failed to get resource details: {response.get_json()}")

        details_data = response.get_json()
        self.assertIn('pins', details_data)
        self.assertIsInstance(details_data['pins'], list)
        self.assertEqual(len(details_data['pins']), 2)

        pin_values_in_response = {p['pin_value'] for p in details_data['pins']}
        self.assertIn("DETAILPIN1", pin_values_in_response)
        self.assertIn("DETAILPIN2", pin_values_in_response)

        for pin_in_list in details_data['pins']:
            self.assertIn('id', pin_in_list)
            self.assertIn('pin_value', pin_in_list)
            self.assertIn('is_active', pin_in_list)
            self.assertIn('notes', pin_in_list)
            self.assertIn('created_at', pin_in_list)
            if pin_in_list['pin_value'] == "DETAILPIN1":
                self.assertFalse(pin_in_list['is_active'])
            if pin_in_list['pin_value'] == "DETAILPIN2":
                self.assertTrue(pin_in_list['is_active'])

        # Also check current_pin is present in the main resource details
        # DETAILPIN2 should be current as DETAILPIN1 was deactivated
        self.assertEqual(details_data.get('current_pin'), "DETAILPIN2")

    def test_delete_resource_pin_success(self):
        """Test successful deletion of a resource PIN."""
        # self.admin is logged in from setUp
        # self.resource is available from setUp
        # Add a PIN to delete
        add_response = self._add_pin_via_api(self.resource.id, pin_value="PIN_TO_DELETE", notes="Test Deletion")
        self.assertEqual(add_response.status_code, 201)
        pin_data = add_response.get_json()
        pin_id_to_delete = pin_data['id']
        original_pin_value = pin_data['pin_value']

        # Make DELETE request
        delete_response = self.client.delete(f'/api/resources/{self.resource.id}/pins/{pin_id_to_delete}')
        self.assertEqual(delete_response.status_code, 200)
        delete_data = delete_response.get_json()
        self.assertEqual(delete_data['message'], 'PIN deleted successfully')
        self.assertEqual(delete_data['deleted_pin_id'], pin_id_to_delete)

        # Verify PIN is deleted from DB
        self.assertIsNone(ResourcePIN.query.get(pin_id_to_delete))

        # Verify AuditLog
        audit_log = AuditLog.query.filter_by(action="DELETE_RESOURCE_PIN", user_id=self.admin.id).order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log)
        self.assertIn(f"PIN ID {pin_id_to_delete}", audit_log.details)
        self.assertIn(f"value starting with {original_pin_value[:3]}...", audit_log.details) # Check for truncated PIN
        self.assertIn(f"resource ID {self.resource.id} ('{self.resource.name}')", audit_log.details)
        self.assertIn(f"deleted by {self.admin.username}", audit_log.details)

    def test_delete_resource_pin_updates_current_pin(self):
        """Test that resource.current_pin is updated correctly after PIN deletion."""
        # Add PIN1 (will become current)
        add_resp1 = self._add_pin_via_api(self.resource.id, pin_value="PIN1CUR", notes="PIN 1")
        self.assertEqual(add_resp1.status_code, 201)
        pin1_id = add_resp1.get_json()['id']
        pin1_value = add_resp1.get_json()['pin_value']
        db.session.refresh(self.resource)
        self.assertEqual(self.resource.current_pin, pin1_value)

        # Add PIN2 (will become current as it's newer and active by default)
        add_resp2 = self._add_pin_via_api(self.resource.id, pin_value="PIN2CUR", notes="PIN 2")
        self.assertEqual(add_resp2.status_code, 201)
        pin2_id = add_resp2.get_json()['id']
        pin2_value = add_resp2.get_json()['pin_value']
        # The _add_pin_via_api sets the new PIN as current if it's the only active one.
        # If PIN1 was active, and PIN2 is added active, current logic in add_resource_pin might not make PIN2 current
        # Let's ensure it is for the test:
        self.resource.current_pin = pin2_value
        db.session.commit()
        db.session.refresh(self.resource)
        self.assertEqual(self.resource.current_pin, pin2_value)


        # Delete PIN2 (which is current_pin)
        delete_resp2 = self.client.delete(f'/api/resources/{self.resource.id}/pins/{pin2_id}')
        self.assertEqual(delete_resp2.status_code, 200)
        db.session.refresh(self.resource)
        self.assertEqual(self.resource.current_pin, pin1_value, "current_pin should fall back to PIN1")
        self.assertEqual(delete_resp2.get_json().get('resource_current_pin'), pin1_value)


        # Delete PIN1 (which is now current_pin)
        delete_resp1 = self.client.delete(f'/api/resources/{self.resource.id}/pins/{pin1_id}')
        self.assertEqual(delete_resp1.status_code, 200)
        db.session.refresh(self.resource)
        self.assertIsNone(self.resource.current_pin, "current_pin should be None after all active PINs are deleted")
        self.assertIsNone(delete_resp1.get_json().get('resource_current_pin'))


    def test_delete_resource_pin_not_found(self):
        """Test deleting a non-existent PIN ID."""
        response = self.client.delete(f'/api/resources/{self.resource.id}/pins/99999')
        self.assertEqual(response.status_code, 404)
        self.assertIn('PIN not found', response.get_json().get('error', ''))

    def test_delete_resource_pin_wrong_resource(self):
        """Test deleting a PIN that does not belong to the specified resource."""
        resource2 = self._create_test_resource(name="Other Resource for PIN Test")
        add_pin_resp = self._add_pin_via_api(resource2.id, pin_value="PIN_FOR_RES2")
        self.assertEqual(add_pin_resp.status_code, 201)
        pin_for_resource2_id = add_pin_resp.get_json()['id']

        # Attempt to delete pin_for_resource2_id using self.resource.id in URL
        response = self.client.delete(f'/api/resources/{self.resource.id}/pins/{pin_for_resource2_id}')
        self.assertEqual(response.status_code, 404) # PIN not found *for this resource*
        self.assertIn('PIN not found for this resource', response.get_json().get('error', ''))

    def test_delete_resource_pin_no_permission(self):
        """Test deleting a PIN without 'manage_resources' permission."""
        # Create a PIN first as admin
        add_resp = self._add_pin_via_api(self.resource.id, pin_value="PIN_NO_PERM_DEL")
        self.assertEqual(add_resp.status_code, 201)
        pin_id = add_resp.get_json()['id']

        self.logout() # Log out admin

        # Create and login as non-admin user (testuser from AppTests setup)
        non_admin_login_resp = self.login('testuser', 'password')
        self.assertEqual(non_admin_login_resp.status_code, 200)
        self.assertTrue(non_admin_login_resp.get_json().get('success'))

        response = self.client.delete(f'/api/resources/{self.resource.id}/pins/{pin_id}')
        self.assertEqual(response.status_code, 403) # Forbidden
        self.assertIn('You do not have the required permissions', response.get_json().get('error', ''))

        # Verify PIN still exists
        self.assertIsNotNone(ResourcePIN.query.get(pin_id))


from unittest.mock import patch
from datetime import datetime as datetime_original, timezone as timezone_original, timedelta as timedelta_original

class TestResourceURLCheckin(AppTests):
    def _create_user_for_checkin_test(self, username="checkin_user"):
        user = User.query.filter_by(username=username).first()
        if not user:
            user = User(username=username, email=f"{username}@example.com")
            user.set_password("password")
            db.session.add(user)
            db.session.commit()
        return user

    def _create_resource_for_checkin_test(self, name="CheckinResource"):
        resource = Resource.query.filter_by(name=name).first()
        if not resource:
            resource = Resource(name=name, status="published")
            db.session.add(resource)
            db.session.commit()
        return resource

    def _create_pin_for_resource(self, resource_id, pin_value="VALIDPIN123", is_active=True):
        pin = ResourcePIN(resource_id=resource_id, pin_value=pin_value, is_active=is_active)
        db.session.add(pin)
        db.session.commit()
        # Update resource's current_pin if this is the first active one
        resource = Resource.query.get(resource_id)
        if is_active and not resource.current_pin:
            resource.current_pin = pin_value
            db.session.commit()
        return pin

    def _create_booking_for_checkin_test(self, user_id, resource_id, start_offset_hours=0, duration_hours=1, status='approved'):
        # Creates a booking relative to a fixed reference time for predictability
        # The actual "current time" will be mocked in tests.
        # Let's use a fixed date for bookings to avoid issues with month/year boundaries in tests.
        booking_start_dt = datetime_original(2024, 7, 15, 12, 0, 0) + timedelta_original(hours=start_offset_hours)
        booking_end_dt = booking_start_dt + timedelta_original(hours=duration_hours)

        user = User.query.get(user_id)
        booking = Booking(
            user_name=user.username, # Assuming user_name is sufficient for booking association in tests
            resource_id=resource_id,
            start_time=booking_start_dt,
            end_time=booking_end_dt,
            title="Checkin Test Booking",
            status=status
        )
        db.session.add(booking)
        db.session.commit()
        return booking

    def _set_checkin_booking_settings(self, requires_login=True, minutes_before=15, minutes_after=15):
        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings()
            db.session.add(settings)
        settings.resource_checkin_url_requires_login = requires_login
        settings.check_in_minutes_before = minutes_before
        settings.check_in_minutes_after = minutes_after
        settings.enable_check_in_out = True # Crucial for any check-in logic to be active
        db.session.commit()
        return settings

    def setUp(self):
        super().setUp()
        self.user = self._create_user_for_checkin_test()
        self.resource = self._create_resource_for_checkin_test()
        self.pin = self._create_pin_for_resource(self.resource.id, "VALIDPIN789")
        self.booking = self._create_booking_for_checkin_test(self.user.id, self.resource.id, start_offset_hours=0) # Starts at 2024-07-15 12:00
        self.settings = self._set_checkin_booking_settings()

    @patch('routes.api_bookings.datetime')
    def test_resource_url_checkin_success_loggedin(self, mock_datetime_obj):
        self._set_checkin_booking_settings(requires_login=True, minutes_before=15, minutes_after=15)
        self.login(self.user.username, "password")

        # Mock time to be at the start of the booking (well within 15 min before/after window)
        mocked_now = self.booking.start_time # This is a naive datetime from model
        # The route uses datetime.now(timezone.utc), so ensure mocked_now is offset-aware if comparing directly
        # or ensure mocked_now is what datetime.now(timezone.utc) will return.
        # For simplicity, if route uses .now(timezone.utc), we mock that.
        mock_datetime_obj.now.return_value = mocked_now.replace(tzinfo=timezone_original.utc)
        # If the route uses .utcnow(), then:
        # mock_datetime_obj.utcnow.return_value = mocked_now

        # Allow other datetime functions to work normally if used by the route or its helpers
        mock_datetime_obj.strptime = datetime_original.strptime
        mock_datetime_obj.combine = datetime_original.combine
        mock_datetime_obj.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs)


        response = self.client.get(f'/r/{self.resource.id}/checkin?pin={self.pin.pin_value}')
        self.assertEqual(response.status_code, 200, f"Check-in failed: {response.get_json()}")
        self.assertIn("Check-in successful", response.get_json().get('message', ''))

        db.session.refresh(self.booking)
        self.assertIsNotNone(self.booking.checked_in_at)

        audit_log = AuditLog.query.filter_by(action="CHECK_IN_VIA_RESOURCE_URL").order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log.user_id, self.user.id)
        self.assertIn(f"Booking ID {self.booking.id}", audit_log.details)
        self.assertIn(f"Resource ID {self.resource.id}", audit_log.details)
        self.assertIn(f"PIN {self.pin.pin_value} used", audit_log.details)

    @patch('routes.api_bookings.datetime')
    def test_resource_url_checkin_invalid_pin(self, mock_datetime_obj):
        self.login(self.user.username, "password")
        mock_datetime_obj.now.return_value = self.booking.start_time.replace(tzinfo=timezone_original.utc)
        mock_datetime_obj.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs)


        response = self.client.get(f'/r/{self.resource.id}/checkin?pin=INVALIDPINXYZ')
        self.assertEqual(response.status_code, 403, f"Response: {response.get_json()}")
        self.assertIn("Invalid PIN provided.", response.get_json().get('error', ''))

    @patch('routes.api_bookings.datetime')
    def test_resource_url_checkin_no_pin(self, mock_datetime_obj):
        self.login(self.user.username, "password")
        mock_datetime_obj.now.return_value = self.booking.start_time.replace(tzinfo=timezone_original.utc)
        mock_datetime_obj.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs)

        response = self.client.get(f'/r/{self.resource.id}/checkin')
        self.assertEqual(response.status_code, 400)
        self.assertIn("PIN is required for check-in.", response.get_json().get('error', ''))

    @patch('routes.api_bookings.datetime')
    def test_resource_url_checkin_inactive_pin(self, mock_datetime_obj):
        self.pin.is_active = False
        db.session.commit()
        self.login(self.user.username, "password")
        mock_datetime_obj.now.return_value = self.booking.start_time.replace(tzinfo=timezone_original.utc)
        mock_datetime_obj.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs)

        response = self.client.get(f'/r/{self.resource.id}/checkin?pin={self.pin.pin_value}')
        self.assertEqual(response.status_code, 403)
        self.assertIn("PIN is not active.", response.get_json().get('error', ''))

    @patch('routes.api_bookings.datetime')
    def test_resource_url_checkin_login_required_fail(self, mock_datetime_obj):
        self._set_checkin_booking_settings(requires_login=True)
        # DO NOT LOGIN
        mock_datetime_obj.now.return_value = self.booking.start_time.replace(tzinfo=timezone_original.utc)
        mock_datetime_obj.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs)

        response = self.client.get(f'/r/{self.resource.id}/checkin?pin={self.pin.pin_value}')
        self.assertEqual(response.status_code, 401) # Unauthorized as login is required
        self.assertIn("Login required for this check-in method.", response.get_json().get('error', ''))

    @patch('routes.api_bookings.datetime')
    def test_resource_url_checkin_login_not_required_no_user_session_fails_to_find_booking(self, mock_datetime_obj):
        self._set_checkin_booking_settings(requires_login=False)
        # Ensure no user is logged in (client is fresh or logged out)
        self.logout() # Ensure any previous session is cleared.

        mock_datetime_obj.now.return_value = self.booking.start_time.replace(tzinfo=timezone_original.utc)
        mock_datetime_obj.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs)

        response = self.client.get(f'/r/{self.resource.id}/checkin?pin={self.pin.pin_value}')
        # Even if login not required, the current logic tries to find a booking for current_user.
        # If no current_user (anonymous), it won't find self.booking which is tied to self.user.
        # This behavior is as per current implementation. A truly anonymous check-in for *any* booking
        # would require different logic.
        self.assertEqual(response.status_code, 404, f"Response: {response.get_json()}")
        self.assertIn("No active booking found for your session within the check-in window for this resource.", response.get_json().get('error', ''))

    @patch('routes.api_bookings.datetime')
    def test_resource_url_checkin_outside_window_too_early(self, mock_datetime_obj):
        self.login(self.user.username, "password")
        minutes_before = self.settings.check_in_minutes_before

        # Time is set to be 1 minute before the check-in window opens
        mocked_now = (self.booking.start_time - timedelta_original(minutes=minutes_before + 1))
        mock_datetime_obj.now.return_value = mocked_now.replace(tzinfo=timezone_original.utc)
        mock_datetime_obj.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs)


        response = self.client.get(f'/r/{self.resource.id}/checkin?pin={self.pin.pin_value}')
        self.assertEqual(response.status_code, 404) # Endpoint returns 404 if no valid booking in window
        self.assertIn("No active booking found for your session within the check-in window for this resource.", response.get_json().get('error', ''))
        # Or, if a more specific message is added for "too early/late":
        # self.assertIn("Check-in window is not open yet.", response.get_json().get('error', ''))

    @patch('routes.api_bookings.datetime')
    def test_resource_url_checkin_outside_window_too_late(self, mock_datetime_obj):
        self.login(self.user.username, "password")
        minutes_after = self.settings.check_in_minutes_after # From BookingSettings

        # Time is set to be 1 minute after the check-in window closes
        # Check-in window closes at self.booking.start_time + timedelta(minutes=minutes_after)
        # No, it's booking.end_time or booking.start_time + grace_after.
        # The route uses: valid_check_in_end = booking.start_time + timedelta(minutes=settings.check_in_minutes_after)
        mocked_now = (self.booking.start_time + timedelta_original(minutes=minutes_after + 1))
        mock_datetime_obj.now.return_value = mocked_now.replace(tzinfo=timezone_original.utc)
        mock_datetime_obj.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs)

        response = self.client.get(f'/r/{self.resource.id}/checkin?pin={self.pin.pin_value}')
        self.assertEqual(response.status_code, 404)
        self.assertIn("No active booking found for your session within the check-in window for this resource.", response.get_json().get('error', ''))
        # Or a more specific message:
        # self.assertIn("Check-in window has passed.", response.get_json().get('error', ''))

    @patch('routes.api_bookings.datetime')
    def test_resource_url_checkin_no_active_booking_found(self, mock_datetime_obj):
        self.login(self.user.username, "password")
        mock_datetime_obj.now.return_value = self.booking.start_time.replace(tzinfo=timezone_original.utc) # Time is fine
        mock_datetime_obj.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs)

        # Make the existing booking 'cancelled'
        self.booking.status = 'cancelled'
        db.session.commit()

        response = self.client.get(f'/r/{self.resource.id}/checkin?pin={self.pin.pin_value}')
        self.assertEqual(response.status_code, 404)
        self.assertIn("No active booking found for your session within the check-in window for this resource.", response.get_json().get('error', ''))

        # Test with booking already checked in
        self.booking.status = 'approved' # Reset status
        self.booking.checked_in_at = datetime_original.utcnow() - timedelta_original(minutes=5) # Checked in 5 mins ago
        db.session.commit()
        response_already_checked_in = self.client.get(f'/r/{self.resource.id}/checkin?pin={self.pin.pin_value}')
        self.assertEqual(response_already_checked_in.status_code, 400) # Or could be 200 with a message "already checked in"
        self.assertIn("Booking has already been checked in.", response_already_checked_in.get_json().get('error', ''))

    def test_resource_url_checkin_redirects_to_correct_login_when_login_required(self):
        """Test that resource URL check-in redirects to the correct login page when login is required."""
        self._set_checkin_booking_settings(requires_login=True)
        self.logout()  # Ensure client is logged out

        # Perform a GET request to the check-in URL
        response = self.client.get(f'/r/{self.resource.id}/checkin?pin={self.pin.pin_value}')

        # Assert that the status code is 401 (Unauthorized, as it renders a page indicating login is needed)
        self.assertEqual(response.status_code, 401)

        # Assert that the response data (HTML content) contains the correct login URL part
        response_data_str = response.data.decode('utf-8')
        # url_for('ui.serve_login') generates '/ui/login'
        expected_login_url_part = url_for('ui.serve_login') # This will be '/ui/login'

        # Check for the href attribute containing the login URL and the next parameter
        # Example: href="/ui/login?next=%2Fr%2F1%2Fcheckin%3Fpin%3DVALIDPIN789"
        # We need to be careful about how `next` is URL-encoded.
        # For simplicity, we'll check for the base login path and the presence of `next=`.
        self.assertIn(f'href="{expected_login_url_part}?next=', response_data_str)

        # More robust check for the next parameter pointing to the original URL
        original_url = f'/r/{self.resource.id}/checkin?pin={self.pin.pin_value}'
        # url_for encodes the `next` parameter. We should check for the encoded version.
        from urllib.parse import quote_plus
        encoded_next_url = quote_plus(original_url)
        self.assertIn(encoded_next_url, response_data_str)
        self.assertIn("Login is required to perform this check-in.", response_data_str)


class TestAPIBulkResourcePINs(AppTests):
    def _create_admin_user_and_login(self, username="bulk_pin_admin", password="adminpass"):
        """Creates an admin user and logs them in."""
        admin_user = User.query.filter_by(username=username).first()
        if not admin_user:
            admin_user = User(username=username, email=f"{username}@example.com", is_admin=True)
            admin_user.set_password(password)
            db.session.add(admin_user)
            db.session.commit()

        login_response = self.login(username, password)
        self.assertEqual(login_response.status_code, 200, "Admin login failed in test setup.")
        self.assertTrue(login_response.get_json().get('success'), "Admin login API call was not successful.")
        return admin_user

    def _create_test_resources(self, count=3, base_name="BulkPINTestRes"):
        """Creates multiple test resources."""
        resources = []
        for i in range(count):
            name = f"{base_name}_{i+1}"
            resource = Resource.query.filter_by(name=name).first()
            if not resource: # Only create if not existing from a previous failed test run for instance
                resource = Resource(name=name, capacity=1, status='published')
                db.session.add(resource)
            else: # Clear pins if resource is being reused from a dirty state
                ResourcePIN.query.filter_by(resource_id=resource.id).delete()
                resource.current_pin = None

            resources.append(resource)
        db.session.commit()
        return resources

    def _set_booking_pin_settings(self, auto_enabled=True, length=6, manual_allowed=True):
        """Configures BookingSettings for PINs."""
        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings()
            db.session.add(settings)

        settings.pin_auto_generation_enabled = auto_enabled
        settings.pin_length = length
        settings.pin_allow_manual_override = manual_allowed
        db.session.commit()
        return settings

    def _add_pin_directly_to_db(self, resource_id, pin_value, is_active=True, notes=None):
        pin = ResourcePIN(resource_id=resource_id, pin_value=pin_value, is_active=is_active, notes=notes, created_at=datetime_original.utcnow())
        db.session.add(pin)
        # db.session.commit() # Deliberately not committing here; commit in test setup after all pins for a resource
        return pin

    def _update_resource_current_pin_in_db(self, resource_obj):
        """Helper to mimic the backend's _update_resource_current_pin for verification."""
        if not resource_obj: return
        latest_active_pin = ResourcePIN.query.filter_by(
            resource_id=resource_obj.id, is_active=True
        ).order_by(ResourcePIN.created_at.desc()).first() # Match backend logic of picking latest
        resource_obj.current_pin = latest_active_pin.pin_value if latest_active_pin else None
        # db.session.commit() # Commit handled by caller if multiple resources updated

    def setUp(self):
        super().setUp()
        self.admin = self._create_admin_user_and_login()
        # Create resources within setUp to ensure they have IDs for tests
        self.resource1 = Resource(name="BPR_Res1", status='published'); db.session.add(self.resource1)
        self.resource2 = Resource(name="BPR_Res2", status='published'); db.session.add(self.resource2)
        self.resource3 = Resource(name="BPR_Res3", status='published'); db.session.add(self.resource3)
        db.session.commit()
        self.resources = [self.resource1, self.resource2, self.resource3]
        self.settings = self._set_booking_pin_settings()

    def test_bulk_action_auto_generate_new_pin(self):
        pin_len = 7
        self._set_booking_pin_settings(auto_enabled=True, length=pin_len)
        resource_ids_to_action = [r.id for r in self.resources[:2]] # Action on first two

        response = self.client.post(url_for('api_resources.bulk_resource_pin_action'),
                                     json={'resource_ids': resource_ids_to_action, 'action': 'auto_generate_new_pin'})

        self.assertEqual(response.status_code, 200, f"Bulk auto-generate failed: {response.get_json()}")
        response_data = response.get_json()
        self.assertEqual(response_data.get('processed_count', 0), len(resource_ids_to_action))
        self.assertEqual(response_data.get('error_count', 0), 0)

        for res_id in resource_ids_to_action:
            resource = Resource.query.get(res_id)
            db.session.refresh(resource) # Ensure we have the latest from DB
            self.assertIsNotNone(resource.current_pin, f"Resource {res_id} current_pin should be set.")
            self.assertEqual(len(resource.current_pin), pin_len, f"PIN length mismatch for resource {res_id}")
            pin_obj = ResourcePIN.query.filter_by(resource_id=res_id, pin_value=resource.current_pin).first()
            self.assertIsNotNone(pin_obj, f"Current PIN {resource.current_pin} not found in DB for resource {res_id}")
            self.assertTrue(pin_obj.is_active)
            self.assertIn("Auto-generated via bulk action", pin_obj.notes if pin_obj.notes else "")

        audit_log = AuditLog.query.filter_by(action="BULK_PIN_ACTION").order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log)
        self.assertIn("'action': 'auto_generate_new_pin'", audit_log.details)
        self.assertIn(f"'processed_count': {len(resource_ids_to_action)}", audit_log.details)

    def test_bulk_action_deactivate_all_pins(self):
        resource_ids_to_action = []
        for i in range(2): # Setup for first two resources
            res = self.resources[i]
            self._add_pin_directly_to_db(res.id, f"PIN{res.id}A", is_active=True)
            self._add_pin_directly_to_db(res.id, f"PIN{res.id}B", is_active=True)
            resource_ids_to_action.append(res.id)
        db.session.commit() # Commit all setup pins
        for res_id in resource_ids_to_action: # Set current_pin after all pins are created_at
            self._update_resource_current_pin_in_db(Resource.query.get(res_id))


        response = self.client.post(url_for('api_resources.bulk_resource_pin_action'),
                                     json={'resource_ids': resource_ids_to_action, 'action': 'deactivate_all_pins'})
        self.assertEqual(response.status_code, 200, f"Bulk deactivate failed: {response.get_json()}")

        for res_id in resource_ids_to_action:
            resource = Resource.query.get(res_id)
            db.session.refresh(resource)
            self.assertIsNone(resource.current_pin, f"Resource {res_id} current_pin should be None after deactivation.")
            active_pins = ResourcePIN.query.filter_by(resource_id=res_id, is_active=True).count()
            self.assertEqual(active_pins, 0, f"Resource {res_id} should have no active PINs.")

        audit_log = AuditLog.query.filter_by(action="BULK_PIN_ACTION").order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log)
        self.assertIn("'action': 'deactivate_all_pins'", audit_log.details)

    def test_bulk_action_activate_all_pins(self):
        resource_ids_to_action = []
        expected_current_pins = {}
        for i in range(2): # Setup for first two resources
            res = self.resources[i]
            # Add pins, ensuring created_at is distinct for deterministic current_pin selection
            p1 = self._add_pin_directly_to_db(res.id, f"PIN{res.id}X", is_active=False, notes="Older")
            db.session.flush() # Flush to get p1 committed for created_at before p2
            import time as time_sleep; time_sleep.sleep(0.01) # Ensure time difference for created_at
            p2 = self._add_pin_directly_to_db(res.id, f"PIN{res.id}Y", is_active=False, notes="Newer")
            expected_current_pins[res.id] = p2.pin_value # p2 should be most recent
            resource_ids_to_action.append(res.id)
        db.session.commit()

        response = self.client.post(url_for('api_resources.bulk_resource_pin_action'),
                                     json={'resource_ids': resource_ids_to_action, 'action': 'activate_all_pins'})
        self.assertEqual(response.status_code, 200, f"Bulk activate failed: {response.get_json()}")

        for res_id in resource_ids_to_action:
            resource = Resource.query.get(res_id)
            db.session.refresh(resource)
            self.assertIsNotNone(resource.current_pin, f"Resource {res_id} current_pin should be set.")
            self.assertEqual(resource.current_pin, expected_current_pins[res_id], f"Resource {res_id} current_pin mismatch.")
            inactive_pins = ResourcePIN.query.filter_by(resource_id=res_id, is_active=False).count()
            self.assertEqual(inactive_pins, 0, f"Resource {res_id} should have no inactive PINs.")

        audit_log = AuditLog.query.filter_by(action="BULK_PIN_ACTION").order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log)
        self.assertIn("'action': 'activate_all_pins'", audit_log.details)

    def test_bulk_action_invalid_action_name(self):
        response = self.client.post(url_for('api_resources.bulk_resource_pin_action'),
                                     json={'resource_ids': [self.resources[0].id], 'action': 'non_existent_action'})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid action.", response.get_json().get('error', ''))

    def test_bulk_action_empty_resource_ids(self):
        response = self.client.post(url_for('api_resources.bulk_resource_pin_action'),
                                     json={'resource_ids': [], 'action': 'auto_generate_new_pin'})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Missing or invalid \"resource_ids\"", response.get_json().get('error', ''))

    def test_bulk_action_with_some_non_existent_resource_ids(self):
        self._set_booking_pin_settings(auto_enabled=True, length=5)
        valid_res_id = self.resources[0].id
        non_existent_id = 99999 # Assuming this ID does not exist
        resource_ids_to_action = [valid_res_id, non_existent_id]

        response = self.client.post(url_for('api_resources.bulk_resource_pin_action'),
                                     json={'resource_ids': resource_ids_to_action, 'action': 'auto_generate_new_pin'})

        # Backend filters for existing resources, so non_existent_id is silently ignored by the processing loop.
        # The response reflects operations on found resources.
        self.assertEqual(response.status_code, 200, f"Response: {response.get_json()}")
        response_data = response.get_json()

        self.assertIn("Processed: 1. Errors/Skipped: 0", response_data.get('message', ''))

        details = response_data.get('details', [])
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]['resource_id'], valid_res_id)
        self.assertEqual(details[0]['status'], 'success')

        resource_valid = Resource.query.get(valid_res_id)
        db.session.refresh(resource_valid)
        self.assertIsNotNone(resource_valid.current_pin)
        self.assertEqual(len(resource_valid.current_pin), 5)


# --- Test Class for FloorMap Role Functionality ---
class TestFloorMapRoles(AppTests):
    def setUp(self):
        super().setUp()
        # Create admin user for API tests
        self.admin_user = User(username='maproleadmin', email='maproleadmin@example.com', is_admin=True)
        self.admin_user.set_password('adminpass')
        db.session.add(self.admin_user)

        # Create some roles for testing
        self.role_map_viewer = Role(name='MapViewer', description='Can view maps')
        self.role_map_editor = Role(name='MapEditor', description='Can edit maps')
        self.role_general_booker = Role(name='GeneralBooker', description='Can book general resources')
        db.session.add_all([self.role_map_viewer, self.role_map_editor, self.role_general_booker])
        db.session.commit()

        # Create a floor map instance specific to these tests
        self.test_map1 = FloorMap(name="Role Test Map 1", image_filename="map_roles1.png")
        self.test_map2 = FloorMap(name="Role Test Map 2", image_filename="map_roles2.png")
        db.session.add_all([self.test_map1, self.test_map2])
        db.session.commit()

    def test_add_roles_to_floor_map_model(self):
        """Test assigning roles to a FloorMap instance directly."""
        self.test_map1.roles.append(self.role_map_viewer)
        self.test_map1.roles.append(self.role_map_editor)
        db.session.commit()

        # Verify roles are associated with the map
        retrieved_map = FloorMap.query.get(self.test_map1.id)
        self.assertIsNotNone(retrieved_map)
        self.assertEqual(len(retrieved_map.roles), 2)
        self.assertIn(self.role_map_viewer, retrieved_map.roles)
        self.assertIn(self.role_map_editor, retrieved_map.roles)

        # Verify backref from Role to FloorMap
        self.assertIn(retrieved_map, self.role_map_viewer.allowed_floor_maps)
        self.assertIn(retrieved_map, self.role_map_editor.allowed_floor_maps)
        self.assertNotIn(retrieved_map, self.role_general_booker.allowed_floor_maps)

    def test_get_admin_maps_api_with_assigned_roles(self):
        """Test GET /api/admin/maps returns maps with assigned_role_ids."""
        self.login(self.admin_user.username, 'adminpass')

        # Assign roles to test_map1
        self.test_map1.roles.append(self.role_map_viewer)
        self.test_map1.roles.append(self.role_map_editor)
        db.session.commit()

        # self.floor_map from parent AppTests.setUp should have no roles assigned initially
        # self.test_map2 should have no roles

        response = self.client.get('/api/admin/maps')
        self.assertEqual(response.status_code, 200)
        maps_data = response.get_json()
        self.assertIsInstance(maps_data, list)

        map1_data = next((m for m in maps_data if m['id'] == self.test_map1.id), None)
        self.assertIsNotNone(map1_data)
        self.assertIn('assigned_role_ids', map1_data)
        self.assertIsInstance(map1_data['assigned_role_ids'], list)
        self.assertEqual(len(map1_data['assigned_role_ids']), 2)
        self.assertIn(self.role_map_viewer.id, map1_data['assigned_role_ids'])
        self.assertIn(self.role_map_editor.id, map1_data['assigned_role_ids'])

        map2_data = next((m for m in maps_data if m['id'] == self.test_map2.id), None)
        self.assertIsNotNone(map2_data)
        self.assertIn('assigned_role_ids', map2_data)
        self.assertEqual(len(map2_data['assigned_role_ids']), 0)

        # Check parent's self.floor_map as well
        parent_map_data = next((m for m in maps_data if m['id'] == self.floor_map.id), None)
        self.assertIsNotNone(parent_map_data)
        self.assertIn('assigned_role_ids', parent_map_data)
        self.assertEqual(len(parent_map_data['assigned_role_ids']), 0, "Parent setup map should have no roles by default")

        self.logout()

    def test_post_map_roles_api_assign_and_clear(self):
        """Test POST /api/admin/maps/<map_id>/roles to assign and clear roles."""
        self.login(self.admin_user.username, 'adminpass')
        map_id_to_test = self.test_map1.id

        # 1. Assign roles
        payload_assign = {'role_ids': [self.role_map_viewer.id, self.role_map_editor.id]}
        response_assign = self.client.post(f'/api/admin/maps/{map_id_to_test}/roles', json=payload_assign)
        self.assertEqual(response_assign.status_code, 200)
        data_assign = response_assign.get_json()
        self.assertEqual(data_assign['map']['id'], map_id_to_test)
        self.assertEqual(len(data_assign['map']['assigned_role_ids']), 2)
        self.assertIn(self.role_map_viewer.id, data_assign['map']['assigned_role_ids'])

        db.session.refresh(self.test_map1) # Refresh from DB
        self.assertEqual(len(self.test_map1.roles), 2)

        # 2. Clear roles
        payload_clear = {'role_ids': []}
        response_clear = self.client.post(f'/api/admin/maps/{map_id_to_test}/roles', json=payload_clear)
        self.assertEqual(response_clear.status_code, 200)
        data_clear = response_clear.get_json()
        self.assertEqual(len(data_clear['map']['assigned_role_ids']), 0)

        db.session.refresh(self.test_map1)
        self.assertEqual(len(self.test_map1.roles), 0)

        # 3. Assign one role
        payload_assign_one = {'role_ids': [self.role_general_booker.id]}
        response_assign_one = self.client.post(f'/api/admin/maps/{map_id_to_test}/roles', json=payload_assign_one)
        self.assertEqual(response_assign_one.status_code, 200)
        data_assign_one = response_assign_one.get_json()
        self.assertEqual(len(data_assign_one['map']['assigned_role_ids']), 1)
        self.assertIn(self.role_general_booker.id, data_assign_one['map']['assigned_role_ids'])

        db.session.refresh(self.test_map1)
        self.assertIn(self.role_general_booker, self.test_map1.roles)

        self.logout()

    def test_post_map_roles_api_invalid_inputs(self):
        """Test POST /api/admin/maps/<map_id>/roles with invalid inputs."""
        self.login(self.admin_user.username, 'adminpass')

        # Invalid map_id
        response_invalid_map = self.client.post('/api/admin/maps/99999/roles', json={'role_ids': [self.role_map_viewer.id]})
        self.assertEqual(response_invalid_map.status_code, 404)
        self.assertIn('Floor map not found', response_invalid_map.get_json().get('error', ''))

        # Non-existent role ID
        map_id_to_test = self.test_map1.id
        payload_invalid_role = {'role_ids': [99999, self.role_map_viewer.id]} # 99999 is non-existent
        response_invalid_role = self.client.post(f'/api/admin/maps/{map_id_to_test}/roles', json=payload_invalid_role)
        self.assertEqual(response_invalid_role.status_code, 400) # Expecting 400 due to invalid role ID
        self.assertIn('One or more provided role IDs are invalid or do not exist', response_invalid_role.get_json().get('error', ''))

        db.session.refresh(self.test_map1)
        self.assertEqual(len(self.test_map1.roles), 0, "Roles should not have changed if one ID was invalid.")

        # Malformed payload (e.g., not a list of integers)
        payload_malformed = {'role_ids': 'not-a-list'}
        response_malformed = self.client.post(f'/api/admin/maps/{map_id_to_test}/roles', json=payload_malformed)
        self.assertEqual(response_malformed.status_code, 400)
        self.assertIn('Invalid role_ids format. Expected a list of integers.', response_malformed.get_json().get('error', ''))

        # Missing 'role_ids' key
        payload_missing_key = {'roles': [self.role_map_viewer.id]}
        response_missing_key = self.client.post(f'/api/admin/maps/{map_id_to_test}/roles', json=payload_missing_key)
        self.assertEqual(response_missing_key.status_code, 400)
        self.assertIn('Invalid request. JSON data with "role_ids"', response_missing_key.get_json().get('error', ''))

        self.logout()

    def test_post_map_roles_api_permissions(self):
        """Test access control for POST /api/admin/maps/<map_id>/roles."""
        # Log out admin, log in as normal user
        self.logout()
        normal_user = User.query.filter_by(username='testuser').first() # from AppTests.setUp
        self.login(normal_user.username, 'password')

        map_id_to_test = self.test_map1.id
        payload_assign = {'role_ids': [self.role_map_viewer.id]}
        response_assign = self.client.post(f'/api/admin/maps/{map_id_to_test}/roles', json=payload_assign)

        # Expect 403 Forbidden if permission_required('manage_floor_maps') is effective
        # The default 'testuser' does not have this permission.
        self.assertEqual(response_assign.status_code, 403)
        self.logout()

# --- End of TestFloorMapRoles ---

# Ensure ResourcePIN is imported if not already at the top
# from models import ResourcePIN


class TestBulkUserOperationsAPI(AppTests):
    def setUp(self):
        super().setUp()
        # Create roles needed for tests
        self.role_user = Role.query.filter_by(name='User').first()
        if not self.role_user:
            self.role_user = Role(name='User', permissions='view_resources,make_bookings')
            db.session.add(self.role_user)

        self.role_editor = Role.query.filter_by(name='Editor').first()
        if not self.role_editor:
            self.role_editor = Role(name='Editor', permissions='manage_resources')
            db.session.add(self.role_editor)

        self.role_admin_actual = Role.query.filter_by(name='Administrator').first()
        if not self.role_admin_actual:
            self.role_admin_actual = Role(name='Administrator', permissions='all_permissions') # Or specific like 'manage_users'
            db.session.add(self.role_admin_actual)

        db.session.commit()

        # Create an admin user with 'manage_users' permission
        self.admin_bulk_user = User.query.filter_by(username='adminbulk').first()
        if not self.admin_bulk_user:
            self.admin_bulk_user = User(username='adminbulk', email='adminbulk@example.com', is_admin=True)
            self.admin_bulk_user.set_password('adminpass')
            self.admin_bulk_user.roles.append(self.role_admin_actual) # Assign Administrator role
            db.session.add(self.admin_bulk_user)
            db.session.commit()

        # Create a non-admin user for permission tests
        self.non_admin_user = User.query.filter_by(username='nonadminbulk').first()
        if not self.non_admin_user:
            self.non_admin_user = User(username='nonadminbulk', email='nonadminbulk@example.com', is_admin=False)
            self.non_admin_user.set_password('userpass')
            self.non_admin_user.roles.append(self.role_user)
            db.session.add(self.non_admin_user)
            db.session.commit()

    # --- Tests for POST /api/admin/users/bulk_add ---

    def test_bulk_add_users_success(self):
        """Test successful bulk addition of multiple users."""
        self.login(self.admin_bulk_user.username, 'adminpass')
        users_data = [
            {"username": "bulkuser1", "email": "bulk1@example.com", "password": "pass1", "is_admin": False, "role_ids": [self.role_user.id]},
            {"username": "bulkuser2", "email": "bulk2@example.com", "password": "pass2", "is_admin": True, "role_ids": [self.role_admin_actual.id, self.role_editor.id]},
            {"username": "bulkuser3", "email": "bulk3@example.com", "password": "pass3"} # No roles, no admin flag
        ]
        response = self.client.post('/api/admin/users/bulk_add', json=users_data)
        self.assertEqual(response.status_code, 201) # Should be 201 if all successful
        data = response.get_json()
        self.assertEqual(data['users_added'], 3)
        self.assertEqual(len(data['errors']), 0)

        # Verify in DB
        u1 = User.query.filter_by(username="bulkuser1").first()
        self.assertIsNotNone(u1)
        self.assertEqual(u1.email, "bulk1@example.com")
        self.assertFalse(u1.is_admin)
        self.assertIn(self.role_user, u1.roles)

        u2 = User.query.filter_by(username="bulkuser2").first()
        self.assertIsNotNone(u2)
        self.assertTrue(u2.is_admin)
        self.assertIn(self.role_admin_actual, u2.roles)
        self.assertIn(self.role_editor, u2.roles)

        u3 = User.query.filter_by(username="bulkuser3").first()
        self.assertIsNotNone(u3)
        self.assertFalse(u3.is_admin) # Default
        self.assertEqual(len(u3.roles), 0) # No roles assigned

        self.logout()

    def test_bulk_add_users_partial_success_and_errors(self):
        """Test bulk addition with a mix of valid and invalid user data."""
        self.login(self.admin_bulk_user.username, 'adminpass')

        # Pre-create a user to cause duplication error
        existing_user_for_conflict = User(username='existinguser', email='existing@example.com')
        existing_user_for_conflict.set_password('password')
        db.session.add(existing_user_for_conflict)
        db.session.commit()

        users_data = [
            {"username": "validbulkuser", "email": "validbulk@example.com", "password": "passvalid", "role_ids": [self.role_user.id]}, # Valid
            {"username": "existinguser", "email": "another@example.com", "password": "pass"}, # Duplicate username
            {"username": "anotheruser", "email": "existing@example.com", "password": "pass"}, # Duplicate email
            {"username": "nousername", "password": "pass"}, # Missing email
            {"username": "bademail", "email": "invalidemail", "password": "pass"}, # Invalid email format
            {"username": "badrole", "email": "badrole@example.com", "password": "pass", "role_ids": [9999]} # Non-existent role ID
        ]
        response = self.client.post('/api/admin/users/bulk_add', json=users_data)
        self.assertEqual(response.status_code, 207) # Partial success
        data = response.get_json()

        self.assertEqual(data['users_added'], 1) # Only 'validbulkuser' should be added
        self.assertEqual(len(data['errors']), 5)

        # Verify DB state
        self.assertIsNotNone(User.query.filter_by(username="validbulkuser").first())
        self.assertIsNone(User.query.filter_by(username="nousername").first())
        self.assertIsNone(User.query.filter_by(username="bademail").first())
        self.assertIsNone(User.query.filter_by(username="badrole").first())

        # Check specific errors (optional, but good for verifying messages)
        errors = data['errors']
        self.assertTrue(any("Username 'existinguser' already exists" in e['error'] for e in errors if e['user_data'].get('username') == 'existinguser'))
        self.assertTrue(any("Email 'existing@example.com' already registered" in e['error'] for e in errors if e['user_data'].get('email') == 'existing@example.com'))
        self.assertTrue(any("Email is required" in e['error'] for e in errors if e['user_data'].get('username') == 'nousername'))
        self.assertTrue(any("Invalid email format" in e['error'] for e in errors if e['user_data'].get('username') == 'bademail'))
        self.assertTrue(any("Role with ID 9999 not found" in e['error'] for e in errors if e['user_data'].get('username') == 'badrole'))

        self.logout()

    def test_bulk_add_users_all_invalid(self):
        """Test bulk addition where all user entries are invalid."""
        self.login(self.admin_bulk_user.username, 'adminpass')
        users_data = [
            {"username": "user1", "password": "p1"}, # Missing email
            {"username": "user2", "email": "invalid", "password": "p2"} # Invalid email
        ]
        initial_user_count = User.query.count()
        response = self.client.post('/api/admin/users/bulk_add', json=users_data)
        # The status code might be 207 if it processes each and finds errors, or 400 if there's an upfront validation schema for the list itself.
        # Given the current backend likely loops, 207 is more probable if any processing starts.
        # If the list itself is malformed (e.g., not a list), it would be 400.
        # For this case (list of bad items), 207 is expected if users_to_add remains empty.
        self.assertEqual(response.status_code, 207) # Or 200 if no users added and no commit happens, resulting in "completed"
        data = response.get_json()
        self.assertEqual(data['users_added'], 0)
        self.assertEqual(len(data['errors']), 2)
        self.assertEqual(User.query.count(), initial_user_count) # No users added
        self.logout()

    def test_bulk_add_users_empty_list(self):
        """Test bulk addition with an empty list."""
        self.login(self.admin_bulk_user.username, 'adminpass')
        response = self.client.post('/api/admin/users/bulk_add', json=[])
        self.assertEqual(response.status_code, 200) # API accepts empty list, adds 0 users.
        data = response.get_json()
        self.assertEqual(data['users_added'], 0)
        self.assertEqual(len(data['errors']), 0)
        self.logout()

    def test_bulk_add_users_not_a_list(self):
        """Test bulk addition with non-list payload."""
        self.login(self.admin_bulk_user.username, 'adminpass')
        response = self.client.post('/api/admin/users/bulk_add', json={"not": "a list"})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn("Invalid input. JSON list of users expected.", data.get('error',''))
        self.logout()


    def test_bulk_add_users_no_permission(self):
        """Test bulk add endpoint without 'manage_users' permission."""
        self.login(self.non_admin_user.username, 'userpass') # Login as non-admin
        users_data = [{"username": "permtest", "email": "perm@test.com", "password": "password"}]
        response = self.client.post('/api/admin/users/bulk_add', json=users_data)
        self.assertEqual(response.status_code, 403)
        self.logout()

    # --- Tests for PUT /api/admin/users/bulk_edit ---
    def _setup_users_for_bulk_edit(self):
        u_edit1 = User(username='edituser1', email='edit1@example.com', is_admin=False)
        u_edit1.set_password('pass1')
        u_edit1.roles.append(self.role_user)

        u_edit2 = User(username='edituser2', email='edit2@example.com', is_admin=False)
        u_edit2.set_password('pass2')

        u_edit3_admin = User(username='edituser3admin', email='edit3@example.com', is_admin=True)
        u_edit3_admin.set_password('pass3')
        u_edit3_admin.roles.append(self.role_admin_actual)

        db.session.add_all([u_edit1, u_edit2, u_edit3_admin])
        db.session.commit()
        return u_edit1, u_edit2, u_edit3_admin

    def test_bulk_edit_users_success(self):
        """Test successful bulk editing of multiple users."""
        self.login(self.admin_bulk_user.username, 'adminpass')
        u1, u2, u3 = self._setup_users_for_bulk_edit()

        updates_data = [
            {"id": u1.id, "email": "updated_edit1@example.com", "role_ids": [self.role_editor.id]},
            {"id": u2.id, "is_admin": True, "password": "newpass2"},
            {"id": u3.id, "username": "updated_edituser3admin"}
        ]
        response = self.client.put('/api/admin/users/bulk_edit', json=updates_data)
        self.assertEqual(response.status_code, 200) # All successful
        data = response.get_json()
        self.assertEqual(data['users_updated'], 3)
        self.assertEqual(len(data['errors']), 0)

        # Verify DB
        db.session.refresh(u1)
        db.session.refresh(u2)
        db.session.refresh(u3)

        self.assertEqual(u1.email, "updated_edit1@example.com")
        self.assertIn(self.role_editor, u1.roles)
        self.assertNotIn(self.role_user, u1.roles) # Roles are replaced

        self.assertTrue(u2.is_admin)
        self.assertTrue(u2.check_password('newpass2'))

        self.assertEqual(u3.username, "updated_edituser3admin")
        self.logout()

    def test_bulk_edit_users_partial_success_and_errors(self):
        """Test bulk editing with a mix of valid updates and errors."""
        self.login(self.admin_bulk_user.username, 'adminpass')
        u1, u2, u3 = self._setup_users_for_bulk_edit()

        # Pre-create another user to cause potential conflicts
        conflict_user = User(username='conflictuser', email='conflict@example.com')
        conflict_user.set_password('password')
        db.session.add(conflict_user)
        db.session.commit()

        updates_data = [
            {"id": u1.id, "email": "valid_update_edit1@example.com"}, # Valid
            {"id": u2.id, "username": "conflictuser"}, # Duplicate username
            {"id": 9999, "email": "doesnotexist@example.com"}, # Non-existent user ID
            {"id": u3.id, "email": "invalidformat"}, # Invalid email format
            {"id": u3.id, "role_ids": [8888]} # Try to update same user u3 again, but with invalid role
                                             # Note: The current backend endpoint processes user by user.
                                             # If a user has an error, subsequent changes for that same user in the list might be skipped
                                             # or might overwrite. The test should reflect the actual behavior.
                                             # For this test, we assume the first error for a user stops further processing for that user item in the list.
                                             # Let's make the second u3 update distinct or test separately.
                                             # For now, let's assume that if u3's email update fails, role_ids won't be processed for it.
                                             # Or, if email is valid, then role_ids check happens.
                                             # The backend should ideally collect all errors for a single user item if possible,
                                             # but current structure is likely one error per item.
        ]
        # To make error for u3 more predictable:
        # Let's assume first u3 update has valid email, then a separate item for u3 with bad role
        # This is not ideal for "bulk_edit" which implies one set of changes per user ID.
        # The API takes a list of objects, each with an ID. So, one user can appear multiple times.
        # Let's adjust the payload to be more realistic:

        updates_data_revised = [
            {"id": u1.id, "email": "valid_update_edit1@example.com"}, # Valid
            {"id": u2.id, "username": "conflictuser"}, # Duplicate username for u2
            {"id": 9999, "email": "doesnotexist@example.com"}, # Non-existent user ID
            {"id": u3.id, "email": "invalidformat", "role_ids": [self.role_user.id]} # u3: invalid email, but roles are valid
        ]


        response = self.client.put('/api/admin/users/bulk_edit', json=updates_data_revised)
        self.assertEqual(response.status_code, 207) # Partial success
        data = response.get_json()

        self.assertEqual(data['users_updated'], 1) # Only u1 should be updated
        self.assertEqual(len(data['errors']), 3)

        db.session.refresh(u1)
        db.session.refresh(u2) # u2 should not change
        db.session.refresh(u3) # u3 should not change due to email error

        self.assertEqual(u1.email, "valid_update_edit1@example.com")
        self.assertNotEqual(u2.username, "conflictuser") # u2's username should not have changed
        self.assertEqual(u3.email, "edit3@example.com") # u3's email should not have changed

        errors = data['errors']
        self.assertTrue(any(err['id'] == u2.id and "Username 'conflictuser' already exists" in err['error'] for err in errors))
        self.assertTrue(any(err['id'] == 9999 and "User not found" in err['error'] for err in errors))
        self.assertTrue(any(err['id'] == u3.id and "Invalid email format" in err['error'] for err in errors))

        self.logout()

    def test_bulk_edit_users_prevent_last_admin_demotion(self):
        """Test bulk edit safeguards against removing the last admin's status/role."""
        self.login(self.admin_bulk_user.username, 'adminpass') # self.admin_bulk_user is an admin

        # Ensure self.admin_bulk_user is the ONLY user with 'Administrator' role and is_admin=True
        all_users = User.query.all()
        for user in all_users:
            if user.id != self.admin_bulk_user.id:
                user.is_admin = False
                if self.role_admin_actual in user.roles:
                    user.roles.remove(self.role_admin_actual)
        self.admin_bulk_user.is_admin = True
        if self.role_admin_actual not in self.admin_bulk_user.roles:
            self.admin_bulk_user.roles.append(self.role_admin_actual)
        db.session.commit()

        # Verify only one admin
        admin_users_count = User.query.filter_by(is_admin=True).count()
        self.assertEqual(admin_users_count, 1, "Setup failed: more than one is_admin=True user")

        users_with_admin_role_count = User.query.filter(User.roles.any(id=self.role_admin_actual.id)).count()
        self.assertEqual(users_with_admin_role_count, 1, "Setup failed: more than one user with Administrator role")


        # Attempt to demote self.admin_bulk_user via is_admin flag
        updates_demote_flag = [{"id": self.admin_bulk_user.id, "is_admin": False}]
        response_flag = self.client.put('/api/admin/users/bulk_edit', json=updates_demote_flag)
        self.assertEqual(response_flag.status_code, 207) # Or 200 if updated_count is 0 and only errors
        data_flag = response_flag.get_json()
        self.assertEqual(data_flag['users_updated'], 0)
        self.assertEqual(len(data_flag['errors']), 1)
        self.assertIn("Cannot remove your own admin status (is_admin flag) as the sole admin", data_flag['errors'][0]['error'])
        db.session.refresh(self.admin_bulk_user)
        self.assertTrue(self.admin_bulk_user.is_admin) # Should not change

        # Attempt to demote self.admin_bulk_user via roles (remove Administrator role)
        updates_demote_role = [{"id": self.admin_bulk_user.id, "role_ids": [self.role_user.id]}] # Assign a non-admin role
        response_role = self.client.put('/api/admin/users/bulk_edit', json=updates_demote_role)
        self.assertEqual(response_role.status_code, 207)
        data_role = response_role.get_json()
        self.assertEqual(data_role['users_updated'], 0)
        self.assertEqual(len(data_role['errors']), 1)
        self.assertIn("Cannot remove your own \"Administrator\" role as the sole holder", data_role['errors'][0]['error'])
        db.session.refresh(self.admin_bulk_user)
        self.assertIn(self.role_admin_actual, self.admin_bulk_user.roles) # Role should not change

        self.logout()


    def test_bulk_edit_users_empty_list(self):
        """Test bulk editing with an empty list."""
        self.login(self.admin_bulk_user.username, 'adminpass')
        response = self.client.put('/api/admin/users/bulk_edit', json=[])
        self.assertEqual(response.status_code, 200) # API accepts empty list, updates 0 users.
        data = response.get_json()
        self.assertEqual(data['users_updated'], 0)
        self.assertEqual(len(data['errors']), 0)
        self.logout()

    def test_bulk_edit_users_not_a_list(self):
        """Test bulk editing with non-list payload."""
        self.login(self.admin_bulk_user.username, 'adminpass')
        response = self.client.put('/api/admin/users/bulk_edit', json={"not": "a list"})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn("Invalid input. JSON list of user updates expected.", data.get('error',''))
        self.logout()

    def test_bulk_edit_users_no_permission(self):
        """Test bulk edit endpoint without 'manage_users' permission."""
        self.login(self.non_admin_user.username, 'userpass')
        u1, _, _ = self._setup_users_for_bulk_edit()
        updates_data = [{"id": u1.id, "email": "perm_test_edit@example.com"}]
        response = self.client.put('/api/admin/users/bulk_edit', json=updates_data)
        self.assertEqual(response.status_code, 403)
        self.logout()

    # --- Tests for GET /api/admin/users/export/csv ---
    def test_export_users_csv_success(self):
        """Test successful CSV export of users."""
        self.login(self.admin_bulk_user.username, 'adminpass')
        # Create some users for export
        u1, u2, u3 = self._setup_users_for_bulk_edit() # Reusing this helper for convenience
        u1.roles = [self.role_user, self.role_editor]
        u2.is_admin = True
        db.session.commit()

        response = self.client.get('/api/admin/users/export/csv')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'text/csv')
        self.assertIn('attachment; filename=users_export.csv', response.headers['Content-Disposition'])

        csv_data = response.data.decode('utf-8')
        import csv
        import io
        csv_reader = csv.reader(io.StringIO(csv_data))
        rows = list(csv_reader)

        self.assertTrue(len(rows) >= 4) # Header + 3 users (plus any other users created in setUp)
        self.assertEqual(rows[0], ['id', 'username', 'email', 'is_admin', 'roles'])

        # Find data for u1 (roles should be sorted: Editor,User)
        u1_row = next((row for row in rows if row[1] == u1.username), None)
        self.assertIsNotNone(u1_row)
        self.assertEqual(u1_row[3], str(u1.is_admin).lower())
        self.assertEqual(u1_row[4], f"{self.role_editor.name},{self.role_user.name}") # Roles are sorted alphabetically by name

        u2_row = next((row for row in rows if row[1] == u2.username), None)
        self.assertIsNotNone(u2_row)
        self.assertEqual(u2_row[3], str(u2.is_admin).lower()) # Should be true
        self.assertEqual(u2_row[4], "") # No roles assigned to u2 in setup

        self.logout()

    def test_export_users_csv_no_users(self):
        """Test CSV export when no users exist (beyond the admin performing the export)."""
        self.login(self.admin_bulk_user.username, 'adminpass')
        # Delete other users if necessary, or ensure test DB is clean for this
        User.query.filter(User.id != self.admin_bulk_user.id).delete()
        db.session.commit()

        response = self.client.get('/api/admin/users/export/csv')
        self.assertEqual(response.status_code, 200)
        csv_data = response.data.decode('utf-8')
        import csv
        import io
        csv_reader = csv.reader(io.StringIO(csv_data))
        rows = list(csv_reader)

        self.assertEqual(len(rows), 2) # Header + admin_bulk_user
        self.assertEqual(rows[0], ['id', 'username', 'email', 'is_admin', 'roles'])
        self.logout()

    def test_export_users_csv_no_permission(self):
        """Test CSV export endpoint without 'manage_users' permission."""
        self.login(self.non_admin_user.username, 'userpass')
        response = self.client.get('/api/admin/users/export/csv')
        self.assertEqual(response.status_code, 403)
        self.logout()

    # --- Tests for POST /api/admin/users/import/csv ---
    def test_import_users_csv_success_create_update(self):
        """Test successful CSV import creating new users and updating existing ones."""
        self.login(self.admin_bulk_user.username, 'adminpass')

        # Existing user to be updated
        existing_user = User(username='csvupdateme', email='csvupdate@example.com', is_admin=False)
        existing_user.set_password('oldpass')
        db.session.add(existing_user)
        db.session.commit()
        existing_user_id = existing_user.id

        csv_content = (
            "username,email,password,is_admin,role_names\n"
            "csvnew1,new1@example.com,newpass1,false,User\n" # New user
            "csvupdateme,updated_email@example.com,newpass_upd,true,Editor\n" # Update existing_user
            "csvnew2,new2@example.com,newpass2,true,\n" # New admin, no roles
        )

        from io import BytesIO
        file_data = {'file': (BytesIO(csv_content.encode('utf-8')), 'import.csv')}

        response = self.client.post('/api/admin/users/import/csv', data=file_data, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 200) # Expect 200 if all processed (even with individual errors later, but here expecting success)
        data = response.get_json()

        self.assertEqual(data.get('users_created'), 2)
        self.assertEqual(data.get('users_updated'), 1)
        self.assertEqual(len(data.get('errors', [])), 0)

        # Verify new user csvnew1
        u_new1 = User.query.filter_by(username='csvnew1').first()
        self.assertIsNotNone(u_new1)
        self.assertEqual(u_new1.email, 'new1@example.com')
        self.assertTrue(u_new1.check_password('newpass1'))
        self.assertFalse(u_new1.is_admin)
        self.assertIn(self.role_user, u_new1.roles)

        # Verify updated user
        u_updated = User.query.get(existing_user_id)
        self.assertEqual(u_updated.email, 'updated_email@example.com')
        self.assertTrue(u_updated.check_password('newpass_upd'))
        self.assertTrue(u_updated.is_admin)
        self.assertIn(self.role_editor, u_updated.roles)

        # Verify new user csvnew2
        u_new2 = User.query.filter_by(username='csvnew2').first()
        self.assertIsNotNone(u_new2)
        self.assertTrue(u_new2.is_admin)
        self.assertEqual(len(u_new2.roles), 0)

        self.logout()

    def test_import_users_csv_with_errors(self):
        """Test CSV import with various errors in data rows."""
        self.login(self.admin_bulk_user.username, 'adminpass')
        csv_content = (
            "username,email,password,is_admin,role_names\n"
            "csvgood1,good1@example.com,goodpass,false,\n" # Valid
            ",missingusername@example.com,pass1,false,\n" # Missing username
            "csvbademail,bademail,pass2,false,\n" # Invalid email format
            "csvnorole,norole@example.com,pass3,false,NonExistentRole\n" # Role not found
            "csvnopassnew,newnopass@example.com,,false,\n" # New user, missing password
        )
        from io import BytesIO
        file_data = {'file': (BytesIO(csv_content.encode('utf-8')), 'import_errors.csv')}
        response = self.client.post('/api/admin/users/import/csv', data=file_data, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 207) # Partial content due to errors
        data = response.get_json()

        self.assertEqual(data.get('users_created'), 1) # Only csvgood1
        self.assertEqual(data.get('users_updated'), 0)
        self.assertTrue(len(data.get('errors', [])) >= 4) # Expecting 4 errors

        # Verify only good user was created
        self.assertIsNotNone(User.query.filter_by(username='csvgood1').first())
        self.assertIsNone(User.query.filter_by(email='missingusername@example.com').first())
        self.assertIsNone(User.query.filter_by(username='csvbademail').first())
        self.assertIsNone(User.query.filter_by(username='csvnorole').first())
        self.assertIsNone(User.query.filter_by(username='csvnopassnew').first())

        errors = data.get('errors')
        self.assertTrue(any("Username is required" in e['error'] and e['row'] == 3 for e in errors))
        self.assertTrue(any("Invalid email format" in e['error'] and e['row'] == 4 for e in errors))
        self.assertTrue(any("Role 'NonExistentRole' not found" in e['error'] and e['row'] == 5 for e in errors))
        self.assertTrue(any("Password is required for new users" in e['error'] and e['row'] == 6 for e in errors))

        self.logout()

    def test_import_users_csv_invalid_file_or_no_file(self):
        """Test CSV import with invalid file or no file provided."""
        self.login(self.admin_bulk_user.username, 'adminpass')

        # No file
        response_no_file = self.client.post('/api/admin/users/import/csv', content_type='multipart/form-data')
        self.assertEqual(response_no_file.status_code, 400)
        self.assertIn("No file part", response_no_file.get_json().get('error', ''))

        # Invalid file type (e.g., a JSON file)
        from io import BytesIO
        json_content = b'{"not": "csv"}'
        file_data_json = {'file': (BytesIO(json_content), 'fake.json')}
        response_json_file = self.client.post('/api/admin/users/import/csv', data=file_data_json, content_type='multipart/form-data')
        self.assertEqual(response_json_file.status_code, 400)
        self.assertIn("Invalid file type", response_json_file.get_json().get('error', ''))

        # Empty CSV or missing headers
        empty_csv_content = "header1,header2\nval1,val2" # Does not match expected headers
        file_data_empty = {'file': (BytesIO(empty_csv_content.encode('utf-8')), 'empty.csv')}
        response_empty = self.client.post('/api/admin/users/import/csv', data=file_data_empty, content_type='multipart/form-data')
        self.assertEqual(response_empty.status_code, 400)
        self.assertIn("Missing required CSV headers", response_empty.get_json().get('error', ''))

        self.logout()

    def test_import_users_csv_no_permission(self):
        """Test CSV import endpoint without 'manage_users' permission."""
        self.login(self.non_admin_user.username, 'userpass')
        from io import BytesIO
        csv_content = b"username,email,password\nuser,test@example.com,pass"
        file_data = {'file': (BytesIO(csv_content), 'test.csv')}
        response = self.client.post('/api/admin/users/import/csv', data=file_data, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 403)
        self.logout()


    # --- Tests for POST /api/admin/users/bulk_add_pattern ---
    def test_bulk_add_pattern_success(self):
        """Test successful user creation with pattern."""
        self.login(self.admin_bulk_user.username, 'adminpass')
        payload = {
            "username_prefix": "pattern_u",
            "start_number": 1,
            "count": 3,
            "email_domain": "pattern.test",
            "default_password": "securePassword123",
            "is_admin": False,
            "role_ids": [self.role_user.id]
        }
        response = self.client.post('/api/admin/users/bulk_add_pattern', json=payload)
        self.assertEqual(response.status_code, 201) # Expect 201 for successful creation batch
        data = response.get_json()
        self.assertEqual(data.get('users_added'), 3)
        self.assertEqual(len(data.get('errors_warnings', [])), 0)

        for i in range(1, 4):
            user = User.query.filter_by(username=f"pattern_u{i}").first()
            self.assertIsNotNone(user)
            self.assertEqual(user.email, f"pattern_u{i}@pattern.test")
            self.assertTrue(user.check_password("securePassword123"))
            self.assertFalse(user.is_admin)
            self.assertIn(self.role_user, user.roles)
        self.logout()

    def test_bulk_add_pattern_with_email_pattern_success(self):
        """Test successful user creation with email_pattern."""
        self.login(self.admin_bulk_user.username, 'adminpass')
        payload = {
            "username_prefix": "emailpat_u",
            "start_number": 10,
            "count": 2,
            "email_pattern": "{username}+test@customdomain.com", # Using email_pattern
            "default_password": "securePassword123",
            "is_admin": True,
            "role_ids": [self.role_admin_actual.id]
        }
        response = self.client.post('/api/admin/users/bulk_add_pattern', json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertEqual(data.get('users_added'), 2)

        for i in range(10, 12):
            user = User.query.filter_by(username=f"emailpat_u{i}").first()
            self.assertIsNotNone(user)
            self.assertEqual(user.email, f"emailpat_u{i}+test@customdomain.com")
            self.assertTrue(user.is_admin)
            self.assertIn(self.role_admin_actual, user.roles)
        self.logout()


    def test_bulk_add_pattern_with_conflicts(self):
        """Test pattern bulk add where some generated users conflict with existing ones."""
        self.login(self.admin_bulk_user.username, 'adminpass')

        # Pre-create a conflicting user
        conflicting_username = "conflict_pattern2"
        conflicting_email_user = "conflict_email_user" # This username is fine, but its email will conflict

        User.query.filter_by(username=conflicting_username).delete() # Clean before test
        User.query.filter_by(email=f"{conflicting_email_user}@conflict.pattern.test").delete() # Clean before test
        db.session.commit()

        existing1 = User(username=conflicting_username, email="exist1@pattern.test")
        existing1.set_password("pass")
        db.session.add(existing1)

        existing2 = User(username=conflicting_email_user, email=f"{conflicting_email_user}@conflict.pattern.test")
        existing2.set_password("pass")
        db.session.add(existing2)
        db.session.commit()

        payload = {
            "username_prefix": "conflict_pattern",
            "start_number": 1,
            "count": 3, # conflict_pattern1, conflict_pattern2 (username conflict), conflict_pattern3
            "email_domain": "pattern.test", # This means conflict_email_user@pattern.test will be generated for conflict_email_user
            "default_password": "password"
        }
        # To make existing2's email conflict, we need the generated username to be 'conflict_email_user'
        # and domain to be 'conflict.pattern.test'
        # Let's adjust payload for a clear email conflict test:
        payload_email_conflict = {
            "username_prefix": conflicting_email_user, # Generates username "conflict_email_user0" if start_number=0
            "start_number": 0, # To make generated username "conflict_email_user0"
            "count": 1,
            "email_domain": "conflict.pattern.test", # This will generate "conflict_email_user0@conflict.pattern.test"
                                                     # This conflicts if existing2.email is "conflict_email_user0@conflict.pattern.test"
                                                     # Let's rename existing2 to match this potential generated user.
            "default_password": "password"
        }
        # Let's simplify the conflict test:
        # existing1: username="conflict_pattern2", email="exist1@pattern.test"
        # existing2: username="someotheruser", email="conflict_pattern3@pattern.test" (email conflict for 3rd generated user)
        User.query.filter_by(username="someotheruser").delete()
        db.session.commit()
        existing2.username = "someotheruser" # Ensure this username is unique
        existing2.email = "conflict_pattern3@pattern.test" # This email will conflict with generated user conflict_pattern3
        db.session.commit()


        response = self.client.post('/api/admin/users/bulk_add_pattern', json=payload)
        self.assertEqual(response.status_code, 207) # Partial success
        data = response.get_json()

        self.assertEqual(data.get('users_added'), 1) # Only conflict_pattern1 should be added
        self.assertEqual(len(data.get('errors_warnings', [])), 2) # conflict_pattern2 (username), conflict_pattern3 (email)

        self.assertIsNotNone(User.query.filter_by(username="conflict_pattern1").first())
        # Check that conflicting users were not overwritten / original ones remain
        self.assertIsNotNone(User.query.filter_by(username=conflicting_username).first()) # existing1
        self.assertIsNotNone(User.query.filter_by(username="someotheruser").first())   # existing2

        errors = data.get('errors_warnings')
        self.assertTrue(any(e['username'] == 'conflict_pattern2' and 'Username already exists' in e['error'] for e in errors))
        self.assertTrue(any(e['username'] == 'conflict_pattern3' and 'Email already registered' in e['error'] for e in errors))

        self.logout()

    def test_bulk_add_pattern_invalid_params(self):
        """Test pattern bulk add with various invalid parameters."""
        self.login(self.admin_bulk_user.username, 'adminpass')

        test_cases = [
            ({"username_prefix": "", "start_number": 1, "count": 1, "email_domain": "d.com", "default_password": "p"}, "Username prefix is required"),
            ({"username_prefix": "up", "start_number": -1, "count": 1, "email_domain": "d.com", "default_password": "p"}, "Start number must be a non-negative integer"),
            ({"username_prefix": "up", "start_number": 1, "count": 0, "email_domain": "d.com", "default_password": "p"}, "Count must be an integer between 1 and 100"),
            ({"username_prefix": "up", "start_number": 1, "count": 101, "email_domain": "d.com", "default_password": "p"}, "Count must be an integer between 1 and 100"),
            ({"username_prefix": "up", "start_number": 1, "count": 1, "email_domain": "d.com"}, "Default password is required"),
            ({"username_prefix": "up", "start_number": 1, "count": 1, "default_password": "p"}, "Either Email Domain or Email Pattern is required"),
            ({"username_prefix": "up", "start_number": 1, "count": 1, "email_domain":"d.com", "email_pattern":"{username}@p.com", "default_password": "p"}, "Provide either Email Domain or Email Pattern, not both"),
            ({"username_prefix": "up", "start_number": 1, "count": 1, "email_pattern":"user@p.com", "default_password": "p"}, "Email Pattern must contain \"{username}\" placeholder"),
            ({"username_prefix": "up", "start_number": 1, "count": 1, "email_domain":"d.com", "default_password": "p", "role_ids": [9999]}, "Role with ID 9999 not found"),
        ]

        for payload, error_msg_part in test_cases:
            with self.subTest(payload=payload):
                response = self.client.post('/api/admin/users/bulk_add_pattern', json=payload)
                self.assertEqual(response.status_code, 400)
                data = response.get_json()
                self.assertIn(error_msg_part, data.get('error', ''))

        self.logout()

    def test_bulk_add_pattern_no_permission(self):
        """Test pattern bulk add endpoint without 'manage_users' permission."""
        self.login(self.non_admin_user.username, 'userpass')
        payload = {"username_prefix": "no_perm", "start_number": 1, "count": 1, "email_domain": "test.com", "default_password": "password"}
        response = self.client.post('/api/admin/users/bulk_add_pattern', json=payload)
        self.assertEqual(response.status_code, 403)
        self.logout()


class TestUserProfile(AppTests):
    def setUp(self):
        super().setUp()
        # Create a more specific user for profile tests if needed, or use 'testuser'
        self.profile_user = User.query.filter_by(username='testuser').first()
        if not self.profile_user: # Should exist from parent setUp
            self.profile_user = User(username='testuser', email='test@example.com')
            self.profile_user.set_password('password')
            db.session.add(self.profile_user)
            db.session.commit()

        # Ensure a clean state for social IDs for each test method if needed
        self.profile_user.google_id = None
        self.profile_user.google_email = None
        self.profile_user.facebook_id = None
        self.profile_user.instagram_id = None
        db.session.commit()

    def test_user_model_attributes(self):
        """Test setting and retrieving all new User model attributes."""
        user = User(
            username='fullprofileuser',
            email='fullprofile@example.com',
            first_name='Full',
            last_name='Profile',
            phone='123-456-7890',
            section='Test Section',
            department='Test Department',
            position='Tester',
            google_id='test_google_123',
            google_email='full_google@example.com',
            facebook_id='test_facebook_123',
            instagram_id='test_instagram_123'
        )
        user.set_password('password')
        db.session.add(user)
        db.session.commit()

        retrieved_user = User.query.filter_by(username='fullprofileuser').first()
        self.assertIsNotNone(retrieved_user)
        self.assertEqual(retrieved_user.first_name, 'Full')
        self.assertEqual(retrieved_user.last_name, 'Profile')
        self.assertEqual(retrieved_user.phone, '123-456-7890')
        self.assertEqual(retrieved_user.section, 'Test Section')
        self.assertEqual(retrieved_user.department, 'Test Department')
        self.assertEqual(retrieved_user.position, 'Tester')
        self.assertEqual(retrieved_user.google_id, 'test_google_123')
        self.assertEqual(retrieved_user.google_email, 'full_google@example.com')
        self.assertEqual(retrieved_user.facebook_id, 'test_facebook_123')
        self.assertEqual(retrieved_user.instagram_id, 'test_instagram_123')

    def test_profile_page_display(self):
        """Test GET /profile displays user information correctly."""
        self.profile_user.first_name = "Test"
        self.profile_user.last_name = "User"
        self.profile_user.phone = "555-0101"
        self.profile_user.section = "Engineering"
        self.profile_user.department = "Software"
        self.profile_user.position = "Lead Tester"
        self.profile_user.google_id = "gid_123"
        self.profile_user.google_email = "testuser_google@example.com"
        # facebook_id and instagram_id remain None for this part of the test
        db.session.commit()

        self.login('testuser', 'password')
        response = self.client.get('/profile')
        self.assertEqual(response.status_code, 200)
        html_content = response.data.decode('utf-8')

        self.assertIn(self.profile_user.username, html_content)
        self.assertIn(self.profile_user.email, html_content)
        self.assertIn("Test", html_content) # First Name
        self.assertIn("User", html_content) # Last Name
        self.assertIn("555-0101", html_content) # Phone
        self.assertIn("Engineering", html_content) # Section
        self.assertIn("Software", html_content) # Department
        self.assertIn("Lead Tester", html_content) # Position

        self.assertIn("Google: Linked (testuser_google@example.com)", html_content)
        self.assertIn("Facebook: Not Linked", html_content)
        self.assertIn("Instagram: Not Linked", html_content)
        self.assertIn(url_for('auth.unlink_google_account'), html_content) # Unlink button/form
        self.assertIn(url_for('auth.link_facebook_auth'), html_content) # Link button
        self.assertIn(url_for('auth.link_instagram_auth'), html_content) # Link button

    def test_edit_profile_page_display(self):
        """Test GET /profile/edit pre-fills form fields."""
        self.profile_user.first_name = "Edit"
        self.profile_user.last_name = "Me"
        self.profile_user.phone = "555-0202"
        self.profile_user.section = "QA"
        self.profile_user.department = "Testing"
        self.profile_user.position = "Senior Tester"
        db.session.commit()

        self.login('testuser', 'password')
        response = self.client.get('/profile/edit')
        self.assertEqual(response.status_code, 200)
        html_content = response.data.decode('utf-8')

        self.assertIn(f'value="{self.profile_user.email}"', html_content)
        self.assertIn(f'value="Edit"', html_content)
        self.assertIn(f'value="Me"', html_content)
        self.assertIn(f'value="555-0202"', html_content)
        self.assertIn(f'value="QA"', html_content)
        self.assertIn(f'value="Testing"', html_content)
        self.assertIn(f'value="Senior Tester"', html_content)

    def test_profile_update_api(self):
        """Test PUT /api/profile updates all fields including password."""
        self.login('testuser', 'password')

        update_payload = {
            "email": "updated_test@example.com",
            "first_name": "UpdatedFirst",
            "last_name": "UpdatedLast",
            "phone": "555-1234",
            "section": "UpdatedSection",
            "department": "UpdatedDept",
            "position": "UpdatedPos",
            "password": "newsecurepassword"
        }
        response = self.client.put('/api/profile', json=update_payload)
        self.assertEqual(response.status_code, 200)
        json_response = response.get_json()
        self.assertTrue(json_response.get('success'))
        self.assertEqual(json_response['user']['email'], "updated_test@example.com")
        self.assertEqual(json_response['user']['first_name'], "UpdatedFirst")

        db.session.refresh(self.profile_user) # Refresh from DB
        self.assertEqual(self.profile_user.email, "updated_test@example.com")
        self.assertEqual(self.profile_user.first_name, "UpdatedFirst")
        self.assertEqual(self.profile_user.last_name, "UpdatedLast")
        self.assertEqual(self.profile_user.phone, "555-1234")
        self.assertEqual(self.profile_user.section, "UpdatedSection")
        self.assertEqual(self.profile_user.department, "UpdatedDept")
        self.assertEqual(self.profile_user.position, "UpdatedPos")
        self.assertTrue(self.profile_user.check_password("newsecurepassword"))

        # Test setting a nullable field to empty string (should become None or empty based on model)
        empty_phone_payload = {"phone": ""}
        response_empty_phone = self.client.put('/api/profile', json=empty_phone_payload)
        self.assertEqual(response_empty_phone.status_code, 200)
        db.session.refresh(self.profile_user)
        self.assertIsNone(self.profile_user.phone) # Assuming empty string from API sets it to None in DB

    @unittest.mock.patch('auth.id_token')
    @unittest.mock.patch('auth.Flow') # Mock the entire Flow class
    def test_google_account_linking_and_unlinking(self, MockFlow, mock_id_token):
        """Test Google account linking and unlinking flow with mocks."""
        self.login('testuser', 'password')

        # --- Test Linking ---
        # Mock Flow instance and its methods
        mock_flow_instance = unittest.mock.Mock()
        mock_flow_instance.authorization_url.return_value = ('https://google.com/auth_url_dummy', 'dummy_state_123')
        MockFlow.from_client_config.return_value = mock_flow_instance

        response_link_init = self.client.get(url_for('auth.link_google_auth'))
        self.assertEqual(response_link_init.status_code, 302)
        self.assertEqual(response_link_init.location, 'https://google.com/auth_url_dummy')
        with self.client.session_transaction() as sess:
            self.assertEqual(sess['oauth_link_state'], 'dummy_state_123')
            self.assertEqual(sess['oauth_link_user_id'], self.profile_user.id)

        # Mock callback phase
        mock_flow_instance.fetch_token.return_value = None # Simulate token fetched internally
        mock_flow_instance.credentials = unittest.mock.Mock(id_token='dummy_jwt_token')
        mock_id_token.verify_oauth2_token.return_value = {
            'sub': 'test_google_id_user1',
            'email': 'user1_google@example.com'
        }

        # Simulate callback from Google
        with self.client.session_transaction() as sess:
            sess['oauth_link_state'] = 'dummy_state_123' # Restore state for callback
            sess['oauth_link_user_id'] = self.profile_user.id

        response_link_callback = self.client.get(url_for('auth.link_google_callback', state='dummy_state_123'))
        self.assertEqual(response_link_callback.status_code, 302) # Redirect to profile
        self.assertIn(url_for('ui.serve_profile_page'), response_link_callback.location)

        db.session.refresh(self.profile_user)
        self.assertEqual(self.profile_user.google_id, 'test_google_id_user1')
        self.assertEqual(self.profile_user.google_email, 'user1_google@example.com')

        # Check flash message (requires response.data from follow_redirects=True)
        # For now, we check DB and audit log.
        link_log = AuditLog.query.filter_by(action="LINK_GOOGLE_SUCCESS", user_id=self.profile_user.id).first()
        self.assertIsNotNone(link_log)
        self.assertIn('linked Google account', link_log.details)

        # --- Test Unlinking ---
        response_unlink = self.client.post(url_for('auth.unlink_google_account'))
        self.assertEqual(response_unlink.status_code, 302)
        self.assertIn(url_for('ui.serve_profile_page'), response_unlink.location)

        db.session.refresh(self.profile_user)
        self.assertIsNone(self.profile_user.google_id)
        self.assertIsNone(self.profile_user.google_email)

        unlink_log = AuditLog.query.filter_by(action="UNLINK_GOOGLE_SUCCESS", user_id=self.profile_user.id).first()
        self.assertIsNotNone(unlink_log)
        self.assertIn('unlinked Google account', unlink_log.details)

    @unittest.mock.patch('auth.id_token')
    @unittest.mock.patch('auth.Flow')
    def test_google_link_conflict(self, MockFlow, mock_id_token):
        """Test linking a Google account already linked to another user."""
        # Create User A, linked to google_id_A
        user_a = User(username='userA', email='a@example.com', google_id='google_id_A', google_email='a_google@example.com')
        user_a.set_password('passA')
        db.session.add(user_a)
        db.session.commit()

        # Log in as User B (self.profile_user)
        self.login('testuser', 'password')

        # Mock Google flow for User B's linking attempt
        mock_flow_instance = unittest.mock.Mock()
        mock_flow_instance.authorization_url.return_value = ('https://google.com/auth_url_dummy_b', 'dummy_state_B')
        MockFlow.from_client_config.return_value = mock_flow_instance
        self.client.get(url_for('auth.link_google_auth')) # Initiate linking for User B

        # Mock callback to return google_id_A (already linked to User A)
        mock_flow_instance.fetch_token.return_value = None
        mock_flow_instance.credentials = unittest.mock.Mock(id_token='dummy_jwt_token_b')
        mock_id_token.verify_oauth2_token.return_value = {
            'sub': 'google_id_A', # This ID is User A's Google ID
            'email': 'a_google@example.com'
        }
        with self.client.session_transaction() as sess: # Restore session for callback
            sess['oauth_link_state'] = 'dummy_state_B'
            sess['oauth_link_user_id'] = self.profile_user.id

        response_callback_conflict = self.client.get(url_for('auth.link_google_callback', state='dummy_state_B'), follow_redirects=True)
        self.assertEqual(response_callback_conflict.status_code, 200) # Lands on profile page
        self.assertIn(b"already linked to another user", response_callback_conflict.data) # Check flash message

        db.session.refresh(self.profile_user)
        self.assertIsNone(self.profile_user.google_id) # User B should not be linked

    @unittest.mock.patch('auth.oauth.facebook') # Mock the facebook client from authlib
    def test_facebook_account_linking_and_unlinking(self, mock_facebook_client):
        """Test Facebook account linking and unlinking with mocks."""
        self.login('testuser', 'password')

        # --- Test Linking ---
        mock_facebook_client.authorize_redirect.return_value = redirect(url_for('ui.serve_index')) # Dummy redirect response

        response_link_init = self.client.get(url_for('auth.link_facebook_auth'))
        mock_facebook_client.authorize_redirect.assert_called_once()
        # We can't easily check redirect URL here as it's handled by Authlib client directly
        # Just ensure it was called and session is set.
        with self.client.session_transaction() as sess:
            self.assertIn('oauth_link_facebook_user_id', sess)
            self.assertEqual(sess['oauth_link_facebook_user_id'], self.profile_user.id)

        # Mock callback phase
        mock_facebook_client.authorize_access_token.return_value = {'access_token': 'dummy_fb_token'}
        mock_facebook_client.get.return_value = unittest.mock.Mock(json=lambda: {'id': 'test_facebook_id_user1'})

        with self.client.session_transaction() as sess: # Restore session for callback
            sess['oauth_link_facebook_user_id'] = self.profile_user.id

        response_link_callback = self.client.get(url_for('auth.link_facebook_callback')) # State not used by Authlib typically
        self.assertEqual(response_link_callback.status_code, 302)
        self.assertIn(url_for('ui.serve_profile_page'), response_link_callback.location)

        db.session.refresh(self.profile_user)
        self.assertEqual(self.profile_user.facebook_id, 'test_facebook_id_user1')

        link_log = AuditLog.query.filter_by(action="LINK_FACEBOOK_SUCCESS", user_id=self.profile_user.id).first()
        self.assertIsNotNone(link_log)

        # --- Test Unlinking ---
        response_unlink = self.client.post(url_for('auth.unlink_facebook_account'))
        self.assertEqual(response_unlink.status_code, 302)
        db.session.refresh(self.profile_user)
        self.assertIsNone(self.profile_user.facebook_id)
        unlink_log = AuditLog.query.filter_by(action="UNLINK_FACEBOOK_SUCCESS", user_id=self.profile_user.id).first()
        self.assertIsNotNone(unlink_log)

    @unittest.mock.patch('auth.oauth.instagram') # Mock the instagram client
    def test_instagram_account_linking_and_unlinking(self, mock_instagram_client):
        """Test Instagram account linking and unlinking with mocks."""
        self.login('testuser', 'password')

        # --- Test Linking ---
        mock_instagram_client.authorize_redirect.return_value = redirect(url_for('ui.serve_index'))

        response_link_init = self.client.get(url_for('auth.link_instagram_auth'))
        mock_instagram_client.authorize_redirect.assert_called_once()
        with self.client.session_transaction() as sess:
            self.assertIn('oauth_link_instagram_user_id', sess)

        # Mock callback phase
        mock_instagram_client.authorize_access_token.return_value = {'access_token': 'dummy_insta_token'}
        mock_instagram_client.get.return_value = unittest.mock.Mock(json=lambda: {'id': 'test_instagram_id_user1'})

        with self.client.session_transaction() as sess:
            sess['oauth_link_instagram_user_id'] = self.profile_user.id

        response_link_callback = self.client.get(url_for('auth.link_instagram_callback'))
        self.assertEqual(response_link_callback.status_code, 302)
        db.session.refresh(self.profile_user)
        self.assertEqual(self.profile_user.instagram_id, 'test_instagram_id_user1')
        link_log = AuditLog.query.filter_by(action="LINK_INSTAGRAM_SUCCESS", user_id=self.profile_user.id).first()
        self.assertIsNotNone(link_log)

        # --- Test Unlinking ---
        response_unlink = self.client.post(url_for('auth.unlink_instagram_account'))
        self.assertEqual(response_unlink.status_code, 302)
        db.session.refresh(self.profile_user)
        self.assertIsNone(self.profile_user.instagram_id)
        unlink_log = AuditLog.query.filter_by(action="UNLINK_INSTAGRAM_SUCCESS", user_id=self.profile_user.id).first()
        self.assertIsNotNone(unlink_log)

class TestHomePage(AppTests):
    def test_home_page_not_authenticated(self):
        """Test home page when user is not authenticated."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')
        self.assertIn('<h2>Login</h2>', content) # Assuming login.html has this
        self.assertIn('<form id="login-form">', content) # Assuming login.html has this form
        self.assertNotIn('<h2>Upcoming Bookings</h2>', content)

    def test_home_page_authenticated_no_bookings(self):
        """Test home page when user is authenticated but has no upcoming bookings."""
        self.login('testuser', 'password')

        # Ensure no future bookings for 'testuser'
        Booking.query.filter(Booking.user_name == 'testuser', Booking.start_time > datetime.utcnow()).delete()
        db.session.commit()

        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')
        self.assertIn('<h2>Upcoming Bookings</h2>', content)
        self.assertIn('No upcoming bookings.', content) # Or translated equivalent
        self.assertNotIn('Quick Actions', content)
        self.assertNotIn('Book a Room', content)

    def test_home_page_authenticated_with_bookings(self):
        """Test home page when user is authenticated and has upcoming bookings."""
        self.login('testuser', 'password')

        # Clean up any existing future bookings for testuser to ensure clean test state
        Booking.query.filter(Booking.user_name == 'testuser', Booking.start_time > datetime.utcnow()).delete()
        db.session.commit()

        # Create a future booking for 'testuser'
        future_booking = self._create_booking(
            user_name='testuser',
            resource_id=self.resource1.id,
            start_offset_hours=2,
            title="Future Meeting"
        )
        # Create a past booking for 'testuser'
        past_booking = self._create_booking(
            user_name='testuser',
            resource_id=self.resource2.id,
            start_offset_hours=-2,
            title="Past Meeting"
        )

        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')

        self.assertIn('<h2>Upcoming Bookings</h2>', content)
        self.assertNotIn('No upcoming bookings.', content)

        # Check for future booking details
        self.assertIn(future_booking.title, content)
        self.assertIn(self.resource1.name, content) # Assuming resource_booked.name is used
        self.assertIn(future_booking.start_time.strftime('%Y-%m-%d %H:%M'), content)
        self.assertIn(future_booking.end_time.strftime('%Y-%m-%d %H:%M'), content)

        # Check that past booking details are NOT present
        self.assertNotIn(past_booking.title, content)
        if self.resource2: # resource2 might be None if setup failed, though unlikely here
             self.assertNotIn(self.resource2.name, content)
        # We don't need to check for past_booking times as the title/resource name absence is sufficient

        self.assertNotIn('Quick Actions', content)
        self.assertNotIn('Book a Room', content)


class TestBookingSettingsModel(AppTests):
    def test_create_booking_settings_default_values(self):
        """Test creation of BookingSettings with default values."""
        settings = BookingSettings.query.first()
        # If settings are created on app setup or first request, one might exist.
        # For a clean model test, ensure no settings exist, then create one.
        if settings:
            db.session.delete(settings)
            db.session.commit()

        new_settings = BookingSettings()
        db.session.add(new_settings)
        db.session.commit()

        self.assertIsNotNone(new_settings.id)
        self.assertEqual(new_settings.allow_past_bookings, False)
        self.assertIsNone(new_settings.max_booking_days_in_future)
        self.assertEqual(new_settings.allow_multiple_resources_same_time, False)
        self.assertIsNone(new_settings.max_bookings_per_user)
        self.assertEqual(new_settings.enable_check_in_out, False)

    def test_booking_settings_set_and_get_fields(self):
        """Test setting and getting each field of the BookingSettings model."""
        settings = BookingSettings.query.first()
        if settings:
            db.session.delete(settings)
            db.session.commit()

        settings = BookingSettings(
            allow_past_bookings=True,
            max_booking_days_in_future=60,
            allow_multiple_resources_same_time=True,
            max_bookings_per_user=5,
            enable_check_in_out=True
        )
        db.session.add(settings)
        db.session.commit()

        retrieved_settings = BookingSettings.query.get(settings.id)
        self.assertIsNotNone(retrieved_settings)
        self.assertEqual(retrieved_settings.allow_past_bookings, True)
        self.assertEqual(retrieved_settings.max_booking_days_in_future, 60)
        self.assertEqual(retrieved_settings.allow_multiple_resources_same_time, True)
        self.assertEqual(retrieved_settings.max_bookings_per_user, 5)
        self.assertEqual(retrieved_settings.enable_check_in_out, True)
        self.assertEqual(retrieved_settings.past_booking_time_adjustment_hours, 0) # Default check

        # Test modifying a single field
        retrieved_settings.max_booking_days_in_future = None
        db.session.commit()
        modified_settings = BookingSettings.query.get(settings.id)
        self.assertIsNone(modified_settings.max_booking_days_in_future)

    def test_booking_settings_past_booking_adjustment_field(self):
        """Test the past_booking_time_adjustment_hours field specifically."""
        settings = BookingSettings.query.first()
        if settings:
            db.session.delete(settings)
            db.session.commit()

        # Test default value
        new_settings = BookingSettings()
        db.session.add(new_settings)
        db.session.commit()
        self.assertEqual(new_settings.past_booking_time_adjustment_hours, 0)
        db.session.delete(new_settings)
        db.session.commit()

        # Test setting positive value
        settings_positive = BookingSettings(past_booking_time_adjustment_hours=5)
        db.session.add(settings_positive)
        db.session.commit()
        retrieved_positive = BookingSettings.query.get(settings_positive.id)
        self.assertEqual(retrieved_positive.past_booking_time_adjustment_hours, 5)
        db.session.delete(settings_positive)
        db.session.commit()

        # Test setting negative value
        settings_negative = BookingSettings(past_booking_time_adjustment_hours=-3)
        db.session.add(settings_negative)
        db.session.commit()
        retrieved_negative = BookingSettings.query.get(settings_negative.id)
        self.assertEqual(retrieved_negative.past_booking_time_adjustment_hours, -3)
        db.session.delete(settings_negative)
        db.session.commit()

        # Test setting zero
        settings_zero = BookingSettings(past_booking_time_adjustment_hours=0)
        db.session.add(settings_zero)
        db.session.commit()
        retrieved_zero = BookingSettings.query.get(settings_zero.id)
        self.assertEqual(retrieved_zero.past_booking_time_adjustment_hours, 0)
        db.session.delete(settings_zero)
        db.session.commit()


class TestBookingSettingsEnforcement(AppTests):
    def setUp(self):
        super().setUp()
        # Helper to create a standard user for booking tests
        self.book_user = User.query.filter_by(username='booktestuser').first()
        if not self.book_user:
            self.book_user = User(username='booktestuser', email='book@example.com')
            self.book_user.set_password('password')
            db.session.add(self.book_user)
            db.session.commit()

        # Ensure no BookingSettings exist by default for a clean test, or create one.
        # Tests will explicitly create/modify BookingSettings as needed.
        BookingSettings.query.delete()
        db.session.commit()

    def _make_booking_payload(self, resource_id, days_offset=0, start_time_str='10:00', end_time_str='11:00', title="Test Booking", user_name="booktestuser"):
        booking_date = date.today() + timedelta(days=days_offset)
        return {
            'resource_id': resource_id,
            'date_str': booking_date.strftime('%Y-%m-%d'),
            'start_time_str': start_time_str,
            'end_time_str': end_time_str,
            'title': title,
            'user_name': user_name
        }

    def _make_booking_payload_fixed_time(self, resource_id, start_datetime, end_datetime, title="Test Booking", user_name="booktestuser"):
        return {
            'resource_id': resource_id,
            'date_str': start_datetime.strftime('%Y-%m-%d'),
            'start_time_str': start_datetime.strftime('%H:%M'),
            'end_time_str': end_datetime.strftime('%H:%M'),
            'title': title,
            'user_name': user_name
        }

    @unittest.mock.patch('routes.api_bookings.datetime')
    def test_past_booking_time_adjustment_logic(self, mock_api_datetime):
        """Test the past_booking_time_adjustment_hours logic in create_booking."""
        self.login(self.book_user.username, 'password')
        res_id = self.resource1.id

        # --- Scenario 1: allow_past_bookings is False ---
        BookingSettings.query.delete()
        db.session.add(BookingSettings(allow_past_bookings=False, past_booking_time_adjustment_hours=0)) # Adjustment irrelevant here
        db.session.commit()

        mock_now = datetime(2024, 1, 15, 12, 0, 0) # Fixed "current" time
        mock_api_datetime.utcnow.return_value = mock_now
        mock_api_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw) # Allow other datetime uses

        # Attempt to book 1 hour ago (should fail)
        past_booking_time_s1 = mock_now - timedelta(hours=1)
        payload_s1_past = self._make_booking_payload_fixed_time(res_id, past_booking_time_s1, past_booking_time_s1 + timedelta(hours=1), title="S1 Past Fail")
        response_s1_past = self.client.post('/api/bookings', json=payload_s1_past)
        self.assertEqual(response_s1_past.status_code, 400, f"S1 Past Fail: {response_s1_past.get_json()}")
        self.assertIn("Booking in the past is not allowed", response_s1_past.get_json().get('error', ''))

        # Attempt to book 1 hour in the future (should succeed)
        future_booking_time_s1 = mock_now + timedelta(hours=1)
        payload_s1_future = self._make_booking_payload_fixed_time(res_id, future_booking_time_s1, future_booking_time_s1 + timedelta(hours=1), title="S1 Future Success")
        response_s1_future = self.client.post('/api/bookings', json=payload_s1_future)
        self.assertEqual(response_s1_future.status_code, 201, f"S1 Future Success: {response_s1_future.get_json()}")
        if response_s1_future.status_code == 201: Booking.query.get(response_s1_future.get_json()['bookings'][0]['id']).delete()
        db.session.commit()

        # --- Scenario 2: allow_past_bookings is True, past_booking_time_adjustment_hours is 0 ---
        settings_s2 = BookingSettings.query.first()
        settings_s2.allow_past_bookings = True
        settings_s2.past_booking_time_adjustment_hours = 0
        db.session.commit()
        mock_api_datetime.utcnow.return_value = mock_now # Reset mock_now just in case

        # Attempt to book 1 minute before mock_now (should fail, as cutoff is exactly mock_now)
        past_booking_time_s2_fail = mock_now - timedelta(minutes=1)
        payload_s2_past_fail = self._make_booking_payload_fixed_time(res_id, past_booking_time_s2_fail, past_booking_time_s2_fail + timedelta(hours=1), title="S2 Past Fail")
        response_s2_past_fail = self.client.post('/api/bookings', json=payload_s2_past_fail)
        self.assertEqual(response_s2_past_fail.status_code, 400, f"S2 Past Fail: {response_s2_past_fail.get_json()}")
        self.assertIn("Booking time is outside the allowed window", response_s2_past_fail.get_json().get('error', ''))

        # Attempt to book exactly at mock_now (should succeed, as check is strictly < cutoff)
        exact_booking_time_s2_succ = mock_now
        payload_s2_exact_succ = self._make_booking_payload_fixed_time(res_id, exact_booking_time_s2_succ, exact_booking_time_s2_succ + timedelta(hours=1), title="S2 Exact Success")
        response_s2_exact_succ = self.client.post('/api/bookings', json=payload_s2_exact_succ)
        self.assertEqual(response_s2_exact_succ.status_code, 201, f"S2 Exact Success: {response_s2_exact_succ.get_json()}")
        if response_s2_exact_succ.status_code == 201: Booking.query.get(response_s2_exact_succ.get_json()['bookings'][0]['id']).delete()
        db.session.commit()

        # --- Scenario 3: allow_past_bookings is True, past_booking_time_adjustment_hours is positive (e.g., 2) ---
        settings_s3 = BookingSettings.query.first()
        settings_s3.allow_past_bookings = True
        settings_s3.past_booking_time_adjustment_hours = 2 # Allows booking up to 2 hours in the past
        db.session.commit()
        mock_api_datetime.utcnow.return_value = mock_now

        # Attempt to book 1 hour ago (should succeed, cutoff is mock_now - 2 hours)
        past_booking_time_s3_succ = mock_now - timedelta(hours=1)
        payload_s3_past_succ = self._make_booking_payload_fixed_time(res_id, past_booking_time_s3_succ, past_booking_time_s3_succ + timedelta(hours=1), title="S3 Past Success (1hr ago)")
        response_s3_past_succ = self.client.post('/api/bookings', json=payload_s3_past_succ)
        self.assertEqual(response_s3_past_succ.status_code, 201, f"S3 Past Success (1hr ago): {response_s3_past_succ.get_json()}")
        if response_s3_past_succ.status_code == 201: Booking.query.get(response_s3_past_succ.get_json()['bookings'][0]['id']).delete()
        db.session.commit()

        # Attempt to book 2 hours ago (should succeed, exactly at cutoff)
        exact_cutoff_booking_s3_succ = mock_now - timedelta(hours=2)
        payload_s3_exact_cutoff_succ = self._make_booking_payload_fixed_time(res_id, exact_cutoff_booking_s3_succ, exact_cutoff_booking_s3_succ + timedelta(hours=1), title="S3 Exact Cutoff Success (2hr ago)")
        response_s3_exact_cutoff_succ = self.client.post('/api/bookings', json=payload_s3_exact_cutoff_succ)
        self.assertEqual(response_s3_exact_cutoff_succ.status_code, 201, f"S3 Exact Cutoff Success (2hr ago): {response_s3_exact_cutoff_succ.get_json()}")
        if response_s3_exact_cutoff_succ.status_code == 201: Booking.query.get(response_s3_exact_cutoff_succ.get_json()['bookings'][0]['id']).delete()
        db.session.commit()

        # Attempt to book 2 hours and 1 minute ago (should fail, before cutoff)
        too_far_past_booking_time_s3_fail = mock_now - timedelta(hours=2, minutes=1)
        payload_s3_past_fail = self._make_booking_payload_fixed_time(res_id, too_far_past_booking_time_s3_fail, too_far_past_booking_time_s3_fail + timedelta(hours=1), title="S3 Past Fail (2hr1min ago)")
        response_s3_past_fail = self.client.post('/api/bookings', json=payload_s3_past_fail)
        self.assertEqual(response_s3_past_fail.status_code, 400, f"S3 Past Fail (2hr1min ago): {response_s3_past_fail.get_json()}")
        self.assertIn("Booking time is outside the allowed window", response_s3_past_fail.get_json().get('error', ''))

        # --- Scenario 4: allow_past_bookings is True, past_booking_time_adjustment_hours is negative (e.g., -2) ---
        # This means bookings must be at least 2 hours in the future from mock_now.
        settings_s4 = BookingSettings.query.first()
        settings_s4.allow_past_bookings = True
        settings_s4.past_booking_time_adjustment_hours = -2
        db.session.commit()
        mock_api_datetime.utcnow.return_value = mock_now

        # Cutoff time is mock_now - (-2 hours) = mock_now + 2 hours.
        # Attempt to book 1 hour in the past (relative to mock_now) (should fail)
        past_booking_time_s4_fail = mock_now - timedelta(hours=1)
        payload_s4_past_fail = self._make_booking_payload_fixed_time(res_id, past_booking_time_s4_fail, past_booking_time_s4_fail + timedelta(hours=1), title="S4 Past Fail (1hr ago)")
        response_s4_past_fail = self.client.post('/api/bookings', json=payload_s4_past_fail)
        self.assertEqual(response_s4_past_fail.status_code, 400, f"S4 Past Fail (1hr ago): {response_s4_past_fail.get_json()}")

        # Attempt to book 1 hour in the future (relative to mock_now) (should fail, because cutoff is mock_now + 2 hours)
        future_booking_time_s4_fail = mock_now + timedelta(hours=1)
        payload_s4_future_fail = self._make_booking_payload_fixed_time(res_id, future_booking_time_s4_fail, future_booking_time_s4_fail + timedelta(hours=1), title="S4 Future Fail (1hr ahead)")
        response_s4_future_fail = self.client.post('/api/bookings', json=payload_s4_future_fail)
        self.assertEqual(response_s4_future_fail.status_code, 400, f"S4 Future Fail (1hr ahead): {response_s4_future_fail.get_json()}")

        # Attempt to book exactly 2 hours in the future (relative to mock_now) (should succeed, at cutoff)
        exact_future_cutoff_s4_succ = mock_now + timedelta(hours=2)
        payload_s4_future_exact_succ = self._make_booking_payload_fixed_time(res_id, exact_future_cutoff_s4_succ, exact_future_cutoff_s4_succ + timedelta(hours=1), title="S4 Future Success (2hr ahead - exact)")
        response_s4_future_exact_succ = self.client.post('/api/bookings', json=payload_s4_future_exact_succ)
        self.assertEqual(response_s4_future_exact_succ.status_code, 201, f"S4 Future Success (2hr ahead - exact): {response_s4_future_exact_succ.get_json()}")
        if response_s4_future_exact_succ.status_code == 201: Booking.query.get(response_s4_future_exact_succ.get_json()['bookings'][0]['id']).delete()
        db.session.commit()

        # Attempt to book 2 hours and 1 minute in the future (relative to mock_now) (should succeed)
        far_future_booking_time_s4_succ = mock_now + timedelta(hours=2, minutes=1)
        payload_s4_future_succ = self._make_booking_payload_fixed_time(res_id, far_future_booking_time_s4_succ, far_future_booking_time_s4_succ + timedelta(hours=1), title="S4 Future Success (2hr1min ahead)")
        response_s4_future_succ = self.client.post('/api/bookings', json=payload_s4_future_succ)
        self.assertEqual(response_s4_future_succ.status_code, 201, f"S4 Future Success (2hr1min ahead): {response_s4_future_succ.get_json()}")
        if response_s4_future_succ.status_code == 201: Booking.query.get(response_s4_future_succ.get_json()['bookings'][0]['id']).delete()
        db.session.commit()

        self.logout()
        # Reset mock for other tests if necessary, though patch is method-scoped
        mock_api_datetime.side_effect = None


    def test_allow_past_bookings_setting(self):
        """Test enforcement of the 'allow_past_bookings' setting."""
        self.login(self.book_user.username, 'password')
        res_id = self.resource1.id

        # Case 1: allow_past_bookings = False (default or explicitly set)
        BookingSettings.query.delete() # Ensure no settings or use default
        db.session.add(BookingSettings(allow_past_bookings=False))
        db.session.commit()

        # Attempt to book in the past (yesterday)
        past_payload = self._make_booking_payload(res_id, days_offset=-1)
        response_past = self.client.post('/api/bookings', json=past_payload)
        self.assertEqual(response_past.status_code, 400)
        self.assertIn('Booking in the past is not allowed', response_past.get_json().get('error', ''))

        # Attempt to book for today (should succeed)
        today_payload = self._make_booking_payload(res_id, days_offset=0)
        response_today = self.client.post('/api/bookings', json=today_payload)
        self.assertEqual(response_today.status_code, 201, f"Booking for today failed: {response_today.get_json()}")
        # Clean up booking
        if response_today.status_code == 201:
            booking_id = response_today.get_json()['bookings'][0]['id']
            Booking.query.filter_by(id=booking_id).delete()
            db.session.commit()

        # Case 2: allow_past_bookings = True
        settings = BookingSettings.query.first()
        settings.allow_past_bookings = True
        db.session.commit()

        # Attempt to book in the past (yesterday, should succeed now)
        response_past_allowed = self.client.post('/api/bookings', json=past_payload)
        self.assertEqual(response_past_allowed.status_code, 201, f"Past booking failed when allowed: {response_past_allowed.get_json()}")
        if response_past_allowed.status_code == 201:
            booking_id = response_past_allowed.get_json()['bookings'][0]['id']
            Booking.query.filter_by(id=booking_id).delete()
            db.session.commit()

        self.logout()

    def test_max_booking_days_in_future_setting(self):
        """Test enforcement of the 'max_booking_days_in_future' setting."""
        self.login(self.book_user.username, 'password')
        res_id = self.resource1.id

        # Case 1: max_booking_days_in_future = 30
        BookingSettings.query.delete()
        db.session.add(BookingSettings(max_booking_days_in_future=30))
        db.session.commit()

        # Attempt to book 29 days in future (should succeed)
        payload_29_days = self._make_booking_payload(res_id, days_offset=29)
        response_29 = self.client.post('/api/bookings', json=payload_29_days)
        self.assertEqual(response_29.status_code, 201, f"Booking 29 days in future failed: {response_29.get_json()}")
        if response_29.status_code == 201:
            Booking.query.filter_by(id=response_29.get_json()['bookings'][0]['id']).delete()
            db.session.commit()

        # Attempt to book 30 days in future (should succeed - boundary condition)
        payload_30_days = self._make_booking_payload(res_id, days_offset=30)
        response_30 = self.client.post('/api/bookings', json=payload_30_days)
        self.assertEqual(response_30.status_code, 201, f"Booking 30 days in future failed: {response_30.get_json()}")
        if response_30.status_code == 201:
            Booking.query.filter_by(id=response_30.get_json()['bookings'][0]['id']).delete()
            db.session.commit()

        # Attempt to book 31 days in future (should fail)
        payload_31_days = self._make_booking_payload(res_id, days_offset=31)
        response_31 = self.client.post('/api/bookings', json=payload_31_days)
        self.assertEqual(response_31.status_code, 400)
        self.assertIn('Bookings cannot be made more than 30 days in advance', response_31.get_json().get('error', ''))

        # Case 2: max_booking_days_in_future = None (no limit)
        settings = BookingSettings.query.first()
        settings.max_booking_days_in_future = None
        db.session.commit()

        # Attempt to book 100 days in future (should succeed)
        payload_100_days = self._make_booking_payload(res_id, days_offset=100)
        response_100 = self.client.post('/api/bookings', json=payload_100_days)
        self.assertEqual(response_100.status_code, 201, f"Booking 100 days in future failed with no limit: {response_100.get_json()}")
        if response_100.status_code == 201:
            Booking.query.filter_by(id=response_100.get_json()['bookings'][0]['id']).delete()
            db.session.commit()

        # Case 3: No BookingSettings record (should default to no limit as per create_booking logic)
        BookingSettings.query.delete()
        db.session.commit()

        payload_far_future_no_settings = self._make_booking_payload(res_id, days_offset=200)
        response_far_no_settings = self.client.post('/api/bookings', json=payload_far_future_no_settings)
        # Default behavior in create_booking if no settings row is: max_booking_days_in_future_effective = None
        self.assertEqual(response_far_no_settings.status_code, 201, f"Booking far in future failed with no settings row: {response_far_no_settings.get_json()}")
        if response_far_no_settings.status_code == 201:
            Booking.query.filter_by(id=response_far_no_settings.get_json()['bookings'][0]['id']).delete()
            db.session.commit()

        self.logout()

    def test_max_bookings_per_user_setting(self):
        """Test enforcement of the 'max_bookings_per_user' setting."""
        self.login(self.book_user.username, 'password')
        res_id1 = self.resource1.id
        res_id2 = self.resource2.id # Use a second resource to avoid direct time conflicts for simplicity

        # Ensure a clean slate for bookings by this user for this test
        Booking.query.filter_by(user_name=self.book_user.username).delete()
        BookingSettings.query.delete()
        db.session.commit()

        # Case 1: max_bookings_per_user = 2
        db.session.add(BookingSettings(max_bookings_per_user=2))
        db.session.commit()

        # Create 1st booking (should succeed)
        payload1 = self._make_booking_payload(res_id1, days_offset=1, title="UserLimitBook1")
        resp1 = self.client.post('/api/bookings', json=payload1)
        self.assertEqual(resp1.status_code, 201, f"UserLimitBook1 failed: {resp1.get_json()}")

        # Create 2nd booking (should succeed)
        payload2 = self._make_booking_payload(res_id2, days_offset=2, title="UserLimitBook2") # Different day/resource
        resp2 = self.client.post('/api/bookings', json=payload2)
        self.assertEqual(resp2.status_code, 201, f"UserLimitBook2 failed: {resp2.get_json()}")

        # Attempt to create 3rd booking (should fail)
        payload3_fail = self._make_booking_payload(res_id1, days_offset=3, title="UserLimitBook3Fail")
        resp3_fail = self.client.post('/api/bookings', json=payload3_fail)
        self.assertEqual(resp3_fail.status_code, 400)
        self.assertIn('exceed the maximum of 2 bookings allowed per user', resp3_fail.get_json().get('error', ''))

        # Test that past bookings are not counted
        # Modify the first booking to be in the past
        booking1_obj = Booking.query.filter_by(title="UserLimitBook1").first()
        self.assertIsNotNone(booking1_obj)
        booking1_obj.start_time = datetime.utcnow() - timedelta(days=2)
        booking1_obj.end_time = datetime.utcnow() - timedelta(days=2, hours=-1)
        db.session.commit()

        # Attempt to create another booking (should succeed as one is now past)
        payload4_past_ignored = self._make_booking_payload(res_id1, days_offset=4, title="UserLimitBook4PastIgnored")
        resp4_past = self.client.post('/api/bookings', json=payload4_past_ignored)
        self.assertEqual(resp4_past.status_code, 201, f"Booking after one became past failed: {resp4_past.get_json()}")

        # Test that cancelled bookings are not counted
        # Cancel the second booking (UserLimitBook2)
        booking2_obj = Booking.query.filter_by(title="UserLimitBook2").first()
        self.assertIsNotNone(booking2_obj)
        booking2_obj.status = 'cancelled'
        db.session.commit()

        # Attempt to create another booking (should succeed as one is now cancelled)
        payload5_cancelled_ignored = self._make_booking_payload(res_id2, days_offset=5, title="UserLimitBook5CancelledIgnored")
        resp5_cancelled = self.client.post('/api/bookings', json=payload5_cancelled_ignored)
        self.assertEqual(resp5_cancelled.status_code, 201, f"Booking after one was cancelled failed: {resp5_cancelled.get_json()}")

        # Clean up: Remove all bookings for this user to reset for next case
        Booking.query.filter_by(user_name=self.book_user.username).delete()
        db.session.commit()

        # Case 2: max_bookings_per_user = None (no limit)
        settings = BookingSettings.query.first()
        settings.max_bookings_per_user = None
        db.session.commit()

        for i in range(5): # Create 5 bookings
            payload_no_limit = self._make_booking_payload(res_id1, days_offset=10 + i, title=f"NoLimitBook{i}")
            resp_no_limit = self.client.post('/api/bookings', json=payload_no_limit)
            self.assertEqual(resp_no_limit.status_code, 201, f"NoLimitBook{i} failed: {resp_no_limit.get_json()}")

        self.assertEqual(Booking.query.filter_by(user_name=self.book_user.username).count(), 5)

        # Clean up for the class
        Booking.query.filter_by(user_name=self.book_user.username).delete()
        BookingSettings.query.delete()
        db.session.commit()
        self.logout()

    def test_past_booking_current_day_and_yesterday(self):
        """Test booking in the past on current day vs. previous day based on settings."""
        self.login(self.book_user.username, 'password')
        res_id = self.resource1.id

        # Ensure clean state for bookings and settings
        Booking.query.filter_by(user_name=self.book_user.username).delete()
        BookingSettings.query.delete()
        db.session.commit()

        # Scenario 1: Past booking on CURRENT DAY (e.g., 10 AM when it's 2 PM)
        # Setting: allow_past_bookings = False
        db.session.add(BookingSettings(allow_past_bookings=False))
        db.session.commit()

        now = datetime.utcnow()
        past_start_time_today = now - timedelta(hours=4) # e.g., 4 hours ago
        past_end_time_today = now - timedelta(hours=3)   # e.g., 3 hours ago

        # Ensure the calculated times are not crossing midnight into "yesterday" for this part of the test
        # If it's early morning, this test might try to book for "yesterday" if not careful.
        # We want to test a time that is definitively earlier *on the same UTC date*.
        if past_start_time_today.date() != now.date():
            # If subtracting hours crossed midnight, adjust to be later but still past
            # e.g. if now is 1 AM, 4 hours ago is yesterday.
            # For simplicity, if it's before 5 AM, try to book 1 hour ago.
            if now.hour < 5:
                past_start_time_today = now - timedelta(hours=2)
                past_end_time_today = now - timedelta(hours=1)
            else: # Default to a time like 10:00 and 11:00 if now is much later
                 past_start_time_today = now.replace(hour=10, minute=0, second=0, microsecond=0)
                 past_end_time_today = now.replace(hour=11, minute=0, second=0, microsecond=0)
                 # If 'now' is before 11 AM, this test for same-day past booking is tricky.
                 # The check `new_booking_start_time < datetime.utcnow()` is precise.
                 # For testing, we need to ensure the time strings we pass are genuinely in the past.

        # Fallback if now is too early for the above logic to make sense for "past on current day"
        if now.hour < 2: # e.g. if it's 00:30 or 01:30 UTC
            self.skipTest("Skipping current day past booking test: current UTC hour is too early.")
        else:
            payload_past_current_day = self._make_booking_payload(
                res_id,
                days_offset=0, # Current day
                start_time_str=past_start_time_today.strftime('%H:%M'),
                end_time_str=past_end_time_today.strftime('%H:%M'),
                title="Past Booking Current Day Fail"
            )
            response_past_current_day = self.client.post('/api/bookings', json=payload_past_current_day)
            self.assertEqual(response_past_current_day.status_code, 400,
                             f"Past booking on current day should fail when not allowed. Payload: {payload_past_current_day}, Response: {response_past_current_day.get_json()}")
            self.assertIn('Booking in the past is not allowed', response_past_current_day.get_json().get('error', ''))

        # Scenario 2: Past booking on PREVIOUS DAY
        # Setting: allow_past_bookings = True
        settings = BookingSettings.query.first()
        if not settings: # Should exist from previous step, but good practice
            settings = BookingSettings()
            db.session.add(settings)
        settings.allow_past_bookings = True
        db.session.commit()

        payload_yesterday_allowed = self._make_booking_payload(
            res_id,
            days_offset=-1, # Yesterday
            start_time_str='10:00', # Specific time yesterday
            end_time_str='11:00',
            title="Past Booking Yesterday Allowed"
        )
        response_yesterday_allowed = self.client.post('/api/bookings', json=payload_yesterday_allowed)
        self.assertEqual(response_yesterday_allowed.status_code, 201,
                         f"Past booking on previous day should succeed when allowed. Payload: {payload_yesterday_allowed}, Response: {response_yesterday_allowed.get_json()}")

        if response_yesterday_allowed.status_code == 201:
            booking_id = response_yesterday_allowed.get_json()['bookings'][0]['id']
            Booking.query.filter_by(id=booking_id).delete()
            db.session.commit()

        # Clean up settings for other tests
        BookingSettings.query.delete()
        db.session.commit()
        self.logout()

    def test_allow_multiple_resources_same_time_setting(self):
        """Test enforcement of the 'allow_multiple_resources_same_time' setting."""
        self.login(self.book_user.username, 'password')
        res_id1 = self.resource1.id
        res_id2 = self.resource2.id

        # Ensure a clean slate for bookings
        Booking.query.filter_by(user_name=self.book_user.username).delete()
        BookingSettings.query.delete()
        db.session.commit()

        # Common time slot for testing
        slot_date_offset = 7 # Days in future to avoid other restrictions
        slot_start_str = '14:00'
        slot_end_str = '15:00'

        # Case 1: allow_multiple_resources_same_time = False
        db.session.add(BookingSettings(allow_multiple_resources_same_time=False))
        db.session.commit()

        # Book Resource A at Time X (should succeed)
        payload_res1_timeX = self._make_booking_payload(res_id1, days_offset=slot_date_offset,
                                                        start_time_str=slot_start_str, end_time_str=slot_end_str,
                                                        title="MultiResFalse Book1")
        resp_res1 = self.client.post('/api/bookings', json=payload_res1_timeX)
        self.assertEqual(resp_res1.status_code, 201, f"Booking Res1 when MultiRes=False failed: {resp_res1.get_json()}")

        # Attempt to book Resource B at Time X by the same user (should fail)
        payload_res2_timeX_fail = self._make_booking_payload(res_id2, days_offset=slot_date_offset,
                                                             start_time_str=slot_start_str, end_time_str=slot_end_str,
                                                             title="MultiResFalse Book2 Fail")
        resp_res2_fail = self.client.post('/api/bookings', json=payload_res2_timeX_fail)
        self.assertEqual(resp_res2_fail.status_code, 409) # Conflict due to user already having a booking
        self.assertIn('You already have a booking for resource', resp_res2_fail.get_json().get('error', ''))
        self.assertIn(self.resource1.name, resp_res2_fail.get_json().get('error', '')) # Error should mention the conflicting resource

        # Clean up booking
        Booking.query.filter_by(user_name=self.book_user.username).delete()
        db.session.commit()

        # Case 2: allow_multiple_resources_same_time = True
        settings = BookingSettings.query.first()
        settings.allow_multiple_resources_same_time = True
        db.session.commit()

        # Book Resource A at Time X (should succeed)
        payload_res1_timeX_allowed = self._make_booking_payload(res_id1, days_offset=slot_date_offset,
                                                                start_time_str=slot_start_str, end_time_str=slot_end_str,
                                                                title="MultiResTrue Book1")
        resp_res1_allowed = self.client.post('/api/bookings', json=payload_res1_timeX_allowed)
        self.assertEqual(resp_res1_allowed.status_code, 201, f"Booking Res1 when MultiRes=True failed: {resp_res1_allowed.get_json()}")

        # Attempt to book Resource B at Time X by the same user (should succeed now)
        payload_res2_timeX_allowed_success = self._make_booking_payload(res_id2, days_offset=slot_date_offset,
                                                                        start_time_str=slot_start_str, end_time_str=slot_end_str,
                                                                        title="MultiResTrue Book2 Success")
        resp_res2_allowed_success = self.client.post('/api/bookings', json=payload_res2_timeX_allowed_success)
        self.assertEqual(resp_res2_allowed_success.status_code, 201, f"Booking Res2 when MultiRes=True failed: {resp_res2_allowed_success.get_json()}")

        # Standard conflict: Attempt to book Resource A at Time X AGAIN (should fail regardless of setting)
        # First, ensure Resource A is booked by *another user* to make it a resource conflict, not user conflict
        other_user = User(username='otherbooker', email='otherb@example.com')
        other_user.set_password('password')
        db.session.add(other_user)
        db.session.commit()

        # Clear previous bookings for res1 by self.book_user
        Booking.query.filter_by(resource_id=res_id1, user_name=self.book_user.username).delete()
        db.session.commit()

        payload_res1_other_user = self._make_booking_payload(res_id1, days_offset=slot_date_offset,
                                                              start_time_str=slot_start_str, end_time_str=slot_end_str,
                                                              title="OtherUser Res1 Booking", user_name='otherbooker')
        resp_res1_other_user = self.client.post('/api/bookings', json=payload_res1_other_user) # Login as other user not strictly needed for this API structure if user_name is in payload
        self.assertEqual(resp_res1_other_user.status_code, 201, f"Other user booking Res1 failed: {resp_res1_other_user.get_json()}")


        # Now self.book_user (still logged in) tries to book res_id1 which is taken by otherbooker
        payload_res1_conflict_standard = self._make_booking_payload(res_id1, days_offset=slot_date_offset,
                                                                    start_time_str=slot_start_str, end_time_str=slot_end_str,
                                                                    title="StandardConflictTest")
        resp_res1_conflict_standard = self.client.post('/api/bookings', json=payload_res1_conflict_standard)
        self.assertEqual(resp_res1_conflict_standard.status_code, 409) # Standard resource conflict
        self.assertIn(f"This time slot ({payload_res1_conflict_standard['date_str']} {slot_start_str}", resp_res1_conflict_standard.get_json().get('error', ''))
        self.assertIn(f"on resource '{self.resource1.name}' is already booked", resp_res1_conflict_standard.get_json().get('error', ''))

        # Clean up
        Booking.query.delete() # Clear all bookings
        BookingSettings.query.delete()
        User.query.filter_by(username='otherbooker').delete()
        db.session.commit()
        self.logout()

# --- Test Class for Booking Permission Logic ---
class TestBookingPermissions(AppTests):
    def setUp(self):
        super().setUp()
        # Common roles - create them once here if they don't exist
        # Ensure roles are fetched or created and committed within the app context

        # Role creation/retrieval logic
        role_admin = Role.query.filter_by(name="Administrator").first()
        if not role_admin:
            role_admin = Role(name="Administrator", permissions="all_permissions")
            db.session.add(role_admin)
        self.role_admin = role_admin

        role_area_a = Role.query.filter_by(name="RoleAreaA").first()
        if not role_area_a:
            role_area_a = Role(name="RoleAreaA", description="Role for Area A")
            db.session.add(role_area_a)
        self.role_area_a = role_area_a

        role_general_b = Role.query.filter_by(name="RoleGeneralB").first()
        if not role_general_b:
            role_general_b = Role(name="RoleGeneralB", description="General Role for Resource B")
            db.session.add(role_general_b)
        self.role_general_b = role_general_b

        role_general_d = Role.query.filter_by(name="RoleGeneralD").first()
        if not role_general_d:
            role_general_d = Role(name="RoleGeneralD", description="General Role for Resource D (fallback test)")
            db.session.add(role_general_d)
        self.role_general_d = role_general_d

        db.session.commit() # Commit all roles at once after checks


    def _create_user_for_perm_test(self, username, password="password", role_names=None, is_admin=False):
        """Helper to create a user for permission tests, ensuring roles exist."""
        user = User.query.filter_by(username=username).first()
        if user: # Delete if exists to ensure clean state for roles
            db.session.delete(user)
            db.session.commit()

        user = User(username=username, email=f"{username}@example.com", is_admin=is_admin)
        user.set_password(password)

        assigned_roles = []
        if role_names:
            for role_name in role_names:
                role = Role.query.filter_by(name=role_name).first()
                # Roles should ideally be created in setUp to ensure their IDs are stable before user creation.
                # If a role_name is passed that wasn't in setUp, this will create it.
                if not role:
                    role = Role(name=role_name, description=f"Dynamic role for {role_name}")
                    db.session.add(role)
                    # Need to commit here if role is new and to be used immediately by user.roles.append
                    db.session.commit()
                assigned_roles.append(role)
        user.roles = assigned_roles

        db.session.add(user)
        db.session.commit()
        return user

    def _create_resource_for_perm_test(self, name, map_coordinates_json_str=None, allowed_user_ids_str=None, booking_restriction_str=None, general_role_names=None, floor_map_id=None):
        """Helper to create a resource for permission tests."""
        resource = Resource(
            name=name,
            capacity=10, # Default capacity
            status='published',
            map_coordinates=map_coordinates_json_str,
            allowed_user_ids=allowed_user_ids_str,
            booking_restriction=booking_restriction_str,
            floor_map_id=floor_map_id if floor_map_id else self.floor_map.id # Use default map if none given
        )
        if general_role_names:
            roles_to_assign = []
            for role_name in general_role_names:
                role = Role.query.filter_by(name=role_name).first()
                if role: # Roles should be created in setUp
                    roles_to_assign.append(role)
            resource.roles = roles_to_assign

        db.session.add(resource)
        db.session.commit()
        return resource

    def _make_booking_request(self, user_making_request, resource_id, date_str=None, start_time_str='09:00', end_time_str='10:00', title='Test Booking'):
        """Helper to log in a user and make a booking request."""
        if not date_str:
            # Default to a date far enough in the future to avoid past booking restrictions
            date_str = (datetime.utcnow() + timedelta(days=35)).strftime('%Y-%m-%d')

        self.login(user_making_request.username, "password") # Assuming common password "password"

        payload = {
            'resource_id': resource_id,
            'date_str': date_str,
            'start_time_str': start_time_str,
            'end_time_str': end_time_str,
            'title': title,
            'user_name': user_making_request.username # Booking for oneself
        }
        response = self.client.post('/api/bookings', json=payload)
        # self.logout() # Consider if logout is needed after each action or if session can persist
        return response

    # --- Test Scenarios ---

    def test_admin_can_book_restrictive_area_role_resource(self):
        """1. Admin Booking: Admin user can book a resource even if it has restrictive area roles."""
        admin_user = self._create_user_for_perm_test("perm_admin_user", is_admin=True, role_names=[self.role_admin.name])

        # Resource with restrictive area role (RoleAreaA)
        map_coords = json.dumps({'allowed_role_ids': [self.role_area_a.id]})
        resource = self._create_resource_for_perm_test("AdminAreaTestRes", map_coordinates_json_str=map_coords)

        response = self._make_booking_request(admin_user, resource.id)
        self.assertEqual(response.status_code, 201, f"Admin booking failed. Response: {response.get_json()}")

    def test_resource_admin_only_restriction(self):
        """2. Resource admin_only Restriction."""
        admin_user = self._create_user_for_perm_test("perm_admin_user_2", is_admin=True, role_names=[self.role_admin.name])
        non_admin_user = self._create_user_for_perm_test("perm_non_admin_user_2")

        resource = self._create_resource_for_perm_test("AdminOnlyRes", booking_restriction_str='admin_only')

        # Non-admin attempts to book
        response_non_admin = self._make_booking_request(non_admin_user, resource.id)
        self.assertEqual(response_non_admin.status_code, 403, f"Non-admin booking admin_only resource should be denied. Response: {response_non_admin.get_json()}")
        if response_non_admin.status_code == 403: # Check error message only if denied
            self.assertIn("This resource can only be booked by administrators", response_non_admin.get_json().get('error', ''))

        # Admin attempts to book
        response_admin = self._make_booking_request(admin_user, resource.id)
        self.assertEqual(response_admin.status_code, 201, f"Admin booking admin_only resource failed. Response: {response_admin.get_json()}")

    def test_area_specific_role_enforcement(self):
        """3. Area-Specific Role Enforcement."""
        user1_has_area_role = self._create_user_for_perm_test("user1_area_role", role_names=[self.role_area_a.name])
        user2_no_area_role = self._create_user_for_perm_test("user2_no_area_role")
        user3_in_allowed_list = self._create_user_for_perm_test("user3_allowed_list")

        map_coords_area_a = json.dumps({'allowed_role_ids': [self.role_area_a.id]})
        # Ensure user3_in_allowed_list.id is a string when concatenating for allowed_user_ids_str
        resource_a = self._create_resource_for_perm_test(
            "AreaRoleResourceA",
            map_coordinates_json_str=map_coords_area_a,
            allowed_user_ids_str=str(user3_in_allowed_list.id)
        )

        # User 1 (has Role_Area_A): Can book Resource A
        response_user1 = self._make_booking_request(user1_has_area_role, resource_a.id)
        self.assertEqual(response_user1.status_code, 201, f"User1 with area role failed to book. Response: {response_user1.get_json()}")
        # Clean up booking to allow next step if it books same default slot
        if response_user1.status_code == 201:
            Booking.query.filter_by(id=response_user1.get_json()['bookings'][0]['id']).delete()
            db.session.commit()

        # User 2 (does NOT have Role_Area_A, not in allowed_user_ids): Denied booking Resource A
        response_user2 = self._make_booking_request(user2_no_area_role, resource_a.id)
        self.assertEqual(response_user2.status_code, 403, f"User2 without area role should be denied. Response: {response_user2.get_json()}")
        if response_user2.status_code == 403:
            self.assertIn("You do not have the required role to book this resource via its map area", response_user2.get_json().get('error', ''))

        # User 3 (in allowed_user_ids for Resource A, does NOT have Role_Area_A): Can book Resource A
        response_user3 = self._make_booking_request(user3_in_allowed_list, resource_a.id)
        self.assertEqual(response_user3.status_code, 201, f"User3 in allowed_user_ids failed to book. Response: {response_user3.get_json()}")

    def test_fallback_to_general_resource_roles(self):
        """4. Fallback to General Resource Roles when area roles are empty."""
        user4_has_general_role_b = self._create_user_for_perm_test("user4_general_role_b", role_names=[self.role_general_b.name])
        user5_no_general_role_b = self._create_user_for_perm_test("user5_no_general_role_b")

        # Resource B with empty area roles, but has general resource roles
        map_coords_empty_area_roles = json.dumps({'allowed_role_ids': []}) # Empty list
        resource_b = self._create_resource_for_perm_test(
            "GeneralRoleResourceB",
            map_coordinates_json_str=map_coords_empty_area_roles,
            general_role_names=[self.role_general_b.name]
        )

        # User 4 (has Role_General_B): Can book Resource B
        response_user4 = self._make_booking_request(user4_has_general_role_b, resource_b.id)
        self.assertEqual(response_user4.status_code, 201, f"User4 with general role B failed to book. Response: {response_user4.get_json()}")
        if response_user4.status_code == 201: Booking.query.filter_by(id=response_user4.get_json()['bookings'][0]['id']).delete(); db.session.commit()

        # User 5 (does NOT have Role_General_B, not in allowed_user_ids): Denied booking Resource B
        response_user5 = self._make_booking_request(user5_no_general_role_b, resource_b.id)
        self.assertEqual(response_user5.status_code, 403, f"User5 without general role B should be denied. Response: {response_user5.get_json()}")
        # The error message might be generic "not authorized" as it fails the general resource role check
        if response_user5.status_code == 403:
            self.assertIn("You are not authorized to book this resource based on its permission settings", response_user5.get_json().get('error', ''))

    def test_fallback_to_open_resource(self):
        """5. Fallback to Open Resource (No Area Roles, No General Roles, No specific user IDs)."""
        user6_any_authenticated = self._create_user_for_perm_test("user6_any_auth")

        # Resource C with no area roles, no general resource roles, no specific user IDs
        map_coords_no_area_roles = json.dumps({}) # No allowed_role_ids key or empty
        resource_c = self._create_resource_for_perm_test(
            "OpenResourceC",
            map_coordinates_json_str=map_coords_no_area_roles,
            allowed_user_ids_str=None, # Or ""
            general_role_names=[] # Or None
        )

        # User 6 (any authenticated non-admin): Can book Resource C
        response_user6 = self._make_booking_request(user6_any_authenticated, resource_c.id)
        self.assertEqual(response_user6.status_code, 201, f"User6 (any auth) failed to book open resource C. Response: {response_user6.get_json()}")

    def test_malformed_map_coordinates_fallback(self):
        """6. Malformed map_coordinates (Fallback to general resource roles)."""
        user7_has_general_role_d = self._create_user_for_perm_test("user7_general_role_d", role_names=[self.role_general_d.name])
        user8_no_general_role_d = self._create_user_for_perm_test("user8_no_general_role_d")


        # Resource D with invalid JSON in map_coordinates, but has general resource roles
        resource_d = self._create_resource_for_perm_test(
            "MalformedMapResourceD",
            map_coordinates_json_str="invalid_json_string",
            general_role_names=[self.role_general_d.name]
        )

        # User 7 (has Role_General_D): Can book Resource D (system falls back gracefully)
        response_user7 = self._make_booking_request(user7_has_general_role_d, resource_d.id)
        self.assertEqual(response_user7.status_code, 201, f"User7 with general role D failed to book malformed map resource. Response: {response_user7.get_json()}")
        if response_user7.status_code == 201: Booking.query.filter_by(id=response_user7.get_json()['bookings'][0]['id']).delete(); db.session.commit()

        # User 8 (no Role_General_D): Denied booking Resource D
        response_user8 = self._make_booking_request(user8_no_general_role_d, resource_d.id)
        self.assertEqual(response_user8.status_code, 403, f"User8 without general role D should be denied for malformed map resource. Response: {response_user8.get_json()}")
        if response_user8.status_code == 403:
             self.assertIn("You are not authorized to book this resource based on its permission settings", response_user8.get_json().get('error', ''))


# Define a helper method for creating an admin with manage_system, or ensure it's part of AppTests/TestAdminFunctionality
# For now, we'll assume self._create_admin_user_with_manage_system() exists or is adapted.

class TestAdminDbDataAPI(AppTests):
    def _create_admin_with_manage_system(self, username_suffix=""):
        """Creates an admin user with 'manage_system' permission."""
        admin_role = Role.query.filter_by(name="Administrator").first()
        if not admin_role:
            admin_role = Role(name="Administrator", permissions="all_permissions") # Assumes 'manage_system'
            db.session.add(admin_role)
            db.session.commit()

        admin_username = f"dbdata_admin{username_suffix}"
        admin_email = f"dbdata_admin{username_suffix}@example.com"

        admin_user = User.query.filter_by(username=admin_username).first()
        if not admin_user:
            admin_user = User(username=admin_username, email=admin_email, is_admin=True)
            admin_user.set_password("adminpass")
            db.session.add(admin_user) # Add first before roles for potential non-nullable user_id in association

        if admin_role not in admin_user.roles:
            admin_user.roles.append(admin_role)
        db.session.commit()
        return admin_user

    def setUp(self):
        super().setUp()
        self.admin_user = self._create_admin_with_manage_system()
        self.login(self.admin_user.username, "adminpass")

        # Create some sample users for testing on the 'user' table
        # Clear existing users first to ensure predictable IDs if needed, except the logged-in admin
        User.query.filter(User.id != self.admin_user.id).delete()
        db.session.commit()

        self.user1 = User(username='alpha_user', email='alpha@example.com', google_id=None)
        self.user1.set_password('pass1')
        self.user2 = User(username='beta_user', email='beta@example.com', google_id='google123')
        self.user2.set_password('pass2')
        self.user3 = User(username='gamma_user_test', email='gamma@example.com', google_id=None)
        self.user3.set_password('pass3')
        db.session.add_all([self.user1, self.user2, self.user3])
        db.session.commit()


    def tearDown(self):
        self.logout() # Logout the admin user
        super().tearDown()


    def test_get_db_table_data_basic_fetch(self):
        """Test basic data fetch from /api/admin/db/table_data/<table_name>."""
        response = self.client.get('/api/admin/db/table_data/user')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['table_name'], 'user')
        self.assertIsInstance(data['records'], list)
        self.assertTrue(len(data['records']) >= 3) # Admin + 3 created users
        self.assertIn('pagination', data)
        self.assertEqual(data['pagination']['page'], 1)
        self.assertIn('columns', data)
        self.assertIsInstance(data['columns'], list)
        self.assertTrue(any(col['name'] == 'username' for col in data['columns']))

    def test_get_db_table_data_pagination(self):
        """Test pagination for /api/admin/db/table_data/."""
        # We have admin + 3 users = 4 users.
        # Page 1, 2 per page
        response = self.client.get('/api/admin/db/table_data/user?page=1&per_page=2')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['records']), 2)
        self.assertEqual(data['pagination']['page'], 1)
        self.assertEqual(data['pagination']['per_page'], 2)
        self.assertTrue(data['pagination']['total_records'] >= 4)
        self.assertTrue(data['pagination']['total_pages'] >= 2)

        # Page 2, 2 per page
        response_p2 = self.client.get('/api/admin/db/table_data/user?page=2&per_page=2')
        self.assertEqual(response_p2.status_code, 200)
        data_p2 = response_p2.get_json()
        self.assertTrue(data_p2['success'])
        self.assertEqual(len(data_p2['records']), 2 if data['pagination']['total_records'] >=4 else data['pagination']['total_records'] - 2 ) # Handles if total is less than 4
        self.assertEqual(data_p2['pagination']['page'], 2)

    def test_get_db_table_data_sorting(self):
        """Test sorting for /api/admin/db/table_data/."""
        # Ascending
        response_asc = self.client.get('/api/admin/db/table_data/user?sort_by=username&sort_order=asc')
        self.assertEqual(response_asc.status_code, 200)
        data_asc = response_asc.get_json()
        self.assertTrue(data_asc['success'])
        usernames_asc = [r['username'] for r in data_asc['records']]
        self.assertEqual(usernames_asc, sorted(usernames_asc))

        # Descending
        response_desc = self.client.get('/api/admin/db/table_data/user?sort_by=username&sort_order=desc')
        self.assertEqual(response_desc.status_code, 200)
        data_desc = response_desc.get_json()
        self.assertTrue(data_desc['success'])
        usernames_desc = [r['username'] for r in data_desc['records']]
        self.assertEqual(usernames_desc, sorted(usernames_desc, reverse=True))

    def test_get_db_table_data_filtering(self):
        """Test filtering for /api/admin/db/table_data/."""
        # EQ filter
        filters_eq = [{"column": "username", "op": "eq", "value": "alpha_user"}]
        response_eq = self.client.get(f'/api/admin/db/table_data/user?filters={urllib.parse.quote(json.dumps(filters_eq))}')
        self.assertEqual(response_eq.status_code, 200)
        data_eq = response_eq.get_json()
        self.assertTrue(data_eq['success'])
        self.assertEqual(len(data_eq['records']), 1)
        self.assertEqual(data_eq['records'][0]['username'], 'alpha_user')

        # ILIKE filter
        filters_ilike = [{"column": "username", "op": "ilike", "value": "%_user_test%"}]
        response_ilike = self.client.get(f'/api/admin/db/table_data/user?filters={urllib.parse.quote(json.dumps(filters_ilike))}')
        self.assertEqual(response_ilike.status_code, 200)
        data_ilike = response_ilike.get_json()
        self.assertTrue(data_ilike['success'])
        self.assertEqual(len(data_ilike['records']), 1)
        self.assertEqual(data_ilike['records'][0]['username'], 'gamma_user_test')

        # IS_NULL filter (on google_id for user1 and user3)
        filters_isnull = [{"column": "google_id", "op": "is_null", "value": ""}] # Value is ignored by backend
        response_isnull = self.client.get(f'/api/admin/db/table_data/user?filters={urllib.parse.quote(json.dumps(filters_isnull))}')
        self.assertEqual(response_isnull.status_code, 200)
        data_isnull = response_isnull.get_json()
        self.assertTrue(data_isnull['success'])
        self.assertTrue(len(data_isnull['records']) >= 2) # admin, user1, user3 might have null google_id
        self.assertTrue(any(r['username'] == 'alpha_user' for r in data_isnull['records']))
        self.assertTrue(any(r['username'] == 'gamma_user_test' for r in data_isnull['records']))

        # IS_NOT_NULL filter (on google_id for user2)
        filters_isnotnull = [{"column": "google_id", "op": "is_not_null", "value": ""}]
        response_isnotnull = self.client.get(f'/api/admin/db/table_data/user?filters={urllib.parse.quote(json.dumps(filters_isnotnull))}')
        self.assertEqual(response_isnotnull.status_code, 200)
        data_isnotnull = response_isnotnull.get_json()
        self.assertTrue(data_isnotnull['success'])
        self.assertEqual(len(data_isnotnull['records']), 1)
        self.assertEqual(data_isnotnull['records'][0]['username'], 'beta_user')

        # IN filter
        user_ids_for_in_filter = f"{self.user1.id},{self.user3.id}"
        filters_in = [{"column": "id", "op": "in", "value": user_ids_for_in_filter}]
        response_in = self.client.get(f'/api/admin/db/table_data/user?filters={urllib.parse.quote(json.dumps(filters_in))}')
        self.assertEqual(response_in.status_code, 200)
        data_in = response_in.get_json()
        self.assertTrue(data_in['success'])
        self.assertEqual(len(data_in['records']), 2)
        usernames_in = {r['username'] for r in data_in['records']}
        self.assertEqual(usernames_in, {'alpha_user', 'gamma_user_test'})


    def test_get_db_table_data_invalid_table(self):
        """Test /api/admin/db/table_data/ with a non-existent table."""
        response = self.client.get('/api/admin/db/table_data/non_existent_table_qwerty')
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertFalse(data['success'])
        self.assertEqual(data['message'], 'Table not found.')

    def test_get_db_table_data_invalid_filter_column(self):
        """Test /api/admin/db/table_data/ with an invalid filter column."""
        filters = [{"column": "invalid_column_name", "op": "eq", "value": "test"}]
        response = self.client.get(f'/api/admin/db/table_data/user?filters={urllib.parse.quote(json.dumps(filters))}')
        # The backend currently logs a warning and skips the filter. So it would return 200.
        # To make it a 400, the backend would need to explicitly check and raise an error.
        # For now, let's assume it skips and returns 200 with all data.
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        # Add more specific check if backend starts returning error for this.

    def test_get_db_table_data_invalid_filter_json(self):
        """Test /api/admin/db/table_data/ with malformed JSON filter."""
        response = self.client.get('/api/admin/db/table_data/user?filters=thisisnotjson')
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data['success'])
        self.assertIn('Invalid filters format: Not valid JSON.', data['message'])

if __name__ == '__main__':
    unittest.main()
