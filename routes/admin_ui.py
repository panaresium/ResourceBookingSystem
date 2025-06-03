from flask import Blueprint, render_template, current_app, jsonify, flash, redirect, url_for, request # Added request
from flask_login import login_required, current_user
from sqlalchemy import func # For analytics_bookings_data if merged here, or general use
import uuid # For task_id generation

# Assuming Booking, Resource, User models are in models.py
from models import Booking, Resource, User
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
                'resource_name': booking_row.resource_name
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
        booking_csv_pagination_current_page=page,
        booking_csv_pagination_total_pages=total_pages,
        booking_csv_pagination_has_prev=has_prev,
        booking_csv_pagination_has_next=has_next
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
    app_instance.logger.info(f"Manual booking CSV backup triggered by user {current_user.username if current_user else 'Unknown User'} with task ID {task_id}.")

    try:
        # backup_bookings_csv is expected to handle its own app_context for DB queries
        # and emit socketio messages if socketio_instance is provided.
        success = backup_bookings_csv(app=app_instance, socketio_instance=socketio_instance, task_id=task_id)
        if success:
            flash(_('Manual booking CSV backup initiated successfully. Check logs or SocketIO messages for progress/completion.'), 'success')
        else:
            flash(_('Manual booking CSV backup failed to complete successfully. Please check server logs.'), 'warning') # Changed to warning as some part might have run
    except Exception as e:
        app_instance.logger.error(f"Exception during manual booking CSV backup initiation by user {current_user.username if current_user else 'Unknown User'}: {str(e)}", exc_info=True)
        flash(_('An unexpected error occurred while starting the manual booking CSV backup. Check server logs.'), 'danger')

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
            flash(_('Booking CSV backup for %(timestamp)s successfully deleted (or was not found).', timestamp=timestamp_str), 'success')
        else:
            flash(_('Failed to delete booking CSV backup for %(timestamp)s. Check server logs.', timestamp=timestamp_str), 'danger')
    except Exception as e:
        app_instance.logger.error(f"Exception during booking CSV backup deletion for {timestamp_str} by user {current_user.username if current_user else 'Unknown User'}: {str(e)}", exc_info=True)
        flash(_('An unexpected error occurred while deleting the booking CSV backup for %(timestamp)s. Check server logs.', timestamp=timestamp_str), 'danger')

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
            flash(_('Booking CSV Backup Verification for "%(timestamp)s": File found at "%(path)s".', timestamp=timestamp_str, path=file_path), 'success')
        elif status == 'not_found':
            flash(_('Booking CSV Backup Verification for "%(timestamp)s": File NOT found at "%(path)s".', timestamp=timestamp_str, path=file_path), 'warning')
        else: # 'error' or 'unknown'
            flash(_('Booking CSV Backup Verification for "%(timestamp)s" FAILED: %(message)s', timestamp=timestamp_str, message=message), 'danger')

    except Exception as e:
        app_instance.logger.error(f"Exception during Booking CSV backup verification for {timestamp_str} by user {current_user.username if current_user else 'Unknown User'}: {str(e)}", exc_info=True)
        flash(_('An unexpected error occurred while verifying Booking CSV backup %(timestamp)s. Check server logs.', timestamp=timestamp_str), 'danger')

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
            flash(_('Backup set %(timestamp)s verified successfully. Status: %(status)s', timestamp=timestamp_str, status=status_message), 'success')
        elif verification_summary.get('status') in ['manifest_missing', 'manifest_corrupt', 'failed_verification', 'critical_error']:
            error_details = "; ".join(errors)
            flash(_('Backup set %(timestamp)s verification FAILED. Status: %(status)s. Errors: %(details)s', timestamp=timestamp_str, status=status_message, details=error_details), 'danger')
            # Log detailed checks for failed verifications
            # for check_item in checks:
            #     app_instance.logger.debug(f"Verification check for {timestamp_str} ({task_id}): {check_item}")
        else: # e.g. 'pending' or other statuses if verify_backup_set is asynchronous (currently it's synchronous)
            flash(_('Backup set %(timestamp)s verification status: %(status)s. Issues: %(errors)s', timestamp=timestamp_str, status=status_message, errors='; '.join(errors)), 'warning')

    except Exception as e:
        app_instance.logger.error(f"Exception during full backup verification for {timestamp_str} by user {current_user.username if current_user else 'Unknown User'}: {str(e)}", exc_info=True)
        flash(_('An unexpected error occurred while verifying backup set %(timestamp)s. Check server logs.', timestamp=timestamp_str), 'danger')

    return redirect(url_for('admin_ui.serve_backup_restore_page'))


@admin_ui_bp.route('/troubleshooting', methods=['GET'])
@login_required
@permission_required('manage_system') # Assuming same permission as backup/restore
def serve_troubleshooting_page():
    current_app.logger.info(f"User {current_user.username} accessed System Troubleshooting page.")
    return render_template('admin_troubleshooting.html')


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

        # Calculate the date 30 days ago
        thirty_days_ago = datetime.utcnow().date() - timedelta(days=30)

        # Query to get booking counts per resource per day for the last 30 days
        # We need to join Booking with Resource to get the resource name
        # We also need to group by resource name and the date part of start_time
        query_results = db.session.query(
            Resource.name,
            func.date(Booking.start_time).label('booking_date'),
            func.count(Booking.id).label('booking_count')
        ).join(Resource, Booking.resource_id == Resource.id) \
        .filter(func.date(Booking.start_time) >= thirty_days_ago) \
        .group_by(Resource.name, func.date(Booking.start_time)) \
        .order_by(Resource.name, func.date(Booking.start_time)) \
        .all()

        analytics_data = {}
        for resource_name, booking_date_obj, booking_count in query_results:
            booking_date_str = booking_date_obj.strftime('%Y-%m-%d')
            if resource_name not in analytics_data:
                analytics_data[resource_name] = []
            analytics_data[resource_name].append({
                "date": booking_date_str,
                "count": booking_count
            })

        current_app.logger.info(f"Successfully processed analytics data. Resources found: {len(analytics_data)}")
        return jsonify(analytics_data)

    except Exception as e:
        current_app.logger.error(f"Error generating analytics bookings data: {e}", exc_info=True)
        return jsonify({"error": "Could not process analytics data"}), 500

# Function to register this blueprint in the app factory
def init_admin_ui_routes(app):
    app.register_blueprint(admin_ui_bp)
