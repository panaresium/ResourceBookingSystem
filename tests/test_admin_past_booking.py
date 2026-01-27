import unittest
import json
from datetime import datetime, timedelta, timezone as timezone_original
from datetime import datetime as datetime_original, timedelta as timedelta_original
from unittest.mock import patch, MagicMock
from app import app
from extensions import db
from models import User, Resource, Booking, FloorMap, BookingSettings, Role

class TestAdminPastBooking(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['LOGIN_DISABLED'] = False
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SECRET_KEY'] = 'test_secret_key' # Ensure secret key
        self.app.config['SERVER_NAME'] = 'localhost.test'

        self.app_context = self.app.app_context()
        self.app_context.push()

        db.drop_all()
        db.create_all()

        # Create Super Admin (to satisfy check_setup_required)
        self.super_admin = User(username='superadmin', email='super@test.com', is_admin=True)
        self.super_admin.set_password('password')
        db.session.add(self.super_admin)

        # Create Admin Role
        self.admin_role = Role(name="Admin", permissions="manage_bookings")
        db.session.add(self.admin_role)

        # Create Admin User (Booking Manager - checks role based permission)
        self.admin_user = User(username='admin', email='admin@test.com', is_admin=False)
        self.admin_user.set_password('password')
        self.admin_user.roles.append(self.admin_role)
        db.session.add(self.admin_user)

        # Create Regular User
        self.user = User(username='user', email='user@test.com', is_admin=False)
        self.user.set_password('password')
        db.session.add(self.user)

        # Create Resource
        self.resource = Resource(name="TestRes", status="published")
        db.session.add(self.resource)

        # Create Settings (Past bookings DISABLED)
        self.settings = BookingSettings(allow_past_bookings=False, past_booking_time_adjustment_hours=0)
        db.session.add(self.settings)

        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def login_manual(self, user):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True

    @patch('routes.api_bookings.get_current_effective_time')
    def test_admin_can_book_past_date(self, mock_get_time):
        # Mock time to "now"
        now = datetime_original(2025, 1, 1, 12, 0, 0, tzinfo=timezone_original.utc)
        mock_get_time.return_value = now

        # Login as Admin User (who has manage_bookings role)
        self.login_manual(self.admin_user)

        # Booking for 1 hour ago
        start_time = now - timedelta_original(hours=1)
        end_time = now

        payload = {
            'resource_id': self.resource.id,
            'user_name': 'admin',
            'date_str': start_time.strftime('%Y-%m-%d'),
            'start_time_str': start_time.strftime('%H:%M'),
            'end_time_str': end_time.strftime('%H:%M'),
            'title': 'Admin Past Booking'
        }

        response = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 201, f"Admin should be able to book past. Status: {response.status_code}, Data: {response.data}")

    @patch('routes.api_bookings.get_current_effective_time')
    def test_regular_user_cannot_book_past_date(self, mock_get_time):
        # Mock time to "now"
        now = datetime_original(2025, 1, 1, 12, 0, 0, tzinfo=timezone_original.utc)
        mock_get_time.return_value = now

        # Login as Regular User
        self.login_manual(self.user)

        # Booking for 1 hour ago
        start_time = now - timedelta_original(hours=1)
        end_time = now

        payload = {
            'resource_id': self.resource.id,
            'user_name': 'user',
            'date_str': start_time.strftime('%Y-%m-%d'),
            'start_time_str': start_time.strftime('%H:%M'),
            'end_time_str': end_time.strftime('%H:%M'),
            'title': 'User Past Booking'
        }

        response = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 400, f"Regular user should NOT be able to book past. Status: {response.status_code}, Data: {response.data}")
        self.assertIn("outside the allowed window", response.get_json()['error'])

if __name__ == '__main__':
    unittest.main()
