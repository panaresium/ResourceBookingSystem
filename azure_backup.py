import os
import hashlib
import logging
import sqlite3
import json
from datetime import datetime, timezone
import tempfile
import re
import time
import csv
import shutil
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError, ServiceRequestError

from models import Booking, db
# from utils import import_bookings_from_csv_file # export_bookings_to_csv_string removed as unused # Line removed

try:
    from azure.storage.fileshare import ShareServiceClient, ShareClient, ShareDirectoryClient, ShareFileClient
except ImportError:  # pragma: no cover - azure sdk optional
    ShareServiceClient = None
    ShareClient = None
    ShareDirectoryClient = None
    ShareFileClient = None
    if 'ResourceNotFoundError' not in globals():
        ResourceNotFoundError = Exception
    if 'HttpResponseError' not in globals():
        HttpResponseError = Exception

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
FLOOR_MAP_UPLOADS = os.path.join(STATIC_DIR, 'floor_map_uploads')
RESOURCE_UPLOADS = os.path.join(STATIC_DIR, 'resource_uploads')
HASH_DB = os.path.join(DATA_DIR, 'backup_hashes.db')

logger = logging.getLogger(__name__)

# --- Constants for Backup System ---
LAST_INCREMENTAL_BOOKING_TIMESTAMP_FILE = os.path.join(DATA_DIR, 'last_incremental_booking_timestamp.txt')
BOOKING_INCREMENTAL_BACKUPS_DIR = 'booking_incremental_backups'

DB_BACKUPS_DIR = 'db_backups'
CONFIG_BACKUPS_DIR = 'config_backups'
MEDIA_BACKUPS_DIR_BASE = 'media_backups'

DB_FILENAME_PREFIX = 'site_'
MAP_CONFIG_FILENAME_PREFIX = 'map_config_'

BOOKING_FULL_JSON_EXPORTS_DIR = 'booking_full_json_exports'

# --- Unified Booking Data Protection Constants ---
AZURE_BOOKING_DATA_PROTECTION_DIR = 'booking_data_protection_backups'
BOOKING_DATA_FULL_DIR_SUFFIX = "full"
BOOKING_DATA_INCREMENTAL_DIR_SUFFIX = "incrementals"
LAST_UNIFIED_BOOKING_INCREMENTAL_TIMESTAMP_FILE = os.path.join(DATA_DIR, 'last_unified_booking_incremental_timestamp.txt')
LAST_BOOKING_DATA_PROTECTION_INCREMENTAL_TIMESTAMP_FILE = os.path.join(DATA_DIR, 'last_booking_data_protection_incremental_timestamp.txt')

def _get_service_client():
    connection_string = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
    if not connection_string:
        raise RuntimeError('AZURE_STORAGE_CONNECTION_STRING environment variable is required')
    if ShareServiceClient is None:
        raise RuntimeError('azure-storage-file-share package is not installed')
    return ShareServiceClient.from_connection_string(connection_string)

def _client_exists(client):
    try:
        if isinstance(client, ShareClient): client.get_share_properties()
        elif isinstance(client, ShareDirectoryClient): client.get_directory_properties()
        elif isinstance(client, ShareFileClient): client.get_file_properties()
        else: return False
        return True
    except ResourceNotFoundError: return False
    except Exception as e:
        logger.warning(f"Error checking client existence for '{getattr(client, 'name', 'Unknown')}': {e}", exc_info=True)
        return False

def _emit_progress(socketio_instance, task_id, event_name, message, detail='', level='INFO'):
    if socketio_instance and task_id:
        try:
            socketio_instance.emit(event_name, {'task_id': task_id, 'status': message, 'detail': detail, 'level': level.upper()})
        except Exception as e:
            logger.error(f"Failed to emit SocketIO event {event_name} for task {task_id}: {e}")

def _ensure_directory_exists(share_client, directory_path):
    if not directory_path: return
    parts = directory_path.split('/')
    current_path = ""
    for part in parts:
        if not part: continue
        current_path += f"{part}"
        dir_client = share_client.get_directory_client(current_path)
        if not _client_exists(dir_client):
            try: dir_client.create_directory()
            except Exception as e: logger.error(f"Failed to create dir '{current_path}': {e}"); raise
        current_path += "/"

def _create_share_with_retry(share_client, share_name, retries=3, delay=5, factor=2):
    current_delay = delay
    for i in range(retries):
        try:
            if _client_exists(share_client):
                logger.info(f"Share '{share_name}' already exists.")
                return True

            logger.info(f"Attempting to create share '{share_name}' (Attempt {i+1}/{retries}).")
            share_client.create_share()
            logger.info(f"Share '{share_name}' created successfully.")
            return True
        except HttpResponseError as e:
            # Common error is "ShareBeingDeleted" or "Conflict" if share is in transitioning state
            logger.warning(f"HttpResponseError creating share '{share_name}' (Attempt {i+1}/{retries}): {e.message or e}")
            if i == retries - 1: # Last retry
                logger.error(f"Failed to create share '{share_name}' after {retries} retries. Last error: {e.message or e}")
                raise
            logger.info(f"Retrying share creation for '{share_name}' in {current_delay} seconds...")
            time.sleep(current_delay)
            current_delay *= factor
        except Exception as e:
            logger.error(f"Unexpected error creating share '{share_name}': {e}", exc_info=True)
            raise # Re-raise other exceptions immediately
    logger.error(f"Share '{share_name}' could not be created after {retries} retries.")
    return False

def upload_file(share_client, source_path, file_path):
    logger.info(f"Attempting to upload '{source_path}' to '{share_client.share_name}/{file_path}'.")
    file_client = share_client.get_file_client(file_path)

    try:
        with open(source_path, "rb") as f_source:
            file_client.upload_file(f_source, overwrite=True) # Using overwrite=True as it's common for backups
        logger.info(f"Successfully uploaded '{source_path}' to '{share_client.share_name}/{file_path}'.")
        return True
    except FileNotFoundError:
        logger.error(f"Upload failed: Source file '{source_path}' not found.")
        return False
    except ResourceNotFoundError:
        # This can mean the share itself doesn't exist, or the parent directory for the file doesn't exist.
        logger.error(f"Upload failed: Resource not found for '{share_client.share_name}/{file_path}'. The share or parent directory might not exist. Ensure directories are created first if needed.")
        return False
    except HttpResponseError as e:
        # More specific Azure storage error
        error_message = e.message or getattr(e.response, 'text', str(e))
        logger.error(f"Upload failed due to HttpResponseError for '{share_client.share_name}/{file_path}': {error_message}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred during upload of '{source_path}' to '{share_client.share_name}/{file_path}': {e}", exc_info=True)
        return False

def download_file(share_client, file_path, dest_path):
    logger.debug(f"download_file called for {file_path} to {dest_path}")
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    # Create an empty file for placeholder if needed by other logic
    # with open(dest_path, 'wb') as f: f.write(b"simulated download content")
    return True

# --- System Backup Listing Function ---
def list_available_backups():
    """
    Lists available backup timestamps based on the presence of database backup files
    or backup manifest files.

    Returns:
        list: A sorted list of unique timestamp strings (YYYYMMDD_HHMMSS), most recent first.
              Returns an empty list if no backups are found or if there's an error.
    """
    logger.info("Attempting to list available full system backups.")
    try:
        service_client = _get_service_client()
        db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
        share_client = service_client.get_share_client(db_share_name)

        if not _client_exists(share_client):
            logger.warning(f"System backup share '{db_share_name}' does not exist. No backups to list.")
            return []

        db_backup_dir_client = share_client.get_directory_client(DB_BACKUPS_DIR)

        if not _client_exists(db_backup_dir_client):
            logger.warning(f"System database backup directory '{DB_BACKUPS_DIR}' does not exist on share '{db_share_name}'. No backups to list.")
            return []

        timestamps = set()
        # Regex to find timestamps in manifest or DB backup filenames
        # Manifest: backup_manifest_YYYYMMDD_HHMMSS.json
        # DB: site_YYYYMMDD_HHMMSS.db
        manifest_pattern = re.compile(r"^backup_manifest_(?P<timestamp>\d{8}_\d{6})\.json$")
        db_pattern = re.compile(rf"^{re.escape(DB_FILENAME_PREFIX)}(?P<timestamp>\d{8}_\d{6})\.db$")

        for item in db_backup_dir_client.list_directories_and_files():
            if item['is_directory']:
                continue

            filename = item['name']
            timestamp_str = None

            manifest_match = manifest_pattern.match(filename)
            if manifest_match:
                timestamp_str = manifest_match.group('timestamp')
            else:
                db_match = db_pattern.match(filename)
                if db_match:
                    timestamp_str = db_match.group('timestamp')

            if timestamp_str:
                try:
                    # Validate timestamp format
                    datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
                    timestamps.add(timestamp_str)
                except ValueError:
                    logger.warning(f"Skipping file with invalid timestamp format in system backup list: {filename}")

        sorted_timestamps = sorted(list(timestamps), reverse=True)
        logger.info(f"Found {len(sorted_timestamps)} available full system backup timestamps.")
        return sorted_timestamps
    except Exception as e:
        logger.error(f"Error listing available full system backups: {e}", exc_info=True)
        return []

