import logging
from datetime import datetime, timedelta, timezone, time
from flask import current_app

# Assuming db is initialized in extensions.py
from extensions import db
# Assuming models are defined in models.py
from models import Booking, Resource, User # Added User
# Assuming utility functions are in utils.py
from utils import load_scheduler_settings, _get_map_configuration_data, add_audit_log, send_email, send_teams_notification # Added send_email, send_teams_notification

# Conditional import for azure_backup
try:
    from azure_backup import create_full_backup, backup_bookings_csv
except ImportError:
    create_full_backup = None
    backup_bookings_csv = None # Ensure it's defined even if import fails

def cancel_unchecked_bookings(app):
    """
    Cancels bookings that were not checked in within the grace period.
    """
    with app.app_context():
        logger = app.logger
        grace_minutes = app.config.get('CHECK_IN_GRACE_MINUTES', 15)
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=grace_minutes)

        stale_bookings = Booking.query.filter(
            Booking.checked_in_at.is_(None),
            Booking.start_time < cutoff_time,
            Booking.status == 'approved'  # Only target 'approved' bookings
        ).all()

        if stale_bookings:
            cancelled_booking_details = []  # Store details for notification
            for booking in stale_bookings:
                original_status = booking.status
                # Store necessary info for notification *before* booking object might become invalid or status changes
                # Ensure resource_booked is accessed while session is active and booking object is valid
                resource_name = "Unknown Resource"
                if booking.resource_booked:
                    resource_name = booking.resource_booked.name

                cancelled_booking_details.append({
                    'user_name': booking.user_name,
                    'resource_name': resource_name,
                    'start_time_str': booking.start_time.strftime('%Y-%m-%d %H:%M UTC'),
                    'booking_id': booking.id,
                    'resource_id': booking.resource_id,
                    'original_status': original_status # Keep original status for audit log
                })
                booking.status = 'cancelled'  # Set status to cancelled
                # Audit log will be added after successful commit to reflect actual change
                # However, if audit log needs to be per-booking before commit, it can be here,
                # but the provided snippet structure defers it. For this change, let's assume
                # a single audit log post-commit or individual logs per notification.
                # The original code logged per booking before commit, let's keep that for the audit part.
                add_audit_log(
                    action="AUTO_CANCEL_NO_CHECK_IN_ATTEMPT", # Indicate attempt before commit
                    details=f"Attempting to auto-cancel Booking ID {booking.id} for resource {resource_name} (User: {booking.user_name}). Original status: {original_status}.",
                    username="System"
                )

            try:
                db.session.commit()
                logger.info(f"Successfully auto-cancelled {len(stale_bookings)} unchecked bookings in DB.")

                # Now, send notifications and add final audit logs
                for details in cancelled_booking_details:
                    add_audit_log( # Log successful cancellation after commit
                        action="AUTO_CANCEL_NO_CHECK_IN_SUCCESS",
                        details=f"Booking ID {details['booking_id']} for resource {details['resource_name']} (User: {details['user_name']}) auto-cancelled. Original status: {details['original_status']}.",
                        username="System"
                    )

                    user = User.query.filter_by(username=details['user_name']).first()
                    if user and user.email:
                        subject = f"Booking Auto-Cancelled: {details['resource_name']}"
                        body_text = (
                            f"Your booking for the resource '{details['resource_name']}' "
                            f"scheduled to start at {details['start_time_str']} "
                            f"has been automatically cancelled due to no check-in within the grace period."
                        )

                        # Check if mail is configured before trying to send
                        if current_app.extensions.get('mail') and hasattr(current_app.extensions['mail'], 'send'):
                            try:
                                send_email(user.email, subject, body_text)
                                logger.info(f"Sent auto-cancellation email to {user.email} for booking ID {details['booking_id']}")
                            except Exception as mail_e:
                                logger.error(f"Failed to send auto-cancellation email to {user.email} for booking {details['booking_id']}: {mail_e}")

                        # Check if Teams webhook is configured
                        if current_app.config.get('TEAMS_WEBHOOK_URL'):
                            try:
                                send_teams_notification(user.email, subject, body_text) # user.email might be used as a lookup
                                logger.info(f"Sent auto-cancellation Teams notification for {user.email} for booking ID {details['booking_id']}")
                            except Exception as teams_e:
                                logger.error(f"Failed to send auto-cancellation Teams notification for {user.email} for booking {details['booking_id']}: {teams_e}")
                    else:
                        logger.warning(f"Could not find user or email for {details['user_name']} to notify about auto-cancelled booking ID {details['booking_id']}.")
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error committing auto-cancellation of bookings or sending notifications: {e}", exc_info=True)
                # Add a general audit log for the failure of the batch
                add_audit_log(action="AUTO_CANCEL_BATCH_FAILED", details=f"Failed to commit auto-cancellations or send notifications. Error: {str(e)}", username="System")
        else:
            logger.info("No stale bookings to auto-cancel at this time.")

