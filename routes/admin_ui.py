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
from azure_backup import verify_backup_set
# Other legacy imports (list_available_booking_csv_backups, list_available_backups, etc.) removed
# as they are not directly used by active routes in this file after cleanup.
# Interactions with those functions are now primarily through API endpoints defined in api_system.py,
# or the features they supported are deprecated.

# Removed duplicate model, db, auth, datetime imports that were already covered above or are standard
import os
import json
from apscheduler.jobstores.base import JobLookupError
# from scheduler_tasks import run_scheduled_booking_csv_backup, run_scheduled_incremental_booking_backup # run_scheduled_booking_csv_backup is legacy
from scheduler_tasks import run_scheduled_incremental_booking_backup # Added run_scheduled_incremental_booking_backup
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

    possible_statuses = ['approved', 'checked_in', 'completed', 'cancelled', 'rejected', 'cancelled_by_admin']
    all_users = User.query.order_by(User.username).all()

    try:
        bookings_query = db.session.query(
            Booking.id, Booking.title, Booking.start_time, Booking.end_time, Booking.status,
            Booking.admin_deleted_message, User.username.label('user_username'), Resource.name.label('resource_name')
        ).join(Resource, Booking.resource_id == Resource.id)\
         .join(User, Booking.user_name == User.username)

        if status_filter: bookings_query = bookings_query.filter(Booking.status == status_filter)
        if user_filter: bookings_query = bookings_query.filter(User.username == user_filter)
        if date_filter_str:
            try:
                date_filter_obj = datetime.strptime(date_filter_str, '%Y-%m-%d').date()
                bookings_query = bookings_query.filter(func.date(Booking.start_time) == date_filter_obj)
            except ValueError: logger.warning(f"Invalid date format for date_filter: '{date_filter_str}'. Ignoring filter.")

        all_booking_rows = bookings_query.all()
        upcoming_bookings_processed, past_bookings_processed = [], []
        now_utc = datetime.now(timezone.utc)

        for row in all_booking_rows:
            start_time_dt = row.start_time
            aware_start_time = start_time_dt.replace(tzinfo=timezone.utc) if start_time_dt and start_time_dt.tzinfo is None else start_time_dt
            end_time_dt = row.end_time
            aware_end_time = end_time_dt.replace(tzinfo=timezone.utc) if end_time_dt and end_time_dt.tzinfo is None else end_time_dt
            booking_data = {'id': row.id, 'title': row.title, 'start_time': aware_start_time, 'end_time': aware_end_time, 'status': row.status, 'user_username': row.user_username, 'resource_name': row.resource_name, 'admin_deleted_message': row.admin_deleted_message}
            if aware_start_time and aware_start_time >= now_utc: upcoming_bookings_processed.append(booking_data)
            elif aware_start_time: past_bookings_processed.append(booking_data)

        upcoming_bookings_processed.sort(key=lambda b: b['start_time'])
        past_bookings_processed.sort(key=lambda b: b['start_time'], reverse=True)
        comprehensive_statuses = sorted(list(set(s for s in ['pending', 'approved', 'rejected', 'cancelled', 'checked_in', 'completed', 'cancelled_by_user', 'cancelled_by_admin', 'cancelled_admin_acknowledged', 'system_cancelled_no_checkin', 'confirmed', 'no_show', 'on_hold', 'under_review'] if s and s.strip())))

        return render_template("admin_bookings.html", upcoming_bookings=upcoming_bookings_processed, past_bookings=past_bookings_processed, all_statuses=comprehensive_statuses, current_status_filter=status_filter, all_users=all_users, current_user_filter=user_filter, current_date_filter=date_filter_str, new_sorting_active=True)
    except Exception as e:
        logger.error(f"Error fetching and sorting bookings for admin page: {e}", exc_info=True)
        comprehensive_statuses = sorted(list(set(s for s in ['pending', 'approved', 'rejected', 'cancelled', 'checked_in', 'completed', 'cancelled_by_user', 'cancelled_by_admin', 'cancelled_admin_acknowledged', 'system_cancelled_no_checkin', 'confirmed', 'no_show', 'on_hold', 'under_review'] if s and s.strip())))
        return render_template("admin_bookings.html", upcoming_bookings=[], past_bookings=[], error="Could not load and sort bookings.", all_statuses=comprehensive_statuses, current_status_filter=status_filter, all_users=all_users, current_user_filter=user_filter, current_date_filter=date_filter_str, new_sorting_active=True)

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
    full_backup_settings.setdefault('interval_value', 60); full_backup_settings.setdefault('interval_unit', 'minutes')
    full_backup_settings.setdefault('schedule_type', 'daily'); full_backup_settings.setdefault('time_of_day', '02:00')
    full_backup_settings.setdefault('day_of_week', None if full_backup_settings['schedule_type'] != 'weekly' else 0)
    time_offset_value = 0
    try:
        booking_settings = BookingSettings.query.first()
        if booking_settings and booking_settings.global_time_offset_hours is not None: time_offset_value = booking_settings.global_time_offset_hours
        elif not booking_settings: current_app.logger.info("No BookingSettings found for system page, defaulting offset to 0.")
        else: current_app.logger.warning("BookingSettings.global_time_offset_hours is None for system page, defaulting offset to 0.")
    except Exception as e: current_app.logger.error(f"Error fetching BookingSettings for system page: {e}", exc_info=True)
    return render_template('admin/backup_system.html', full_backup_settings=full_backup_settings, global_time_offset_hours=time_offset_value)

