import logging
from datetime import datetime, timedelta, timezone, time
from flask import current_app, render_template
from extensions import db, socketio
from models import Booking, Resource, User
from utils import load_scheduler_settings, _get_map_configuration_data, add_audit_log, send_email, send_teams_notification

try:
    from azure_backup import create_full_backup, backup_bookings_csv, backup_incremental_bookings
except ImportError:
    create_full_backup = None
    backup_bookings_csv = None
    backup_incremental_bookings = None

def cancel_unchecked_bookings(app_instance): # Changed app to app_instance for clarity
    """
    Cancels bookings that were not checked in within the grace period.
    Assumes an app context is active or app_instance is provided.
    """
    current_app_for_task = app_instance if app_instance else current_app._get_current_object()
    with current_app_for_task.app_context():
        logger = current_app_for_task.logger
        grace_minutes = current_app_for_task.config.get('CHECK_IN_GRACE_MINUTES', 15)
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=grace_minutes)

        stale_bookings = Booking.query.filter(
            Booking.checked_in_at.is_(None),
            Booking.start_time < cutoff_time,
            Booking.status == 'approved'
        ).all()

        if stale_bookings:
            cancelled_booking_details = []
            for booking in stale_bookings:
                original_status = booking.status
                resource_name = "Unknown Resource"
                if booking.resource_booked:
                    resource_name = booking.resource_booked.name
                cancelled_booking_details.append({
                    'user_name': booking.user_name, 'resource_name': resource_name,
                    'start_time_str': booking.start_time.strftime('%Y-%m-%d %H:%M UTC'),
                    'booking_id': booking.id, 'resource_id': booking.resource_id,
                    'original_status': original_status
                })
                booking.status = 'cancelled'
                add_audit_log(
                    action="AUTO_CANCEL_NO_CHECK_IN_ATTEMPT",
                    details=f"Attempting to auto-cancel Booking ID {booking.id} for resource {resource_name} (User: {booking.user_name}). Original status: {original_status}.",
                    username="System"
                )
            try:
                db.session.commit()
                logger.info(f"Successfully auto-cancelled {len(stale_bookings)} unchecked bookings in DB.")
                for details in cancelled_booking_details:
                    add_audit_log(
                        action="AUTO_CANCEL_NO_CHECK_IN_SUCCESS",
                        details=f"Booking ID {details['booking_id']} for resource {details['resource_name']} (User: {details['user_name']}) auto-cancelled. Original status: {details['original_status']}.",
                        username="System"
                    )
                    user = User.query.filter_by(username=details['user_name']).first()
                    if user and user.email:
                        subject = f"Booking Auto-Cancelled: {details['resource_name']}"
                        body_text = (f"Your booking for the resource '{details['resource_name']}' "
                                     f"scheduled to start at {details['start_time_str']} "
                                     f"has been automatically cancelled due to no check-in within the grace period.")
                        try:
                            send_email(user.email, subject, body_text)
                            logger.info(f"Sent auto-cancellation email to {user.email} for booking ID {details['booking_id']}")
                        except Exception as mail_e:
                            logger.error(f"Failed to send auto-cancellation email to {user.email} for booking {details['booking_id']}: {mail_e}")
                        if current_app_for_task.config.get('TEAMS_WEBHOOK_URL'):
                            try:
                                send_teams_notification(user.email, subject, body_text)
                                logger.info(f"Sent auto-cancellation Teams notification for {user.email} for booking ID {details['booking_id']}")
                            except Exception as teams_e:
                                logger.error(f"Failed to send auto-cancellation Teams notification for {user.email} for booking {details['booking_id']}: {teams_e}")
                    else:
                        logger.warning(f"Could not find user or email for {details['user_name']} to notify about auto-cancelled booking ID {details['booking_id']}.")
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error committing auto-cancellation of bookings or sending notifications: {e}", exc_info=True)
                add_audit_log(action="AUTO_CANCEL_BATCH_FAILED", details=f"Failed to commit auto-cancellations or send notifications. Error: {str(e)}", username="System")
        else:
            logger.info("No stale bookings to auto-cancel at this time.")

