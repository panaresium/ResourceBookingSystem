from flask import Blueprint, render_template, current_app, jsonify, flash, redirect, url_for, request, Response # Added request and Response
from flask_login import login_required, current_user
from sqlalchemy import func, cast, Date, Time, extract # For analytics_bookings_data if merged here, or general use
import io # For CSV export/import
import csv # For CSV export/import
from werkzeug.utils import secure_filename # For CSV import
import uuid # For task_id generation

# Assuming Booking, Resource, User models are in models.py
from models import Booking, Resource, User, FloorMap, BookingSettings # Added FloorMap
# Assuming db is in extensions.py
from extensions import db, socketio # Try to import socketio
# Assuming permission_required is in auth.py
from auth import permission_required # Corrected: auth.py is at root
from datetime import datetime, timedelta, timezone # Add datetime imports
from utils import load_scheduler_settings, save_scheduler_settings, DEFAULT_FULL_BACKUP_SCHEDULE, DEFAULT_BOOKING_CSV_BACKUP_SCHEDULE, add_audit_log # Ensure add_audit_log is imported

# Import backup/restore functions
from azure_backup import (
    list_available_backups,
    restore_full_backup,
    list_available_booking_csv_backups,
    restore_bookings_from_csv_backup,
    backup_bookings_csv,
    verify_backup_set,
    delete_backup_set,
    delete_booking_csv_backup,
    verify_booking_csv_backup,
    # New imports for selective booking restore
    list_available_incremental_booking_backups,
    restore_incremental_bookings,
    restore_bookings_from_full_db_backup
)
# Removed duplicate model, db, auth, datetime imports that were already covered above or are standard
import os
import json
from apscheduler.jobstores.base import JobLookupError
from scheduler_tasks import run_scheduled_booking_csv_backup # For re-adding job
from translations import _ # For flash messages and other translatable strings

admin_ui_bp = Blueprint('admin_ui', __name__, url_prefix='/admin', template_folder='../templates')

@admin_ui_bp.route('/users_manage')
@login_required
@permission_required('manage_users')
def serve_user_management_page():
    current_app.logger.info(f"Admin user {current_user.username} accessed User Management page.")
    return render_template("user_management.html")

@admin_ui_bp.route('/logs')
@login_required
@permission_required('view_audit_logs')
def serve_audit_log_page():
    current_app.logger.info(f"Admin user {current_user.username} accessed Audit Log page.")
    return render_template("log_view.html")

@admin_ui_bp.route('/maps')
@login_required
@permission_required('manage_floor_maps')
def serve_admin_maps():
    return render_template("admin_maps.html")

@admin_ui_bp.route('/resources_manage')
@login_required
@permission_required('manage_resources')
def serve_resource_management_page():
    current_app.logger.info(f"Admin user {current_user.username} accessed Resource Management page.")
    return render_template("resource_management.html")

@admin_ui_bp.route('/bookings')
@login_required
@permission_required('manage_bookings')
def serve_admin_bookings_page():
    logger = current_app.logger
    status_filter = request.args.get('status_filter')
    user_filter = request.args.get('user_filter')
    date_filter_str = request.args.get('date_filter')

    logger.info(f"User {current_user.username} accessed Admin Bookings page. Status filter: '{status_filter}', User filter: '{user_filter}', Date filter: '{date_filter_str}'")

    # Define the list of possible statuses for the dropdown
    possible_statuses = ['approved', 'checked_in', 'completed', 'cancelled', 'rejected', 'cancelled_by_admin']

    all_users = User.query.order_by(User.username).all() # Fetch all users

    try:
        bookings_query = db.session.query(
            Booking.id,
            Booking.title,
            Booking.start_time,
            Booking.end_time,
            Booking.status,
            Booking.admin_deleted_message,
            User.username.label('user_username'),
            Resource.name.label('resource_name')
        ).join(Resource, Booking.resource_id == Resource.id)\
         .join(User, Booking.user_name == User.username)

        if status_filter:
            bookings_query = bookings_query.filter(Booking.status == status_filter)

        if user_filter:
            bookings_query = bookings_query.filter(User.username == user_filter)

        if date_filter_str:
            try:
                date_filter_obj = datetime.strptime(date_filter_str, '%Y-%m-%d').date()
                bookings_query = bookings_query.filter(func.date(Booking.start_time) == date_filter_obj)
            except ValueError:
                logger.warning(f"Invalid date format for date_filter: '{date_filter_str}'. Ignoring filter.")
                # flash('Invalid date format. Please use YYYY-MM-DD.', 'warning')

        # Fetch all rows matching filters, without initial overall sorting if Python sort is preferred later.
        # However, database level sorting for large datasets is usually more efficient.
        # For this refactor, we'll fetch then sort in Python as per the plan.
        all_booking_rows = bookings_query.all()

        upcoming_bookings_processed = []
        past_bookings_processed = []
        now_utc = datetime.now(timezone.utc)

        # Optional: Consider global_time_offset_hours from BookingSettings for 'effective_now'
        # booking_settings = BookingSettings.query.first()
        # current_offset_hours = booking_settings.global_time_offset_hours if booking_settings and booking_settings.global_time_offset_hours is not None else 0
        # effective_now_for_comparison = now_utc - timedelta(hours=current_offset_hours)
        # For this implementation, we use now_utc directly as per instruction, assuming start_time is UTC.

        for row in all_booking_rows:
            start_time_dt = row.start_time
            aware_start_time = start_time_dt
            if start_time_dt is not None and start_time_dt.tzinfo is None:
                aware_start_time = start_time_dt.replace(tzinfo=timezone.utc)

            end_time_dt = row.end_time
            aware_end_time = end_time_dt
            if end_time_dt is not None and end_time_dt.tzinfo is None:
                aware_end_time = end_time_dt.replace(tzinfo=timezone.utc)

            booking_data = {
                'id': row.id,
                'title': row.title,
                'start_time': aware_start_time, # Use the (potentially) tz-aware version
                'end_time': aware_end_time,     # Use the (potentially) tz-aware version
                'status': row.status,
                'user_username': row.user_username,
                'resource_name': row.resource_name,
                'admin_deleted_message': row.admin_deleted_message
            }

            # Partitioning based on start_time relative to now_utc
            if aware_start_time is not None and aware_start_time >= now_utc:
                upcoming_bookings_processed.append(booking_data)
            elif aware_start_time is not None: # It's in the past
                past_bookings_processed.append(booking_data)
            # else: start_time is None. If this is possible, decide how to classify such bookings.
            # For now, they won't be added to either list if start_time is None.

        # Sort upcoming_or_current_bookings by start_time ascending (soonest first)
        upcoming_bookings_processed.sort(key=lambda b: b['start_time'])
        # Sort past_bookings by start_time descending (most recent past first)
        past_bookings_processed.sort(key=lambda b: b['start_time'], reverse=True)

        # The 'possible_statuses' list in the original code for the filter dropdown was:
        # ['approved', 'checked_in', 'completed', 'cancelled', 'rejected', 'cancelled_by_admin']
        # The admin_bookings.html template also uses `all_statuses` for the status change dropdown.
        # This should be a comprehensive list of all valid statuses the system uses.
        # For consistency, let's define a more comprehensive list or fetch from a central place if available.
        # For now, using a more extended list similar to what was used in admin_api_bookings.py
        comprehensive_statuses = [
            'pending', 'approved', 'rejected', 'cancelled', 'checked_in', 'completed',
            'cancelled_by_user', 'cancelled_by_admin', 'cancelled_admin_acknowledged',
            'no_show', 'awaiting_payment', 'payment_failed', 'confirmed_pending_payment',
            'rescheduled', 'awaiting_confirmation', 'under_review', 'on_hold', 'archived',
            'expired', 'draft', 'system_cancelled', 'error', 'pending_approval',
            'pending_resource_confirmation', 'active', 'inactive', 'user_confirmed',
            'admin_confirmed', 'auto_approved', 'auto_cancelled', 'payment_pending',
            'payment_received', 'fulfillment_pending', 'fulfillment_complete', 'action_required',
            'dispute_raised', 'dispute_resolved', 'refund_pending', 'refund_completed',
            'partially_refunded', 'voided', 'pending_cancellation', 'cancellation_requested',
            'attended', 'absent', 'tentative', 'waitlisted', 'blocked', 'requires_modification',
            'pending_reschedule', 'reschedule_confirmed', 'reschedule_declined',
            'pending_payment_confirmation', 'payment_disputed', 'subscription_active',
            'subscription_cancelled', 'subscription_ended', 'subscription_pending', 'trial', 'past_due'
        ]
        # Filter out any None or empty strings from comprehensive_statuses if they exist
        comprehensive_statuses = sorted(list(set(s for s in comprehensive_statuses if s and s.strip())))


        return render_template("admin_bookings.html",
                               upcoming_bookings=upcoming_bookings_processed,
                               past_bookings=past_bookings_processed,
                               all_statuses=comprehensive_statuses, # Use the more comprehensive list
                               current_status_filter=status_filter,
                               all_users=all_users,
                               current_user_filter=user_filter,
                               current_date_filter=date_filter_str,
                               new_sorting_active=True)
    except Exception as e:
        logger.error(f"Error fetching and sorting bookings for admin page: {e}", exc_info=True)
        # Define comprehensive_statuses here as well for the error case
        comprehensive_statuses = [
            'pending', 'approved', 'rejected', 'cancelled', 'checked_in', 'completed',
            'cancelled_by_user', 'cancelled_by_admin', 'cancelled_admin_acknowledged', 'no_show'
            # A smaller, but still reasonable default list for error cases
        ]
        comprehensive_statuses = sorted(list(set(s for s in comprehensive_statuses if s and s.strip())))

        return render_template("admin_bookings.html",
                               upcoming_bookings=[],
                               past_bookings=[],
                               error="Could not load and sort bookings.",
                               all_statuses=comprehensive_statuses,
                               current_status_filter=status_filter,
                               all_users=all_users,
                               current_user_filter=user_filter,
                               current_date_filter=date_filter_str,
                               new_sorting_active=True)

