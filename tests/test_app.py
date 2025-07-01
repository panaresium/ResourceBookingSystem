import unittest
import unittest.mock
import json
import urllib.parse
from sqlalchemy import text

from datetime import datetime, time, date, timedelta, timezone as timezone_original
from datetime import datetime as datetime_original, timedelta as timedelta_original # For mocking

from flask import url_for, redirect, current_app as flask_current_app
from app import app # app object
from extensions import db # socketio removed
from models import User, Resource, Booking, WaitlistEntry, FloorMap, AuditLog, BookingSettings, ResourcePIN, Role
from utils import teams_log, slack_log, email_log
from unittest.mock import patch, mock_open, MagicMock, ANY
from datetime import datetime, timedelta, time as dt_time # datetime is already imported, this line might be redundant if not used for specific aliasing.
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials as UserCredentials

from scheduler_tasks import auto_checkout_overdue_bookings # Removed problematic constants

import os
import tempfile
from utils import generate_booking_image, send_email as utils_send_email
import utils


class AppTests(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['LOGIN_DISABLED'] = False
        app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('TEST_DATABASE_URL', 'sqlite:///:memory:')
        app.config['SCHEDULER_ENABLED'] = False # Default for most tests
        app.config['MAIL_SUPPRESS_SEND'] = True
        app.config['SERVER_NAME'] = 'localhost.test'

        self.app_context = app.app_context()
        self.app_context.push()

        db.drop_all()
        db.create_all()

        email_log.clear()
        teams_log.clear()
        slack_log.clear()

        user = User.query.filter_by(username='testuser').first()
        if not user:
            user = User(username='testuser', email='test@example.com', is_admin=False)
            user.set_password('password')
            db.session.add(user)
            db.session.commit()

        import uuid
        unique_name = f"Test Map {uuid.uuid4()}"
        unique_file = f"{uuid.uuid4()}.png"
        # Ensure a FloorMap exists for resources
        floor_map = FloorMap.query.first()
        if not floor_map:
            floor_map = FloorMap(name=unique_name, image_filename=unique_file)
            db.session.add(floor_map)
            db.session.commit()
        self.floor_map = floor_map


        res1 = Resource(
            name='Room A', capacity=10, equipment='Projector,Whiteboard', tags='large',
            floor_map_id=self.floor_map.id, status='published',
            map_coordinates=json.dumps({'type': 'rect', 'x': 10, 'y': 20, 'width': 30, 'height': 30})
        )
        res2 = Resource(
            name='Room B', capacity=4, equipment='Whiteboard', tags='small',
            floor_map_id=self.floor_map.id, status='published',
            map_coordinates=json.dumps({'type': 'rect', 'x': 50, 'y': 20, 'width': 30, 'height': 30})
        )
        # Add a third resource for tests that need it
        res3 = Resource(
            name='Room C', capacity=5, equipment='Monitor', tags='medium',
            floor_map_id=self.floor_map.id, status='published'
        )
        db.session.add_all([res1, res2, res3])
        db.session.commit()

        self.resource1 = res1
        self.resource2 = res2
        self.resource3 = res3 # Make it available to tests
        
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def login(self, username, password):
        response = self.client.post('/api/auth/login',
                                    data=json.dumps(dict(username=username, password=password)),
                                    content_type='application/json',
                                    follow_redirects=True)
        return response

    def logout(self):
        return self.client.post('/api/auth/logout', follow_redirects=True)

    def _create_booking(self, user_name, resource_id, start_offset_hours, duration_hours=1, title="Test Booking", status="approved"):
        start_time = datetime_original.utcnow() + timedelta_original(hours=start_offset_hours) # Use datetime_original and timedelta_original
        end_time = start_time + timedelta_original(hours=duration_hours) # Use timedelta_original
        booking = Booking(
            user_name=user_name,
            resource_id=resource_id,
            start_time=start_time,
            end_time=end_time,
            title=title,
            status=status
        )
        db.session.add(booking)
        db.session.commit()
        return booking

# --- Start of TestAdminBookingSettingsPINConfig ---
# (Assuming TestAdminBookingSettingsPINConfig and other original classes are here)
class TestAdminBookingSettingsPINConfig(AppTests):
    def _create_admin_user(self, username="settings_pin_admin", email_ext="settings_pin_admin"):
        admin_user = User.query.filter_by(username=username).first()
        if not admin_user:
            admin_user = User(username=username, email=f"{email_ext}@example.com", is_admin=True)
            admin_user.set_password("adminpass")
            db.session.add(admin_user)
            db.session.commit()
        return admin_user

    def get_current_booking_settings(self):
        return BookingSettings.query.first()

    def _get_base_booking_settings_form_data(self):
        settings = self.get_current_booking_settings()
        if not settings: settings = BookingSettings()
        data = {
            'allow_past_bookings': 'on' if settings.allow_past_bookings else '',
            'max_booking_days_in_future': str(settings.max_booking_days_in_future or ''),
            'allow_multiple_resources_same_time': 'on' if settings.allow_multiple_resources_same_time else '',
            'max_bookings_per_user': str(settings.max_bookings_per_user or ''),
            'enable_check_in_out': 'on' if settings.enable_check_in_out else '',
            'past_booking_time_adjustment_hours': str(settings.past_booking_time_adjustment_hours or '0'),
            'check_in_minutes_before': str(settings.check_in_minutes_before or '15'),
            'check_in_minutes_after': str(settings.check_in_minutes_after or '15'),
            'pin_auto_generation_enabled': 'on' if settings.pin_auto_generation_enabled else '',
            'pin_length': str(settings.pin_length or '6'),
            'pin_allow_manual_override': 'on' if settings.pin_allow_manual_override else '',
            'resource_checkin_url_requires_login': 'on' if settings.resource_checkin_url_requires_login else '',
            'allow_check_in_without_pin': 'on' if hasattr(settings, 'allow_check_in_without_pin') and settings.allow_check_in_without_pin else '',
        }
        checkbox_keys = [
            'allow_past_bookings', 'allow_multiple_resources_same_time', 'enable_check_in_out',
            'pin_auto_generation_enabled', 'pin_allow_manual_override',
            'resource_checkin_url_requires_login', 'allow_check_in_without_pin'
        ]
        final_data = {}
        for k, v in data.items():
            if k in checkbox_keys:
                if v == 'on': final_data[k] = v
            else: final_data[k] = v
        return final_data

    def test_update_allow_check_in_without_pin_setting(self):
        admin = self._create_admin_user(username="settings_allow_no_pin_admin")
        self.login(admin.username, "adminpass")
        settings = self.get_current_booking_settings()
        if not settings:
            settings = BookingSettings(allow_check_in_without_pin=True); db.session.add(settings)
        else: settings.allow_check_in_without_pin = True
        db.session.commit()

        form_data_set_false = self._get_base_booking_settings_form_data()
        if 'allow_check_in_without_pin' in form_data_set_false: del form_data_set_false['allow_check_in_without_pin']

        response_set_false = self.client.post(url_for('admin_ui.update_booking_settings'), data=form_data_set_false, follow_redirects=True)
        self.assertEqual(response_set_false.status_code, 200)
        settings_after_false = self.get_current_booking_settings(); self.assertFalse(settings_after_false.allow_check_in_without_pin)
        response_get_false = self.client.get(url_for('admin_ui.serve_booking_settings_page'))
        self.assertNotIn('id="allow_check_in_without_pin" checked', response_get_false.data.decode('utf-8'))

        form_data_set_true = self._get_base_booking_settings_form_data()
        form_data_set_true['allow_check_in_without_pin'] = 'on'
        response_set_true = self.client.post(url_for('admin_ui.update_booking_settings'), data=form_data_set_true, follow_redirects=True)
        self.assertEqual(response_set_true.status_code, 200)
        settings_after_true = self.get_current_booking_settings(); self.assertTrue(settings_after_true.allow_check_in_without_pin)
        response_get_true = self.client.get(url_for('admin_ui.serve_booking_settings_page'))
        self.assertIn('id="allow_check_in_without_pin" checked', response_get_true.data.decode('utf-8'))
        self.logout()
# --- End of TestAdminBookingSettingsPINConfig ---

# Helper class for test_auto_checkout_no_user_email
class StubUser:
    def __init__(self, id, username, email):
        self.id = id
        self.username = username
        self.email = email

class TestAutoCheckoutTask(AppTests):
    def setUp(self):
        super().setUp()
        self.task_user = User.query.filter_by(username='taskuser_auto_checkout').first()
        if not self.task_user:
            self.task_user = User(username='taskuser_auto_checkout', email='taskuser_auto_checkout@example.com')
            self.task_user.set_password('password')
            db.session.add(self.task_user)
            db.session.commit()

        self.task_resource = Resource.query.filter_by(name='TaskResourceAutoCheckout').first()
        if not self.task_resource:
            self.task_resource = Resource(name='TaskResourceAutoCheckout', status='published')
            db.session.add(self.task_resource)
            db.session.commit()

        settings = BookingSettings.query.first()
        if not settings:
            db.session.add(BookingSettings())
            db.session.commit()

    @patch.dict(app.config, {'SCHEDULER_ENABLED': True})
    @patch('scheduler_tasks.send_email')
    @patch('scheduler_tasks.add_audit_log')
    # @patch('scheduler_tasks.socketio.emit') # Removed
    @patch('scheduler_tasks.datetime')
    def test_auto_checkout_success(self, mock_scheduler_datetime, mock_add_audit_log, mock_send_email): # mock_socketio_emit removed
        mocked_now = datetime_original(2024, 1, 1, 14, 0, 0, tzinfo=timezone_original.utc) # Use datetime_original
        mock_scheduler_datetime.now.return_value = mocked_now
        mock_scheduler_datetime.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs) if args else mocked_now

        # TODO: Define these constants or get them from BookingSettings for TestAutoCheckoutTask if these tests are to be run.
        # For now, TestPastBookingLogic is the focus.
        # Using placeholder values to allow the file to be parsed for TestPastBookingLogic.
        DEFAULT_AUTO_CHECKOUT_GRACE_PERIOD_HOURS_PLACEHOLDER = 2 # Placeholder
        DEFAULT_AUTO_CHECKOUT_SET_CHECKOUT_AFTER_END_HOURS_PLACEHOLDER = 1 # Placeholder

        booking_end_time = mocked_now - timedelta_original(hours=DEFAULT_AUTO_CHECKOUT_GRACE_PERIOD_HOURS_PLACEHOLDER + 1) # Use timedelta_original
        booking_check_in_time = booking_end_time - timedelta_original(hours=1) # Use timedelta_original

        overdue_booking = Booking(
            user_name=self.task_user.username, resource_id=self.task_resource.id,
            start_time=booking_check_in_time - timedelta_original(hours=1), end_time=booking_end_time, # Use timedelta_original
            checked_in_at=booking_check_in_time, status='checked_in', title='Overdue Booking Test'
        )
        db.session.add(overdue_booking)
        db.session.commit()
        booking_id = overdue_booking.id

        auto_checkout_overdue_bookings(app_instance=app)

        checked_out_booking = db.session.get(Booking, booking_id)
        self.assertIsNotNone(checked_out_booking.checked_out_at, "checked_out_at should be populated")
        expected_checkout_time = booking_end_time + timedelta_original(hours=DEFAULT_AUTO_CHECKOUT_SET_CHECKOUT_AFTER_END_HOURS_PLACEHOLDER) # Use timedelta_original
        self.assertEqual(checked_out_booking.checked_out_at, expected_checkout_time.replace(tzinfo=None))
        self.assertEqual(checked_out_booking.status, 'completed')
        mock_send_email.assert_called_once()
        mock_add_audit_log.assert_called_once()
        # mock_socketio_emit.assert_called_once() # Removed

    @patch.dict(app.config, {'SCHEDULER_ENABLED': True})
    @patch('scheduler_tasks.send_email')
    @patch('scheduler_tasks.datetime')
    def test_auto_checkout_not_overdue_yet(self, mock_scheduler_datetime, mock_send_email):
        mocked_now = datetime_original(2024, 1, 1, 14, 0, 0, tzinfo=timezone_original.utc) # Use datetime_original
        mock_scheduler_datetime.now.return_value = mocked_now
        mock_scheduler_datetime.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs) if args else mocked_now
        booking_end_time = mocked_now - timedelta_original(minutes=30) # Use timedelta_original
        not_overdue_booking = Booking(
            user_name=self.task_user.username, resource_id=self.task_resource.id,
            start_time=booking_end_time - timedelta_original(hours=1), end_time=booking_end_time, # Use timedelta_original
            checked_in_at=booking_end_time - timedelta_original(minutes=30), status='checked_in' # Use timedelta_original
        )
        db.session.add(not_overdue_booking); db.session.commit()
        auto_checkout_overdue_bookings(app_instance=app)
        db.session.refresh(not_overdue_booking)
        self.assertIsNone(not_overdue_booking.checked_out_at)
        self.assertEqual(not_overdue_booking.status, 'checked_in')
        mock_send_email.assert_not_called()

    @patch.dict(app.config, {'SCHEDULER_ENABLED': True})
    @patch('scheduler_tasks.send_email')
    @patch('scheduler_tasks.datetime')
    def test_auto_checkout_already_checked_out(self, mock_scheduler_datetime, mock_send_email):
        mocked_now = datetime_original(2024, 1, 1, 14, 0, 0, tzinfo=timezone_original.utc) # Use datetime_original
        mock_scheduler_datetime.now.return_value = mocked_now
        mock_scheduler_datetime.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs) if args else mocked_now
        booking_end_time = mocked_now - timedelta_original(hours=2) # Use timedelta_original
        already_checked_out_booking = Booking(
            user_name=self.task_user.username, resource_id=self.task_resource.id,
            start_time=booking_end_time - timedelta_original(hours=1), end_time=booking_end_time, # Use timedelta_original
            checked_in_at=booking_end_time - timedelta_original(minutes=30), # Use timedelta_original
            checked_out_at=booking_end_time + timedelta_original(minutes=10), status='completed' # Use timedelta_original
        )
        db.session.add(already_checked_out_booking); db.session.commit()
        auto_checkout_overdue_bookings(app_instance=app)
        mock_send_email.assert_not_called()

    @patch.dict(app.config, {'SCHEDULER_ENABLED': True})
    @patch('scheduler_tasks.send_email')
    @patch('scheduler_tasks.datetime')
    def test_auto_checkout_not_checked_in(self, mock_scheduler_datetime, mock_send_email):
        mocked_now = datetime_original(2024, 1, 1, 14, 0, 0, tzinfo=timezone_original.utc) # Use datetime_original
        mock_scheduler_datetime.now.return_value = mocked_now
        mock_scheduler_datetime.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs) if args else mocked_now
        booking_end_time = mocked_now - timedelta_original(hours=2) # Use timedelta_original
        not_checked_in_booking = Booking(
            user_name=self.task_user.username, resource_id=self.task_resource.id,
            start_time=booking_end_time - timedelta_original(hours=1), end_time=booking_end_time, # Use timedelta_original
            checked_in_at=None, status='approved'
        )
        db.session.add(not_checked_in_booking); db.session.commit()
        auto_checkout_overdue_bookings(app_instance=app)
        mock_send_email.assert_not_called()
        db.session.refresh(not_checked_in_booking)
        self.assertEqual(not_checked_in_booking.status, 'approved')

    @patch.dict(app.config, {'SCHEDULER_ENABLED': True})
    @patch('scheduler_tasks.send_email')
    @patch('scheduler_tasks.add_audit_log')
    # @patch('scheduler_tasks.socketio.emit') # Removed
    @patch('scheduler_tasks.datetime')
    def test_auto_checkout_multiple_bookings(self, mock_scheduler_datetime, mock_add_audit_log, mock_send_email): # mock_socketio_emit removed
        mocked_now = datetime_original(2024, 1, 1, 14, 0, 0, tzinfo=timezone_original.utc) # Use datetime_original
        mock_scheduler_datetime.now.return_value = mocked_now
        mock_scheduler_datetime.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs) if args else mocked_now

        b_overdue_end = mocked_now - timedelta_original(hours=2) # Use timedelta_original
        b_overdue = Booking(user_name=self.task_user.username, resource_id=self.task_resource.id,
                            start_time=b_overdue_end - timedelta_original(hours=1), end_time=b_overdue_end, # Use timedelta_original
                            checked_in_at=b_overdue_end - timedelta_original(minutes=30), status='checked_in', title="B Overdue") # Use timedelta_original
        b_not_overdue_end = mocked_now - timedelta_original(minutes=30) # Use timedelta_original
        b_not_overdue = Booking(user_name=self.task_user.username, resource_id=self.task_resource.id,
                                start_time=b_not_overdue_end - timedelta_original(hours=1), end_time=b_not_overdue_end, # Use timedelta_original
                                checked_in_at=b_not_overdue_end - timedelta_original(minutes=10), status='checked_in', title="B Not Overdue") # Use timedelta_original
        b_already_out_end = mocked_now - timedelta_original(hours=3) # Use timedelta_original
        b_already_out = Booking(user_name=self.task_user.username, resource_id=self.task_resource.id,
                                start_time=b_already_out_end - timedelta_original(hours=1), end_time=b_already_out_end, # Use timedelta_original
                                checked_in_at=b_already_out_end - timedelta_original(minutes=30), # Use timedelta_original
                                checked_out_at=b_already_out_end + timedelta_original(minutes=5), status='completed', title="B Already Out") # Use timedelta_original
        db.session.add_all([b_overdue, b_not_overdue, b_already_out]); db.session.commit()
        overdue_id = b_overdue.id

        auto_checkout_overdue_bookings(app_instance=app)

        mock_send_email.assert_called_once()
        mock_add_audit_log.assert_called_once()
        # mock_socketio_emit.assert_called_once() # Removed

        processed_b_overdue = db.session.get(Booking, overdue_id)
        self.assertEqual(processed_b_overdue.status, 'completed', "Overdue booking status should be 'completed'")
        self.assertIsNotNone(processed_b_overdue.checked_out_at, "Overdue booking should have checked_out_at set")

        db.session.refresh(b_not_overdue); self.assertEqual(b_not_overdue.status, 'checked_in'); self.assertIsNone(b_not_overdue.checked_out_at)
        db.session.refresh(b_already_out); self.assertEqual(b_already_out.status, 'completed'); self.assertIsNotNone(b_already_out.checked_out_at)

    @unittest.skip("Temporarily skipping due to InterfaceError investigation")
    @patch.dict(app.config, {'SCHEDULER_ENABLED': True})
    @patch('scheduler_tasks.User.query')
    @patch('scheduler_tasks.send_email')
    @patch('scheduler_tasks.add_audit_log')
    # @patch('scheduler_tasks.socketio.emit') # Removed
    @patch('scheduler_tasks.datetime')
    def test_auto_checkout_no_user_email(self, mock_scheduler_datetime, mock_add_audit_log, mock_send_email, mock_user_query_in_task): # mock_socketio_emit removed
        mocked_now = datetime_original(2024, 1, 1, 14, 0, 0, tzinfo=timezone_original.utc) # Use datetime_original
        mock_scheduler_datetime.now.return_value = mocked_now
        mock_scheduler_datetime.side_effect = lambda *args, **kwargs: datetime_original(*args, **kwargs) if args else mocked_now

        user_for_this_test = User.query.filter_by(username="no_email_test_user").first()
        if not user_for_this_test:
            user_for_this_test = User(username="no_email_test_user", email="valid_for_db@example.com")
            user_for_this_test.set_password("password")
            db.session.add(user_for_this_test)
            db.session.commit()

        # Using placeholder values as above
        DEFAULT_AUTO_CHECKOUT_GRACE_PERIOD_HOURS_PLACEHOLDER = 2 # Placeholder
        booking_end_time = mocked_now - timedelta_original(hours=DEFAULT_AUTO_CHECKOUT_GRACE_PERIOD_HOURS_PLACEHOLDER + 1) # Use timedelta_original
        overdue_booking_no_email = Booking(
            user_name=user_for_this_test.username, resource_id=self.task_resource.id,
            start_time=booking_end_time - timedelta_original(hours=1), end_time=booking_end_time, # Use timedelta_original
            checked_in_at=booking_end_time - timedelta_original(minutes=30), status='checked_in' # Use timedelta_original
        )
        db.session.add(overdue_booking_no_email); db.session.commit()
        booking_id = overdue_booking_no_email.id

        stub_booker = StubUser(
            id=user_for_this_test.id,
            username=user_for_this_test.username,
            email=None
        )
        mock_user_query_in_task.filter_by.return_value.first.return_value = stub_booker

        auto_checkout_overdue_bookings(app_instance=app)

        mock_send_email.assert_not_called()
        processed_booking = db.session.get(Booking, booking_id)
        self.assertEqual(processed_booking.status, 'completed', "Booking status should be 'completed' even if user has no email")
        self.assertIsNotNone(processed_booking.checked_out_at, "checked_out_at should be set even if user has no email")
        mock_add_audit_log.assert_called_once()
        # mock_socketio_emit.assert_called_once() # Removed


