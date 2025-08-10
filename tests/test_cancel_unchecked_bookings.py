import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app import app
from extensions import db
from models import Booking, BookingSettings, Resource, User, AuditLog
from scheduler_tasks import cancel_unchecked_bookings


class CancelUncheckedBookingsTests(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['MAIL_SUPPRESS_SEND'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        settings = BookingSettings(enable_check_in_out=True, check_in_minutes_after=15)
        db.session.add(settings)

        user = User(username='user1', email='user1@example.com')
        user.set_password('password')
        resource = Resource(name='Resource 1', status='published')
        db.session.add_all([user, resource])
        db.session.commit()

        now = datetime.utcnow()
        past_start = now - timedelta(minutes=30)
        within_start = now - timedelta(minutes=10)

        booking1 = Booking(
            user_name='user1',
            resource_id=resource.id,
            start_time=past_start,
            end_time=past_start + timedelta(hours=1),
            status='approved'
        )
        booking2 = Booking(
            user_name='user1',
            resource_id=resource.id,
            start_time=within_start,
            end_time=within_start + timedelta(hours=1),
            status='approved'
        )
        db.session.add_all([booking1, booking2])
        db.session.commit()

        self.booking1_id = booking1.id
        self.booking2_id = booking2.id

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    @patch('scheduler_tasks.send_email')
    @patch('scheduler_tasks.render_template', return_value='body')
    def test_cancel_unchecked_bookings(self, mock_render, mock_email):
        cancel_unchecked_bookings(self.app)

        booking1 = db.session.get(Booking, self.booking1_id)
        booking2 = db.session.get(Booking, self.booking2_id)

        self.assertEqual(booking1.status, 'cancelled_by_system')
        self.assertEqual(booking2.status, 'approved')

        logs = AuditLog.query.filter_by(action='AUTO_CANCEL_NO_CHECKIN').all()
        self.assertEqual(len(logs), 1)
        self.assertIn(str(self.booking1_id), logs[0].details)
        mock_email.assert_called_once()


if __name__ == '__main__':
    unittest.main()