def restore_full_backup(backup_timestamp, socketio_instance=None, task_id=None, dry_run=False):
    logger.warning(f"Placeholder function 'restore_full_backup' called for timestamp: {backup_timestamp}, dry_run: {dry_run}. Not implemented.")
    # Expected to return: restored_db_path, map_config_json_path, resource_configs_json_path, user_configs_json_path, actions_list
    # For a placeholder, we can return None for paths and an empty list for actions.
    if dry_run:
        actions_list = [
            "DRY RUN: Would check for Azure service client.",
            f"DRY RUN: Would attempt to find backup set for {backup_timestamp}.",
            "DRY RUN: Would download database backup file.",
            "DRY RUN: Would download map configuration file.",
            "DRY RUN: Would download resource configurations file.",
            "DRY RUN: Would download user configurations file.",
            "DRY RUN: Would download media files (floor maps, resource uploads)."
        ]
        # Simulate some progress messages for dry run via socketio if provided
        _emit_progress(socketio_instance, task_id, 'restore_progress', "DRY RUN: Starting full system restore dry run...", detail=f'Timestamp: {backup_timestamp}')
        for action in actions_list:
            _emit_progress(socketio_instance, task_id, 'restore_progress', action, level='INFO')
        _emit_progress(socketio_instance, task_id, 'restore_progress', "DRY RUN: Completed.", detail='SUCCESS', actions=actions_list) # Pass actions here
        return None, None, None, None, actions_list # For dry_run=True, paths are None, actions_list is populated

    _emit_progress(socketio_instance, task_id, 'restore_progress', "Restore Error: Full restore is not implemented.", detail='NOT_IMPLEMENTED', level='ERROR')
    return None, None, None, None, [] # For actual run, paths are None, actions_list is empty

# --- LEGACY - Azure CSV Functionality - Kept for reference / To be removed ---
# def backup_bookings_csv(app, socketio_instance=None, task_id=None, start_date_dt=None, end_date_dt=None, range_label=None):
#     """
#     DEPRECATED / LEGACY
#     Creates a CSV backup of booking data and uploads it to Azure File Share.
#     Range label helps identify the scope of the backup (e.g., "all", "1day", "scheduled_auto").
#     """
#     # This function's body would be here, each line prefixed with #
#     # For brevity, I'm showing only a part of it commented.
#     # if range_label and range_label.strip():
#     #     effective_range_label = range_label.strip()
#     # else:
#     #     effective_range_label = "all"
#     # # ... rest of the function body commented out ...
#     # logger.info(f"Starting LEGACY booking CSV backup process ({log_msg_detail}). Task ID: {task_id}")
# --- Unified Booking Data Protection Functions (Full, Incremental Backup, List, Delete) ---
def backup_full_booking_data_json_azure(app, socketio_instance=None, task_id=None) -> bool:
    event_name = 'full_booking_data_backup_progress'
    _emit_progress(socketio_instance, task_id, event_name, 'Starting full unified booking data JSON backup...', level='INFO')
    logger.info(f"[Task {task_id}] Starting full unified booking data JSON backup process.")
    try:
        with app.app_context():
            all_bookings = Booking.query.all()
        if not all_bookings:
            _emit_progress(socketio_instance, task_id, event_name, "No bookings found to backup.", level='INFO')
            return True
        _emit_progress(socketio_instance, task_id, event_name, f"Found {len(all_bookings)} bookings. Serializing...", level='INFO')
        serialized_bookings = []
        for booking in all_bookings:
            if hasattr(booking, 'to_dict') and callable(getattr(booking, 'to_dict')) :
                serialized_bookings.append(booking.to_dict())
            else:
                created_at_iso = booking.created_at.isoformat() if booking.created_at else None; last_modified_iso = booking.last_modified.isoformat() if booking.last_modified else None; start_time_iso = booking.start_time.isoformat() if booking.start_time else None; end_time_iso = booking.end_time.isoformat() if booking.end_time else None; checked_in_at_iso = booking.checked_in_at.isoformat() if booking.checked_in_at else None; checked_out_at_iso = booking.checked_out_at.isoformat() if booking.checked_out_at else None; token_expires_iso = booking.check_in_token_expires_at.isoformat() if booking.check_in_token_expires_at else None
                serialized_bookings.append({
                    'id': booking.id, 'resource_id': booking.resource_id, 'user_name': booking.user_name, 'start_time': start_time_iso, 'end_time': end_time_iso, 'title': booking.title, 'status': booking.status, 'created_at': created_at_iso, 'last_modified': last_modified_iso, 'is_recurring': booking.is_recurring, 'recurrence_id': booking.recurrence_id, 'is_cancelled': booking.is_cancelled, 'checked_in_at': checked_in_at_iso, 'checked_out_at': checked_out_at_iso, 'admin_deleted_message': booking.admin_deleted_message, 'check_in_token': booking.check_in_token, 'check_in_token_expires_at': token_expires_iso, 'pin': booking.pin
                })
        service_client = _get_service_client()
        share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
        share_client = service_client.get_share_client(share_name)
        if not _client_exists(share_client):
            _create_share_with_retry(share_client, share_name)
        full_backup_dir_on_share = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{BOOKING_DATA_FULL_DIR_SUFFIX}"
        _ensure_directory_exists(share_client, AZURE_BOOKING_DATA_PROTECTION_DIR)
        _ensure_directory_exists(share_client, full_backup_dir_on_share)
        timestamp_for_filename = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        filename = f"booking_data_full_{timestamp_for_filename}.json"
        remote_path_on_azure = f"{full_backup_dir_on_share}/{filename}"
        json_data_bytes = json.dumps(serialized_bookings, indent=4).encode('utf-8')
        file_client = share_client.get_file_client(remote_path_on_azure)
        _emit_progress(socketio_instance, task_id, event_name, f"Uploading {filename} to {share_name}...", level='INFO')
        file_client.upload_file(data=json_data_bytes, overwrite=True)
        _emit_progress(socketio_instance, task_id, event_name, 'Full unified booking data backup uploaded successfully.', detail=f'{share_name}/{remote_path_on_azure}', level='SUCCESS')
        return True
    except Exception as e:
        logger.error(f"[Task {task_id}] Failed to backup full unified booking data to JSON: {e}", exc_info=True)
        _emit_progress(socketio_instance, task_id, event_name, 'Full unified booking data JSON backup failed.', detail=str(e), level='ERROR')
        return False

def get_modified_bookings_since(timestamp_utc: datetime, app):
    with app.app_context():
        return Booking.query.filter(Booking.last_modified >= timestamp_utc).all()