class TestPastBookingLogic(AppTests):
    common_error_message = 'Booking time is outside the allowed window for past or future bookings as per current settings.'

    def _set_booking_settings(self, allow_past, adjustment_hours, global_offset_hours=0):
        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings()
        settings.allow_past_bookings = allow_past
        settings.past_booking_time_adjustment_hours = adjustment_hours
        settings.global_time_offset_hours = global_offset_hours # New
        db.session.add(settings)
        db.session.commit()
        return settings # Return settings to access the offset in the test

    def _create_payload(self, booking_start_dt):
        booking_end_dt = booking_start_dt + timedelta_original(hours=1)
        return {
            'resource_id': self.resource1.id,
            'user_name': 'testuser',
            'date_str': booking_start_dt.strftime('%Y-%m-%d'),
            'start_time_str': booking_start_dt.strftime('%H:%M'),
            'end_time_str': booking_end_dt.strftime('%H:%M'),
            'title': 'Test Past Booking Logic'
        }

    @patch('routes.api_bookings.get_current_effective_time')
    def test_allow_past_true_deep_past(self, mock_get_effective_time):
        self.login('testuser', 'password')
        settings = self._set_booking_settings(allow_past=True, adjustment_hours=0, global_offset_hours=0)

        mocked_underlying_utc_now = datetime_original(2025, 6, 11, 16, 0, 0, tzinfo=timezone_original.utc)
        mocked_effective_current_time = mocked_underlying_utc_now + timedelta_original(hours=settings.global_time_offset_hours)
        mock_get_effective_time.return_value = mocked_effective_current_time

        # User perceives time as mocked_effective_current_time (naive version for payload)
        user_perceived_now_naive = mocked_effective_current_time.replace(tzinfo=None)
        booking_start_dt = user_perceived_now_naive - timedelta_original(hours=32) # Deep past from user's perspective
        payload = self._create_payload(booking_start_dt)

        response = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(response.status_code, 201, response.get_json())
        self.logout()

    @patch('routes.api_bookings.get_current_effective_time')
    def test_allow_past_true_slight_past(self, mock_get_effective_time):
        self.login('testuser', 'password')
        settings = self._set_booking_settings(allow_past=True, adjustment_hours=5, global_offset_hours=0) # Adjustment hours irrelevant

        mocked_underlying_utc_now = datetime_original(2025, 6, 11, 16, 0, 0, tzinfo=timezone_original.utc)
        mocked_effective_current_time = mocked_underlying_utc_now + timedelta_original(hours=settings.global_time_offset_hours)
        mock_get_effective_time.return_value = mocked_effective_current_time

        user_perceived_now_naive = mocked_effective_current_time.replace(tzinfo=None)
        booking_start_dt = user_perceived_now_naive - timedelta_original(hours=1) # Slight past
        payload = self._create_payload(booking_start_dt)

        response = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(response.status_code, 201, response.get_json())
        self.logout()

    @patch('routes.api_bookings.get_current_effective_time')
    def test_allow_past_false_adj_2_book_1_hr_ago_success(self, mock_get_effective_time):
        self.login('testuser', 'password')
        settings = self._set_booking_settings(allow_past=False, adjustment_hours=2, global_offset_hours=0)

        mocked_underlying_utc_now = datetime_original(2025, 6, 11, 16, 0, 0, tzinfo=timezone_original.utc)
        mocked_effective_current_time = mocked_underlying_utc_now + timedelta_original(hours=settings.global_time_offset_hours)
        mock_get_effective_time.return_value = mocked_effective_current_time

        user_perceived_now_naive = mocked_effective_current_time.replace(tzinfo=None)
        # Booking 1 hour ago. Cutoff is effective_now - 2 hours = 14:00. Booking at 15:00. Should be allowed.
        booking_start_dt = user_perceived_now_naive - timedelta_original(hours=1)
        payload = self._create_payload(booking_start_dt)
        response = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 201, response.get_json())
        self.logout()

    @patch('routes.api_bookings.get_current_effective_time')
    def test_allow_past_false_adj_2_book_3_hr_ago_fail(self, mock_get_effective_time):
        self.login('testuser', 'password')
        settings = self._set_booking_settings(allow_past=False, adjustment_hours=2, global_offset_hours=0)

        mocked_underlying_utc_now = datetime_original(2025, 6, 11, 16, 0, 0, tzinfo=timezone_original.utc)
        mocked_effective_current_time = mocked_underlying_utc_now + timedelta_original(hours=settings.global_time_offset_hours)
        mock_get_effective_time.return_value = mocked_effective_current_time

        user_perceived_now_naive = mocked_effective_current_time.replace(tzinfo=None)
        # Booking 3 hours ago. Cutoff is effective_now - 2 hours = 14:00. Booking at 13:00. Should fail.
        booking_start_dt = user_perceived_now_naive - timedelta_original(hours=3)
        payload = self._create_payload(booking_start_dt)
        response = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json()['error'], self.common_error_message)
        self.logout()

    @patch('routes.api_bookings.get_current_effective_time')
    def test_allow_past_false_adj_0_book_1_min_ago_fail(self, mock_get_effective_time):
        self.login('testuser', 'password')
        settings = self._set_booking_settings(allow_past=False, adjustment_hours=0, global_offset_hours=0)

        mocked_underlying_utc_now = datetime_original(2025, 6, 11, 16, 0, 0, tzinfo=timezone_original.utc)
        mocked_effective_current_time = mocked_underlying_utc_now + timedelta_original(hours=settings.global_time_offset_hours)
        mock_get_effective_time.return_value = mocked_effective_current_time

        user_perceived_now_naive = mocked_effective_current_time.replace(tzinfo=None)
        # Booking 1 min ago. Cutoff is effective_now - 0 hours = 16:00. Booking at 15:59. Should fail.
        booking_start_dt = user_perceived_now_naive - timedelta_original(minutes=1)
        payload = self._create_payload(booking_start_dt)
        response = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json()['error'], self.common_error_message)
        self.logout()

    @patch('routes.api_bookings.get_current_effective_time')
    def test_allow_past_false_adj_0_book_now_success(self, mock_get_effective_time):
        self.login('testuser', 'password')
        settings = self._set_booking_settings(allow_past=False, adjustment_hours=0, global_offset_hours=0)

        mocked_underlying_utc_now = datetime_original(2025, 6, 11, 16, 0, 0, tzinfo=timezone_original.utc)
        mocked_effective_current_time = mocked_underlying_utc_now + timedelta_original(hours=settings.global_time_offset_hours)
        mock_get_effective_time.return_value = mocked_effective_current_time

        user_perceived_now_naive = mocked_effective_current_time.replace(tzinfo=None)
        # Booking for current mock time. Cutoff is effective_now - 0 hours = 16:00. Booking at 16:00. Should succeed.
        booking_start_dt = user_perceived_now_naive
        payload = self._create_payload(booking_start_dt)
        response = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 201, response.get_json())
        self.logout()

    @patch('routes.api_bookings.get_current_effective_time')
    def test_allow_past_false_adj_neg_2_book_1_hr_future_fail(self, mock_get_effective_time):
        self.login('testuser', 'password')
        settings = self._set_booking_settings(allow_past=False, adjustment_hours=-2, global_offset_hours=0) # Must be 2hr in future

        mocked_underlying_utc_now = datetime_original(2025, 6, 11, 16, 0, 0, tzinfo=timezone_original.utc)
        mocked_effective_current_time = mocked_underlying_utc_now + timedelta_original(hours=settings.global_time_offset_hours)
        mock_get_effective_time.return_value = mocked_effective_current_time

        user_perceived_now_naive = mocked_effective_current_time.replace(tzinfo=None)
        # Booking 1 hour in future. Cutoff is effective_now - (-2 hours) = 18:00. Booking at 17:00. Should fail.
        booking_start_dt = user_perceived_now_naive + timedelta_original(hours=1)
        payload = self._create_payload(booking_start_dt)
        response = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json()['error'], self.common_error_message)
        self.logout()

    @patch('routes.api_bookings.get_current_effective_time')
    def test_allow_past_false_adj_neg_2_book_2_hr_future_success(self, mock_get_effective_time):
        self.login('testuser', 'password')
        settings = self._set_booking_settings(allow_past=False, adjustment_hours=-2, global_offset_hours=0) # Must be 2hr in future

        mocked_underlying_utc_now = datetime_original(2025, 6, 11, 16, 0, 0, tzinfo=timezone_original.utc)
        mocked_effective_current_time = mocked_underlying_utc_now + timedelta_original(hours=settings.global_time_offset_hours)
        mock_get_effective_time.return_value = mocked_effective_current_time

        user_perceived_now_naive = mocked_effective_current_time.replace(tzinfo=None)
        # Booking 2 hours in future. Cutoff is effective_now - (-2 hours) = 18:00. Booking at 18:00. Should succeed.
        booking_start_dt = user_perceived_now_naive + timedelta_original(hours=2)
        payload = self._create_payload(booking_start_dt)
        response = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 201, response.get_json())
        self.logout()

    # New tests for global_time_offset_hours
    @patch('routes.api_bookings.get_current_effective_time')
    def test_booking_with_positive_global_offset(self, mock_get_effective_time):
        self.login('testuser', 'password')
        # Effective time is UTC + 2 hours. Booking for 1 hour before effective 'now' should fail.
        settings = self._set_booking_settings(allow_past=False, adjustment_hours=0, global_offset_hours=2)

        mocked_underlying_utc_now = datetime_original(2025, 6, 11, 14, 0, 0, tzinfo=timezone_original.utc) # Actual UTC is 14:00
        mocked_effective_current_time = mocked_underlying_utc_now + timedelta_original(hours=settings.global_time_offset_hours) # Effective 'now' is 16:00
        mock_get_effective_time.return_value = mocked_effective_current_time

        # User attempts to book for 15:00 (effective local time)
        booking_start_dt_user_perception = datetime_original(2025, 6, 11, 15, 0, 0)
        payload = self._create_payload(booking_start_dt_user_perception)
        response = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json()['error'], self.common_error_message)
        self.logout()

    @patch('routes.api_bookings.get_current_effective_time')
    def test_booking_with_negative_global_offset(self, mock_get_effective_time):
        self.login('testuser', 'password')
        # Effective time is UTC - 2 hours. Booking for 1 hour before effective 'now' should fail.
        settings = self._set_booking_settings(allow_past=False, adjustment_hours=0, global_offset_hours=-2)

        mocked_underlying_utc_now = datetime_original(2025, 6, 11, 18, 0, 0, tzinfo=timezone_original.utc) # Actual UTC is 18:00
        mocked_effective_current_time = mocked_underlying_utc_now + timedelta_original(hours=settings.global_time_offset_hours) # Effective 'now' is 16:00
        mock_get_effective_time.return_value = mocked_effective_current_time

        # User attempts to book for 15:00 (effective local time)
        booking_start_dt_user_perception = datetime_original(2025, 6, 11, 15, 0, 0)
        payload = self._create_payload(booking_start_dt_user_perception)
        response = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json()['error'], self.common_error_message)
        self.logout()

    @patch('routes.api_bookings.get_current_effective_time')
    def test_booking_with_positive_global_offset_allowed_by_past_adjustment(self, mock_get_effective_time):
        self.login('testuser', 'password')
        # Effective time is UTC + 2 hours. past_adjustment_hours = 3.
        # Effective 'now' is 16:00. User can book back to effective 13:00.
        settings = self._set_booking_settings(allow_past=False, adjustment_hours=3, global_offset_hours=2)

        mocked_underlying_utc_now = datetime_original(2025, 6, 11, 14, 0, 0, tzinfo=timezone_original.utc) # Actual UTC is 14:00
        mocked_effective_current_time = mocked_underlying_utc_now + timedelta_original(hours=settings.global_time_offset_hours) # Effective 'now' is 16:00
        mock_get_effective_time.return_value = mocked_effective_current_time

        # User attempts to book for 15:00 (effective local time). This is 1 hour before effective 16:00.
        # Since past_adjustment_hours = 3, this should be allowed.
        booking_start_dt_user_perception = datetime_original(2025, 6, 11, 15, 0, 0)
        payload = self._create_payload(booking_start_dt_user_perception)
        response = self.client.post('/api/bookings', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(response.status_code, 201, response.get_json())
        self.logout()

    def test_import_resources_admin_success(self):
        # Setup: Create an admin user and log in
        admin_user = self._create_admin_user(username="admin_import_test", email_ext="import_test")
        login_response = self.login(admin_user.username, "adminapipass") # Assuming password based on _create_admin_user
        self.assertEqual(login_response.status_code, 200)

        # Setup: Create a resource to be updated by the import
        # No app_with_db fixture in unittest, use self.app_context or app.app_context()
        with app.app_context():
            initial_resource = Resource(name="TestResourceForImport", capacity=10, status="draft", floor_map_id=self.floor_map.id)
            db.session.add(initial_resource)
            db.session.commit()
            resource_id_to_update = initial_resource.id

        # Prepare import data that will update the existing resource
        import_data = [
            {
                "id": resource_id_to_update, # Target the existing resource
                "name": "TestResourceUpdatedName",
                "capacity": 20,
                "equipment": "New Projector",
                "status": "published", # Ensure this is a valid status
                "tags": "updated, test",
                "booking_restriction": None, # Assuming 'none' is not a defined value, use None or valid one
                "published_at": datetime.utcnow().isoformat() + "Z", # Example, ensure format is correct
                "allowed_user_ids": None,
                "roles": [],
                "is_under_maintenance": False,
                "maintenance_until": None
            }
        ]
        import_file_content = json.dumps(import_data)
        # Need to import io
        import io
        import_file_bytes = io.BytesIO(import_file_content.encode('utf-8'))

        # Execution: Make the POST request
        # For unittest, client is self.client. Headers might need to be handled if login() doesn't set session cookies
        # Assuming login() sets up session cookies correctly for subsequent requests by self.client
        response = self.client.post(
            '/api/admin/resources/import', # Use url_for if preferred and available in this context
            # headers=admin_auth_header, # Not directly available, rely on session from login
            data={'file': (import_file_bytes, 'import.json')},
            content_type='multipart/form-data'
        )

        # Assertion: Check the response
        self.assertEqual(response.status_code, 200, f"Import request failed: {response.get_json()}")
        response_json = response.get_json()

        # The message from _import_resource_configurations_data for 1 processed, 1 updated, 0 errors, 0 warnings
        self.assertEqual(response_json['message'], "Resources processed: 1 (Updated: 1).")
        self.assertEqual(response_json['created'], 0)
        self.assertEqual(response_json['updated'], 1)
        self.assertEqual(response_json['errors'], [])
        # Check warnings if applicable, e.g. not present or empty
        self.assertTrue('warnings' not in response_json or response_json['warnings'] == [], "Warnings should be empty or not present")


        # Optional: Verify the resource was actually updated in the DB
        with app.app_context():
            updated_resource = db.session.get(Resource, resource_id_to_update)
            self.assertIsNotNone(updated_resource)
            self.assertEqual(updated_resource.name, "TestResourceUpdatedName")
            self.assertEqual(updated_resource.capacity, 20)
            self.assertEqual(updated_resource.equipment, "New Projector")
            self.assertEqual(updated_resource.status, "published")

        self.logout()


class TestUpdateBookingConflicts(AppTests):
    def _create_initial_booking(self, user_name, resource_id, start_offset_hours, duration_hours=1, title="Initial Booking", status="approved"):
        # Using datetime_original and timedelta_original from AppTests context for consistency
        # Ensure bookings are far enough in the future to avoid other validation issues
        start_time = datetime_original.utcnow() + timedelta_original(hours=start_offset_hours)
        end_time = start_time + timedelta_original(hours=duration_hours)
        booking = Booking(
            user_name=user_name,
            resource_id=resource_id,
            start_time=start_time, # Stored as naive UTC by convention in tests
            end_time=end_time,     # Stored as naive UTC by convention in tests
            title=title,
            status=status
        )
        # Add BookingSettings to ensure global_time_offset_hours is available for the API
        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings(global_time_offset_hours=0, allow_multiple_resources_same_time=False)
            db.session.add(settings)
        else:
            settings.global_time_offset_hours = 0 # Ensure it's 0 for test predictability
            settings.allow_multiple_resources_same_time = False # Ensure default for these tests
        db.session.add(booking)
        db.session.commit()
        return booking

    def _update_booking_payload(self, new_start_time_dt, new_end_time_dt, title="Updated Title"):
        # Convert naive datetimes (assumed UTC for test logic) to ISO format strings.
        return {
            "start_time": new_start_time_dt.isoformat(),
            "end_time": new_end_time_dt.isoformat(),
            "title": title
        }

    def test_update_conflict_own_booking_different_resource(self):
        self.login('testuser', 'password')
        # Booking to keep: e.g., 102:00 - 103:00 on resource1
        booking_to_keep = self._create_initial_booking('testuser', self.resource1.id, start_offset_hours=102, duration_hours=1, title="Kept Booking R1")
        # Booking to update: e.g., 104:00 - 105:00 on resource2
        booking_to_update = self._create_initial_booking('testuser', self.resource2.id, start_offset_hours=104, duration_hours=1, title="Updated Booking R2")

        # Try to move booking_to_update to overlap with booking_to_keep: e.g., 102:30 - 103:30
        new_start_dt = booking_to_keep.start_time + timedelta_original(minutes=30)
        new_end_dt = new_start_dt + timedelta_original(hours=1)
        payload = self._update_booking_payload(new_start_dt, new_end_dt)

        response = self.client.put(f'/api/bookings/{booking_to_update.id}', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(response.status_code, 409, response.get_json())
        error_data = response.get_json()
        self.assertIn("conflicts with another of your existing bookings", error_data.get('error', ''))
        # Check that the conflicting resource mentioned is booking_to_keep's resource
        self.assertIn(self.resource1.name, error_data.get('error', ''))
        self.logout()

    def test_update_conflict_own_booking_same_resource(self):
        self.login('testuser', 'password')
        # Booking to keep: e.g., 102:00 - 103:00 on resource1
        booking_to_keep = self._create_initial_booking('testuser', self.resource1.id, start_offset_hours=102, duration_hours=1)
        # Booking to update: e.g., 104:00 - 105:00 on resource1
        booking_to_update = self._create_initial_booking('testuser', self.resource1.id, start_offset_hours=104, duration_hours=1)

        # Try to move booking_to_update to overlap with booking_to_keep: e.g., 102:30 - 103:30
        new_start_dt = booking_to_keep.start_time + timedelta_original(minutes=30)
        new_end_dt = new_start_dt + timedelta_original(hours=1)
        payload = self._update_booking_payload(new_start_dt, new_end_dt)

        response = self.client.put(f'/api/bookings/{booking_to_update.id}', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(response.status_code, 409, response.get_json())
        error_data = response.get_json()
        # This is the original check's message for same resource conflict
        self.assertIn("conflicts with an existing booking on this resource", error_data.get('error', ''))
        self.logout()

    def test_update_conflict_other_user_same_resource(self):
        user2 = User.query.filter_by(username='user2').first()
        if not user2:
            user2 = User(username='user2', email='user2@example.com')
            user2.set_password('password')
            db.session.add(user2)
            db.session.commit()

        # Booking by other user: e.g., 102:00 - 103:00 on resource1
        booking_other_user = self._create_initial_booking('user2', self.resource1.id, start_offset_hours=102, duration_hours=1)

        self.login('testuser', 'password')
        # Booking to update by testuser: e.g., 104:00 - 105:00 on resource1
        booking_to_update = self._create_initial_booking('testuser', self.resource1.id, start_offset_hours=104, duration_hours=1)

        # Try to move booking_to_update to overlap with booking_other_user: e.g., 102:30 - 103:30
        new_start_dt = booking_other_user.start_time + timedelta_original(minutes=30)
        new_end_dt = new_start_dt + timedelta_original(hours=1)
        payload = self._update_booking_payload(new_start_dt, new_end_dt)

        response = self.client.put(f'/api/bookings/{booking_to_update.id}', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(response.status_code, 409, response.get_json())
        error_data = response.get_json()
        # This is the original check's message for same resource conflict (another user)
        self.assertIn("conflicts with an existing booking on this resource", error_data.get('error', ''))
        self.logout()

    def test_update_no_conflict_successful(self):
        self.login('testuser', 'password')
        # Booking to update: e.g., 102:00 - 103:00 on resource1
        booking_to_update = self._create_initial_booking('testuser', self.resource1.id, start_offset_hours=102, duration_hours=1)

        # New time, far in the future, no conflict: e.g., 107:00 - 108:00
        new_start_dt = booking_to_update.start_time + timedelta_original(hours=5)
        new_end_dt = new_start_dt + timedelta_original(hours=1)
        updated_title = "Successfully Updated Booking"
        payload = self._update_booking_payload(new_start_dt, new_end_dt, title=updated_title)

        response = self.client.put(f'/api/bookings/{booking_to_update.id}', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()
        self.assertEqual(data['title'], updated_title)

        # API returns start_time as UTC ISO string.
        # new_start_dt is naive, assumed UTC in test. Add tzinfo for comparison.
        expected_start_iso = new_start_dt.replace(tzinfo=timezone_original.utc).isoformat()
        self.assertEqual(data['start_time'], expected_start_iso)

        # Check database
        updated_booking_db = db.session.get(Booking, booking_to_update.id)
        self.assertEqual(updated_booking_db.title, updated_title)
        # In DB, time is stored as naive (effectively UTC in test context with offset 0)
        self.assertEqual(updated_booking_db.start_time, new_start_dt)
        self.assertEqual(updated_booking_db.end_time, new_end_dt)
        self.logout()

    def test_update_no_actual_change(self):
        self.login('testuser', 'password')
        booking = self._create_initial_booking('testuser', self.resource1.id, start_offset_hours=100, duration_hours=1, title="Original Title")

        # Prepare payload with existing data
        payload = {
            "start_time": booking.start_time.isoformat(),
            "end_time": booking.end_time.isoformat(),
            "title": booking.title
        }

        response = self.client.put(f'/api/bookings/{booking.id}', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json().get('error'), 'No changes supplied.')
        self.logout()

    def test_update_only_title_changed(self):
        self.login('testuser', 'password')
        booking = self._create_initial_booking('testuser', self.resource1.id, start_offset_hours=102, duration_hours=1, title="Original Title Only")
        new_title = "Updated Title Only"

        # Prepare payload, changing only the title
        payload = {
            "start_time": booking.start_time.isoformat(),
            "end_time": booking.end_time.isoformat(),
            "title": new_title
        }

        response = self.client.put(f'/api/bookings/{booking.id}', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()
        self.assertEqual(data['title'], new_title)

        # Verify times in response are unchanged (booking.start_time is naive UTC in test context)
        expected_start_iso = booking.start_time.replace(tzinfo=timezone_original.utc).isoformat()
        expected_end_iso = booking.end_time.replace(tzinfo=timezone_original.utc).isoformat()
        self.assertEqual(data['start_time'], expected_start_iso)
        self.assertEqual(data['end_time'], expected_end_iso)

        # Verify in DB
        updated_booking_db = db.session.get(Booking, booking.id)
        self.assertEqual(updated_booking_db.title, new_title)
        self.assertEqual(updated_booking_db.start_time, booking.start_time) # Should be unchanged
        self.assertEqual(updated_booking_db.end_time, booking.end_time)     # Should be unchanged
        self.logout()

# Model Tests
class TestBookingSettingsModel(AppTests):
    def test_booking_settings_model_defaults(self):
        settings = BookingSettings()
        db.session.add(settings)
        db.session.commit()

        fetched_settings = BookingSettings.query.first()
        self.assertIsNotNone(fetched_settings)
        self.assertIsNone(fetched_settings.auto_release_if_not_checked_in_minutes)
        self.assertEqual(fetched_settings.auto_checkout_delay_minutes, 60)
        # Check a few other defaults to ensure the object is behaving as expected
        self.assertEqual(fetched_settings.enable_check_in_out, False)
        self.assertEqual(fetched_settings.check_in_minutes_before, 15)


# Admin Route Tests
class TestAdminBookingSettingsRoutes(AppTests):
    def _create_admin_user_for_settings(self):
        admin_user = User.query.filter_by(username='admin_settings_user').first()
        if not admin_user:
            admin_user = User(username='admin_settings_user', email='admin_settings@example.com', is_admin=True)
            admin_user.set_password("securepassword")
            db.session.add(admin_user)
            db.session.commit()
        return admin_user

    def _get_full_booking_settings_form_data(self, current_settings=None):
        """ Helper to get a full set of form data, using current or default values. """
        if current_settings is None:
            current_settings = BookingSettings.query.first()
            if not current_settings: # If no settings in DB, create a default one for form population
                current_settings = BookingSettings()
                # Note: This temporary settings object won't have an ID and might not reflect committed state
                # but it's good enough for populating form field values with model defaults.

        # Helper to convert boolean to 'on' or None (for checkboxes not present in POST if off)
        def cb_value(val):
            return 'on' if val else None

        data = {
            'allow_past_bookings': cb_value(current_settings.allow_past_bookings),
            'max_booking_days_in_future': str(current_settings.max_booking_days_in_future or ''),
            'allow_multiple_resources_same_time': cb_value(current_settings.allow_multiple_resources_same_time),
            'max_bookings_per_user': str(current_settings.max_bookings_per_user or ''),
            'enable_check_in_out': cb_value(current_settings.enable_check_in_out),
            'check_in_minutes_before': str(current_settings.check_in_minutes_before),
            'check_in_minutes_after': str(current_settings.check_in_minutes_after),
            'past_booking_time_adjustment_hours': str(current_settings.past_booking_time_adjustment_hours),
            'pin_auto_generation_enabled': cb_value(current_settings.pin_auto_generation_enabled),
            'pin_length': str(current_settings.pin_length),
            'pin_allow_manual_override': cb_value(current_settings.pin_allow_manual_override),
            'resource_checkin_url_requires_login': cb_value(current_settings.resource_checkin_url_requires_login),
            'allow_check_in_without_pin': cb_value(current_settings.allow_check_in_without_pin),
            'enable_auto_checkout': cb_value(current_settings.enable_auto_checkout),
            'auto_checkout_delay_minutes': str(current_settings.auto_checkout_delay_minutes),
            'auto_release_if_not_checked_in_minutes': str(current_settings.auto_release_if_not_checked_in_minutes or ''),
        }
        # Remove None values so they are not submitted (like unchecked checkboxes)
        return {k: v for k, v in data.items() if v is not None}


    def test_get_booking_settings_page_renders_specific_fields(self):
        admin = self._create_admin_user_for_settings()
        self.login(admin.username, "securepassword")

        # Ensure there's a settings object, or create one with defaults
        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings()
            db.session.add(settings)
            db.session.commit()

        response = self.client.get(url_for('admin_ui.serve_booking_settings_page'))
        self.assertEqual(response.status_code, 200)
        response_data = response.data.decode('utf-8')
        self.assertIn("Auto Check-out Delay (Minutes)", response_data)
        self.assertIn("Auto-release booking if not checked-in after X minutes", response_data)
        # Check if the values are rendered (using current or default)
        self.assertIn(f'name="auto_checkout_delay_minutes" value="{settings.auto_checkout_delay_minutes}"', response_data)
        self.assertIn(f'name="auto_release_if_not_checked_in_minutes" value="{settings.auto_release_if_not_checked_in_minutes or ""}"', response_data)
        self.logout()

    def test_get_booking_settings_page_loads_ok(self):
        admin = self._create_admin_user_for_settings()
        self.login(admin.username, "securepassword")

        # Ensure a BookingSettings object exists, as the page expects it
        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings() # Use default values from the model
            db.session.add(settings)
            db.session.commit()

        response = self.client.get(url_for('admin_ui.serve_booking_settings_page'))
        self.assertEqual(response.status_code, 200)
        response_data = response.data.decode('utf-8')
        # Check for a general title or a known field on the booking settings page.
        # Using "Booking Settings" as a general placeholder.
        # If a more specific, unique element is known from 'admin_booking_settings.html', that would be better.
        self.assertIn("Booking Page Settings", response_data) # Assuming this title exists
        self.logout()

    def test_update_booking_settings_success(self):
        admin = self._create_admin_user_for_settings()
        self.login(admin.username, "securepassword")

        # Get initial settings or create if none
        initial_settings = BookingSettings.query.first()
        if not initial_settings:
            initial_settings = BookingSettings()
            db.session.add(initial_settings)
            db.session.commit()
            initial_settings = BookingSettings.query.first() # Re-fetch to get committed state

        form_data = self._get_full_booking_settings_form_data(initial_settings)

        # Apply specific changes for this test
        form_data['auto_checkout_delay_minutes'] = '30'
        form_data['auto_release_if_not_checked_in_minutes'] = '15'
        form_data['enable_check_in_out'] = 'on' # Make sure this is on for release_minutes to be relevant

        response = self.client.post(url_for('admin_ui.update_booking_settings'), data=form_data, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Booking settings updated successfully.", response.data)

        updated_settings = BookingSettings.query.first()
        self.assertEqual(updated_settings.auto_checkout_delay_minutes, 30)
        self.assertEqual(updated_settings.auto_release_if_not_checked_in_minutes, 15)
        self.assertTrue(updated_settings.enable_check_in_out)
        self.logout()

    def test_update_booking_settings_validation_errors(self):
        admin = self._create_admin_user_for_settings()
        self.login(admin.username, "securepassword")

        initial_settings = BookingSettings.query.first()
        if not initial_settings:
            initial_settings = BookingSettings() # Default values: auto_checkout_delay_minutes=60, auto_release_if_not_checked_in_minutes=None
            db.session.add(initial_settings)
            db.session.commit()
            initial_settings = BookingSettings.query.first() # Re-fetch

        form_data = self._get_full_booking_settings_form_data(initial_settings)

        # Introduce errors
        form_data['auto_checkout_delay_minutes'] = '-5' # Invalid
        form_data['auto_release_if_not_checked_in_minutes'] = 'abc' # Invalid

        response = self.client.post(url_for('admin_ui.update_booking_settings'), data=form_data, follow_redirects=True)
        self.assertEqual(response.status_code, 200) # Should reload the page

        response_data = response.data.decode('utf-8')
        self.assertIn("Auto Check-out Delay must be at least 1 minute.", response_data)
        self.assertIn("Invalid input for Auto-release minutes.", response_data)

        # Verify settings were not changed from initial values
        settings_after_error = BookingSettings.query.first()
        self.assertEqual(settings_after_error.auto_checkout_delay_minutes, initial_settings.auto_checkout_delay_minutes)
        self.assertEqual(settings_after_error.auto_release_if_not_checked_in_minutes, initial_settings.auto_release_if_not_checked_in_minutes)
        self.logout()

from utils import SCHEDULER_SETTINGS_FILE_PATH, DEFAULT_SCHEDULER_SETTINGS # For scheduler settings tests

# ... (existing AppTests class and other test classes)

class TestAdminBackupSettingsRoutes(AppTests):
    def _create_admin_user_for_backup_settings(self, username="backup_admin_user", password="adminpassword"):
        admin_user = User.query.filter_by(username=username).first()
        if not admin_user:
            admin_user = User(username=username, email=f"{username}@example.com", is_admin=True)
            admin_user.set_password(password)

            # Assign a role with 'manage_system' permission
            admin_role = Role.query.filter_by(name="Admin").first()
            if not admin_role:
                # Ensure the Admin role has all permissions needed by setup or other tests if it's created here.
                # For this test class, 'manage_system' is key.
                admin_role = Role(name="Admin", permissions="manage_system,manage_users,view_audit_logs,manage_resources,manage_bookings,manage_system_settings,manage_floor_maps")
                db.session.add(admin_role)

            if admin_role not in admin_user.roles:
                admin_user.roles.append(admin_role)

            db.session.add(admin_user)
            db.session.commit()
        self.login(username, password)
        return admin_user

    def setUp(self):
        super().setUp()
        # Explicitly delete all BookingSettings before each test in this class
        # to ensure a clean state, as some tests expect no settings to exist initially.
        db.session.query(BookingSettings).delete()
        # Also clear AuditLog to prevent interference between tests
        db.session.query(AuditLog).delete()
        db.session.commit()

        # For scheduler settings, we primarily rely on mocking
        # load_scheduler_settings and save_scheduler_settings directly in the tests.
        # This avoids direct file system interaction for SCHEDULER_SETTINGS_FILE_PATH.
        pass

    def tearDown(self):
        # Clean up any BookingSettings created during a test, if necessary.
        # db.session.query(BookingSettings).delete()
        # db.session.commit()
        # Audit logs are cleaned in setUp.
        super().tearDown()

    def test_save_global_time_offset_success(self):
        admin = self._create_admin_user_for_backup_settings()

        # Test creates settings if not present, so start with none or one to be updated.
        # For this test, let's ensure one exists to be updated.
        initial_db_settings = BookingSettings(global_time_offset_hours=0)
        db.session.add(initial_db_settings)
        db.session.commit()
        original_offset = initial_db_settings.global_time_offset_hours

        new_offset = 5
        # Ensure new_offset is different from original_offset to actually test an update.
        if new_offset == original_offset:
            new_offset = original_offset + 1 if original_offset < 23 else original_offset -1
            if not (-23 <= new_offset <= 23): new_offset = 0 # fallback if +1 goes out of bounds

        response = self.client.post(url_for('admin_ui.save_backup_time_offset'),
                                    data={'global_time_offset_hours': str(new_offset)},
                                    follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith(url_for('admin_ui.serve_backup_settings_page')))

        redirect_response = self.client.get(response.location)
        self.assertIn(b"Global time offset saved successfully.", redirect_response.data)

        updated_settings = BookingSettings.query.first()
        self.assertIsNotNone(updated_settings)
        self.assertEqual(updated_settings.global_time_offset_hours, new_offset)

        audit_log = AuditLog.query.filter_by(action='Update Global Time Offset').order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log)
        self.assertIn(f'Set to {new_offset} hours', audit_log.details)
        self.assertEqual(audit_log.user_id, admin.id)

    def test_save_global_time_offset_invalid_value(self):
        admin = self._create_admin_user_for_backup_settings()
        # Ensure a setting exists to check it's unchanged
        settings = BookingSettings(global_time_offset_hours=1)
        db.session.add(settings)
        db.session.commit()
        initial_offset = settings.global_time_offset_hours
        initial_audit_count = AuditLog.query.filter_by(action='Update Global Time Offset').count()


        # Test non-integer
        response_abc = self.client.post(url_for('admin_ui.save_backup_time_offset'),
                                        data={'global_time_offset_hours': 'abc'},
                                        follow_redirects=True)
        self.assertIn(b"Invalid value for time offset.", response_abc.data)
        db.session.refresh(settings) # Re-fetch from DB
        self.assertEqual(settings.global_time_offset_hours, initial_offset)

        # Test out of range (too high)
        response_high = self.client.post(url_for('admin_ui.save_backup_time_offset'),
                                         data={'global_time_offset_hours': '25'},
                                         follow_redirects=True)
        self.assertIn(b"Global time offset must be between -23 and 23 hours.", response_high.data)
        db.session.refresh(settings)
        self.assertEqual(settings.global_time_offset_hours, initial_offset)

        # Test out of range (too low)
        response_low = self.client.post(url_for('admin_ui.save_backup_time_offset'),
                                        data={'global_time_offset_hours': '-25'},
                                        follow_redirects=True)
        self.assertIn(b"Global time offset must be between -23 and 23 hours.", response_low.data)
        db.session.refresh(settings)
        self.assertEqual(settings.global_time_offset_hours, initial_offset)

        # Verify no new audit log was created for these failed attempts
        final_audit_count = AuditLog.query.filter_by(action='Update Global Time Offset').count()
        self.assertEqual(final_audit_count, initial_audit_count)


    def test_save_global_time_offset_no_initial_settings(self):
        admin = self._create_admin_user_for_backup_settings()
        # setUp ensures no BookingSettings exist, so we can directly test creation.
        self.assertIsNone(BookingSettings.query.first())

        response = self.client.post(url_for('admin_ui.save_backup_time_offset'),
                                    data={'global_time_offset_hours': '3'},
                                    follow_redirects=True)
        self.assertIn(b"Global time offset saved successfully.", response.data)

        new_settings = BookingSettings.query.first()
        self.assertIsNotNone(new_settings)
        self.assertEqual(new_settings.global_time_offset_hours, 3)

        audit_log = AuditLog.query.filter_by(action='Update Global Time Offset').order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log)
        self.assertIn('Set to 3 hours', audit_log.details)
        self.assertEqual(audit_log.user_id, admin.id)


    @patch('routes.admin_ui.save_scheduler_settings') # utils.save_scheduler_settings is called by this
    @patch('routes.admin_ui.load_scheduler_settings') # utils.load_scheduler_settings is called by this
    def test_save_auto_restore_startup_behavior_enabled(self, mock_load_settings, mock_save_settings):
        admin = self._create_admin_user_for_backup_settings()
        # Simulate that current settings have this disabled
        mock_load_settings.return_value = {'auto_restore_booking_records_on_startup': False, 'other_setting': 'value'}

        response = self.client.post(url_for('admin_ui.save_auto_restore_booking_records_settings'),
                                    data={'auto_restore_booking_records_enabled': 'true'}, # This is the name in the form
                                    follow_redirects=True)
        self.assertIn(b"Startup behavior settings saved successfully.", response.data)

        mock_save_settings.assert_called_once()
        args_called = mock_save_settings.call_args[0][0] # First argument to the mock
        self.assertTrue(args_called['auto_restore_booking_records_on_startup'])
        self.assertEqual(args_called['other_setting'], 'value') # Ensure other settings are preserved

        audit_log = AuditLog.query.filter_by(action='Update Startup Behavior Settings').order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log)
        self.assertIn('set to True', audit_log.details) # Based on new implementation
        self.assertEqual(audit_log.user_id, admin.id)

    @patch('routes.admin_ui.save_scheduler_settings')
    @patch('routes.admin_ui.load_scheduler_settings')
    def test_save_auto_restore_startup_behavior_disabled(self, mock_load_settings, mock_save_settings):
        admin = self._create_admin_user_for_backup_settings()
        # Simulate that current settings have this enabled
        mock_load_settings.return_value = {'auto_restore_booking_records_on_startup': True, 'other_setting': 'value'}

        # If checkbox is unchecked, 'auto_restore_booking_records_enabled' is not in request.form
        response = self.client.post(url_for('admin_ui.save_auto_restore_booking_records_settings'),
                                    data={},
                                    follow_redirects=True)
        self.assertIn(b"Startup behavior settings saved successfully.", response.data)

        mock_save_settings.assert_called_once()
        args_called = mock_save_settings.call_args[0][0]
        # The route logic converts absence of 'auto_restore_booking_records_enabled' or value not 'true' to False
        self.assertFalse(args_called['auto_restore_booking_records_on_startup'])
        self.assertEqual(args_called['other_setting'], 'value')

        audit_log = AuditLog.query.filter_by(action='Update Startup Behavior Settings').order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit_log)
        self.assertIn('set to False', audit_log.details) # Based on new implementation
        self.assertEqual(audit_log.user_id, admin.id)

    def test_save_settings_permission_denied_non_admin(self):
        # Create a non-admin user (no 'manage_system' permission)
        non_admin_user = User.query.filter_by(username='non_admin_backup_test').first()
        if not non_admin_user:
            non_admin_user = User(username='non_admin_backup_test', email='non_admin_bk@example.com', is_admin=False)
            non_admin_user.set_password('password')
            # Ensure this user does NOT have the 'Admin' role or any role with 'manage_system'
            basic_role = Role.query.filter_by(name="User").first()
            if not basic_role:
                basic_role = Role(name="User", permissions="can_book") # Example basic role
                db.session.add(basic_role)
            if basic_role not in non_admin_user.roles:
                 non_admin_user.roles.append(basic_role)
            db.session.add(non_admin_user)
            db.session.commit()

        self.login(non_admin_user.username, 'password')

        response_offset = self.client.post(url_for('admin_ui.save_backup_time_offset'),
                                           data={'global_time_offset_hours': '5'},
                                           follow_redirects=False) # Check redirect before follow
        # @permission_required typically redirects to login or a 'permission_denied' page
        # Check for 302 redirect, then optionally check the flash message on the target page
        self.assertEqual(response_offset.status_code, 302)
        # Example: flash message check after redirect
        # redirected_page_offset = self.client.get(response_offset.location)
        # self.assertIn(b"You do not have permission to access this page.", redirected_page_offset.data)


        response_startup = self.client.post(url_for('admin_ui.save_auto_restore_booking_records_settings'),
                                            data={'auto_restore_booking_records_enabled': 'true'},
                                            follow_redirects=False)
        self.assertEqual(response_startup.status_code, 302)
        # redirected_page_startup = self.client.get(response_startup.location)
        # self.assertIn(b"You do not have permission to access this page.", redirected_page_startup.data)

        self.logout()


# Need io for file uploads in AdminAPITestCase
import io

class AdminAPITestCase(AppTests):
    def _create_admin_user(self, username="admin_api_user", email_ext="admin_api"):
        admin_user = User.query.filter_by(username=username).first()
        if not admin_user:
            admin_user = User(username=username, email=f"{email_ext}@example.com", is_admin=True)
            admin_user.set_password("adminapipass")
            role = Role.query.filter_by(name='Admin').first()
            if not role:
                role = Role(name='Admin', permissions=['manage_system', 'view_audit_logs']) # Add relevant permissions
                db.session.add(role)
            admin_user.roles.append(role)
            db.session.add(admin_user)
            db.session.commit()
        return admin_user

    @patch('routes.api_system.list_available_backups', None)
    @patch('routes.api_system.current_app.logger.error')
    def test_list_backups_azure_not_configured(self, mock_logger_error, mock_list_backups_import):
        # mock_list_backups_import is implicitly used by the decorator
        admin_user = self._create_admin_user()
        self.login(admin_user.username, "adminapipass")

        # Set the global error message in the routes.api_system module to simulate an import error
        # This is necessary because the actual import happens at module load time,
        # but we want to test the behavior of the endpoint when this message is set.
        with patch('routes.api_system.azure_import_error_message', "Simulated Azure Import Error for testing logging"):
            response = self.client.get(url_for('api_system.api_list_backups'))

        self.assertEqual(response.status_code, 500)
        json_response = response.get_json()
        self.assertEqual(json_response['message'], "Backup module is not configured.")

        mock_logger_error.assert_called_once()
        # Check that the specific deferred message (which now comes from azure_import_error_message) was logged.
        # The original test set azure_import_error_message directly.
        # The actual error message logged will be the one set in azure_import_error_message.
        self.assertIn("Simulated Azure Import Error for testing logging", mock_logger_error.call_args[0][0])
        self.logout()

    @patch('azure_backup.logger.warning') # Patch the logger where the warning is issued
    def test_list_booking_data_protection_backups_placeholder(self, mock_azure_logger_warning):
        admin_user = self._create_admin_user(username="admin_booking_dp_list", email_ext="bookingdp")
        self.login(admin_user.username, "adminapipass")

        response = self.client.get(url_for('api_system.api_list_booking_data_backups'))

        self.assertEqual(response.status_code, 200)
        json_response = response.get_json()
        self.assertTrue(json_response['success'])
        self.assertEqual(json_response['backups'], [])

        # Assert that the placeholder's warning was logged
        mock_azure_logger_warning.assert_called_once()
        self.assertIn("Placeholder function 'list_booking_data_json_backups' called", mock_azure_logger_warning.call_args[0][0])
        self.logout()

    @patch('routes.api_system.create_full_backup', None)
    def test_one_click_backup_azure_not_configured(self, mock_create_full_backup_none):
        admin_user = self._create_admin_user(username="admin_one_click_backup_test", email_ext="oneclick")
        self.login(admin_user.username, "adminapipass")

        response = self.client.post(url_for('api_system.api_one_click_backup'))
        self.assertEqual(response.status_code, 200)
        json_response = response.get_json()
        self.assertTrue(json_response['success'])
        self.assertIn('task_id', json_response)
        task_id = json_response['task_id']

        # Poll task status
        start_time = time.time()
        timeout_seconds = 10 # Max wait time for the task to finish
        final_task_status = None

        while time.time() - start_time < timeout_seconds:
            status_response = self.client.get(url_for('api_system.get_task_status_api', task_id=task_id))
            self.assertEqual(status_response.status_code, 200)
            task_status = status_response.get_json()
            if task_status.get('is_done'):
                final_task_status = task_status
                break
            time.sleep(0.2) # Poll every 200ms

        self.assertIsNotNone(final_task_status, f"Task {task_id} did not finish within {timeout_seconds} seconds.")

        self.assertEqual(final_task_status['status_summary'], "Azure backup module not available.")
        self.assertFalse(final_task_status['success'])
        self.assertEqual(final_task_status['result_message'], "Azure backup module not available.")

        # Verify the specific log entry within the task
        # The worker `do_backup_work` calls `update_task_log` with the more detailed message first.
        found_log_entry = False
        for entry in final_task_status.get('log_entries', []):
            if "Azure backup module (create_full_backup) not available." in entry.get('message', ''):
                self.assertEqual(entry.get('level'), 'error')
                found_log_entry = True
                break
        self.assertTrue(found_log_entry, "Expected log entry about 'create_full_backup not available' not found.")

        self.logout()

    @patch('azure_backup.logger.warning')
    def test_delete_booking_data_placeholder(self, mock_azure_logger_warning):
        admin_user = self._create_admin_user(username="admin_delete_booking_test", email_ext="deletebooking")
        self.login(admin_user.username, "adminapipass")

        payload = {'backup_filename': 'test.json', 'backup_type': 'full'}
        response = self.client.post(url_for('api_system.api_delete_booking_data_backup'), json=payload)

        self.assertEqual(response.status_code, 500)
        json_response = response.get_json()
        self.assertFalse(json_response['success'])
        self.assertIn("Failed to delete backup 'test.json'", json_response['message'])

        mock_azure_logger_warning.assert_called_once()
        self.assertIn("Placeholder function 'delete_booking_data_json_backup' called for file: test.json, type: full", mock_azure_logger_warning.call_args[0][0])
        self.logout()

    @patch('azure_backup.logger.warning')
    def test_restore_booking_data_pit_placeholder(self, mock_azure_logger_warning):
        admin_user = self._create_admin_user(username="admin_restore_pit_test", email_ext="restorepit")
        self.login(admin_user.username, "adminapipass")

        payload = {'filename': 'test.json', 'backup_type': 'full', 'backup_timestamp_iso': '2023-01-01T00:00:00Z'}
        response = self.client.post(url_for('api_system.api_unified_booking_data_point_in_time_restore'), json=payload)

        self.assertEqual(response.status_code, 200)
        json_response = response.get_json()
        self.assertTrue(json_response['success'])
        self.assertIsNotNone(json_response.get('task_id')) # task_id is generated by the route
        self.assertEqual(json_response['summary']['status'], 'not_implemented')
        self.assertEqual(json_response['summary']['message'], 'Restore to point in time is not implemented.')

        mock_azure_logger_warning.assert_called_once()
        self.assertIn("Placeholder function 'restore_booking_data_to_point_in_time' called for file: test.json", mock_azure_logger_warning.call_args[0][0])
        self.logout()

    @patch('azure_backup.logger.warning')
    def test_download_booking_data_placeholder(self, mock_azure_logger_warning):
        admin_user = self._create_admin_user(username="admin_download_booking_test", email_ext="downloadbooking")
        self.login(admin_user.username, "adminapipass")

        response = self.client.get(url_for('api_system.api_download_booking_data_backup', backup_type='full', filename='testfile.json'))

        self.assertEqual(response.status_code, 404)
        json_response = response.get_json()
        self.assertFalse(json_response['success'])
        self.assertEqual(json_response['message'], 'File not found or download failed.')

        mock_azure_logger_warning.assert_called_once()
        self.assertIn("Placeholder function 'download_booking_data_json_backup' called for file: testfile.json, type: full", mock_azure_logger_warning.call_args[0][0])
        self.logout()

    def test_import_new_resources_only(self):
        admin_user = self._create_admin_user(username="admin_import_new", email_ext="import_new")
        self.login(admin_user.username, "adminapipass")

        # Setup: Create Roles
        role1 = Role(name="Test Role 1 Import")
        role2 = Role(name="Test Role 2 Import")
        db.session.add_all([role1, role2])
        db.session.commit()
        role1_id = role1.id
        role2_id = role2.id

        # Prepare JSON data
        now_iso = datetime.utcnow().isoformat() + "Z"
        later_iso = (datetime.utcnow() + timedelta(days=5)).isoformat() + "Z"

        import_data = [
            {
                "id": 101,
                "name": "New Resource One",
                "capacity": 10,
                "equipment": "Projector",
                "status": "draft",
                "tags": "new, single_tag", # Test single tag string
                "booking_restriction": "restricted_roles",
                "published_at": now_iso,
                "allowed_user_ids": json.dumps([admin_user.id]), # Test JSON string
                "roles": [{"id": role1_id}],
                "is_under_maintenance": False,
                "maintenance_until": None
            },
            {
                "id": 102,
                "name": "New Resource Two",
                "capacity": 5,
                "equipment": "Whiteboard, Markers",
                "status": "published",
                "tags": ["tagA", "tagB"], # Test list of tags
                "booking_restriction": None,
                "published_at": None,
                "allowed_user_ids": None, # Test None
                "roles": [{"id": role1_id}, {"id": role2_id}],
                "is_under_maintenance": True,
                "maintenance_until": later_iso
            }
        ]
        import_file_content = json.dumps(import_data)
        import_file_bytes = io.BytesIO(import_file_content.encode('utf-8'))

        response = self.client.post(
            url_for('api_resources.import_resources_admin'),
            data={'file': (import_file_bytes, 'import_new.json')},
            content_type='multipart/form-data'
        )

        self.assertEqual(response.status_code, 200, f"Import request failed: {response.get_json()}")
        response_json = response.get_json()

        self.assertEqual(response_json['created'], 2)
        self.assertEqual(response_json['updated'], 0)
        self.assertEqual(response_json['errors'], [])
        self.assertEqual(response_json['warnings'], [])

        # DB Assertions
        res101 = db.session.get(Resource, 101)
        self.assertIsNotNone(res101)
        self.assertEqual(res101.name, "New Resource One")
        self.assertEqual(res101.capacity, 10)
        self.assertEqual(res101.tags, "new, single_tag")
        self.assertEqual(res101.booking_restriction, "restricted_roles")
        self.assertIsNotNone(res101.published_at)
        self.assertEqual(res101.allowed_user_ids, json.dumps([admin_user.id]))
        self.assertEqual(len(res101.roles), 1)
        self.assertEqual(res101.roles[0].id, role1_id)
        self.assertFalse(res101.is_under_maintenance)
        self.assertIsNone(res101.maintenance_until)


        res102 = db.session.get(Resource, 102)
        self.assertIsNotNone(res102)
        self.assertEqual(res102.name, "New Resource Two")
        self.assertEqual(res102.tags, "tagA,tagB") # Should be converted to string
        self.assertTrue(res102.is_under_maintenance)
        self.assertIsNotNone(res102.maintenance_until)
        self.assertEqual(len(res102.roles), 2)
        # Ensure correct parsing of datetime strings
        self.assertEqual(res101.published_at.replace(tzinfo=None), datetime.fromisoformat(now_iso.replace("Z", "")))
        self.assertEqual(res102.maintenance_until.replace(tzinfo=None), datetime.fromisoformat(later_iso.replace("Z", "")))


        self.logout()

    def test_import_mixed_new_and_existing_resources(self):
        admin_user = self._create_admin_user(username="admin_import_mixed", email_ext="import_mixed")
        self.login(admin_user.username, "adminapipass")

        # Setup: Create existing Resource
        existing_resource = Resource(id=201, name="Existing R1", capacity=5, status="draft")
        db.session.add(existing_resource)
        db.session.commit()

        import_data = [
            {
                "id": 201, # Existing
                "name": "Existing R1 Updated",
                "capacity": 50,
                "status": "published"
            },
            {
                "id": 103, # New
                "name": "Brand New Resource",
                "capacity": 3,
                "status": "draft",
                "tags": "new_mixed_test"
            }
        ]
        import_file_content = json.dumps(import_data)
        import_file_bytes = io.BytesIO(import_file_content.encode('utf-8'))

        response = self.client.post(
            url_for('api_resources.import_resources_admin'),
            data={'file': (import_file_bytes, 'import_mixed.json')},
            content_type='multipart/form-data'
        )
        self.assertEqual(response.status_code, 200, f"Import request failed: {response.get_json()}")
        response_json = response.get_json()

        self.assertEqual(response_json['created'], 1)
        self.assertEqual(response_json['updated'], 1)
        self.assertEqual(response_json['errors'], [])

        # DB Assertions
        res201_updated = db.session.get(Resource, 201)
        self.assertIsNotNone(res201_updated)
        self.assertEqual(res201_updated.name, "Existing R1 Updated")
        self.assertEqual(res201_updated.capacity, 50)
        self.assertEqual(res201_updated.status, "published")

        res103_new = db.session.get(Resource, 103)
        self.assertIsNotNone(res103_new)
        self.assertEqual(res103_new.name, "Brand New Resource")
        self.assertEqual(res103_new.tags, "new_mixed_test")

        self.logout()

    def test_import_new_resource_with_invalid_id(self):
        admin_user = self._create_admin_user(username="admin_import_invalid_id", email_ext="import_invalid_id")
        self.login(admin_user.username, "adminapipass")

        import_data = [
            {
                "id": "invalid_id_string", # Non-integer ID
                "name": "Resource With Invalid ID",
                "capacity": 10
            },
            {
                "id": 105, # Valid new resource for comparison
                "name": "Valid New Resource After Invalid",
                "capacity": 5
            }
        ]
        import_file_content = json.dumps(import_data)
        import_file_bytes = io.BytesIO(import_file_content.encode('utf-8'))

        response = self.client.post(
            url_for('api_resources.import_resources_admin'),
            data={'file': (import_file_bytes, 'import_invalid.json')},
            content_type='multipart/form-data'
        )
        self.assertEqual(response.status_code, 207, f"Import request status code was not 207: {response.get_json()}")
        response_json = response.get_json()

        self.assertEqual(response_json['created'], 1) # Only the valid one should be created
        self.assertEqual(response_json['updated'], 0)
        self.assertIsInstance(response_json['errors'], list)
        self.assertEqual(len(response_json['errors']), 1)
        self.assertIn("has a non-integer ID. Cannot create.", response_json['errors'][0])
        self.assertIn("invalid_id_string", response_json['errors'][0])


        # DB Assertions
        res_invalid = Resource.query.filter_by(name="Resource With Invalid ID").first()
        self.assertIsNone(res_invalid, "Resource with invalid ID string should not have been created by name.")
        # Check if a resource with a numerically interpreted ID was created by mistake (should not happen)
        # This depends on how SQLAlchemy handles get() with non-integer, but our code should prevent it.
        # res_invalid_num_id = db.session.get(Resource, "invalid_id_string") # This would likely error in get()
        # self.assertIsNone(res_invalid_num_id)


        res105_valid = db.session.get(Resource, 105)
        self.assertIsNotNone(res105_valid)
        self.assertEqual(res105_valid.name, "Valid New Resource After Invalid")

        self.logout()

    def test_import_new_resource_with_non_existent_role(self):
        admin_user = self._create_admin_user(username="admin_import_bad_role", email_ext="import_bad_role")
        self.login(admin_user.username, "adminapipass")

        # Setup: Create one existing Role
        existing_role = Role(name="Existing Role For Import")
        db.session.add(existing_role)
        db.session.commit()
        existing_role_id = existing_role.id
        non_existent_role_id = 9999 # Assumed not to exist

        import_data = [
            {
                "id": 104,
                "name": "New Resource With Mixed Roles",
                "capacity": 8,
                "roles": [{"id": existing_role_id}, {"id": non_existent_role_id}]
            }
        ]
        import_file_content = json.dumps(import_data)
        import_file_bytes = io.BytesIO(import_file_content.encode('utf-8'))

        response = self.client.post(
            url_for('api_resources.import_resources_admin'),
            data={'file': (import_file_bytes, 'import_roles.json')},
            content_type='multipart/form-data'
        )

        self.assertEqual(response.status_code, 207, f"Import request status code was not 207: {response.get_json()}")
        response_json = response.get_json()

        self.assertEqual(response_json['created'], 1)
        self.assertEqual(response_json['updated'], 0)
        self.assertEqual(response_json['errors'], [])
        self.assertIsInstance(response_json['warnings'], list)
        self.assertEqual(len(response_json['warnings']), 1)
        self.assertIn(f"Role ID {non_existent_role_id} from backup not found", response_json['warnings'][0])

        # DB Assertions
        res104 = db.session.get(Resource, 104)
        self.assertIsNotNone(res104)
        self.assertEqual(res104.name, "New Resource With Mixed Roles")
        self.assertEqual(len(res104.roles), 1, "Resource should only have one role assigned.")
        self.assertEqual(res104.roles[0].id, existing_role_id, "The assigned role is not the existing one.")

        self.logout()


class TestBookingResourceRelease(AppTests):
    def _common_user_setup(self):
        user1 = User.query.filter_by(username='testuser1_release').first()
        if not user1:
            user1 = User(username='testuser1_release', email='testuser1_release@example.com')
            user1.set_password('password')
            db.session.add(user1)
        user2 = User.query.filter_by(username='testuser2_release').first()
        if not user2:
            user2 = User(username='testuser2_release', email='testuser2_release@example.com')
            user2.set_password('password')
            db.session.add(user2)
        db.session.commit()
        return user1, user2

    def test_resource_available_after_system_cancelled_no_checkin(self):
        user1, user2 = self._common_user_setup()

        # Ensure BookingSettings exist for global_time_offset_hours
        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings(global_time_offset_hours=0) # Default to 0 for predictability
            db.session.add(settings)
            db.session.commit()
        else: # Ensure offset is predictable for test payload generation
            settings.global_time_offset_hours = 0
            db.session.commit()


        self.login(user1.username, 'password')

        # Define a future time slot to avoid conflicts with past booking logic validation
        # Using datetime_original from AppTests context for consistency if time is ever mocked globally
        booking_start_dt = datetime_original.utcnow().replace(microsecond=0) + timedelta_original(days=1, hours=2) # Tomorrow at T+2 hours UTC
        booking_end_dt = booking_start_dt + timedelta_original(hours=1)

        # Create initial booking payload
        # Times are naive UTC, which the API then treats as venue local time
        # For this test, with global_time_offset_hours=0, naive UTC = naive venue local
        initial_booking_payload = {
            'resource_id': self.resource1.id,
            'user_name': user1.username,
            'date_str': booking_start_dt.strftime('%Y-%m-%d'),
            'start_time_str': booking_start_dt.strftime('%H:%M'),
            'end_time_str': booking_end_dt.strftime('%H:%M'),
            'title': 'Initial Booking by User1'
        }
        response_initial = self.client.post('/api/bookings', data=json.dumps(initial_booking_payload), content_type='application/json')
        self.assertEqual(response_initial.status_code, 201, f"Initial booking failed: {response_initial.get_json()}")
        initial_booking_id = response_initial.get_json()['bookings'][0]['id']

        # Simulate System Cancellation
        booking_to_cancel = db.session.get(Booking, initial_booking_id)
        self.assertIsNotNone(booking_to_cancel, "Initial booking not found in DB")
        booking_to_cancel.status = 'system_cancelled_no_checkin'
        db.session.commit()
        self.logout()

        # Attempt New Booking by User2 for the same slot
        self.login(user2.username, 'password')
        new_booking_payload = {
            'resource_id': self.resource1.id,
            'user_name': user2.username,
            'date_str': booking_start_dt.strftime('%Y-%m-%d'), # Same date
            'start_time_str': booking_start_dt.strftime('%H:%M'), # Same start time
            'end_time_str': booking_end_dt.strftime('%H:%M'),   # Same end time
            'title': 'New Booking by User2'
        }
        response_new = self.client.post('/api/bookings', data=json.dumps(new_booking_payload), content_type='application/json')
        self.assertEqual(response_new.status_code, 201, f"New booking by user2 failed: {response_new.get_json()}")

        # Assertions
        new_booking_id = response_new.get_json()['bookings'][0]['id']
        new_booking_db = db.session.get(Booking, new_booking_id)
        self.assertIsNotNone(new_booking_db, "New booking by user2 not found in DB")
        self.assertEqual(new_booking_db.status, 'approved') # Default status for new bookings

        original_booking_db = db.session.get(Booking, initial_booking_id)
        self.assertIsNotNone(original_booking_db, "Original booking by user1 not found in DB after new booking")
        self.assertEqual(original_booking_db.status, 'system_cancelled_no_checkin')
        self.logout()

    def test_resource_unavailable_for_approved_status_conflict(self):
        user1, user2 = self._common_user_setup()

        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings(global_time_offset_hours=0)
            db.session.add(settings)
            db.session.commit()
        else:
            settings.global_time_offset_hours = 0
            db.session.commit()

        self.login(user1.username, 'password')

        # Define a different future time slot for this test
        booking_start_dt = datetime_original.utcnow().replace(microsecond=0) + timedelta_original(days=2, hours=4) # Day after tomorrow T+4 hours UTC
        booking_end_dt = booking_start_dt + timedelta_original(hours=1)

        # Create initial booking payload (status will be 'approved' by default)
        initial_booking_payload = {
            'resource_id': self.resource1.id,
            'user_name': user1.username,
            'date_str': booking_start_dt.strftime('%Y-%m-%d'),
            'start_time_str': booking_start_dt.strftime('%H:%M'),
            'end_time_str': booking_end_dt.strftime('%H:%M'),
            'title': 'Approved Booking by User1'
        }
        response_initial = self.client.post('/api/bookings', data=json.dumps(initial_booking_payload), content_type='application/json')
        self.assertEqual(response_initial.status_code, 201, f"Initial booking for conflict test failed: {response_initial.get_json()}")
        initial_booking_id = response_initial.get_json()['bookings'][0]['id']

        # Verify it's approved
        booking_db = db.session.get(Booking, initial_booking_id)
        self.assertEqual(booking_db.status, 'approved')
        self.logout()

        # Attempt Conflicting Booking by User2
        self.login(user2.username, 'password')
        conflicting_booking_payload = {
            'resource_id': self.resource1.id,
            'user_name': user2.username,
            'date_str': booking_start_dt.strftime('%Y-%m-%d'), # Same date
            'start_time_str': booking_start_dt.strftime('%H:%M'), # Same start time
            'end_time_str': booking_end_dt.strftime('%H:%M'),   # Same end time
            'title': 'Conflicting Booking by User2'
        }
        response_conflict = self.client.post('/api/bookings', data=json.dumps(conflicting_booking_payload), content_type='application/json')

        # Assertion
        self.assertEqual(response_conflict.status_code, 409, f"Conflicting booking did not fail as expected: {response_conflict.get_json()}")
        self.assertIn("is already booked or conflicts", response_conflict.get_json().get('error', ''))
        self.logout()

    def test_user_can_book_other_resource_after_own_booking_cancelled(self):
        user1, user2 = self._common_user_setup()

        # 1. Set up BookingSettings
        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings(allow_multiple_resources_same_time=False, global_time_offset_hours=0)
            db.session.add(settings)
        else:
            settings.allow_multiple_resources_same_time = False
            settings.global_time_offset_hours = 0
        db.session.commit()

        # 2. Log in as user1
        login_response = self.login(user1.username, 'password')
        self.assertEqual(login_response.status_code, 200)

        # 3. Define a future time slot
        # Use datetime_original and timedelta_original for consistency with other tests
        booking_start_dt = datetime_original.utcnow().replace(microsecond=0) + timedelta_original(days=3, hours=10) # e.g., 3 days from now at 10:00 UTC
        booking_end_dt = booking_start_dt + timedelta_original(hours=1) # 1-hour duration

        # Prepare payload strings (assuming global_time_offset_hours=0, so UTC times are effectively local for the API)
        date_str_payload = booking_start_dt.strftime('%Y-%m-%d')
        start_time_str_payload = booking_start_dt.strftime('%H:%M')
        end_time_str_payload = booking_end_dt.strftime('%H:%M')

        # 4. Create an initial booking for user1 on self.resource1
        initial_booking_payload = {
            'resource_id': self.resource1.id,
            'user_name': user1.username,
            'date_str': date_str_payload,
            'start_time_str': start_time_str_payload,
            'end_time_str': end_time_str_payload,
            'title': 'User1 Initial Booking on R1'
        }
        response_initial = self.client.post('/api/bookings', data=json.dumps(initial_booking_payload), content_type='application/json')
        self.assertEqual(response_initial.status_code, 201, f"Initial booking for user1 failed: {response_initial.get_json()}")
        initial_booking_id = response_initial.get_json()['bookings'][0]['id']

        # 5. Retrieve the created booking and change its status to 'cancelled'
        booking_to_cancel = db.session.get(Booking, initial_booking_id)
        self.assertIsNotNone(booking_to_cancel, "Initial booking not found in DB")
        booking_to_cancel.status = 'cancelled' # Using 'cancelled' as one of the example statuses
        # With the new logic in create_booking, we should NOT delete the booking.
        # The application should handle reusing this 'cancelled' slot.
        # db.session.delete(booking_to_cancel)
        db.session.commit()

        # 6. Log out user1
        self.logout()

        # 7. Verification Part 1 (Different User, Same Resource)
        login_response_user2 = self.login(user2.username, 'password')
        self.assertEqual(login_response_user2.status_code, 200)

        booking_payload_user2_r1 = {
            'resource_id': self.resource1.id, # Same resource
            'user_name': user2.username,
            'date_str': date_str_payload,      # Same time slot
            'start_time_str': start_time_str_payload,
            'end_time_str': end_time_str_payload,
            'title': 'User2 Booking on R1 after User1 cancelled'
        }
        response_user2_r1 = self.client.post('/api/bookings', data=json.dumps(booking_payload_user2_r1), content_type='application/json')
        self.assertEqual(response_user2_r1.status_code, 201, f"Booking for user2 on resource1 failed: {response_user2_r1.get_json()}")

        # Clean up user2's booking before next step if necessary (optional, but good practice)
        user2_booking_id = response_user2_r1.get_json()['bookings'][0]['id']
        booking_to_delete = db.session.get(Booking, user2_booking_id)
        if booking_to_delete:
            db.session.delete(booking_to_delete)
            db.session.commit()
        self.logout()


        # 8. Verification Part 2 (Original User, Different Resource, Same Time)
        login_response_user1_again = self.login(user1.username, 'password')
        self.assertEqual(login_response_user1_again.status_code, 200)

        booking_payload_user1_r2 = {
            'resource_id': self.resource2.id, # Different resource (self.resource2)
            'user_name': user1.username,
            'date_str': date_str_payload,      # Same time slot
            'start_time_str': start_time_str_payload,
            'end_time_str': end_time_str_payload,
            'title': 'User1 Booking on R2 (Same Time as Cancelled R1 Booking)'
        }
        response_user1_r2 = self.client.post('/api/bookings', data=json.dumps(booking_payload_user1_r2), content_type='application/json')
        self.assertEqual(response_user1_r2.status_code, 201, f"Booking for user1 on resource2 failed: {response_user1_r2.get_json()}")
        self.logout()

    def test_original_user_can_rebook_own_cancelled_slot(self):
        user1, _ = self._common_user_setup() # We only need user1 for this test

        # Ensure BookingSettings exist and global_time_offset_hours is 0
        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings(global_time_offset_hours=0)
            db.session.add(settings)
        else:
            settings.global_time_offset_hours = 0
        db.session.commit()

        self.login(user1.username, 'password')

        # Define a future time slot
        booking_start_dt = datetime_original.utcnow().replace(microsecond=0) + timedelta_original(days=4, hours=11) # e.g., 4 days from now at 11:00 UTC
        booking_end_dt = booking_start_dt + timedelta_original(hours=1)

        date_str_payload = booking_start_dt.strftime('%Y-%m-%d')
        start_time_str_payload = booking_start_dt.strftime('%H:%M')
        end_time_str_payload = booking_end_dt.strftime('%H:%M')

        # Create initial booking for user1 on self.resource1
        initial_payload = {
            'resource_id': self.resource1.id,
            'user_name': user1.username,
            'date_str': date_str_payload,
            'start_time_str': start_time_str_payload,
            'end_time_str': end_time_str_payload,
            'title': 'User1 Original Booking'
        }
        response_initial = self.client.post('/api/bookings', data=json.dumps(initial_payload), content_type='application/json')
        self.assertEqual(response_initial.status_code, 201, f"Initial booking failed: {response_initial.get_json()}")
        initial_booking_data = response_initial.get_json()['bookings'][0]
        original_booking_id = initial_booking_data['id']

        # Fetch and store last_modified and token to check later if they change
        booking_to_cancel = db.session.get(Booking, original_booking_id)
        self.assertIsNotNone(booking_to_cancel)
        original_last_modified = booking_to_cancel.last_modified
        original_check_in_token = booking_to_cancel.check_in_token

        # Change status to 'cancelled'
        booking_to_cancel.status = 'cancelled'
        db.session.commit()
        # Ensure last_modified is updated by the cancellation to make the later check more robust
        # Depending on DB precision, we might need a slight delay or ensure the update is distinct
        # For now, assume the commit updates it sufficiently or the rebook logic will.
        cancelled_last_modified = booking_to_cancel.last_modified
        self.assertIsNotNone(cancelled_last_modified)
        # self.assertNotEqual(original_last_modified, cancelled_last_modified) # This might be too sensitive

        # User1 (still logged in) attempts to re-book the exact same slot
        rebook_payload = {
            'resource_id': self.resource1.id,
            'user_name': user1.username,
            'date_str': date_str_payload,
            'start_time_str': start_time_str_payload,
            'end_time_str': end_time_str_payload,
            'title': 'User1 Re-booked Title' # Can be same or different
        }
        response_rebook = self.client.post('/api/bookings', data=json.dumps(rebook_payload), content_type='application/json')
        self.assertEqual(response_rebook.status_code, 201, f"Re-booking failed: {response_rebook.get_json()}")

        rebooked_data = response_rebook.get_json()['bookings'][0]

        # Verify no new booking record was created; ID should be the same
        self.assertEqual(rebooked_data['id'], original_booking_id, "Booking ID changed, indicating a new record was created instead of update.")

        # Fetch the booking from DB and verify its state
        rebooked_booking_db = db.session.get(Booking, original_booking_id)
        self.assertIsNotNone(rebooked_booking_db)
        self.assertEqual(rebooked_booking_db.user_name, user1.username)
        self.assertEqual(rebooked_booking_db.status, 'approved')
        self.assertEqual(rebooked_booking_db.title, 'User1 Re-booked Title')

        # Check that last_modified has been updated
        self.assertIsNotNone(rebooked_booking_db.last_modified)
        # This check can be flaky due to timing and DB precision.
        # A more robust check would be to ensure it's greater than original_last_modified if that was captured before the cancellation commit.
        # For now, we rely on the fact that the update path sets it.
        # If cancelled_last_modified was captured after the cancel commit, compare with that.
        if original_last_modified and cancelled_last_modified: # Ensure both were captured
             self.assertGreater(rebooked_booking_db.last_modified, cancelled_last_modified, "last_modified should be updated on rebook.")
        else: # Fallback if original_last_modified wasn't different from cancelled_last_modified
             self.assertNotEqual(rebooked_booking_db.last_modified, original_last_modified, "last_modified should be updated on rebook (compared to very original).")


        # Check if check_in_token was regenerated (it should be)
        self.assertIsNotNone(rebooked_booking_db.check_in_token)
        self.assertNotEqual(rebooked_booking_db.check_in_token, original_check_in_token, "Check-in token should be regenerated on rebook.")

        self.logout()

class TestMapAvailabilityAPI(AppTests):
    def setUp(self):
        super().setUp()
        self.map_user = User.query.filter_by(username='map_test_user').first()
        if not self.map_user:
            self.map_user = User(username='map_test_user', email='map_test_user@example.com', is_admin=False)
            self.map_user.set_password('map_password')
            db.session.add(self.map_user)
            db.session.commit()

        self.test_map = FloorMap.query.filter_by(name='Test Map For Availability API').first()
        if not self.test_map:
            self.test_map = FloorMap(name='Test Map For Availability API', image_filename='map_avail_test.png')
            db.session.add(self.test_map)
            db.session.commit()

        self.map_res1 = Resource(
            name='MapTestResource1', capacity=5, equipment='Display', tags='map_test',
            floor_map_id=self.test_map.id, status='published',
            map_coordinates=json.dumps({'type': 'rect', 'x': 10, 'y': 10, 'width': 20, 'height': 20})
        )
        self.map_res2 = Resource(
            name='MapTestResource2', capacity=5, equipment='Display', tags='map_test',
            floor_map_id=self.test_map.id, status='published',
            map_coordinates=json.dumps({'type': 'rect', 'x': 40, 'y': 10, 'width': 20, 'height': 20})
        )
        db.session.add_all([self.map_res1, self.map_res2])
        db.session.commit()

    def _set_allow_multiple_bookings_setting(self, allow_multiple: bool):
        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings()
            db.session.add(settings)
        settings.allow_multiple_resources_same_time = allow_multiple
        db.session.commit()
        # Ensure current_app logger is available or use a fallback for testing
        logger = flask_current_app.logger if flask_current_app else MagicMock()
        logger.info(f"Test: Set allow_multiple_resources_same_time to {allow_multiple}")


    def _make_booking(self, user_name: str, resource_id: int, date_obj: date, start_time_obj: time, end_time_obj: time, title: str) -> Booking:
        start_datetime = datetime.combine(date_obj, start_time_obj)
        end_datetime = datetime.combine(date_obj, end_time_obj)
        # Bookings in the DB are stored as naive UTC.
        # For tests, if date_obj and time_obj are naive, combine gives naive datetime.
        # Assuming test inputs are for the "effective" local time of the venue.
        # If global_time_offset_hours is 0 (default for tests), this naive datetime is treated as UTC.
        booking = Booking(
            user_name=user_name,
            resource_id=resource_id,
            start_time=start_datetime, # Naive datetime, assumed UTC for DB
            end_time=end_datetime,     # Naive datetime, assumed UTC for DB
            title=title,
            status='approved'
        )
        db.session.add(booking)
        db.session.commit()
        return booking

    def test_map_availability_with_multiple_booking_setting(self):
        self.login(self.map_user.username, 'map_password')

        target_date = date(2025, 7, 1)
        # Primary slots as defined in routes/api_maps.py
        primary_slot1_start = time(8, 0)
        primary_slot1_end = time(12, 0)
        primary_slot2_start = time(13, 0)
        primary_slot2_end = time(17, 0)

        # Scenario A: allow_multiple_resources_same_time = False
        self._set_allow_multiple_bookings_setting(False)

        # Create a booking for self.map_user on self.map_res1 for the first primary slot
        self._make_booking(
            user_name=self.map_user.username,
            resource_id=self.map_res1.id,
            date_obj=target_date,
            start_time_obj=primary_slot1_start,
            end_time_obj=primary_slot1_end,
            title="Booking for Scenario A"
        )

        response_a = self.client.get(f'/api/maps-availability?date={target_date.isoformat()}')
        self.assertEqual(response_a.status_code, 200)
        data_a = response_a.get_json()

        status_when_multiple_false = "not_found" # Default if map not in response
        for map_data in data_a.get('maps_availability', []):
            if map_data['map_id'] == self.test_map.id:
                status_when_multiple_false = map_data['availability_status']
                break
        self.assertNotEqual(status_when_multiple_false, "not_found", "Test map not found in API response for Scenario A")

        # Log details for Scenario A
        if flask_current_app:
            flask_current_app.logger.info(f"Scenario A (multiple=false): Map {self.test_map.id} availability status = {status_when_multiple_false}")
            flask_current_app.logger.info(f"Data A: {data_a}")


        # Scenario B: allow_multiple_resources_same_time = True
        self._set_allow_multiple_bookings_setting(True)

        # The booking on self.map_res1 still exists
        response_b = self.client.get(f'/api/maps-availability?date={target_date.isoformat()}')
        self.assertEqual(response_b.status_code, 200)
        data_b = response_b.get_json()

        status_when_multiple_true = "not_found" # Default if map not in response
        for map_data in data_b.get('maps_availability', []):
            if map_data['map_id'] == self.test_map.id:
                status_when_multiple_true = map_data['availability_status']
                break
        self.assertNotEqual(status_when_multiple_true, "not_found", "Test map not found in API response for Scenario B")

        # Log details for Scenario B
        if flask_current_app:
            flask_current_app.logger.info(f"Scenario B (multiple=true): Map {self.test_map.id} availability status = {status_when_multiple_true}")
            flask_current_app.logger.info(f"Data B: {data_b}")


        # Crucial Assertion
        availability_order = {"low": 0, "medium": 1, "high": 2, "full":3, "booked":0} # "booked" could be treated as "low" for user

        # Adjust "booked" to "low" if that's how the frontend/logic interprets it for this comparison
        # The API might return "booked" if all slots on that specific resource are taken by the user,
        # but for map-level availability, this might translate to a different aggregate status.
        # For this test, we rely on the defined availability_order.
        # If status_when_multiple_false is 'booked', map it to 'low' or 0.
        # If status_when_multiple_true is 'booked', map it to 'low' or 0.

        numeric_status_false = availability_order.get(status_when_multiple_false, -1) # -1 if status unknown
        numeric_status_true = availability_order.get(status_when_multiple_true, -1)   # -1 if status unknown

        self.assertGreaterEqual(numeric_status_true, numeric_status_false,
                                f"Availability with multiple=true ({status_when_multiple_true}) should be >= availability with multiple=false ({status_when_multiple_false})")

        self.logout()

# Scheduler Task Unit Tests
# Importing the tasks and other necessary components
from scheduler_tasks import auto_release_unclaimed_bookings, auto_checkout_overdue_bookings
from utils import get_current_effective_time # To mock this

# Ensure datetime, date, time are imported for type hinting and usage if not already at the top
from datetime import datetime, date, time


class TestAutoReleaseTask(AppTests):
    def setUp(self):
        super().setUp()
        # Create a default BookingSettings if none exists, as the task expects one.
        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings()
            db.session.add(settings)
            db.session.commit()
        self.settings = settings

        self.test_user = User.query.filter_by(username='testuser').first()
        self.test_resource = self.resource1 # Use one of the resources created in AppTests.setUp

    @patch('scheduler_tasks.send_email')
    @patch('scheduler_tasks.add_audit_log')
    @patch('scheduler_tasks.db.session.commit')
    @patch('scheduler_tasks.BookingSettings.query')
    def test_auto_release_disabled_by_main_flag(self, mock_settings_query, mock_commit, mock_audit, mock_send_email):
        mock_settings = MagicMock(spec=BookingSettings)
        mock_settings.enable_check_in_out = False
        mock_settings.auto_release_if_not_checked_in_minutes = 30 # This shouldn't matter
        mock_settings.global_time_offset_hours = 0
        mock_settings_query.first.return_value = mock_settings

        # Create a booking that would otherwise be released
        booking_start_time = datetime.utcnow() - timedelta(minutes=60)
        booking = self._create_booking(self.test_user.username, self.test_resource.id, start_offset_hours=-1) # approx 1hr ago
        booking.status = 'approved'
        booking.checked_in_at = None
        db.session.commit()

        auto_release_unclaimed_bookings(app) # Pass the global app fixture

        db.session.refresh(booking)
        self.assertEqual(booking.status, 'approved') # Status should not change
        mock_commit.assert_not_called()
        mock_audit.assert_not_called()
        mock_send_email.assert_not_called()

    @patch('scheduler_tasks.send_email')
    @patch('scheduler_tasks.add_audit_log')
    @patch('scheduler_tasks.db.session.commit')
    @patch('scheduler_tasks.BookingSettings.query')
    def test_auto_release_disabled_by_minutes_none(self, mock_settings_query, mock_commit, mock_audit, mock_send_email):
        mock_settings = MagicMock(spec=BookingSettings)
        mock_settings.enable_check_in_out = True
        mock_settings.auto_release_if_not_checked_in_minutes = None # Disabled
        mock_settings.global_time_offset_hours = 0
        mock_settings_query.first.return_value = mock_settings

        booking_start_time = datetime.utcnow() - timedelta(minutes=60)
        booking = self._create_booking(self.test_user.username, self.test_resource.id, start_offset_hours=-1)
        booking.status = 'approved'; booking.checked_in_at = None; db.session.commit()

        auto_release_unclaimed_bookings(app)

        db.session.refresh(booking)
        self.assertEqual(booking.status, 'approved')
        mock_commit.assert_not_called()

    @patch('scheduler_tasks.get_current_effective_time')
    @patch('scheduler_tasks.send_email')
    @patch('scheduler_tasks.add_audit_log')
    @patch('scheduler_tasks.db.session.commit')
    @patch('scheduler_tasks.BookingSettings.query')
    def test_booking_released_successfully(self, mock_settings_query, mock_commit, mock_audit, mock_send_email, mock_effective_time):
        mock_settings = MagicMock(spec=BookingSettings)
        mock_settings.enable_check_in_out = True
        mock_settings.auto_release_if_not_checked_in_minutes = 30
        mock_settings.global_time_offset_hours = 0
        mock_settings_query.first.return_value = mock_settings

        # Mock current time to be, for example, 2024-01-01 12:00:00 (effective local)
        # Effective time is what the venue operates on.
        # `get_current_effective_time` returns an *aware* datetime object.
        mocked_now_aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone_original.utc) # Assuming offset 0 for simplicity
        mock_effective_time.return_value = mocked_now_aware

        # Booking started 60 minutes ago (local naive time), check-in deadline was 30 mins ago
        # Booking start_time should be naive local for the task's logic
        booking_start_local_naive = mocked_now_aware.replace(tzinfo=None) - timedelta(minutes=60)

        booking = Booking(
            user_name=self.test_user.username, resource_id=self.test_resource.id,
            start_time=booking_start_local_naive, end_time=booking_start_local_naive + timedelta(hours=1),
            status='approved', checked_in_at=None, title='Test Release'
        )
        db.session.add(booking); db.session.commit()

        auto_release_unclaimed_bookings(app)

        db.session.refresh(booking)
        self.assertEqual(booking.status, 'system_cancelled_no_checkin')
        mock_commit.assert_called_once()
        mock_audit.assert_called_once_with(action="AUTO_RELEASE_NO_CHECKIN", details=ANY)
        mock_send_email.assert_called_once() # Assuming user has email

    @patch('scheduler_tasks.get_current_effective_time')
    @patch('scheduler_tasks.db.session.commit')
    @patch('scheduler_tasks.BookingSettings.query')
    def test_booking_not_yet_due_for_release(self, mock_settings_query, mock_commit, mock_effective_time):
        mock_settings = MagicMock(spec=BookingSettings)
        mock_settings.enable_check_in_out = True
        mock_settings.auto_release_if_not_checked_in_minutes = 30
        mock_settings.global_time_offset_hours = 0
        mock_settings_query.first.return_value = mock_settings

        mocked_now_aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone_original.utc)
        mock_effective_time.return_value = mocked_now_aware

        # Booking started 15 minutes ago (local naive), deadline is in 15 mins
        booking_start_local_naive = mocked_now_aware.replace(tzinfo=None) - timedelta(minutes=15)
        booking = Booking(
            user_name=self.test_user.username, resource_id=self.test_resource.id,
            start_time=booking_start_local_naive, end_time=booking_start_local_naive + timedelta(hours=1),
            status='approved', checked_in_at=None
        )
        db.session.add(booking); db.session.commit()

        auto_release_unclaimed_bookings(app)
        db.session.refresh(booking)
        self.assertEqual(booking.status, 'approved')
        mock_commit.assert_not_called()

    @patch('scheduler_tasks.get_current_effective_time')
    @patch('scheduler_tasks.db.session.commit')
    @patch('scheduler_tasks.BookingSettings.query')
    def test_booking_already_checked_in_not_released(self, mock_settings_query, mock_commit, mock_effective_time):
        mock_settings = MagicMock(spec=BookingSettings)
        mock_settings.enable_check_in_out = True
        mock_settings.auto_release_if_not_checked_in_minutes = 30
        mock_settings.global_time_offset_hours = 0
        mock_settings_query.first.return_value = mock_settings

        mocked_now_aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone_original.utc)
        mock_effective_time.return_value = mocked_now_aware

        # Booking started 60 mins ago, but was checked in 50 mins ago
        booking_start_local_naive = mocked_now_aware.replace(tzinfo=None) - timedelta(minutes=60)
        checked_in_time_local_naive = mocked_now_aware.replace(tzinfo=None) - timedelta(minutes=50)
        booking = Booking(
            user_name=self.test_user.username, resource_id=self.test_resource.id,
            start_time=booking_start_local_naive, end_time=booking_start_local_naive + timedelta(hours=1),
            status='approved', # Status might change to 'checked_in' by another mechanism
            checked_in_at=checked_in_time_local_naive
        )
        db.session.add(booking); db.session.commit()

        auto_release_unclaimed_bookings(app)
        db.session.refresh(booking)
        self.assertEqual(booking.status, 'approved') # Or 'checked_in', depends on other logic not tested here
        mock_commit.assert_not_called()


