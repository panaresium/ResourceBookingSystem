import os
import uuid
import json
import math # Added for math.ceil
from datetime import datetime, timezone, timedelta, time

from flask import Blueprint, jsonify, request, current_app, url_for, Response
from flask_login import login_required, current_user
from sqlalchemy import func # For count query
# from sqlalchemy import or_ # For more complex queries if needed in get_audit_logs

# Relative imports from project structure
from auth import permission_required
from extensions import db, socketio # socketio might be None if not available
from models import AuditLog, User, Resource, FloorMap, Booking, Role, BookingSettings # Added BookingSettings
from utils import (
    add_audit_log,
    _get_map_configuration_data,
    _import_map_configuration_data,
    _get_resource_configurations_data, # For backup
    _get_user_configurations_data,    # For backup
    _import_resource_configurations_data, # For restore
    _import_user_configurations_data,    # For restore
    _load_schedule_from_json,
    _save_schedule_to_json,
    load_unified_backup_schedule_settings,
    save_unified_backup_schedule_settings,
    reschedule_unified_backup_jobs, # Moved from app_factory
)
# from app_factory import reschedule_unified_backup_jobs # Removed

# Conditional imports for Azure Backup functionality
# Ensure download_booking_data_json_backup is imported
try:
    print(f"DEBUG api_system.py: Attempting to import from azure_backup (again)...") # New debug
    from azure_backup import (
        create_full_backup,
        list_available_backups,
        restore_full_backup,
        verify_backup_set,
        delete_backup_set,
        _get_service_client, # For selective restore
        _client_exists, # For selective restore
        FLOOR_MAP_UPLOADS, # For selective restore media component
        RESOURCE_UPLOADS,  # For selective restore media component
        restore_database_component, # For selective restore
        download_map_config_component, # For selective restore
        restore_media_component, # For selective restore
        # Imports for new booking restore functionalities
        # list_available_booking_csv_backups, # Removed
        # restore_bookings_from_csv_backup, # Removed
        list_available_incremental_booking_backups, # Keeping non-CSV legacy for now
        restore_incremental_bookings, # Keeping non-CSV legacy for now
        restore_bookings_from_full_db_backup,
        backup_incremental_bookings, # Added for manual incremental backup
        backup_full_bookings_json, # Added for manual full JSON booking export
        list_available_full_booking_json_exports, # For listing full JSON exports
        restore_bookings_from_full_json_export, # For restoring from full JSON export
        delete_incremental_booking_backup, # For deleting incremental JSON backups
        # New Unified Booking Data Protection functions
        backup_booking_data_json_to_azure, # For manual full backup trigger
        list_booking_data_json_backups,    # For listing unified backups
        # restore_booking_data_from_json_backup, # This is now primarily for full restore, called by orchestrator
        delete_booking_data_json_backup,   # For deleting specific unified backups
        restore_booking_data_to_point_in_time, # New orchestrator for PIT restore
        download_booking_data_json_backup # For downloading unified backups
    )
    import azure_backup # To access module-level constants if needed by moved functions
    print(f"DEBUG api_system.py: Successfully imported from azure_backup (again). create_full_backup type: {type(create_full_backup)}") # New debug
except ImportError as e_detailed_azure_import: # Capture the exception instance
    print(f"CRITICAL_DEBUG api_system.py: Caught ImportError when importing from azure_backup. Exception type: {type(e_detailed_azure_import)}, Error: {e_detailed_azure_import}")
    import traceback # Import traceback module
    print("CRITICAL_DEBUG api_system.py: Full traceback of the import error:")
    traceback.print_exc() # Print the full traceback for the caught error

    # Assign None to all expected imports
    create_full_backup = None
    list_available_backups = None
    restore_full_backup = None
    verify_backup_set = None
    delete_backup_set = None
    _get_service_client = None
    _client_exists = None
    FLOOR_MAP_UPLOADS = None
    RESOURCE_UPLOADS = None
    restore_database_component = None
    download_map_config_component = None
    restore_media_component = None
    list_available_incremental_booking_backups = None
    restore_incremental_bookings = None
    restore_bookings_from_full_db_backup = None
    backup_incremental_bookings = None
    backup_full_bookings_json = None
    list_available_full_booking_json_exports = None
    restore_bookings_from_full_json_export = None
    delete_incremental_booking_backup = None
    backup_booking_data_json_to_azure = None
    list_booking_data_json_backups = None
    delete_booking_data_json_backup = None
    restore_booking_data_to_point_in_time = None
    download_booking_data_json_backup = None
    azure_backup = None

api_system_bp = Blueprint('api_system', __name__)