def backup_incremental_bookings_generic(app, output_dir_name_on_share: str, timestamp_file_path_local: str, socket_event_name: str, filename_prefix: str, socketio_instance=None, task_id=None) -> bool:
    _emit_progress(socketio_instance, task_id, socket_event_name, f'Starting {filename_prefix} incremental backup...', level='INFO')
    since_timestamp_utc = None
    try:
        if os.path.exists(timestamp_file_path_local):
            with open(timestamp_file_path_local, 'r', encoding='utf-8') as f:
                timestamp_str = f.read().strip()
            if timestamp_str:
                since_timestamp_utc = datetime.fromisoformat(timestamp_str)
                if since_timestamp_utc.tzinfo is None:
                    since_timestamp_utc = since_timestamp_utc.replace(tzinfo=timezone.utc)
        if since_timestamp_utc is None:
            since_timestamp_utc = datetime(1970, 1, 1, tzinfo=timezone.utc)
        _emit_progress(socketio_instance, task_id, socket_event_name, f"Checking for changes since {since_timestamp_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}...", level='INFO')
    except Exception as e:
        _emit_progress(socketio_instance, task_id, socket_event_name, f"Error reading last backup timestamp for {filename_prefix}.", detail=str(e), level='ERROR'); return False
    current_run_timestamp_utc = datetime.now(timezone.utc)
    modified_bookings_objects = get_modified_bookings_since(since_timestamp_utc, app)
    if not modified_bookings_objects:
        _emit_progress(socketio_instance, task_id, socket_event_name, f"No modified bookings for {filename_prefix} since last backup.", level='INFO')
        try:
            os.makedirs(os.path.dirname(timestamp_file_path_local), exist_ok=True)
            with open(timestamp_file_path_local, 'w', encoding='utf-8') as f: f.write(current_run_timestamp_utc.isoformat())
        except IOError as e_io:
            _emit_progress(socketio_instance, task_id, socket_event_name, f'CRITICAL: Failed to update {filename_prefix} timestamp file after no changes.', detail=str(e_io), level='ERROR')
            return True
        return True
    _emit_progress(socketio_instance, task_id, socket_event_name, f"Found {len(modified_bookings_objects)} modified bookings for {filename_prefix}. Serializing...", level='INFO')
    serialized_bookings = []
    for b in modified_bookings_objects:
        if hasattr(b, 'to_dict') and callable(getattr(b, 'to_dict')):
            serialized_bookings.append(b.to_dict())
        else:
            created_at_iso = b.created_at.isoformat() if b.created_at else None; last_modified_iso = b.last_modified.isoformat() if b.last_modified else None; start_time_iso = b.start_time.isoformat() if b.start_time else None; end_time_iso = b.end_time.isoformat() if b.end_time else None; checked_in_at_iso = b.checked_in_at.isoformat() if b.checked_in_at else None; checked_out_at_iso = b.checked_out_at.isoformat() if b.checked_out_at else None; token_expires_iso = b.check_in_token_expires_at.isoformat() if b.check_in_token_expires_at else None
            serialized_bookings.append({
                'id': b.id, 'resource_id': b.resource_id, 'user_name': b.user_name, 'start_time': start_time_iso, 'end_time': end_time_iso, 'title': b.title, 'status': b.status, 'created_at': created_at_iso, 'last_modified': last_modified_iso, 'is_recurring': b.is_recurring, 'recurrence_id': b.recurrence_id, 'is_cancelled': b.is_cancelled, 'checked_in_at': checked_in_at_iso, 'checked_out_at': checked_out_at_iso, 'admin_deleted_message': b.admin_deleted_message, 'check_in_token': b.check_in_token, 'check_in_token_expires_at': token_expires_iso, 'pin': b.pin
            })
    try:
        service_client = _get_service_client()
        share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
        share_client = service_client.get_share_client(share_name)
        if not _client_exists(share_client): _create_share_with_retry(share_client, share_name)
        _ensure_directory_exists(share_client, output_dir_name_on_share)
        since_ts_str = since_timestamp_utc.strftime('%Y%m%d_%H%M%S')
        current_ts_str = current_run_timestamp_utc.strftime('%Y%m%d_%H%M%S')
        filename = f"{filename_prefix}_from_{since_ts_str}_to_{current_ts_str}.json"
        remote_path_on_azure = f"{output_dir_name_on_share}/{filename}"
        json_data_bytes = json.dumps(serialized_bookings, indent=2).encode('utf-8')
        file_client = share_client.get_file_client(remote_path_on_azure)
        _emit_progress(socketio_instance, task_id, socket_event_name, f"Uploading {filename} ({len(serialized_bookings)} items)...", level='INFO')
        file_client.upload_file(data=json_data_bytes, overwrite=True)
        _emit_progress(socketio_instance, task_id, socket_event_name, f'{filename_prefix} incremental backup uploaded successfully.', detail=remote_path_on_azure, level='SUCCESS')
    except Exception as e:
        _emit_progress(socketio_instance, task_id, socket_event_name, f'{filename_prefix} incremental backup failed during upload.', detail=str(e), level='ERROR'); return False
    try:
        os.makedirs(os.path.dirname(timestamp_file_path_local), exist_ok=True)
        with open(timestamp_file_path_local, 'w', encoding='utf-8') as f: f.write(current_run_timestamp_utc.isoformat())
    except IOError as e_io:
        _emit_progress(socketio_instance, task_id, socket_event_name, f'CRITICAL: Failed to update {filename_prefix} timestamp file after upload.', detail=str(e_io), level='ERROR')
        return True
    return True

def backup_scheduled_incremental_booking_data(app, socketio_instance=None, task_id=None) -> bool:
    return backup_incremental_bookings_generic(
        app=app,
        output_dir_name_on_share=f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{BOOKING_DATA_INCREMENTAL_DIR_SUFFIX}",
        timestamp_file_path_local=LAST_UNIFIED_BOOKING_INCREMENTAL_TIMESTAMP_FILE,
        socket_event_name='scheduled_incremental_booking_backup_progress',
        filename_prefix='unified_booking_incrementals',
        socketio_instance=socketio_instance,
        task_id=task_id
    )