@admin_ui_bp.route('/backup_restore')
@login_required
@permission_required('manage_system')
def serve_backup_restore_page():
    current_app.logger.info(f"User {current_user.username} accessed legacy /admin/backup_restore, redirecting to /admin/backup/system.")
    return redirect(url_for('admin_ui.serve_backup_system_page'))

@admin_ui_bp.route('/backup/system', methods=['GET'])
@login_required
@permission_required('manage_system')
def serve_backup_system_page():
    current_app.logger.info(f"User {current_user.username} accessed System Backup & Restore page.")
    scheduler_settings = load_scheduler_settings()
    full_backup_settings = scheduler_settings.get('full_backup', DEFAULT_FULL_BACKUP_SCHEDULE.copy())

    # Get global_time_offset_hours
    time_offset_value = 0 # Default
    try:
        booking_settings = BookingSettings.query.first()
        if booking_settings and booking_settings.global_time_offset_hours is not None:
            time_offset_value = booking_settings.global_time_offset_hours
        elif not booking_settings:
            current_app.logger.info("No BookingSettings found for system page, defaulting offset to 0. Consider creating a default record.")
        else: # booking_settings exists but global_time_offset_hours is None
            current_app.logger.warning("BookingSettings.global_time_offset_hours is None for system page, defaulting offset to 0.")
    except Exception as e:
        current_app.logger.error(f"Error fetching BookingSettings for system page: {e}", exc_info=True)
        # time_offset_value remains 0

    # list_available_backups() is handled by JavaScript on the client-side now for this tab.
    return render_template('admin/backup_system.html',
                           full_backup_settings=full_backup_settings,
                           global_time_offset_hours=time_offset_value)

@admin_ui_bp.route('/backup/booking_data', methods=['GET'])
@login_required
@permission_required('manage_system')
def serve_backup_booking_data_page():
    current_app.logger.info(f"User {current_user.username} accessed Booking Data Management page.")
    scheduler_settings = load_scheduler_settings()
    booking_csv_backup_settings = scheduler_settings.get('booking_csv_backup', DEFAULT_BOOKING_CSV_BACKUP_SCHEDULE.copy())

    # Pagination logic for Booking CSV Backups (Flask-populated part)
    all_booking_csv_files = list_available_booking_csv_backups() if list_available_booking_csv_backups else []
    page = request.args.get('page', 1, type=int)
    per_page = 10
    total_items = len(all_booking_csv_files)
    total_pages = (total_items + per_page - 1) // per_page if per_page > 0 else 0
    if total_pages == 0 and total_items > 0 : total_pages = 1 # if per_page is 0 but items exist
    if page > total_pages and total_pages > 0: page = total_pages # cap page
    if page < 1: page = 1 # ensure page is at least 1

    start_index = (page - 1) * per_page
    end_index = start_index + per_page
    paginated_booking_csv_backups = all_booking_csv_files[start_index:end_index]
    has_prev = page > 1
    has_next = page < total_pages

    # Other lists (full system backups for selective booking restore, incremental backups)
    # will be loaded client-side by JavaScript.

    # Get global_time_offset_hours
    time_offset_value = 0 # Default
    try:
        booking_settings = BookingSettings.query.first()
        if booking_settings and booking_settings.global_time_offset_hours is not None:
            time_offset_value = booking_settings.global_time_offset_hours
        elif not booking_settings:
            current_app.logger.info("No BookingSettings found for booking data page, defaulting offset to 0. Consider creating a default record.")
        else: # booking_settings exists but global_time_offset_hours is None
            current_app.logger.warning("BookingSettings.global_time_offset_hours is None for booking data page, defaulting offset to 0.")
    except Exception as e:
        current_app.logger.error(f"Error fetching BookingSettings for booking data page: {e}", exc_info=True)
        # time_offset_value remains 0

    return render_template('admin/backup_booking_data.html',
                           booking_csv_backup_settings=booking_csv_backup_settings,
                           booking_csv_backups=paginated_booking_csv_backups,
                           booking_csv_page=page,
                           booking_csv_total_pages=total_pages,
                           booking_csv_has_prev=has_prev,
                           booking_csv_has_next=has_next,
                           global_time_offset_hours=time_offset_value)

@admin_ui_bp.route('/backup/settings', methods=['GET'])
@login_required
@permission_required('manage_system')
def serve_backup_settings_page():
    current_app.logger.info(f"User {current_user.username} accessed Backup General Settings page.")
    scheduler_settings = load_scheduler_settings()
    auto_restore_booking_records_on_startup = scheduler_settings.get('auto_restore_booking_records_on_startup', False)

    # Get global_time_offset_hours from BookingSettings
    booking_settings = BookingSettings.query.first()
    if not booking_settings:
        current_app.logger.info("No BookingSettings found, creating default with global_time_offset_hours = 0.")
        booking_settings = BookingSettings(global_time_offset_hours=0)
        db.session.add(booking_settings)
        try:
            db.session.commit()
            current_app.logger.info("Default BookingSettings committed to database.")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error committing default BookingSettings: {e}", exc_info=True)
            # If commit fails, we still proceed with the default value in memory for this request
            # but it won't be persisted, which is a potential issue for subsequent operations.
            # For this specific read-only operation in the GET request, it's acceptable.

    global_time_offset_hours = booking_settings.global_time_offset_hours if booking_settings else 0
    # Ensure global_time_offset_hours is not None, default to 0 if it is (should be handled by model default)
    if global_time_offset_hours is None:
        global_time_offset_hours = 0
        current_app.logger.warning("global_time_offset_hours was None, defaulted to 0.")


    return render_template('admin/backup_settings.html',
                           auto_restore_booking_records_on_startup=auto_restore_booking_records_on_startup,
                           global_time_offset_hours=global_time_offset_hours)