@api_system_bp.route('/api/admin/logs', methods=['GET'])
@login_required
@permission_required('view_audit_logs')
def get_audit_logs():
    """Fetches audit logs with pagination."""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 25, type=int) # Increased default per_page

        logs_query = AuditLog.query.order_by(AuditLog.timestamp.desc())

        search_term = request.args.get('search')
        if search_term:
            search_filter = f'%{search_term}%'
            # Using OR condition with | operator (specific to SQLAlchemy ORM)
            logs_query = logs_query.filter(
                AuditLog.username.ilike(search_filter) |
                AuditLog.action.ilike(search_filter) |
                AuditLog.details.ilike(search_filter)
            )

        total_logs = logs_query.count()
        logs_pagination = logs_query.paginate(page=page, per_page=per_page, error_out=False)
        logs = logs_pagination.items

        logs_data = [{
            'id': log.id,
            'timestamp': log.timestamp.replace(tzinfo=timezone.utc).isoformat(),
            'user_id': log.user_id,
            'username': log.username,
            'action': log.action,
            'details': log.details
        } for log in logs]

        current_app.logger.info(f"User {current_user.username} fetched audit logs page {page} with search '{search_term or ''}'.")
        return jsonify({
            'logs': logs_data,
            'total': total_logs,
            'current_page': page,
            'per_page': per_page,
            'has_next': logs_pagination.has_next,
            'has_prev': logs_pagination.has_prev,
            'next_num': logs_pagination.next_num,
            'prev_num': logs_pagination.prev_num,
            'pages': logs_pagination.pages
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching audit logs by {current_user.username}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to fetch audit logs due to a server error.'}), 500

@api_system_bp.route('/ping', methods=['GET'])
def ping():
    return jsonify(message='pong', timestamp=datetime.now(timezone.utc).isoformat()), 200

@api_system_bp.route('/debug/list_routes', methods=['GET'])
@login_required
# @permission_required('manage_system') # Or some debug permission
def debug_list_routes():
    # Ensure current_app is used if this is not part of app itself.
    # For blueprints, current_app is the way to access the app instance.
    output = []
    for rule in current_app.url_map.iter_rules():
        options = {}
        for arg in rule.arguments:
            options[arg] = f"[{arg}]"

        methods = ','.join(sorted(rule.methods))
        url = str(rule)
        line = f"{url:70s} {methods:30s} {rule.endpoint}" # Adjusted spacing
        output.append(line)

    output.sort()
    html_output = "<html><head><title>Registered Routes</title></head><body><h2>Application Routes:</h2><pre>"
    html_output += "\n".join(output)
    html_output += "</pre></body></html>"
    return html_output, 200

# --- Backup and Restore API Routes ---

# --- Unified Booking Data Protection API Routes (New) ---

@api_system_bp.route('/api/admin/booking_data_protection/manual_backup', methods=['POST'])
@login_required
@permission_required('manage_system') # Assuming same permission as other backup operations
def api_manual_booking_data_backup_json():
    task_id = uuid.uuid4().hex
    current_app.logger.info(f"User {current_user.username} initiated manual unified booking data backup (Task ID: {task_id}).")

    if not backup_booking_data_json_to_azure:
        current_app.logger.error("azure_backup.backup_booking_data_json_to_azure function not available.")
        if socketio:
            socketio.emit('booking_data_protection_backup_progress', {
                'task_id': task_id,
                'status': 'Error: Unified backup function not available on server.',
                'detail': 'CRITICAL_ERROR',
                'level': 'ERROR'
            })
        return jsonify({
            'success': False,
            'message': 'Manual unified booking data backup function is not available on the server.',
            'task_id': task_id
        }), 500

    try:
        success = backup_booking_data_json_to_azure(
            app=current_app._get_current_object(),
            socketio_instance=socketio,
            task_id=task_id
        )

        if success:
            current_app.logger.info(f"Manual unified booking data backup process (Task ID: {task_id}) started successfully.")
            add_audit_log(action="MANUAL_UNIFIED_BOOKING_BACKUP_STARTED", details=f"Task ID: {task_id}", user_id=current_user.id)
            return jsonify({
                'success': True,
                'message': 'Manual unified booking data backup process started successfully.',
                'task_id': task_id
            }), 200
        else:
            current_app.logger.error(f"Failed to start manual unified booking data backup (Task ID: {task_id}). Function returned non-success.")
            add_audit_log(action="MANUAL_UNIFIED_BOOKING_BACKUP_FAILED_START", details=f"Task ID: {task_id}. Function indicated failure.", user_id=current_user.id)
            return jsonify({
                'success': False,
                'message': 'Failed to start manual unified booking data backup. Check server logs for details.',
                'task_id': task_id
            }), 500
    except Exception as e:
        current_app.logger.exception(f"Exception during manual unified booking data backup initiation (Task ID: {task_id}):")
        add_audit_log(action="MANUAL_UNIFIED_BOOKING_BACKUP_ERROR", details=f"Task ID: {task_id}. Exception: {str(e)}", user_id=current_user.id)
        if socketio:
            socketio.emit('booking_data_protection_backup_progress', {
                'task_id': task_id,
                'status': f'Error: {str(e)}',
                'detail': 'EXCEPTION',
                'level': 'ERROR'
            })
        return jsonify({
            'success': False,
            'message': f'An unexpected error occurred: {str(e)}',
            'task_id': task_id
        }), 500

@api_system_bp.route('/api/admin/booking_data_protection/list_backups', methods=['GET'])
@login_required
@permission_required('manage_system')
def api_list_booking_data_backups():
    current_app.logger.info(f"User {current_user.username} requested list of unified booking data backups.")
    if not list_booking_data_json_backups:
        return jsonify({'success': False, 'message': 'Functionality to list unified backups is not available.', 'backups': []}), 501
    try:
        backups = list_booking_data_json_backups() # This should return 'filename', 'type', 'timestamp_str' (ISO)
        return jsonify({'success': True, 'backups': backups}), 200
    except Exception as e:
        current_app.logger.exception("Exception listing unified booking data backups:")
        return jsonify({'success': False, 'message': f'Error: {str(e)}', 'backups': []}), 500

@api_system_bp.route('/api/admin/booking_data_protection/restore', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_unified_booking_data_point_in_time_restore(): # Renamed for clarity
    task_id = uuid.uuid4().hex
    data = request.get_json()

    filename = data.get('filename')
    backup_type = data.get('backup_type')
    backup_timestamp_iso = data.get('backup_timestamp_iso')

    if not all([filename, backup_type, backup_timestamp_iso]):
        return jsonify({'success': False, 'message': 'Missing required parameters: filename, backup_type, and backup_timestamp_iso are required.', 'task_id': task_id}), 400

    current_app.logger.info(f"User {current_user.username} initiated Point-in-Time booking data restore (Task {task_id}): File='{filename}', Type='{backup_type}', Timestamp='{backup_timestamp_iso}'")

    if not restore_booking_data_to_point_in_time:
        current_app.logger.error("azure_backup.restore_booking_data_to_point_in_time function not available.")
        return jsonify({'success': False, 'message': 'Point-in-time restore function not available on server.', 'task_id': task_id}), 501

    try:
        summary = restore_booking_data_to_point_in_time(
            app=current_app._get_current_object(),
            selected_filename=filename,
            selected_type=backup_type,
            selected_timestamp_iso=backup_timestamp_iso,
            socketio_instance=socketio,
            task_id=task_id
        )
        # The summary from restore_booking_data_to_point_in_time should contain overall status and messages.
        add_audit_log(
            action="POINT_IN_TIME_RESTORE_BOOKING_DATA",
            details=f"Task {task_id}, File {filename}, Type {backup_type}, Timestamp {backup_timestamp_iso}. Summary: {json.dumps(summary)}",
            user_id=current_user.id
        )
        # Return success:True because the API call itself was handled. The functional success is in summary.status.
        return jsonify({'success': True, 'summary': summary, 'task_id': task_id}), 200
    except Exception as e:
        current_app.logger.exception(f"Exception during point-in-time booking data restore (Task {task_id}):")
        add_audit_log(
            action="POINT_IN_TIME_RESTORE_BOOKING_DATA_ERROR",
            details=f"Task {task_id}, File {filename}, Type {backup_type}, Timestamp {backup_timestamp_iso}. Error: {str(e)}",
            user_id=current_user.id
        )
        # Construct a summary-like object for consistency in error reporting on client-side
        error_summary = {'status': 'failure', 'message': f'An unexpected error occurred: {str(e)}', 'errors': [str(e)]}
        return jsonify({'success': False, 'message': str(e), 'task_id': task_id, 'summary': error_summary}), 500

@api_system_bp.route('/api/admin/booking_data_protection/delete', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_delete_booking_data_backup():
    task_id = uuid.uuid4().hex # For potential future SocketIO use, though delete is often quick
    data = request.get_json()
    if not data or 'backup_filename' not in data or 'backup_type' not in data: # Added backup_type
        return jsonify({'success': False, 'message': 'Backup filename and type are required.', 'task_id': task_id}), 400

    filename = data['backup_filename']
    backup_type = data['backup_type'] # Get backup_type from request
    current_app.logger.info(f"User {current_user.username} initiated deletion of unified booking data backup (Task {task_id}): {filename}, Type: {backup_type}")

    if not delete_booking_data_json_backup:
        return jsonify({'success': False, 'message': 'Delete function for unified backups not available.', 'task_id': task_id}), 501

    try:
        success = delete_booking_data_json_backup(
            filename=filename,
            backup_type=backup_type, # Pass backup_type to backend
            socketio_instance=socketio,
            task_id=task_id
        )
        if success:
            add_audit_log(action="DELETE_UNIFIED_BOOKING_BACKUP_SUCCESS", details=f"Task {task_id}, Filename {filename}, Type {backup_type}.", user_id=current_user.id)
            return jsonify({'success': True, 'message': f"Unified backup '{filename}' (type: {backup_type}) deleted successfully.", 'task_id': task_id}), 200
        else:
            add_audit_log(action="DELETE_UNIFIED_BOOKING_BACKUP_FAILED", details=f"Task {task_id}, Filename {filename}, Type {backup_type}. Deletion function indicated failure.", user_id=current_user.id)
            return jsonify({'success': False, 'message': f"Failed to delete unified backup '{filename}' (type: {backup_type}). See server logs.", 'task_id': task_id}), 500
    except Exception as e:
        current_app.logger.exception(f"Exception during deletion of unified booking data backup (Task {task_id}):")
        add_audit_log(action="DELETE_UNIFIED_BOOKING_BACKUP_ERROR", details=f"Task {task_id}, Filename {filename}, Type {backup_type}, Error: {str(e)}", user_id=current_user.id)
        return jsonify({'success': False, 'message': str(e), 'task_id': task_id}), 500

# --- END Unified Booking Data Protection API Routes ---

@api_system_bp.route('/api/admin/booking_data_protection/download/<string:backup_type>/<path:filename>', methods=['GET'])
@login_required
@permission_required('manage_system')
def api_download_booking_data_backup(backup_type, filename):
    current_app.logger.info(f"User {current_user.username} requested download of unified backup: Type='{backup_type}', Filename='{filename}'.")

    if not download_booking_data_json_backup:
        current_app.logger.error("Download function (download_booking_data_json_backup) not available.")
        add_audit_log(action="DOWNLOAD_UNIFIED_BACKUP_ERROR", details=f"Attempt by {current_user.username} for {filename} ({backup_type}). Function not available.", user_id=current_user.id)
        return jsonify({'success': False, 'message': 'Download functionality is not available on the server.'}), 501

    try:
        file_content = download_booking_data_json_backup(filename=filename, backup_type=backup_type)

        if file_content is not None:
            current_app.logger.info(f"Successfully prepared download for '{filename}' ({backup_type}). Size: {len(file_content)} bytes.")
            # Note: Audit log for success might be too verbose for every download. Consider if needed.
            # add_audit_log(action="DOWNLOAD_UNIFIED_BACKUP_SUCCESS", details=f"User {current_user.username} downloaded {filename} ({backup_type}).", user_id=current_user.id)
            return Response(
                file_content,
                mimetype='application/json',
                headers={"Content-Disposition": f"attachment;filename={filename}"}
            )
        else:
            current_app.logger.warning(f"File content not found or error during download for '{filename}' ({backup_type}).")
            add_audit_log(action="DOWNLOAD_UNIFIED_BACKUP_NOT_FOUND", details=f"Attempt by {current_user.username} for {filename} ({backup_type}). File not found or download failed.", user_id=current_user.id)
            return jsonify({'success': False, 'message': 'File not found or failed to download.'}), 404
    except Exception as e:
        current_app.logger.exception(f"Unexpected error during download of unified backup '{filename}' ({backup_type}):")
        add_audit_log(action="DOWNLOAD_UNIFIED_BACKUP_EXCEPTION", details=f"Attempt by {current_user.username} for {filename} ({backup_type}). Exception: {str(e)}", user_id=current_user.id)
        return jsonify({'success': False, 'message': f'An unexpected error occurred: {str(e)}'}), 500

# --- Unified Backup Schedule Settings API Routes ---
@api_system_bp.route('/api/admin/settings/unified_backup_schedule', methods=['GET'])
@login_required
@permission_required('manage_system')
def get_unified_backup_schedule():
    current_app.logger.info(f"User {current_user.username} fetching unified backup schedule settings.")
    try:
        settings = load_unified_backup_schedule_settings(current_app) # Pass current_app
        return jsonify(settings), 200
    except Exception as e:
        current_app.logger.exception("Error fetching unified backup schedule settings:")
        # Fallback to default might be too complex here if current_app.config isn't fully available
        # Best to signal error clearly.
        return jsonify({'error': f'Failed to load unified backup schedule settings: {str(e)}'}), 500

@api_system_bp.route('/api/admin/settings/unified_backup_schedule', methods=['POST'])
@login_required
@permission_required('manage_system')
def update_unified_backup_schedule():
    current_app.logger.info(f"User {current_user.username} attempting to update unified backup schedule.")
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid input. JSON data expected.'}), 400

    try:
        success, message = save_unified_backup_schedule_settings(data)
        if success:
            current_app.logger.info(f"Unified backup schedule updated by {current_user.username}. New settings: {data}")
            add_audit_log(action="UPDATE_UNIFIED_BACKUP_SCHEDULE",
                          details=f"User {current_user.username} updated unified backup schedule. New settings: {json.dumps(data)}",
                          user_id=current_user.id)
            try:
                reschedule_unified_backup_jobs(current_app._get_current_object())
                current_app.logger.info("Unified backup jobs rescheduled successfully after settings update.")
                message += " Scheduler jobs updated." # Append to original success message
            except Exception as e_reschedule:
                current_app.logger.exception("Error rescheduling unified backup jobs after settings update:")
                # Log the error, but don't fail the entire operation if saving settings worked.
                # The message to the user will indicate settings were saved, but rescheduling might have an issue.
                message += " However, an error occurred while attempting to update the scheduler jobs. Check server logs."
            return jsonify({'success': True, 'message': message}), 200
        else:
            add_audit_log(action="UPDATE_UNIFIED_BACKUP_SCHEDULE_FAILED",
                          details=f"Error: {message}. Attempted data: {json.dumps(data)}",
                          user_id=current_user.id)
            return jsonify({'success': False, 'message': message}), 400 # 400 for validation errors
    except Exception as e:
        current_app.logger.exception("Error updating unified backup schedule settings:")
        add_audit_log(action="UPDATE_UNIFIED_BACKUP_SCHEDULE_ERROR",
                      details=f"Exception: {str(e)}. Attempted data: {json.dumps(data)}",
                      user_id=current_user.id)
        return jsonify({'success': False, 'message': f'Error updating unified backup schedule: {str(e)}'}), 500

# --- END Unified Backup Schedule Settings API Routes ---

@api_system_bp.route('/api/admin/one_click_backup', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_one_click_backup():
    current_app.logger.info(f"User {current_user.username} initiated one-click backup.")
    task_id = uuid.uuid4().hex
    current_app.logger.info(f"Generated task_id {task_id} for one-click backup.")

    print(f"DEBUG api_one_click_backup: Value of 'create_full_backup' at function entry: {str(create_full_backup)}, Type: {type(create_full_backup)}")
    if not create_full_backup:
        current_app.logger.error("Azure backup module not available for one-click backup.")
        return jsonify({'success': False, 'message': "Azure backup module is not available. Please ensure the 'azure-storage-file-share' package is installed and the 'AZURE_STORAGE_CONNECTION_STRING' environment variable is correctly configured.", 'task_id': task_id}), 501
    try:
        timestamp_str = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        map_config_data = _get_map_configuration_data() # Uses models directly, ensure they are imported
        resource_config_data = _get_resource_configurations_data()
        user_config_data = _get_user_configurations_data()

        success = create_full_backup(
            timestamp_str,
            map_config_data=map_config_data,
            resource_configs_data=resource_config_data,
            user_configs_data=user_config_data,
            socketio_instance=socketio, # socketio from extensions
            task_id=task_id
        )
        if success:
            message = f"Backup process initiated with timestamp {timestamp_str}. See live logs for completion status."
            current_app.logger.info(f"One-click backup process for task {task_id} (timestamp {timestamp_str}) completed with overall success: {success}.")
            add_audit_log(action="ONE_CLICK_BACKUP_COMPLETED", details=f"Task {task_id}, Timestamp {timestamp_str}, Success: {success}", user_id=current_user.id)
            return jsonify({'success': True, 'message': message, 'task_id': task_id, 'timestamp': timestamp_str}), 200
        else:
            message = "Backup process initiated but reported failure. Check server logs for details."
            current_app.logger.error(f"One-click backup process for task {task_id} (timestamp {timestamp_str}) failed.")
            add_audit_log(action="ONE_CLICK_BACKUP_COMPLETED_WITH_FAILURES", details=f"Task {task_id}, Timestamp {timestamp_str}, Success: {success}", user_id=current_user.id)
            return jsonify({'success': False, 'message': message, 'task_id': task_id}), 500
    except Exception as e:
        current_app.logger.exception(f"Exception during one-click backup (task {task_id}) initiated by {current_user.username}:")
        add_audit_log(action="ONE_CLICK_BACKUP_ERROR", details=f"Task {task_id}, Exception: {str(e)}", user_id=current_user.id)
        return jsonify({'success': False, 'message': f'An unexpected error occurred: {str(e)}', 'task_id': task_id}), 500

@api_system_bp.route('/api/admin/list_backups', methods=['GET'])
@login_required
@permission_required('manage_system')
def api_list_backups():
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 5, type=int) # Default per_page to 5

        if page < 1:
            page = 1
        if per_page < 1:
            per_page = 5 # Ensure per_page is at least 1, default to 5

        current_app.logger.info(f"User {current_user.username} requested list of available backups (page: {page}, per_page: {per_page}).")

        if not list_available_backups:
            current_app.logger.error("Azure backup module not available for listing backups.")
            return jsonify({'success': False, 'message': 'Backup module is not configured or available.', 'backups': [], 'page': page, 'per_page': per_page, 'total_items': 0, 'total_pages': 0, 'has_next': False, 'has_prev': False}), 500

        all_backups = list_available_backups()
        total_items = len(all_backups)
        total_pages = math.ceil(total_items / per_page) if per_page > 0 else 0

        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        paginated_backups = all_backups[start_index:end_index]

        has_next = page < total_pages
        has_prev = page > 1

        current_app.logger.info(f"Found {total_items} available backups. Returning {len(paginated_backups)} for page {page}.")
        return jsonify({
            'success': True,
            'backups': paginated_backups,
            'page': page,
            'per_page': per_page,
            'total_items': total_items,
            'total_pages': total_pages,
            'has_next': has_next,
            'has_prev': has_prev
        }), 200
    except Exception as e:
        current_app.logger.exception(f"Exception listing available backups for user {current_user.username}:")
        # Attempt to return pagination fields even on error, with zero/false values
        return jsonify({
            'success': False,
            'message': f'An error occurred while listing backups: {str(e)}',
            'backups': [],
            'page': request.args.get('page', 1, type=int), # Try to get requested page
            'per_page': request.args.get('per_page', 5, type=int), # Try to get requested per_page
            'total_items': 0,
            'total_pages': 0,
            'has_next': False,
            'has_prev': False
        }), 500

@api_system_bp.route('/api/admin/one_click_restore', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_one_click_restore():
    data = request.get_json()
    task_id = uuid.uuid4().hex

    if not data or 'backup_timestamp' not in data:
        current_app.logger.warning(f"Restore attempt (task {task_id}) with missing backup_timestamp.")
        return jsonify({'success': False, 'message': 'Backup timestamp is required.', 'task_id': task_id}), 400

    backup_timestamp = data['backup_timestamp']
    current_app.logger.info(f"User {current_user.username} initiated restore (task {task_id}) for timestamp: {backup_timestamp}.")

    if not restore_full_backup or not _import_map_configuration_data or not _import_resource_configurations_data or not _import_user_configurations_data :
        current_app.logger.error(f"Azure backup or import helpers not available for restore (task {task_id}).")
        if socketio:
             socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Restore module or helpers not configured on server.', 'detail': 'ERROR'})
        return jsonify({'success': False, 'message': 'Restore module or helpers not configured or available.', 'task_id': task_id}), 500

    try:
        if socketio:
            socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Restore process starting...', 'detail': f'Timestamp: {backup_timestamp}'})

        # Note: The last returned item (actions_list) is for dry_run, so we use _ here.
        restored_db_path, map_config_json_path, resource_configs_json_path, user_configs_json_path, _ = restore_full_backup(
            backup_timestamp,
            socketio_instance=socketio,
            task_id=task_id
        )

        if not restored_db_path: # Indicates a failure in the azure_backup.restore_full_backup download/untar phase
            message = f"Restore (task {task_id}) failed during file download/extraction phase for timestamp {backup_timestamp}."
            current_app.logger.error(message)
            add_audit_log(action="ONE_CLICK_RESTORE_FILE_OPS_FAILED", details=message, user_id=current_user.id)
            # SocketIO message should have been emitted by restore_full_backup
            return jsonify({'success': False, 'message': message, 'task_id': task_id}), 500

        current_app.logger.info(f"Database restored (task {task_id}) for backup {backup_timestamp} to {restored_db_path}.")

        # Import resource configurations
        resource_import_summary_msg = "Resource configurations file was not part of this backup or was not downloaded."
        if resource_configs_json_path and os.path.exists(resource_configs_json_path):
            current_app.logger.info(f"Resource configs JSON {resource_configs_json_path} (task {task_id}) downloaded for {backup_timestamp}.")
            if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Importing resource configurations...', 'detail': resource_configs_json_path})
            try:
                with open(resource_configs_json_path, 'r', encoding='utf-8') as f: resource_configs_to_import = json.load(f)
                res_created, res_updated, res_errors = _import_resource_configurations_data(resource_configs_to_import) # Pass db instance
                resource_import_summary_msg = f"Resource config import: {res_created} created, {res_updated} updated."
                if res_errors: resource_import_summary_msg += f" Errors: {len(res_errors)} (see logs for details)."
                if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': f'Resource configurations import: {resource_import_summary_msg}', 'detail': json.dumps(res_errors) if res_errors else 'Completed.'})
                current_app.logger.info(f"Resource configurations import (task {task_id}) summary: {resource_import_summary_msg} Errors: {res_errors}")
            except Exception as res_import_exc:
                resource_import_summary_msg = f"Error processing resource_configs file {resource_configs_json_path} (task {task_id}): {str(res_import_exc)}"
                current_app.logger.exception(resource_import_summary_msg)
                if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Error during resource configurations import.', 'detail': str(res_import_exc)})
            finally:
                try: os.remove(resource_configs_json_path)
                except OSError as e_remove: current_app.logger.error(f"Error removing temp resource_configs file {resource_configs_json_path} (task {task_id}): {e_remove}")
        else:
            current_app.logger.info(f"No resource_configs.json file for {backup_timestamp} (task {task_id}). Skipping resource configurations import.")
            if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Resource configurations import skipped (no file).'})

        # Import map configurations
        map_import_summary_msg = "Map configuration file was not part of this backup or was not downloaded."
        if map_config_json_path and os.path.exists(map_config_json_path):
            current_app.logger.info(f"Map config JSON {map_config_json_path} (task {task_id}) downloaded for {backup_timestamp}.")
            if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Importing map configuration...', 'detail': map_config_json_path})
            try:
                with open(map_config_json_path, 'r', encoding='utf-8') as f: map_config_data_to_import = json.load(f)
                import_summary, import_status_code = _import_map_configuration_data(map_config_data_to_import) # Uses models directly
                map_import_summary_msg = f"Map configuration import from {backup_timestamp} completed with status {import_status_code}."
                if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': f'Map configuration import status: {import_status_code}', 'detail': json.dumps(import_summary)})
                if import_status_code >= 400: current_app.logger.error(f"Failed to import map config (task {task_id}): {json.dumps(import_summary)}")
                else: current_app.logger.info(f"Successfully imported map config (task {task_id}).")
            except Exception as map_import_exc:
                map_import_summary_msg = f"Error processing map config file {map_config_json_path} (task {task_id}): {str(map_import_exc)}"
                current_app.logger.exception(map_import_summary_msg)
                if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Error during map configuration import.', 'detail': str(map_import_exc)})
            finally:
                try: os.remove(map_config_json_path)
                except OSError as e_remove: current_app.logger.error(f"Error removing temp map config file {map_config_json_path} (task {task_id}): {e_remove}")
        else:
            current_app.logger.info(f"No map config file for {backup_timestamp} (task {task_id}). Skipping map import.")
            if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Map configuration import skipped (no file).'})

        # Import user/role configurations
        user_import_summary_msg = "User/role configurations file was not part of this backup or was not downloaded."
        if user_configs_json_path and os.path.exists(user_configs_json_path):
            current_app.logger.info(f"User/role configs JSON {user_configs_json_path} (task {task_id}) downloaded for {backup_timestamp}.")
            if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Importing user/role configurations...', 'detail': user_configs_json_path})
            try:
                with open(user_configs_json_path, 'r', encoding='utf-8') as f: user_configs_to_import = json.load(f)
                r_created, r_updated, u_created, u_updated, u_errors = _import_user_configurations_data(user_configs_to_import) # Pass db instance
                user_import_summary_msg = f"User/Role config import: Roles ({r_created} created, {r_updated} updated), Users ({u_created} created, {u_updated} updated)."
                if u_errors: user_import_summary_msg += f" Errors: {len(u_errors)} (see logs for details)."
                if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': f'User/role configurations import: {user_import_summary_msg}', 'detail': json.dumps(u_errors) if u_errors else 'Completed.'})
                current_app.logger.info(f"User/role configurations import (task {task_id}) summary: {user_import_summary_msg} Errors: {u_errors}")
            except Exception as user_import_exc:
                user_import_summary_msg = f"Error processing user_configs file {user_configs_json_path} (task {task_id}): {str(user_import_exc)}"
                current_app.logger.exception(user_import_summary_msg)
                if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Error during user/role configurations import.', 'detail': str(user_import_exc)})
            finally:
                try: os.remove(user_configs_json_path)
                except OSError as e_remove: current_app.logger.error(f"Error removing temp user_configs file {user_configs_json_path} (task {task_id}): {e_remove}")
        else:
            current_app.logger.info(f"No user_configs.json file for {backup_timestamp} (task {task_id}). Skipping user/role configurations import.")
            if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': 'User/role configurations import skipped (no file).'})

        final_message = (
            f"Restore (task {task_id}) from {backup_timestamp} completed. "
            f"DB restored. {map_import_summary_msg} {resource_import_summary_msg} {user_import_summary_msg} "
            "Application restart is recommended."
        )
        current_app.logger.info(final_message)
        add_audit_log(action="ONE_CLICK_RESTORE_COMPLETED", details=final_message, user_id=current_user.id)
        if socketio:
            socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Restore process fully completed. Please restart application.', 'detail': 'SUCCESS'})
        return jsonify({'success': True, 'message': final_message, 'task_id': task_id}), 200
    except Exception as e:
        current_app.logger.exception(f"Critical exception during restore (task {task_id}) for {backup_timestamp}:")
        add_audit_log(action="ONE_CLICK_RESTORE_CRITICAL_ERROR", details=f"Task {task_id}, Exception: {str(e)} for {backup_timestamp}", user_id=current_user.id)
        if socketio:
            socketio.emit('restore_progress', {'task_id': task_id, 'status': f'Critical error during restore: {str(e)}', 'detail': 'ERROR'})
        return jsonify({'success': False, 'message': f'An unexpected critical error: {str(e)}', 'task_id': task_id}), 500

@api_system_bp.route('/api/admin/restore_dry_run/<string:backup_timestamp>', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_restore_dry_run(backup_timestamp):
    task_id = uuid.uuid4().hex
    current_app.logger.info(f"User {current_user.username} initiated RESTORE DRY RUN (task {task_id}) for timestamp: {backup_timestamp}.")

    if not restore_full_backup: # This also implies azure_backup module itself is missing
        current_app.logger.error(f"Azure backup module not available for restore dry run (task {task_id}).")
        if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Restore Dry Run: Backup module not configured on server.', 'detail': 'ERROR', 'actions': []})
        return jsonify({'success': False, 'message': 'Backup module is not configured or available.', 'task_id': task_id, 'actions': []}), 500

    try:
        if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Restore Dry Run starting...', 'detail': f'Timestamp: {backup_timestamp}', 'actions': []})

        # restore_full_backup with dry_run=True returns paths as None and a list of actions
        _, _, _, _, actions_list = restore_full_backup(
            backup_timestamp,
            dry_run=True,
            socketio_instance=socketio,
            task_id=task_id
        )
        final_actions_list = list(actions_list)

        message = f"Restore Dry Run (task {task_id}) for {backup_timestamp} completed. Actions: {len(final_actions_list)}."
        current_app.logger.info(message)
        add_audit_log(action="RESTORE_DRY_RUN_COMPLETED", details=f"{message} User: {current_user.username}. Actions: {json.dumps(final_actions_list)}", user_id=current_user.id)
        if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Restore Dry Run completed.', 'detail': 'SUCCESS', 'actions': final_actions_list})
        return jsonify({'success': True, 'message': message, 'task_id': task_id, 'actions': final_actions_list}), 200

    except Exception as e:
        current_app.logger.exception(f"Critical exception during restore dry run (task {task_id}) for {backup_timestamp}:")
        add_audit_log(action="RESTORE_DRY_RUN_CRITICAL_ERROR", details=f"Task {task_id}, Exception: {str(e)} for {backup_timestamp}", user_id=current_user.id)
        if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': f'DRY RUN: Critical error: {str(e)}', 'detail': 'ERROR', 'actions': []})
        return jsonify({'success': False, 'message': f'An unexpected critical error during dry run: {str(e)}', 'task_id': task_id, 'actions': []}), 500

@api_system_bp.route('/api/admin/selective_restore', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_selective_restore():
    data = request.get_json()
    task_id = uuid.uuid4().hex

    if not data: return jsonify({'success': False, 'message': 'Invalid input. JSON data expected.', 'task_id': task_id}), 400
    backup_timestamp = data.get('backup_timestamp')
    components = data.get('components', [])

    if not backup_timestamp: return jsonify({'success': False, 'message': 'Backup timestamp is required.', 'task_id': task_id}), 400
    if not components or not isinstance(components, list) or not all(isinstance(c, str) for c in components) or not components:
        return jsonify({'success': False, 'message': 'Components list must be a non-empty list of strings.', 'task_id': task_id}), 400

    current_app.logger.info(f"User {current_user.username} initiated SELECTIVE RESTORE (task {task_id}) for ts: {backup_timestamp}, components: {components}.")
    if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Selective Restore process starting...', 'detail': f'Timestamp: {backup_timestamp}, Components: {", ".join(components)}'})

    overall_success = True
    actions_performed_summary = []

    if not azure_backup or not _get_service_client or not restore_database_component or not download_map_config_component or not restore_media_component or not _client_exists:
        message = "Selective Restore failed: Azure Backup module or one of its components is not configured/available."
        current_app.logger.error(message)
        if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': message, 'detail': 'ERROR'})
        return jsonify({'success': False, 'message': message, 'task_id': task_id}), 500

    try:
        service_client = _get_service_client()
        if not service_client:
             message = "Selective Restore failed: Could not get Azure service client."
             current_app.logger.error(message)
             if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': message, 'detail': 'ERROR'})
             return jsonify({'success': False, 'message': message, 'task_id': task_id}), 500

        db_share_client = service_client.get_share_client(os.environ.get('AZURE_DB_SHARE', 'db-backups'))
        config_share_client = service_client.get_share_client(os.environ.get('AZURE_CONFIG_SHARE', 'config-backups'))
        media_share_client = service_client.get_share_client(os.environ.get('AZURE_MEDIA_SHARE', 'media'))

        # Database Component
        if 'database' in components:
            if not _client_exists(db_share_client):
                msg = f"DB component skipped: Share '{db_share_client.share_name}' not found or accessible."
                actions_performed_summary.append(msg)
                current_app.logger.warning(msg)
                overall_success = False
            else:
                db_success, db_msg, _, _ = restore_database_component(backup_timestamp, db_share_client, False, socketio, task_id)
                actions_performed_summary.append(f"Database: {db_msg}")
                if not db_success: overall_success = False

        # Map Config Component (Download and Import)
        if 'map_config' in components:
            if not _client_exists(config_share_client):
                msg = f"Map Config component skipped: Share '{config_share_client.share_name}' not found or accessible."
                actions_performed_summary.append(msg)
                current_app.logger.warning(msg)
            else:
                mc_success, mc_msg, _, mc_path = download_map_config_component(backup_timestamp, config_share_client, False, socketio, task_id)
                actions_performed_summary.append(f"Map Config Download: {mc_msg}")
                if mc_success and mc_path and os.path.exists(mc_path):
                    try:
                        with open(mc_path, 'r', encoding='utf-8') as f: map_data = json.load(f)
                        import_summary, import_status = _import_map_configuration_data(map_data)
                        msg = f"Map Config Import: Status {import_status}. Summary: {json.dumps(import_summary)}"
                        actions_performed_summary.append(msg)
                        if import_status >= 400: overall_success = False
                        if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': msg})
                    except Exception as e_import:
                        msg = f"Map Config Import Error: {str(e_import)}"
                        actions_performed_summary.append(msg)
                        current_app.logger.exception(msg)
                        if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': msg, 'detail': 'ERROR'})
                        overall_success = False
                    finally:
                        if os.path.exists(mc_path): os.remove(mc_path)
                elif not mc_success: overall_success = False

        # Media Components (Floor Maps, Resource Uploads)
        for media_comp in ['floor_maps', 'resource_uploads']:
            if media_comp in components:
                if not _client_exists(media_share_client):
                    msg = f"{media_comp.replace('_',' ').title()} component skipped: Share '{media_share_client.share_name}' not found."
                    actions_performed_summary.append(msg)
                    current_app.logger.warning(msg)
                    overall_success = False
                else:
                    azure_backup_constant = FLOOR_MAP_UPLOADS if media_comp == 'floor_maps' else RESOURCE_UPLOADS
                    local_folder_name = "floor_map_uploads" if media_comp == 'floor_maps' else "resource_uploads"
                    media_success, media_msg, _ = restore_media_component(backup_timestamp, media_comp.replace('_',' ').title(), azure_backup_constant, local_folder_name, media_share_client, False, socketio, task_id)
                    actions_performed_summary.append(f"{media_comp.replace('_',' ').title()}: {media_msg}")
                    if not media_success: overall_success = False

        final_msg = f"Selective restore (task {task_id}) for {backup_timestamp} finished. Overall Success: {overall_success}. Details: {'; '.join(actions_performed_summary)}"
        current_app.logger.info(final_msg)
        add_audit_log(action="SELECTIVE_RESTORE_COMPLETED", details=final_msg, user_id=current_user.id)
        if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Selective restore completed.', 'detail': 'SUCCESS' if overall_success else 'PARTIAL_FAILURE', 'summary': actions_performed_summary})
        return jsonify({'success': overall_success, 'message': final_msg, 'task_id': task_id, 'summary': actions_performed_summary}), 200

    except Exception as e:
        error_msg = f"Critical error during selective restore (task {task_id}) for {backup_timestamp}: {str(e)}"
        current_app.logger.exception(error_msg)
        add_audit_log(action="SELECTIVE_RESTORE_CRITICAL_ERROR", details=error_msg, user_id=current_user.id)
        if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': error_msg, 'detail': 'ERROR'})
        return jsonify({'success': False, 'message': error_msg, 'task_id': task_id}), 500


# --- Selective Booking Restore API Routes ---

# CSV related routes api_list_booking_csv_backups and api_restore_bookings_from_csv removed.

@api_system_bp.route('/api/admin/booking_restore/list_incremental', methods=['GET'])
@login_required
@permission_required('manage_system')
def api_list_incremental_booking_backups():
    current_app.logger.info(f"User {current_user.username} requested list of incremental booking backups.")
    if not list_available_incremental_booking_backups:
        return jsonify({'success': False, 'message': 'Backup module not configured.', 'backups': []}), 500
    try:
        backups = list_available_incremental_booking_backups()
        return jsonify({'success': True, 'backups': backups}), 200
    except Exception as e:
        current_app.logger.exception("Exception listing incremental booking backups:")
        return jsonify({'success': False, 'message': f'Error: {str(e)}', 'backups': []}), 500

@api_system_bp.route('/api/admin/booking_restore/list_full_backups', methods=['GET'])
@login_required
@permission_required('manage_system')
def api_list_full_db_backups_for_booking_restore():
    current_app.logger.info(f"User {current_user.username} requested list of full DB backups for booking restore.")
    if not list_available_backups: # This is the existing function for full system backups
        return jsonify({'success': False, 'message': 'Backup module not configured.', 'backups': []}), 500
    try:
        # These are full system backup timestamps, but can be used to restore just bookings from the DB
        backups = list_available_backups()
        # Format them slightly for consistency if needed, or return as is.
        # For now, returning as is, UI can adapt or another transformation step can be added.
        return jsonify({'success': True, 'backups': backups}), 200
    except Exception as e:
        current_app.logger.exception("Exception listing full DB backups for booking restore:")
        return jsonify({'success': False, 'message': f'Error: {str(e)}', 'backups': []}), 500

@api_system_bp.route('/api/admin/booking_restore/from_csv', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_restore_bookings_from_csv():
    task_id = uuid.uuid4().hex
    data = request.get_json()
    if not data or 'backup_timestamp' not in data:
        return jsonify({'success': False, 'message': 'Backup timestamp is required.', 'task_id': task_id}), 400

    backup_timestamp = data['backup_timestamp']
    current_app.logger.info(f"User {current_user.username} initiated booking restore from CSV (Task {task_id}): {backup_timestamp}")

    # This functionality is being removed.
    # if not restore_bookings_from_csv_backup:
    #     return jsonify({'success': False, 'message': 'Restore function not available.', 'task_id': task_id}), 500
    # try:
    #     summary = restore_bookings_from_csv_backup(
    #         app=current_app._get_current_object(),
    #         timestamp_str=backup_timestamp,
    #         socketio_instance=socketio,
    #         task_id=task_id
    #     )
    #     add_audit_log(action="RESTORE_BOOKINGS_CSV", details=f"Task {task_id}, Timestamp {backup_timestamp}. Summary: {json.dumps(summary)}", user_id=current_user.id)
    #     return jsonify({'success': True, 'summary': summary, 'task_id': task_id}), 200
    # except Exception as e:
    #     current_app.logger.exception(f"Exception during booking restore from CSV (Task {task_id}):")
    #     add_audit_log(action="RESTORE_BOOKINGS_CSV_ERROR", details=f"Task {task_id}, Timestamp {backup_timestamp}, Error: {str(e)}", user_id=current_user.id)
    #     return jsonify({'success': False, 'message': str(e), 'task_id': task_id}), 500
    current_app.logger.warning(f"Attempt to use removed CSV restore endpoint by {current_user.username}.")
    return jsonify({'success': False, 'message': 'CSV restore functionality has been removed.'}), 410


@api_system_bp.route('/api/admin/booking_restore/from_incremental', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_restore_bookings_from_incremental():
    task_id = uuid.uuid4().hex
    current_app.logger.info(f"User {current_user.username} initiated booking restore from incremental backups (Task {task_id}).")

    if not restore_incremental_bookings:
        return jsonify({'success': False, 'message': 'Restore function not available.', 'task_id': task_id}), 500

    try:
        summary = restore_incremental_bookings(
            app=current_app._get_current_object(),
            socketio_instance=socketio,
            task_id=task_id
        )
        add_audit_log(action="RESTORE_BOOKINGS_INCREMENTAL", details=f"Task {task_id}. Summary: {json.dumps(summary)}", user_id=current_user.id)
        return jsonify({'success': True, 'summary': summary, 'task_id': task_id}), 200
    except Exception as e:
        current_app.logger.exception(f"Exception during booking restore from incremental (Task {task_id}):")
        add_audit_log(action="RESTORE_BOOKINGS_INCREMENTAL_ERROR", details=f"Task {task_id}, Error: {str(e)}", user_id=current_user.id)
        return jsonify({'success': False, 'message': str(e), 'task_id': task_id}), 500

@api_system_bp.route('/api/admin/booking_restore/from_full_db', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_restore_bookings_from_full_db():
    task_id = uuid.uuid4().hex
    data = request.get_json()
    if not data or 'backup_timestamp' not in data:
        return jsonify({'success': False, 'message': 'Backup timestamp is required.', 'task_id': task_id}), 400

    backup_timestamp = data['backup_timestamp']
    current_app.logger.info(f"User {current_user.username} initiated booking restore from full DB backup (Task {task_id}): {backup_timestamp}")

    if not restore_bookings_from_full_db_backup:
        return jsonify({'success': False, 'message': 'Restore function not available.', 'task_id': task_id}), 500

    try:
        summary = restore_bookings_from_full_db_backup(
            app=current_app._get_current_object(),
            timestamp_str=backup_timestamp,
            socketio_instance=socketio,
            task_id=task_id
        )
        add_audit_log(action="RESTORE_BOOKINGS_FULL_DB", details=f"Task {task_id}, Timestamp {backup_timestamp}. Summary: {json.dumps(summary)}", user_id=current_user.id)
        return jsonify({'success': True, 'summary': summary, 'task_id': task_id}), 200
    except Exception as e:
        current_app.logger.exception(f"Exception during booking restore from full DB (Task {task_id}):")
        add_audit_log(action="RESTORE_BOOKINGS_FULL_DB_ERROR", details=f"Task {task_id}, Timestamp {backup_timestamp}, Error: {str(e)}", user_id=current_user.id)
        return jsonify({'success': False, 'message': str(e), 'task_id': task_id}), 500

@api_system_bp.route('/api/admin/booking_restore/list_full_json_exports', methods=['GET'])
@login_required
@permission_required('manage_system')
def api_list_full_booking_json_exports():
    current_app.logger.info(f"User {current_user.username} requested list of full booking JSON exports.")
    if not list_available_full_booking_json_exports:
        return jsonify({'success': False, 'message': 'Functionality to list full JSON exports is not available.', 'backups': []}), 501
    try:
        backups = list_available_full_booking_json_exports()
        return jsonify({'success': True, 'backups': backups}), 200
    except Exception as e:
        current_app.logger.exception("Exception listing full booking JSON exports:")
        return jsonify({'success': False, 'message': f'Error: {str(e)}', 'backups': []}), 500

@api_system_bp.route('/api/admin/booking_restore/from_full_json_export', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_restore_bookings_from_full_json_export():
    task_id = uuid.uuid4().hex
    data = request.get_json()
    if not data or 'filename' not in data:
        return jsonify({'success': False, 'message': 'Filename of the full JSON export is required.', 'task_id': task_id}), 400

    filename = data['filename']
    current_app.logger.info(f"User {current_user.username} initiated booking restore from full JSON export (Task {task_id}): {filename}")

    if not restore_bookings_from_full_json_export:
        return jsonify({'success': False, 'message': 'Restore function from full JSON export not available.', 'task_id': task_id}), 501

    try:
        summary = restore_bookings_from_full_json_export(
            app=current_app._get_current_object(),
            filename=filename,
            socketio_instance=socketio,
            task_id=task_id
        )
        add_audit_log(action="RESTORE_BOOKINGS_FULL_JSON", details=f"Task {task_id}, Filename {filename}. Summary: {json.dumps(summary)}", user_id=current_user.id)
        # The summary itself contains 'status', 'message', 'bookings_restored', 'errors'
        # Return success:True if the operation itself was handled, check summary.status for functional outcome
        return jsonify({'success': True, 'summary': summary, 'task_id': task_id}), 200
    except Exception as e:
        current_app.logger.exception(f"Exception during booking restore from full JSON export (Task {task_id}):")
        add_audit_log(action="RESTORE_BOOKINGS_FULL_JSON_ERROR", details=f"Task {task_id}, Filename {filename}, Error: {str(e)}", user_id=current_user.id)
        return jsonify({'success': False, 'message': str(e), 'task_id': task_id, 'summary': {'status': 'failure', 'message': str(e), 'errors': [str(e)]}}), 500

@api_system_bp.route('/api/admin/manual_incremental_booking_backup', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_manual_incremental_booking_backup():
    task_id = uuid.uuid4().hex
    current_app.logger.info(f"User {current_user.username} initiated manual incremental booking backup (Task ID: {task_id}).")

    if not backup_incremental_bookings: # Check if function was successfully imported
        current_app.logger.error("azure_backup.backup_incremental_bookings function not available.")
        # Emitting SocketIO event directly as the task function won't be called
        if socketio:
            socketio.emit('incremental_booking_backup_progress', { # Ensure this event name is handled by JS
                'task_id': task_id,
                'status': 'Error: Backup function not available on server.',
                'detail': 'CRITICAL_ERROR',
                'error_details': 'The server is not configured for this type of backup.'
            })
        return jsonify({
            'success': False,
            'message': 'Manual incremental booking backup function is not available on the server.',
            'task_id': task_id
        }), 500

    try:
        # Pass the actual app instance and socketio instance
        # backup_incremental_bookings is expected to handle its own detailed SocketIO emissions
        success = backup_incremental_bookings(
            app=current_app._get_current_object(),
            socketio_instance=socketio, # from extensions
            task_id=task_id
        )

        if success: # Assuming backup_incremental_bookings returns a boolean or similar success indicator
            current_app.logger.info(f"Manual incremental booking backup process (Task ID: {task_id}) started successfully.")
            add_audit_log(action="MANUAL_INCREMENTAL_BACKUP_STARTED", details=f"Task ID: {task_id}", user_id=current_user.id)
            return jsonify({
                'success': True,
                'message': 'Manual incremental booking backup process started successfully.',
                'task_id': task_id
            }), 200
        else:
            # This case implies backup_incremental_bookings was called but returned False or an equivalent non-success state.
            # The function itself should emit relevant SocketIO messages about why it failed internally.
            current_app.logger.error(f"Failed to start manual incremental booking backup process (Task ID: {task_id}). backup_incremental_bookings returned non-success.")
            add_audit_log(action="MANUAL_INCREMENTAL_BACKUP_FAILED_START", details=f"Task ID: {task_id}. Function indicated failure.", user_id=current_user.id)
            return jsonify({
                'success': False,
                'message': 'Failed to start manual incremental booking backup process. Check server logs and live operation logs for details.',
                'task_id': task_id
            }), 500
    except Exception as e:
        current_app.logger.exception(f"Exception during manual incremental booking backup initiation (Task ID: {task_id}):")
        add_audit_log(action="MANUAL_INCREMENTAL_BACKUP_ERROR", details=f"Task ID: {task_id}. Exception: {str(e)}", user_id=current_user.id)
        # Emitting SocketIO event directly as the task function might not have
        if socketio:
            socketio.emit('incremental_booking_backup_progress', { # Ensure this event name is handled by JS
                'task_id': task_id,
                'status': f'Error: {str(e)}',
                'detail': 'EXCEPTION',
                'error_details': str(e)
            })
        return jsonify({
            'success': False,
            'message': f'An unexpected error occurred: {str(e)}',
            'task_id': task_id
        }), 500

@api_system_bp.route('/api/admin/manual_full_booking_export_json', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_manual_full_booking_export_json():
    task_id = uuid.uuid4().hex
    current_app.logger.info(f"User {current_user.username} initiated manual full booking JSON export (Task ID: {task_id}).")

    if not backup_full_bookings_json:
        current_app.logger.error("azure_backup.backup_full_bookings_json function not available.")
        if socketio:
            socketio.emit('full_booking_export_progress', { # Ensure this event name is handled by JS
                'task_id': task_id,
                'status': 'Error: Full export function not available on server.',
                'detail': 'CRITICAL_ERROR',
                'error_details': 'The server is not configured for this type of backup.'
            })
        return jsonify({
            'success': False,
            'message': 'Manual full booking JSON export function is not available on the server.',
            'task_id': task_id
        }), 500

    try:
        success = backup_full_bookings_json(
            app=current_app._get_current_object(),
            socketio_instance=socketio,
            task_id=task_id
        )

        if success:
            current_app.logger.info(f"Manual full booking JSON export process (Task ID: {task_id}) started successfully.")
            add_audit_log(action="MANUAL_FULL_BOOKING_EXPORT_STARTED", details=f"Task ID: {task_id}", user_id=current_user.id)
            return jsonify({
                'success': True,
                'message': 'Manual full booking JSON export process started successfully.',
                'task_id': task_id
            }), 200
        else:
            current_app.logger.error(f"Failed to start manual full booking JSON export process (Task ID: {task_id}). backup_full_bookings_json returned non-success.")
            add_audit_log(action="MANUAL_FULL_BOOKING_EXPORT_FAILED_START", details=f"Task ID: {task_id}. Function indicated failure.", user_id=current_user.id)
            return jsonify({
                'success': False,
                'message': 'Failed to start manual full booking JSON export process. Check server logs and live operation logs for details.',
                'task_id': task_id
            }), 500
    except Exception as e:
        current_app.logger.exception(f"Exception during manual full booking JSON export initiation (Task ID: {task_id}):")
        add_audit_log(action="MANUAL_FULL_BOOKING_EXPORT_ERROR", details=f"Task ID: {task_id}. Exception: {str(e)}", user_id=current_user.id)
        if socketio:
            socketio.emit('full_booking_export_progress', { # Ensure this event name is handled by JS
                'task_id': task_id,
                'status': f'Error: {str(e)}',
                'detail': 'EXCEPTION',
                'error_details': str(e)
            })
        return jsonify({
            'success': False,
            'message': f'An unexpected error occurred: {str(e)}',
            'task_id': task_id
        }), 500

@api_system_bp.route('/api/admin/verify_backup', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_verify_backup():
    data = request.get_json()
    task_id = uuid.uuid4().hex
    if not data or 'backup_timestamp' not in data: return jsonify({'success': False, 'message': 'Backup timestamp is required.', 'task_id': task_id}), 400
    backup_timestamp = data['backup_timestamp']
    current_app.logger.info(f"User {current_user.username} initiated VERIFY BACKUP (task {task_id}) for timestamp: {backup_timestamp}.")

    if not verify_backup_set:
        message = "Backup verification module not configured or available."
        current_app.logger.error(message)
        if socketio: socketio.emit('verify_backup_progress', {'task_id': task_id, 'status': message, 'detail': 'ERROR', 'results': None})
        return jsonify({'success': False, 'message': message, 'task_id': task_id, 'results': None}), 500

    try:
        if socketio: socketio.emit('verify_backup_progress', {'task_id': task_id, 'status': 'Backup verification starting...', 'detail': f'Timestamp: {backup_timestamp}'})
        verification_results = verify_backup_set(backup_timestamp, socketio_instance=socketio, task_id=task_id)
        final_message = f"Verification for backup {backup_timestamp} (task {task_id}) completed. Status: {verification_results.get('status')}."
        current_app.logger.info(final_message)
        add_audit_log(action="VERIFY_BACKUP_COMPLETED", details=f"{final_message} Results: {json.dumps(verification_results)}", user_id=current_user.id)
        if socketio: socketio.emit('verify_backup_progress', {'task_id': task_id, 'status': f"Verification complete: {verification_results.get('status')}", 'detail': 'SUCCESS' if verification_results.get('status') == 'verified_present' else 'INFO', 'results': verification_results})
        return jsonify({'success': True, 'message': final_message, 'task_id': task_id, 'results': verification_results}), 200
    except Exception as e:
        error_message = f"Error during backup verification for {backup_timestamp} (task {task_id}): {str(e)}"
        current_app.logger.exception(error_message)
        add_audit_log(action="VERIFY_BACKUP_ERROR", details=error_message, user_id=current_user.id)
        if socketio: socketio.emit('verify_backup_progress', {'task_id': task_id, 'status': 'Backup verification failed.', 'detail': str(e), 'results': None})
        return jsonify({'success': False, 'message': error_message, 'task_id': task_id, 'results': None}), 500

@api_system_bp.route('/api/admin/backup_schedule', methods=['GET'])
@login_required
@permission_required('manage_system')
def get_backup_schedule():
    current_app.logger.info(f"User {current_user.username} fetching backup schedule configuration (from JSON).")
    try:
        schedule_data = _load_schedule_from_json()
        return jsonify(schedule_data), 200
    except Exception as e:
        current_app.logger.exception("Error fetching backup schedule config from JSON:")
        return jsonify(_load_schedule_from_json.DEFAULT_SCHEDULE_DATA.copy()), 500 # Use default from util

@api_system_bp.route('/api/admin/backup_schedule', methods=['POST'])
@login_required
@permission_required('manage_system')
def update_backup_schedule():
    current_app.logger.info(f"User {current_user.username} attempting to update backup schedule (to JSON).")
    data = request.get_json()
    if not data: return jsonify({'success': False, 'message': 'Invalid input. JSON data expected.'}), 400

    try:
        is_enabled = data.get('is_enabled')
        schedule_type = data.get('schedule_type')
        time_of_day_str = data.get('time_of_day')

        if not isinstance(is_enabled, bool): return jsonify({'success': False, 'message': 'is_enabled must be true or false.'}), 400
        if schedule_type not in ['daily', 'weekly']: return jsonify({'success': False, 'message': "schedule_type must be 'daily' or 'weekly'."}), 400
        if not time_of_day_str: return jsonify({'success': False, 'message': 'time_of_day is required.'}), 400
        try:
            datetime.strptime(time_of_day_str, '%H:%M')
            data['time_of_day'] = time_of_day_str # Ensure it's HH:MM
        except ValueError:
            try: # Allow HH:MM:SS from old DB for parsing, but will save as HH:MM
                parsed_time = datetime.strptime(time_of_day_str, '%H:%M:%S').time()
                data['time_of_day'] = parsed_time.strftime('%H:%M')
            except ValueError:
                return jsonify({'success': False, 'message': "time_of_day must be in HH:MM or HH:MM:SS format."}), 400

        if schedule_type == 'weekly':
            day_of_week_val = data.get('day_of_week')
            if day_of_week_val is None or str(day_of_week_val).strip() == '': return jsonify({'success': False, 'message': 'day_of_week is required for weekly schedule.'}), 400
            try:
                day_of_week_int = int(day_of_week_val)
                if not (0 <= day_of_week_int <= 6): raise ValueError("Day of week must be 0-6.")
                data['day_of_week'] = day_of_week_int
            except (ValueError, TypeError): return jsonify({'success': False, 'message': 'day_of_week must be an integer between 0 and 6.'}), 400
        else: data['day_of_week'] = None

        success, message = _save_schedule_to_json(data)
        if success:
            current_app.logger.info(f"Backup schedule updated by {current_user.username} (JSON): {data}")
            add_audit_log(action="UPDATE_BACKUP_SCHEDULE_JSON", details=f"User {current_user.username} updated backup schedule (JSON). New config: {data}", user_id=current_user.id)
            return jsonify({'success': True, 'message': message}), 200
        else:
            add_audit_log(action="UPDATE_BACKUP_SCHEDULE_JSON_FAILED", details=f"Error: {message}. Data: {data}", user_id=current_user.id)
            return jsonify({'success': False, 'message': message}), 500
    except ValueError as ve: return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        current_app.logger.exception("Error updating backup schedule config (JSON):")
        add_audit_log(action="UPDATE_BACKUP_SCHEDULE_JSON_ERROR", details=f"Error: {str(e)}. Data: {data}", user_id=current_user.id)
        return jsonify({'success': False, 'message': f'Error updating schedule: {str(e)}'}), 500

@api_system_bp.route('/api/admin/delete_backup/<string:backup_timestamp>', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_delete_backup_set(backup_timestamp):
    task_id = uuid.uuid4().hex
    current_app.logger.info(f"[Task {task_id}] User {current_user.username} initiated DELETE BACKUP for timestamp: {backup_timestamp}.")

    if not delete_backup_set:
        error_message = "Backup deletion function is not available. Check system configuration."
        current_app.logger.error(f"[Task {task_id}] {error_message}")
        add_audit_log(action="DELETE_BACKUP_SET_UNAVAILABLE", details=f"Task {task_id}: Attempt to delete backup {backup_timestamp}, function missing.", user_id=current_user.id)
        if socketio: socketio.emit('backup_delete_progress', {'task_id': task_id, 'status': error_message, 'detail': 'ERROR'})
        return jsonify({'success': False, 'message': error_message, 'task_id': task_id}), 500

    try:
        if socketio: socketio.emit('backup_delete_progress', {'task_id': task_id, 'status': 'Deletion process starting...', 'detail': f'Target timestamp: {backup_timestamp}'})
        success = delete_backup_set(backup_timestamp, socketio_instance=socketio, task_id=task_id)
        if success:
            message = f"Backup set '{backup_timestamp}' deleted successfully."
            current_app.logger.info(f"[Task {task_id}] {message}")
            add_audit_log(action="DELETE_BACKUP_SET_SUCCESS", details=f"Task {task_id}: {message} User: {current_user.username}.", user_id=current_user.id)
            if socketio: socketio.emit('backup_delete_progress', {'task_id': task_id, 'status': message, 'detail': 'SUCCESS'})
            return jsonify({'success': True, 'message': message, 'task_id': task_id}), 200
        else:
            message = f"Failed to delete backup set '{backup_timestamp}'. See logs for details."
            current_app.logger.warning(f"[Task {task_id}] {message} (reported by delete_backup_set). User: {current_user.username}.")
            add_audit_log(action="DELETE_BACKUP_SET_FAILED", details=f"Task {task_id}: {message} User: {current_user.username}.", user_id=current_user.id)
            return jsonify({'success': False, 'message': message, 'task_id': task_id}), 500
    except Exception as e:
        error_message = f"Unexpected error deleting backup set '{backup_timestamp}': {str(e)}"
        current_app.logger.exception(f"[Task {task_id}] {error_message} User: {current_user.username}.")
        add_audit_log(action="DELETE_BACKUP_SET_ERROR", details=f"Task {task_id}: {error_message} User: {current_user.username}.", user_id=current_user.id)
        if socketio: socketio.emit('backup_delete_progress', {'task_id': task_id, 'status': error_message, 'detail': 'CRITICAL_ERROR'})
        return jsonify({'success': False, 'message': error_message, 'task_id': task_id}), 500

@api_system_bp.route('/api/admin/bulk_delete_system_backups', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_bulk_delete_system_backups():
    main_task_id = uuid.uuid4().hex
    current_app.logger.info(f"[Task {main_task_id}] User {current_user.username} initiated BULK DELETE SYSTEM BACKUPS.")

    data = request.get_json()
    if not data or 'timestamps' not in data or not isinstance(data['timestamps'], list):
        current_app.logger.warning(f"[Task {main_task_id}] Invalid payload received for bulk delete: {data}")
        return jsonify({'success': False, 'message': 'Invalid payload. "timestamps" list is required.', 'task_id': main_task_id}), 400

    timestamps_to_delete = data['timestamps']
    if not timestamps_to_delete:
        return jsonify({'success': True, 'message': 'No timestamps provided for deletion.', 'results': {}, 'task_id': main_task_id}), 200

    if not delete_backup_set:
        error_message = "Backup deletion function is not available. Check system configuration."
        current_app.logger.error(f"[Task {main_task_id}] {error_message}")
        add_audit_log(action="BULK_DELETE_BACKUPS_UNAVAILABLE", details=f"Task {main_task_id}: Bulk delete attempt, function missing.", user_id=current_user.id)
        if socketio: socketio.emit('bulk_backup_delete_progress', {'task_id': main_task_id, 'status': error_message, 'detail': 'ERROR', 'results': {}})
        return jsonify({'success': False, 'message': error_message, 'task_id': main_task_id}), 500

    results = {}
    overall_success = True

    if socketio:
        socketio.emit('bulk_backup_delete_progress', {
            'task_id': main_task_id,
            'status': f'Starting bulk deletion of {len(timestamps_to_delete)} backup sets...',
            'detail': 'INITIATED',
            'total_timestamps': len(timestamps_to_delete),
            'processed_count': 0,
            'current_timestamp': None
        })

    for index, timestamp in enumerate(timestamps_to_delete):
        individual_task_id = f"{main_task_id}_{index}" # More specific task ID for logging if needed, but main_task_id tracks the overall operation
        current_app.logger.info(f"[Task {main_task_id}] Processing timestamp '{timestamp}' for bulk deletion (item {index + 1}/{len(timestamps_to_delete)}). Individual task ref: {individual_task_id}")
        if socketio:
            socketio.emit('bulk_backup_delete_progress', {
                'task_id': main_task_id,
                'status': f'Deleting backup set {timestamp}...',
                'detail': 'IN_PROGRESS',
                'total_timestamps': len(timestamps_to_delete),
                'processed_count': index,
                'current_timestamp': timestamp
            })
        try:
            success = delete_backup_set(timestamp, socketio_instance=socketio, task_id=main_task_id) # Pass main_task_id for socket progress
            if success:
                results[timestamp] = "success"
                current_app.logger.info(f"[Task {main_task_id}] Successfully deleted backup set '{timestamp}'.")
                add_audit_log(action="DELETE_BACKUP_SET_SUCCESS_BULK", details=f"Task {main_task_id}: Backup {timestamp} deleted as part of bulk operation. User: {current_user.username}.", user_id=current_user.id)
            else:
                results[timestamp] = "failed"
                overall_success = False
                current_app.logger.warning(f"[Task {main_task_id}] Failed to delete backup set '{timestamp}' during bulk operation.")
                add_audit_log(action="DELETE_BACKUP_SET_FAILED_BULK", details=f"Task {main_task_id}: Failed to delete backup {timestamp} during bulk operation. User: {current_user.username}.", user_id=current_user.id)
        except Exception as e:
            results[timestamp] = "error"
            overall_success = False
            error_message = f"Unexpected error deleting backup set '{timestamp}' during bulk operation: {str(e)}"
            current_app.logger.exception(f"[Task {main_task_id}] {error_message}")
            add_audit_log(action="DELETE_BACKUP_SET_ERROR_BULK", details=f"Task {main_task_id}: {error_message} User: {current_user.username}.", user_id=current_user.id)
            # Emit individual error to socket if desired, but main progress indicates overall status
            if socketio:
                socketio.emit('bulk_backup_delete_progress', {
                    'task_id': main_task_id,
                    'status': f'Error deleting backup set {timestamp}: {str(e)}',
                    'detail': 'ERROR_ITEM',
                    'total_timestamps': len(timestamps_to_delete),
                    'processed_count': index + 1,
                    'current_timestamp': timestamp,
                    'error_details': str(e)
                })

    final_message = f"Bulk deletion process completed for {len(timestamps_to_delete)} timestamps."
    if not overall_success:
        final_message += " Some deletions may have failed or encountered errors."

    current_app.logger.info(f"[Task {main_task_id}] {final_message} Results: {results}")
    add_audit_log(action="BULK_DELETE_SYSTEM_BACKUPS_COMPLETED", details=f"Task {main_task_id}: {final_message} Results: {json.dumps(results)}", user_id=current_user.id)

    if socketio:
        socketio.emit('bulk_backup_delete_progress', {
            'task_id': main_task_id,
            'status': final_message,
            'detail': 'COMPLETED' if overall_success else 'COMPLETED_WITH_ERRORS',
            'total_timestamps': len(timestamps_to_delete),
            'processed_count': len(timestamps_to_delete),
            'results': results
        })

    return jsonify({'success': overall_success, 'message': final_message, 'results': results, 'task_id': main_task_id}), 200 if overall_success else 207 # 207 Multi-Status

def init_api_system_routes(app):
    app.register_blueprint(api_system_bp)

@api_system_bp.route('/api/system/booking_settings', methods=['GET'])
@login_required # Or @permission_required('some_permission_if_not_all_logged_in_users_can_see')
def get_booking_settings():
    """Fetches all current booking settings."""
    try:
        settings = BookingSettings.query.first()
        if settings:
            # Convert Decimal fields to string for JSON serialization if any exist.
            # Example: 'pin_length': str(settings.pin_length) if isinstance(settings.pin_length, Decimal) else settings.pin_length,
            settings_data = {
                'allow_past_bookings': settings.allow_past_bookings,
                'max_booking_days_in_future': settings.max_booking_days_in_future,
                'allow_multiple_resources_same_time': settings.allow_multiple_resources_same_time,
                'max_bookings_per_user': settings.max_bookings_per_user,
                'enable_check_in_out': settings.enable_check_in_out,
                'past_booking_time_adjustment_hours': settings.past_booking_time_adjustment_hours,
                'check_in_minutes_before': settings.check_in_minutes_before,
                'check_in_minutes_after': settings.check_in_minutes_after,
                'pin_auto_generation_enabled': settings.pin_auto_generation_enabled,
                'pin_length': settings.pin_length,
                'pin_allow_manual_override': settings.pin_allow_manual_override,
                'resource_checkin_url_requires_login': settings.resource_checkin_url_requires_login,
                # Add any other settings fields here
            }
            current_app.logger.info(f"User {current_user.username} fetched booking settings.")
            return jsonify(settings_data), 200
        else:
            # Return default values or an empty object if no settings are found
            # This matches the behavior of the admin_ui.serve_booking_settings_page
            # when no settings exist.
            current_app.logger.info("Booking settings requested but none found in DB; returning defaults for an API context.")
            # Consider if API should return 404 or default structure. For PIN UI, defaults are likely better.
            return jsonify({
                'allow_past_bookings': False, 'max_booking_days_in_future': 30, # Example defaults
                'allow_multiple_resources_same_time': False, 'max_bookings_per_user': None,
                'enable_check_in_out': False, 'past_booking_time_adjustment_hours': 0,
                'check_in_minutes_before': 15, 'check_in_minutes_after': 15,
                'pin_auto_generation_enabled': True, 'pin_length': 6,
                'pin_allow_manual_override': True, 'resource_checkin_url_requires_login': True,
            }), 200 # Or 404 if settings must exist
    except Exception as e:
        current_app.logger.exception(f"Error fetching booking settings for user {current_user.username}:")
        return jsonify({'error': 'Failed to fetch booking settings due to a server error.'}), 500

# --- Raw DB View Route ---

@api_system_bp.route('/api/admin/view_db_raw_top100', methods=['GET'])
@login_required
@permission_required('manage_system')
def api_admin_view_db_raw_top100():
    """Fetches top 100 records from all database tables."""
    current_app.logger.info(f"User {current_user.username} requested raw top 100 DB records from all tables.")
    
    raw_data = {}

    # Create a mapping from table names to SQLAlchemy Model classes
    model_map = {mapper.class_.__tablename__: mapper.class_ for mapper in db.Model.registry.mappers if hasattr(mapper.class_, '__tablename__')}

    try:
        for table_name in db.metadata.tables.keys():
            table_obj = db.metadata.tables[table_name]
            ModelClass = model_map.get(table_name)
            serialized_records = []
            
            try:
                if ModelClass:
                    current_app.logger.debug(f"Querying table: {table_name} using model: {ModelClass.__name__}")
                    records = ModelClass.query.limit(100).all()
                    for record in records:
                        record_dict = {}
                        for column in table_obj.columns: # Use table_obj.columns for consistency
                            val = getattr(record, column.name)
                            if isinstance(val, datetime):
                                record_dict[column.name] = val.isoformat()
                            elif isinstance(val, uuid.UUID):
                                record_dict[column.name] = str(val)
                            else:
                                record_dict[column.name] = val
                        serialized_records.append(record_dict)
                else:
                    current_app.logger.debug(f"Querying table: {table_name} using direct table object.")
                    # Query using the table object directly
                    records = db.session.query(table_obj).limit(100).all()
                    for row in records: # These are RowProxy objects
                        record_dict = {}
                        # row._asdict() is convenient but ensure all column types are serializable
                        # Or iterate through columns like in the model case for explicit type handling
                        row_dict = row._asdict()
                        for column_name, val in row_dict.items():
                            if isinstance(val, datetime):
                                record_dict[column.name] = val.isoformat()
                            elif isinstance(val, uuid.UUID):
                                record_dict[column.name] = str(val)
                            else:
                                record_dict[column.name] = val
                        serialized_records.append(record_dict)

                raw_data[table_name] = serialized_records

            except Exception as query_exc:
                current_app.logger.warning(f"Could not query or serialize table '{table_name}'. Error: {query_exc}", exc_info=True)
                raw_data[table_name] = [{"info": f"Skipped table: {table_name} - Could not directly query or process (Error: {str(query_exc)[:100]}...). See logs."}]

        current_app.logger.info(f"Successfully fetched raw DB data from all tables for {current_user.username}.")
        return jsonify({'success': True, 'data': raw_data}), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching raw DB data from all tables for {current_user.username}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Failed to fetch raw database data: {str(e)}'}), 500

# --- DB Schema Info Routes ---

@api_system_bp.route('/api/admin/db/table_names', methods=['GET'])
@login_required
@permission_required('manage_system')
def api_admin_get_table_names():
    """Fetches all table names from the database with their record counts."""
    current_app.logger.info(f"User {current_user.username} requested list of database table names with counts.")
    try:
        all_table_names = list(db.metadata.tables.keys())
        tables_with_counts = []
        for table_name in all_table_names:
            table_obj = db.metadata.tables[table_name]
            try:
                # Construct a count query: SELECT count(*) FROM table_name
                # Using func.count() without a specific column counts all rows.
                # Using select_from(table_obj) ensures we are counting from the correct table.
                count_query = db.session.query(func.count(1).label("row_count")).select_from(table_obj) # Use count(1) for efficiency
                record_count = count_query.scalar()
                tables_with_counts.append({'name': table_name, 'count': record_count})
            except Exception as count_exc:
                current_app.logger.error(f"Error fetching count for table {table_name} by {current_user.username}: {count_exc}", exc_info=True)
                tables_with_counts.append({'name': table_name, 'count': -1}) # Indicate error for this table

        current_app.logger.info(f"Successfully retrieved {len(tables_with_counts)} table names with counts for {current_user.username}.")
        return jsonify({'success': True, 'tables': tables_with_counts}), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching database table names with counts for {current_user.username}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Failed to retrieve table names with counts: {str(e)}'}), 500

@api_system_bp.route('/api/admin/db/table_info/<string:table_name>', methods=['GET'])
@login_required
@permission_required('manage_system')
def api_admin_get_table_info(table_name: str):
    """Fetches column information for a specific database table."""
    current_app.logger.info(f"User {current_user.username} requested info for table: {table_name}.")
    try:
        if table_name not in db.metadata.tables:
            current_app.logger.warning(f"Table '{table_name}' not found by {current_user.username}.")
            return jsonify({'success': False, 'message': 'Table not found.'}), 404

        table_obj = db.metadata.tables[table_name]
        column_info_list = []
        for column in table_obj.columns:
            column_info_list.append({
                'name': column.name,
                'type': str(column.type),
                'nullable': column.nullable,
                'primary_key': column.primary_key
            })

        current_app.logger.info(f"Successfully retrieved info for table '{table_name}' for {current_user.username}.")
        return jsonify({'success': True, 'table_name': table_name, 'columns': column_info_list}), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching info for table '{table_name}' for {current_user.username}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Failed to retrieve table information for {table_name}: {str(e)}'}), 500

@api_system_bp.route('/api/admin/db/table_data/<string:table_name>', methods=['GET'])
@login_required
@permission_required('manage_system')
def api_admin_get_table_data(table_name: str):
    """Fetches paginated and filterable data from a specific database table."""
    import math # For math.ceil

    current_app.logger.info(f"User {current_user.username} requested data for table: {table_name} with query params: {request.args}")

    if table_name not in db.metadata.tables:
        current_app.logger.warning(f"Table '{table_name}' not found by {current_user.username}.")
        return jsonify({'success': False, 'message': 'Table not found.'}), 404

    table_obj = db.metadata.tables[table_name]

    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 30, type=int)
        filters_str = request.args.get('filters') # JSON string
        sort_by = request.args.get('sort_by')
        sort_order = request.args.get('sort_order', 'asc')

        if page < 1: page = 1
        if per_page < 1: per_page = 1
        if per_page > 200: per_page = 200 # Max limit for per_page

        query = db.session.query(table_obj)

        # Apply Filters
        if filters_str:
            try:
                filters = json.loads(filters_str)
                if not isinstance(filters, list):
                    raise ValueError("Filters must be a list.")
                for f_data in filters:
                    if not isinstance(f_data, dict) or not all(k in f_data for k in ['column', 'op', 'value']):
                        current_app.logger.warning(f"Invalid filter data format: {f_data} for table {table_name}")
                        continue # Or return error

                    col_name = f_data['column']
                    op = f_data['op'].lower()
                    value = f_data['value']

                    if col_name not in table_obj.c:
                        current_app.logger.warning(f"Invalid column '{col_name}' for filtering in table {table_name}")
                        continue # Or return error

                    column_obj = table_obj.c[col_name]

                    if op == 'eq': query = query.filter(column_obj == value)
                    elif op == 'neq': query = query.filter(column_obj != value)
                    elif op == 'ilike': query = query.filter(column_obj.ilike(value))
                    elif op == 'gt': query = query.filter(column_obj > value)
                    elif op == 'gte': query = query.filter(column_obj >= value)
                    elif op == 'lt': query = query.filter(column_obj < value)
                    elif op == 'lte': query = query.filter(column_obj <= value)
                    elif op == 'in': query = query.filter(column_obj.in_(value.split(',')))
                    elif op == 'notin': query = query.filter(column_obj.notin_(value.split(',')))
                    elif op == 'is_null': query = query.filter(column_obj.is_(None))
                    elif op == 'is_not_null': query = query.filter(column_obj.isnot(None))
                    else:
                        current_app.logger.warning(f"Unsupported filter operation '{op}' for table {table_name}")
                        # Potentially return a 400 error or ignore
            except json.JSONDecodeError:
                current_app.logger.warning(f"Invalid JSON in filters string for table {table_name}: {filters_str}")
                return jsonify({'success': False, 'message': 'Invalid filters format: Not valid JSON.'}), 400
            except ValueError as ve:
                current_app.logger.warning(f"Invalid filters structure for table {table_name}: {ve}")
                return jsonify({'success': False, 'message': f'Invalid filters structure: {ve}.'}), 400
            except Exception as e_filter: # Catch other potential errors during filter application
                current_app.logger.error(f"Error applying filter for table {table_name}: {e_filter}", exc_info=True)
                return jsonify({'success': False, 'message': f'Error applying filter: {e_filter}.'}), 500


        # Apply Sorting
        if sort_by:
            if sort_by not in table_obj.c:
                current_app.logger.warning(f"Invalid column '{sort_by}' for sorting in table {table_name}")
                # Optionally return a 400 error or ignore sorting
            else:
                sort_column_obj = table_obj.c[sort_by]
                if sort_order.lower() == 'desc':
                    query = query.order_by(sort_column_obj.desc())
                else:
                    query = query.order_by(sort_column_obj.asc())

        total_records = query.count() # Count after filtering

        # Apply Pagination
        offset = (page - 1) * per_page
        paginated_query = query.limit(per_page).offset(offset)

        result_records_raw = paginated_query.all()

        # Serialize Records
        serialized_records = []
        for row in result_records_raw:
            record_dict_raw = row._asdict()
            record_dict_final = {}
            for col_name, val in record_dict_raw.items():
                if isinstance(val, datetime): # This handles datetime.datetime
                    record_dict_final[col_name] = val.isoformat()
                elif isinstance(val, time): # Add this condition for datetime.time
                    record_dict_final[col_name] = val.isoformat()
                elif isinstance(val, uuid.UUID):
                    record_dict_final[col_name] = str(val)
                else:
                    record_dict_final[col_name] = val
            serialized_records.append(record_dict_final)

        # Column Information
        column_info_list = []
        for column in table_obj.columns:
            column_info_list.append({
                'name': column.name,
                'type': str(column.type),
                'nullable': column.nullable,
                'primary_key': column.primary_key
            })

        current_app.logger.info(f"Successfully retrieved data for table '{table_name}' by {current_user.username}.")
        return jsonify({
            'success': True,
            'table_name': table_name,
            'columns': column_info_list,
            'records': serialized_records,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total_records': total_records,
                'total_pages': math.ceil(total_records / per_page) if per_page > 0 else 0
            }
        }), 200

    except Exception as e:
        current_app.logger.error(f"Error fetching data for table '{table_name}' for {current_user.username}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Failed to retrieve data for table {table_name}: {str(e)}'}), 500

# --- System Data Cleanup Route ---

@api_system_bp.route('/api/admin/cleanup_system_data', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_admin_cleanup_system_data():
    """Cleans up database records and uploaded files."""
    current_app.logger.info(f"User {current_user.username} initiated system data cleanup.")
    
    try:
        # Database Cleanup
        num_bookings_deleted = Booking.query.delete()
        add_audit_log(action="DB_CLEANUP", details=f"Deleted {num_bookings_deleted} records from Booking table.", user_id=current_user.id)
        current_app.logger.info(f"Deleted {num_bookings_deleted} records from Booking table.")

        num_resources_deleted = Resource.query.delete()
        add_audit_log(action="DB_CLEANUP", details=f"Deleted {num_resources_deleted} records from Resource table.", user_id=current_user.id)
        current_app.logger.info(f"Deleted {num_resources_deleted} records from Resource table.")

        num_floormaps_deleted = FloorMap.query.delete()
        add_audit_log(action="DB_CLEANUP", details=f"Deleted {num_floormaps_deleted} records from FloorMap table.", user_id=current_user.id)
        current_app.logger.info(f"Deleted {num_floormaps_deleted} records from FloorMap table.")
        
        db.session.commit()
        current_app.logger.info("Database cleanup committed.")

        # Uploaded Files Cleanup
        # Construct paths relative to the application's root directory
        floor_map_uploads_path = os.path.join(current_app.root_path, 'static', 'floor_map_uploads')
        resource_uploads_path = os.path.join(current_app.root_path, 'static', 'resource_uploads')
        
        paths_to_clean = {
            "Floor Map Uploads": floor_map_uploads_path,
            "Resource Uploads": resource_uploads_path
        }
        
        files_deleted_count = 0
        deletion_errors = []

        for dir_label, directory_path in paths_to_clean.items():
            if not os.path.exists(directory_path):
                current_app.logger.info(f"Directory '{directory_path}' for {dir_label} not found. Skipping.")
                continue
            if not os.path.isdir(directory_path):
                current_app.logger.warning(f"Path '{directory_path}' for {dir_label} is not a directory. Skipping.")
                continue

            current_app.logger.info(f"Cleaning up files in {dir_label} at '{directory_path}'.")
            for filename in os.listdir(directory_path):
                file_path = os.path.join(directory_path, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path): # Check if it's a file or a symlink
                        os.remove(file_path)
                        files_deleted_count += 1
                        current_app.logger.debug(f"Deleted file: {file_path}")
                    # Optionally, handle subdirectories if they are not expected and should be removed.
                    # else:
                    #     current_app.logger.info(f"Skipping non-file item: {file_path}")
                except Exception as e_file:
                    err_msg = f"Failed to delete file {file_path}: {str(e_file)}"
                    current_app.logger.error(err_msg)
                    deletion_errors.append(err_msg)
        
        add_audit_log(action="FILE_CLEANUP", details=f"Deleted {files_deleted_count} uploaded files. Errors: {len(deletion_errors)}.", user_id=current_user.id)
        current_app.logger.info(f"Uploaded files cleanup completed. Deleted: {files_deleted_count}. Errors: {len(deletion_errors)}.")

        if deletion_errors:
            return jsonify({'success': False, 'message': f'Cleanup partially completed. Database cleared. File deletion errors: {"; ".join(deletion_errors)}'}), 500
            
        return jsonify({'success': True, 'message': 'System data cleanup completed successfully.'}), 200
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error during system data cleanup by {current_user.username}: {e}", exc_info=True)
        add_audit_log(action="CLEANUP_SYSTEM_DATA_ERROR", details=f"Error: {str(e)}", user_id=current_user.id)
        return jsonify({'success': False, 'message': f'An error occurred during cleanup: {str(e)}'}), 500

# --- Reload Configurations Route ---

@api_system_bp.route('/api/admin/reload_configurations', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_admin_reload_configurations():
    """Attempts to reload certain configurations from their sources."""
    current_app.logger.info(f"User {current_user.username} initiated configuration reload.")
    
    try:
        # Reload Map Configuration
        current_app.logger.info("Attempting to re-fetch map configuration data.")
        map_data = _get_map_configuration_data()
        # Note: This action re-fetches the data. For it to be effective globally,
        # the application would need a mechanism to re-initialize or update
        # any services or caches that use this data.
        current_app.logger.info(f"Map configuration data re-fetched. Contains {len(map_data.get('floor_maps', []))} floor maps and {len(map_data.get('connections', []))} connections. Effective update depends on application's internal state management.")
        add_audit_log(action="RELOAD_CONFIG_MAP", details="Attempted to reload map configurations. Data re-fetched.", user_id=current_user.id)

        # Reload Backup Schedule
        current_app.logger.info("Attempting to reload backup schedule configuration.")
        schedule_data = _load_schedule_from_json()
        current_app.config['BACKUP_SCHEDULE_CONFIG'] = schedule_data # Assuming scheduler reads from here
        current_app.logger.info(f"Backup schedule configuration reloaded into app.config: {schedule_data}")
        add_audit_log(action="RELOAD_CONFIG_SCHEDULE", details=f"Reloaded backup schedule configuration: {schedule_data}", user_id=current_user.id)
        
        add_audit_log(action="RELOAD_CONFIGURATIONS_FINISHED", details="Configuration reload attempt finished.", user_id=current_user.id)
        return jsonify({'success': True, 'message': 'Configuration reload attempt finished. Note: Full effect for map configurations may require deeper application integration or restart.'}), 200
        
    except Exception as e:
        current_app.logger.error(f"Error during configuration reload by {current_user.username}: {e}", exc_info=True)
        add_audit_log(action="RELOAD_CONFIGURATIONS_ERROR", details=f"Error: {str(e)}", user_id=current_user.id)
        return jsonify({'success': False, 'message': f'An error occurred during configuration reload: {str(e)}'}), 500

@api_system_bp.route('/api/settings/booking_config_status', methods=['GET'])
@login_required
def get_booking_config_status():
    """
    Fetches the 'allow_multiple_resources_same_time' setting from BookingSettings.
    """
    try:
        settings = BookingSettings.query.first()
        allow_multiple = False # Default value
        if settings:
            if hasattr(settings, 'allow_multiple_resources_same_time'):
                allow_multiple = settings.allow_multiple_resources_same_time
            else:
                current_app.logger.warning("BookingSettings found, but 'allow_multiple_resources_same_time' attribute is missing. Defaulting to False.")
        else:
            current_app.logger.warning("BookingSettings not found in the database. Defaulting 'allow_multiple_resources_same_time' to False.")

        # current_app.logger.debug(f"API /api/settings/booking_config_status returning: {allow_multiple}")
        return jsonify({'allow_multiple_resources_same_time': allow_multiple}), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching booking_config_status for user {current_user.username}: {e}", exc_info=True)
        # In case of error, still return the default value to prevent frontend issues
        return jsonify({'allow_multiple_resources_same_time': False, 'error': 'Failed to fetch setting due to a server error.'}), 500