def apply_scheduled_resource_status_changes(app_instance): # Changed app to app_instance
    current_app_for_task = app_instance if app_instance else current_app._get_current_object()
    with current_app_for_task.app_context():
        logger = current_app_for_task.logger
        now = datetime.now(timezone.utc)
        resources_to_update = Resource.query.filter(
            Resource.scheduled_status_at.isnot(None), Resource.scheduled_status_at <= now,
            Resource.scheduled_status.isnot(None), Resource.scheduled_status != ""
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
                details=(f"Resource {resource.id} ('{resource.name}') status automatically changed "
                         f"from '{old_status}' to '{new_status}' as scheduled for {resource.scheduled_status_at.isoformat()}."),
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

def run_scheduled_backup_job(app_instance): # Changed app to app_instance
    current_app_for_task = app_instance if app_instance else current_app._get_current_object()
    with current_app_for_task.app_context():
        logger = current_app_for_task.logger
        logger.info("run_scheduled_backup_job: Checking backup schedule (from UI settings)...")
        try:
            settings = load_scheduler_settings()
            full_backup_schedule = settings.get('full_backup', {})
            if not full_backup_schedule.get('is_enabled'):
                logger.info("run_scheduled_backup_job: Full backups are disabled via UI settings. Skipping.")
                return
            now_utc = datetime.now(timezone.utc)
            current_time_utc = now_utc.time()
            scheduled_time_str = full_backup_schedule.get('time_of_day', "02:00")
            try:
                scheduled_time_obj = datetime.strptime(scheduled_time_str, '%H:%M').time()
            except ValueError:
                logger.error(f"run_scheduled_backup_job: Invalid time_of_day '{scheduled_time_str}' in UI settings. Using 02:00.")
                scheduled_time_obj = time(2,0)
            backup_due = False
            schedule_type = full_backup_schedule.get('schedule_type', 'daily')
            if current_time_utc.hour == scheduled_time_obj.hour and current_time_utc.minute == scheduled_time_obj.minute:
                if schedule_type == 'daily': backup_due = True
                elif schedule_type == 'weekly':
                    day_of_week_setting = full_backup_schedule.get('day_of_week')
                    if day_of_week_setting is not None and now_utc.weekday() == day_of_week_setting: backup_due = True
            if not backup_due:
                logger.debug(f"run_scheduled_backup_job: Backup not currently due. Current UTC: {current_time_utc.strftime('%H:%M')}, Scheduled UTC: {scheduled_time_str}, Type: {schedule_type}, Today's weekday: {now_utc.weekday()}")
            if backup_due:
                logger.info(f"run_scheduled_backup_job: Backup is due (UI settings) at {scheduled_time_str} UTC. Starting backup...")
                timestamp_str = now_utc.strftime('%Y%m%d_%H%M%S')
                map_config = _get_map_configuration_data()
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
        except Exception as e:
            logger.exception("run_scheduled_backup_job: Error during scheduled backup job execution (UI settings).")
            add_audit_log(action="SCHEDULED_BACKUP_ERROR_UI", details=f"Exception: {str(e)}", username="System")

def run_scheduled_booking_csv_backup(app_instance): # Changed app to app_instance
    current_app_for_task = app_instance if app_instance else current_app._get_current_object()
    with current_app_for_task.app_context():
        logger = current_app_for_task.logger
        logger.info("run_scheduled_booking_csv_backup: Checking Booking Records backup schedule (from UI settings)...")
        try:
            settings = load_scheduler_settings()
            csv_backup_schedule = settings.get('booking_csv_backup', {})
            if not csv_backup_schedule.get('is_enabled'):
                logger.info("run_scheduled_booking_csv_backup: Scheduled Booking Records backups are disabled via UI settings. Skipping.")
                return
            backup_type = csv_backup_schedule.get('booking_backup_type', 'full_export')
            task_id_str = f"scheduled_booking_records_backup_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            success = False
            if backup_type == 'incremental':
                logger.info(f"run_scheduled_booking_csv_backup: Initiating INCREMENTAL booking records backup. Task ID: {task_id_str}")
                if not backup_incremental_bookings:
                    logger.error("run_scheduled_booking_csv_backup: backup_incremental_bookings function not available/imported. Cannot proceed.")
                    return
                success = backup_incremental_bookings(app=current_app_for_task, socketio_instance=None, task_id=task_id_str) # Pass current_app_for_task
                if success:
                    logger.info(f"run_scheduled_booking_csv_backup: Scheduled INCREMENTAL booking records backup completed successfully. Task ID: {task_id_str}")
                    add_audit_log(action="SCHEDULED_INCREMENTAL_BOOKING_BACKUP_SUCCESS_UI", details=f"Scheduled incremental booking records backup successful. Task ID: {task_id_str}", username="System")
                else:
                    logger.error(f"run_scheduled_booking_csv_backup: Scheduled INCREMENTAL booking records backup failed. Task ID: {task_id_str}")
                    add_audit_log(action="SCHEDULED_INCREMENTAL_BOOKING_BACKUP_FAILED_UI", details=f"Scheduled incremental booking records backup failed. Task ID: {task_id_str}", username="System")
            elif backup_type == 'full_export':
                if not backup_bookings_csv:
                    logger.error("run_scheduled_booking_csv_backup: backup_bookings_csv function not available/imported. Cannot proceed.")
                    return
                range_setting = csv_backup_schedule.get('range', 'all'); range_label = range_setting
                start_date_dt = None; end_date_dt = None
                if range_setting != 'all':
                    utcnow = datetime.now(timezone.utc)
                    end_date_dt = datetime(utcnow.year, utcnow.month, utcnow.day, tzinfo=timezone.utc) + timedelta(days=1)
                    if range_setting == "1day": start_date_dt = end_date_dt - timedelta(days=1)
                    elif range_setting == "3days": start_date_dt = end_date_dt - timedelta(days=3)
                    elif range_setting == "7days": start_date_dt = end_date_dt - timedelta(days=7)
                    else: logger.warning(f"Unknown range '{range_setting}'. Defaulting to 'all'."); range_label = 'all'
                logger.info(f"Initiating FULL EXPORT booking records backup (UI settings) for range: {range_label}, Start: {start_date_dt}, End: {end_date_dt}. Task ID: {task_id_str}")
                success = backup_bookings_csv(
                    app=current_app_for_task, socketio_instance=None, task_id=task_id_str, # Pass current_app_for_task
                    start_date_dt=start_date_dt, end_date_dt=end_date_dt, range_label=range_label
                )
                if success:
                    logger.info(f"Scheduled FULL EXPORT booking records backup (UI settings, range: {range_label}) completed successfully.")
                    add_audit_log(action="SCHEDULED_FULL_EXPORT_BOOKING_BACKUP_SUCCESS_UI", details=f"Scheduled full export (UI settings, range: {range_label}) successful.", username="System")
                else:
                    logger.error(f"Scheduled FULL EXPORT booking records backup (UI settings, range: {range_label}) failed.")
                    add_audit_log(action="SCHEDULED_FULL_EXPORT_BOOKING_BACKUP_FAILED_UI", details=f"Scheduled full export (UI settings, range: {range_label}) failed.", username="System")
            else:
                logger.error(f"Unknown booking_backup_type '{backup_type}' configured. Skipping job.")
                add_audit_log(action="SCHEDULED_BOOKING_BACKUP_ERROR_UI", details=f"Unknown backup type: {backup_type}", username="System")
        except Exception as e:
            logger.exception("Error during scheduled booking records backup execution (UI settings).")
            add_audit_log(action="SCHEDULED_BOOKING_BACKUP_ERROR_UI", details=f"Exception: {str(e)}", username="System")

AUTO_CHECKOUT_INTERVAL_MINUTES_CONFIG_KEY = 'AUTO_CHECKOUT_INTERVAL_MINUTES'
AUTO_CHECKOUT_GRACE_PERIOD_HOURS_CONFIG_KEY = 'AUTO_CHECKOUT_GRACE_PERIOD_HOURS'
AUTO_CHECKOUT_SET_CHECKOUT_AFTER_END_HOURS_CONFIG_KEY = 'AUTO_CHECKOUT_SET_CHECKOUT_AFTER_END_HOURS'
DEFAULT_AUTO_CHECKOUT_INTERVAL_MINUTES = 10
DEFAULT_AUTO_CHECKOUT_GRACE_PERIOD_HOURS = 1
DEFAULT_AUTO_CHECKOUT_SET_CHECKOUT_AFTER_END_HOURS = 1

def auto_checkout_overdue_bookings(app_instance=None):
    current_app_for_task = app_instance if app_instance else current_app._get_current_object()
    with current_app_for_task.app_context():
        job_name = 'auto_checkout_overdue_bookings'
        logger = current_app_for_task.logger
        logger.info(f"Scheduler job '{job_name}' starting.")
        if not current_app_for_task.config.get('SCHEDULER_ENABLED', True):
            logger.info(f"Scheduler job '{job_name}' skipped: SCHEDULER_ENABLED is false.")
            return
        grace_period_hours = current_app_for_task.config.get(AUTO_CHECKOUT_GRACE_PERIOD_HOURS_CONFIG_KEY, DEFAULT_AUTO_CHECKOUT_GRACE_PERIOD_HOURS)
        set_checkout_after_end_hours = current_app_for_task.config.get(AUTO_CHECKOUT_SET_CHECKOUT_AFTER_END_HOURS_CONFIG_KEY, DEFAULT_AUTO_CHECKOUT_SET_CHECKOUT_AFTER_END_HOURS)
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=grace_period_hours)
        bookings_to_checkout = []
        try:
            bookings_to_checkout = Booking.query.filter(
                Booking.checked_in_at.isnot(None),
                Booking.checked_out_at.is_(None),
                Booking.end_time < cutoff_time
            ).all()
        except Exception as e:
            logger.error(f"Error querying bookings for auto-checkout: {e}", exc_info=True)
            return
        if not bookings_to_checkout:
            logger.info(f"Scheduler job '{job_name}': No overdue bookings to auto-checkout.")
            return
        processed_count = 0
        for booking in bookings_to_checkout:
            try:
                original_end_time_for_email = booking.end_time.replace(tzinfo=timezone.utc) if booking.end_time.tzinfo is None else booking.end_time
                booking.checked_out_at = booking.end_time + timedelta(hours=set_checkout_after_end_hours)
                booking.status = 'completed'
                resource_name_for_log = booking.resource_booked.name if booking.resource_booked else 'N/A'
                logger.info(f"Auto-checking out booking ID {booking.id}. User: {booking.user_name}. Resource: {resource_name_for_log}. Original End: {original_end_time_for_email.isoformat()}. New Checkout: {booking.checked_out_at.isoformat()}")
                add_audit_log(
                    action="AUTO_CHECKOUT",
                    details=f"Booking ID {booking.id} for resource '{resource_name_for_log}' (User: {booking.user_name}) automatically checked out. Original end time: {original_end_time_for_email.isoformat()}. Checked out at: {booking.checked_out_at.isoformat()}.",
                    username="System"
                )
                booker = User.query.filter_by(username=booking.user_name).first()
                if booker and booker.email:
                    email_data = {
                        'user_name': booking.user_name, 'resource_name': resource_name_for_log,
                        'booking_title': booking.title or 'N/A',
                        'original_end_time': original_end_time_for_email.strftime('%Y-%m-%d %H:%M:%S %Z'),
                        'auto_checkout_time': booking.checked_out_at.replace(tzinfo=timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')
                    }
                    email_subject = "Your Booking Has Been Automatically Checked Out"
                    email_body_plain = render_template('email/booking_auto_checkout_text.html', **email_data)
                    html_email_body = render_template('email/booking_auto_checkout.html', **email_data)
                    send_email(to_address=booker.email, subject=email_subject, body=email_body_plain, html_body=html_email_body)
                    logger.info(f"Sent auto-checkout notification email to {booker.email} for booking ID {booking.id}")
                if socketio:
                    socketio.emit('booking_updated', {
                        'action': 'auto_checked_out', 'booking_id': booking.id,
                        'resource_id': booking.resource_id, 'status': 'completed',
                        'checked_out_at': booking.checked_out_at.replace(tzinfo=timezone.utc).isoformat()
                    })
                processed_count += 1
            except Exception as e_booking:
                logger.error(f"Error auto-checking out booking ID {booking.id}: {e_booking}", exc_info=True)
                db.session.rollback()
        if processed_count > 0:
            try:
                db.session.commit()
                logger.info(f"Scheduler job '{job_name}': Successfully auto-checked out and committed {processed_count} bookings.")
            except Exception as e_commit:
                logger.error(f"Error committing auto-checkout changes to DB: {e_commit}", exc_info=True)
                db.session.rollback()
        else:
            logger.info(f"Scheduler job '{job_name}': No bookings were processed in this run (either none found or errors during processing).")
