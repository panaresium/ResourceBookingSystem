import datetime
import unittest
from unittest.mock import MagicMock, patch

# --- Mock Models ---
class User:
    def __init__(self, id, username, email="testuser@example.com", is_admin=False):
        self.id = id
        self.username = username
        self.email = email
        self.is_admin = is_admin
        self.is_authenticated = True # For current_user mocks

class Resource:
    def __init__(self, id, name, current_pin=None):
        self.id = id
        self.name = name
        self.current_pin = current_pin # This field seems less used than ResourcePIN table by the API
        self.pins = [] # To store ResourcePIN objects

class ResourcePIN:
    def __init__(self, id, resource_id, pin_value, is_active=True):
        self.id = id
        self.resource_id = resource_id
        self.pin_value = pin_value
        self.is_active = is_active

class Booking:
    def __init__(self, id, resource_id, user_name, start_time, end_time, status='approved', checked_in_at=None):
        self.id = id
        self.resource_id = resource_id
        self.user_name = user_name
        self.start_time = start_time
        self.end_time = end_time
        self.status = status
        self.checked_in_at = checked_in_at
        self.resource_booked = None # Will be linked to a Resource object

class BookingSettings:
    def __init__(self, id=1, enable_check_in_out=True, check_in_minutes_before=15, check_in_minutes_after=15, global_time_offset_hours=0):
        self.id = id
        self.enable_check_in_out = enable_check_in_out
        self.check_in_minutes_before = check_in_minutes_before
        self.check_in_minutes_after = check_in_minutes_after
        self.global_time_offset_hours = global_time_offset_hours

# --- Mock DB ---
mock_db_data = {
    "users": [],
    "resources": [],
    "resource_pins": [],
    "bookings": [],
    "booking_settings": []
}

# Helper to reset and populate mock_db_data for each test
def setup_mock_db():
    mock_db_data["users"] = []
    mock_db_data["resources"] = []
    mock_db_data["resource_pins"] = []
    mock_db_data["bookings"] = []
    mock_db_data["booking_settings"] = [BookingSettings()] # Default settings

    # Test User
    test_user = User(id=1, username="testuser")
    mock_db_data["users"].append(test_user)

    # Resource with PIN
    resource_pin = Resource(id=1, name="Test Room PIN")
    mock_db_data["resources"].append(resource_pin)
    active_pin = ResourcePIN(id=1, resource_id=1, pin_value="12345", is_active=True)
    resource_pin.pins.append(active_pin) # Link PIN to resource
    mock_db_data["resource_pins"].append(active_pin)


    # Resource without PIN
    resource_no_pin = Resource(id=2, name="Test Room NoPIN")
    mock_db_data["resources"].append(resource_no_pin)

    # Bookings
    now = datetime.datetime.now(datetime.timezone.utc)
    booking_pin_resource = Booking(
        id=1, resource_id=1, user_name="testuser",
        start_time=now - datetime.timedelta(minutes=5),
        end_time=now + datetime.timedelta(hours=1),
        status='approved'
    )
    booking_pin_resource.resource_booked = resource_pin # Link resource to booking
    mock_db_data["bookings"].append(booking_pin_resource)

    booking_no_pin_resource = Booking(
        id=2, resource_id=2, user_name="testuser",
        start_time=now - datetime.timedelta(minutes=5),
        end_time=now + datetime.timedelta(hours=1),
        status='approved'
    )
    booking_no_pin_resource.resource_booked = resource_no_pin
    mock_db_data["bookings"].append(booking_no_pin_resource)

    # Booking for PIN required but user tries to check in without PIN
    booking_pin_resource_no_pin_attempt = Booking(
        id=3, resource_id=1, user_name="testuser", # Uses resource_pin which has a PIN
        start_time=now - datetime.timedelta(minutes=3),
        end_time=now + datetime.timedelta(hours=2),
        status='approved'
    )
    booking_pin_resource_no_pin_attempt.resource_booked = resource_pin
    mock_db_data["bookings"].append(booking_pin_resource_no_pin_attempt)


# --- Mock Flask app and db session ---
mock_app = MagicMock()
mock_app.logger = MagicMock()

mock_db_session = MagicMock()
mock_db_session.commit = MagicMock()
mock_db_session.rollback = MagicMock()