@admin_ui_bp.route('/admin/restore_booking_csv/<timestamp_str>', methods=['POST']) # This URL might need to be adjusted if it's not blueprint relative
@login_required
@permission_required('manage_system')
def restore_booking_csv_route(timestamp_str):
    current_app.logger.info(f"User {current_user.username} initiated restore for booking CSV backup: {timestamp_str}")
    task_id = uuid.uuid4().hex

    # Use current_app._get_current_object() to pass the actual app instance
    # Pass socketio instance if available and configured, else None
    socketio_instance = None
    if hasattr(current_app, 'extensions') and 'socketio' in current_app.extensions:
        socketio_instance = current_app.extensions['socketio']
    elif 'socketio' in globals() and socketio: # Check imported socketio from extensions
        socketio_instance = socketio

    summary = restore_bookings_from_csv_backup(
        current_app._get_current_object(),
        timestamp_str,
        socketio_instance=socketio_instance,
        task_id=task_id
    )

    if summary['status'] == 'completed_successfully' or (summary['status'] == 'completed_with_errors' and not summary.get('errors')):
        flash_msg = f"Booking CSV restore for {timestamp_str} completed. Processed: {summary.get('processed',0)}, Created: {summary.get('created',0)}, Skipped Duplicates: {summary.get('skipped_duplicates',0)}."
        if summary.get('errors'): # Should not happen if status is completed_successfully, but good check
             flash_msg += f" Warnings: {'; '.join(summary['errors'])}"
        flash(flash_msg, 'success')
    elif summary['status'] == 'completed_with_errors' and summary.get('errors'):
        error_details = '; '.join(summary['errors'])
        flash(f"Booking CSV restore for {timestamp_str} completed with errors. Errors: {error_details}. Processed: {summary.get('processed',0)}, Created: {summary.get('created',0)}, Skipped: {summary.get('skipped_duplicates',0)}.", 'danger')
    else: # 'failed' or any other status
        error_details = '; '.join(summary.get('errors', ['Unknown error']))
        flash(f"Booking CSV restore for {timestamp_str} failed. Status: {summary.get('status','unknown')}. Message: {summary.get('message','N/A')}. Details: {error_details}", 'danger')

    return redirect(url_for('admin_ui.serve_backup_booking_data_page')) # Redirect to the booking data tab

@admin_ui_bp.route('/admin/manual_backup_bookings_csv', methods=['POST']) # This URL might need to be adjusted
@login_required
@permission_required('manage_system')
def manual_backup_bookings_csv_route():
    task_id = uuid.uuid4().hex
    socketio_instance = None
    if hasattr(current_app, 'extensions') and 'socketio' in current_app.extensions:
        socketio_instance = current_app.extensions['socketio']
    elif 'socketio' in globals() and socketio: # Check imported socketio from extensions
        socketio_instance = socketio

    app_instance = current_app._get_current_object()

    range_type = request.form.get('backup_range_type', 'all')
    start_date_dt = None
    end_date_dt = None
    range_label = range_type

    utcnow = datetime.utcnow()
    # Calculate end_date_dt as the beginning of tomorrow to include all of today
    # For 'all', start_date_dt and end_date_dt remain None
    if range_type != "all":
        end_date_dt = datetime(utcnow.year, utcnow.month, utcnow.day) + timedelta(days=1)

    if range_type == "1day":
        start_date_dt = end_date_dt - timedelta(days=1)
    elif range_type == "3days":
        start_date_dt = end_date_dt - timedelta(days=3)
    elif range_type == "7days":
        start_date_dt = end_date_dt - timedelta(days=7)
    elif range_type == "all": # Explicitly handle 'all' for clarity, though defaults cover it
        start_date_dt = None
        end_date_dt = None
        range_label = "all"

    log_detail = f"range: {range_label}"
    if start_date_dt: log_detail += f", from: {start_date_dt.strftime('%Y-%m-%d')}"
    if end_date_dt: log_detail += f", to: {end_date_dt.strftime('%Y-%m-%d')}"

    app_instance.logger.info(f"Manual booking CSV backup ({log_detail}) triggered by user {current_user.username if current_user else 'Unknown User'} with task ID {task_id}.")

    try:
        success = backup_bookings_csv(
            app=app_instance,
            socketio_instance=socketio_instance,
            task_id=task_id,
            start_date_dt=start_date_dt,
            end_date_dt=end_date_dt,
            range_label=range_label
        )
        if success:
            flash(_('Manual booking CSV backup for range "%(range)s" initiated successfully. Check logs or SocketIO messages for progress/completion.') % {'range': range_label}, 'success')
        else:
            flash(_('Manual booking CSV backup for range "%(range)s" failed to complete successfully. Please check server logs.') % {'range': range_label}, 'warning')
    except Exception as e:
        app_instance.logger.error(f"Exception during manual booking CSV backup (range: {range_label}) initiation by user {current_user.username if current_user else 'Unknown User'}: {str(e)}", exc_info=True)
        flash(_('An unexpected error occurred while starting the manual booking CSV backup for range "%(range)s". Check server logs.') % {'range': range_label}, 'danger')

    return redirect(url_for('admin_ui.serve_backup_booking_data_page')) # Redirect to the booking data tab

@admin_ui_bp.route('/admin/delete_booking_csv/<timestamp_str>', methods=['POST']) # This URL might need to be adjusted
@login_required
@permission_required('manage_system')
def delete_booking_csv_backup_route(timestamp_str):
    task_id = uuid.uuid4().hex
    socketio_instance = None
    if hasattr(current_app, 'extensions') and 'socketio' in current_app.extensions:
        socketio_instance = current_app.extensions['socketio']
    elif 'socketio' in globals() and socketio:
        socketio_instance = socketio

    app_instance = current_app._get_current_object()
    app_instance.logger.info(f"Deletion of booking CSV backup {timestamp_str} triggered by user {current_user.username if current_user else 'Unknown User'} with task ID {task_id}.")

    try:
        success = delete_booking_csv_backup(timestamp_str, socketio_instance=socketio_instance, task_id=task_id)
        if success:
            flash(_('Booking CSV backup for %(timestamp)s successfully deleted (or was not found).') % {'timestamp': timestamp_str}, 'success')
        else:
            flash(_('Failed to delete booking CSV backup for %(timestamp)s. Check server logs.') % {'timestamp': timestamp_str}, 'danger')
    except Exception as e:
        app_instance.logger.error(f"Exception during booking CSV backup deletion for {timestamp_str} by user {current_user.username if current_user else 'Unknown User'}: {str(e)}", exc_info=True)
        flash(_('An unexpected error occurred while deleting the booking CSV backup for %(timestamp)s. Check server logs.') % {'timestamp': timestamp_str}, 'danger')

    return redirect(url_for('admin_ui.serve_backup_booking_data_page')) # Redirect to the booking data tab


