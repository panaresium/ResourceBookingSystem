from flask import Blueprint, render_template, current_app, jsonify, flash, redirect, url_for, request # Added request
from flask_login import login_required, current_user
from sqlalchemy import func, cast, Date, Time, extract # For analytics_bookings_data if merged here, or general use
import uuid # For task_id generation

# Assuming Booking, Resource, User models are in models.py
from models import Booking, Resource, User, FloorMap, BookingSettings # Added FloorMap
# Assuming db is in extensions.py
from extensions import db, socketio # Try to import socketio
# Assuming permission_required is in auth.py
from auth import permission_required # Corrected: auth.py is at root
from datetime import datetime, timedelta # Add datetime imports

# Import backup/restore functions
# Note: backup_bookings_csv is added here
from azure_backup import list_available_backups, restore_full_backup, \
                         list_available_booking_csv_backups, restore_bookings_from_csv_backup, \
                         backup_bookings_csv, verify_backup_set, delete_backup_set, \
                         delete_booking_csv_backup, verify_booking_csv_backup
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
    logger.info(f"User {current_user.username} accessed Admin Bookings page.")
    try:
        bookings_query = db.session.query(
            Booking.id,
            Booking.title,
            Booking.start_time,
            Booking.end_time,
            Booking.status,
            Booking.admin_deleted_message, # Added admin_deleted_message to query
            User.username.label('user_username'),
            Resource.name.label('resource_name')
        ).join(Resource, Booking.resource_id == Resource.id)\
         .join(User, Booking.user_name == User.username) # Ensure User model is imported

        all_bookings = bookings_query.order_by(Booking.start_time.desc()).all()

        bookings_list = []
        for booking_row in all_bookings:
            bookings_list.append({
                'id': booking_row.id,
                'title': booking_row.title,
                'start_time': booking_row.start_time,
                'end_time': booking_row.end_time,
                'status': booking_row.status,
                'user_username': booking_row.user_username,
                'resource_name': booking_row.resource_name,
                'admin_deleted_message': booking_row.admin_deleted_message # Added admin_deleted_message to dict
            })
        return render_template("admin_bookings.html", bookings=bookings_list)
    except Exception as e:
        logger.error(f"Error fetching bookings for admin page: {e}", exc_info=True)
        return render_template("admin_bookings.html", bookings=[], error="Could not load bookings.")

@admin_ui_bp.route('/backup_restore')
@login_required
@permission_required('manage_system')
def serve_backup_restore_page():
    current_app.logger.info(f"User {current_user.username} accessed Backup/Restore admin page.")
    # Existing logic for full backups (if any, or add similarly)
    full_backups = list_available_backups() # Assuming this lists full backup timestamps

    # New logic for booking CSV backups
    all_booking_csv_files = list_available_booking_csv_backups()

    # Pagination for Booking CSV Backups
    page = request.args.get('page', 1, type=int)
    per_page = 10 # Items per page
    total_items = len(all_booking_csv_files)
    total_pages = (total_items + per_page - 1) // per_page
    start_index = (page - 1) * per_page
    end_index = start_index + per_page
    paginated_booking_csv_backups = all_booking_csv_files[start_index:end_index]
    has_prev = page > 1
    has_next = page < total_pages

    return render_template(
        'admin_backup_restore.html',
        full_backups=full_backups,
        booking_csv_backups=paginated_booking_csv_backups,
        booking_csv_page=page,
        booking_csv_total_pages=total_pages,
        booking_csv_has_prev=has_prev,
        booking_csv_has_next=has_next
    )

@admin_ui_bp.route('/admin/restore_booking_csv/<timestamp_str>', methods=['POST'])
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

    return redirect(url_for('admin_ui.serve_backup_restore_page'))

@admin_ui_bp.route('/admin/manual_backup_bookings_csv', methods=['POST'])
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

    return redirect(url_for('admin_ui.serve_backup_restore_page'))

@admin_ui_bp.route('/admin/delete_booking_csv/<timestamp_str>', methods=['POST'])
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

    return redirect(url_for('admin_ui.serve_backup_restore_page'))


@admin_ui_bp.route('/save_booking_csv_schedule', methods=['POST']) # Corrected path to be relative to blueprint
@login_required
@permission_required('manage_system')
def save_booking_csv_schedule_route():
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

    return redirect(url_for('admin_ui.serve_backup_restore_page'))


@admin_ui_bp.route('/admin/verify_booking_csv/<timestamp_str>', methods=['POST'])
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

    return redirect(url_for('admin_ui.serve_backup_restore_page'))


@admin_ui_bp.route('/admin/verify_full_backup/<timestamp_str>', methods=['POST'])
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

    return redirect(url_for('admin_ui.serve_backup_restore_page'))


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

        # Handle past_booking_time_adjustment_hours
        past_booking_adjustment_str = request.form.get('past_booking_time_adjustment_hours')
        if past_booking_adjustment_str is not None and past_booking_adjustment_str.strip() != "":
            try:
                settings.past_booking_time_adjustment_hours = int(past_booking_adjustment_str)
            except ValueError:
                db.session.rollback()
                flash(_('Invalid input for "Past booking time adjustment". Please enter a valid integer.'), 'danger')
                return redirect(url_for('admin_ui.serve_booking_settings_page'))
        else:
            # If empty, set to default (e.g., 0 or a specific default from model)
            # Assuming model default is 0, or explicitly set here if form can send empty for "reset"
            settings.past_booking_time_adjustment_hours = 0


        db.session.commit()
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
