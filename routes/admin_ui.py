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
from scheduler_tasks import run_scheduled_booking_csv_backup, run_scheduled_incremental_booking_backup # Added run_scheduled_incremental_booking_backup
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

        all_booking_rows = bookings_query.all()

        upcoming_bookings_processed = []
        past_bookings_processed = []
        now_utc = datetime.now(timezone.utc)

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
                'start_time': aware_start_time,
                'end_time': aware_end_time,
                'status': row.status,
                'user_username': row.user_username,
                'resource_name': row.resource_name,
                'admin_deleted_message': row.admin_deleted_message
            }

            if aware_start_time is not None and aware_start_time >= now_utc:
                upcoming_bookings_processed.append(booking_data)
            elif aware_start_time is not None:
                past_bookings_processed.append(booking_data)

        upcoming_bookings_processed.sort(key=lambda b: b['start_time'])
        past_bookings_processed.sort(key=lambda b: b['start_time'], reverse=True)

        comprehensive_statuses = [
            'pending', 'approved', 'rejected', 'cancelled', 'checked_in', 'completed',
            'cancelled_by_user', 'cancelled_by_admin', 'cancelled_admin_acknowledged',
            'system_cancelled_no_checkin', 'confirmed', 'no_show', 'on_hold', 'under_review'
        ]
        comprehensive_statuses = sorted(list(set(s for s in comprehensive_statuses if s and s.strip())))

        return render_template("admin_bookings.html",
                               upcoming_bookings=upcoming_bookings_processed,
                               past_bookings=past_bookings_processed,
                               all_statuses=comprehensive_statuses,
                               current_status_filter=status_filter,
                               all_users=all_users,
                               current_user_filter=user_filter,
                               current_date_filter=date_filter_str,
                               new_sorting_active=True)
    except Exception as e:
        logger.error(f"Error fetching and sorting bookings for admin page: {e}", exc_info=True)
        comprehensive_statuses = [
            'pending', 'approved', 'rejected', 'cancelled', 'checked_in', 'completed',
            'cancelled_by_user', 'cancelled_by_admin', 'cancelled_admin_acknowledged',
            'system_cancelled_no_checkin', 'confirmed', 'no_show', 'on_hold', 'under_review'
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
    full_backup_settings.setdefault('interval_value', 60)
    full_backup_settings.setdefault('interval_unit', 'minutes')
    full_backup_settings.setdefault('schedule_type', 'daily')
    full_backup_settings.setdefault('time_of_day', '02:00')
    full_backup_settings.setdefault('day_of_week', None if full_backup_settings['schedule_type'] != 'weekly' else 0)

    time_offset_value = 0
    try:
        booking_settings = BookingSettings.query.first()
        if booking_settings and booking_settings.global_time_offset_hours is not None:
            time_offset_value = booking_settings.global_time_offset_hours
        elif not booking_settings:
            current_app.logger.info("No BookingSettings found for system page, defaulting offset to 0. Consider creating a default record.")
        else:
            current_app.logger.warning("BookingSettings.global_time_offset_hours is None for system page, defaulting offset to 0.")
    except Exception as e:
        current_app.logger.error(f"Error fetching BookingSettings for system page: {e}", exc_info=True)

    return render_template('admin/backup_system.html',
                           full_backup_settings=full_backup_settings,
                           global_time_offset_hours=time_offset_value)

@admin_ui_bp.route('/backup/booking_data', methods=['GET'])
@login_required
@permission_required('manage_system')
def serve_backup_booking_data_page():
    current_app.logger.info(f"User {current_user.username} accessed Booking Data Management page.")
    scheduler_settings = load_scheduler_settings()

    DEFAULT_BOOKING_DATA_PROTECTION_SCHEDULE = {'is_enabled': False, 'interval_minutes': 1440}
    booking_data_protection_schedule = scheduler_settings.get(
        'booking_data_protection_schedule',
        DEFAULT_BOOKING_DATA_PROTECTION_SCHEDULE.copy()
    )
    booking_data_protection_schedule.setdefault('is_enabled', DEFAULT_BOOKING_DATA_PROTECTION_SCHEDULE['is_enabled'])
    booking_data_protection_schedule.setdefault('interval_minutes', DEFAULT_BOOKING_DATA_PROTECTION_SCHEDULE['interval_minutes'])

    all_booking_csv_files = list_available_booking_csv_backups() if list_available_booking_csv_backups else []
    page = request.args.get('page', 1, type=int)
    per_page = 10
    total_items = len(all_booking_csv_files)
    total_pages = (total_items + per_page - 1) // per_page if per_page > 0 else 0
    if total_pages == 0 and total_items > 0 : total_pages = 1
    if page > total_pages and total_pages > 0: page = total_pages
    if page < 1: page = 1

    start_index = (page - 1) * per_page
    end_index = start_index + per_page
    paginated_booking_csv_backups = all_booking_csv_files[start_index:end_index]
    has_prev = page > 1
    has_next = page < total_pages

    time_offset_value = 0
    try:
        booking_settings = BookingSettings.query.first()
        if booking_settings and booking_settings.global_time_offset_hours is not None:
            time_offset_value = booking_settings.global_time_offset_hours
        elif not booking_settings:
            current_app.logger.info("No BookingSettings found for booking data page, defaulting offset to 0. Consider creating a default record.")
        else:
            current_app.logger.warning("BookingSettings.global_time_offset_hours is None for booking data page, defaulting offset to 0.")
    except Exception as e:
        current_app.logger.error(f"Error fetching BookingSettings for booking data page: {e}", exc_info=True)

    return render_template('admin/backup_booking_data.html',
                           booking_data_protection_schedule=booking_data_protection_schedule,
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

    global_time_offset_hours = booking_settings.global_time_offset_hours if booking_settings else 0
    if global_time_offset_hours is None:
        global_time_offset_hours = 0
        current_app.logger.warning("global_time_offset_hours was None, defaulted to 0.")

    return render_template('admin/backup_settings.html',
                           auto_restore_booking_records_on_startup=auto_restore_booking_records_on_startup,
                           global_time_offset_hours=global_time_offset_hours)

# LEGACY - Azure CSV Restore Route - Body fully commented out.
# @admin_ui_bp.route('/admin/restore_booking_csv/<timestamp_str>', methods=['POST'])
# @login_required
# @permission_required('manage_system')
# def restore_booking_csv_route(timestamp_str):
    # # current_app.logger.info(f"User {current_user.username} initiated restore for booking CSV backup: {timestamp_str}")
    # # task_id = uuid.uuid4().hex
    # #
    # # # Use current_app._get_current_object() to pass the actual app instance
    # # # Pass socketio instance if available and configured, else None
    # # socketio_instance = None
    # # if hasattr(current_app, 'extensions') and 'socketio' in current_app.extensions:
    # #     socketio_instance = current_app.extensions['socketio']
    # # elif 'socketio' in globals() and socketio: # Check imported socketio from extensions
    # #     socketio_instance = socketio
    # #
    # # summary = restore_bookings_from_csv_backup(
    # #     current_app._get_current_object(),
    # #     timestamp_str,
    # #     socketio_instance=socketio_instance,
    # #     task_id=task_id # This task_id was also not defined as it was part of the commented function
    # # )
    # #
    # # if summary['status'] == 'completed_successfully' or (summary['status'] == 'completed_with_errors' and not summary.get('errors')):
    # #     flash_msg = f"Booking CSV restore for {timestamp_str} completed. Processed: {summary.get('processed',0)}, Created: {summary.get('created',0)}, Skipped Duplicates: {summary.get('skipped_duplicates',0)}."
    # #     if summary.get('errors'):
    # #          flash_msg += f" Warnings: {'; '.join(summary['errors'])}"
    # #     flash(flash_msg, 'success')
    # # elif summary['status'] == 'completed_with_errors' and summary.get('errors'):
    # #     error_details = '; '.join(summary['errors'])
    # #     flash(f"Booking CSV restore for {timestamp_str} completed with errors. Errors: {error_details}. Processed: {summary.get('processed',0)}, Created: {summary.get('created',0)}, Skipped: {summary.get('skipped_duplicates',0)}.", 'danger')
    # # else: # 'failed' or any other status
    # #     error_details = '; '.join(summary.get('errors', ['Unknown error']))
    # #     flash(f"Booking CSV restore for {timestamp_str} failed. Status: {summary.get('status','unknown')}. Message: {summary.get('message','N/A')}. Details: {error_details}", 'danger')
    # #
    # # # return redirect(url_for('admin_ui.serve_backup_booking_data_page')) # Redirect to the booking data tab

# LEGACY - Azure CSV Manual Backup Route - Body fully commented out.
# @admin_ui_bp.route('/admin/manual_backup_bookings_csv', methods=['POST'])
# @login_required
# @permission_required('manage_system')
# def manual_backup_bookings_csv_route():
    # # task_id = uuid.uuid4().hex # task_id was defined here.
    # # socketio_instance = None
    # # if hasattr(current_app, 'extensions') and 'socketio' in current_app.extensions:
    # #     socketio_instance = current_app.extensions['socketio']
    # # elif 'socketio' in globals() and socketio:
    # #     socketio_instance = socketio
    #
    # # app_instance = current_app._get_current_object()
    #
    # # range_type = request.form.get('backup_range_type', 'all')
    # # start_date_dt = None
    # # end_date_dt = None
    # # range_label = range_type
    #
    # # utcnow = datetime.utcnow()
    # # if range_type != "all":
    # #     end_date_dt = datetime(utcnow.year, utcnow.month, utcnow.day) + timedelta(days=1)
    #
    # # if range_type == "1day":
    # #     start_date_dt = end_date_dt - timedelta(days=1)
    # # elif range_type == "3days":
    # #     start_date_dt = end_date_dt - timedelta(days=3)
    # # elif range_type == "7days":
    # #     start_date_dt = end_date_dt - timedelta(days=7)
    # # elif range_type == "all":
    # #     start_date_dt = None
    # #     end_date_dt = None
    # #     range_label = "all"
    #
    # # log_detail = f"range: {range_label}"
    # # if start_date_dt: log_detail += f", from: {start_date_dt.strftime('%Y-%m-%d')}"
    # # if end_date_dt: log_detail += f", to: {end_date_dt.strftime('%Y-%m-%d')}"
    #
    # # app_instance.logger.info(f"Manual booking CSV backup ({log_detail}) triggered by user {current_user.username if current_user else 'Unknown User'} with task ID {task_id}.")
    #
    # # try:
    # #     success = backup_bookings_csv(
    # #         app=app_instance,
    # #         socketio_instance=socketio_instance,
    # #         task_id=task_id,
    # #         start_date_dt=start_date_dt,
    # #         end_date_dt=end_date_dt,
    # #         range_label=range_label
    # #     )
    # #     if success:
    # #         flash(_('Manual booking CSV backup for range "%(range)s" initiated successfully. Check logs or SocketIO messages for progress/completion.') % {'range': range_label}, 'success')
    # #     else:
    # #         flash(_('Manual booking CSV backup for range "%(range)s" failed to complete successfully. Please check server logs.') % {'range': range_label}, 'warning')
    # # except Exception as e:
    # #     app_instance.logger.error(f"Exception during manual booking CSV backup (range: {range_label}) initiation by user {current_user.username if current_user else 'Unknown User'}: {str(e)}", exc_info=True)
    # #     flash(_('An unexpected error occurred while starting the manual booking CSV backup for range "%(range)s". Check server logs.') % {'range': range_label}, 'danger')
    #
    # # return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

# LEGACY - Azure CSV Delete Route - Body fully commented out.
# @admin_ui_bp.route('/admin/delete_booking_csv/<timestamp_str>', methods=['POST'])
# @login_required
# @permission_required('manage_system')
# def delete_booking_csv_backup_route(timestamp_str):
    # # task_id = uuid.uuid4().hex # task_id was defined here
    # # socketio_instance = None
    # # if hasattr(current_app, 'extensions') and 'socketio' in current_app.extensions:
    # #     socketio_instance = current_app.extensions['socketio']
    # # elif 'socketio' in globals() and socketio:
    # #     socketio_instance = socketio
    #
    # # app_instance = current_app._get_current_object()
    # # app_instance.logger.info(f"Deletion of booking CSV backup {timestamp_str} triggered by user {current_user.username if current_user else 'Unknown User'} with task ID {task_id}.")
    #
    # # try:
    # #     success = delete_booking_csv_backup(timestamp_str, socketio_instance=socketio_instance, task_id=task_id)
    # #     if success:
    # #         flash(_('Booking CSV backup for %(timestamp)s successfully deleted (or was not found).') % {'timestamp': timestamp_str}, 'success')
    # #     else:
    # #         flash(_('Failed to delete booking CSV backup for %(timestamp)s. Check server logs.') % {'timestamp': timestamp_str}, 'danger')
    # # except Exception as e:
    # #     app_instance.logger.error(f"Exception during booking CSV backup deletion for {timestamp_str} by user {current_user.username if current_user else 'Unknown User'}: {str(e)}", exc_info=True)
    # #     flash(_('An unexpected error occurred while deleting the booking CSV backup for %(timestamp)s. Check server logs.') % {'timestamp': timestamp_str}, 'danger')
    #
    # # return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

# LEGACY - Azure CSV Schedule Save Route - Body fully commented out.
# @admin_ui_bp.route('/save_booking_csv_schedule', methods=['POST'])
# @login_required
# @permission_required('manage_system')
# def save_booking_csv_schedule_settings():
    # # current_app.logger.info(f"User {current_user.username} attempting to save Booking CSV Backup schedule settings.")
    # # booking_csv_schedule_config_file = os.path.join(current_app.config['DATA_DIR'], 'booking_csv_schedule.json')
    # # try:
    # #     is_enabled = request.form.get('booking_csv_schedule_enabled') == 'true'
    # #     interval_value_str = request.form.get('booking_csv_schedule_interval_value', '24')
    # #     interval_unit = request.form.get('booking_csv_schedule_interval_unit', 'hours')
    # #     range_type = request.form.get('booking_csv_schedule_range_type', 'all')
    # #     try:
    # #         interval_value = int(interval_value_str)
    # #         if interval_value <= 0:
    # #             raise ValueError(_("Interval must be positive."))
    # #     except ValueError as ve:
    # #         flash(str(ve) or _('Invalid interval value. Please enter a positive integer.'), 'danger')
    # #         return redirect(url_for('admin_ui.serve_backup_booking_data_page'))
    # #     allowed_units = ['minutes', 'hours', 'days']
    # #     if interval_unit not in allowed_units:
    # #         flash(_('Invalid interval unit specified.'), 'danger')
    # #         return redirect(url_for('admin_ui.serve_backup_booking_data_page'))
    # #     allowed_range_types = ['all', '1day', '3days', '7days']
    # #     if range_type not in allowed_range_types:
    # #         flash(_('Invalid backup data range type specified.'), 'danger')
    # #         return redirect(url_for('admin_ui.serve_backup_booking_data_page'))
    # #     schedule_settings = {
    # #         'enabled': is_enabled,
    # #         'interval_value': interval_value,
    # #         'interval_unit': interval_unit,
    # #         'range_type': range_type
    # #     }
    # #     os.makedirs(os.path.dirname(booking_csv_schedule_config_file), exist_ok=True)
    # #     with open(booking_csv_schedule_config_file, 'w') as f:
    # #         json.dump(schedule_settings, f, indent=4)
    # #     current_app.logger.info(f"Booking CSV Backup schedule settings saved to file by {current_user.username}: {schedule_settings}")
    # #     flash(_('Booking CSV backup schedule settings saved successfully.'), 'success')
    # #     current_app.config['BOOKING_CSV_SCHEDULE_SETTINGS'] = schedule_settings
    # #     current_app.logger.info(f"Updated app.config['BOOKING_CSV_SCHEDULE_SETTINGS'] to: {schedule_settings}")
    # #     scheduler = getattr(current_app, 'scheduler', None)
    # #     if scheduler and scheduler.running:
    # #         job_id = 'scheduled_booking_csv_backup_job'
    # #         try:
    # #             if scheduler.get_job(job_id):
    # #                 scheduler.remove_job(job_id)
    # #         except JobLookupError:
    # #             pass
    # #         except Exception as e_remove:
    # #             current_app.logger.error(f"Error removing existing scheduler job '{job_id}': {e_remove}", exc_info=True)
    # #             flash(_('Error removing old schedule job. New schedule might not apply until restart.'), 'warning')
    # #         if schedule_settings.get('enabled'):
    # #             job_kwargs = {interval_unit: interval_value}
    # #             try:
    # #                 scheduler.add_job(
    # #                     func=run_scheduled_booking_csv_backup,
    # #                     trigger='interval',
    # #                     id=job_id,
    # #                     **job_kwargs,
    # #                     args=[current_app._get_current_object()]
    # #                 )
    # #                 flash(_('Schedule updated. New settings will apply.'), 'info')
    # #             except Exception as e_add_job:
    # #                 current_app.logger.error(f"Failed to add/update scheduler job '{job_id}': {e_add_job}", exc_info=True)
    # #                 flash(_('Failed to apply new schedule settings to the scheduler. Please check logs.'), 'danger')
    # #         else:
    # #             flash(_('Schedule is now disabled. Job removed if it existed.'), 'info')
    # #     elif not scheduler or not scheduler.running:
    # #         flash(_('Schedule settings saved, but scheduler is not running. Changes will apply on restart.'), 'warning')
    # # except Exception as e:
    # #     current_app.logger.error(f"Error saving Booking CSV backup schedule settings by {current_user.username}: {str(e)}", exc_info=True)
    # #     flash(_('An error occurred while saving the schedule settings. Please check the logs.'), 'danger')
    # # return redirect(url_for('admin_ui.serve_backup_booking_data_page'))


@admin_ui_bp.route('/settings/schedule/full_backup', methods=['POST'])
@login_required
@permission_required('manage_system')
def save_full_backup_schedule_settings():
    current_app.logger.info(f"User {current_user.username} attempting to save Full Backup schedule settings.")
    try:
        all_settings = load_scheduler_settings()
        if 'full_backup' not in all_settings:
            from utils import DEFAULT_FULL_BACKUP_SCHEDULE
            all_settings['full_backup'] = DEFAULT_FULL_BACKUP_SCHEDULE.copy()

        is_enabled = request.form.get('full_backup_enabled') == 'true'
        schedule_type = request.form.get('full_backup_schedule_type', 'daily')

        all_settings['full_backup']['is_enabled'] = is_enabled
        all_settings['full_backup']['schedule_type'] = schedule_type

        if schedule_type == 'interval':
            interval_value_str = request.form.get('full_backup_interval_value')
            interval_unit = request.form.get('full_backup_interval_unit', 'minutes')
            try:
                interval_value = int(interval_value_str)
                if interval_value <= 0:
                    flash(_('Interval value must be a positive integer.'), 'danger')
                    return redirect(url_for('admin_ui.serve_backup_system_page'))
            except (ValueError, TypeError):
                flash(_('Invalid interval value. Please enter a positive integer.'), 'danger')
                return redirect(url_for('admin_ui.serve_backup_system_page'))
            if interval_unit not in ['minutes', 'hours']:
                flash(_('Invalid interval unit. Must be "minutes" or "hours".'), 'danger')
                return redirect(url_for('admin_ui.serve_backup_system_page'))
            all_settings['full_backup']['interval_value'] = interval_value
            all_settings['full_backup']['interval_unit'] = interval_unit
            all_settings['full_backup'].pop('time_of_day', None)
            all_settings['full_backup'].pop('day_of_week', None)
        elif schedule_type in ['daily', 'weekly']:
            time_of_day = request.form.get('full_backup_time_of_day', '02:00')
            try: datetime.strptime(time_of_day, '%H:%M')
            except ValueError:
                flash(_('Invalid time format for Time of Day. Please use HH:MM.'), 'danger')
                return redirect(url_for('admin_ui.serve_backup_system_page'))
            all_settings['full_backup']['time_of_day'] = time_of_day
            if schedule_type == 'weekly':
                day_of_week_str = request.form.get('full_backup_day_of_week')
                if day_of_week_str is not None and day_of_week_str.isdigit():
                    day_of_week = int(day_of_week_str)
                    if not (0 <= day_of_week <= 6):
                        flash(_('Invalid day of the week.'), 'danger')
                        return redirect(url_for('admin_ui.serve_backup_system_page'))
                    all_settings['full_backup']['day_of_week'] = day_of_week
                else:
                    flash(_('Day of the week is required for weekly schedule.'), 'danger')
                    return redirect(url_for('admin_ui.serve_backup_system_page'))
            else:
                all_settings['full_backup'].pop('day_of_week', None)
            all_settings['full_backup'].pop('interval_value', None)
            all_settings['full_backup'].pop('interval_unit', None)
        else:
            flash(_('Invalid schedule type specified.'), 'danger')
            return redirect(url_for('admin_ui.serve_backup_system_page'))

        save_scheduler_settings(all_settings)
        flash(_('Full backup schedule settings saved successfully.'), 'success')
        current_app.logger.info(f"Full backup schedule settings saved by {current_user.username}: {all_settings['full_backup']}")
    except Exception as e:
        current_app.logger.error(f"Error saving Full Backup schedule settings by {current_user.username}: {str(e)}", exc_info=True)
        flash(_('An error occurred while saving the full backup schedule settings. Please check the logs.'), 'danger')
    return redirect(url_for('admin_ui.serve_backup_system_page'))

# LEGACY - This route was for the old CSV schedule, now handled by booking_data_protection_schedule or removed.
# @admin_ui_bp.route('/settings/schedule/booking_csv', methods=['POST'])
# @login_required
# @permission_required('manage_system')
# def save_booking_data_schedule_settings():
#     pass

# @admin_ui_bp.route('/settings/schedule/booking_incremental_json', methods=['POST']) # Old route for incremental JSON schedule
# @login_required
# @permission_required('manage_system')
# def save_booking_incremental_json_schedule_settings():
#     pass # Commented out as this is replaced by unified schedule


@admin_ui_bp.route('/backup/booking_data_protection/schedule/save', methods=['POST'])
@login_required
@permission_required('manage_system')
def save_booking_data_protection_schedule():
    current_app.logger.info(f"User {current_user.username} attempting to save Unified Booking Data Protection schedule settings.")
    try:
        all_settings = load_scheduler_settings()
        is_enabled = request.form.get('booking_data_protection_enabled') == 'true'
        interval_minutes_str = request.form.get('booking_data_protection_interval_minutes', '1440')
        try:
            interval_minutes = int(interval_minutes_str)
            if interval_minutes < 1:
                flash(_('Interval for Unified Booking Data backup must be at least 1 minute.'), 'danger')
                return redirect(url_for('admin_ui.serve_backup_booking_data_page'))
        except ValueError:
            flash(_('Invalid interval value for Unified Booking Data backup. Please enter a number.'), 'danger')
            return redirect(url_for('admin_ui.serve_backup_booking_data_page'))
        DEFAULT_SCHEDULE = {'is_enabled': False, 'interval_minutes': 1440}
        if 'booking_data_protection_schedule' not in all_settings:
            all_settings['booking_data_protection_schedule'] = DEFAULT_SCHEDULE.copy()
        all_settings['booking_data_protection_schedule']['is_enabled'] = is_enabled
        all_settings['booking_data_protection_schedule']['interval_minutes'] = interval_minutes
        save_scheduler_settings(all_settings)
        flash(_('Unified Booking Data Protection schedule settings saved successfully.'), 'success')
        current_app.logger.info(f"Unified Booking Data Protection schedule settings saved by {current_user.username}: {all_settings['booking_data_protection_schedule']}")
        scheduler = getattr(current_app, 'scheduler', None)
        job_id = 'scheduled_booking_data_protection_job'
        if scheduler and scheduler.running:
            try:
                existing_job = scheduler.get_job(job_id)
                if existing_job:
                    scheduler.remove_job(job_id)
                    current_app.logger.info(f"Removed existing scheduler job '{job_id}' for unified booking data backups.")
            except JobLookupError:
                current_app.logger.info(f"Scheduler job '{job_id}' for unified backups not found, no need to remove.")
            except Exception as e_remove:
                current_app.logger.error(f"Error removing existing scheduler job '{job_id}' for unified backups: {e_remove}", exc_info=True)
                flash(_('Error removing old unified backup schedule job. New schedule might not apply until restart.'), 'warning')
            if is_enabled:
                try:
                    from scheduler_tasks import run_scheduled_booking_data_protection_task
                    scheduler.add_job(
                        id=job_id,
                        func=run_scheduled_booking_data_protection_task,
                        trigger='interval',
                        minutes=interval_minutes,
                        args=[current_app._get_current_object()],
                        replace_existing=True
                    )
                    flash(_('Unified Booking Data Protection schedule updated. New settings will apply.'), 'info')
                    current_app.logger.info(f"Added/Updated scheduler job '{job_id}' for unified backups with interval {interval_minutes} minutes.")
                except Exception as e_add_job:
                    current_app.logger.error(f"Failed to add/update scheduler job '{job_id}' for unified backups: {e_add_job}", exc_info=True)
                    flash(_('Failed to apply new unified backup schedule settings to the scheduler. Check logs.'), 'danger')
            else:
                flash(_('Unified Booking Data Protection schedule is now disabled. Job removed if it existed.'), 'info')
                current_app.logger.info(f"Scheduled unified backup is now disabled. Job '{job_id}' removed (if it existed).")
        elif not scheduler or not scheduler.running:
            current_app.logger.warning("Scheduler not found or not running. Unified backup schedule changes will apply on next app start.")
            flash(_('Unified backup schedule settings saved, but scheduler is not running. Changes will apply on restart.'), 'warning')
    except Exception as e:
        current_app.logger.error(f"Error saving Unified Booking Data Protection schedule settings by {current_user.username}: {str(e)}", exc_info=True)
        flash(_('An error occurred while saving the Unified Booking Data Protection schedule settings. Please check the logs.'), 'danger')
    return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

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
    return redirect(url_for('admin_ui.serve_backup_settings_page'))

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
        if not (-23 <= new_offset_value <= 23):
            flash(_('Time offset must be an integer between -23 and +23 hours.'), 'danger')
            return redirect(url_for('admin_ui.serve_backup_settings_page'))
        settings = BookingSettings.query.first()
        if not settings:
            current_app.logger.info("No BookingSettings found, creating default instance before saving time offset.")
            settings = BookingSettings(global_time_offset_hours=0)
            db.session.add(settings)
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
        db.session.rollback()
        current_app.logger.error(f"Error saving Global Time Offset by {current_user.username}: {str(e)}", exc_info=True)
        flash(_('An error occurred while saving the time offset. Please check the logs.'), 'danger')
    return redirect(url_for('admin_ui.serve_backup_settings_page'))

# LEGACY - Azure CSV Verify Route - Body fully commented out.
# @admin_ui_bp.route('/admin/verify_booking_csv/<timestamp_str>', methods=['POST'])
# @login_required
# @permission_required('manage_system')
# def verify_booking_csv_backup_route(timestamp_str):
    # # task_id = uuid.uuid4().hex # task_id was defined here
    # # socketio_instance = None
    # # if hasattr(current_app, 'extensions') and 'socketio' in current_app.extensions:
    # #     socketio_instance = current_app.extensions['socketio']
    # # elif 'socketio' in globals() and socketio:
    # #     socketio_instance = socketio
    #
    # # app_instance = current_app._get_current_object()
    # # app_instance.logger.info(f"Booking CSV backup verification for {timestamp_str} triggered by user {current_user.username if current_user else 'Unknown User'} with task ID {task_id}.")
    #
    # # try:
    # #     verification_result = verify_booking_csv_backup(timestamp_str, socketio_instance=socketio_instance, task_id=task_id)
    # #
    # #     status = verification_result.get('status', 'unknown')
    # #     message = verification_result.get('message', 'No details provided.')
    # #     file_path = verification_result.get('file_path', 'N/A')
    # #
    # #     if status == 'success':
    # #         flash(_('Booking CSV Backup Verification for "%(timestamp)s": File found at "%(path)s".') % {'timestamp': timestamp_str, 'path': file_path}, 'success')
    # #     elif status == 'not_found':
    # #         flash(_('Booking CSV Backup Verification for "%(timestamp)s": File NOT found at "%(path)s".') % {'timestamp': timestamp_str, 'path': file_path}, 'warning')
    # #     else: # 'error' or 'unknown'
    # #         flash(_('Booking CSV Backup Verification for "%(timestamp)s" FAILED: %(message)s') % {'timestamp': timestamp_str, 'message': message}, 'danger')
    # #
    # # except Exception as e:
    # #     app_instance.logger.error(f"Exception during Booking CSV backup verification for {timestamp_str} by user {current_user.username if current_user else 'Unknown User'}: {str(e)}", exc_info=True)
    # #     flash(_('An unexpected error occurred while verifying Booking CSV backup %(timestamp)s. Check server logs.') % {'timestamp': timestamp_str}, 'danger')
    #
    # # return redirect(url_for('admin_ui.serve_backup_booking_data_page'))


@admin_ui_bp.route('/verify_full_backup/<timestamp_str>', methods=['POST'])
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
        if verification_summary.get('status') == 'verified_present':
            flash(_('Backup set %(timestamp)s verified successfully. Status: %(status)s') % {'timestamp': timestamp_str, 'status': status_message}, 'success')
        elif verification_summary.get('status') in ['manifest_missing', 'manifest_corrupt', 'failed_verification', 'critical_error']:
            error_details = "; ".join(errors)
            flash(_('Backup set %(timestamp)s verification FAILED. Status: %(status)s. Errors: %(details)s') % {'timestamp': timestamp_str, 'status': status_message, 'details': error_details}, 'danger')
        else:
            flash(_('Backup set %(timestamp)s verification status: %(status)s. Issues: %(errors)s') % {'timestamp': timestamp_str, 'status': status_message, 'errors': '; '.join(errors)}, 'warning')
    except Exception as e:
        app_instance.logger.error(f"Exception during full backup verification for {timestamp_str} by user {current_user.username if current_user else 'Unknown User'}: {str(e)}", exc_info=True)
        flash(_('An unexpected error occurred while verifying backup set %(timestamp)s. Check server logs.') % {'timestamp': timestamp_str}, 'danger')
    return redirect(url_for('admin_ui.serve_backup_system_page'))

@admin_ui_bp.route('/troubleshooting', methods=['GET'])
@login_required
@permission_required('manage_system')
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
        settings = BookingSettings(
            allow_past_bookings=False, max_booking_days_in_future=30,
            allow_multiple_resources_same_time=False, max_bookings_per_user=None,
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
        settings.max_booking_days_in_future = int(max_days_future_str) if max_days_future_str and max_days_future_str.strip() else None
        settings.allow_multiple_resources_same_time = request.form.get('allow_multiple_resources_same_time') == 'on'
        max_bookings_user_str = request.form.get('max_bookings_per_user')
        settings.max_bookings_per_user = int(max_bookings_user_str) if max_bookings_user_str and max_bookings_user_str.strip() else None
        settings.enable_check_in_out = request.form.get('enable_check_in_out') == 'on'
        check_in_minutes_before_str = request.form.get('check_in_minutes_before', '15')
        settings.check_in_minutes_before = int(check_in_minutes_before_str) if check_in_minutes_before_str.strip() else 15
        check_in_minutes_after_str = request.form.get('check_in_minutes_after', '15')
        settings.check_in_minutes_after = int(check_in_minutes_after_str) if check_in_minutes_after_str.strip() else 15
        if settings.check_in_minutes_before < 0 or settings.check_in_minutes_after < 0:
            db.session.rollback(); flash(_('Check-in window minutes cannot be negative.'), 'danger')
            return redirect(url_for('admin_ui.serve_booking_settings_page'))
        if 'past_booking_time_adjustment_hours' in request.form:
            past_booking_adjustment_str = request.form['past_booking_time_adjustment_hours']
            settings.past_booking_time_adjustment_hours = 0 if past_booking_adjustment_str.strip() == "" else int(past_booking_adjustment_str)
        settings.pin_auto_generation_enabled = request.form.get('pin_auto_generation_enabled') == 'on'
        pin_length_str = request.form.get('pin_length', '6')
        pin_length_val = int(pin_length_str) if pin_length_str.strip() else 6
        if not (4 <= pin_length_val <= 32): raise ValueError("PIN length must be between 4 and 32.")
        settings.pin_length = pin_length_val
        settings.pin_allow_manual_override = request.form.get('pin_allow_manual_override') == 'on'
        settings.resource_checkin_url_requires_login = request.form.get('resource_checkin_url_requires_login') == 'on'
        settings.allow_check_in_without_pin = request.form.get('allow_check_in_without_pin') == 'on'
        settings.enable_auto_checkout = request.form.get('enable_auto_checkout') == 'on'
        auto_checkout_delay_minutes_str = request.form.get('auto_checkout_delay_minutes', '60')
        auto_checkout_delay_minutes_val = int(auto_checkout_delay_minutes_str) if auto_checkout_delay_minutes_str.strip() else 60
        if auto_checkout_delay_minutes_val < 1: raise ValueError("Auto Check-out Delay must be at least 1 minute.")
        settings.auto_checkout_delay_minutes = auto_checkout_delay_minutes_val
        auto_release_str = request.form.get('auto_release_if_not_checked_in_minutes')
        if not auto_release_str or auto_release_str.strip() == "" or auto_release_str.strip() == "0": settings.auto_release_if_not_checked_in_minutes = None
        else:
            auto_release_val = int(auto_release_str)
            if auto_release_val < 0: db.session.rollback(); flash(_('Auto-release minutes must be a non-negative integer.'), 'danger'); return redirect(url_for('admin_ui.serve_booking_settings_page'))
            settings.auto_release_if_not_checked_in_minutes = auto_release_val
        checkin_reminder_minutes_before_str = request.form.get('checkin_reminder_minutes_before', '30')
        checkin_reminder_minutes_before_val = int(checkin_reminder_minutes_before_str) if checkin_reminder_minutes_before_str.strip() else 30
        if checkin_reminder_minutes_before_val < 0: raise ValueError("Check-in Reminder Minutes Before must be non-negative.")
        settings.checkin_reminder_minutes_before = checkin_reminder_minutes_before_val
        db.session.commit()
        changed_settings_log = f"allow_past_bookings={settings.allow_past_bookings}, max_booking_days_in_future={settings.max_booking_days_in_future}, ..." # Truncated for brevity
        add_audit_log(action="UPDATE_BOOKING_SETTINGS", details=f"Booking settings updated by {current_user.username}. New values: {changed_settings_log}")
        flash(_('Booking settings updated successfully.'), 'success')
    except ValueError as ve:
        db.session.rollback(); flash(f'{_("Invalid input")}: {str(ve)}', 'danger')
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error updating booking settings: {e}", exc_info=True)
        flash(_('An unexpected error occurred while updating booking settings.'), 'danger')
    return redirect(url_for('admin_ui.serve_booking_settings_page'))

@admin_ui_bp.route('/analytics/')
@login_required
@permission_required('view_analytics')
def analytics_dashboard():
    current_app.logger.info(f"User {current_user.username} accessed analytics dashboard.")
    return render_template('analytics.html')

@admin_ui_bp.route('/system-settings', methods=['GET', 'POST'])
@login_required
@permission_required('manage_system_settings')
def system_settings_page():
    settings = BookingSettings.query.first()
    if not settings:
        settings = BookingSettings(global_time_offset_hours=0)
        db.session.add(settings)
        try: db.session.commit()
        except Exception as e:
            current_app.logger.error(f"Error creating default BookingSettings: {e}"); db.session.rollback()
            flash(_('Error initializing system settings. Please try again.'), 'danger')
            settings = BookingSettings(global_time_offset_hours=0)
    if request.method == 'POST':
        try:
            new_offset_str = request.form.get('global_time_offset_hours')
            if new_offset_str is None or new_offset_str.strip() == "": flash(_('Time offset value must be provided.'), 'danger')
            else:
                new_offset = int(new_offset_str)
                if not (-24 < new_offset < 24): flash(_('Time offset must be between -23 and +23 hours.'), 'danger')
                else:
                    settings.global_time_offset_hours = new_offset
                    db.session.commit()
                    flash(_('Global time offset updated successfully.'), 'success')
                    add_audit_log(action="UPDATE_TIME_OFFSET", details=f"Global time offset set to {new_offset} hours by {current_user.username}.")
        except ValueError: db.session.rollback(); flash(_('Invalid input for time offset. Please enter a whole number.'), 'danger')
        except Exception as e:
            db.session.rollback(); current_app.logger.error(f"Error updating time offset: {e}", exc_info=True)
            flash(_('An error occurred while updating the time offset. Please check logs.'), 'danger')
        return redirect(url_for('admin_ui.system_settings_page'))
    current_offset_hours = settings.global_time_offset_hours if settings.global_time_offset_hours is not None else 0
    utc_now = datetime.now(timezone.utc)
    effective_time = utc_now + timedelta(hours=current_offset_hours)
    return render_template('admin/system_settings.html',
                           global_time_offset_hours=current_offset_hours,
                           current_utc_time_str=utc_now.strftime('%Y-%m-%d %H:%M:%S %Z'),
                           effective_operational_time_str=effective_time.strftime('%Y-%m-%d %H:%M:%S %Z (Effective)'))

@admin_ui_bp.route('/analytics/data')
@login_required
@permission_required('view_analytics')
def analytics_bookings_data():
    try:
        current_app.logger.info(f"User {current_user.username} requested analytics bookings data.")
        thirty_days_ago = datetime.utcnow().date() - timedelta(days=30)
        daily_counts_query = db.session.query(
            Resource.name.label("resource_name"),
            cast(func.date(Booking.start_time), db.Date).label('booking_date'),
            func.count(Booking.id).label('booking_count')
        ).join(Resource, Booking.resource_id == Resource.id) \
        .filter(cast(func.date(Booking.start_time), db.Date) >= thirty_days_ago) \
        .group_by(Resource.name, func.date(Booking.start_time)) \
        .order_by(Resource.name, func.date(Booking.start_time)) \
        .all()
        daily_counts_data = {}
        for row in daily_counts_query:
            resource_name = row.resource_name
            booking_date_str = row.booking_date.strftime('%Y-%m-%d')
            if resource_name not in daily_counts_data: daily_counts_data[resource_name] = []
            daily_counts_data[resource_name].append({"date": booking_date_str, "count": row.booking_count})
        base_query = db.session.query( Booking.id, Booking.start_time, Booking.end_time, Resource.name.label('resource_name'), Resource.capacity.label('resource_capacity'), Resource.equipment.label('resource_equipment'), Resource.tags.label('resource_tags'), Resource.status.label('resource_status'), FloorMap.location.label('floor_location'), FloorMap.floor.label('floor_number'), User.username.label('user_username'), extract('hour', Booking.start_time).label('booking_hour'), extract('dow', Booking.start_time).label('booking_day_of_week'), extract('month', Booking.start_time).label('booking_month')
        ).join(Resource, Booking.resource_id == Resource.id) \
         .join(User, Booking.user_name == User.username) \
         .outerjoin(FloorMap, Resource.floor_map_id == FloorMap.id)
        all_bookings_for_aggregation = base_query.all()
        aggregated_data = {"by_resource_attributes": {}, "by_floor_attributes": {}, "by_user": {}, "by_time_attributes": {"hour_of_day": {}, "day_of_week": {}, "month": {}}}
        for booking in all_bookings_for_aggregation:
            duration_hours = (booking.end_time - booking.start_time).total_seconds() / 3600
            res_name_key = booking.resource_name
            if res_name_key not in aggregated_data["by_resource_attributes"]: aggregated_data["by_resource_attributes"][res_name_key] = {'count': 0, 'total_duration_hours': 0}
            aggregated_data["by_resource_attributes"][res_name_key]['count'] += 1; aggregated_data["by_resource_attributes"][res_name_key]['total_duration_hours'] += duration_hours
            if booking.floor_location and booking.floor_number:
                floor_key = f"Floor: {booking.floor_number}, Location: {booking.floor_location}"
                if floor_key not in aggregated_data["by_floor_attributes"]: aggregated_data["by_floor_attributes"][floor_key] = {'count': 0, 'total_duration_hours': 0}
                aggregated_data["by_floor_attributes"][floor_key]['count'] += 1; aggregated_data["by_floor_attributes"][floor_key]['total_duration_hours'] += duration_hours
            user_key = booking.user_username
            if user_key not in aggregated_data["by_user"]: aggregated_data["by_user"][user_key] = {'count': 0, 'total_duration_hours': 0}
            aggregated_data["by_user"][user_key]['count'] += 1; aggregated_data["by_user"][user_key]['total_duration_hours'] += duration_hours
            hour_key = str(booking.booking_hour)
            if hour_key not in aggregated_data["by_time_attributes"]["hour_of_day"]: aggregated_data["by_time_attributes"]["hour_of_day"][hour_key] = {'count': 0, 'total_duration_hours': 0}
            aggregated_data["by_time_attributes"]["hour_of_day"][hour_key]['count'] += 1; aggregated_data["by_time_attributes"]["hour_of_day"][hour_key]['total_duration_hours'] += duration_hours
            dow_map = {0: "Sunday", 1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday"}
            dow_key = dow_map.get(booking.booking_day_of_week, "Unknown")
            if dow_key not in aggregated_data["by_time_attributes"]["day_of_week"]: aggregated_data["by_time_attributes"]["day_of_week"][dow_key] = {'count': 0, 'total_duration_hours': 0}
            aggregated_data["by_time_attributes"]["day_of_week"][dow_key]['count'] += 1; aggregated_data["by_time_attributes"]["day_of_week"][dow_key]['total_duration_hours'] += duration_hours
            month_map = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"} # Using short month names
            month_key = month_map.get(booking.booking_month, "Unknown")
            if month_key not in aggregated_data["by_time_attributes"]["month"]: aggregated_data["by_time_attributes"]["month"][month_key] = {'count': 0, 'total_duration_hours': 0}
            aggregated_data["by_time_attributes"]["month"][month_key]['count'] += 1; aggregated_data["by_time_attributes"]["month"][month_key]['total_duration_hours'] += duration_hours
        final_response = {"daily_counts_last_30_days": daily_counts_data, "aggregations": aggregated_data}
        current_app.logger.info(f"Successfully processed analytics data. Daily counts resources: {len(daily_counts_data)}, Aggregation items: {len(all_bookings_for_aggregation)}")
        return jsonify(final_response)
    except Exception as e:
        current_app.logger.error(f"Error generating analytics bookings data: {e}", exc_info=True)
        return jsonify({"error": "Could not process analytics data"}), 500

def init_admin_ui_routes(app):
    app.register_blueprint(admin_ui_bp)

# LEGACY - Local CSV Export - UI Removed, route kept for potential direct use or future reinstatement.
# @admin_ui_bp.route('/export_bookings_csv')
# @login_required
# @permission_required('manage_system')
# def export_bookings_csv():
#     current_app.logger.info(f"User {current_user.username} initiated CSV export of bookings.")
#     try:
#         bookings = Booking.query.all()
#
#         csv_output = io.StringIO()
#         csv_writer = csv.writer(csv_output)
#
#         # Write header row
#         header = ['id', 'resource_id', 'user_name', 'start_time', 'end_time', 'title', 'status']
#         csv_writer.writerow(header)
#
#         for booking in bookings:
#             row = [
#                 booking.id,
#                 booking.resource_id,
#                 booking.user_name,
#                 booking.start_time.strftime('%Y-%m-%d %H:%M:%S') if booking.start_time else '',
#                 booking.end_time.strftime('%Y-%m-%d %H:%M:%S') if booking.end_time else '',
#                 booking.title,
#                 booking.status
#             ]
#             csv_writer.writerow(row)
#
#         csv_output.seek(0)
#
#         return Response(
#             csv_output,
#             mimetype="text/csv",
#             headers={"Content-Disposition": "attachment;filename=bookings_export.csv"}
#         )
#     except Exception as e:
#         current_app.logger.error(f"Error exporting bookings to CSV: {e}", exc_info=True)
#         flash(_('An error occurred while exporting bookings to CSV. Please check the logs.'), 'danger')
#         return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

# LEGACY - Local CSV Import - UI Removed, route kept for potential direct use or future reinstatement.
# @admin_ui_bp.route('/import_bookings_csv', methods=['POST'])
# @login_required
# @permission_required('manage_system')
# def import_bookings_csv():
#     current_app.logger.info(f"User {current_user.username} initiated CSV import of bookings.")
#     if 'file' not in request.files:
#         flash(_('No file part in the request.'), 'danger')
#         return redirect(url_for('admin_ui.serve_backup_booking_data_page'))
#
#     file = request.files['file']
#     if file.filename == '':
#         flash(_('No selected file.'), 'danger')
#         return redirect(url_for('admin_ui.serve_backup_booking_data_page'))
#
#     if file and file.filename.endswith('.csv'):
#         filename = secure_filename(file.filename)
#         current_app.logger.info(f"Processing uploaded CSV file: {filename}")
#         try:
#             # Read the file content as a string
#             file_content = file.stream.read().decode("UTF-8")
#             csv_file = io.StringIO(file_content)
#             csv_reader = csv.reader(csv_file)
#
#             header = next(csv_reader, None) # Skip header row
#             if not header or header != ['id', 'resource_id', 'user_name', 'start_time', 'end_time', 'title', 'status']:
#                 flash(_('Invalid CSV header. Please ensure the header matches the export format.'), 'danger')
#                 return redirect(url_for('admin_ui.serve_backup_booking_data_page'))
#
#             bookings_to_add = []
#             for row_number, row in enumerate(csv_reader, start=2): # Start row count from 2 (after header)
#                 try:
#                     # Basic validation: ensure correct number of columns
#                     if len(row) != 7:
#                         flash(_(f"Skipping row {row_number}: Incorrect number of columns. Expected 7, got {len(row)}."), 'warning')
#                         current_app.logger.warning(f"CSV Import: Skipping row {row_number} due to incorrect column count. Data: {row}")
#                         continue
#
#                     resource_id_str = row[1]
#                     user_name = row[2]
#                     start_time_str = row[3]
#                     end_time_str = row[4]
#                     title = row[5] if row[5] else None # Handle optional title
#                     status = row[6]
#
#                     # Data validation and type conversion
#                     try:
#                         resource_id = int(resource_id_str)
#                     except ValueError:
#                         flash(_(f"Skipping row {row_number}: Invalid resource_id '{resource_id_str}'. Must be an integer."), 'warning')
#                         current_app.logger.warning(f"CSV Import: Skipping row {row_number} due to invalid resource_id. Data: {row}")
#                         continue
#
#                     try:
#                         start_time = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S') if start_time_str else None
#                         end_time = datetime.strptime(end_time_str, '%Y-%m-%d %H:%M:%S') if end_time_str else None
#                     except ValueError as ve:
#                         flash(_(f"Skipping row {row_number}: Invalid date format for start_time or end_time. Expected 'YYYY-MM-DD HH:MM:SS'. Error: {ve}"), 'warning')
#                         current_app.logger.warning(f"CSV Import: Skipping row {row_number} due to date parsing error. Data: {row}. Error: {ve}")
#                         continue
#
#                     # Optional: Add more validation (e.g., check if user_name and resource_id exist)
#                     # For now, we assume they exist or allow DB constraints to handle it.
#
#                     new_booking = Booking(
#                         resource_id=resource_id,
#                         user_name=user_name,
#                         start_time=start_time,
#                         end_time=end_time,
#                         title=title,
#                         status=status
#                         # id is auto-generated, so we don't set it from the CSV's first column.
#                         # If you need to preserve IDs, you'd need to handle potential conflicts.
#                     )
#                     bookings_to_add.append(new_booking)
#                 except Exception as e_row:
#                     flash(_(f"Error processing row {row_number}: {str(e_row)}. Skipping this row."), 'warning')
#                     current_app.logger.error(f"CSV Import: Error processing row {row_number}. Data: {row}. Error: {e_row}", exc_info=True)
#                     continue # Skip to the next row
#
#             if bookings_to_add:
#                 db.session.add_all(bookings_to_add)
#                 db.session.commit()
#                 flash(_(f'Successfully imported {len(bookings_to_add)} bookings from {filename}.'), 'success')
#                 current_app.logger.info(f"Successfully imported {len(bookings_to_add)} bookings from {filename}.")
#             else:
#                 flash(_('No new bookings were imported. The file might have been empty or all rows had errors.'), 'info')
#                 current_app.logger.info(f"No new bookings imported from {filename}. File might be empty or all rows had errors.")
#
#         except Exception as e:
#             db.session.rollback()
#             current_app.logger.error(f"Error importing bookings from CSV file {filename}: {e}", exc_info=True)
#             flash(_(f'An error occurred while importing bookings from {filename}. Error: {str(e)}'), 'danger')
#     else:
#         flash(_('Invalid file type. Please upload a CSV file.'), 'danger')
#
#     return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

@admin_ui_bp.route('/export_all_bookings_json')
@login_required
@permission_required('manage_system')
def export_all_bookings_json():
    current_app.logger.info(f"User {current_user.username} initiated export of all bookings to JSON.")
    try:
        all_bookings = Booking.query.all()

        serialized_bookings = []
        for booking in all_bookings:
            serialized_bookings.append({
                'id': booking.id,
                'resource_id': booking.resource_id,
                'user_name': booking.user_name,
                'start_time': booking.start_time.isoformat() if booking.start_time else None,
                'end_time': booking.end_time.isoformat() if booking.end_time else None,
                'title': booking.title,
                'status': booking.status,
                'created_at': booking.created_at.isoformat() if booking.created_at else None,
                'last_modified': booking.last_modified.isoformat() if booking.last_modified else None,
                'is_recurring': booking.is_recurring,
                'recurrence_id': booking.recurrence_id,
                'is_cancelled': booking.is_cancelled,
                'checked_in_at': booking.checked_in_at.isoformat() if booking.checked_in_at else None,
                'checked_out_at': booking.checked_out_at.isoformat() if booking.checked_out_at else None,
                'admin_deleted_message': booking.admin_deleted_message,
                'check_in_token': booking.check_in_token,
                'check_in_token_expires_at': booking.check_in_token_expires_at.isoformat() if booking.check_in_token_expires_at else None,
                'pin': booking.pin
            })

        json_data_string = json.dumps(serialized_bookings, indent=4)

        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        filename = f"all_bookings_export_{timestamp}.json"

        add_audit_log(action="EXPORT_ALL_BOOKINGS_JSON", details=f"User {current_user.username} exported {len(serialized_bookings)} bookings to JSON file {filename}.", user_id=current_user.id)

        return Response(
            json_data_string,
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment;filename={filename}"}
        )

    except Exception as e:
        current_app.logger.error(f"Error exporting all bookings to JSON for user {current_user.username}: {e}", exc_info=True)
        flash(_('An error occurred while exporting all bookings to JSON. Please check the logs.'), 'danger')
        # Redirect back to the page where the button was clicked
        return redirect(request.referrer or url_for('admin_ui.serve_backup_booking_data_page'))

@admin_ui_bp.route('/import_bookings_json', methods=['POST'])
@login_required
@permission_required('manage_system')
def import_bookings_json():
    current_app.logger.info(f"User {current_user.username} initiated import of bookings from local JSON file.")

    if 'file' not in request.files:
        flash(_('No file part in the request. Please select a JSON file to import.'), 'danger')
        return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

    file = request.files['file']
    if file.filename == '':
        flash(_('No file selected. Please select a JSON file to import.'), 'danger')
        return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

    if not file.filename.endswith('.json'):
        flash(_('Invalid file type. Please upload a .json file.'), 'danger')
        return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

    filename = secure_filename(file.filename)
    current_app.logger.info(f"Processing uploaded JSON file for booking import: {filename}")

    try:
        file_content = file.stream.read().decode("UTF-8")
        bookings_data_from_json = json.loads(file_content)

        if not isinstance(bookings_data_from_json, list):
            flash(_('Invalid JSON format. Expected a list of booking objects.'), 'danger')
            return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

        # Clear existing bookings - THIS IS A DESTRUCTIVE ACTION
        current_app.logger.warning(f"User {current_user.username} is clearing ALL existing bookings due to JSON import from file {filename}.")
        _emit_progress(None, None, 'booking_json_import_progress', "Clearing all existing bookings...", level='WARNING') # Generic progress

        try:
            num_deleted = db.session.query(Booking).delete()
            db.session.commit()
            current_app.logger.info(f"Successfully cleared {num_deleted} existing bookings before JSON import.")
            _emit_progress(None, None, 'booking_json_import_progress', f"{num_deleted} existing bookings cleared.", level='INFO')
        except Exception as e_delete:
            db.session.rollback()
            current_app.logger.error(f"Error clearing existing bookings during JSON import: {e_delete}", exc_info=True)
            flash(_('Error clearing existing bookings. Import aborted. Please check logs.'), 'danger')
            return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

        bookings_imported_count = 0
        for booking_data in bookings_data_from_json:
            if not isinstance(booking_data, dict):
                current_app.logger.warning(f"Skipping non-dictionary item in JSON data: {booking_data}")
                continue
            try:
                # Convert datetime strings to datetime objects
                for dt_field in ['start_time', 'end_time', 'created_at', 'last_modified',
                                 'checked_in_at', 'checked_out_at', 'check_in_token_expires_at']:
                    if booking_data.get(dt_field) and isinstance(booking_data[dt_field], str):
                        try:
                            booking_data[dt_field] = datetime.fromisoformat(booking_data[dt_field])
                        except ValueError: # Handle cases where fromisoformat might fail (e.g. non-standard ISO string)
                            current_app.logger.warning(f"Could not parse datetime string '{booking_data[dt_field]}' for field '{dt_field}' in booking data: {booking_data.get('id', 'Unknown ID')}. Setting to None.")
                            booking_data[dt_field] = None
                    elif booking_data.get(dt_field) is not None: # It's not a string and not None, ensure it's None if not parsable
                         booking_data[dt_field] = None


                new_booking = Booking(
                    # id is not set, allowing auto-generation
                    resource_id=booking_data.get('resource_id'),
                    user_name=booking_data.get('user_name'),
                    start_time=booking_data.get('start_time'),
                    end_time=booking_data.get('end_time'),
                    title=booking_data.get('title'),
                    status=booking_data.get('status', 'approved'),
                    created_at=booking_data.get('created_at'), # Let DB handle default if None
                    last_modified=booking_data.get('last_modified'), # Let DB handle default/onupdate if None
                    is_recurring=booking_data.get('is_recurring', False),
                    recurrence_id=booking_data.get('recurrence_id'),
                    is_cancelled=booking_data.get('is_cancelled', False),
                    checked_in_at=booking_data.get('checked_in_at'),
                    checked_out_at=booking_data.get('checked_out_at'),
                    admin_deleted_message=booking_data.get('admin_deleted_message'),
                    check_in_token=booking_data.get('check_in_token'),
                    check_in_token_expires_at=booking_data.get('check_in_token_expires_at'),
                    pin=booking_data.get('pin')
                )
                db.session.add(new_booking)
                bookings_imported_count += 1
            except Exception as e_item:
                db.session.rollback() # Rollback for this item, or potentially for the whole import
                current_app.logger.error(f"Error processing booking item from JSON file {filename}: {booking_data.get('id', 'Unknown ID')}. Error: {e_item}", exc_info=True)
                flash(_('Error processing a booking item from the JSON file. Import aborted. Some bookings may have been cleared. Error: %(error)s', error=str(e_item)), 'danger')
                return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

        db.session.commit()
        flash(_('Successfully imported %(count)s bookings from JSON file "%(filename)s". All previous bookings were deleted.', count=bookings_imported_count, filename=filename), 'success')
        add_audit_log(action="IMPORT_BOOKINGS_JSON", details=f"Imported {bookings_imported_count} bookings from local JSON file '{filename}'. All previous bookings deleted.", user_id=current_user.id)
        _emit_progress(None, None, 'booking_json_import_progress', f"Imported {bookings_imported_count} bookings from {filename}.", level='SUCCESS')

    except json.JSONDecodeError as jde:
        current_app.logger.error(f"Invalid JSON file uploaded by {current_user.username}: {filename}. Error: {jde}", exc_info=True)
        flash(_('Invalid JSON file. Please ensure the file is correctly formatted. Error: %(error)s', error=str(jde)), 'danger')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error importing bookings from JSON file {filename} by user {current_user.username}: {e}", exc_info=True)
        flash(_('An error occurred while importing bookings from JSON file "%(filename)s". Error: %(error)s', filename=filename, error=str(e)), 'danger')

    return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

# The /clear_all_bookings route is part of the "Local Data Management" and should be kept.
# It was previously commented out by mistake in my plan.
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

[end of routes/admin_ui.py]
