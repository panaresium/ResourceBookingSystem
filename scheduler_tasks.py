from datetime import datetime, timedelta, timezone
from flask import current_app, render_template, url_for
from extensions import db
from models import Booking, User, Resource, FloorMap, BookingSettings
from utils import add_audit_log, send_email, _get_map_configuration_data, _get_resource_configurations_data, _get_user_configurations_data, get_current_effective_time
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
        logger = app.logger
        logger.info("Scheduler: Starting auto_checkout_overdue_bookings task...")

        booking_settings = BookingSettings.query.first()
        if not booking_settings:
            logger.warning("Scheduler: BookingSettings not found. Auto-checkout task will not run.")
            return

        enable_auto_checkout = booking_settings.enable_auto_checkout
        auto_checkout_delay_minutes = booking_settings.auto_checkout_delay_minutes # Changed
        current_offset_hours = booking_settings.global_time_offset_hours if hasattr(booking_settings, 'global_time_offset_hours') and booking_settings.global_time_offset_hours is not None else 0

        logger.info(f"Scheduler: Auto-checkout enabled: {enable_auto_checkout}, Delay: {auto_checkout_delay_minutes} minutes, Offset: {current_offset_hours} hours.") # Changed

        if not enable_auto_checkout:
            logger.info("Scheduler: Auto-checkout feature is disabled in settings. Task will not run.")
            return

        effective_now_aware = get_current_effective_time() # Aware, in venue's effective timezone
        effective_now_local_naive = effective_now_aware.replace(tzinfo=None) # Naive representation of venue's current time

        # Cutoff time in naive venue local time
        cutoff_time_local_naive = effective_now_local_naive - timedelta(minutes=auto_checkout_delay_minutes) # Changed

        try:
            overdue_bookings = Booking.query.filter(
                Booking.status == 'checked_in',
                Booking.checked_out_at.is_(None), # This is naive local
                Booking.end_time < cutoff_time_local_naive # Booking.end_time is naive local
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
                # Set actual checkout time based on configured delay; this will be naive local
                actual_checkout_time_local_naive = booking.end_time + timedelta(minutes=auto_checkout_delay_minutes) # Changed

                booking.checked_out_at = actual_checkout_time_local_naive # Store naive local
                booking.status = 'completed'

                db.session.add(booking)
                db.session.commit()

                # For logging/display, convert to UTC
                actual_checkout_time_utc = (actual_checkout_time_local_naive - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc)
                add_audit_log(
                    action="AUTO_CHECKOUT_SUCCESS",
                    details=(
                        f"Booking ID {booking.id} for resource '{resource_name_for_log}' by user "
                        f"'{user_name_for_log}' automatically checked out at "
                        f"{actual_checkout_time_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}."
                    )
                )
                logger.info(f"Scheduler: Booking ID {booking.id} successfully auto checked-out in DB (local time: {actual_checkout_time_local_naive}).")

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

                    explanation = f"This booking was automatically checked out because it was still active more than {auto_checkout_delay_minutes} minute(s) past its scheduled end time." # Changed

                    # Times for email: start_time and end_time are naive local. actual_checkout_time_local_naive is also naive local.
                    # Display them as such, or convert to a specific display timezone if needed.
                    # For consistency with previous UTC display in emails for checkout times:
                    auto_checkout_at_utc_display = (actual_checkout_time_local_naive - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc)

                    email_data = {
                        'user_name': user.username,
                        'booking_title': booking.title or "N/A",
                        'resource_name': resource_name_for_email,
                        'start_time': booking.start_time.strftime('%Y-%m-%d %H:%M'), # Naive local
                        'end_time': booking.end_time.strftime('%Y-%m-%d %H:%M'),     # Naive local
                        'auto_checked_out_at_time': auto_checkout_at_utc_display.strftime('%Y-%m-%d %H:%M:%S UTC'),
                        'location': floor_map_location,
                        'floor': floor_map_floor,
                        'explanation': explanation
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
        logger = app.logger
        logger.info("Scheduler: Starting apply_scheduled_resource_status_changes task...")

        booking_settings_for_offset = BookingSettings.query.first()
        current_offset_hours = 0
        if booking_settings_for_offset and hasattr(booking_settings_for_offset, 'global_time_offset_hours') and booking_settings_for_offset.global_time_offset_hours is not None:
            current_offset_hours = booking_settings_for_offset.global_time_offset_hours

        effective_now_aware = get_current_effective_time() # Aware, in venue's effective timezone
        effective_now_local_naive = effective_now_aware.replace(tzinfo=None) # Naive representation of venue's current time

        try:
            resources_to_update = []
            all_sched_resources = Resource.query.filter(
                Resource.scheduled_status.isnot(None),
                Resource.scheduled_status_at.isnot(None)
            ).all()

            for res in all_sched_resources:
                if res.scheduled_status_at: # Should always be true due to query filter
                    # Convert naive UTC scheduled_status_at to naive local for comparison
                    scheduled_at_utc_aware = res.scheduled_status_at.replace(tzinfo=timezone.utc)
                    scheduled_at_local_aware = scheduled_at_utc_aware + timedelta(hours=current_offset_hours)
                    scheduled_at_local_naive = scheduled_at_local_aware.replace(tzinfo=None)

                    if scheduled_at_local_naive <= effective_now_local_naive:
                        resources_to_update.append(res)

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

def auto_release_unclaimed_bookings(app):
    """
    Automatically cancels bookings that are 'approved' but not checked in
    within a configured number of minutes after their start time.
    """
    with app.app_context():
        logger = app.logger
        logger.info("Scheduler: Starting auto_release_unclaimed_bookings task...")

        booking_settings = BookingSettings.query.first()
        if not booking_settings:
            logger.warning("Scheduler: BookingSettings not found. Auto-release task will not run.")
            return

        enable_check_in_out = booking_settings.enable_check_in_out
        release_minutes = booking_settings.auto_release_if_not_checked_in_minutes
        current_offset_hours = booking_settings.global_time_offset_hours if hasattr(booking_settings, 'global_time_offset_hours') and booking_settings.global_time_offset_hours is not None else 0

        logger.info(f"Scheduler: Auto-release settings: Check-in/out enabled: {enable_check_in_out}, Release minutes: {release_minutes}, Offset: {current_offset_hours} hours.")

        if not enable_check_in_out:
            logger.info("Scheduler: Check-in/out feature is disabled in settings. Auto-release task will not run.")
            return

        if not release_minutes or release_minutes <= 0:
            logger.info("Scheduler: Auto-release minutes not configured or is zero/negative. Auto-release task will not run.")
            return

        effective_now_aware = get_current_effective_time()  # Aware, in venue's effective timezone
        effective_now_local_naive = effective_now_aware.replace(tzinfo=None)  # Naive representation of venue's current time

        try:
            # Query for bookings that are 'approved' and have not been checked in
            unclaimed_bookings = Booking.query.filter(
                Booking.status == 'approved',
                Booking.checked_in_at.is_(None)
            ).all()
        except Exception as e_query:
            logger.error(f"Scheduler: Error querying for unclaimed bookings: {e_query}", exc_info=True)
            logger.info("Scheduler: auto_release_unclaimed_bookings task finished due to query error.")
            return

        logger.info(f"Scheduler: Found {len(unclaimed_bookings)} unclaimed 'approved' bookings to evaluate for auto-release.")

        for booking in unclaimed_bookings:
            resource_name_for_log = booking.resource_booked.name if booking.resource_booked else f"Unknown Resource (ID: {booking.resource_id})"
            user_name_for_log = booking.user_name if booking.user_name else "Unknown User"

            try:
                # booking.start_time is naive local
                start_time_local_naive = booking.start_time
                deadline_local_naive = start_time_local_naive + timedelta(minutes=release_minutes)

                if effective_now_local_naive > deadline_local_naive:
                    logger.info(f"Scheduler: Booking ID {booking.id} for '{resource_name_for_log}' by '{user_name_for_log}' is past its check-in deadline ({deadline_local_naive}). Attempting to auto-release.")

                    original_status = booking.status
                    booking.status = 'system_cancelled_no_checkin'
                    # Optionally, set a specific field for release reason or time if model has one
                    # booking.cancellation_reason = "Auto-released due to no check-in"
                    # booking.cancelled_at = effective_now_local_naive # Or use UTC time

                    db.session.add(booking)
                    db.session.commit()

                    # Convert deadline to UTC for consistent logging if desired
                    deadline_utc_aware = (deadline_local_naive - timedelta(hours=current_offset_hours)).replace(tzinfo=timezone.utc)

                    audit_log_details = (
                        f"Booking ID {booking.id} for resource '{resource_name_for_log}' by user '{user_name_for_log}' "
                        f"(original status: {original_status}) auto-released. "
                        f"Check-in deadline (local): {deadline_local_naive.strftime('%Y-%m-%d %H:%M:%S')}, "
                        f"Deadline (UTC): {deadline_utc_aware.strftime('%Y-%m-%d %H:%M:%S UTC')}."
                    )
                    add_audit_log(action="AUTO_RELEASE_NO_CHECKIN", details=audit_log_details)
                    logger.info(f"Scheduler: Booking ID {booking.id} status changed to '{booking.status}'. {audit_log_details}")

                    # Send Email Notification (similar to auto_checkout_overdue_bookings)
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

                        explanation = (
                            f"This booking was automatically cancelled because it was not checked-in "
                            f"within {release_minutes} minutes of its scheduled start time."
                        )

                        # Times for email: start_time and end_time are naive local.
                        # deadline_local_naive is also naive local.
                        # Display them as such, or convert to a specific display timezone if needed.
                        # For consistency, let's display deadline in local time.
                        email_data = {
                            'user_name': user.username,
                            'booking_title': booking.title or "N/A",
                            'resource_name': resource_name_for_email,
                            'start_time_local': booking.start_time.strftime('%Y-%m-%d %H:%M'), # Naive local
                            'end_time_local': booking.end_time.strftime('%Y-%m-%d %H:%M'),     # Naive local
                            'check_in_deadline_local': deadline_local_naive.strftime('%Y-%m-%d %H:%M:%S'),
                            'location': floor_map_location,
                            'floor': floor_map_floor,
                            'explanation': explanation
                        }

                        subject = f"Booking Automatically Cancelled (No Check-in): {email_data.get('resource_name', 'N/A')} - {email_data.get('booking_title', 'N/A')}"

                        try:
                            # Ensure email templates exist for this scenario
                            html_body = render_template('email/booking_auto_cancelled_no_checkin.html', **email_data)
                            text_body = render_template('email/booking_auto_cancelled_no_checkin_text.html', **email_data)
                            send_email(to_address=user.email, subject=subject, body=text_body, html_body=html_body)
                            logger.info(f"Scheduler: Auto-release (no check-in) email initiated for booking ID {booking.id} to {user.email}.")
                        except Exception as e_email:
                            # Check if it's a Jinja template not found error
                            if "TemplateNotFound" in str(type(e_email)):
                                logger.warning(f"Scheduler: Email template for auto-release not found. Skipping email for booking {booking.id}. Error: {e_email}")
                            else:
                                logger.error(f"Scheduler: Error sending auto-release email for booking {booking.id} to {user.email}: {e_email}", exc_info=True)
                    elif booking.user_name: # User exists but no email, or user object not found
                        logger.warning(f"Scheduler: User {booking.user_name} not found or has no email. Skipping auto-release email for booking {booking.id}.")
                    else: # booking.user_name is None or empty
                         logger.warning(f"Scheduler: Booking ID {booking.id} has no associated user_name. Skipping auto-release email.")

                else:
                    logger.debug(f"Scheduler: Booking ID {booking.id} for '{resource_name_for_log}' by '{user_name_for_log}' is not yet past its check-in deadline ({deadline_local_naive}). Effective local time: {effective_now_local_naive}")

            except Exception as e_booking_process:
                db.session.rollback()
                logger.error(f"Scheduler: Error processing auto-release for booking ID {booking.id}: {e_booking_process}", exc_info=True)
                add_audit_log(
                    action="AUTO_RELEASE_NO_CHECKIN_FAILED",
                    details=f"Scheduler: Failed to auto-release booking ID {booking.id} for '{resource_name_for_log}'. Error: {str(e_booking_process)}"
                )

        logger.info("Scheduler: auto_release_unclaimed_bookings task finished.")


def send_checkin_reminders(app):
    with app.app_context():
        logger = app.logger
        logger.info("Scheduler: Starting send_checkin_reminders task...")
        try:
            booking_settings = BookingSettings.query.first()
            if not booking_settings:
                logger.warning("Scheduler: BookingSettings not found. Check-in reminder task will not run.")
                return

            if not booking_settings.enable_check_in_out:
                logger.info("Scheduler: Check-in/out feature is disabled. Check-in reminder task will not run.")
                return

            # Get global_time_offset_hours from settings for local time conversions
            current_offset_hours = booking_settings.global_time_offset_hours if hasattr(booking_settings, 'global_time_offset_hours') and booking_settings.global_time_offset_hours is not None else 0

            # Effective current time in venue's local timezone (naive)
            effective_now_aware = get_current_effective_time() # Aware, in venue's effective timezone
            effective_now_local_naive = effective_now_aware.replace(tzinfo=None) # Naive representation of venue's current time

            logger.info(f"Scheduler: Effective local time for processing: {effective_now_local_naive.strftime('%Y-%m-%d %H:%M:%S')}")

            # Fetch all approved bookings where checked_in_at is None
            potential_bookings_local_query = Booking.query.filter(
                Booking.status == 'approved',
                Booking.checked_in_at.is_(None)
            ).all()

            logger.info(f"Scheduler: Found {len(potential_bookings_local_query)} potential bookings (approved, not checked-in) for reminder/cancellation processing.")

            sent_reminders_count = 0
            cancelled_bookings_count = 0

            for booking in potential_bookings_local_query:
                user = User.query.filter_by(username=booking.user_name).first()
                resource = db.session.get(Resource, booking.resource_id)

                if not user:
                    logger.warning(f"Scheduler: Could not find user '{booking.user_name}' for booking ID {booking.id}. Skipping processing for this booking.")
                    continue
                if not resource:
                    logger.warning(f"Scheduler: Could not find resource ID {booking.resource_id} for booking ID {booking.id}. Skipping processing for this booking.")
                    continue

                # Booking times are naive local
                booking_start_local_naive = booking.start_time

                # Get check-in window parameters from BookingSettings
                # Ensure these settings exist and are valid
                check_in_minutes_before = booking_settings.check_in_minutes_before
                check_in_minutes_after = booking_settings.check_in_minutes_after
                reminder_minutes_before_start = booking_settings.checkin_reminder_minutes_before

                if reminder_minutes_before_start is None or reminder_minutes_before_start <= 0:
                    logger.info(f"Scheduler: Check-in reminder minutes not configured or invalid for booking ID {booking.id}. Reminder logic will be skipped.")
                    # Proceed to cancellation logic if applicable

                if check_in_minutes_before is None or check_in_minutes_after is None:
                    logger.warning(f"Scheduler: Check-in window (before/after minutes) not fully configured in BookingSettings. Skipping reminder/cancellation for booking ID {booking.id}.")
                    continue

                # Calculate reminder send target and check-in deadline
                # Reminder target: X minutes before booking start_time
                reminder_send_target_local_naive = booking_start_local_naive - timedelta(minutes=reminder_minutes_before_start if reminder_minutes_before_start else 0)
                # Check-in deadline: Y minutes after booking start_time
                check_in_deadline_local_naive = booking_start_local_naive + timedelta(minutes=check_in_minutes_after)

                # Reminder Logic
                if booking.checkin_reminder_sent_at is None and \
                   (reminder_minutes_before_start and reminder_minutes_before_start > 0) and \
                   effective_now_local_naive >= reminder_send_target_local_naive and \
                   effective_now_local_naive < booking_start_local_naive and \
                   effective_now_local_naive <= check_in_deadline_local_naive: # Ensure reminder is not sent after deadline

                    if not user.email:
                        logger.warning(f"Scheduler: User {user.username} has no email address. Skipping reminder for booking ID {booking.id}.")
                    else:
                        try:
                            logger.info(f"Scheduler: [send_checkin_reminders] Attempting to generate checkin_url. SERVER_NAME='{current_app.config.get('SERVER_NAME')}', APPLICATION_ROOT='{current_app.config.get('APPLICATION_ROOT')}', PREFERRED_URL_SCHEME='{current_app.config.get('PREFERRED_URL_SCHEME')}'")
                            checkin_url = url_for('ui.check_in_at_resource', resource_id=booking.resource_id, _external=True)
                            booking_start_str = booking_start_local_naive.strftime("%Y-%m-%d %H:%M:%S") + " (Venue Local Time)"
                            email_subject = f"Check-in Reminder: {booking.title or resource.name}"
                            app_name = current_app.config.get('APP_NAME', 'Smart Resource Booking System')

                            html_body = render_template('email/checkin_reminder_email.html',
                                                        booking_title=booking.title or "Booking",
                                                        resource_name=resource.name,
                                                        booking_start_time=booking_start_str,
                                                        checkin_url=checkin_url,
                                                        app_name=app_name,
                                                        user_name=user.username)
                            text_body = render_template('email/checkin_reminder_email.txt',
                                                        booking_title=booking.title or "Booking",
                                                        resource_name=resource.name,
                                                        booking_start_time=booking_start_str,
                                                        checkin_url=checkin_url,
                                                        app_name=app_name,
                                                        user_name=user.username)
                            send_email(
                                to_address=user.email,
                                subject=email_subject,
                                text_body=text_body,
                                html_body=html_body
                            )
                            booking.checkin_reminder_sent_at = datetime.now(timezone.utc) # Mark as sent with current UTC time
                            db.session.add(booking)
                            db.session.commit()
                            sent_reminders_count += 1
                            logger.info(f"Scheduler: Sent check-in reminder for booking ID {booking.id} to {user.email}.")
                        except Exception as e_send_reminder:
                            db.session.rollback()
                            logger.error(f"Scheduler: Error sending reminder for booking ID {booking.id}: {e_send_reminder}", exc_info=True)

                # Cancellation Logic
                # Ensure booking status is still 'approved' before cancelling
                elif effective_now_local_naive > check_in_deadline_local_naive and booking.status == 'approved':
                    logger.info(f"Scheduler: Booking ID {booking.id} for resource '{resource.name}' by user '{user.username}' is past its check-in deadline ({check_in_deadline_local_naive}). Attempting to auto-cancel.")
                    original_status = booking.status
                    booking.status = 'system_cancelled_no_checkin'

                    try:
                        db.session.add(booking)
                        # Audit log before commit, in case commit fails
                        audit_log_details = (
                            f"Booking ID {booking.id} for resource '{resource.name}' by user "
                            f"'{user.username}' (original status: {original_status}) auto-cancelled due to no check-in. "
                            f"Check-in deadline (local): {check_in_deadline_local_naive.strftime('%Y-%m-%d %H:%M:%S')}."
                        )
                        add_audit_log(action="AUTO_CANCEL_NO_CHECKIN", details=audit_log_details)
                        db.session.commit()
                        cancelled_bookings_count += 1
                        logger.info(f"Scheduler: Booking ID {booking.id} status changed to '{booking.status}'. {audit_log_details}")

                        # Send Cancellation Email
                        if user.email:
                            floor_map_location = "N/A"
                            floor_map_floor = "N/A"
                            if resource.floor_map_id:
                                floor_map = FloorMap.query.get(resource.floor_map_id)
                                if floor_map:
                                    floor_map_location = floor_map.location or "N/A"
                                    floor_map_floor = floor_map.floor or "N/A"

                            explanation = (
                                f"This booking was automatically cancelled because it was not checked-in "
                                f"within {check_in_minutes_after} minutes of its scheduled start time (by {check_in_deadline_local_naive.strftime('%Y-%m-%d %H:%M:%S')})."
                            )
                            email_data = {
                                'user_name': user.username,
                                'booking_title': booking.title or "N/A",
                                'resource_name': resource.name,
                                'start_time_local': booking_start_local_naive.strftime('%Y-%m-%d %H:%M'),
                                'end_time_local': booking.end_time.strftime('%Y-%m-%d %H:%M'), # Assuming booking.end_time is naive local
                                'check_in_deadline_local': check_in_deadline_local_naive.strftime('%Y-%m-%d %H:%M:%S'),
                                'location': floor_map_location,
                                'floor': floor_map_floor,
                                'explanation': explanation
                            }
                            subject = f"Booking Automatically Cancelled (No Check-in): {email_data.get('resource_name', 'N/A')} - {email_data.get('booking_title', 'N/A')}"

                            try:
                                html_body_cancel = render_template('email/booking_auto_cancelled_no_checkin.html', **email_data)
                                text_body_cancel = render_template('email/booking_auto_cancelled_no_checkin_text.html', **email_data)
                                send_email(to_address=user.email, subject=subject, body=text_body_cancel, html_body=html_body_cancel)
                                logger.info(f"Scheduler: Auto-cancellation (no check-in) email initiated for booking ID {booking.id} to {user.email}.")
                            except Exception as e_send_cancel_email:
                                if "TemplateNotFound" in str(type(e_send_cancel_email)):
                                    logger.warning(f"Scheduler: Email template for auto-cancellation not found. Skipping email for booking {booking.id}. Error: {e_send_cancel_email}")
                                else:
                                    logger.error(f"Scheduler: Error sending auto-cancellation email for booking {booking.id} to {user.email}: {e_send_cancel_email}", exc_info=True)
                        else:
                            logger.warning(f"Scheduler: User {user.username} has no email. Skipping auto-cancellation email for booking ID {booking.id}.")
                    except Exception as e_cancel_commit:
                        db.session.rollback()
                        logger.error(f"Scheduler: Error committing cancellation for booking ID {booking.id}: {e_cancel_commit}", exc_info=True)
                        add_audit_log(action="AUTO_CANCEL_NO_CHECKIN_FAILED", details=f"Failed to auto-cancel booking ID {booking.id}. Error: {str(e_cancel_commit)}")
                # else: booking is not yet in reminder window and not past cancellation deadline
                    # logger.debug(f"Booking ID {booking.id} not yet in reminder window or past cancellation deadline.")

            if sent_reminders_count > 0:
                logger.info(f"Scheduler: Successfully sent {sent_reminders_count} check-in reminders.")
            if cancelled_bookings_count > 0:
                logger.info(f"Scheduler: Successfully auto-cancelled {cancelled_bookings_count} bookings due to no check-in.")

            if sent_reminders_count == 0 and cancelled_bookings_count == 0:
                logger.info("Scheduler: No reminders sent and no bookings cancelled in this run.")

        except Exception as e_task:
            # Attempt to rollback any db changes if an unexpected error occurs at task level
            try:
                db.session.rollback()
                logger.info("Scheduler: Rolled back database session due to error in main task block.")
            except Exception as e_rollback:
                logger.error(f"Scheduler: Critical error during task-level rollback: {e_rollback}", exc_info=True)
            logger.error(f"Scheduler: Error in send_checkin_reminders task's main try block: {e_task}", exc_info=True)
        finally:
            logger.info("Scheduler: Task 'send_checkin_reminders' finished.")