@admin_ui_bp.route('/backup/booking_data', methods=['GET'])
@login_required
@permission_required('manage_system')
def serve_backup_booking_data_page():
    current_app.logger.info(f"User {current_user.username} accessed Booking Data Management page.")
    scheduler_settings = load_scheduler_settings()
    DEFAULT_BOOKING_DATA_PROTECTION_SCHEDULE = {'is_enabled': False, 'interval_minutes': 1440}
    booking_data_protection_schedule = scheduler_settings.get('booking_data_protection_schedule', DEFAULT_BOOKING_DATA_PROTECTION_SCHEDULE.copy())
    booking_data_protection_schedule.setdefault('is_enabled', DEFAULT_BOOKING_DATA_PROTECTION_SCHEDULE['is_enabled'])
    booking_data_protection_schedule.setdefault('interval_minutes', DEFAULT_BOOKING_DATA_PROTECTION_SCHEDULE['interval_minutes'])

    # Legacy CSV list is no longer server-populated. Client-side JS will handle fetching if needed.
    # Default/empty values are passed to the template for any remaining placeholders.
    paginated_booking_csv_backups = []
    page, total_pages, has_prev, has_next = 1, 0, False, False

    time_offset_value = 0
    try:
        booking_settings = BookingSettings.query.first()
        if booking_settings and booking_settings.global_time_offset_hours is not None: time_offset_value = booking_settings.global_time_offset_hours
        elif not booking_settings: current_app.logger.info("No BookingSettings found for booking data page, defaulting offset to 0.")
        else: current_app.logger.warning("BookingSettings.global_time_offset_hours is None for booking data page, defaulting offset to 0.")
    except Exception as e: current_app.logger.error(f"Error fetching BookingSettings for booking data page: {e}", exc_info=True)

    return render_template('admin/backup_booking_data.html',
                           booking_data_protection_schedule=booking_data_protection_schedule,
                           # Legacy CSV variables removed from here:
                           # booking_csv_backups=paginated_booking_csv_backups,
                           # booking_csv_page=page,
                           # booking_csv_total_pages=total_pages,
                           # booking_csv_has_prev=has_prev,
                           # booking_csv_has_next=has_next,
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
        try: db.session.commit(); current_app.logger.info("Default BookingSettings committed.")
        except Exception as e: db.session.rollback(); current_app.logger.error(f"Error committing default BookingSettings: {e}", exc_info=True)
    global_time_offset_hours = booking_settings.global_time_offset_hours if booking_settings else 0
    if global_time_offset_hours is None: global_time_offset_hours = 0; current_app.logger.warning("global_time_offset_hours was None, defaulted to 0.")
    return render_template('admin/backup_settings.html', auto_restore_booking_records_on_startup=auto_restore_booking_records_on_startup, global_time_offset_hours=global_time_offset_hours)

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
    # # elif 'socketio' in globals() and socketio:
    # #     socketio_instance = socketio
    # #
    # # summary = restore_bookings_from_csv_backup(
    # #     current_app._get_current_object(),
    # #     timestamp_str,
    # #     socketio_instance=socketio_instance,
    # #     task_id=task_id
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
    # # else:
    # #     error_details = '; '.join(summary.get('errors', ['Unknown error']))
    # #     flash(f"Booking CSV restore for {timestamp_str} failed. Status: {summary.get('status','unknown')}. Message: {summary.get('message','N/A')}. Details: {error_details}", 'danger')
    # #
    # # # return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

# LEGACY - Azure CSV Manual Backup Route - Body fully commented out.
# @admin_ui_bp.route('/admin/manual_backup_bookings_csv', methods=['POST'])
# @login_required
# @permission_required('manage_system')
# def manual_backup_bookings_csv_route():
    # # task_id = uuid.uuid4().hex
    # # socketio_instance = None
    # # if hasattr(current_app, 'extensions') and 'socketio' in current_app.extensions:
    # #     socketio_instance = current_app.extensions['socketio']
    # # elif 'socketio' in globals() and socketio:
    # #     socketio_instance = socketio
    # # app_instance = current_app._get_current_object()
    # # range_type = request.form.get('backup_range_type', 'all')
    # # start_date_dt = None; end_date_dt = None; range_label = range_type
    # # utcnow = datetime.utcnow()
    # # if range_type != "all": end_date_dt = datetime(utcnow.year, utcnow.month, utcnow.day) + timedelta(days=1)
    # # if range_type == "1day": start_date_dt = end_date_dt - timedelta(days=1)
    # # elif range_type == "3days": start_date_dt = end_date_dt - timedelta(days=3)
    # # elif range_type == "7days": start_date_dt = end_date_dt - timedelta(days=7)
    # # elif range_type == "all": start_date_dt = None; end_date_dt = None; range_label = "all"
    # # log_detail = f"range: {range_label}"
    # # if start_date_dt: log_detail += f", from: {start_date_dt.strftime('%Y-%m-%d')}"
    # # if end_date_dt: log_detail += f", to: {end_date_dt.strftime('%Y-%m-%d')}"
    # # app_instance.logger.info(f"Manual booking CSV backup ({log_detail}) triggered by user {current_user.username if current_user else 'Unknown User'} with task ID {task_id}.")
    # # try:
    # #     success = backup_bookings_csv(app=app_instance, socketio_instance=socketio_instance, task_id=task_id, start_date_dt=start_date_dt, end_date_dt=end_date_dt, range_label=range_label)
    # #     if success: flash(_('Manual booking CSV backup for range "%(range)s" initiated successfully. Check logs or SocketIO messages for progress/completion.') % {'range': range_label}, 'success')
    # #     else: flash(_('Manual booking CSV backup for range "%(range)s" failed to complete successfully. Please check server logs.') % {'range': range_label}, 'warning')
    # # except Exception as e:
    # #     app_instance.logger.error(f"Exception during manual booking CSV backup (range: {range_label}) initiation by user {current_user.username if current_user else 'Unknown User'}: {str(e)}", exc_info=True)
    # #     flash(_('An unexpected error occurred while starting the manual booking CSV backup for range "%(range)s". Check server logs.') % {'range': range_label}, 'danger')
    # # # return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

# LEGACY - Azure CSV Delete Route - Body fully commented out.
# @admin_ui_bp.route('/admin/delete_booking_csv/<timestamp_str>', methods=['POST'])
# @login_required
# @permission_required('manage_system')
# def delete_booking_csv_backup_route(timestamp_str):
    # # task_id = uuid.uuid4().hex
    # # socketio_instance = None
    # # if hasattr(current_app, 'extensions') and 'socketio' in current_app.extensions:
    # #     socketio_instance = current_app.extensions['socketio']
    # # elif 'socketio' in globals() and socketio:
    # #     socketio_instance = socketio
    # # app_instance = current_app._get_current_object()
    # # app_instance.logger.info(f"Deletion of booking CSV backup {timestamp_str} triggered by user {current_user.username if current_user else 'Unknown User'} with task ID {task_id}.")
    # # try:
    # #     success = delete_booking_csv_backup(timestamp_str, socketio_instance=socketio_instance, task_id=task_id)
    # #     if success: flash(_('Booking CSV backup for %(timestamp)s successfully deleted (or was not found).') % {'timestamp': timestamp_str}, 'success')
    # #     else: flash(_('Failed to delete booking CSV backup for %(timestamp)s. Check server logs.') % {'timestamp': timestamp_str}, 'danger')
    # # except Exception as e:
    # #     app_instance.logger.error(f"Exception during booking CSV backup deletion for {timestamp_str} by user {current_user.username if current_user else 'Unknown User'}: {str(e)}", exc_info=True)
    # #     flash(_('An unexpected error occurred while deleting the booking CSV backup for %(timestamp)s. Check server logs.') % {'timestamp': timestamp_str}, 'danger')
    # # # return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

# LEGACY - Azure CSV Schedule Save Route - Body fully commented out.
# @admin_ui_bp.route('/save_booking_csv_schedule', methods=['POST'])
# @login_required
# @permission_required('manage_system')
# def save_booking_csv_schedule_settings():
    # # ... (entire body commented out) ...
    # # return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

@admin_ui_bp.route('/settings/schedule/full_backup', methods=['POST'])
@login_required
@permission_required('manage_system')
def save_full_backup_schedule_settings():
    # ... (implementation as provided) ...
    return redirect(url_for('admin_ui.serve_backup_system_page'))

# LEGACY - This route was for the old CSV schedule, now handled by booking_data_protection_schedule or removed.
# @admin_ui_bp.route('/settings/schedule/booking_csv', methods=['POST'])
# @login_required
# @permission_required('manage_system')
# def save_booking_data_schedule_settings(): # This name was for the old CSV schedule
#     pass

# @admin_ui_bp.route('/settings/schedule/booking_incremental_json', methods=['POST'])
# @login_required
# @permission_required('manage_system')
# def save_booking_incremental_json_schedule_settings():
#     pass


@admin_ui_bp.route('/backup/booking_data_protection/schedule/save', methods=['POST'])
@login_required
@permission_required('manage_system')
def save_booking_data_protection_schedule():
    # ... (implementation as provided) ...
    return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

@admin_ui_bp.route('/settings/startup/auto_restore_bookings', methods=['POST'])
@login_required
@permission_required('manage_system')
def save_auto_restore_booking_records_settings():
    # ... (implementation as provided) ...
    return redirect(url_for('admin_ui.serve_backup_settings_page'))

@admin_ui_bp.route('/backup/settings/time_offset', methods=['POST'], endpoint='save_backup_time_offset')
@login_required
@permission_required('manage_system')
def save_backup_time_offset_route():
    # ... (implementation as provided) ...
    return redirect(url_for('admin_ui.serve_backup_settings_page'))

# LEGACY - Azure CSV Verify Route - Body fully commented out.
# @admin_ui_bp.route('/admin/verify_booking_csv/<timestamp_str>', methods=['POST'])
# @login_required
# @permission_required('manage_system')
# def verify_booking_csv_backup_route(timestamp_str):
    # # ... (entire body commented out) ...
    # # # return redirect(url_for('admin_ui.serve_backup_booking_data_page'))


@admin_ui_bp.route('/verify_full_backup/<timestamp_str>', methods=['POST'])
@login_required
@permission_required('manage_system')
def verify_full_backup_route(timestamp_str):
    # ... (implementation as provided) ...
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
    # ... (implementation as provided) ...
    return render_template('admin_booking_settings.html', settings=settings)

@admin_ui_bp.route('/booking_settings/update', methods=['POST'])
@login_required
@permission_required('manage_system')
def update_booking_settings():
    # ... (implementation as provided) ...
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
    # ... (implementation as provided) ...
    return render_template('admin/system_settings.html',
                           global_time_offset_hours=current_offset_hours,
                           current_utc_time_str=utc_now.strftime('%Y-%m-%d %H:%M:%S %Z'),
                           effective_operational_time_str=effective_time.strftime('%Y-%m-%d %H:%M:%S %Z (Effective)'))

@admin_ui_bp.route('/analytics/data')
@login_required
@permission_required('view_analytics')
def analytics_bookings_data():
    # ... (implementation as provided) ...
    return jsonify(final_response)

def init_admin_ui_routes(app):
    app.register_blueprint(admin_ui_bp)

# LEGACY - Local CSV Export - UI Removed, route kept for potential direct use or future reinstatement.
# @admin_ui_bp.route('/export_bookings_csv')
# @login_required
# @permission_required('manage_system')
# def export_bookings_csv():
#     # ... (body previously commented out) ...
#     pass

# LEGACY - Local CSV Import - UI Removed, route kept for potential direct use or future reinstatement.
# @admin_ui_bp.route('/import_bookings_csv', methods=['POST'])
# @login_required
# @permission_required('manage_system')
# def import_bookings_csv():
#     # ... (body previously commented out) ...
#     pass

@admin_ui_bp.route('/export_all_bookings_json')
@login_required
@permission_required('manage_system')
def export_all_bookings_json():
    # ... (implementation as provided) ...
    return Response(
        json_data_string,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

@admin_ui_bp.route('/import_bookings_json', methods=['POST'])
@login_required
@permission_required('manage_system')
def import_bookings_json():
    # ... (implementation as provided) ...
    return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

@admin_ui_bp.route('/clear_all_bookings', methods=['POST'])
@login_required
@permission_required('manage_system')
def clear_all_bookings_data():
    # ... (implementation as provided) ...
    return redirect(url_for('admin_ui.serve_backup_booking_data_page'))

[end of routes/admin_ui.py]