def apply_scheduled_resource_status_changes(app):
    """
    Applies scheduled status changes to resources.
    """
    with app.app_context():
        logger = app.logger
        now = datetime.now(timezone.utc)
        resources_to_update = Resource.query.filter(
            Resource.scheduled_status_at.isnot(None),
            Resource.scheduled_status_at <= now,
            Resource.scheduled_status.isnot(None),
            Resource.scheduled_status != ""
        ).all()

        if not resources_to_update:
            logger.info("No resource status changes to apply at this time.")
            return

        for resource in resources_to_update:
            old_status = resource.status
            new_status = resource.scheduled_status

            logger.info(
                f"Applying scheduled status change for resource {resource.id} ('{resource.name}') "
                f"from '{old_status}' to '{new_status}' scheduled for {resource.scheduled_status_at.isoformat()}"
            )

            resource.status = new_status
            if new_status == 'published' and old_status != 'published':
                resource.published_at = resource.scheduled_status_at

            add_audit_log(
                action="SYSTEM_APPLY_SCHEDULED_STATUS",
                details=(
                    f"Resource {resource.id} ('{resource.name}') status automatically changed "
                    f"from '{old_status}' to '{new_status}' as scheduled for {resource.scheduled_status_at.isoformat()}."
                ),
                username="System"
            )

            resource.scheduled_status = None
            resource.scheduled_status_at = None

        try:
            db.session.commit()
            logger.info(f"Successfully applied scheduled status changes for {len(resources_to_update)} resources.")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error committing scheduled status changes: {e}", exc_info=True)

def run_scheduled_backup_job(app):
    """
    Checks the backup schedule and runs a full backup if due.
    """
    with app.app_context():
        logger = app.logger
        logger.info("run_scheduled_backup_job: Checking backup schedule (from UI settings)...")
        try:
            settings = load_scheduler_settings()
            full_backup_schedule = settings.get('full_backup', {}) # Default to empty dict if key missing

            if not full_backup_schedule.get('is_enabled'):
                logger.info("run_scheduled_backup_job: Full backups are disabled via UI settings. Skipping.")
                return

            now_utc = datetime.now(timezone.utc)
            current_time_utc = now_utc.time()
            # Use default from new structure if key missing
            scheduled_time_str = full_backup_schedule.get('time_of_day', "02:00")
            try:
                scheduled_time_obj = datetime.strptime(scheduled_time_str, '%H:%M').time()
            except ValueError:
                logger.error(f"run_scheduled_backup_job: Invalid time_of_day '{scheduled_time_str}' in UI settings. Using 02:00.")
                scheduled_time_obj = time(2,0)

            backup_due = False
            # Use default from new structure if key missing
            schedule_type = full_backup_schedule.get('schedule_type', 'daily')

            # Check if current time matches scheduled time (hour and minute)
            # Note: APScheduler should ideally trigger the job at the correct time,
            # so this check is a secondary confirmation.
            if current_time_utc.hour == scheduled_time_obj.hour and current_time_utc.minute == scheduled_time_obj.minute:
                if schedule_type == 'daily':
                    backup_due = True
                elif schedule_type == 'weekly':
                    day_of_week_setting = full_backup_schedule.get('day_of_week') # This is an int (0-6)
                    if day_of_week_setting is not None and now_utc.weekday() == day_of_week_setting:
                        backup_due = True

            if not backup_due:
                # This part of the logic might be less relevant if APScheduler is configured precisely.
                # However, it's kept for consistency with the original logic.
                # A more robust check might involve seeing if the *last run time* for this job
                # was more than 23 hours ago (for daily) or 6 days ago (for weekly at specific time).
                # For now, stick to time comparison.
                logger.debug(f"run_scheduled_backup_job: Backup not currently due based on time/day check. Current UTC: {current_time_utc.strftime('%H:%M')}, Scheduled UTC: {scheduled_time_str}, Type: {schedule_type}, Today's weekday: {now_utc.weekday()}")
                # APScheduler should handle the precise triggering, so if this job runs, it's likely due.
                # Forcing backup_due = True if the job is triggered by a precisely timed scheduler.
                # However, to respect the 'time_of_day' and 'day_of_week' from UI, the check is maintained.
                # If this job is run by a simple interval (e.g. every hour), then this time check is critical.


            if backup_due: # If the above logic determined it's time
                logger.info(f"run_scheduled_backup_job: Backup is due (UI settings) at {scheduled_time_str} UTC. Starting backup...")
                timestamp_str = now_utc.strftime('%Y%m%d_%H%M%S')
                map_config = _get_map_configuration_data() # This uses app_context

                if not create_full_backup:
                    logger.error("run_scheduled_backup_job: create_full_backup function not available/imported.")
                    return

                success = create_full_backup(timestamp_str, map_config_data=map_config, socketio_instance=None, task_id=None)

                if success:
                    logger.info(f"run_scheduled_backup_job: Scheduled backup (UI settings) completed successfully. Timestamp: {timestamp_str}")
                    add_audit_log(action="SCHEDULED_BACKUP_SUCCESS_UI", details=f"Scheduled backup successful (UI settings). Timestamp: {timestamp_str}", username="System")
                else:
                    logger.error(f"run_scheduled_backup_job: Scheduled backup (UI settings) failed. Timestamp attempted: {timestamp_str}")
                    add_audit_log(action="SCHEDULED_BACKUP_FAILED_UI", details=f"Scheduled backup failed (UI settings). Timestamp attempted: {timestamp_str}", username="System")
            # else:
                # logger.debug already covered above
                # logger.debug(f"run_scheduled_backup_job: Backup not currently due. Current: {current_time_utc.strftime('%H:%M')}, Scheduled: {scheduled_time_str}, Type: {schedule_type}")


        except Exception as e:
            logger.exception("run_scheduled_backup_job: Error during scheduled backup job execution (UI settings).")
            add_audit_log(action="SCHEDULED_BACKUP_ERROR_UI", details=f"Exception: {str(e)}", username="System")