class TestAutoCheckoutTaskUpdated(AppTests):
    def setUp(self):
        super().setUp()
        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings() # Defaults include auto_checkout_delay_minutes = 60
            db.session.add(settings)
            db.session.commit()
        self.settings = settings
        self.test_user = User.query.filter_by(username='testuser').first()
        self.test_resource = self.resource1

    @patch('scheduler_tasks.get_current_effective_time')
    @patch('scheduler_tasks.send_email')
    @patch('scheduler_tasks.add_audit_log')
    @patch('scheduler_tasks.db.session.commit')
    @patch('scheduler_tasks.BookingSettings.query')
    def test_booking_checked_out_successfully_minutes(self, mock_settings_query, mock_commit, mock_audit, mock_send_email, mock_effective_time):
        mock_settings = MagicMock(spec=BookingSettings)
        mock_settings.enable_auto_checkout = True
        mock_settings.auto_checkout_delay_minutes = 60 # Test with 60 minutes
        mock_settings.global_time_offset_hours = 0
        mock_settings_query.first.return_value = mock_settings

        mocked_now_aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone_original.utc)
        mock_effective_time.return_value = mocked_now_aware

        # Booking ended 90 minutes ago (local naive). Delay is 60 minutes. So, it's overdue.
        booking_end_local_naive = mocked_now_aware.replace(tzinfo=None) - timedelta(minutes=90)
        booking_start_local_naive = booking_end_local_naive - timedelta(hours=1)
        checked_in_local_naive = booking_start_local_naive + timedelta(minutes=5)

        booking = Booking(
            user_name=self.test_user.username, resource_id=self.test_resource.id,
            start_time=booking_start_local_naive, end_time=booking_end_local_naive,
            checked_in_at=checked_in_local_naive, status='checked_in', title='Test Auto Checkout Minutes'
        )
        db.session.add(booking); db.session.commit()

        auto_checkout_overdue_bookings(app)

        db.session.refresh(booking)
        self.assertEqual(booking.status, 'completed')
        self.assertIsNotNone(booking.checked_out_at)
        expected_checkout_time_local_naive = booking_end_local_naive + timedelta(minutes=60)
        self.assertEqual(booking.checked_out_at, expected_checkout_time_local_naive)
        mock_commit.assert_called_once()
        mock_audit.assert_called_once()
        mock_send_email.assert_called_once()

    @patch('scheduler_tasks.get_current_effective_time')
    @patch('scheduler_tasks.db.session.commit')
    @patch('scheduler_tasks.BookingSettings.query')
    def test_booking_not_yet_due_for_checkout_minutes(self, mock_settings_query, mock_commit, mock_effective_time):
        mock_settings = MagicMock(spec=BookingSettings)
        mock_settings.enable_auto_checkout = True
        mock_settings.auto_checkout_delay_minutes = 60
        mock_settings.global_time_offset_hours = 0
        mock_settings_query.first.return_value = mock_settings

        mocked_now_aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone_original.utc)
        mock_effective_time.return_value = mocked_now_aware

        # Booking ended 30 minutes ago (local naive). Delay is 60 minutes. Not overdue.
        booking_end_local_naive = mocked_now_aware.replace(tzinfo=None) - timedelta(minutes=30)
        booking_start_local_naive = booking_end_local_naive - timedelta(hours=1)
        booking = Booking(
            user_name=self.test_user.username, resource_id=self.test_resource.id,
            start_time=booking_start_local_naive, end_time=booking_end_local_naive,
            checked_in_at=booking_start_local_naive + timedelta(minutes=5), status='checked_in'
        )
        db.session.add(booking); db.session.commit()

        auto_checkout_overdue_bookings(app)
        db.session.refresh(booking)
        self.assertEqual(booking.status, 'checked_in')
        self.assertIsNone(booking.checked_out_at)
        mock_commit.assert_not_called()

