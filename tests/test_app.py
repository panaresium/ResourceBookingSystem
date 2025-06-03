import unittest
import unittest.mock
import json
from sqlalchemy import text

from datetime import datetime, time, date, timedelta

from app import app, db, User, Resource, Booking, WaitlistEntry, FloorMap, AuditLog, email_log, teams_log, slack_log
from models import BookingSettings # Import the new model

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
        self.assertIn(b'Resource Usage Analytics', resp_admin.data) # Check for some content

    def test_analytics_bookings_data_endpoint(self):
        """Validate JSON structure returned by bookings data endpoint."""
        admin_user = self._create_admin_user(username="analyticsadmin2", email_ext="analytics2")
        self.login(admin_user.username, 'adminpass')
        
        # Create a booking for analytics data (ensure resource1 is used from AppTests setup)
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
        self.assertIn(self.resource1.name, html_content) # Room A

        self.assertIn(booking2.title, html_content)
        self.assertIn(booking2.user_name, html_content) # testuser2
        self.assertIn(self.resource2.name, html_content) # Room B
        self.logout()

    def test_admin_cancel_booking_permission(self):
        """Test permissions for the admin cancel booking API endpoint."""
        booking = self._create_booking(user_name='testuser', resource_id=self.resource1.id, start_offset_hours=1)

        # Unauthenticated
        response_unauth = self.client.post(f'/api/admin/bookings/{booking.id}/cancel')
        self.assertEqual(response_unauth.status_code, 401) # Expect 401 for API if not logged in

        # Non-admin login
        self.login('testuser', 'password')
        response_non_admin = self.client.post(f'/api/admin/bookings/{booking.id}/cancel')
        self.assertEqual(response_non_admin.status_code, 403)
        self.logout()

        # Admin with permission should be tested in functionality test

    def test_admin_cancel_booking_functionality(self):
        """Test functionality of admin cancelling a booking."""
        admin = self._create_admin_user()
        self.login(admin.username, 'adminpass')

        booking_user = User.query.filter_by(username='testuser').first()
        booking = self._create_booking(user_name=booking_user.username, resource_id=self.resource1.id, start_offset_hours=1, title="To Be Cancelled")
        initial_status = booking.status
        self.assertNotEqual(initial_status, 'cancelled')

        response = self.client.post(f'/api/admin/bookings/{booking.id}/cancel')
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertTrue(json_data.get('message'), 'Booking cancelled successfully')
        self.assertEqual(json_data.get('new_status'), 'cancelled')

        # Verify booking status in DB
        updated_booking = Booking.query.get(booking.id)
        self.assertEqual(updated_booking.status, 'cancelled')

        # Verify audit log
        audit_log = AuditLog.query.filter(
            AuditLog.action == "ADMIN_CANCEL_BOOKING",
            AuditLog.user_id == admin.id
        ).order_by(AuditLog.id.desc()).first()

        self.assertIsNotNone(audit_log)
        self.assertIn(f"Admin '{admin.username}' cancelled booking ID {booking.id}", audit_log.details)
        self.assertIn(f"Booked by: '{booking_user.username}'", audit_log.details)
        self.assertIn(f"Resource: '{self.resource1.name}'", audit_log.details)
        self.assertIn(f"Title: '{booking.title}'", audit_log.details)
        self.logout()

    def test_admin_cancel_already_cancelled_booking(self):
        """Test attempting to cancel an already cancelled booking by admin."""
        admin = self._create_admin_user()
        self.login(admin.username, 'adminpass')

        booking = self._create_booking(user_name='testuser', resource_id=self.resource1.id, start_offset_hours=1)

        # First cancellation
        response_first_cancel = self.client.post(f'/api/admin/bookings/{booking.id}/cancel')
        self.assertEqual(response_first_cancel.status_code, 200)
        self.assertEqual(Booking.query.get(booking.id).status, 'cancelled')

        # Attempt to cancel again
        response_second_cancel = self.client.post(f'/api/admin/bookings/{booking.id}/cancel')
        self.assertEqual(response_second_cancel.status_code, 400)
        json_data = response_second_cancel.get_json()
        self.assertIn('already in a terminal state', json_data.get('error', '').lower())
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
            'enable_check_in_out': 'on'
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
            'enable_check_in_out': 'on'
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

        # Test modifying a single field
        retrieved_settings.max_booking_days_in_future = None
        db.session.commit()
        modified_settings = BookingSettings.query.get(settings.id)
        self.assertIsNone(modified_settings.max_booking_days_in_future)


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


if __name__ == '__main__':
    unittest.main()