def run_scheduled_booking_csv_backup(app):
    """
    Runs the scheduled CSV backup for bookings.
    """
    with app.app_context():
        logger = app.logger
        logger.info("run_scheduled_booking_csv_backup: Checking CSV backup schedule (from UI settings)...")
        try:
            if not backup_bookings_csv:
                logger.error("run_scheduled_booking_csv_backup: backup_bookings_csv function not available/imported. Cannot proceed.")
                return

            settings = load_scheduler_settings()
            # Use default from new structure if key missing
            csv_backup_schedule = settings.get('booking_csv_backup', {})

            if not csv_backup_schedule.get('is_enabled'):
                logger.info("run_scheduled_booking_csv_backup: Booking CSV backups are disabled via UI settings. Skipping.")
                return

            # The job for CSV backup is expected to be run by APScheduler at the specified interval.
            # So, if this function is called, it means it's time to run the backup.
            # The 'interval_minutes' from csv_backup_schedule is used by APScheduler setup, not directly here.

            # Use default from new structure if key missing
            range_setting = csv_backup_schedule.get('range', 'all')
            # range_label will be the same as range_setting for filename and logging
            range_label = range_setting

            start_date_dt = None
            end_date_dt = None

            if range_setting != 'all':
                utcnow = datetime.now(timezone.utc)
                end_date_dt = datetime(utcnow.year, utcnow.month, utcnow.day, tzinfo=timezone.utc) + timedelta(days=1)

                if range_setting == "1day":
                    start_date_dt = end_date_dt - timedelta(days=1)
                elif range_setting == "3days":
                    start_date_dt = end_date_dt - timedelta(days=3)
                elif range_setting == "7days":
                    start_date_dt = end_date_dt - timedelta(days=7)
                # Add other range options if they become available in UI settings
                else:
                    logger.warning(f"run_scheduled_booking_csv_backup: Unknown range '{range_setting}' in UI settings. Defaulting to 'all'.")
                    range_label = 'all' # Fallback range_label for filename consistency

            task_id_str = f"scheduled_booking_csv_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            logger.info(f"run_scheduled_booking_csv_backup: Running scheduled booking CSV backup (UI settings) for range: {range_label}, Start: {start_date_dt}, End: {end_date_dt}. Task ID: {task_id_str}")

            success = backup_bookings_csv(
                app=app, # app_context is already active
                socketio_instance=None,
                task_id=task_id_str,
                start_date_dt=start_date_dt,
                end_date_dt=end_date_dt,
                range_label=range_label
            )

            if success:
                logger.info(f"run_scheduled_booking_csv_backup: Scheduled booking CSV backup (UI settings, range: {range_label}) completed successfully.")
                add_audit_log(action="SCHEDULED_BOOKING_CSV_BACKUP_SUCCESS_UI", details=f"Scheduled booking CSV backup (UI settings, range: {range_label}) successful.", username="System")
            else:
                logger.error(f"run_scheduled_booking_csv_backup: Scheduled booking CSV backup (UI settings, range: {range_label}) failed.")
                add_audit_log(action="SCHEDULED_BOOKING_CSV_BACKUP_FAILED_UI", details=f"Scheduled booking CSV backup (UI settings, range: {range_label}) failed.", username="System")
        except Exception as e:
            logger.exception("run_scheduled_booking_csv_backup: Error during scheduled booking CSV backup execution (UI settings).")
            add_audit_log(action="SCHEDULED_BOOKING_CSV_BACKUP_ERROR_UI", details=f"Exception: {str(e)}", username="System")