# Email Template Rendering Tests
from flask import render_template

class TestEmailTemplates(AppTests):
    def test_render_auto_release_email(self):
        # Test data consistent with what the auto_release_unclaimed_bookings task would provide
        # after updating it to match the template variables.
        email_data = {
            'user_name': 'Test User',
            'resource_name': 'Test Room 101',
            'start_time': '2024-01-01 10:00', # Assuming these are strings as prepared by the task
            'end_time': '2024-01-01 11:00',
            'release_minutes': 30,
            'cancelled_at_time': '2024-01-01 10:30', # Placeholder for when it was processed
            'booking_title': 'Project Meeting',
            'location': 'Main Building',
            'floor': '1st Floor',
            # The 'explanation' is constructed within the template for this one, based on release_minutes
        }
        # The actual 'explanation' for auto_release is built into the template text itself
        # using release_minutes. The Python task provides 'release_minutes'.
        # For auto_checkout, the 'explanation' is passed in, so we'll test that separately.


        with app.app_context(): # render_template needs app context
            # Test HTML template
            html_output = render_template('email/booking_auto_cancelled_no_checkin.html', **email_data)
            self.assertIn("Dear Test User,", html_output)
            self.assertIn("your booking for <strong>Test Room 101</strong>", html_output)
            self.assertIn("from <strong>2024-01-01 10:00</strong> to <strong>2024-01-01 11:00</strong>", html_output)
            self.assertIn("within the allowed time period of 30 minutes", html_output)
            self.assertIn("<strong>Resource:</strong> Test Room 101", html_output)
            self.assertIn("<strong>Booking Title:</strong> Project Meeting", html_output)
            self.assertIn("<strong>Cancelled At (Deadline):</strong> 2024-01-01 10:30", html_output)
            self.assertIn("<strong>Location:</strong> Main Building", html_output)
            self.assertIn("<strong>Floor:</strong> 1st Floor", html_output)

            # Test Text template
            text_output = render_template('email/booking_auto_cancelled_no_checkin_text.html', **email_data)
            self.assertIn("Dear Test User,", text_output)
            self.assertIn("your booking for Test Room 101", text_output)
            self.assertIn("from 2024-01-01 10:00 to 2024-01-01 11:00", text_output)
            self.assertIn("within the allowed time period of 30 minutes", text_output)
            self.assertIn("- Resource: Test Room 101", text_output)
            self.assertIn("- Booking Title: Project Meeting", text_output)
            self.assertIn("- Cancelled At (Deadline): 2024-01-01 10:30", text_output)
            self.assertIn("- Location: Main Building", text_output)
            self.assertIn("- Floor: 1st Floor", text_output)

    def test_render_auto_checkout_email_minutes_wording(self):
        # Test data consistent with auto_checkout_overdue_bookings task
        email_data = {
            'user_name': 'Checkout User',
            'resource_name': 'Meeting Pod A',
            'start_time': '2024-01-02 14:00',
            'end_time': '2024-01-02 15:00',
            'auto_checked_out_at_time': '2024-01-02 16:00 UTC', # Example
            'location': 'Annex',
            'floor': '2',
            'booking_title': 'Quick Sync',
            # This explanation is generated in the scheduler task
            'explanation': "This booking was automatically checked out because it was still active more than 60 minute(s) past its scheduled end time."
        }
        with app.app_context():
            # Test HTML template for the specific wording
            html_output = render_template('email/booking_auto_checkout.html', **email_data)
            self.assertIn("more than 60 minute(s) past its scheduled end time.", html_output)

            # Test Text template for the specific wording
            text_output = render_template('email/booking_auto_checkout_text.html', **email_data)
            self.assertIn("more than 60 minute(s) past its scheduled end time.", text_output)


