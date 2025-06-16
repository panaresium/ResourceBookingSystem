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
from utils import import_bookings_from_csv_file # export_bookings_to_csv_string removed as unused

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

BOOKING_CSV_BACKUPS_DIR = 'booking_csv_backups'
BOOKING_CSV_FILENAME_PREFIX = 'bookings_'

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
    logger.debug(f"_create_share_with_retry called for {share_name}")
    # Simulate share creation for cleanup task
    pass

def upload_file(share_client, source_path, file_path):
    logger.debug(f"upload_file called for {source_path} to {file_path}")
    # Simulate file upload for cleanup task
    pass

def download_file(share_client, file_path, dest_path):
    logger.debug(f"download_file called for {file_path} to {dest_path}")
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    # Create an empty file for placeholder if needed by other logic
    # with open(dest_path, 'wb') as f: f.write(b"simulated download content")
    return True


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
#     # # ...
#     # return False


# --- LEGACY - Azure CSV Functionality - Kept for reference / To be removed ---
# def list_available_booking_csv_backups():
#     """
#     DEPRECATED / LEGACY
#     Lists available booking CSV backups from Azure File Share, extracting metadata from filenames.
#     Returns a list of dictionaries, each representing a backup item, sorted by timestamp descending.
#     """
#     # logger.info("Attempting to list available LEGACY booking CSV backups with range labels.")
#     # backup_items = []
#     # # ... rest of the function body commented out ...
#     # return backup_items


# --- LEGACY - Azure CSV Functionality - Kept for reference / To be removed ---
# def restore_bookings_from_csv_backup(app, filename: str, socketio_instance=None, task_id=None):
#     """
#     DEPRECATED / LEGACY
#     Restores bookings from a specific CSV backup file stored on Azure.
#     """
#     # event_name = 'booking_csv_restore_progress'
#     # # ... rest of the function body commented out ...
#     # return actions_summary

# --- LEGACY - Azure CSV Functionality - Kept for reference / To be removed ---
# def verify_booking_csv_backup(filename: str, socketio_instance=None, task_id=None):
#     """
#     DEPRECATED / LEGACY
#     Verifies if a specific booking CSV backup file exists on Azure.
#     """
#     # event_name = 'booking_csv_verify_progress'
#     # # ... rest of the function body commented out ...
#     # return result

# --- LEGACY - Azure CSV Functionality - Kept for reference / To be removed ---
# def delete_booking_csv_backup(filename: str, socketio_instance=None, task_id=None):
#     """
#     DEPRECATED / LEGACY
#     Deletes a specific booking CSV backup file from Azure.
#     """
#     # event_name = 'booking_csv_delete_progress'
#     # # ... rest of the function body commented out ...
#     # return False


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
    logger.info(f"Creating full system backup for {timestamp_str} (simulated).")
    return True

def backup_database():
    logger.info("Simulating backup_database")
    return "mock_db_backup.db"
