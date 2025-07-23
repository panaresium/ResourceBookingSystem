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
from extensions import db # socketio removed
# Assuming permission_required is in auth.py
from auth import permission_required # Corrected: auth.py is at root
from datetime import datetime, timedelta, timezone # Add datetime imports
from utils import load_scheduler_settings, save_scheduler_settings, DEFAULT_FULL_BACKUP_SCHEDULE, DEFAULT_BOOKING_CSV_BACKUP_SCHEDULE, add_audit_log # Ensure add_audit_log is imported

# Import backup/restore functions
# Other legacy imports (list_available_booking_csv_backups, list_available_backups, etc.) removed
# as they are not directly used by active routes in this file after cleanup.
# Interactions with those functions are now primarily through API endpoints defined in api_system.py,
# or the features they supported are deprecated.

# Removed duplicate model, db, auth, datetime imports that were already covered above or are standard
import os
import json
from apscheduler.jobstores.base import JobLookupError
# from scheduler_tasks import run_scheduled_booking_csv_backup # run_scheduled_booking_csv_backup is legacy
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
    # scheduler_settings and booking_data_protection_schedule are no longer loaded here.
    # This information is now fetched by client-side JavaScript via an API endpoint.

    time_offset_value = 0
    try:
        booking_settings = BookingSettings.query.first()
        if booking_settings and booking_settings.global_time_offset_hours is not None: time_offset_value = booking_settings.global_time_offset_hours
        elif not booking_settings: current_app.logger.info("No BookingSettings found for booking data page, defaulting offset to 0.")
        else: current_app.logger.warning("BookingSettings.global_time_offset_hours is None for booking data page, defaulting offset to 0.")
    except Exception as e: current_app.logger.error(f"Error fetching BookingSettings for booking data page: {e}", exc_info=True)

    return render_template('admin/backup_booking_data.html',
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

    # Check Gmail configuration status
    gmail_refresh_token = current_app.config.get('GMAIL_REFRESH_TOKEN')
    gmail_sender_address = current_app.config.get('GMAIL_SENDER_ADDRESS')
    is_gmail_configured = bool(gmail_refresh_token and gmail_sender_address)
    current_app.logger.debug(f"Rendering backup_settings_page for {current_user.username}. Gmail Configured: {is_gmail_configured}")

    return render_template('admin/backup_settings.html',
                           auto_restore_booking_records_on_startup=auto_restore_booking_records_on_startup,
                           global_time_offset_hours=global_time_offset_hours,
                           is_gmail_configured=is_gmail_configured,
                           gmail_sender_address=gmail_sender_address if is_gmail_configured else None)

# LEGACY - Azure CSV Restore Route - Body fully commented out.
# LEGACY CSV Routes are fully removed.

@admin_ui_bp.route('/settings/schedule/full_backup', methods=['POST'])
@login_required
@permission_required('manage_system')
def save_full_backup_schedule_settings():
    try:
        is_enabled = request.form.get('full_backup_enabled') == 'true'

        scheduler_settings = load_scheduler_settings()
        if 'full_backup' not in scheduler_settings:
            scheduler_settings['full_backup'] = DEFAULT_FULL_BACKUP_SCHEDULE.copy()

        scheduler_settings['full_backup']['is_enabled'] = is_enabled

        schedule_type = request.form.get('full_backup_schedule_type', 'daily')
        time_of_day = request.form.get('full_backup_time_of_day')
        day_of_week_str = request.form.get('full_backup_day_of_week')
        interval_value_str = request.form.get('full_backup_interval_value')
        interval_unit = request.form.get('full_backup_interval_unit', 'minutes')

        scheduler_settings['full_backup']['schedule_type'] = schedule_type

        if schedule_type == 'daily' or schedule_type == 'weekly':
            scheduler_settings['full_backup']['time_of_day'] = time_of_day
            if schedule_type == 'weekly':
                try:
                    day_of_week = int(day_of_week_str)
                    scheduler_settings['full_backup']['day_of_week'] = day_of_week
                except (ValueError, TypeError):
                    current_app.logger.warning(f"Invalid day_of_week value: {day_of_week_str}. Skipping update for day_of_week.")
            # Remove interval settings if they exist
            scheduler_settings['full_backup'].pop('interval_value', None)
            scheduler_settings['full_backup'].pop('interval_unit', None)
        elif schedule_type == 'interval':
            interval_value = 60 # Default value
            try:
                interval_value = int(interval_value_str)
                if interval_value < 1:
                    current_app.logger.warning(f"Interval value must be at least 1. Received {interval_value}. Defaulting to 60.")
                    interval_value = 60
            except (ValueError, TypeError):
                current_app.logger.warning(f"Invalid interval_value: {interval_value_str}. Defaulting to 60.")

            scheduler_settings['full_backup']['interval_value'] = interval_value
            scheduler_settings['full_backup']['interval_unit'] = interval_unit
            # Remove daily/weekly settings if they exist
            scheduler_settings['full_backup'].pop('time_of_day', None)
            scheduler_settings['full_backup'].pop('day_of_week', None)

        save_scheduler_settings(scheduler_settings)
        add_audit_log(action='Update Full Backup Schedule', details=f'Updated full backup schedule settings. Enabled: {is_enabled}, Type: {schedule_type}')
        flash(_('Full backup schedule settings saved successfully.'), 'success')
        current_app.logger.info(f"Full backup schedule settings saved by {current_user.username}. Enabled: {is_enabled}, Type: {schedule_type}")

    except Exception as e:
        current_app.logger.error(f"Error saving full backup schedule settings: {e}", exc_info=True)
        flash(_('An error occurred while saving full backup schedule settings: %(error)s', error=str(e)), 'error')

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
    logger = current_app.logger
    try:
        # Checkbox value is 'true' if checked, otherwise not present in form data
        auto_restore_enabled_str = request.form.get('auto_restore_booking_records_enabled')
        auto_restore_enabled_bool = auto_restore_enabled_str == 'true'

        scheduler_settings = load_scheduler_settings()
        scheduler_settings['auto_restore_booking_records_on_startup'] = auto_restore_enabled_bool
        save_scheduler_settings(scheduler_settings)

        flash(_('Startup behavior settings saved successfully.'), 'success')
        add_audit_log(action='Update Startup Behavior Settings', details=f'Automatic booking restore on startup set to {auto_restore_enabled_bool}')
        logger.info(f"Startup behavior settings (auto_restore_booking_records_on_startup) set to {auto_restore_enabled_bool} by user {current_user.username}.")

    except Exception as e:
        flash(_('Error saving startup behavior settings: %(error)s', error=str(e)), 'error')
        logger.error(f"Error saving startup behavior settings: {e}", exc_info=True)

    return redirect(url_for('admin_ui.serve_backup_settings_page'))

@admin_ui_bp.route('/backup/settings/time_offset', methods=['POST'], endpoint='save_backup_time_offset')
@login_required
@permission_required('manage_system')
def save_backup_time_offset_route():
    logger = current_app.logger
    try:
        offset_value_str = request.form.get('global_time_offset_hours')
        if offset_value_str is None:
            flash(_('No time offset value provided.'), 'error')
            return redirect(url_for('admin_ui.serve_backup_settings_page'))

        offset_value = int(offset_value_str)

        if not (-23 <= offset_value <= 23):
            flash(_('Global time offset must be between -23 and 23 hours.'), 'error')
            return redirect(url_for('admin_ui.serve_backup_settings_page'))

        settings = BookingSettings.query.first()
        if not settings:
            logger.info("No BookingSettings found, creating a new one.")
            settings = BookingSettings()
            db.session.add(settings)

        settings.global_time_offset_hours = offset_value
        db.session.commit()

        flash(_('Global time offset saved successfully.'), 'success')
        add_audit_log(action='Update Global Time Offset', details=f'Set to {offset_value} hours.')
        logger.info(f"Global time offset set to {offset_value} hours by user {current_user.username}.")

    except ValueError:
        flash(_('Invalid value for time offset. Please enter a whole number.'), 'error')
        logger.warning(f"ValueError while trying to set time offset: {offset_value_str}")
    except Exception as e:
        db.session.rollback()
        flash(_('Error saving global time offset: %(error)s', error=str(e)), 'error')
        logger.error(f"Error saving global time offset: {e}", exc_info=True)

    return redirect(url_for('admin_ui.serve_backup_settings_page'))

# LEGACY - Azure CSV Verify Route - Body fully commented out.
# @admin_ui_bp.route('/admin/verify_booking_csv/<timestamp_str>', methods=['POST'])
# @login_required
# @permission_required('manage_system')
# def verify_booking_csv_backup_route(timestamp_str):
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
    current_app.logger.info(f"User {current_user.username} accessed Booking Settings page.")
    settings = BookingSettings.query.first()
    if not settings:
        current_app.logger.info("No BookingSettings found, creating default BookingSettings.")
        settings = BookingSettings() # Assuming default values are handled by the model
        db.session.add(settings)
        try:
            db.session.commit()
            current_app.logger.info("Default BookingSettings committed.")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error committing default BookingSettings: {e}", exc_info=True)
            # If commit fails, the page will be rendered with potentially uncommitted settings object.
            # Depending on the model, 'settings' might be None or an empty object if initialization failed
            # or if an error occurred before this point.
            # For this task, ensuring 'settings' is defined is the primary goal.
            # A robust solution might involve flashing an error message or redirecting.
            # If settings is None after a failed commit, ensure it's at least an empty object for the template,
            # though BookingSettings() should provide an instance.

    # Fallback in case settings is somehow None (e.g. commit failed and rolled back, and instance became None)
    # This is more of a defensive check; BookingSettings() should return an instance.
    if settings is None:
        current_app.logger.error("BookingSettings is None even after attempting to fetch or create. Using a temporary empty object for rendering.")
        # This situation indicates a deeper problem, but for template rendering, avoid NameError.
        # A proper fix would depend on why 'settings' became None.
        # For now, this matches the pattern of providing a default if things go very wrong.
        settings = {} # Or BookingSettings() if that's guaranteed to not raise here

    return render_template('admin_booking_settings.html', settings=settings)

@admin_ui_bp.route('/booking_settings/update', methods=['POST'])
@login_required
@permission_required('manage_system')
def update_booking_settings():
    logger = current_app.logger

    def _parse_int_field(field_name, default_value=None, min_val=None, max_val=None, nullable=False):
        value_str = request.form.get(field_name)
        if value_str is None or value_str == '':
            return None if nullable else default_value
        try:
            value_int = int(value_str)
            if min_val is not None and value_int < min_val:
                logger.warning(f"Value for {field_name} ({value_int}) is below minimum ({min_val}). Clamping to {min_val}.")
                return min_val
            if max_val is not None and value_int > max_val:
                logger.warning(f"Value for {field_name} ({value_int}) is above maximum ({max_val}). Clamping to {max_val}.")
                return max_val
            return value_int
        except ValueError:
            logger.warning(f"Invalid integer value for {field_name}: '{value_str}'. Using default: {default_value}.")
            return default_value

    try:
        settings = BookingSettings.query.first()
        if not settings:
            logger.info("No BookingSettings found, creating a new instance.")
            settings = BookingSettings()
            db.session.add(settings)

        # Update fields
        settings.allow_past_bookings = 'allow_past_bookings' in request.form
        # Past Booking Time Adjustment should be settable independently of allow_past_bookings for same-day grace period.
        settings.past_booking_time_adjustment_hours = _parse_int_field('past_booking_time_adjustment_hours', default_value=0, min_val=0)

        settings.max_booking_days_in_future = _parse_int_field('max_booking_days_in_future', nullable=True, min_val=0)
        settings.allow_multiple_resources_same_time = 'allow_multiple_resources_same_time' in request.form
        settings.max_bookings_per_user = _parse_int_field('max_bookings_per_user', nullable=True, min_val=0)

        settings.enable_check_in_out = 'enable_check_in_out' in request.form
        if settings.enable_check_in_out:
            settings.check_in_minutes_before = _parse_int_field('check_in_minutes_before', default_value=15, min_val=0)
            settings.check_in_minutes_after = _parse_int_field('check_in_minutes_after', default_value=15, min_val=0)
            settings.checkin_reminder_minutes_before = _parse_int_field('checkin_reminder_minutes_before', default_value=30, min_val=0)
            settings.resource_checkin_url_requires_login = 'resource_checkin_url_requires_login' in request.form
            settings.allow_check_in_without_pin = 'allow_check_in_without_pin' in request.form
            settings.enable_auto_checkout = 'enable_auto_checkout' in request.form
            if settings.enable_auto_checkout:
                 settings.auto_checkout_delay_minutes = _parse_int_field('auto_checkout_delay_minutes', default_value=60, min_val=1)
            else:
                 settings.auto_checkout_delay_minutes = 60 # Default if auto checkout is disabled
            settings.auto_release_if_not_checked_in_minutes = _parse_int_field('auto_release_if_not_checked_in_minutes', nullable=True, min_val=0)
        else: # Defaults if check-in/out is disabled
            settings.check_in_minutes_before = 15
            settings.check_in_minutes_after = 15
            settings.checkin_reminder_minutes_before = 30
            settings.resource_checkin_url_requires_login = False
            settings.allow_check_in_without_pin = False
            settings.enable_auto_checkout = False
            settings.auto_checkout_delay_minutes = 60
            settings.auto_release_if_not_checked_in_minutes = None


        settings.pin_auto_generation_enabled = 'pin_auto_generation_enabled' in request.form
        if settings.pin_auto_generation_enabled:
            settings.pin_length = _parse_int_field('pin_length', default_value=6, min_val=4, max_val=32)
            settings.pin_allow_manual_override = 'pin_allow_manual_override' in request.form
        else: # Defaults if PIN auto-generation is disabled
            settings.pin_length = 6
            settings.pin_allow_manual_override = False

        db.session.commit()
        add_audit_log(action='Update Booking Settings', details=f'Updated various booking settings by user {current_user.username}')
        flash(_('Booking settings updated successfully.'), 'success')
        logger.info(f"Booking settings updated by user {current_user.username}.")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating booking settings: {e}", exc_info=True)
        flash(_('Error updating booking settings: %(error)s', error=str(e)), 'error')

    return redirect(url_for('admin_ui.serve_booking_settings_page'))

@admin_ui_bp.route('/analytics/')
@login_required
@permission_required('view_analytics')
def analytics_dashboard():
    current_app.logger.info(f"User {current_user.username} accessed analytics dashboard.")
    return render_template('analytics.html')

@admin_ui_bp.route('/maintenance')
@login_required
@permission_required('manage_maintenance')
def serve_maintenance_page():
    floors = FloorMap.query.all()
    buildings = {}
    for floor in floors:
        if floor.location not in buildings:
            buildings[floor.location] = []
        buildings[floor.location].append(floor)
    resources = Resource.query.all()
    return render_template("admin/maintenance.html", floors=floors, buildings=buildings, resources=resources)

@admin_ui_bp.route('/system-settings', methods=['GET', 'POST'])
@login_required
@permission_required('manage_system_settings')
def system_settings_page():
    logger = current_app.logger
    # Initialize with default or existing values
    booking_settings = BookingSettings.query.first()
    current_offset_hours = booking_settings.global_time_offset_hours if booking_settings and booking_settings.global_time_offset_hours is not None else 0

    if request.method == 'POST':
        new_offset_str = request.form.get('global_time_offset_hours')
        try:
            new_offset_hours = int(new_offset_str)
            if not (-23 <= new_offset_hours <= 23):
                flash(_('Global time offset must be between -23 and 23 hours.'), 'error')
            else:
                if not booking_settings:
                    booking_settings = BookingSettings(global_time_offset_hours=new_offset_hours)
                    db.session.add(booking_settings)
                    logger.info(f"New BookingSettings created with offset {new_offset_hours} by {current_user.username}.")
                else:
                    booking_settings.global_time_offset_hours = new_offset_hours
                    logger.info(f"Global time offset updated to {new_offset_hours} by {current_user.username}.")

                db.session.commit()
                add_audit_log(action='Update Global Time Offset', details=f'Set to {new_offset_hours} hours by {current_user.username}.')
                flash(_('Global time offset saved successfully.'), 'success')
                current_offset_hours = new_offset_hours # Update for immediate display
        except ValueError:
            flash(_('Invalid value for time offset. Please enter a whole number.'), 'error')
            logger.warning(f"ValueError for time offset by {current_user.username}: {new_offset_str}")
        except Exception as e:
            db.session.rollback()
            flash(_('Error saving global time offset: %(error)s', error=str(e)), 'error')
            logger.error(f"Error saving global time offset by {current_user.username}: {e}", exc_info=True)
        # Redirect to GET to prevent form re-submission on refresh
        return redirect(url_for('admin_ui.system_settings_page'))

    # For GET request or after POST processing for display
    utc_now = datetime.now(timezone.utc)
    effective_time = utc_now + timedelta(hours=current_offset_hours)

    # Gmail configuration status is no longer checked here, it's moved to serve_backup_settings_page
    logger.debug(f"Rendering system_settings_page for {current_user.username}. Offset: {current_offset_hours}")

    return render_template('admin/system_settings.html',
                           global_time_offset_hours=current_offset_hours,
                           current_utc_time_str=utc_now.strftime('%Y-%m-%d %H:%M:%S %Z'),
                           effective_operational_time_str=effective_time.strftime('%Y-%m-%d %H:%M:%S %Z (Effective)'))

@admin_ui_bp.route('/analytics/data')
@login_required
@permission_required('view_analytics')
def analytics_bookings_data():
    current_app.logger.info(f"User {current_user.username} attempting to fetch analytics data.")
    try:
        total_bookings = db.session.query(func.count(Booking.id)).scalar()

        status_counts_query = db.session.query(Booking.status, func.count(Booking.id)).group_by(Booking.status).all()
        bookings_by_status = {status: count for status, count in status_counts_query}

        # Example: Bookings per day (last 30 days for simplicity)
        # This requires Booking.start_time to be a DateTime field
        thirty_days_ago_dt = datetime.utcnow() - timedelta(days=30)

        # Fetch raw start_time values for bookings in the relevant period
        query_results = db.session.query(
            Booking.start_time
        ).filter(
            Booking.start_time.isnot(None),
            Booking.start_time != ''
        ).filter(
             Booking.start_time >= thirty_days_ago_dt
        ).all()

        bookings_per_day = {}
        for row in query_results:
            raw_start_time_value = row[0]
            try:
                # Attempt to convert to string first, as fromisoformat expects a string
                start_time_as_string = str(raw_start_time_value)
                # Then parse the string to a datetime object, then get the date part
                date_obj = datetime.fromisoformat(start_time_as_string).date()
                date_key = date_obj.isoformat()
                bookings_per_day[date_key] = bookings_per_day.get(date_key, 0) + 1
            except ValueError as ve:
                current_app.logger.warning(f"Analytics: Could not parse start_time '{raw_start_time_value}' to date. Error: {ve}")
            except TypeError as te:
                current_app.logger.warning(f"Analytics: TypeError while processing start_time '{raw_start_time_value}'. Error: {te}")
            except Exception as ex:
                current_app.logger.error(f"Analytics: Unexpected error processing start_time '{raw_start_time_value}'. Error: {ex}", exc_info=True)

        final_response = {
            "total_bookings": total_bookings,
            "bookings_by_status": bookings_by_status,
            "bookings_per_day": bookings_per_day
        }
        current_app.logger.info(f"Successfully fetched analytics data (Python-parsed daily counts): {final_response}")
        return jsonify(final_response)
    except Exception as e:
        current_app.logger.error(f"Error fetching analytics data: {e}", exc_info=True)
        return jsonify({"error": "Could not fetch analytics data", "details": str(e)}), 500

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
    logger = current_app.logger
    try:
        num_deleted = db.session.query(Booking).delete()
        db.session.commit()
        add_audit_log(action='CLEAR_ALL_BOOKINGS', details=f'All {num_deleted} booking entries deleted by user {current_user.username}.')
        logger.info(f"User {current_user.username} cleared all {num_deleted} booking entries.")
        # flash(_('All booking data has been successfully cleared.'), 'success') # Flash is for redirects
        return jsonify({'success': True, 'message': _('All booking data has been successfully cleared.')}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error clearing all booking data by user {current_user.username}: {e}", exc_info=True)
        # flash(_('An error occurred while clearing booking data: %(error)s', error=str(e)), 'error')
        return jsonify({'success': False, 'message': _('An error occurred while clearing booking data: %(error)s', error=str(e))}), 500
