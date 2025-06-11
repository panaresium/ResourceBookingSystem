from datetime import datetime, timedelta, timezone
from flask import current_app, render_template
from extensions import db
from models import Booking, User, Resource, FloorMap, BookingSettings
from utils import add_audit_log, send_email, _get_map_configuration_data, _get_resource_configurations_data, _get_user_configurations_data
from azure_backup import backup_bookings_csv, create_full_backup
# Ensure current_app is available if not passed directly
# from flask import current_app # current_app is already imported by the other functions

# Constants for scheduler job configuration keys, can be used by app_factory
AUTO_CHECKOUT_INTERVAL_MINUTES_CONFIG_KEY = 'AUTO_CHECKOUT_INTERVAL_MINUTES'
DEFAULT_AUTO_CHECKOUT_INTERVAL_MINUTES = 15

def auto_checkout_overdue_bookings(app): # app is now a required argument
    """
    Automatically checks out bookings that are still 'checked_in'
    and whose end_time is past a configured delay.
    """
    with app.app_context():
        logger = app.logger # Logger obtained from the passed app, inside context
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

def run_scheduled_booking_csv_backup(app=None):
    """
    Scheduled task entry point to run the booking CSV backup.
    Uses the provided app context or gets it from current_app.
    """
    with app.app_context():
        logger = app.logger
        logger.info("Scheduler: Starting run_scheduled_booking_csv_backup task...")
        try:
            # The backup_bookings_csv function itself needs an app instance.
            # It will internally determine the range based on its schedule settings.
            # For a scheduled task, socketio_instance and task_id are typically None.
            success = backup_bookings_csv(
                app=app,
                socketio_instance=None,
                task_id=None,
                start_date_dt=None,
                end_date_dt=None,
                range_label="scheduled_auto"
            )
            if success:
                logger.info("Scheduler: run_scheduled_booking_csv_backup (backup_bookings_csv call) reported success.")
            else:
                logger.warning("Scheduler: run_scheduled_booking_csv_backup (backup_bookings_csv call) reported issues (returned False). See azure_backup logs for details.")
        except Exception as e:
            logger.error(f"Scheduler: Exception during run_scheduled_booking_csv_backup execution: {e}", exc_info=True)

        logger.info("Scheduler: run_scheduled_booking_csv_backup task finished.")

def cancel_unchecked_bookings(app):
    """
    Placeholder for the scheduled task to cancel bookings that were not checked in
    within the allowed window.
    """
    with app.app_context():
        logger = app.logger # Corrected: use app.logger after context
        logger.info("Scheduler: Task 'cancel_unchecked_bookings' called.")
        logger.warning("Scheduler: The logic for 'cancel_unchecked_bookings' is not yet fully implemented. This is a placeholder.")
        # TODO: Implement logic to query 'approved' bookings where:
    # - check_in_out is enabled (BookingSettings)
    # - current_time > booking.start_time + check_in_minutes_after (grace period)
    # - booking.checked_in_at is NULL
    # For each such booking:
    # - Update status to 'cancelled_by_system' (or a new status).
    # - Add an audit log.
    # - Optionally, send a notification to the user.
    logger.info("Scheduler: Task 'cancel_unchecked_bookings' finished (placeholder).")

def apply_scheduled_resource_status_changes(app=None):
    """
    Scheduled task to apply pending scheduled status changes to resources.
    """
    with app.app_context():
        logger = app.logger # Corrected: use app.logger after context
        logger.info("Scheduler: Starting apply_scheduled_resource_status_changes task...")
        now_utc = datetime.now(timezone.utc)

        try:
            resources_to_update = Resource.query.filter(
                Resource.scheduled_status.isnot(None),
                Resource.scheduled_status_at.isnot(None),
                Resource.scheduled_status_at <= now_utc
            ).all()

            if not resources_to_update:
                logger.info("Scheduler: No resource status changes to apply at this time.")
                logger.info("Scheduler: Task 'apply_scheduled_resource_status_changes' finished.")
                return

            logger.info(f"Scheduler: Found {len(resources_to_update)} resource(s) with pending status changes.")

            for resource in resources_to_update:
                old_status = resource.status
                new_status = resource.scheduled_status

                log_details = (
                    f"Resource ID {resource.id} ('{resource.name}') status changed from '{old_status}' "
                    f"to '{new_status}' based on schedule (scheduled at: {resource.scheduled_status_at})."
                )

                resource.status = new_status
                resource.scheduled_status = None
                resource.scheduled_status_at = None

                try:
                    db.session.add(resource)
                    db.session.commit()
                    add_audit_log(action="RESOURCE_SCHEDULED_STATUS_APPLIED", details=log_details)
                    logger.info(f"Scheduler: {log_details}")
                except Exception as e_commit:
                    db.session.rollback()
                    logger.error(f"Scheduler: Error updating resource ID {resource.id} status: {e_commit}", exc_info=True)
                    add_audit_log(action="RESOURCE_SCHEDULED_STATUS_FAILED", details=f"Failed to apply scheduled status for Resource ID {resource.id}. Error: {str(e_commit)}")

        except Exception as e_query:
            logger.error(f"Scheduler: Error querying for resources with scheduled status changes: {e_query}", exc_info=True)

        logger.info("Scheduler: Task 'apply_scheduled_resource_status_changes' finished.")

def run_scheduled_backup_job(app=None):
    """
    Scheduled task entry point to run a full system backup.
    """
    with app.app_context():
        logger = app.logger # Corrected: use app.logger after context
        logger.info("Scheduler: Starting run_scheduled_backup_job (full system backup)...")

        try:
            timestamp_str = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')

            # Gather configuration data
            logger.info("Scheduler: Gathering map configuration data for backup...")
            map_config_data = _get_map_configuration_data()

            logger.info("Scheduler: Gathering resource configurations data for backup...")
            resource_configs_data = _get_resource_configurations_data()

            logger.info("Scheduler: Gathering user and role configurations data for backup...")
            user_configs_data = _get_user_configurations_data()

            # Call the main backup function from azure_backup.py
            # SocketIO and task_id are None for a non-interactive scheduled job
            logger.info(f"Scheduler: Calling create_full_backup for timestamp {timestamp_str}...")
            success = create_full_backup(
                timestamp_str=timestamp_str,
                map_config_data=map_config_data,
                resource_configs_data=resource_configs_data,
                user_configs_data=user_configs_data,
                socketio_instance=None,
                task_id=None
            )

            if success:
                logger.info(f"Scheduler: Full system backup job completed successfully for timestamp {timestamp_str}.")
            else:
                logger.error(f"Scheduler: Full system backup job encountered errors for timestamp {timestamp_str}. Check azure_backup logs.")

        except Exception as e:
            logger.error(f"Scheduler: Critical error in run_scheduled_backup_job: {e}", exc_info=True)

        logger.info("Scheduler: Task 'run_scheduled_backup_job' finished.")