@admin_ui_bp.route('/save_booking_csv_schedule', methods=['POST'])
@login_required
@permission_required('manage_system')
def save_booking_csv_schedule_settings(): # Renamed function to match new approach
    current_app.logger.info(f"User {current_user.username} attempting to save Booking CSV Backup schedule settings.")

    # Construct config file path within the route to use current_app context
    booking_csv_schedule_config_file = os.path.join(current_app.config['DATA_DIR'], 'booking_csv_schedule.json')

    try:
        is_enabled = request.form.get('booking_csv_schedule_enabled') == 'true'
        interval_value_str = request.form.get('booking_csv_schedule_interval_value', '24')
        interval_unit = request.form.get('booking_csv_schedule_interval_unit', 'hours')
        range_type = request.form.get('booking_csv_schedule_range_type', 'all')

        # Validate Interval Value
        try:
            interval_value = int(interval_value_str)
            if interval_value <= 0:
                raise ValueError(_("Interval must be positive."))
        except ValueError as ve:
            flash(str(ve) or _('Invalid interval value. Please enter a positive integer.'), 'danger')
            return redirect(url_for('admin_ui.serve_backup_restore_page'))

        # Validate Interval Unit
        allowed_units = ['minutes', 'hours', 'days']
        if interval_unit not in allowed_units:
            flash(_('Invalid interval unit specified.'), 'danger')
            return redirect(url_for('admin_ui.serve_backup_restore_page'))

        # Validate Range Type
        allowed_range_types = ['all', '1day', '3days', '7days']
        if range_type not in allowed_range_types:
            flash(_('Invalid backup data range type specified.'), 'danger')
            return redirect(url_for('admin_ui.serve_backup_restore_page'))

        schedule_settings = {
            'enabled': is_enabled,
            'interval_value': interval_value,
            'interval_unit': interval_unit,
            'range_type': range_type
        }

        os.makedirs(os.path.dirname(booking_csv_schedule_config_file), exist_ok=True)
        with open(booking_csv_schedule_config_file, 'w') as f:
            json.dump(schedule_settings, f, indent=4)

        current_app.logger.info(f"Booking CSV Backup schedule settings saved to file by {current_user.username}: {schedule_settings}")
        flash(_('Booking CSV backup schedule settings saved successfully.'), 'success')

        # Update current app config with new settings
        current_app.config['BOOKING_CSV_SCHEDULE_SETTINGS'] = schedule_settings
        current_app.logger.info(f"Updated app.config['BOOKING_CSV_SCHEDULE_SETTINGS'] to: {schedule_settings}")

        # Dynamically update the scheduler
        scheduler = getattr(current_app, 'scheduler', None)
        if scheduler and scheduler.running:
            job_id = 'scheduled_booking_csv_backup_job'
            try:
                existing_job = scheduler.get_job(job_id)
                if existing_job:
                    scheduler.remove_job(job_id)
                    current_app.logger.info(f"Removed existing scheduler job '{job_id}' to apply new schedule.")
            except JobLookupError:
                current_app.logger.info(f"Scheduler job '{job_id}' not found, no need to remove before potentially adding.")
            except Exception as e_remove: # Catch other potential errors during job removal
                current_app.logger.error(f"Error removing existing scheduler job '{job_id}': {e_remove}", exc_info=True)
                flash(_('Error removing old schedule job. Please check logs. New schedule might not apply until restart.'), 'warning')

            if schedule_settings.get('enabled'):
                interval_value = schedule_settings.get('interval_value')
                interval_unit = schedule_settings.get('interval_unit')

                job_kwargs = {}
                if interval_unit == 'minutes': job_kwargs['minutes'] = interval_value
                elif interval_unit == 'hours': job_kwargs['hours'] = interval_value
                elif interval_unit == 'days': job_kwargs['days'] = interval_value
                else:
                    # This case should ideally be prevented by earlier validation
                    current_app.logger.error(f"Invalid interval unit '{interval_unit}' for scheduler. Defaulting to 24 hours.")
                    job_kwargs = {'hours': 24} # Fallback

                try:
                    scheduler.add_job(
                        func=run_scheduled_booking_csv_backup, # Direct function reference
                        trigger='interval',
                        id=job_id,
                        **job_kwargs,
                        args=[current_app._get_current_object()] # Pass app instance for the job context
                    )
                    flash(_('Schedule updated. New settings will apply. The job has been re-added/updated.'), 'info')
                    current_app.logger.info(f"Added/Updated scheduler job '{job_id}' with interval {interval_value} {interval_unit}.")
                except Exception as e_add_job:
                    current_app.logger.error(f"Failed to add/update scheduler job '{job_id}': {e_add_job}", exc_info=True)
                    flash(_('Failed to apply new schedule settings to the scheduler. Please check logs.'), 'danger')
            else:
                # If schedule is disabled and job was removed (or not found), this is the desired state.
                flash(_('Schedule updated and is now disabled. The job has been removed if it existed.'), 'info')
                current_app.logger.info(f"Scheduled booking CSV backup is now disabled. Job '{job_id}' removed (if it existed).")
        elif not scheduler or not scheduler.running:
            current_app.logger.warning("Scheduler not found or not running. Schedule changes will apply on next app start.")
            flash(_('Schedule settings saved, but scheduler is not running. Changes will apply on restart.'), 'warning')

    except Exception as e:
        current_app.logger.error(f"Error saving Booking CSV backup schedule settings by {current_user.username}: {str(e)}", exc_info=True)
        flash(_('An error occurred while saving the schedule settings. Please check the logs.'), 'danger')

    return redirect(url_for('admin_ui.serve_backup_booking_data_page')) # Redirect to the booking data tab


@admin_ui_bp.route('/settings/schedule/full_backup', methods=['POST'])
@login_required
@permission_required('manage_system')
def save_full_backup_schedule_settings():
    current_app.logger.info(f"User {current_user.username} attempting to save Full Backup schedule settings.")
    try:
        all_settings = load_scheduler_settings()

        # Ensure 'full_backup' key exists, using a copy of defaults if not
        if 'full_backup' not in all_settings:
            from utils import DEFAULT_FULL_BACKUP_SCHEDULE # Import default for safety
            all_settings['full_backup'] = DEFAULT_FULL_BACKUP_SCHEDULE.copy()

        all_settings['full_backup']['is_enabled'] = request.form.get('full_backup_enabled') == 'true'
        all_settings['full_backup']['schedule_type'] = request.form.get('full_backup_schedule_type', 'daily')
        all_settings['full_backup']['time_of_day'] = request.form.get('full_backup_time_of_day', '02:00')

        day_of_week_str = request.form.get('full_backup_day_of_week')
        if day_of_week_str is not None and day_of_week_str.isdigit():
            all_settings['full_backup']['day_of_week'] = int(day_of_week_str)
        elif all_settings['full_backup']['schedule_type'] == 'weekly':
            all_settings['full_backup']['day_of_week'] = 0 # Default to Monday if weekly and not specified
        else:
            all_settings['full_backup']['day_of_week'] = None


        save_scheduler_settings(all_settings)
        flash(_('Full backup schedule settings saved successfully.'), 'success')
        current_app.logger.info(f"Full backup schedule settings saved by {current_user.username}: {all_settings['full_backup']}")

        # Here you might want to update APScheduler if it's running, similar to booking_csv_schedule_route
        # For now, this subtask focuses on saving to JSON. APScheduler update is a separate concern.

    except Exception as e:
        current_app.logger.error(f"Error saving Full Backup schedule settings by {current_user.username}: {str(e)}", exc_info=True)
        flash(_('An error occurred while saving the full backup schedule settings. Please check the logs.'), 'danger')
    return redirect(url_for('admin_ui.serve_backup_system_page')) # Redirect to system tab


@admin_ui_bp.route('/settings/schedule/booking_csv', methods=['POST']) # This route is for saving the schedule for booking CSVs
@login_required
@permission_required('manage_system')
def save_booking_data_schedule_settings(): # Renamed to reflect it's for booking data schedules
    current_app.logger.info(f"User {current_user.username} attempting to save Booking Data Backup schedule settings.")
    try:
        all_settings = load_scheduler_settings()

        if 'booking_csv_backup' not in all_settings: # Ensure this key matches what's used in load/save
            from utils import DEFAULT_BOOKING_CSV_BACKUP_SCHEDULE
            all_settings['booking_csv_backup'] = DEFAULT_BOOKING_CSV_BACKUP_SCHEDULE.copy()

        all_settings['booking_csv_backup']['is_enabled'] = request.form.get('booking_csv_backup_enabled') == 'true'

        interval_minutes_str = request.form.get('booking_csv_backup_interval_minutes', '60')
        try:
            interval_minutes = int(interval_minutes_str)
            if interval_minutes < 1:
                flash(_('Interval for Booking Data backup must be at least 1 minute.'), 'danger')
                return redirect(url_for('admin_ui.serve_backup_booking_data_page'))
            all_settings['booking_csv_backup']['interval_minutes'] = interval_minutes
        except ValueError:
            flash(_('Invalid interval value for Booking Data backup. Please enter a number.'), 'danger')
            return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

        all_settings['booking_csv_backup']['booking_backup_type'] = request.form.get('booking_backup_type', 'full_export')

        if all_settings['booking_csv_backup']['booking_backup_type'] == 'full_export':
            all_settings['booking_csv_backup']['range'] = request.form.get('booking_csv_backup_range_type', 'all')
        else:
            if 'range' not in all_settings['booking_csv_backup']:
                 all_settings['booking_csv_backup']['range'] = 'all' # Default if not present

        save_scheduler_settings(all_settings)
        flash(_('Booking data backup schedule settings saved successfully.'), 'success')
        current_app.logger.info(f"Booking Data backup schedule settings saved by {current_user.username}: {all_settings['booking_csv_backup']}")

        # APScheduler update logic would go here - for now, changes apply on restart or next scheduled task load
        # based on scheduler_tasks.py logic.

    except Exception as e:
        current_app.logger.error(f"Error saving Booking Data backup schedule settings by {current_user.username}: {str(e)}", exc_info=True)
        flash(_('An error occurred while saving the Booking Data backup schedule settings. Please check the logs.'), 'danger')
    return redirect(url_for('admin_ui.serve_backup_booking_data_page')) # Redirect to booking data tab


