import os
import uuid
import json
from datetime import datetime, timezone, timedelta, time

from flask import Blueprint, jsonify, request, current_app, url_for
from flask_login import login_required, current_user
# from sqlalchemy import or_ # For more complex queries if needed in get_audit_logs

# Relative imports from project structure
from auth import permission_required
from extensions import db, socketio # socketio might be None if not available
from models import AuditLog, User, Resource, FloorMap, Booking, Role # Added User, Resource, FloorMap for utils that might need them in this context
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
)

# Conditional imports for Azure Backup functionality
try:
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
        restore_media_component # For selective restore
    )
    import azure_backup # To access module-level constants if needed by moved functions
except ImportError:
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

@api_system_bp.route('/api/admin/one_click_backup', methods=['POST'])
@login_required
@permission_required('manage_system')
def api_one_click_backup():
    current_app.logger.info(f"User {current_user.username} initiated one-click backup.")
    task_id = uuid.uuid4().hex
    current_app.logger.info(f"Generated task_id {task_id} for one-click backup.")

    if not create_full_backup:
        current_app.logger.error("Azure backup module not available for one-click backup.")
        return jsonify({'success': False, 'message': 'Backup module is not configured or available.', 'task_id': task_id}), 500
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
    current_app.logger.info(f"User {current_user.username} requested list of available backups.")
    if not list_available_backups:
        current_app.logger.error("Azure backup module not available for listing backups.")
        return jsonify({'success': False, 'message': 'Backup module is not configured or available.', 'backups': []}), 500
    try:
        backups = list_available_backups()
        current_app.logger.info(f"Found {len(backups)} available backups.")
        return jsonify({'success': True, 'backups': backups}), 200
    except Exception as e:
        current_app.logger.exception(f"Exception listing available backups for user {current_user.username}:")
        return jsonify({'success': False, 'message': f'An error occurred while listing backups: {str(e)}', 'backups': []}), 500

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

        # Import resource configurations
        resource_import_summary_msg = "Resource configurations file was not part of this backup or was not downloaded."
        if resource_configs_json_path and os.path.exists(resource_configs_json_path):
            current_app.logger.info(f"Resource configs JSON {resource_configs_json_path} (task {task_id}) downloaded for {backup_timestamp}.")
            if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Importing resource configurations...', 'detail': resource_configs_json_path})
            try:
                with open(resource_configs_json_path, 'r', encoding='utf-8') as f: resource_configs_to_import = json.load(f)
                res_created, res_updated, res_errors = _import_resource_configurations_data(resource_configs_to_import, db) # Pass db instance
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

        # Import user/role configurations
        user_import_summary_msg = "User/role configurations file was not part of this backup or was not downloaded."
        if user_configs_json_path and os.path.exists(user_configs_json_path):
            current_app.logger.info(f"User/role configs JSON {user_configs_json_path} (task {task_id}) downloaded for {backup_timestamp}.")
            if socketio: socketio.emit('restore_progress', {'task_id': task_id, 'status': 'Importing user/role configurations...', 'detail': user_configs_json_path})
            try:
                with open(user_configs_json_path, 'r', encoding='utf-8') as f: user_configs_to_import = json.load(f)
                r_created, r_updated, u_created, u_updated, u_errors = _import_user_configurations_data(user_configs_to_import, db) # Pass db instance
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

def init_api_system_routes(app):
    app.register_blueprint(api_system_bp)

# --- Raw DB View Route ---

@api_system_bp.route('/api/admin/view_db_raw_top100', methods=['GET'])
@login_required
@permission_required('manage_system')
def api_admin_view_db_raw_top100():
    """Fetches top 100 records from key database tables."""
    current_app.logger.info(f"User {current_user.username} requested raw top 100 DB records.")

    models_to_query = {
        "User": User,
        "Booking": Booking,
        "Resource": Resource,
        "FloorMap": FloorMap,
        "AuditLog": AuditLog,
        "Role": Role
    }

    raw_data = {}

    try:
        for model_name, ModelClass in models_to_query.items():
            records = ModelClass.query.limit(100).all()
            serialized_records = []
            for record in records:
                record_dict = {}
                for column in record.__table__.columns:
                    val = getattr(record, column.name)
                    if isinstance(val, datetime):
                        record_dict[column.name] = val.isoformat()
                    elif isinstance(val, (uuid.UUID)):
                        record_dict[column.name] = str(val)
                    else:
                        record_dict[column.name] = val
                serialized_records.append(record_dict)
            raw_data[model_name] = serialized_records

        current_app.logger.info(f"Successfully fetched raw DB data for {current_user.username}.")
        return jsonify({'success': True, 'data': raw_data}), 200

    except Exception as e:
        current_app.logger.error(f"Error fetching raw DB data for {current_user.username}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Failed to fetch raw database data: {str(e)}'}), 500

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