# --- Mock API route logic (simplified from routes/api_bookings.py) ---
def mockable_check_in_booking(booking_id, provided_pin, current_user_username="testuser"):
    booking = next((b for b in mock_db_data["bookings"] if b.id == booking_id), None)
    if not booking:
        return {'error': 'Booking not found.'}, 404

    user = next((u for u in mock_db_data["users"] if u.username == current_user_username), None)
    if not user: # Should not happen with current_user mock but good practice
        return {'error': 'User not found for current session.'}, 401


    if booking.user_name != user.username:
        return {'error': 'You are not authorized to check into this booking.'}, 403

    if booking.checked_in_at:
        return {'message': 'Already checked in.', 'checked_in_at': booking.checked_in_at.isoformat()}, 200

    settings = mock_db_data["booking_settings"][0]
    if not settings.enable_check_in_out:
        return {'error': 'Check-in/out feature is disabled.'}, 403

    # Calculate effective_now for check-in window validation
    _now_utc_aware = datetime.datetime.now(datetime.timezone.utc) # This will be the patched (fixed) time
    effective_now_utc_aware = _now_utc_aware + datetime.timedelta(hours=settings.global_time_offset_hours)
    # Booking times (start_time) are naive UTC in the mock DB, representing venue's local time if it were UTC.
    # So, for comparison, use naive version of effective_now.
    effective_now_naive_utc = effective_now_utc_aware.replace(tzinfo=None)

    # Booking.start_time is naive in mock_db_data, treat as naive UTC
    booking_start_naive_utc = booking.start_time

    # Check-in window logic (all naive UTC comparisons)
    check_in_window_start_naive_utc = booking_start_naive_utc - datetime.timedelta(minutes=settings.check_in_minutes_before)
    check_in_window_end_naive_utc = booking_start_naive_utc + datetime.timedelta(minutes=settings.check_in_minutes_after)

    if not (check_in_window_start_naive_utc <= effective_now_naive_utc <= check_in_window_end_naive_utc):
        return {'error': 'Check-in is only allowed within the defined window.'}, 403

    resource = booking.resource_booked # Assumes this is linked during setup
    if not resource:
         return {'error': 'Associated resource not found for this booking.'}, 500

    # PIN Validation Logic
    # Check if any PIN is configured for the resource
    resource_has_any_pin = any(p.resource_id == resource.id for p in mock_db_data["resource_pins"])

    if resource_has_any_pin: # PIN is required if configured for the resource
        if not provided_pin: # PIN was expected but not given
            mock_app.logger.warning(f"User {user.username} failed PIN check-in for booking {booking.id}. PIN required but not provided for resource {resource.id}")
            # The actual API returns 403 for "Invalid or inactive PIN" even if PIN is missing.
            # We'll simulate that for consistency, as the new UI flow will likely send an empty string if user doesn't type.
            return {'error': 'Invalid or inactive PIN provided.'}, 403


        active_pin_entry = next((
            p for p in mock_db_data["resource_pins"]
            if p.resource_id == resource.id and p.pin_value == provided_pin and p.is_active
        ), None)

        if not active_pin_entry:
            mock_app.logger.warning(f"User {user.username} failed PIN check-in for booking {booking.id}. Invalid/inactive PIN: '{provided_pin}' for resource {resource.id}")
            return {'error': 'Invalid or inactive PIN provided.'}, 403
        # If active_pin_entry is found, PIN is valid.

    # If resource_has_any_pin is False, no PIN is required, so we proceed.

    # Record check-in time using the actual time of the event (_now_utc_aware), made naive for DB storage
    booking.checked_in_at = _now_utc_aware.replace(tzinfo=None)
    mock_db_session.commit()
    return {'message': 'Check-in successful.', 'checked_in_at': booking.checked_in_at.isoformat(), 'booking_id': booking.id}, 200