@admin_ui_bp.route('/settings/startup/auto_restore_bookings', methods=['POST'])
@login_required
@permission_required('manage_system')
def save_auto_restore_booking_records_settings():
    current_app.logger.info(f"User {current_user.username} attempting to save 'Auto Restore Booking Records on Startup' settings.")
    try:
        all_settings = load_scheduler_settings()

        is_enabled = request.form.get('auto_restore_booking_records_enabled') == 'true'
        all_settings['auto_restore_booking_records_on_startup'] = is_enabled

        save_scheduler_settings(all_settings)

        if is_enabled:
            flash(_('Automatic restore of booking records on startup ENABLED.'), 'success')
        else:
            flash(_('Automatic restore of booking records on startup DISABLED.'), 'success')

        current_app.logger.info(f"'Auto Restore Booking Records on Startup' setting saved by {current_user.username}: {is_enabled}")

    except Exception as e:
        current_app.logger.error(f"Error saving 'Auto Restore Booking Records on Startup' setting by {current_user.username}: {str(e)}", exc_info=True)
        flash(_('An error occurred while saving the auto restore setting. Please check the logs.'), 'danger')
    return redirect(url_for('admin_ui.serve_backup_settings_page')) # Redirect to settings tab


@admin_ui_bp.route('/backup/settings/time_offset', methods=['POST'], endpoint='save_backup_time_offset')
@login_required
@permission_required('manage_system')
def save_backup_time_offset_route():
    current_app.logger.info(f"User {current_user.username} attempting to save Global Time Offset for backups.")
    try:
        new_offset_str = request.form.get('global_time_offset_hours')

        if new_offset_str is None or new_offset_str.strip() == "":
            flash(_('Time offset value must be provided and cannot be empty.'), 'danger')
            return redirect(url_for('admin_ui.serve_backup_settings_page'))

        try:
            new_offset_value = int(new_offset_str)
        except ValueError:
            flash(_('Invalid input for time offset. Please enter a whole number (integer).'), 'danger')
            return redirect(url_for('admin_ui.serve_backup_settings_page'))

        if not (-23 <= new_offset_value <= 23): # Range check
            flash(_('Time offset must be an integer between -23 and +23 hours.'), 'danger')
            return redirect(url_for('admin_ui.serve_backup_settings_page'))

        # If validation passes, proceed to save
        settings = BookingSettings.query.first()
        if not settings:
            current_app.logger.info("No BookingSettings found, creating default instance before saving time offset.")
            settings = BookingSettings(global_time_offset_hours=0) # Default other fields as per model
            db.session.add(settings)
            # Attempt to commit here to ensure 'settings' object is persistent for the next step
            try:
                db.session.commit()
                current_app.logger.info("Created and committed default BookingSettings.")
            except Exception as e_commit_default:
                db.session.rollback()
                current_app.logger.error(f"Error committing new default BookingSettings: {e_commit_default}", exc_info=True)
                flash(_('Error initializing system settings. Could not save time offset.'), 'danger')
                return redirect(url_for('admin_ui.serve_backup_settings_page'))

        settings.global_time_offset_hours = new_offset_value
        db.session.commit()

        add_audit_log(action="UPDATE_GLOBAL_TIME_OFFSET", details=f"Global time offset for backups set to {new_offset_value} hours by {current_user.username}.")
        flash(_('Global time offset saved successfully.'), 'success')
        current_app.logger.info(f"Global time offset set to {new_offset_value} hours by {current_user.username}.")

    except Exception as e:
        db.session.rollback() # Rollback in case of other unexpected errors during the process
        current_app.logger.error(f"Error saving Global Time Offset by {current_user.username}: {str(e)}", exc_info=True)
        flash(_('An error occurred while saving the time offset. Please check the logs.'), 'danger')

    return redirect(url_for('admin_ui.serve_backup_settings_page'))


@admin_ui_bp.route('/admin/verify_booking_csv/<timestamp_str>', methods=['POST']) # This URL might need to be adjusted
@login_required
@permission_required('manage_system')
def verify_booking_csv_backup_route(timestamp_str):
    task_id = uuid.uuid4().hex
    socketio_instance = None
    if hasattr(current_app, 'extensions') and 'socketio' in current_app.extensions:
        socketio_instance = current_app.extensions['socketio']
    elif 'socketio' in globals() and socketio:
        socketio_instance = socketio

    app_instance = current_app._get_current_object()
    app_instance.logger.info(f"Booking CSV backup verification for {timestamp_str} triggered by user {current_user.username if current_user else 'Unknown User'} with task ID {task_id}.")

    try:
        verification_result = verify_booking_csv_backup(timestamp_str, socketio_instance=socketio_instance, task_id=task_id)

        status = verification_result.get('status', 'unknown')
        message = verification_result.get('message', 'No details provided.')
        file_path = verification_result.get('file_path', 'N/A')

        if status == 'success':
            flash(_('Booking CSV Backup Verification for "%(timestamp)s": File found at "%(path)s".') % {'timestamp': timestamp_str, 'path': file_path}, 'success')
        elif status == 'not_found':
            flash(_('Booking CSV Backup Verification for "%(timestamp)s": File NOT found at "%(path)s".') % {'timestamp': timestamp_str, 'path': file_path}, 'warning')
        else: # 'error' or 'unknown'
            flash(_('Booking CSV Backup Verification for "%(timestamp)s" FAILED: %(message)s') % {'timestamp': timestamp_str, 'message': message}, 'danger')

    except Exception as e:
        app_instance.logger.error(f"Exception during Booking CSV backup verification for {timestamp_str} by user {current_user.username if current_user else 'Unknown User'}: {str(e)}", exc_info=True)
        flash(_('An unexpected error occurred while verifying Booking CSV backup %(timestamp)s. Check server logs.') % {'timestamp': timestamp_str}, 'danger')

    return redirect(url_for('admin_ui.serve_backup_booking_data_page')) # Redirect to booking data tab


@admin_ui_bp.route('/verify_full_backup/<timestamp_str>', methods=['POST']) # This URL might need to be adjusted
@login_required
@permission_required('manage_system')
def verify_full_backup_route(timestamp_str):
    task_id = uuid.uuid4().hex
    socketio_instance = None
    if hasattr(current_app, 'extensions') and 'socketio' in current_app.extensions:
        socketio_instance = current_app.extensions['socketio']
    elif 'socketio' in globals() and socketio:
        socketio_instance = socketio

    app_instance = current_app._get_current_object()
    app_instance.logger.info(f"Full backup verification for {timestamp_str} triggered by user {current_user.username if current_user else 'Unknown User'} with task ID {task_id}.")

    try:
        verification_summary = verify_backup_set(timestamp_str, socketio_instance=socketio_instance, task_id=task_id)

        status_message = verification_summary.get('status', 'unknown').replace('_', ' ').title()
        errors = verification_summary.get('errors', [])
        # checks = verification_summary.get('checks', []) # For more detailed logging if needed

        if verification_summary.get('status') == 'verified_present':
            flash(_('Backup set %(timestamp)s verified successfully. Status: %(status)s') % {'timestamp': timestamp_str, 'status': status_message}, 'success')
        elif verification_summary.get('status') in ['manifest_missing', 'manifest_corrupt', 'failed_verification', 'critical_error']:
            error_details = "; ".join(errors)
            flash(_('Backup set %(timestamp)s verification FAILED. Status: %(status)s. Errors: %(details)s') % {'timestamp': timestamp_str, 'status': status_message, 'details': error_details}, 'danger')
            # Log detailed checks for failed verifications
            # for check_item in checks:
            #     app_instance.logger.debug(f"Verification check for {timestamp_str} ({task_id}): {check_item}")
        else: # e.g. 'pending' or other statuses if verify_backup_set is asynchronous (currently it's synchronous)
            flash(_('Backup set %(timestamp)s verification status: %(status)s. Issues: %(errors)s') % {'timestamp': timestamp_str, 'status': status_message, 'errors': '; '.join(errors)}, 'warning')

    except Exception as e:
        app_instance.logger.error(f"Exception during full backup verification for {timestamp_str} by user {current_user.username if current_user else 'Unknown User'}: {str(e)}", exc_info=True)
        flash(_('An unexpected error occurred while verifying backup set %(timestamp)s. Check server logs.') % {'timestamp': timestamp_str}, 'danger')

    return redirect(url_for('admin_ui.serve_backup_system_page')) # Redirect to system tab


