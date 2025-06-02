import logging
from datetime import datetime, timedelta, timezone, time
from flask import current_app

# Assuming db is initialized in extensions.py
from extensions import db
# Assuming models are defined in models.py
from models import Booking, Resource
# Assuming utility functions are in utils.py
from utils import _load_schedule_from_json, _get_map_configuration_data, add_audit_log

# Conditional import for azure_backup
try:
    from azure_backup import create_full_backup
except ImportError:
    create_full_backup = None

def cancel_unchecked_bookings():
    """
    Cancels bookings that were not checked in within the grace period.
    """
    with current_app.app_context():
        logger = current_app.logger
        grace_minutes = current_app.config.get('CHECK_IN_GRACE_MINUTES', 15)
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=grace_minutes)

        stale_bookings = Booking.query.filter(
            Booking.checked_in_at.is_(None),
            Booking.start_time < cutoff_time,
            Booking.status != 'cancelled' # Avoid trying to cancel already cancelled bookings
        ).all()

        if stale_bookings:
            for booking in stale_bookings:
                original_status = booking.status
                booking.status = 'cancelled' # Set status to cancelled
                logger.info(f"Auto-cancelling booking ID {booking.id} for resource {booking.resource_id} due to no check-in. Original status: {original_status}.")
                add_audit_log(
                    action="AUTO_CANCEL_NO_CHECK_IN",
                    details=f"Booking ID {booking.id} for resource {booking.resource_id} (User: {booking.user_name}) auto-cancelled. Original status: {original_status}.",
                    username="System"
                )
            try:
                db.session.commit()
                logger.info(f"Successfully auto-cancelled {len(stale_bookings)} unchecked bookings.")
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error committing auto-cancellation of bookings: {e}", exc_info=True)
        else:
            logger.info("No stale bookings to auto-cancel at this time.")

def apply_scheduled_resource_status_changes():
    """
    Applies scheduled status changes to resources.
    """
    with current_app.app_context():
        logger = current_app.logger
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

def run_scheduled_backup_job():
    """
    Checks the backup schedule and runs a full backup if due.
    """
    with current_app.app_context():
        logger = current_app.logger
        logger.info("run_scheduled_backup_job: Checking backup schedule (from JSON)...")
        try:
            # _load_schedule_from_json is expected to use current_app.config internally
            schedule_data = _load_schedule_from_json()

            if not schedule_data.get('is_enabled'):
                logger.info("run_scheduled_backup_job: Scheduled backups are disabled (JSON). Skipping.")
                return

            now_utc = datetime.now(timezone.utc)
            current_time_utc = now_utc.time()
            scheduled_time_str = schedule_data.get('time_of_day', "02:00")
            try:
                scheduled_time_obj = datetime.strptime(scheduled_time_str, '%H:%M').time()
            except ValueError:
                logger.error(f"run_scheduled_backup_job: Invalid time_of_day '{scheduled_time_str}' in JSON. Using 02:00.")
                scheduled_time_obj = time(2,0)

            backup_due = False
            schedule_type = schedule_data.get('schedule_type', 'daily')

            if current_time_utc.hour == scheduled_time_obj.hour and current_time_utc.minute == scheduled_time_obj.minute:
                if schedule_type == 'daily':
                    backup_due = True
                elif schedule_type == 'weekly':
                    day_of_week_json = schedule_data.get('day_of_week')
                    if day_of_week_json is not None and now_utc.weekday() == day_of_week_json:
                        backup_due = True

            if backup_due:
                logger.info(f"run_scheduled_backup_job: Backup is due (JSON config) at {scheduled_time_str}. Starting backup...")
                timestamp_str = now_utc.strftime('%Y%m%d_%H%M%S')
                map_config = _get_map_configuration_data()

                if not create_full_backup: # Check if azure_backup.create_full_backup was imported
                    logger.error("run_scheduled_backup_job: create_full_backup function not available/imported.")
                    return

                # Assuming create_full_backup does not need socketio instance when run by scheduler
                success = create_full_backup(timestamp_str, map_config_data=map_config, socketio_instance=None, task_id=None)

                if success:
                    logger.info(f"run_scheduled_backup_job: Scheduled backup (JSON) completed successfully. Timestamp: {timestamp_str}")
                    add_audit_log(action="SCHEDULED_BACKUP_SUCCESS_JSON", details=f"Scheduled backup successful (JSON). Timestamp: {timestamp_str}", username="System")
                else:
                    logger.error(f"run_scheduled_backup_job: Scheduled backup (JSON) failed. Timestamp attempted: {timestamp_str}")
                    add_audit_log(action="SCHEDULED_BACKUP_FAILED_JSON", details=f"Scheduled backup failed (JSON). Timestamp attempted: {timestamp_str}", username="System")
            else:
                logger.debug(f"run_scheduled_backup_job: Backup not currently due. Current: {current_time_utc.strftime('%H:%M')}, Scheduled: {scheduled_time_str}, Type: {schedule_type}")

        except Exception as e:
            logger.exception("run_scheduled_backup_job: Error during scheduled backup job execution (JSON config).")
            add_audit_log(action="SCHEDULED_BACKUP_ERROR_JSON", details=f"Exception: {str(e)}", username="System")