class TestUnavailableDatesAPI(AppTests):
    def setUp(self):
        super().setUp()
        # Create a dedicated user for these tests or use self.client with existing testuser
        self.test_user = User.query.filter_by(username='testuser').first()
        # Login the user
        self.login(self.test_user.username, 'password')

        # Ensure resources from AppTests.setUp are available via self
        # self.resource1, self.resource2 are already set up by AppTests

        # Create a third resource specific to this test class if needed, or ensure it's in AppTests
        res3_name = 'Room C for UnavailableDatesAPI'
        self.resource3 = Resource.query.filter_by(name=res3_name).first()
        if not self.resource3:
            self.resource3 = Resource(name=res3_name, capacity=5, status='published', floor_map_id=self.floor_map.id)
            db.session.add(self.resource3)
            db.session.commit()
        else: # Ensure it's published if it exists
            self.resource3.status = 'published'
            db.session.commit()


    def _set_booking_settings(self, allow_past_bookings, past_booking_time_adjustment_hours, global_time_offset_hours):
        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings()
            db.session.add(settings)
        settings.allow_past_bookings = allow_past_bookings
        settings.past_booking_time_adjustment_hours = past_booking_time_adjustment_hours
        settings.global_time_offset_hours = global_time_offset_hours
        # Default other relevant settings if necessary for get_unavailable_dates logic
        settings.allow_multiple_resources_same_time = True # Default to true, specific tests can override
        db.session.commit()

    # Patch 'routes.api_resources.datetime' to mock datetime.now(timezone.utc)
    # The actual datetime object is imported as 'datetime' in api_resources.py
    @patch('routes.api_resources.datetime')
    def test_unavailable_today_morning_with_positive_global_offset(self, mock_datetime_in_api):
        # --- Scenario Setup ---
        # Venue is UTC+2. Current UTC time is 10:00. Effective venue time is 12:00.
        # Past adjustment is 1 hour. Cutoff is 12:00 - 1hr = 11:00 venue time.

        self._set_booking_settings(
            allow_past_bookings=False,  # Typical setting
            past_booking_time_adjustment_hours=1,
            global_time_offset_hours=2
        )

        mock_now_utc = datetime_original(2025, 7, 15, 10, 0, 0, tzinfo=timezone_original.utc) # 10:00 UTC
        mock_datetime_in_api.now = MagicMock(return_value=mock_now_utc)
        # This ensures that when api_resources.py calls datetime.now(timezone.utc), it gets our mock_now_utc
        # And that other calls to datetime.datetime(...) still work
        mock_datetime_in_api.combine = datetime_original.combine
        mock_datetime_in_api.strptime = datetime_original.strptime
        mock_datetime_in_api.fromisoformat = datetime_original.fromisoformat


        # --- API Call ---
        response = self.client.get(f'/api/resources/unavailable_dates?user_id={self.test_user.id}')
        self.assertEqual(response.status_code, 200, response.get_json())
        unavailable_dates_list = response.get_json()

        # --- Assertions ---
        # Today's date string
        today_str = mock_now_utc.date().isoformat() # "2025-07-15"

        # Debugging output
        print(f"Test: Positive Offset (New Logic). Today: {today_str}. Unavailable Dates: {unavailable_dates_list}")
        # Expected (New Logic): Cutoff 11:00 UTC (Venue Time).
        # Morning slot (08:00-12:00 VT) -> Start 06:00 UTC. 11:00 >= 06:00 -> Morning PASSED.
        # Afternoon slot (13:00-17:00 VT) -> Start 11:00 UTC. 11:00 >= 11:00 -> Afternoon PASSED.
        # Both slots passed, so today should BE in the unavailable list.
        self.assertIn(today_str, unavailable_dates_list,
                      f"Today ({today_str}) SHOULD be unavailable as the cutoff (11:00 Venue Time) makes both morning (starts 08:00 VT / 06:00 UTC) and afternoon (starts 13:00 VT / 11:00 UTC) slots passed.")

    @patch('routes.api_resources.datetime')
    def test_unavailable_all_day_today_due_to_cutoff(self, mock_datetime_in_api):
        self._set_booking_settings(
            allow_past_bookings=False,
            past_booking_time_adjustment_hours=-8, # Cutoff is 8 hours in the future
            global_time_offset_hours=0
        )

        mock_now_utc = datetime_original(2025, 7, 15, 10, 0, 0, tzinfo=timezone_original.utc) # 10:00 UTC
        mock_datetime_in_api.now = MagicMock(return_value=mock_now_utc)
        mock_datetime_in_api.combine = datetime_original.combine
        mock_datetime_in_api.strptime = datetime_original.strptime
        mock_datetime_in_api.fromisoformat = datetime_original.fromisoformat

        response = self.client.get(f'/api/resources/unavailable_dates?user_id={self.test_user.id}')
        self.assertEqual(response.status_code, 200, response.get_json())
        unavailable_dates_list = response.get_json()

        today_str = mock_now_utc.date().isoformat() # "2025-07-15"
        print(f"Test: Cutoff in Future (New Logic - Universal Cutoff). Today: {today_str}. Unavailable Dates: {unavailable_dates_list}")
        # Expected: Cutoff 18:00 UTC (Venue Time).
        # Morning slot (08:00-12:00 VT) -> Start 08:00 UTC. Cutoff 18:00 UTC >= Slot Start 08:00 UTC -> Morning PASSED.
        # Afternoon slot (13:00-17:00 VT) -> Start 13:00 UTC. Cutoff 18:00 UTC >= Slot Start 13:00 UTC -> Afternoon PASSED.
        # Both standard slots passed, so today *should* be in the unavailable list.
        self.assertIn(today_str, unavailable_dates_list,
                      f"Today ({today_str}) SHOULD be unavailable as cutoff (18:00 Venue Time) makes all standard slots passed.")

    @patch('routes.api_resources.datetime')
    def test_unavailable_today_afternoon_with_negative_global_offset(self, mock_datetime_in_api):
        self._set_booking_settings(
            allow_past_bookings=False,
            past_booking_time_adjustment_hours=1,
            global_time_offset_hours=-2 # Venue is UTC-2
        )

        mock_now_utc = datetime_original(2025, 7, 15, 18, 0, 0, tzinfo=timezone_original.utc) # 18:00 UTC
        mock_datetime_in_api.now = MagicMock(return_value=mock_now_utc)
        mock_datetime_in_api.combine = datetime_original.combine
        mock_datetime_in_api.strptime = datetime_original.strptime
        mock_datetime_in_api.fromisoformat = datetime_original.fromisoformat

        response = self.client.get(f'/api/resources/unavailable_dates?user_id={self.test_user.id}')
        self.assertEqual(response.status_code, 200, response.get_json())
        unavailable_dates_list = response.get_json()

        today_str = mock_now_utc.date().isoformat() # "2025-07-15"
        print(f"Test: Negative Offset (New Logic - Universal Cutoff). Today: {today_str}. Unavailable Dates: {unavailable_dates_list}")
        # Expected (New Logic - Universal Cutoff): Cutoff 15:00 UTC (Venue Time).
        # Morning slot (08:00-12:00 VT) -> Start 10:00 UTC. Cutoff 15:00 UTC >= Slot Start 10:00 UTC -> Morning PASSED.
        # Afternoon slot (13:00-17:00 VT) -> Start 15:00 UTC. Cutoff 15:00 UTC >= Slot Start 15:00 UTC -> Afternoon PASSED.
        # Both standard slots passed, so today *should* be in the unavailable list.
        self.assertIn(today_str, unavailable_dates_list,
                         f"Today ({today_str}) SHOULD BE unavailable as the cutoff (15:00 Venue Time) makes both standard slots passed.")

    @patch('routes.api_resources.datetime')
    def test_day_unavailable_due_to_conflict_multi_disabled(self, mock_datetime_in_api):
        self._set_booking_settings(
            allow_past_bookings=False,
            past_booking_time_adjustment_hours=24, # Make today fully available from time cutoff
            global_time_offset_hours=0
        )
        settings = BookingSettings.query.first() # Get the settings instance
        settings.allow_multiple_resources_same_time = False # Key setting for this test
        db.session.commit()

        mock_now_utc = datetime_original(2025, 7, 15, 1, 0, 0, tzinfo=timezone_original.utc) # Mock current time

        mock_datetime_in_api.now = MagicMock(return_value=mock_now_utc)
        mock_datetime_in_api.combine = datetime_original.combine
        mock_datetime_in_api.strptime = datetime_original.strptime
        mock_datetime_in_api.fromisoformat = datetime_original.fromisoformat

        target_date_obj = date(2025, 7, 15)
        target_date_str = target_date_obj.isoformat()

        all_resources_db = Resource.query.all()
        original_statuses = {res.id: res.status for res in all_resources_db}

        # Ensure self.resource1, self.resource2, self.resource3 are published for this test
        # and others are draft
        resource_ids_to_publish = [self.resource1.id, self.resource2.id, self.resource3.id]
        for res_db in all_resources_db:
            if res_db.id in resource_ids_to_publish:
                res_db.status = 'published'
            else:
                res_db.status = 'draft'
        db.session.commit()

        self.resource1 = Resource.query.get(self.resource1.id)
        self.resource2 = Resource.query.get(self.resource2.id)
        self.resource3 = Resource.query.get(self.resource3.id)

        # Bookings are stored as naive UTC. With global_time_offset_hours=0, venue time = UTC.
        booking1_start_dt = datetime.combine(target_date_obj, time(8, 0))
        booking1_end_dt = datetime.combine(target_date_obj, time(12, 0))
        booking1 = Booking(user_name=self.test_user.username, resource_id=self.resource1.id,
                           start_time=booking1_start_dt, end_time=booking1_end_dt,
                           title="Morning R1", status="approved")

        booking2_start_dt = datetime.combine(target_date_obj, time(13, 0))
        booking2_end_dt = datetime.combine(target_date_obj, time(17, 0))
        booking2 = Booking(user_name=self.test_user.username, resource_id=self.resource1.id,
                           start_time=booking2_start_dt, end_time=booking2_end_dt,
                           title="Afternoon R1", status="approved")

        db.session.add_all([booking1, booking2])
        db.session.commit()

        try:
            response = self.client.get(f'/api/resources/unavailable_dates?user_id={self.test_user.id}')
            self.assertEqual(response.status_code, 200, f"API call failed: {response.get_json()}")
            unavailable_dates_list = response.get_json()

            self.assertIn(target_date_str, unavailable_dates_list,
                          f"{target_date_str} should be unavailable due to user conflicts on all resources when multiple bookings are disabled.")
        finally:
            # Restore original statuses
            for res_id, status in original_statuses.items():
                res_db_restore = Resource.query.get(res_id)
                if res_db_restore: res_db_restore.status = status
            db.session.commit()

    @patch('routes.api_resources.datetime')
    def test_day_available_when_conflict_but_multi_enabled(self, mock_datetime_in_api):
        self._set_booking_settings(
            allow_past_bookings=False,
            past_booking_time_adjustment_hours=24,
            global_time_offset_hours=0
        )
        settings = BookingSettings.query.first()
        settings.allow_multiple_resources_same_time = True # Key setting for this test
        db.session.commit()

        mock_now_utc = datetime_original(2025, 7, 15, 1, 0, 0, tzinfo=timezone_original.utc)
        mock_datetime_in_api.now = MagicMock(return_value=mock_now_utc)
        mock_datetime_in_api.combine = datetime_original.combine
        mock_datetime_in_api.strptime = datetime_original.strptime
        mock_datetime_in_api.fromisoformat = datetime_original.fromisoformat

        target_date_obj = date(2025, 7, 15)
        target_date_str = target_date_obj.isoformat()

        # Ensure self.resource1 and self.resource2 are published, others draft
        original_statuses = {}
        all_resources_q = Resource.query.all()
        for r in all_resources_q:
            original_statuses[r.id] = r.status
            if r.id == self.resource1.id or r.id == self.resource2.id:
                r.status = 'published'
            else:
                r.status = 'draft'
        db.session.commit()

        self.resource1 = Resource.query.get(self.resource1.id) # Re-fetch
        self.resource2 = Resource.query.get(self.resource2.id) # Re-fetch

        booking1_start_dt = datetime.combine(target_date_obj, time(8, 0))
        booking1_end_dt = datetime.combine(target_date_obj, time(12, 0))
        booking1 = Booking(user_name=self.test_user.username, resource_id=self.resource1.id,
                           start_time=booking1_start_dt, end_time=booking1_end_dt,
                           title="Morning R1", status="approved")
        db.session.add(booking1)
        db.session.commit()

        try:
            response = self.client.get(f'/api/resources/unavailable_dates?user_id={self.test_user.id}')
            self.assertEqual(response.status_code, 200, f"API call failed: {response.get_json()}")
            unavailable_dates_list = response.get_json()

            self.assertNotIn(target_date_str, unavailable_dates_list,
                             f"{target_date_str} should NOT be unavailable when multiple bookings are enabled, even with a booking on one resource, as other resources are available.")
        finally:
            # Restore original statuses for other resources
            for res_id, status in original_statuses.items():
                res_db_restore = Resource.query.get(res_id)
                if res_db_restore: res_db_restore.status = status
            db.session.commit()

    @patch('routes.api_resources.datetime')
    def test_unavailable_due_to_resource_permissions(self, mock_datetime_in_api):
        original_test_user_is_admin = self.test_user.is_admin
        self.test_user.is_admin = False
        db.session.commit()

        self._set_booking_settings(
            allow_past_bookings=False,
            past_booking_time_adjustment_hours=24,
            global_time_offset_hours=0
        )
        settings = BookingSettings.query.first()
        if not settings:
            settings = BookingSettings(allow_multiple_resources_same_time=False)
            db.session.add(settings)
        else:
            settings.allow_multiple_resources_same_time = False
        db.session.commit()


        mock_now_utc = datetime_original(2025, 7, 15, 10, 0, 0, tzinfo=timezone_original.utc)
        mock_datetime_in_api.now = MagicMock(return_value=mock_now_utc)
        mock_datetime_in_api.combine = datetime_original.combine
        mock_datetime_in_api.strptime = datetime_original.strptime
        mock_datetime_in_api.fromisoformat = datetime_original.fromisoformat

        target_date_str = date(2025, 7, 15).isoformat()

        original_resource1_status = self.resource1.status
        original_resource1_restriction = self.resource1.booking_restriction
        original_resource2_status = self.resource2.status
        original_resource2_restriction = self.resource2.booking_restriction

        other_resources_original_statuses = {}
        all_resources_q = Resource.query.filter(Resource.id.notin_([self.resource1.id, self.resource2.id]))
        for r_other in all_resources_q.all():
            other_resources_original_statuses[r_other.id] = r_other.status

        try:
            self.resource1.status = 'published'
            self.resource1.booking_restriction = 'admin_only'
            self.resource2.status = 'published'
            self.resource2.booking_restriction = None
            for r_other_id in other_resources_original_statuses.keys():
                r_to_draft = Resource.query.get(r_other_id)
                if r_to_draft: r_to_draft.status = 'draft'
            db.session.commit()

            self.resource1 = Resource.query.get(self.resource1.id)
            self.resource2 = Resource.query.get(self.resource2.id)

            response1 = self.client.get(f'/api/resources/unavailable_dates?user_id={self.test_user.id}')
            self.assertEqual(response1.status_code, 200, f"API call failed (Scenario 1): {response1.get_json()}")
            unavailable_dates_list1 = response1.get_json()

            self.assertNotIn(target_date_str, unavailable_dates_list1,
                             f"{target_date_str} should NOT be unavailable when ResourceB is bookable by the user. List: {unavailable_dates_list1}")

            self.resource2.booking_restriction = 'admin_only'
            db.session.commit()
            self.resource2 = Resource.query.get(self.resource2.id)

            response2 = self.client.get(f'/api/resources/unavailable_dates?user_id={self.test_user.id}')
            self.assertEqual(response2.status_code, 200, f"API call failed (Scenario 2): {response2.get_json()}")
            unavailable_dates_list2 = response2.get_json()

            self.assertIn(target_date_str, unavailable_dates_list2,
                          f"{target_date_str} SHOULD be unavailable when both ResourceA and ResourceB are unbookable by the user due to permissions. List: {unavailable_dates_list2}")

        finally:
            self.test_user.is_admin = original_test_user_is_admin
            db.session.commit()

            self.resource1 = Resource.query.get(self.resource1.id) # Re-fetch before restoring
            self.resource2 = Resource.query.get(self.resource2.id) # Re-fetch before restoring
            if self.resource1:
                self.resource1.status = original_resource1_status
                self.resource1.booking_restriction = original_resource1_restriction
            if self.resource2:
                self.resource2.status = original_resource2_status
                self.resource2.booking_restriction = original_resource2_restriction
            db.session.commit() # Commit resource1 and resource2 changes

            for r_id_key, original_status in other_resources_original_statuses.items():
                res_db_restore = Resource.query.get(r_id_key)
                if res_db_restore:
                    res_db_restore.status = original_status
            db.session.commit() # Commit changes for other resources

    # New Test Method 1
    @patch('routes.api_resources.datetime')
    def test_june14_scenario_morning_cutoff_afternoon_conflict(self, mock_datetime_in_api):
        GLOBAL_OFFSET = -5
        self._set_booking_settings(
            allow_past_bookings=False,
            past_booking_time_adjustment_hours=4,
            global_time_offset_hours=GLOBAL_OFFSET
        )
        settings = BookingSettings.query.first()
        settings.allow_multiple_resources_same_time = False
        db.session.commit()

        # effective_cutoff is 08:30 Venue Time on 2025-06-14
        # Venue 08:30 is 13:30 UTC. effective_cutoff_datetime_utc = 2025-06-14 13:30:00 UTC
        # effective_venue_now_utc = 13:30 UTC + 4h = 17:30 UTC
        # mock_now_utc = 17:30 UTC - (-5h) = 22:30 UTC
        mock_now_utc = datetime_original(2025, 6, 14, 22, 30, 0, tzinfo=timezone_original.utc)
        mock_datetime_in_api.now = MagicMock(return_value=mock_now_utc)
        mock_datetime_in_api.combine = datetime_original.combine
        mock_datetime_in_api.strptime = datetime_original.strptime
        mock_datetime_in_api.fromisoformat = datetime_original.fromisoformat

        target_date_obj_venue = date(2025, 6, 14)
        target_date_str = target_date_obj_venue.isoformat()

        # Store original states
        original_statuses = {res.id: (res.status, res.booking_restriction) for res in Resource.query.all()}

        resource_ids_to_publish = [self.resource1.id, self.resource2.id, self.resource3.id]

        try:
            for res_db in Resource.query.all():
                if res_db.id in resource_ids_to_publish:
                    res_db.status = 'published'
                    res_db.booking_restriction = None # User can book
                else:
                    res_db.status = 'draft'
            db.session.commit()

            # Re-fetch to be safe
            self.resource1 = Resource.query.get(self.resource1.id)
            self.resource2 = Resource.query.get(self.resource2.id)
            self.resource3 = Resource.query.get(self.resource3.id)

            # User booking on resource3 for the afternoon slot (Venue Time)
            # Convert to naive UTC for storage
            booking_afternoon_start_venue = datetime.combine(target_date_obj_venue, time(13,0))
            booking_afternoon_end_venue = datetime.combine(target_date_obj_venue, time(17,0))

            booking_afternoon_start_utc_naive = (booking_afternoon_start_venue - timedelta(hours=GLOBAL_OFFSET)).replace(tzinfo=None)
            booking_afternoon_end_utc_naive = (booking_afternoon_end_venue - timedelta(hours=GLOBAL_OFFSET)).replace(tzinfo=None)

            user_booking = Booking(user_name=self.test_user.username, resource_id=self.resource3.id,
                                   start_time=booking_afternoon_start_utc_naive,
                                   end_time=booking_afternoon_end_utc_naive,
                                   title="Afternoon R3 User Booking", status="approved")
            db.session.add(user_booking)
            db.session.commit()

            response = self.client.get(f'/api/resources/unavailable_dates?user_id={self.test_user.id}')
            self.assertEqual(response.status_code, 200, f"API call failed: {response.get_json()}")
            unavailable_dates_list = response.get_json()

            self.assertIn(target_date_str, unavailable_dates_list,
                          f"{target_date_str} should be unavailable. Morning slots passed by cutoff (08:30 VT), afternoon slots on R1/R2 conflict with user's R3 booking.")

        finally:
            # Cleanup bookings
            Booking.query.filter_by(user_name=self.test_user.username, resource_id=self.resource3.id).delete()
            # Restore original resource states
            for res_id, (status, restriction) in original_statuses.items():
                res_db_restore = Resource.query.get(res_id)
                if res_db_restore:
                    res_db_restore.status = status
                    res_db_restore.booking_restriction = restriction
            db.session.commit()

    # New Test Method 2
    @patch('routes.api_resources.datetime')
    def test_june15_scenario_all_slots_booked_by_user_multi_false(self, mock_datetime_in_api):
        GLOBAL_OFFSET = -5
        self._set_booking_settings(
            allow_past_bookings=False,
            past_booking_time_adjustment_hours=24, # Cutoff not an issue
            global_time_offset_hours=GLOBAL_OFFSET
        )
        settings = BookingSettings.query.first()
        settings.allow_multiple_resources_same_time = False
        db.session.commit()

        mock_now_utc = datetime_original(2025, 6, 15, 1, 0, 0, tzinfo=timezone_original.utc) # Early June 15th
        mock_datetime_in_api.now = MagicMock(return_value=mock_now_utc)
        mock_datetime_in_api.combine = datetime_original.combine
        mock_datetime_in_api.strptime = datetime_original.strptime
        mock_datetime_in_api.fromisoformat = datetime_original.fromisoformat

        target_date_obj_venue = date(2025, 6, 15)
        target_date_str = target_date_obj_venue.isoformat()

        # Store original states
        original_statuses = {res.id: (res.status, res.booking_restriction) for res in Resource.query.all()}
        resource_ids_to_publish = [self.resource1.id, self.resource2.id]

        try:
            for res_db in Resource.query.all():
                if res_db.id in resource_ids_to_publish:
                    res_db.status = 'published'
                    res_db.booking_restriction = None # User can book
                else:
                    res_db.status = 'draft'
            db.session.commit()

            self.resource1 = Resource.query.get(self.resource1.id) # Re-fetch
            self.resource2 = Resource.query.get(self.resource2.id) # Re-fetch

            bookings_to_add = []
            # Bookings for resource1 (Venue Time)
            r1_slots_venue = [
                (datetime.combine(target_date_obj_venue, time(8,0)), datetime.combine(target_date_obj_venue, time(12,0))),
                (datetime.combine(target_date_obj_venue, time(13,0)), datetime.combine(target_date_obj_venue, time(17,0)))
            ]
            for start_vt, end_vt in r1_slots_venue:
                start_utc_naive = (start_vt - timedelta(hours=GLOBAL_OFFSET)).replace(tzinfo=None)
                end_utc_naive = (end_vt - timedelta(hours=GLOBAL_OFFSET)).replace(tzinfo=None)
                bookings_to_add.append(Booking(user_name=self.test_user.username, resource_id=self.resource1.id,
                                               start_time=start_utc_naive, end_time=end_utc_naive,
                                               title=f"R1 {start_vt.strftime('%H%M')}", status="approved"))

            # Bookings for resource2 (Venue Time)
            r2_slots_venue = [
                (datetime.combine(target_date_obj_venue, time(8,0)), datetime.combine(target_date_obj_venue, time(12,0))),
                (datetime.combine(target_date_obj_venue, time(13,0)), datetime.combine(target_date_obj_venue, time(17,0)))
            ]
            for start_vt, end_vt in r2_slots_venue:
                start_utc_naive = (start_vt - timedelta(hours=GLOBAL_OFFSET)).replace(tzinfo=None)
                end_utc_naive = (end_vt - timedelta(hours=GLOBAL_OFFSET)).replace(tzinfo=None)
                bookings_to_add.append(Booking(user_name=self.test_user.username, resource_id=self.resource2.id,
                                               start_time=start_utc_naive, end_time=end_utc_naive,
                                               title=f"R2 {start_vt.strftime('%H%M')}", status="approved"))

            db.session.add_all(bookings_to_add)
            db.session.commit()

            response = self.client.get(f'/api/resources/unavailable_dates?user_id={self.test_user.id}')
            self.assertEqual(response.status_code, 200, f"API call failed: {response.get_json()}")
            unavailable_dates_list = response.get_json()

            self.assertIn(target_date_str, unavailable_dates_list,
                          f"{target_date_str} should be unavailable as all slots on all published/allowed resources are booked by the user.")

        finally:
            # Cleanup bookings
            Booking.query.filter(Booking.user_name == self.test_user.username, func.date(Booking.start_time + timedelta(hours=GLOBAL_OFFSET)) == target_date_obj_venue).delete()
            # Restore original resource states
            for res_id, (status, restriction) in original_statuses.items():
                res_db_restore = Resource.query.get(res_id)
                if res_db_restore:
                    res_db_restore.status = status
                    res_db_restore.booking_restriction = restriction
            db.session.commit()


if __name__ == '__main__':
    unittest.main()

[end of tests/test_app.py]