@admin_ui_bp.route('/troubleshooting', methods=['GET'])
@login_required
@permission_required('manage_system') # Assuming same permission as backup/restore
def serve_troubleshooting_page():
    current_app.logger.info(f"User {current_user.username} accessed System Troubleshooting page.")
    return render_template('admin_troubleshooting.html')

@admin_ui_bp.route('/booking_settings', methods=['GET'])
@login_required
@permission_required('manage_system')
def serve_booking_settings_page():
    current_app.logger.info(f"User {current_user.username} accessed Booking Settings page.")
    settings = BookingSettings.query.first()
    if not settings:
        # Create a default instance if no settings exist in DB, but don't save yet
        settings = BookingSettings(
            allow_past_bookings=False,
            max_booking_days_in_future=30, # Default to 30 days
            allow_multiple_resources_same_time=False,
            max_bookings_per_user=None,
            enable_check_in_out=False
        )
    return render_template('admin_booking_settings.html', settings=settings)

@admin_ui_bp.route('/booking_settings/update', methods=['POST'])
@login_required
@permission_required('manage_system')
def update_booking_settings():
    current_app.logger.info(f"User {current_user.username} attempting to update Booking Settings.")
    settings = BookingSettings.query.first()
    if not settings:
        settings = BookingSettings()
        db.session.add(settings)

    try:
        settings.allow_past_bookings = request.form.get('allow_past_bookings') == 'on'

        max_days_future_str = request.form.get('max_booking_days_in_future')
        if max_days_future_str and max_days_future_str.strip():
            settings.max_booking_days_in_future = int(max_days_future_str)
        else:
            settings.max_booking_days_in_future = None

        settings.allow_multiple_resources_same_time = request.form.get('allow_multiple_resources_same_time') == 'on'

        max_bookings_user_str = request.form.get('max_bookings_per_user')
        if max_bookings_user_str and max_bookings_user_str.strip():
            settings.max_bookings_per_user = int(max_bookings_user_str)
        else:
            settings.max_bookings_per_user = None

        settings.enable_check_in_out = request.form.get('enable_check_in_out') == 'on'

        # New settings for check-in window
        check_in_minutes_before_str = request.form.get('check_in_minutes_before', '15')
        settings.check_in_minutes_before = int(check_in_minutes_before_str) if check_in_minutes_before_str.strip() else 15

        check_in_minutes_after_str = request.form.get('check_in_minutes_after', '15')
        settings.check_in_minutes_after = int(check_in_minutes_after_str) if check_in_minutes_after_str.strip() else 15

        if settings.check_in_minutes_before < 0 or settings.check_in_minutes_after < 0:
            db.session.rollback()
            flash(_('Check-in window minutes cannot be negative.'), 'danger')
            return redirect(url_for('admin_ui.serve_booking_settings_page'))

        # Handle past_booking_time_adjustment_hours
        if 'past_booking_time_adjustment_hours' in request.form:
            past_booking_adjustment_str = request.form['past_booking_time_adjustment_hours']
            if past_booking_adjustment_str.strip() == "": # Submitted but empty
                settings.past_booking_time_adjustment_hours = 0
            else:
                try:
                    settings.past_booking_time_adjustment_hours = int(past_booking_adjustment_str)
                except ValueError:
                    db.session.rollback()
                    flash(_('Invalid input for "Past booking time adjustment". Please enter a valid integer.'), 'danger')
                    return redirect(url_for('admin_ui.serve_booking_settings_page'))
        # If 'past_booking_time_adjustment_hours' is not in request.form (e.g., field was disabled),
        # do nothing, thereby preserving the existing value in settings.

        # New Global PIN Settings
        settings.pin_auto_generation_enabled = request.form.get('pin_auto_generation_enabled') == 'on'

        pin_length_str = request.form.get('pin_length', '6') # Default to '6' if not provided
        try:
            pin_length_val = int(pin_length_str) if pin_length_str.strip() else 6 # Default if empty string
            if not (4 <= pin_length_val <= 32):
                # This error will be caught by the broader ValueError below if not specific enough,
                # but better to raise it to be caught by specific logic if added.
                # For now, relying on the general ValueError flash message.
                raise ValueError("PIN length must be between 4 and 32.")
            settings.pin_length = pin_length_val
        except ValueError as ve: # Catch specific error for pin_length
            db.session.rollback()
            # Using f-string for error message as _() might not be appropriate for dynamic parts like str(ve)
            flash(f'{_("Invalid PIN length")}: {str(ve)}', 'danger')
            return redirect(url_for('admin_ui.serve_booking_settings_page'))

        settings.pin_allow_manual_override = request.form.get('pin_allow_manual_override') == 'on'
        settings.resource_checkin_url_requires_login = request.form.get('resource_checkin_url_requires_login') == 'on'
        settings.allow_check_in_without_pin = request.form.get('allow_check_in_without_pin') == 'on'

        # Auto Check-out Settings
        settings.enable_auto_checkout = request.form.get('enable_auto_checkout') == 'on'
        auto_checkout_delay_hours_str = request.form.get('auto_checkout_delay_hours', '1')
        try:
            auto_checkout_delay_hours_val = int(auto_checkout_delay_hours_str) if auto_checkout_delay_hours_str.strip() else 1
            if auto_checkout_delay_hours_val < 1:
                raise ValueError("Auto Check-out Delay must be at least 1 hour.")
            settings.auto_checkout_delay_hours = auto_checkout_delay_hours_val
        except ValueError as ve_auto_checkout:
            db.session.rollback()
            flash(f'{_("Invalid Auto Check-out Delay")}: {str(ve_auto_checkout)}', 'danger')
            return redirect(url_for('admin_ui.serve_booking_settings_page'))

        # Auto-release if not checked in minutes
        auto_release_str = request.form.get('auto_release_if_not_checked_in_minutes')
        if not auto_release_str or auto_release_str.strip() == "" or auto_release_str.strip() == "0":
            settings.auto_release_if_not_checked_in_minutes = None
        else:
            try:
                auto_release_val = int(auto_release_str)
                if auto_release_val < 0:
                    db.session.rollback()
                    flash(_('Auto-release minutes must be a non-negative integer.'), 'danger')
                    return redirect(url_for('admin_ui.serve_booking_settings_page'))
                settings.auto_release_if_not_checked_in_minutes = auto_release_val
            except ValueError:
                db.session.rollback()
                flash(_('Invalid input for Auto-release minutes. Please enter a whole number.'), 'danger')
                return redirect(url_for('admin_ui.serve_booking_settings_page'))

        db.session.commit()
        # Log changed settings
        changed_settings_log = (
            f"allow_past_bookings={settings.allow_past_bookings}, "
            f"max_booking_days_in_future={settings.max_booking_days_in_future}, "
            f"allow_multiple_resources_same_time={settings.allow_multiple_resources_same_time}, "
            f"max_bookings_per_user={settings.max_bookings_per_user}, "
            f"enable_check_in_out={settings.enable_check_in_out}, "
            f"check_in_minutes_before={settings.check_in_minutes_before}, "
            f"check_in_minutes_after={settings.check_in_minutes_after}, "
            f"past_booking_time_adjustment_hours={settings.past_booking_time_adjustment_hours}, "
            f"pin_auto_generation_enabled={settings.pin_auto_generation_enabled}, "
            f"pin_length={settings.pin_length}, "
            f"pin_allow_manual_override={settings.pin_allow_manual_override}, "
            f"resource_checkin_url_requires_login={settings.resource_checkin_url_requires_login}, "
            f"allow_check_in_without_pin={settings.allow_check_in_without_pin}, "
            f"enable_auto_checkout={settings.enable_auto_checkout}, "
            f"auto_checkout_delay_hours={settings.auto_checkout_delay_hours}, "
            f"auto_release_if_not_checked_in_minutes={settings.auto_release_if_not_checked_in_minutes}"
        )
        # Assuming add_audit_log is available and imported
        # from utils import add_audit_log # Ensure this import is at the top of the file
        from utils import add_audit_log # Added here for clarity, ensure it's at the top
        add_audit_log(action="UPDATE_BOOKING_SETTINGS", details=f"Booking settings updated by {current_user.username}. New values: {changed_settings_log}")

        flash(_('Booking settings updated successfully.'), 'success')
    except ValueError:
        db.session.rollback()
        flash(_('Invalid input for numeric field. Please enter a valid number or leave it empty.'), 'danger')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating booking settings: {e}", exc_info=True)
        flash(_('An unexpected error occurred while updating booking settings.'), 'danger')

    return redirect(url_for('admin_ui.serve_booking_settings_page'))