def list_booking_data_json_backups():
    logger.info("Attempting to list available unified booking data JSON backups (full and incremental).")
    backup_items = []
    try:
        service_client = _get_service_client()
        share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
        share_client = service_client.get_share_client(share_name)
        if not _client_exists(share_client): return []
        full_backup_dir_path = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{BOOKING_DATA_FULL_DIR_SUFFIX}"
        full_dir_client = share_client.get_directory_client(full_backup_dir_path)
        if _client_exists(full_dir_client):
            full_pattern = re.compile(r"^booking_data_full_(?P<timestamp>\d{8}_\d{6})\.json$")
            for item in full_dir_client.list_directories_and_files():
                if item['is_directory']: continue
                filename = item['name']
                match = full_pattern.match(filename)
                if not match: continue
                timestamp_str = match.group('timestamp')
                try:
                    ts_datetime = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S').replace(tzinfo=timezone.utc)
                    backup_items.append({
                        'filename': filename, 'type': 'full', 'timestamp': ts_datetime,
                        'display_name': f"Full Booking Data - {ts_datetime.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                    })
                except ValueError: continue
        incremental_backup_dir_path = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{BOOKING_DATA_INCREMENTAL_DIR_SUFFIX}"
        incremental_dir_client = share_client.get_directory_client(incremental_backup_dir_path)
        if _client_exists(incremental_dir_client):
            inc_pattern = re.compile(r"^unified_booking_incrementals_from_(?P<from_timestamp>\d{8}_\d{6})_to_(?P<to_timestamp>\d{8}_\d{6})\.json$")
            for item in incremental_dir_client.list_directories_and_files():
                if item['is_directory']: continue
                filename = item['name']
                match = inc_pattern.match(filename)
                if not match: continue
                to_ts_str = match.group('to_timestamp')
                try:
                    from_dt = datetime.strptime(match.group('from_timestamp'), '%Y%m%d_%H%M%S').replace(tzinfo=timezone.utc)
                    to_dt = datetime.strptime(to_ts_str, '%Y%m%d_%H%M%S').replace(tzinfo=timezone.utc)
                    backup_items.append({
                        'filename': filename, 'type': 'incremental', 'timestamp': to_dt,
                        'from_timestamp_obj': from_dt,
                        'display_name': f"Incremental: {from_dt.strftime('%Y-%m-%d %H:%M')} to {to_dt.strftime('%Y-%m-%d %H:%M UTC')}"
                    })
                except ValueError: continue
        backup_items.sort(key=lambda x: x['timestamp'], reverse=True)
        for item in backup_items:
            item['timestamp_str'] = item['timestamp'].strftime('%Y%m%d_%H%M%S')
            if 'from_timestamp_obj' in item:
                item['from_timestamp_str'] = item['from_timestamp_obj'].strftime('%Y%m%d_%H%M%S')
        return backup_items
    except Exception as e:
        logger.error(f"Error listing unified booking data JSON backups: {e}", exc_info=True)
        return []

def delete_booking_data_json_backup(filename: str, backup_type: str, socketio_instance=None, task_id=None) -> bool:
    event_name = 'unified_booking_data_delete_progress'
    log_prefix = f"[Task {task_id if task_id else 'N/A'}] "
    _emit_progress(socketio_instance, task_id, event_name, f"Starting deletion of {backup_type} backup: {filename}", level='INFO')
    try:
        service_client = _get_service_client()
        share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
        share_client = service_client.get_share_client(share_name)
        if not _client_exists(share_client):
            _emit_progress(socketio_instance, task_id, event_name, f"Azure share '{share_name}' not found.", level='ERROR')
            return False
        sub_dir_suffix = ""
        if backup_type == 'full': sub_dir_suffix = BOOKING_DATA_FULL_DIR_SUFFIX
        elif backup_type == 'incremental': sub_dir_suffix = BOOKING_DATA_INCREMENTAL_DIR_SUFFIX
        else:
            _emit_progress(socketio_instance, task_id, event_name, f"Invalid backup_type '{backup_type}'.", level='ERROR')
            return False
        remote_file_path = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{sub_dir_suffix}/{filename}"
        file_client = share_client.get_file_client(remote_file_path)
        if not _client_exists(file_client):
            if backup_type == 'full' and (filename.startswith("booking_data_backup_") or filename.startswith("booking_data_full_")):
                legacy_path_attempt = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{filename}"
                legacy_file_client = share_client.get_file_client(legacy_path_attempt)
                if _client_exists(legacy_file_client):
                    file_client = legacy_file_client
                    remote_file_path = legacy_path_attempt
                else:
                    _emit_progress(socketio_instance, task_id, event_name, "File not found, assuming already deleted.", detail=remote_file_path, level='INFO')
                    return True
            else:
                _emit_progress(socketio_instance, task_id, event_name, "File not found, assuming already deleted.", detail=remote_file_path, level='INFO')
                return True
        _emit_progress(socketio_instance, task_id, event_name, f"File '{filename}' found at {remote_file_path}. Deleting...", level='INFO')
        file_client.delete_file()
        _emit_progress(socketio_instance, task_id, event_name, f"{backup_type.capitalize()} backup '{filename}' deleted.", detail=remote_file_path, level='SUCCESS')
        return True
    except ResourceNotFoundError:
        _emit_progress(socketio_instance, task_id, event_name, "File not found (ResourceNotFoundError).", detail=filename, level='INFO')
        return True
    except Exception as e:
        _emit_progress(socketio_instance, task_id, event_name, f"Error during {backup_type} file deletion.", detail=str(e), level='ERROR')
        return False

# --- Point-in-Time Restore Core Logic ---
def _apply_single_incremental_json_file(app, incremental_filename: str, temp_download_path: str, socketio_instance=None, task_id=None, event_name='booking_data_protection_restore_progress') -> dict:
    summary = {'applied': 0, 'updated': 0, 'created': 0, 'errors': []}
    log_prefix = f"[Task {task_id if task_id else 'PIT_Restore'}]"
    _emit_progress(socketio_instance, task_id, event_name, f"Applying incremental file: {incremental_filename}", level='INFO')
    logger.info(f"{log_prefix} Applying incremental file: {incremental_filename}")
    service_client = _get_service_client()
    share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
    share_client = service_client.get_share_client(share_name)
    if not _client_exists(share_client):
        msg = f"Azure share '{share_name}' not found for incremental restore."
        summary['errors'].append(msg); logger.error(f"{log_prefix} {msg}")
        _emit_progress(socketio_instance, task_id, event_name, msg, level='ERROR')
        return summary
    remote_file_path = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{BOOKING_DATA_INCREMENTAL_DIR_SUFFIX}/{incremental_filename}"
    if not download_file(share_client, remote_file_path, temp_download_path):
        msg = f"Failed to download incremental file '{incremental_filename}' from '{remote_file_path}'."
        summary['errors'].append(msg); logger.error(f"{log_prefix} {msg}")
        _emit_progress(socketio_instance, task_id, event_name, msg, level='ERROR')
        return summary
    try:
        with open(temp_download_path, 'r', encoding='utf-8') as f:
            bookings_data = json.load(f)
        with app.app_context():
            items_in_file_processed = 0
            for booking_json in bookings_data:
                items_in_file_processed +=1
                try:
                    booking_id = booking_json.get('id')
                    if not booking_id:
                        summary['errors'].append(f"Missing 'id' in booking data in {incremental_filename}. Item data: {booking_json[:100]}")
                        continue
                    for dt_field in ['start_time', 'end_time', 'created_at', 'last_modified', 'checked_in_at', 'checked_out_at', 'check_in_token_expires_at']:
                        if booking_json.get(dt_field): booking_json[dt_field] = datetime.fromisoformat(booking_json[dt_field])
                        else: booking_json[dt_field] = None
                    existing_booking = Booking.query.get(booking_id)
                    if existing_booking:
                        json_lm_aware = booking_json.get('last_modified')
                        if json_lm_aware and json_lm_aware.tzinfo is None: json_lm_aware = json_lm_aware.replace(tzinfo=timezone.utc)
                        db_lm_aware = existing_booking.last_modified
                        if db_lm_aware and db_lm_aware.tzinfo is None: db_lm_aware = db_lm_aware.replace(tzinfo=timezone.utc)
                        if json_lm_aware and db_lm_aware and json_lm_aware < db_lm_aware:
                            logger.warning(f"{log_prefix} Incremental {incremental_filename}: Skipping update for booking ID {booking_id} as backup data is older ({json_lm_aware}) than current DB data ({db_lm_aware}).")
                            summary['errors'].append(f"Skipped update for booking ID {booking_id} (older data in {incremental_filename}).")
                            continue
                        for key, value in booking_json.items():
                            if hasattr(existing_booking, key): setattr(existing_booking, key, value)
                        summary['updated'] += 1
                    else:
                        new_booking_data = {key: val for key, val in booking_json.items() if hasattr(Booking, key)}
                        new_booking = Booking(**new_booking_data)
                        db.session.add(new_booking)
                        summary['created'] += 1
                    summary['applied'] +=1
                except Exception as e_item:
                    err_msg_item = f"Error processing item (original ID {booking_json.get('id', 'Unknown')}) in {incremental_filename}: {str(e_item)}"
                    logger.error(f"{log_prefix} {err_msg_item}", exc_info=True)
                    summary['errors'].append(err_msg_item)
                    _emit_progress(socketio_instance, task_id, event_name, f"Error in {incremental_filename}.", detail=err_msg_item, level='WARNING')
            if not summary['errors'] or (summary['created'] > 0 or summary['updated'] > 0) :
                db.session.commit()
                logger.info(f"{log_prefix} Committed changes from {incremental_filename}. Created: {summary['created']}, Updated: {summary['updated']}.")
            elif summary['errors'] and not (summary['created'] > 0 or summary['updated'] > 0):
                db.session.rollback()
                logger.warning(f"{log_prefix} Rolled back {incremental_filename} due to only errors and no successful operations.")
    except json.JSONDecodeError as json_err:
        msg = f"Invalid JSON in incremental file '{incremental_filename}': {json_err}"
        summary['errors'].append(msg); logger.error(f"{log_prefix} {msg}", exc_info=True)
        _emit_progress(socketio_instance, task_id, event_name, msg, level='ERROR')
    except Exception as e_file:
        msg = f"Error processing incremental file '{incremental_filename}': {str(e_file)}"
        summary['errors'].append(msg); logger.error(f"{log_prefix} {msg}", exc_info=True)
        _emit_progress(socketio_instance, task_id, event_name, msg, level='ERROR')
    finally:
        if os.path.exists(temp_download_path):
            try: os.remove(temp_download_path)
            except OSError as e_remove: logger.error(f"{log_prefix} Error removing temp incremental file {temp_download_path}: {e_remove}")
    _emit_progress(socketio_instance, task_id, event_name, f"Finished applying {incremental_filename}. Applied: {summary['applied']}, Created: {summary['created']}, Updated: {summary['updated']}, Errors: {len(summary['errors'])}", level='INFO' if not summary['errors'] else 'WARNING')
    return summary

def restore_booking_data_from_json_backup(app, filename: str, backup_type: str, socketio_instance=None, task_id=None) -> dict:
    event_name = 'booking_data_protection_restore_progress'
    summary = {'status': 'started', 'message': f'Starting FULL restore from JSON backup: {filename}.', 'errors': [], 'bookings_restored':0 }
    _emit_progress(socketio_instance, task_id, event_name, summary['message'], level='INFO')
    log_prefix = f"[Task {task_id if task_id else 'FullRestore'}]"
    logger.info(f"{log_prefix} {summary['message']}")
    if backup_type != 'full':
        msg = "This function is only for 'full' backup type restores."
        summary.update({'status': 'failure', 'message': msg, 'errors': [msg]})
        logger.error(f"{log_prefix} {msg}")
        _emit_progress(socketio_instance, task_id, event_name, msg, level='ERROR')
        return summary
    temp_downloaded_file_path = None
    try:
        service_client = _get_service_client()
        share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
        share_client = service_client.get_share_client(share_name)
        if not _client_exists(share_client):
            msg = f"Azure share '{share_name}' not found."
            summary.update({'status': 'failure', 'message': msg, 'errors': [msg]}); return summary
        remote_file_path = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{BOOKING_DATA_FULL_DIR_SUFFIX}/{filename}"
        file_client = share_client.get_file_client(remote_file_path)
        if not _client_exists(file_client) and (filename.startswith("booking_data_backup_") or filename.startswith("booking_data_full_")):
            legacy_path_attempt = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{filename}"
            legacy_fc = share_client.get_file_client(legacy_path_attempt)
            if _client_exists(legacy_fc):
                logger.warning(f"{log_prefix} File '{filename}' not in '{BOOKING_DATA_FULL_DIR_SUFFIX}/' but found at legacy path. Using: {legacy_path_attempt}")
                file_client = legacy_fc; remote_file_path = legacy_path_attempt
            else:
                msg = f"Full JSON backup file '{filename}' not found in primary or legacy locations."
                summary.update({'status': 'failure', 'message': msg, 'errors': [msg]}); return summary
        elif not _client_exists(file_client):
             msg = f"Full JSON backup file '{filename}' not found at '{remote_file_path}'."
             summary.update({'status': 'failure', 'message': msg, 'errors': [msg]}); return summary
        with tempfile.NamedTemporaryFile(delete=False, suffix='.json') as tmp_file: temp_downloaded_file_path = tmp_file.name
        if not download_file(share_client, remote_file_path, temp_downloaded_file_path):
            msg = f"Failed to download '{filename}'."
            summary.update({'status': 'failure', 'message': msg, 'errors': [msg]}); return summary
        _emit_progress(socketio_instance, task_id, event_name, "Download complete. Clearing existing bookings and importing...", level='INFO')
        with app.app_context():
            logger.info(f"{log_prefix} Clearing existing bookings from the database for full restore.")
            db.session.query(Booking).delete()
            with open(temp_downloaded_file_path, 'r', encoding='utf-8') as f: bookings_data = json.load(f)
            count_restored = 0
            for booking_json in bookings_data:
                try:
                    for dt_field in ['start_time', 'end_time', 'created_at', 'last_modified', 'checked_in_at', 'checked_out_at', 'check_in_token_expires_at']:
                        if booking_json.get(dt_field): booking_json[dt_field] = datetime.fromisoformat(booking_json[dt_field])
                        else: booking_json[dt_field] = None
                    new_booking = Booking(**booking_json)
                    db.session.add(new_booking)
                    count_restored += 1
                except Exception as e_item:
                    db.session.rollback()
                    err_msg_item = f"Error processing booking item (original ID {booking_json.get('id', 'Unknown')}) during full restore: {str(e_item)}"
                    logger.error(f"{log_prefix} {err_msg_item}", exc_info=True)
                    summary['errors'].append(err_msg_item)
            if not summary['errors']:
                db.session.commit()
                summary.update({'status': 'success', 'message': f"Successfully restored {count_restored} bookings from '{filename}'.", 'bookings_restored': count_restored})
            else:
                db.session.rollback()
                summary.update({'status': 'failure', 'message': f"Full restore from '{filename}' completed with {len(summary['errors'])} errors. No bookings committed."})
    except Exception as e:
        if hasattr(db, 'session') and db.session.is_active: db.session.rollback()
        msg = f"Critical error during full restore from '{filename}': {str(e)}"
        summary.update({'status': 'failure', 'message': msg}); summary['errors'].append(msg)
        logger.error(f"{log_prefix} {msg}", exc_info=True)
    finally:
        if temp_downloaded_file_path and os.path.exists(temp_downloaded_file_path):
            try: os.remove(temp_downloaded_file_path)
            except OSError as e_rem: logger.error(f"{log_prefix} Error removing temp file {temp_downloaded_file_path}: {e_rem}")
    _emit_progress(socketio_instance, task_id, event_name, summary['message'], level='SUCCESS' if summary['status']=='success' else 'ERROR')
    return summary

def restore_booking_data_to_point_in_time(app, selected_filename: str, selected_type: str, selected_timestamp_iso: str, socketio_instance=None, task_id=None) -> dict:
    event_name = 'booking_data_protection_restore_progress'
    overall_summary = {
        'status': 'started',
        'message': f"Point-in-time restore initiated for {selected_type} backup '{selected_filename}' (timestamp: {selected_timestamp_iso}).",
        'errors': [], 'full_restore_summary': None, 'incrementals_applied_summaries': []
    }
    log_prefix = f"[Task {task_id if task_id else 'PIT_Restore'}]"
    _emit_progress(socketio_instance, task_id, event_name, overall_summary['message'], level='INFO')
    logger.info(f"{log_prefix} {overall_summary['message']}")
    temp_incremental_download_dir = None
    try:
        selected_datetime_obj = datetime.fromisoformat(selected_timestamp_iso)
        if selected_datetime_obj.tzinfo is None:
            selected_datetime_obj = selected_datetime_obj.replace(tzinfo=timezone.utc)
        if selected_type == 'full':
            _emit_progress(socketio_instance, task_id, event_name, f"Performing full restore of '{selected_filename}'.", level='INFO')
            full_restore_summary = restore_booking_data_from_json_backup(app, selected_filename, 'full', socketio_instance, task_id)
            overall_summary['full_restore_summary'] = full_restore_summary
            overall_summary['status'] = full_restore_summary['status']
            overall_summary['message'] = full_restore_summary['message']
            overall_summary['errors'].extend(full_restore_summary.get('errors', []))
            return overall_summary
        elif selected_type == 'incremental':
            _emit_progress(socketio_instance, task_id, event_name, "Incremental restore: Locating suitable base full backup.", level='INFO')
            all_backups = list_booking_data_json_backups()
            suitable_full_backups = sorted(
                [b for b in all_backups if b['type'] == 'full' and b['timestamp'] <= selected_datetime_obj],
                key=lambda x: x['timestamp'], reverse=True
            )
            if not suitable_full_backups:
                msg = "No suitable full backup found prior to or at the selected incremental's timestamp. Cannot proceed."
                overall_summary.update({'status': 'failure', 'message': msg, 'errors': [msg]})
                _emit_progress(socketio_instance, task_id, event_name, msg, level='ERROR'); logger.error(f"{log_prefix} {msg}")
                return overall_summary
            latest_suitable_full_backup = suitable_full_backups[0]
            _emit_progress(socketio_instance, task_id, event_name, f"Base full backup found: {latest_suitable_full_backup['filename']}. Restoring...", level='INFO')
            logger.info(f"{log_prefix} Restoring base full backup: {latest_suitable_full_backup['filename']} (Timestamp: {latest_suitable_full_backup['timestamp']})")
            full_restore_summary = restore_booking_data_from_json_backup(app, latest_suitable_full_backup['filename'], 'full', socketio_instance, task_id)
            overall_summary['full_restore_summary'] = full_restore_summary
            if full_restore_summary['status'] != 'success':
                msg = f"Failed to restore base full backup '{latest_suitable_full_backup['filename']}'. Cannot apply incrementals."
                overall_summary.update({'status': 'failure', 'message': msg})
                overall_summary['errors'].extend(full_restore_summary.get('errors', []))
                _emit_progress(socketio_instance, task_id, event_name, msg, level='ERROR'); logger.error(f"{log_prefix} {msg}")
                return overall_summary
            _emit_progress(socketio_instance, task_id, event_name, "Base full backup restored. Applying subsequent incremental backups...", level='INFO')
            incrementals_to_apply = sorted(
                [b for b in all_backups if b['type'] == 'incremental' and
                                           b['timestamp'] > latest_suitable_full_backup['timestamp'] and
                                           b['timestamp'] <= selected_datetime_obj],
                key=lambda x: x['timestamp']
            )
            if not incrementals_to_apply:
                overall_summary['status'] = 'success'
                overall_summary['message'] = f"Full backup '{latest_suitable_full_backup['filename']}' restored. No subsequent incrementals found up to selected point."
                _emit_progress(socketio_instance, task_id, event_name, overall_summary['message'], level='INFO')
                logger.info(f"{log_prefix} {overall_summary['message']}")
                return overall_summary
            logger.info(f"{log_prefix} Found {len(incrementals_to_apply)} incremental backups to apply after full backup {latest_suitable_full_backup['filename']}.")
            temp_incremental_download_dir = tempfile.mkdtemp(prefix="pit_restore_inc_")
            total_incrementals_applied_successfully = 0
            for inc_backup_info in incrementals_to_apply:
                _emit_progress(socketio_instance, task_id, event_name, f"Applying incremental: {inc_backup_info['filename']}", level='INFO')
                temp_file_path = os.path.join(temp_incremental_download_dir, inc_backup_info['filename'])
                inc_summary = _apply_single_incremental_json_file(app, inc_backup_info['filename'], temp_file_path, socketio_instance, task_id, event_name)
                overall_summary['incrementals_applied_summaries'].append(inc_summary)
                if inc_summary.get('errors'):
                    overall_summary['errors'].extend(inc_summary['errors'])
                    logger.warning(f"{log_prefix} Errors applying incremental {inc_backup_info['filename']}: {inc_summary['errors']}")
                    _emit_progress(socketio_instance, task_id, event_name, f"Errors encountered while applying {inc_backup_info['filename']}. Check logs.", level='WARNING')
                if inc_summary.get('applied', 0) > 0 or (not inc_summary.get('errors') and inc_summary.get('applied',0)==0) :
                    total_incrementals_applied_successfully +=1
            if not overall_summary['errors']:
                overall_summary['status'] = 'success'
                overall_summary['message'] = f"Point-in-time restore completed. Full backup '{latest_suitable_full_backup['filename']}' and {len(incrementals_to_apply)} incremental(s) applied."
            else:
                overall_summary['status'] = 'partial_success' if total_incrementals_applied_successfully > 0 or full_restore_summary['status'] == 'success' else 'failure'
                overall_summary['message'] = f"Point-in-time restore completed with errors. Full: '{latest_suitable_full_backup['filename']}', Incrementals attempted: {len(incrementals_to_apply)}. Check details."
            logger.info(f"{log_prefix} {overall_summary['message']}")
            _emit_progress(socketio_instance, task_id, event_name, overall_summary['message'], level='SUCCESS' if overall_summary['status'] == 'success' else 'WARNING')
        else:
            msg = f"Invalid selected_type '{selected_type}' for point-in-time restore."
            overall_summary.update({'status': 'failure', 'message': msg, 'errors': [msg]})
            _emit_progress(socketio_instance, task_id, event_name, msg, level='ERROR'); logger.error(f"{log_prefix} {msg}")
    except Exception as e:
        msg = f"Critical error during point-in-time restore: {str(e)}"
        overall_summary.update({'status': 'failure', 'message': msg}); overall_summary['errors'].append(msg)
        logger.error(f"{log_prefix} {msg}", exc_info=True)
        _emit_progress(socketio_instance, task_id, event_name, msg, level='CRITICAL_ERROR')
        if hasattr(db, 'session') and db.session.is_active:
            db.session.rollback()
            logger.info(f"{log_prefix} Rolled back database session due to critical error in PIT restore.")
    finally:
        if temp_incremental_download_dir and os.path.exists(temp_incremental_download_dir):
            try:
                shutil.rmtree(temp_incremental_download_dir)
                logger.info(f"{log_prefix} Cleaned up temporary directory: {temp_incremental_download_dir}")
            except OSError as e_rmdir:
                logger.error(f"{log_prefix} Error removing temporary directory {temp_incremental_download_dir}: {e_rmdir}")
                overall_summary['errors'].append(f"Cleanup error: {e_rmdir}")
    return overall_summary

# --- Legacy/Original Non-CSV JSON Export and Incremental Functions ---
def list_available_incremental_booking_backups():
    logger.info("Attempting to list available (legacy) incremental booking backups.")
    return []

# --- Full System Backup Functions ---
def create_full_backup(timestamp_str, map_config_data=None, resource_configs_data=None, user_configs_data=None, socketio_instance=None, task_id=None):
    overall_success = True # Initialize at the start of the function
    backed_up_items = [] # Initialize list to track backed up items
    _emit_progress(socketio_instance, task_id, 'backup_progress', "Attempting to initialize Azure service client for backup...", level='INFO')
    try:
        service_client = _get_service_client() # Call this at the beginning
        if not service_client: # Should not happen if _get_service_client raises error on failure
            _emit_progress(socketio_instance, task_id, 'backup_progress', "Failed to get Azure service client (returned None).", level='ERROR')
            return False # Critical failure, cannot proceed
        _emit_progress(socketio_instance, task_id, 'backup_progress', "Azure service client initialized.", level='INFO')
    except RuntimeError as e:
        # This exception (e.g. missing connection string or SDK not installed) will be caught by the calling function in api_system.py
        logger.error(f"RuntimeError during _get_service_client in create_full_backup: {str(e)}")
        _emit_progress(socketio_instance, task_id, 'backup_progress', f"Backup Pre-check Failed: {str(e)}", detail=str(e), level='ERROR')
        raise # Re-raise the error so api_system.py can catch it and handle it as an operational failure

    # --- Database Backup ---
    _emit_progress(socketio_instance, task_id, 'backup_progress', "Starting database backup...", level='INFO')
    db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
    db_share_client = None
    try:
        db_share_client = service_client.get_share_client(db_share_name)
        if not _create_share_with_retry(db_share_client, db_share_name):
            _emit_progress(socketio_instance, task_id, 'backup_progress', f"Failed to create or access DB share: {db_share_name}", level='ERROR')
            return False # Critical failure

        _ensure_directory_exists(db_share_client, DB_BACKUPS_DIR) # Ensure base directory for DB backups

        local_db_path = os.path.join(DATA_DIR, 'site.db') # Assuming this is the DB path
        db_backup_filename = f"{DB_FILENAME_PREFIX}{timestamp_str}.db"
        remote_db_file_path = f"{DB_BACKUPS_DIR}/{db_backup_filename}"

        if not os.path.exists(local_db_path):
            _emit_progress(socketio_instance, task_id, 'backup_progress', f"Local database file not found at {local_db_path}", level='ERROR')
            return False # Critical failure

        _emit_progress(socketio_instance, task_id, 'backup_progress', f"Uploading database '{local_db_path}' to '{db_share_name}/{remote_db_file_path}'...", level='INFO')
        if upload_file(db_share_client, local_db_path, remote_db_file_path):
            _emit_progress(socketio_instance, task_id, 'backup_progress', "Database backup successful.", level='SUCCESS')
            backed_up_items.append({
                "type": "database",
                "source_path": local_db_path,
                "azure_path": f"{db_share_name}/{remote_db_file_path}",
                "filename": db_backup_filename
            })
        else:
            _emit_progress(socketio_instance, task_id, 'backup_progress', "Database backup failed during upload.", level='ERROR')
            # overall_success = False # Set flag, but for now, requirement is to return False directly
            return False
    except Exception as e_db:
        logger.error(f"Error during database backup: {e_db}", exc_info=True)
        _emit_progress(socketio_instance, task_id, 'backup_progress', f"Database backup failed: {str(e_db)}", level='ERROR')
        # overall_success = False
        return False

    # --- Configuration Data Backup ---
    _emit_progress(socketio_instance, task_id, 'backup_progress', "Starting configuration data backup...", level='INFO')
    config_share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
    config_share_client = None
    try:
        config_share_client = service_client.get_share_client(config_share_name)
        if not _create_share_with_retry(config_share_client, config_share_name):
            _emit_progress(socketio_instance, task_id, 'backup_progress', f"Failed to create or access Config share: {config_share_name}", level='ERROR')
            return False # Critical failure for configs as a whole

        _ensure_directory_exists(config_share_client, CONFIG_BACKUPS_DIR)

        configs_to_backup = [
            (map_config_data, "map_config", MAP_CONFIG_FILENAME_PREFIX),
            (resource_configs_data, "resource_configs", "resource_configs_"), # Using a new prefix
            (user_configs_data, "user_configs", "user_configs_")          # Using a new prefix
        ]

        for config_data, config_name, filename_prefix in configs_to_backup:
            _emit_progress(socketio_instance, task_id, 'backup_progress', f"Processing {config_name} backup...", level='INFO')
            if not config_data: # Handles None or empty dict/list
                _emit_progress(socketio_instance, task_id, 'backup_progress', f"{config_name} data is empty, skipping.", level='INFO')
                continue

            tmp_file_path = None
            try:
                # Using delete=False, so we manage deletion in the finally block
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8', dir=DATA_DIR) as tmp_file:
                    json.dump(config_data, tmp_file, indent=4)
                    tmp_file_path = tmp_file.name

                config_backup_filename = f"{filename_prefix}{timestamp_str}.json"
                remote_config_file_path = f"{CONFIG_BACKUPS_DIR}/{config_backup_filename}"

                _emit_progress(socketio_instance, task_id, 'backup_progress', f"Uploading {config_name} ({config_backup_filename}) to '{config_share_name}/{remote_config_file_path}'...", level='INFO')
                if upload_file(config_share_client, tmp_file_path, remote_config_file_path):
                    _emit_progress(socketio_instance, task_id, 'backup_progress', f"{config_name} backup successful.", level='SUCCESS')
                    backed_up_items.append({
                        "type": "config",
                        "config_name": config_name,
                        "source_data_type": str(type(config_data)),
                        "azure_path": f"{config_share_name}/{remote_config_file_path}",
                        "filename": config_backup_filename
                    })
                else:
                    _emit_progress(socketio_instance, task_id, 'backup_progress', f"{config_name} backup failed during upload.", level='ERROR')
                    overall_success = False # Continue with other configs but mark overall as failed
            except Exception as e_conf_item: # Catch error for individual config processing/upload
                logger.error(f"Error during {config_name} backup: {e_conf_item}", exc_info=True)
                _emit_progress(socketio_instance, task_id, 'backup_progress', f"{config_name} backup failed: {str(e_conf_item)}", level='ERROR')
                overall_success = False
            finally:
                if tmp_file_path and os.path.exists(tmp_file_path):
                    try:
                        os.remove(tmp_file_path)
                    except OSError as e_remove:
                        logger.error(f"Error removing temporary config file {tmp_file_path}: {e_remove}")
                        _emit_progress(socketio_instance, task_id, 'backup_progress', f"Error cleaning up temp file for {config_name}: {str(e_remove)}", level='WARNING')

    except Exception as e_config_share_setup: # Catch errors from share/dir setup for configs
        logger.error(f"Error during configuration share/directory setup: {e_config_share_setup}", exc_info=True)
        _emit_progress(socketio_instance, task_id, 'backup_progress', f"Configuration backup stage failed critically: {str(e_config_share_setup)}", level='ERROR')
        overall_success = False # Mark as failed
        return False # Critical failure for the entire backup operation if config share setup fails

    # --- Media Files Backup ---
    if overall_success: # Only proceed if previous critical steps were okay
        _emit_progress(socketio_instance, task_id, 'backup_progress', "Starting media files backup...", level='INFO')
        media_share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media-backups')
        media_share_client = None
        try:
            media_share_client = service_client.get_share_client(media_share_name)
            if not _create_share_with_retry(media_share_client, media_share_name):
                _emit_progress(socketio_instance, task_id, 'backup_progress', f"Failed to create or access Media share: {media_share_name}", level='ERROR')
                return False # Critical failure for media backup stage

            # Timestamped parent directory for this backup's media
            timestamped_media_backup_base_dir = f"{MEDIA_BACKUPS_DIR_BASE}/backup_{timestamp_str}"
            _ensure_directory_exists(media_share_client, MEDIA_BACKUPS_DIR_BASE) # Ensure base 'media_backups' dir
            _ensure_directory_exists(media_share_client, timestamped_media_backup_base_dir) # Ensure 'media_backups/backup_YYYYMMDD_HHMMSS'

            media_sources = [
                {"name": "Floor Map Uploads", "local_path": FLOOR_MAP_UPLOADS, "azure_subdir": "floor_map_uploads"},
                {"name": "Resource Uploads", "local_path": RESOURCE_UPLOADS, "azure_subdir": "resource_uploads"}
            ]

            for media_source in media_sources:
                media_type_name = media_source["name"]
                local_folder_path = media_source["local_path"]
                azure_target_sub_dir_name = media_source["azure_subdir"]

                _emit_progress(socketio_instance, task_id, 'backup_progress', f"Processing {media_type_name} backup from '{local_folder_path}'...", level='INFO')

                if not os.path.isdir(local_folder_path):
                    _emit_progress(socketio_instance, task_id, 'backup_progress', f"Local folder for {media_type_name} ('{local_folder_path}') not found, skipping.", level='WARNING')
                    continue

                # Specific Azure directory for this media type for this backup run
                azure_media_type_target_dir = f"{timestamped_media_backup_base_dir}/{azure_target_sub_dir_name}"
                try:
                    _ensure_directory_exists(media_share_client, azure_media_type_target_dir)
                except Exception as e_dir_create:
                    logger.error(f"Failed to create Azure directory '{azure_media_type_target_dir}' for {media_type_name}: {e_dir_create}", exc_info=True)
                    _emit_progress(socketio_instance, task_id, 'backup_progress', f"Failed to create Azure directory for {media_type_name}, skipping. Error: {str(e_dir_create)}", level='ERROR')
                    overall_success = False
                    continue # Skip this media type if its directory cannot be created

                files_in_local_folder = os.listdir(local_folder_path)
                if not files_in_local_folder:
                    _emit_progress(socketio_instance, task_id, 'backup_progress', f"No files found in {media_type_name} at '{local_folder_path}', skipping.", level='INFO')
                    continue

                file_backup_count = 0
                successful_uploads_count = 0
                for filename in files_in_local_folder:
                    local_file_path = os.path.join(local_folder_path, filename)
                    if os.path.isfile(local_file_path):
                        file_backup_count +=1
                        remote_media_file_path = f"{azure_media_type_target_dir}/{filename}"
                        # Reduced verbosity for individual file uploads unless an error occurs
                        # _emit_progress(socketio_instance, task_id, 'backup_progress', f"Uploading {media_type_name} file '{filename}' to '{media_share_name}/{remote_media_file_path}'...", level='DEBUG')
                        if upload_file(media_share_client, local_file_path, remote_media_file_path):
                            successful_uploads_count += 1
                            backed_up_items.append({
                                "type": "media",
                                "media_type": media_type_name,
                                "source_path": local_file_path,
                                "azure_path": f"{media_share_name}/{remote_media_file_path}",
                                "filename": filename
                            })
                        else:
                            _emit_progress(socketio_instance, task_id, 'backup_progress', f"Backup of {media_type_name} file '{filename}' failed.", level='ERROR')
                            overall_success = False # Continue with other files but mark overall as failed
                _emit_progress(socketio_instance, task_id, 'backup_progress', f"{successful_uploads_count}/{file_backup_count} file(s) successfully backed up for {media_type_name}.", level='INFO' if successful_uploads_count == file_backup_count else 'WARNING')

        except Exception as e_media_share_setup: # Errors from media share or top-level timestamped dir creation
            logger.error(f"Error during media files share/directory setup: {e_media_share_setup}", exc_info=True)
            _emit_progress(socketio_instance, task_id, 'backup_progress', f"Media files backup stage failed critically: {str(e_media_share_setup)}", level='ERROR')
            overall_success = False # Mark as failed
            return False # Critical failure for the entire backup operation

    # --- Manifest File Creation and Upload ---
    if overall_success: # Only create manifest if all previous steps deemed critical were successful
        _emit_progress(socketio_instance, task_id, 'backup_progress', "Creating backup manifest...", level='INFO')
        manifest_data = {
            "backup_timestamp_utc": timestamp_str,
            "backup_format_version": "1.0",
            "status": "success", # If we are here, overall_success was true
            "files": backed_up_items,
            "summary": {
                "total_files_listed": len(backed_up_items),
                "database_files": sum(1 for item in backed_up_items if item["type"] == "database"),
                "config_files": sum(1 for item in backed_up_items if item["type"] == "config"),
                "media_files": sum(1 for item in backed_up_items if item["type"] == "media"),
            }
        }
        tmp_manifest_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8', dir=DATA_DIR) as tmp_file:
                json.dump(manifest_data, tmp_file, indent=4)
                tmp_manifest_path = tmp_file.name

            manifest_filename = f"backup_manifest_{timestamp_str}.json"
            # Upload manifest to the DB backup share and directory for co-location with DB backup
            if db_share_client: # db_share_client should be defined from DB backup step
                remote_manifest_path = f"{DB_BACKUPS_DIR}/{manifest_filename}"
                _emit_progress(socketio_instance, task_id, 'backup_progress', f"Uploading backup manifest '{manifest_filename}' to '{db_share_name}/{remote_manifest_path}'...", level='INFO')
                if upload_file(db_share_client, tmp_manifest_path, remote_manifest_path):
                    _emit_progress(socketio_instance, task_id, 'backup_progress', "Backup manifest uploaded successfully.", level='SUCCESS')
                else:
                    _emit_progress(socketio_instance, task_id, 'backup_progress', "Failed to upload backup manifest.", level='ERROR')
                    overall_success = False # Manifest is critical for a complete backup set
            else:
                _emit_progress(socketio_instance, task_id, 'backup_progress', "DB share client not available for manifest upload. Skipping manifest.", level='ERROR')
                overall_success = False

        except Exception as e_manifest:
            logger.error(f"Error creating or uploading manifest: {e_manifest}", exc_info=True)
            _emit_progress(socketio_instance, task_id, 'backup_progress', f"Error creating or uploading manifest: {str(e_manifest)}", level='ERROR')
            overall_success = False
        finally:
            if tmp_manifest_path and os.path.exists(tmp_manifest_path):
                try:
                    os.remove(tmp_manifest_path)
                except OSError as e_remove_manifest:
                    logger.error(f"Error removing temporary manifest file {tmp_manifest_path}: {e_remove_manifest}")
                    _emit_progress(socketio_instance, task_id, 'backup_progress', f"Error cleaning up temp manifest file: {str(e_remove_manifest)}", level='WARNING')
    elif not overall_success:
         _emit_progress(socketio_instance, task_id, 'backup_progress', "Skipping manifest creation due to previous errors in backup process.", level='WARNING')


    # At the very end of create_full_backup, after all steps:
    if overall_success:
       _emit_progress(socketio_instance, task_id, 'backup_progress', "Full system backup completed successfully.", detail='Overall Success', level='SUCCESS')
    else:
       _emit_progress(socketio_instance, task_id, 'backup_progress', "Full system backup completed with one or more failures.", detail='Overall Failure', level='ERROR')
    return overall_success

def backup_database():
    logger.info("Simulating backup_database")
    # This is a placeholder. The actual logic for backing up the database should be here.
    return "mock_db_backup.db" # Simulate returning a filename

def download_booking_data_json_backup(filename: str, backup_type: str):
    """
    Downloads a specific unified booking data JSON backup file (full or incremental) from Azure File Share.

    Args:
        filename (str): The name of the backup file to download.
        backup_type (str): The type of backup ('full' or 'incremental').

    Returns:
        bytes: The content of the downloaded file if successful, None otherwise.
    """
    logger.info(f"Attempting to download unified booking data backup: Type='{backup_type}', Filename='{filename}'.")
    try:
        service_client = _get_service_client()
        share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups') # Uses the same share as other configs
        share_client = service_client.get_share_client(share_name)

        if not _client_exists(share_client):
            logger.error(f"Azure share '{share_name}' not found for downloading backup '{filename}'.")
            return None

        if backup_type == 'full':
            sub_dir_suffix = BOOKING_DATA_FULL_DIR_SUFFIX
        elif backup_type == 'incremental':
            sub_dir_suffix = BOOKING_DATA_INCREMENTAL_DIR_SUFFIX
        else:
            logger.error(f"Invalid backup_type '{backup_type}' specified for download. Must be 'full' or 'incremental'.")
            return None

        # Construct the remote file path on Azure
        # Base directory for unified backups + type-specific suffix + filename
        remote_file_path = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{sub_dir_suffix}/{filename}"

        file_client = share_client.get_file_client(remote_file_path)

        if not _client_exists(file_client):
            # Attempt to check legacy path for full backups for backward compatibility
            if backup_type == 'full' and (filename.startswith("booking_data_backup_") or filename.startswith("booking_data_full_")):
                legacy_path_attempt = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{filename}"
                logger.warning(f"File '{filename}' not found at primary path '{remote_file_path}'. Attempting legacy path: '{legacy_path_attempt}'")
                legacy_file_client = share_client.get_file_client(legacy_path_attempt)
                if _client_exists(legacy_file_client):
                    file_client = legacy_file_client # Use the legacy client if file found there
                    logger.info(f"File found at legacy path: {legacy_path_attempt}")
                else:
                    logger.error(f"Unified backup file '{filename}' not found at primary path '{remote_file_path}' or legacy path '{legacy_path_attempt}'.")
                    return None
            else:
                logger.error(f"Unified backup file '{filename}' not found at path '{remote_file_path}'.")
                return None

        logger.info(f"Downloading file '{filename}' from '{file_client.share_name}/{file_client.file_path}'...")
        download_stream = file_client.download_file()
        file_content = download_stream.readall()
        logger.info(f"Successfully downloaded {len(file_content)} bytes for backup '{filename}'.")
        return file_content

    except ResourceNotFoundError:
        logger.error(f"ResourceNotFoundError: Unified backup file '{filename}' (type: {backup_type}) not found on Azure share '{share_name}'. Path attempted: '{remote_file_path}' (and legacy if applicable).")
        return None
    except HttpResponseError as hre:
        logger.error(f"HttpResponseError downloading backup '{filename}': {hre.message}", exc_info=True)
        return None
    except ServiceRequestError as sre:
        logger.error(f"ServiceRequestError (network issue?) downloading backup '{filename}': {sre.message}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error downloading unified backup '{filename}': {e}", exc_info=True)
        return None

# --- Placeholder Functions for api_system.py Imports ---

def verify_backup_set(backup_timestamp, socketio_instance=None, task_id=None):
    logger.warning(f"Placeholder function 'verify_backup_set' called for {backup_timestamp}. Not implemented.")
    _emit_progress(socketio_instance, task_id, 'verify_backup_progress', "Verification not implemented.", detail='NOT_IMPLEMENTED', level='WARNING')
    return {'status': 'not_implemented', 'message': 'Verification feature is not implemented.', 'checks': [], 'errors': ['Not implemented']}

def delete_backup_set(backup_timestamp, socketio_instance=None, task_id=None):
    logger.warning(f"Placeholder function 'delete_backup_set' called for {backup_timestamp}. Not implemented.")
    _emit_progress(socketio_instance, task_id, 'backup_delete_progress', "Deletion not implemented.", detail='NOT_IMPLEMENTED', level='WARNING')
    return False

def restore_database_component(backup_timestamp, db_share_client, dry_run=False, socketio_instance=None, task_id=None):
    logger.warning(f"Placeholder 'restore_database_component' for {backup_timestamp}, dry_run={dry_run}. Not implemented.")
    _emit_progress(socketio_instance, task_id, 'restore_progress', "DB component restore not implemented.", level='WARNING')
    return False, "DB component restore not implemented.", None, None # success, message, db_path, actions

def download_map_config_component(backup_timestamp, config_share_client, dry_run=False, socketio_instance=None, task_id=None):
    logger.warning(f"Placeholder 'download_map_config_component' for {backup_timestamp}, dry_run={dry_run}. Not implemented.")
    _emit_progress(socketio_instance, task_id, 'restore_progress', "Map config download not implemented.", level='WARNING')
    return False, "Map config download not implemented.", None, None # success, message, local_path, actions

def restore_media_component(backup_timestamp, media_component_name, azure_remote_folder, local_target_folder, media_share_client, dry_run=False, socketio_instance=None, task_id=None):
    logger.warning(f"Placeholder 'restore_media_component' for {backup_timestamp}, component {media_component_name}. Not implemented.")
    _emit_progress(socketio_instance, task_id, 'restore_progress', f"{media_component_name} restore not implemented.", level='WARNING')
    return False, f"{media_component_name} restore not implemented.", None # success, message, actions

def restore_incremental_bookings(app, socketio_instance=None, task_id=None): # app argument added
    logger.warning("Placeholder 'restore_incremental_bookings'. Not implemented.")
    _emit_progress(socketio_instance, task_id, 'restore_progress', "Incremental booking restore not implemented.", level='WARNING')
    return {'status': 'not_implemented', 'message': 'Not implemented'}

def restore_bookings_from_full_db_backup(app, timestamp_str, socketio_instance=None, task_id=None): # app argument added
    logger.warning(f"Placeholder 'restore_bookings_from_full_db_backup' for {timestamp_str}. Not implemented.")
    _emit_progress(socketio_instance, task_id, 'restore_progress', "Booking restore from full DB not implemented.", level='WARNING')
    return {'status': 'not_implemented', 'message': 'Not implemented'}

def backup_incremental_bookings(app, socketio_instance=None, task_id=None): # app argument added
    logger.warning("Placeholder 'backup_incremental_bookings'. Not implemented.")
    _emit_progress(socketio_instance, task_id, 'incremental_booking_backup_progress', "Incremental booking backup not implemented.", level='WARNING')
    return False

def backup_full_bookings_json(app, socketio_instance=None, task_id=None): # app argument added
    logger.warning("Placeholder 'backup_full_bookings_json'. Not implemented.")
    _emit_progress(socketio_instance, task_id, 'full_booking_export_progress', "Full booking JSON export not implemented.", level='WARNING')
    return False

def list_available_full_booking_json_exports():
    logger.warning("Placeholder 'list_available_full_booking_json_exports'. Not implemented.")
    return []

def restore_bookings_from_full_json_export(app, filename, socketio_instance=None, task_id=None): # app argument added
    logger.warning(f"Placeholder 'restore_bookings_from_full_json_export' for {filename}. Not implemented.")
    _emit_progress(socketio_instance, task_id, 'restore_progress', "Booking restore from JSON export not implemented.", level='WARNING')
    return {'status': 'not_implemented', 'message': 'Not implemented'}

def delete_incremental_booking_backup(filename, backup_type=None, socketio_instance=None, task_id=None): # Added backup_type to match expected signature from api_system
    logger.warning(f"Placeholder 'delete_incremental_booking_backup' for {filename}. Not implemented.")
    _emit_progress(socketio_instance, task_id, 'delete_incremental_booking_backup_progress', "Delete incremental booking backup not implemented.", level='WARNING')
    return False
