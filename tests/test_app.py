import unittest
import unittest.mock
import json
from sqlalchemy import text

from datetime import datetime, time, date, timedelta

from app import app, db, User, Resource, Booking, WaitlistEntry, FloorMap, AuditLog, email_log, teams_log, slack_log

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


class TestBookingUserActions(AppTests):
    def _create_booking(self, user_name, resource_id, start_offset_hours, duration_hours=1, title="Test Booking"):
        """Helper to create a booking."""
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
        self.assertEqual(datetime.fromisoformat(data['start_time']), new_start_time)
        self.assertEqual(datetime.fromisoformat(data['end_time']), new_end_time)

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
        self.assertEqual(len(json_data_pending), 1)
        self.assertEqual(json_data_pending[0]['id'], booking_id)

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

if __name__ == '__main__':
    unittest.main()