@admin_ui_bp.route('/analytics/') # Merged from analytics_bp
@login_required
@permission_required('view_analytics')
def analytics_dashboard():
    current_app.logger.info(f"User {current_user.username} accessed analytics dashboard.")
    return render_template('analytics.html')

@admin_ui_bp.route('/system-settings', methods=['GET', 'POST'])
@login_required
@permission_required('manage_system_settings') # Or 'manage_system' if 'manage_system_settings' is not defined
def system_settings_page():
    settings = BookingSettings.query.first()
    if not settings:
        settings = BookingSettings(global_time_offset_hours=0)
        db.session.add(settings)
        # Commit immediately if it's new to ensure it's in DB for GET request display
        try:
            db.session.commit()
        except Exception as e:
            current_app.logger.error(f"Error creating default BookingSettings: {e}")
            db.session.rollback()
            flash(_('Error initializing system settings. Please try again.'), 'danger')
            # Fallback to a temporary object if DB commit fails for the GET request
            settings = BookingSettings(global_time_offset_hours=0) # Temporary for display

    if request.method == 'POST':
        try:
            new_offset_str = request.form.get('global_time_offset_hours')
            if new_offset_str is None or new_offset_str.strip() == "":
                flash(_('Time offset value must be provided and cannot be empty.'), 'danger')
            else:
                new_offset = int(new_offset_str)
                if not (-24 < new_offset < 24): # Basic sanity check
                    flash(_('Time offset must be a reasonable integer, e.g., between -23 and +23 hours.'), 'danger')
                else:
                    settings.global_time_offset_hours = new_offset
                    db.session.commit()
                    flash(_('Global time offset updated successfully.'), 'success')
                    add_audit_log(action="UPDATE_TIME_OFFSET", details=f"Global time offset set to {new_offset} hours by {current_user.username}.")
        except ValueError:
            db.session.rollback()
            flash(_('Invalid input for time offset. Please enter a whole number (integer).'), 'danger')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating time offset: {e}", exc_info=True)
            flash(_('An error occurred while updating the time offset. Please check logs.'), 'danger')
        return redirect(url_for('admin_ui.system_settings_page'))

    # For GET request, prepare display times
    current_offset_hours = settings.global_time_offset_hours
    if current_offset_hours is None: # Should have a default, but safeguard
        current_offset_hours = 0

    # Use timezone.utc for explicit UTC time
    utc_now = datetime.now(timezone.utc)
    # Calculate effective time by adding offset
    effective_time = utc_now + timedelta(hours=current_offset_hours)

    return render_template('admin/system_settings.html',
                           global_time_offset_hours=current_offset_hours, # Pass as global_time_offset_hours for consistency
                           current_utc_time_str=utc_now.strftime('%Y-%m-%d %H:%M:%S %Z'),
                           effective_operational_time_str=effective_time.strftime('%Y-%m-%d %H:%M:%S %Z (Effective)'))

