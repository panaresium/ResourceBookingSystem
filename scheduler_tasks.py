from datetime import datetime, timedelta, timezone
from flask import current_app, render_template
from extensions import db # Changed to absolute import
from models import Booking, User, Resource, FloorMap, BookingSettings # Changed to absolute import
from utils import add_audit_log, send_email # Changed to absolute import

def auto_checkout_overdue_bookings():
    """
    Automatically checks out bookings that are still 'checked_in'
    and whose end_time is past a configured delay.
    """
    with current_app.app_context():
        logger = current_app.logger
        logger.info("Scheduler: Starting auto_checkout_overdue_bookings task...")

        booking_settings = BookingSettings.query.first()
        if not booking_settings:
            logger.warning("Scheduler: BookingSettings not found. Auto-checkout task will not run.")
            return

        enable_auto_checkout = booking_settings.enable_auto_checkout
        auto_checkout_delay_hours = booking_settings.auto_checkout_delay_hours

        logger.info(f"Scheduler: Auto-checkout enabled: {enable_auto_checkout}, Delay: {auto_checkout_delay_hours} hours.")

        if not enable_auto_checkout:
            logger.info("Scheduler: Auto-checkout feature is disabled in settings. Task will not run.")
            return

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=auto_checkout_delay_hours)

        try:
            overdue_bookings = Booking.query.filter(
                Booking.status == 'checked_in',
                Booking.checked_out_at.is_(None),
                Booking.end_time < cutoff_time
            ).all()
        except Exception as e_query:
            logger.error(f"Scheduler: Error querying for overdue bookings: {e_query}", exc_info=True)
            logger.info("Scheduler: Auto_checkout_overdue_bookings task finished due to query error.")
            return

        logger.info(f"Scheduler: Found {len(overdue_bookings)} overdue bookings to auto check-out.")

        for booking in overdue_bookings:
            logger.info(f"Scheduler: Processing auto check-out for booking ID {booking.id}...")
            resource_name_for_log = booking.resource_booked.name if booking.resource_booked else f"Unknown Resource (ID: {booking.resource_id})"
            user_name_for_log = booking.user_name if booking.user_name else "Unknown User"

            try:
                # Set actual checkout time based on configured delay
                actual_checkout_time = booking.end_time + timedelta(hours=auto_checkout_delay_hours)

                booking.checked_out_at = actual_checkout_time
                booking.status = 'completed'

                db.session.add(booking) # Add booking to session before commit
                db.session.commit() # Commit per booking to isolate failures

                add_audit_log(
                    action="AUTO_CHECKOUT_SUCCESS",
                    details=(
                        f"Booking ID {booking.id} for resource '{resource_name_for_log}' by user "
                        f"'{user_name_for_log}' automatically checked out at "
                        f"{actual_checkout_time.strftime('%Y-%m-%d %H:%M:%S UTC')}."
                    )
                )
                logger.info(f"Scheduler: Booking ID {booking.id} successfully auto checked-out in DB.")

                # Send Email Notification
                user = User.query.filter_by(username=booking.user_name).first()
                if user and user.email:
                    resource = Resource.query.get(booking.resource_id)
                    floor_map_location = "N/A"
                    floor_map_floor = "N/A"
                    resource_name_for_email = "Unknown Resource"

                    if resource:
                        resource_name_for_email = resource.name
                        if resource.floor_map_id:
                            floor_map = FloorMap.query.get(resource.floor_map_id)
                            if floor_map:
                                floor_map_location = floor_map.location or "N/A"
                                floor_map_floor = floor_map.floor or "N/A"

                    explanation = f"This booking was automatically checked out because it was still active more than {auto_checkout_delay_hours} hour(s) past its scheduled end time."

                    email_data = {
                        'user_name': user.username,
                        'booking_title': booking.title or "N/A",
                        'resource_name': resource_name_for_email,
                        'start_time': booking.start_time.strftime('%Y-%m-%d %H:%M'),
                        'end_time': booking.end_time.strftime('%Y-%m-%d %H:%M'),
                        'auto_checked_out_at_time': actual_checkout_time.strftime('%Y-%m-%d %H:%M:%S UTC'),
                        'location': floor_map_location,
                        'floor': floor_map_floor,
                        'explanation': explanation # Added explanation
                    }

                    subject = f"Booking Automatically Checked Out: {email_data.get('resource_name', 'N/A')} - {email_data.get('booking_title', 'N/A')}"

                    try:
                        html_body = render_template('email/booking_auto_checkout.html', **email_data)
                        text_body = render_template('email/booking_auto_checkout_text.html', **email_data)
                        send_email(to_address=user.email, subject=subject, body=text_body, html_body=html_body)
                        logger.info(f"Scheduler: Auto check-out email initiated for booking ID {booking.id} to {user.email}.")
                    except Exception as e_email:
                        logger.error(f"Scheduler: Error sending auto check-out email for booking {booking.id} to {user.email}: {e_email}", exc_info=True)
                else:
                    logger.warning(f"Scheduler: User {booking.user_name} not found or has no email. Skipping auto check-out email for booking {booking.id}.")

            except Exception as e:
                db.session.rollback()
                logger.error(f"Scheduler: Error processing auto check-out for booking ID {booking.id}: {e}", exc_info=True)
                add_audit_log(
                    action="AUTO_CHECKOUT_FAILED",
                    details=f"Scheduler: Failed to auto check-out booking ID {booking.id}. Error: {str(e)}"
                )

        logger.info("Scheduler: Auto_checkout_overdue_bookings task finished.")