class TestPINCheckIn(unittest.TestCase):

    def setUp(self):
        setup_mock_db()
        self.user = next(u for u in mock_db_data["users"] if u.username == "testuser")

    @patch('__main__.mock_db_session', new_callable=MagicMock)
    # Removed erroneous patch for current_app.logger
    @patch('__main__.mock_app.logger', new_callable=MagicMock)
    def test_scenario_1_correct_pin(self, mock_app_logger, mock_session): # Adjusted arguments
        print("\n--- Scenario 1: Correct PIN ---")
        booking_id = 1 # Booking for "Test Room PIN"
        pin = "12345"

        response, status_code = mockable_check_in_booking(booking_id, pin, self.user.username)

        print(f"Response: {response}, Status Code: {status_code}")
        self.assertEqual(status_code, 200)
        self.assertIn('Check-in successful', response.get('message', ''))
        booking = next(b for b in mock_db_data["bookings"] if b.id == booking_id)
        self.assertIsNotNone(booking.checked_in_at)
        print(f"Booking ID {booking_id} checked_in_at: {booking.checked_in_at}")

    @patch('__main__.mock_db_session', new_callable=MagicMock)
    @patch('__main__.mock_app.logger', new_callable=MagicMock)
    def test_scenario_2_incorrect_pin(self, mock_logger, mock_session):
        print("\n--- Scenario 2: Incorrect PIN ---")
        booking_id = 1 # Booking for "Test Room PIN"
        pin = "54321" # Incorrect PIN

        response, status_code = mockable_check_in_booking(booking_id, pin, self.user.username)

        print(f"Response: {response}, Status Code: {status_code}")
        self.assertEqual(status_code, 403)
        self.assertIn('Invalid or inactive PIN provided', response.get('error', ''))
        booking = next(b for b in mock_db_data["bookings"] if b.id == booking_id)
        self.assertIsNone(booking.checked_in_at)
        print(f"Booking ID {booking_id} checked_in_at remains: {booking.checked_in_at}")

    @patch('__main__.mock_db_session', new_callable=MagicMock)
    @patch('__main__.mock_app.logger', new_callable=MagicMock)
    def test_scenario_3_missing_pin_for_pin_resource(self, mock_logger, mock_session):
        print("\n--- Scenario 3: Missing PIN (Resource Requires PIN) ---")
        booking_id = 3 # Booking for "Test Room PIN", but we'll try with empty PIN
        pin = "" # Empty PIN

        response, status_code = mockable_check_in_booking(booking_id, pin, self.user.username)

        print(f"Response: {response}, Status Code: {status_code}")
        self.assertEqual(status_code, 403) # API treats empty PIN as invalid if PIN is set on resource
        self.assertIn('Invalid or inactive PIN provided', response.get('error', ''))
        booking = next(b for b in mock_db_data["bookings"] if b.id == booking_id)
        self.assertIsNone(booking.checked_in_at)
        print(f"Booking ID {booking_id} checked_in_at remains: {booking.checked_in_at}")

    @patch('__main__.mock_db_session', new_callable=MagicMock)
    @patch('__main__.mock_app.logger', new_callable=MagicMock)
    def test_scenario_4_no_pin_for_no_pin_resource(self, mock_logger, mock_session):
        print("\n--- Scenario 4: No PIN (Resource Does NOT Require PIN) ---")
        booking_id = 2 # Booking for "Test Room NoPIN"
        pin = None # No PIN provided

        response, status_code = mockable_check_in_booking(booking_id, pin, self.user.username)

        print(f"Response: {response}, Status Code: {status_code}")
        self.assertEqual(status_code, 200)
        self.assertIn('Check-in successful', response.get('message', ''))
        booking = next(b for b in mock_db_data["bookings"] if b.id == booking_id)
        self.assertIsNotNone(booking.checked_in_at)
        print(f"Booking ID {booking_id} checked_in_at: {booking.checked_in_at}")

# This allows running the tests from the command line
if __name__ == '__main__':
    # Mock current_app for the test execution context if the tested function uses it
    # For this script, we directly pass mock_app.logger or use a module-level mock
    with patch.object(datetime, 'datetime', MagicMock(wraps=datetime.datetime)) as mock_dt:
        mock_dt.now.return_value = datetime.datetime(2023, 1, 1, 10, 10, 0, tzinfo=datetime.timezone.utc) # Fixed time for testing window

        # Adjust setup_mock_db to use this fixed time if necessary for check-in window
        # Re-run setup with fixed time
        original_now = datetime.datetime.now
        datetime.datetime.now = lambda tz=None: datetime.datetime(2023, 1, 1, 10, 10, 0, tzinfo=tz if tz else datetime.timezone.utc)

        # Re-initialize DB with fixed time for booking start_times relative to this 'now'
        # For simplicity, the current setup_mock_db uses dynamic now, which is fine for relative tests.
        # If absolute time tests were needed, we'd pass the fixed_now into setup_mock_db.
        # For now, the relative time setup should work.

        # For the mockable_check_in_booking, it will use the patched datetime.datetime.now

        unittest.main(argv=['first-arg-is-ignored'], exit=False)

        datetime.datetime.now = original_now # Restore