@admin_ui_bp.route('/analytics/data') # New route for analytics data
@login_required
@permission_required('view_analytics')
def analytics_bookings_data():
    try:
        current_app.logger.info(f"User {current_user.username} requested analytics bookings data.")

        # Existing functionality: Daily counts per resource for the last 30 days
        thirty_days_ago = datetime.utcnow().date() - timedelta(days=30)
        daily_counts_query = db.session.query(
            Resource.name.label("resource_name"),
            cast(func.date(Booking.start_time), db.Date).label('booking_date'), # Ensure booking_date is a Date object
            func.count(Booking.id).label('booking_count')
        ).join(Resource, Booking.resource_id == Resource.id) \
        .filter(cast(func.date(Booking.start_time), db.Date) >= thirty_days_ago) \
        .group_by(Resource.name, func.date(Booking.start_time)) \
        .order_by(Resource.name, func.date(Booking.start_time)) \
        .all()

        daily_counts_data = {}
        for row in daily_counts_query:
            resource_name = row.resource_name
            # row.booking_date should now be a date object due to cast in query
            booking_date_str = row.booking_date.strftime('%Y-%m-%d')
            if resource_name not in daily_counts_data:
                daily_counts_data[resource_name] = []
            daily_counts_data[resource_name].append({
                "date": booking_date_str,
                "count": row.booking_count
            })

        # New aggregations
        # Base query for new aggregations
        base_query = db.session.query(
            Booking.id,
            Booking.start_time,
            Booking.end_time,
            Resource.name.label('resource_name'),
            Resource.capacity.label('resource_capacity'),
            Resource.equipment.label('resource_equipment'),
            Resource.tags.label('resource_tags'),
            Resource.status.label('resource_status'),
            FloorMap.location.label('floor_location'),
            FloorMap.floor.label('floor_number'),
            User.username.label('user_username'),
            # Time attributes
            extract('hour', Booking.start_time).label('booking_hour'),
            extract('dow', Booking.start_time).label('booking_day_of_week'), # Sunday=0, Saturday=6
            extract('month', Booking.start_time).label('booking_month')
        ).join(Resource, Booking.resource_id == Resource.id) \
         .join(User, Booking.user_name == User.username) \
         .outerjoin(FloorMap, Resource.floor_map_id == FloorMap.id) # Use outerjoin in case a resource is not mapped

        all_bookings_for_aggregation = base_query.all()

        aggregated_data = {
            "by_resource_attributes": {},
            "by_floor_attributes": {},
            "by_user": {},
            "by_time_attributes": {
                "hour_of_day": {},
                "day_of_week": {},
                "month": {}
            }
        }

        for booking in all_bookings_for_aggregation:
            duration_seconds = (booking.end_time - booking.start_time).total_seconds()
            duration_hours = duration_seconds / 3600

            # --- Aggregation by Resource Attributes ---
            # By resource name
            res_name_key = booking.resource_name
            if res_name_key not in aggregated_data["by_resource_attributes"]:
                aggregated_data["by_resource_attributes"][res_name_key] = {'count': 0, 'total_duration_hours': 0}
            aggregated_data["by_resource_attributes"][res_name_key]['count'] += 1
            aggregated_data["by_resource_attributes"][res_name_key]['total_duration_hours'] += duration_hours

            # You can add more detailed breakdowns if needed, e.g., by equipment, capacity, etc.
            # For simplicity, this example primarily groups by resource name.
            # Consider if equipment, tags should be sub-keys or if each unique combination is a primary key.

            # --- Aggregation by FloorMap Attributes ---
            if booking.floor_location and booking.floor_number: # Ensure map data exists
                floor_key = f"Floor: {booking.floor_number}, Location: {booking.floor_location}"
                if floor_key not in aggregated_data["by_floor_attributes"]:
                    aggregated_data["by_floor_attributes"][floor_key] = {'count': 0, 'total_duration_hours': 0}
                aggregated_data["by_floor_attributes"][floor_key]['count'] += 1
                aggregated_data["by_floor_attributes"][floor_key]['total_duration_hours'] += duration_hours

            # --- Aggregation by User ---
            user_key = booking.user_username
            if user_key not in aggregated_data["by_user"]:
                aggregated_data["by_user"][user_key] = {'count': 0, 'total_duration_hours': 0}
            aggregated_data["by_user"][user_key]['count'] += 1
            aggregated_data["by_user"][user_key]['total_duration_hours'] += duration_hours

            # --- Aggregation by Time Attributes ---
            # Hour of Day
            hour_key = str(booking.booking_hour)
            if hour_key not in aggregated_data["by_time_attributes"]["hour_of_day"]:
                aggregated_data["by_time_attributes"]["hour_of_day"][hour_key] = {'count': 0, 'total_duration_hours': 0}
            aggregated_data["by_time_attributes"]["hour_of_day"][hour_key]['count'] += 1
            aggregated_data["by_time_attributes"]["hour_of_day"][hour_key]['total_duration_hours'] += duration_hours

            # Day of Week (0=Sunday, 1=Monday, ..., 6=Saturday for PostgreSQL's DOW)
            # Adjust if your DB uses a different convention or if you want specific day names
            dow_map = {0: "Sunday", 1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday"}
            dow_key = dow_map.get(booking.booking_day_of_week, "Unknown")
            if dow_key not in aggregated_data["by_time_attributes"]["day_of_week"]:
                aggregated_data["by_time_attributes"]["day_of_week"][dow_key] = {'count': 0, 'total_duration_hours': 0}
            aggregated_data["by_time_attributes"]["day_of_week"][dow_key]['count'] += 1
            aggregated_data["by_time_attributes"]["day_of_week"][dow_key]['total_duration_hours'] += duration_hours

            # Month
            month_map = {
                1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
                7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December"
            }
            month_key = month_map.get(booking.booking_month, "Unknown")
            if month_key not in aggregated_data["by_time_attributes"]["month"]:
                aggregated_data["by_time_attributes"]["month"][month_key] = {'count': 0, 'total_duration_hours': 0}
            aggregated_data["by_time_attributes"]["month"][month_key]['count'] += 1
            aggregated_data["by_time_attributes"]["month"][month_key]['total_duration_hours'] += duration_hours

        # Combine existing daily counts with new aggregated data
        final_response = {
            "daily_counts_last_30_days": daily_counts_data,
            "aggregations": aggregated_data
        }

        current_app.logger.info(f"Successfully processed analytics data. Daily counts resources: {len(daily_counts_data)}, Aggregation items processed: {len(all_bookings_for_aggregation)}")
        return jsonify(final_response)

    except Exception as e:
        current_app.logger.error(f"Error generating analytics bookings data: {e}", exc_info=True)
        return jsonify({"error": "Could not process analytics data"}), 500

# Function to register this blueprint in the app factory
def init_admin_ui_routes(app):
    app.register_blueprint(admin_ui_bp)

@admin_ui_bp.route('/export_bookings_csv')
@login_required
@permission_required('manage_system')
def export_bookings_csv():
    current_app.logger.info(f"User {current_user.username} initiated CSV export of bookings.")
    try:
        bookings = Booking.query.all()

        csv_output = io.StringIO()
        csv_writer = csv.writer(csv_output)

        # Write header row
        header = ['id', 'resource_id', 'user_name', 'start_time', 'end_time', 'title', 'status']
        csv_writer.writerow(header)

        for booking in bookings:
            row = [
                booking.id,
                booking.resource_id,
                booking.user_name,
                booking.start_time.strftime('%Y-%m-%d %H:%M:%S') if booking.start_time else '',
                booking.end_time.strftime('%Y-%m-%d %H:%M:%S') if booking.end_time else '',
                booking.title,
                booking.status
            ]
            csv_writer.writerow(row)

        csv_output.seek(0)

        return Response(
            csv_output,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=bookings_export.csv"}
        )
    except Exception as e:
        current_app.logger.error(f"Error exporting bookings to CSV: {e}", exc_info=True)
        flash(_('An error occurred while exporting bookings to CSV. Please check the logs.'), 'danger')
        return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

@admin_ui_bp.route('/import_bookings_csv', methods=['POST'])
@login_required
@permission_required('manage_system')
def import_bookings_csv():
    current_app.logger.info(f"User {current_user.username} initiated CSV import of bookings.")
    if 'file' not in request.files:
        flash(_('No file part in the request.'), 'danger')
        return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

    file = request.files['file']
    if file.filename == '':
        flash(_('No selected file.'), 'danger')
        return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

    if file and file.filename.endswith('.csv'):
        filename = secure_filename(file.filename)
        current_app.logger.info(f"Processing uploaded CSV file: {filename}")
        try:
            # Read the file content as a string
            file_content = file.stream.read().decode("UTF-8")
            csv_file = io.StringIO(file_content)
            csv_reader = csv.reader(csv_file)

            header = next(csv_reader, None) # Skip header row
            if not header or header != ['id', 'resource_id', 'user_name', 'start_time', 'end_time', 'title', 'status']:
                flash(_('Invalid CSV header. Please ensure the header matches the export format.'), 'danger')
                return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

            bookings_to_add = []
            for row_number, row in enumerate(csv_reader, start=2): # Start row count from 2 (after header)
                try:
                    # Basic validation: ensure correct number of columns
                    if len(row) != 7:
                        flash(_(f"Skipping row {row_number}: Incorrect number of columns. Expected 7, got {len(row)}."), 'warning')
                        current_app.logger.warning(f"CSV Import: Skipping row {row_number} due to incorrect column count. Data: {row}")
                        continue

                    resource_id_str = row[1]
                    user_name = row[2]
                    start_time_str = row[3]
                    end_time_str = row[4]
                    title = row[5] if row[5] else None # Handle optional title
                    status = row[6]

                    # Data validation and type conversion
                    try:
                        resource_id = int(resource_id_str)
                    except ValueError:
                        flash(_(f"Skipping row {row_number}: Invalid resource_id '{resource_id_str}'. Must be an integer."), 'warning')
                        current_app.logger.warning(f"CSV Import: Skipping row {row_number} due to invalid resource_id. Data: {row}")
                        continue

                    try:
                        start_time = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S') if start_time_str else None
                        end_time = datetime.strptime(end_time_str, '%Y-%m-%d %H:%M:%S') if end_time_str else None
                    except ValueError as ve:
                        flash(_(f"Skipping row {row_number}: Invalid date format for start_time or end_time. Expected 'YYYY-MM-DD HH:MM:SS'. Error: {ve}"), 'warning')
                        current_app.logger.warning(f"CSV Import: Skipping row {row_number} due to date parsing error. Data: {row}. Error: {ve}")
                        continue

                    # Optional: Add more validation (e.g., check if user_name and resource_id exist)
                    # For now, we assume they exist or allow DB constraints to handle it.

                    new_booking = Booking(
                        resource_id=resource_id,
                        user_name=user_name,
                        start_time=start_time,
                        end_time=end_time,
                        title=title,
                        status=status
                        # id is auto-generated, so we don't set it from the CSV's first column.
                        # If you need to preserve IDs, you'd need to handle potential conflicts.
                    )
                    bookings_to_add.append(new_booking)
                except Exception as e_row:
                    flash(_(f"Error processing row {row_number}: {str(e_row)}. Skipping this row."), 'warning')
                    current_app.logger.error(f"CSV Import: Error processing row {row_number}. Data: {row}. Error: {e_row}", exc_info=True)
                    continue # Skip to the next row

            if bookings_to_add:
                db.session.add_all(bookings_to_add)
                db.session.commit()
                flash(_(f'Successfully imported {len(bookings_to_add)} bookings from {filename}.'), 'success')
                current_app.logger.info(f"Successfully imported {len(bookings_to_add)} bookings from {filename}.")
            else:
                flash(_('No new bookings were imported. The file might have been empty or all rows had errors.'), 'info')
                current_app.logger.info(f"No new bookings imported from {filename}. File might be empty or all rows had errors.")

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error importing bookings from CSV file {filename}: {e}", exc_info=True)
            flash(_(f'An error occurred while importing bookings from {filename}. Error: {str(e)}'), 'danger')
    else:
        flash(_('Invalid file type. Please upload a CSV file.'), 'danger')

    return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

@admin_ui_bp.route('/clear_all_bookings', methods=['POST'])
@login_required
@permission_required('manage_system')
def clear_all_bookings_data():
    current_app.logger.info(f"User {current_user.username} initiated clearing of all booking data.")
    try:
        num_deleted = db.session.query(Booking).delete()
        db.session.commit()
        current_app.logger.info(f"User {current_user.username} successfully cleared all {num_deleted} booking(s).")
        flash(_('Successfully cleared all %(num_deleted)s booking(s).', num_deleted=num_deleted), 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error clearing all bookings by user {current_user.username}: {str(e)}", exc_info=True)
        flash(_('Error clearing booking data. Please check system logs for details.'), 'danger')

    return redirect(url_for('admin_ui.serve_backup_booking_data_page'))
