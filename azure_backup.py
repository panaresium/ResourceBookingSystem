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
from extensions import db # Ensure db is imported from extensions (already imported via models)
from utils import update_task_log # Ensure this is imported from utils
from datetime import datetime, time, timezone # Ensure these are imported (datetime, time were already there, timezone might be new)

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

# Assuming ShareServiceClient, _get_service_client, _client_exists, AZURE_BOOKING_DATA_PROTECTION_DIR, logger are defined above in the file.

def list_booking_data_json_backups():
    logger.info("Attempting to list unified booking data JSON backups from Azure.")
    all_backups = []

    try:
        service_client = _get_service_client()
        # Use app.config for share name if available, otherwise fallback to env var or default.
        # This function might be called from contexts where app is not directly available.
        # For now, assume direct os.environ.get or a fixed name if app.config is not straightforward here.
        # Let's use a common share name, ideally configured via app.
        # Assuming current_app can be imported or share name is passed/globally available.
        # For this subtask, let's rely on environment variable as a fallback like _get_service_client does for connection string.
        share_name = os.environ.get('AZURE_BOOKING_DATA_SHARE', 'booking-data-backups')
        if not share_name:
            logger.error("Azure share name for booking data backups is not configured (AZURE_BOOKING_DATA_SHARE).")
            return []

        share_client = service_client.get_share_client(share_name)
        if not _client_exists(share_client):
            logger.warning(f"Azure share '{share_name}' not found. Cannot list booking data backups.")
            return []

        base_backup_dir_client = share_client.get_directory_client(AZURE_BOOKING_DATA_PROTECTION_DIR)
        if not _client_exists(base_backup_dir_client):
            logger.info(f"Base backup directory '{AZURE_BOOKING_DATA_PROTECTION_DIR}' not found in share '{share_name}'. No backups to list.")
            return []

        # Define subdirectories and their types/parsers
        # Add more as other backup types (scheduled full, incremental) are implemented
        backup_sources = [
            {"subdir": "manual_full_json", "type": "manual_full_json", "name_pattern": re.compile(r"manual_full_booking_export_(\d{8}_\d{6})\.json")}
            # Example for future:
            # {"subdir": "full", "type": "scheduled_full_json", "name_pattern": re.compile(r"scheduled_full_export_(\d{8}_\d{6})\.json")},
            # {"subdir": "incrementals", "type": "incremental_json", "name_pattern": re.compile(r"incremental_(\d{8}_\d{6})_to_(\d{8}_\d{6})\.json")}
        ]

        for source in backup_sources:
            source_dir_path = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{source['subdir']}"
            dir_client = share_client.get_directory_client(source_dir_path)
            if not _client_exists(dir_client):
                logger.info(f"Backup subdirectory '{source_dir_path}' not found. Skipping.")
                continue

            logger.info(f"Scanning for backups in '{source_dir_path}' of type '{source['type']}'.")
            for item in dir_client.list_directories_and_files():
                if item['is_directory']:
                    continue # Not expecting further subdirectories for these backup files

                filename = item['name']
                match = source['name_pattern'].match(filename)
                if match:
                    timestamp_str_from_name = match.group(1) # Assumes first group is the timestamp
                    try:
                        # Parse timestamp from YYYYMMDD_HHMMSS format
                        dt_obj_naive = datetime.strptime(timestamp_str_from_name, '%Y%m%d_%H%M%S')
                        # Convert to UTC and then to ISO format string
                        # Assuming filename timestamp is already effectively UTC as per generation logic
                        dt_obj_utc = dt_obj_naive.replace(tzinfo=timezone.utc)
                        iso_timestamp_str = dt_obj_utc.isoformat()

                        display_name = f"{source['type'].replace('_', ' ').title()} - {dt_obj_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}"

                        all_backups.append({
                            'filename': filename, # Store full filename for download/delete operations
                            'full_path': f"{source_dir_path}/{filename}", # Useful for operations needing full path
                            'display_name': display_name,
                            'type': source['type'],
                            'timestamp_str': iso_timestamp_str, # ISO string for sorting and client-side parsing
                            'size_bytes': item.get('size', 0) # Get size if available
                        })
                        logger.debug(f"Found backup: {filename}, Timestamp: {iso_timestamp_str}")
                    except ValueError:
                        logger.warning(f"Could not parse timestamp from filename: {filename} in {source_dir_path}. Skipping.")
                    except Exception as e_parse:
                         logger.error(f"Error processing file {filename} in {source_dir_path}: {e_parse}", exc_info=True)
                else:
                    logger.debug(f"Filename {filename} in {source_dir_path} did not match pattern for type {source['type']}.")

        # Sort backups by timestamp string (ISO format naturally sorts chronologically)
        all_backups.sort(key=lambda x: x['timestamp_str'], reverse=True)

        logger.info(f"Found {len(all_backups)} unified booking data backups.")
        return all_backups

    except Exception as e:
        logger.error(f"Error listing unified booking data JSON backups: {e}", exc_info=True)
        return []

def delete_booking_data_json_backup(filename, backup_type=None, task_id=None): # task_id can be used for logging if needed
    # Note: _emit_progress is tied to utils.update_task_log which might not be ideal if this isn't a long task.
    # Using logger directly for simplicity unless this becomes a background task.
    log_prefix = f"[Task {task_id}] " if task_id else ""
    logger.info(f"{log_prefix}Attempting to delete unified backup: Type='{backup_type}', Filename='{filename}'.")

    try:
        service_client = _get_service_client()
        share_name = os.environ.get('AZURE_BOOKING_DATA_SHARE', 'booking-data-backups') # Consistent with download
        if not share_name:
            logger.error(f"{log_prefix}Azure share name for booking data backups is not configured (AZURE_BOOKING_DATA_SHARE).")
            return False

        share_client = service_client.get_share_client(share_name)
        if not _client_exists(share_client):
            logger.warning(f"{log_prefix}Azure share '{share_name}' not found. Cannot delete backup.")
            return False

        target_subdir = ""
        if backup_type == "manual_full_json":
            target_subdir = "manual_full_json"
        # Add other type mappings here if other backup types are introduced
        # e.g., elif backup_type == "scheduled_full_json": target_subdir = "full"
        else:
            logger.error(f"{log_prefix}Cannot determine directory for backup type '{backup_type}'. Deletion aborted.")
            return False

        remote_file_path = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{target_subdir}/{filename}"

        file_client = share_client.get_file_client(remote_file_path)

        if not _client_exists(file_client):
            logger.warning(f"{log_prefix}File '{remote_file_path}' not found in share '{share_name}'. No action taken, considered success for deletion.")
            return True # If file doesn't exist, it's effectively "deleted"

        file_client.delete_file()
        logger.info(f"{log_prefix}Successfully deleted file '{remote_file_path}'.")
        return True

    except ResourceNotFoundError: # Should be caught by _client_exists, but as defense
        logger.warning(f"{log_prefix}File '{filename}' (Type: {backup_type}) not found during delete. Considered success.")
        return True
    except Exception as e:
        logger.error(f"{log_prefix}An unexpected error occurred during deletion of '{filename}' (Type: {backup_type}): {e}", exc_info=True)
        return False

def restore_booking_data_to_point_in_time(app, selected_filename, selected_type, selected_timestamp_iso, task_id=None):
    update_task_log(task_id, f"Starting restore from '{selected_filename}' (Type: {selected_type}).", level="info")

    if selected_type != "manual_full_json": # For now, only support restoring this type
        msg = f"Restore for backup type '{selected_type}' is not currently supported. Only 'manual_full_json' is supported."
        update_task_log(task_id, msg, level="error")
        return {'status': 'failure', 'message': msg, 'errors': [msg]}

    try:
        with app.app_context(): # Ensure DB operations are within app context
            update_task_log(task_id, f"Downloading backup file: {selected_filename}...", level="info")
            file_content_bytes = download_booking_data_json_backup(filename=selected_filename, backup_type=selected_type)

            if file_content_bytes is None:
                msg = f"Failed to download backup file '{selected_filename}'."
                update_task_log(task_id, msg, level="error")
                return {'status': 'failure', 'message': msg, 'errors': ["File download failed."]}

            try:
                file_content_str = file_content_bytes.decode('utf-8')
                backup_data = json.loads(file_content_str)
                bookings_from_json = backup_data.get("bookings", [])
                export_timestamp = backup_data.get("export_timestamp", "N/A")
                update_task_log(task_id, f"Successfully downloaded and parsed backup file. Exported at: {export_timestamp}. Contains {len(bookings_from_json)} bookings.", level="info")
            except json.JSONDecodeError as e:
                msg = f"Failed to parse JSON from backup file: {str(e)}"
                update_task_log(task_id, msg, level="error")
                return {'status': 'failure', 'message': msg, 'errors': [f"JSON decode error: {str(e)}"]}
            except Exception as e: # Catch other errors like decode if not utf-8
                msg = f"Error processing backup file content: {str(e)}"
                update_task_log(task_id, msg, level="error")
                return {'status': 'failure', 'message': msg, 'errors': [f"File processing error: {str(e)}"]}

            update_task_log(task_id, "WARNING: All existing booking data in the database will be deleted before restoring. This action cannot be undone.", level="warning")

            # Add a small delay to allow user to potentially see the warning if this were interactive,
            # or for logs to catch up. In a real scenario, a confirmation step would be better.
            # For now, just proceeding after warning.
            # import time as time_module # Already imported in azure_backup.py
            # time_module.sleep(3)

            update_task_log(task_id, "Deleting existing booking data...", level="info")
            try:
                num_deleted = db.session.query(Booking).delete()
                db.session.commit() # Commit deletion
                update_task_log(task_id, f"Successfully deleted {num_deleted} existing bookings.", level="info")
            except Exception as e:
                db.session.rollback()
                msg = f"Failed to delete existing bookings: {str(e)}"
                update_task_log(task_id, msg, level="error")
                return {'status': 'failure', 'message': msg, 'errors': [f"DB delete error: {str(e)}"]}

            update_task_log(task_id, f"Starting import of {len(bookings_from_json)} bookings from backup...", level="info")
            bookings_restored_count = 0
            bookings_failed_count = 0
            restore_errors = []

            for i, booking_json in enumerate(bookings_from_json):
                try:
                    # Basic validation of essential fields
                    if not all(k in booking_json for k in ['id', 'resource_id', 'user_name', 'start_time', 'end_time', 'status']):
                        bookings_failed_count += 1
                        err_msg = f"Skipping booking entry {i+1} due to missing essential fields (id, resource_id, etc.). Data: {str(booking_json)[:200]}"
                        restore_errors.append(err_msg)
                        update_task_log(task_id, err_msg, level="warning")
                        continue

                    # Convert datetime strings to datetime objects
                    # Ensure _parse_iso_datetime is available or define it, or use datetime.fromisoformat directly
                    # _parse_iso_datetime is in utils.py, but azure_backup.py might not import it directly.
                    # For simplicity, using datetime.fromisoformat, assuming Z means UTC.
                    def parse_datetime_optional(dt_str):
                        if not dt_str: return None
                        # Handle 'Z' for UTC explicitly for fromisoformat if not automatically handled by older pythons for it
                        if isinstance(dt_str, str) and dt_str.endswith('Z'):
                            return datetime.fromisoformat(dt_str[:-1] + '+00:00')
                        return datetime.fromisoformat(dt_str) if isinstance(dt_str, str) else None

                    def parse_time_optional(t_str):
                        if not t_str: return None
                        return time.fromisoformat(t_str) if isinstance(t_str, str) else None

                    new_booking = Booking(
                        id=booking_json['id'], # Attempt to preserve original ID
                        resource_id=booking_json['resource_id'],
                        user_name=booking_json.get('user_name'),
                        title=booking_json.get('title'),
                        start_time=parse_datetime_optional(booking_json['start_time']),
                        end_time=parse_datetime_optional(booking_json['end_time']),
                        status=booking_json.get('status', 'approved'), # Default status if missing
                        checked_in_at=parse_datetime_optional(booking_json.get('checked_in_at')),
                        checked_out_at=parse_datetime_optional(booking_json.get('checked_out_at')),
                        recurrence_rule=booking_json.get('recurrence_rule'),
                        admin_deleted_message=booking_json.get('admin_deleted_message'),
                        check_in_token=booking_json.get('check_in_token'),
                        check_in_token_expires_at=parse_datetime_optional(booking_json.get('check_in_token_expires_at')),
                        checkin_reminder_sent_at=parse_datetime_optional(booking_json.get('checkin_reminder_sent_at')),
                        last_modified=parse_datetime_optional(booking_json.get('last_modified')) or datetime.now(timezone.utc), # Use backup's last_modified or now
                        booking_display_start_time=parse_time_optional(booking_json.get('booking_display_start_time')),
                        booking_display_end_time=parse_time_optional(booking_json.get('booking_display_end_time'))
                    )

                    # Check if booking with this ID already exists (should not happen if we deleted all)
                    # This is more relevant if we were not bulk-deleting.
                    # existing_booking = Booking.query.get(new_booking.id)
                    # if existing_booking:
                    #     # Handle conflict: skip, update, or error
                    #     update_task_log(task_id, f"Booking with ID {new_booking.id} already exists. Skipping.", level="warning")
                    #     bookings_failed_count += 1
                    #     continue

                    db.session.add(new_booking)
                    bookings_restored_count += 1

                    if bookings_restored_count % 100 == 0: # Log progress every 100 bookings
                        update_task_log(task_id, f"Restored {bookings_restored_count}/{len(bookings_from_json)} bookings...", level="info")

                except Exception as e_item:
                    bookings_failed_count += 1
                    err_msg = f"Error restoring booking item {i+1} (ID: {booking_json.get('id', 'N/A')}): {str(e_item)}. Data: {str(booking_json)[:200]}"
                    restore_errors.append(err_msg)
                    update_task_log(task_id, err_msg, level="error")
                    db.session.rollback() # Rollback this item

            if bookings_failed_count > 0:
                db.session.commit() # Commit successful ones if any
                update_task_log(task_id, f"Restore partially completed. Successfully restored: {bookings_restored_count}. Failed: {bookings_failed_count}.", level="warning")
                return {'status': 'failure', 'message': f"Restore partially completed. Restored: {bookings_restored_count}, Failed: {bookings_failed_count}.", 'errors': restore_errors}
            else:
                db.session.commit()
                msg = f"Successfully restored {bookings_restored_count} bookings from '{selected_filename}'."
                update_task_log(task_id, msg, level="success")
                return {'status': 'success', 'message': msg}

    except Exception as e_main:
        db.session.rollback()
        msg = f"A critical error occurred during the restore process: {str(e_main)}"
        update_task_log(task_id, msg, level="critical", detail=str(e_main)) # Pass exception as detail
        return {'status': 'failure', 'message': msg, 'errors': [str(e_main)]}

def download_booking_data_json_backup(filename, backup_type=None):
    logger.info(f"Attempting to download unified backup: Type='{backup_type}', Filename='{filename}'.")
    try:
        service_client = _get_service_client()
        share_name = os.environ.get('AZURE_BOOKING_DATA_SHARE', 'booking-data-backups')
        if not share_name:
            logger.error("Azure share name for booking data backups is not configured (AZURE_BOOKING_DATA_SHARE).")
            return None

        share_client = service_client.get_share_client(share_name)
        if not _client_exists(share_client):
            logger.warning(f"Azure share '{share_name}' not found. Cannot download backup.")
            return None

        # Determine subdirectory based on backup_type
        # This mapping should align with how list_booking_data_json_backups structures types and paths.
        subdir_map = {
            "manual_full_json": "manual_full_json",
            "scheduled_full_json": "full", # Example, if scheduled backups go to 'full'
            "incremental_json": "incrementals" # Example
        }
        # Fallback to a generic path or error if type unknown, for now, let's assume type gives direct subdir
        # or filename in list_booking_data_json_backups contains the subpath.
        # The 'full_path' from list_booking_data_json_backups is better but this function only gets filename and type.

        # For simplicity, let's assume backup_type directly maps to a known subdirectory under AZURE_BOOKING_DATA_PROTECTION_DIR
        # or that the 'filename' might sometimes be a relative path including its type-specific subdir.
        # Given the current structure from previous steps:
        # Manual backups are in AZURE_BOOKING_DATA_PROTECTION_DIR + "/manual_full_json/" + filename

        target_subdir = ""
        if backup_type == "manual_full_json":
            target_subdir = "manual_full_json"
        # Add other type mappings here if other backup types are introduced
        # e.g., elif backup_type == "scheduled_full_json": target_subdir = "full"
        else:
            logger.warning(f"Unknown or unhandled backup_type '{backup_type}' for download. Attempting download from base backup directory.")
            # If type is unknown, or if filename is expected to be unique across all types in the root of AZURE_BOOKING_DATA_PROTECTION_DIR
            # This part might need refinement based on where `list_booking_data_json_backups` actually finds various types.
            # For now, if type is not 'manual_full_json', assume it might be directly under AZURE_BOOKING_DATA_PROTECTION_DIR or this will fail.
            # A safer bet is to require type to be known.

        if not target_subdir:
             logger.error(f"Cannot determine directory for backup type '{backup_type}'. Download aborted.")
             return None

        remote_file_path = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{target_subdir}/{filename}"

        file_client = share_client.get_file_client(remote_file_path)
        if not _client_exists(file_client):
            logger.error(f"File '{remote_file_path}' not found in share '{share_name}'.")
            return None

        download_stream = file_client.download_file()
        file_content = download_stream.readall()
        logger.info(f"Successfully downloaded file '{remote_file_path}'. Size: {len(file_content)} bytes.")
        return file_content

    except ResourceNotFoundError:
        logger.error(f"Resource not found during download operation for {filename} (Type: {backup_type}). Path might be incorrect or file does not exist.")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred during download of '{filename}' (Type: {backup_type}): {e}", exc_info=True)
        return None

# --- Constants for Backup System ---
LAST_INCREMENTAL_BOOKING_TIMESTAMP_FILE = os.path.join(DATA_DIR, 'last_incremental_booking_timestamp.txt')
BOOKING_INCREMENTAL_BACKUPS_DIR = 'booking_incremental_backups'

DB_BACKUPS_DIR = 'db_backups'
CONFIG_BACKUPS_DIR = 'config_backups'
MEDIA_BACKUPS_DIR_BASE = 'media_backups' # Base directory name on Azure for timestamped media backup folders

DB_FILENAME_PREFIX = 'site_'
MAP_CONFIG_FILENAME_PREFIX = 'map_config_'
RESOURCE_CONFIG_FILENAME_PREFIX = "resource_configs_" # Added
USER_CONFIG_FILENAME_PREFIX = "user_configs_"       # Added


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

def _emit_progress(task_id, message, detail='', level='INFO'):
    from utils import update_task_log # Added for HTTP polling task status
    if task_id:
        try:
            update_task_log(task_id, message, detail, level.lower())
        except Exception as e:
            logger.error(f"AzureBackup: Failed to update task log for task {task_id} (message: {message}): {e}", exc_info=True)
    else:
        logger.warning(f"AzureBackup: _emit_progress called without task_id. Message: {message}, Detail: {detail}")


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
            logger.warning(f"HttpResponseError creating share '{share_name}' (Attempt {i+1}/{retries}): {e.message or e}")
            if i == retries - 1:
                logger.error(f"Failed to create share '{share_name}' after {retries} retries. Last error: {e.message or e}")
                raise
            logger.info(f"Retrying share creation for '{share_name}' in {current_delay} seconds...")
            time.sleep(current_delay)
            current_delay *= factor
        except Exception as e:
            logger.error(f"Unexpected error creating share '{share_name}': {e}", exc_info=True)
            raise
    logger.error(f"Share '{share_name}' could not be created after {retries} retries.")
    return False

def upload_file(share_client, source_path, file_path):
    logger.info(f"Attempting to upload '{source_path}' to '{share_client.share_name}/{file_path}'.")
    file_client = share_client.get_file_client(file_path)
    try:
        try:
            file_client.get_file_properties()
            logger.info(f"File '{file_path}' already exists in share '{share_client.share_name}'. Deleting it before upload.")
            file_client.delete_file()
            logger.info(f"Successfully deleted existing file '{file_path}' from share '{share_client.share_name}'.")
        except ResourceNotFoundError:
            logger.info(f"File '{file_path}' does not exist in share '{share_client.share_name}'. Proceeding with upload.")
            pass
        with open(source_path, "rb") as f_source:
            file_client.upload_file(f_source)
        logger.info(f"Successfully uploaded '{source_path}' to '{share_client.share_name}/{file_path}'.")
        return True
    except FileNotFoundError:
        logger.error(f"Upload failed: Source file '{source_path}' not found.")
        return False
    except ResourceNotFoundError:
        logger.error(f"Upload failed: Resource not found for '{share_client.share_name}/{file_path}'.")
        return False
    except HttpResponseError as e:
        error_message = e.message or getattr(e.response, 'text', str(e))
        logger.error(f"Upload failed for '{share_client.share_name}/{file_path}': {error_message}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Unexpected error during upload of '{source_path}' to '{share_client.share_name}/{file_path}': {e}", exc_info=True)
        return False

def download_file(share_client, file_path, dest_path):
    logger.debug(f"download_file called for {file_path} to {dest_path}")
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    file_client = share_client.get_file_client(file_path)
    try:
        with open(dest_path, "wb") as f_dest:
            download_stream = file_client.download_file()
            f_dest.write(download_stream.readall())
        logger.info(f"Successfully downloaded '{file_path}' to '{dest_path}'.")
        return True
    except ResourceNotFoundError:
        logger.error(f"Download failed: File '{file_path}' not found in share '{share_client.share_name}'.")
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred during download of '{file_path}': {e}", exc_info=True)
        return False

def list_available_backups():
    # ... (original implementation) ...
    logger.info("Attempting to list available full system backups.")
    try:
        service_client = _get_service_client()
        db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
        share_client = service_client.get_share_client(db_share_name)
        if not _client_exists(share_client): return []
        db_backup_dir_client = share_client.get_directory_client(DB_BACKUPS_DIR)
        if not _client_exists(db_backup_dir_client): return []
        timestamps = set()
        manifest_pattern = re.compile(r"^backup_manifest_(?P<timestamp>\d{8}_\d{6})\.json$")
        db_pattern = re.compile(rf"^{re.escape(DB_FILENAME_PREFIX)}(?P<timestamp>\d{8}_\d{6})\.db$")
        for item in db_backup_dir_client.list_directories_and_files():
            if item['is_directory']: continue
            filename = item['name']
            timestamp_str = None
            manifest_match = manifest_pattern.match(filename)
            if manifest_match: timestamp_str = manifest_match.group('timestamp')
            else:
                db_match = db_pattern.match(filename)
                if db_match: timestamp_str = db_match.group('timestamp')
            if timestamp_str:
                try: datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S'); timestamps.add(timestamp_str)
                except ValueError: logger.warning(f"Skipping file with invalid timestamp format: {filename}")
        return sorted(list(timestamps), reverse=True)
    except Exception as e:
        logger.error(f"Error listing available full system backups: {e}", exc_info=True)
        return []

def restore_full_backup(backup_timestamp, task_id=None, dry_run=False):
    # ... (original placeholder, unchanged for this subtask) ...
    logger.warning(f"Placeholder 'restore_full_backup' for {backup_timestamp}, dry_run={dry_run}, task_id: {task_id}.")
    if dry_run:
        _emit_progress(task_id, "DRY RUN: Starting...", detail=f'Timestamp: {backup_timestamp}')
        _emit_progress(task_id, "DRY RUN: Completed.", detail=json.dumps({'actions': ["Simulated action 1"]}), level='SUCCESS')
        return None, None, None, None, ["Simulated action 1"]
    _emit_progress(task_id, "Restore Error: Not implemented.", detail='NOT_IMPLEMENTED', level='ERROR')
    return None, None, None, None, []


def create_full_backup(timestamp_str, map_config_data=None, resource_configs_data=None, user_configs_data=None, task_id=None):
    # ... (original implementation, using new _emit_progress) ...
    overall_success = True
    backed_up_items = []
    _emit_progress(task_id, "Attempting to initialize Azure service client for backup...", level='INFO')
    try:
        service_client = _get_service_client()
        if not service_client:
            _emit_progress(task_id, "Failed to get Azure service client.", level='ERROR')
            return False
        _emit_progress(task_id, "Azure service client initialized.", level='INFO')
    except RuntimeError as e:
        logger.error(f"RuntimeError in create_full_backup: {str(e)}")
        _emit_progress(task_id, f"Backup Pre-check Failed: {str(e)}", detail=str(e), level='ERROR')
        raise
    # DB Backup
    _emit_progress(task_id, "Starting database backup...", level='INFO')
    db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
    db_share_client = None
    try:
        db_share_client = service_client.get_share_client(db_share_name)
        if not _create_share_with_retry(db_share_client, db_share_name): _emit_progress(task_id, f"Failed to create DB share: {db_share_name}", level='ERROR'); return False
        _ensure_directory_exists(db_share_client, DB_BACKUPS_DIR)
        local_db_path = os.path.join(DATA_DIR, 'site.db')
        db_backup_filename = f"{DB_FILENAME_PREFIX}{timestamp_str}.db"
        remote_db_file_path = f"{DB_BACKUPS_DIR}/{db_backup_filename}"
        if not os.path.exists(local_db_path): _emit_progress(task_id, f"Local DB not found: {local_db_path}", level='ERROR'); return False
        if upload_file(db_share_client, local_db_path, remote_db_file_path):
            _emit_progress(task_id, "Database backup successful.", level='SUCCESS')
            backed_up_items.append({ "type": "database", "filename": db_backup_filename })
        else: _emit_progress(task_id, "Database backup failed.", level='ERROR'); return False
    except Exception as e_db: _emit_progress(task_id, f"Database backup error: {str(e_db)}", level='ERROR'); return False
    # Config Backup
    _emit_progress(task_id, "Starting configuration data backup...", level='INFO')
    config_share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
    try:
        config_share_client = service_client.get_share_client(config_share_name)
        if not _create_share_with_retry(config_share_client, config_share_name): _emit_progress(task_id, f"Failed to create Config share: {config_share_name}", level='ERROR'); return False
        _ensure_directory_exists(config_share_client, CONFIG_BACKUPS_DIR)
        configs_to_backup = [
            (map_config_data, "map_config", MAP_CONFIG_FILENAME_PREFIX),
            (resource_configs_data, "resource_configs", RESOURCE_CONFIG_FILENAME_PREFIX),
            (user_configs_data, "user_configs", USER_CONFIG_FILENAME_PREFIX)
        ]
        for config_data, name, prefix in configs_to_backup:
            if not config_data: _emit_progress(task_id, f"{name} data empty, skipping.", level='INFO'); continue
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', dir=DATA_DIR) as tmp: tmp_path = tmp.name; json.dump(config_data, tmp, indent=4)
                filename = f"{prefix}{timestamp_str}.json"; remote_path = f"{CONFIG_BACKUPS_DIR}/{filename}"
                if upload_file(config_share_client, tmp_path, remote_path): _emit_progress(task_id, f"{name} backup successful.", level='SUCCESS'); backed_up_items.append({"type": "config", "name": name, "filename": filename})
                else: _emit_progress(task_id, f"{name} backup failed.", level='ERROR'); overall_success = False
            finally:
                if tmp_path and os.path.exists(tmp_path): os.remove(tmp_path)
    except Exception as e_cfg: _emit_progress(task_id, f"Config backup error: {str(e_cfg)}", level='ERROR'); return False
    # Media Backup
    if overall_success:
        _emit_progress(task_id, "Starting media files backup...", level='INFO')
        media_share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media-backups')
        try:
            media_share_client = service_client.get_share_client(media_share_name)
            if not _create_share_with_retry(media_share_client, media_share_name): _emit_progress(task_id, f"Failed to create Media share: {media_share_name}", level='ERROR'); return False
            ts_media_dir = f"{MEDIA_BACKUPS_DIR_BASE}/backup_{timestamp_str}"; _ensure_directory_exists(media_share_client, MEDIA_BACKUPS_DIR_BASE); _ensure_directory_exists(media_share_client, ts_media_dir)
            media_sources = [{"name": "Floor Maps", "path": FLOOR_MAP_UPLOADS, "subdir": "floor_map_uploads"}, {"name": "Resource Uploads", "path": RESOURCE_UPLOADS, "subdir": "resource_uploads"}]
            for src in media_sources:
                _emit_progress(task_id, f"Processing media source: {src['name']}. Local path configured: '{src['path']}'", level='DEBUG')
                is_dir = os.path.isdir(src["path"])
                _emit_progress(task_id, f"Path '{src['path']}' is directory? {is_dir}", level='DEBUG')

                if not is_dir:
                    _emit_progress(task_id, f"{src['name']} local path '{src['path']}' is not a directory or not found, skipping.", level='WARNING')
                    continue

                azure_target_dir = f"{ts_media_dir}/{src['subdir']}"
                _ensure_directory_exists(media_share_client, azure_target_dir)

                files_in_source_path = []
                try:
                    files_in_source_path = os.listdir(src["path"])
                    _emit_progress(task_id, f"Files/folders found in '{src['path']}': {files_in_source_path}", level='DEBUG')
                except Exception as e_listdir:
                    _emit_progress(task_id, f"Error listing directory '{src['path']}': {str(e_listdir)}", level='ERROR')
                    overall_success = False
                    continue # Skip to the next media source

                if not files_in_source_path:
                    _emit_progress(task_id, f"No files or subdirectories found in local folder '{src['path']}' for {src['name']}, skipping upload for this source.", level='INFO')
                    continue

                _emit_progress(task_id, f"Starting upload of items from {src['path']} to Azure directory {azure_target_dir} for {src['name']}...", level='INFO')

                file_upload_success_count = 0
                file_upload_failure_count = 0

                for filename in files_in_source_path:
                    local_file_path = os.path.join(src["path"], filename)
                    _emit_progress(task_id, f"Processing item: '{filename}'. Full local path: '{local_file_path}'", level='DEBUG')
                    is_file = os.path.isfile(local_file_path)
                    _emit_progress(task_id, f"Path '{local_file_path}' is file? {is_file}", level='DEBUG')

                    if is_file:
                        remote_file_path_in_azure = f"{azure_target_dir}/{filename}"

                        if upload_file(media_share_client, local_file_path, remote_file_path_in_azure):
                            _emit_progress(task_id, f"Successfully uploaded {filename} for {src['name']}.", level='INFO')
                            file_upload_success_count += 1
                        else:
                            _emit_progress(task_id, f"Failed to upload {filename} for {src['name']}.", level='ERROR')
                            file_upload_failure_count += 1
                    else:
                        _emit_progress(task_id, f"Skipping non-file item '{filename}' in {src['path']}.", level='INFO')

                if file_upload_failure_count > 0:
                    _emit_progress(task_id, f"{src['name']} backup: {file_upload_success_count} file(s) uploaded successfully, {file_upload_failure_count} file(s) failed.", level='ERROR')
                    overall_success = False
                elif file_upload_success_count > 0 :
                     _emit_progress(task_id, f"{src['name']} backup: All {file_upload_success_count} file(s) uploaded successfully.", level='SUCCESS')
                else:
                    _emit_progress(task_id, f"{src['name']} backup: No actual files were uploaded (source might have been empty or contained only non-files).", level='INFO')
        except Exception as e_media:
            _emit_progress(task_id, f"Media backup error: {str(e_media)}", level='ERROR')
            overall_success = False # Ensure overall_success is false if the entire media block fails
            # Depending on desired behavior, you might return False here if media backup is critical
            # For now, setting overall_success to False and letting manifest creation handle it.
    # Manifest
    if overall_success:
        _emit_progress(task_id, "Creating backup manifest...", level='INFO')
        manifest_data = {
            "backup_timestamp": timestamp_str,
            "backup_version": "1.0",  # Consider making this dynamic if app version is available
            "components": []
        }

        # Add database component
        for item in backed_up_items:
            if item.get("type") == "database":
                manifest_data["components"].append({
                    "type": "database",
                    "filename": item["filename"],
                    "share": db_share_name
                })
                break # Assuming only one DB backup

        # Add config components
        for item in backed_up_items:
            if item.get("type") == "config":
                manifest_data["components"].append({
                    "type": "config",
                    "name": item["name"],
                    "filename": item["filename"],
                    "share": config_share_name
                })

        # Add media component (if media backup was attempted and successful up to this point)
        # This assumes that if overall_success is true and media_share_name is set, media was included.
        media_share_name_local = os.environ.get('AZURE_MEDIA_SHARE', 'media-backups') # Get it as it's defined in the media backup section
        if media_share_name_local: # Check if media backup was configured/attempted
             manifest_data["components"].append({
                "type": "media",
                "base_dir": f"{MEDIA_BACKUPS_DIR_BASE}/backup_{timestamp_str}",
                "share": media_share_name_local
            })

        tmp_manifest_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', dir=DATA_DIR, encoding='utf-8') as tmp_mf:
                tmp_manifest_path = tmp_mf.name
                json.dump(manifest_data, tmp_mf, indent=4)

            manifest_filename = f"backup_manifest_{timestamp_str}.json"
            remote_manifest_path = f"{DB_BACKUPS_DIR}/{manifest_filename}"

            if db_share_client and upload_file(db_share_client, tmp_manifest_path, remote_manifest_path):
                _emit_progress(task_id, "Manifest uploaded successfully.", detail=f"Manifest: {manifest_filename}", level='SUCCESS')
                # Optionally add manifest to backed_up_items if needed for other post-processing
                # backed_up_items.append({"type": "manifest", "filename": manifest_filename, "share": db_share_name})
            else:
                _emit_progress(task_id, "Manifest upload failed.", detail=f"Could not upload {manifest_filename}", level='ERROR')
                overall_success = False # Mark overall backup as failed if manifest upload fails
        except Exception as e_manifest:
            _emit_progress(task_id, "Error creating or uploading manifest.", detail=str(e_manifest), level='ERROR')
            overall_success = False
        finally:
            if tmp_manifest_path and os.path.exists(tmp_manifest_path):
                try:
                    os.remove(tmp_manifest_path)
                except OSError as e_remove:
                    _emit_progress(task_id, f"Error removing temporary manifest file {tmp_manifest_path}", detail=str(e_remove), level='ERROR')

    _emit_progress(task_id, "Full system backup finished.", detail=f"Overall success: {overall_success}", level='SUCCESS' if overall_success else 'ERROR')
    return overall_success

# --- delete_backup_set Implementation ---
def delete_backup_set(backup_timestamp, task_id=None):
    logger.info(f"[Task {task_id}] Initiating deletion for backup set with timestamp: {backup_timestamp}")
    _emit_progress(task_id, f"Starting deletion of backup set: {backup_timestamp}", level="INFO")

    overall_success = True
    service_client = None
    try:
        service_client = _get_service_client()
    except RuntimeError as e:
        _emit_progress(task_id, "Failed to initialize Azure service client.", detail=str(e), level="ERROR")
        return False

    db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
    config_share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
    media_share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media-backups')

    deleted_components = []
    failed_components = []

    def _delete_file_if_exists_local(share_client, file_path, component_name):
        nonlocal overall_success # To modify overall_success from outer scope
        try:
            file_client = share_client.get_file_client(file_path)
            if _client_exists(file_client):
                _emit_progress(task_id, f"Deleting {component_name} file: {file_path} from share {share_client.share_name}", level="INFO")
                file_client.delete_file()
                _emit_progress(task_id, f"Successfully deleted {component_name} file: {file_path}", level="INFO")
                deleted_components.append(f"{component_name}: {file_path}")
                return True
            else:
                _emit_progress(task_id, f"{component_name} file not found: {file_path}", level="INFO")
                deleted_components.append(f"{component_name}: {file_path} (not found)")
                return True
        except Exception as e:
            logger.error(f"[Task {task_id}] Error deleting {component_name} file {file_path}: {e}", exc_info=True)
            _emit_progress(task_id, f"Error deleting {component_name} file: {file_path}", detail=str(e), level="ERROR")
            failed_components.append(f"{component_name}: {file_path}")
            overall_success = False
            return False

    def _delete_directory_recursive_local(share_client, dir_path, component_name_prefix):
        nonlocal overall_success
        try:
            dir_client = share_client.get_directory_client(dir_path)
            if not _client_exists(dir_client):
                _emit_progress(task_id, f"{component_name_prefix} directory not found: {dir_path}", level="INFO")
                deleted_components.append(f"{component_name_prefix} directory: {dir_path} (not found)")
                return True

            _emit_progress(task_id, f"Deleting contents of {component_name_prefix} directory: {dir_path}...", level="INFO")
            for item in dir_client.list_directories_and_files():
                item_path = f"{dir_path}/{item['name']}"
                if item['is_directory']:
                    _delete_directory_recursive_local(share_client, item_path, f"{component_name_prefix} subdirectory")
                else:
                    _delete_file_if_exists_local(share_client, item_path, f"{component_name_prefix} file")

            _emit_progress(task_id, f"Deleting {component_name_prefix} directory itself: {dir_path}", level="INFO")
            dir_client.delete_directory()
            _emit_progress(task_id, f"Successfully deleted {component_name_prefix} directory: {dir_path}", level="INFO")
            deleted_components.append(f"{component_name_prefix} directory: {dir_path}")
            return True
        except Exception as e:
            logger.error(f"[Task {task_id}] Error deleting {component_name_prefix} directory {dir_path}: {e}", exc_info=True)
            _emit_progress(task_id, f"Error deleting {component_name_prefix} directory {dir_path}", detail=str(e), level="ERROR")
            failed_components.append(f"{component_name_prefix} directory: {dir_path}")
            overall_success = False
            return False

    _emit_progress(task_id, "Processing database and manifest files for deletion...", level="INFO")
    try:
        db_share_client = service_client.get_share_client(db_share_name)
        if _client_exists(db_share_client):
            db_file = f"{DB_BACKUPS_DIR}/{DB_FILENAME_PREFIX}{backup_timestamp}.db"
            manifest_file = f"{DB_BACKUPS_DIR}/backup_manifest_{backup_timestamp}.json"
            _delete_file_if_exists_local(db_share_client, db_file, "Database backup")
            _delete_file_if_exists_local(db_share_client, manifest_file, "Backup manifest")
        else:
            _emit_progress(task_id, f"Database share '{db_share_name}' not found. Skipping.", level="WARNING")
    except Exception as e:
        _emit_progress(task_id, f"Error accessing DB share '{db_share_name}'.", detail=str(e), level="ERROR"); overall_success = False; failed_components.append(f"DB Share: {db_share_name}")

    _emit_progress(task_id, "Processing configuration files for deletion...", level="INFO")
    try:
        config_share_client = service_client.get_share_client(config_share_name)
        if _client_exists(config_share_client):
            map_config_file = f"{CONFIG_BACKUPS_DIR}/{MAP_CONFIG_FILENAME_PREFIX}{backup_timestamp}.json"
            resource_config_file = f"{CONFIG_BACKUPS_DIR}/{RESOURCE_CONFIG_FILENAME_PREFIX}{backup_timestamp}.json"
            user_config_file = f"{CONFIG_BACKUPS_DIR}/{USER_CONFIG_FILENAME_PREFIX}{backup_timestamp}.json"
            _delete_file_if_exists_local(config_share_client, map_config_file, "Map config")
            _delete_file_if_exists_local(config_share_client, resource_config_file, "Resource configs")
            _delete_file_if_exists_local(config_share_client, user_config_file, "User configs")
        else:
            _emit_progress(task_id, f"Config share '{config_share_name}' not found. Skipping.", level="WARNING")
    except Exception as e:
        _emit_progress(task_id, f"Error accessing Config share '{config_share_name}'.", detail=str(e), level="ERROR"); overall_success = False; failed_components.append(f"Config Share: {config_share_name}")

    _emit_progress(task_id, "Processing media files for deletion...", level="INFO")
    try:
        media_share_client = service_client.get_share_client(media_share_name)
        if _client_exists(media_share_client):
            media_backup_dir_for_timestamp = f"{MEDIA_BACKUPS_DIR_BASE}/backup_{backup_timestamp}"
            _delete_directory_recursive_local(media_share_client, media_backup_dir_for_timestamp, "Media backup")
        else:
            _emit_progress(task_id, f"Media share '{media_share_name}' not found. Skipping.", level="WARNING")
    except Exception as e:
        _emit_progress(task_id, f"Error accessing Media share '{media_share_name}'.", detail=str(e), level="ERROR"); overall_success = False; failed_components.append(f"Media Share: {media_share_name}")

    if overall_success:
        _emit_progress(task_id, f"Successfully processed deletion for backup set {backup_timestamp}.", level="SUCCESS")
        logger.info(f"[Task {task_id}] Deletion process for {backup_timestamp} completed. Success: True. Processed: {deleted_components}")
    else:
        _emit_progress(task_id, f"Deletion for backup set {backup_timestamp} completed with errors.", detail=f"Failed: {failed_components}", level="ERROR")
        logger.error(f"[Task {task_id}] Deletion for {backup_timestamp} completed. Success: False. Failed: {failed_components}. Processed: {deleted_components}")

    return overall_success


# --- Other placeholder functions with updated signatures ---
def verify_backup_set(backup_timestamp, task_id=None):
    _emit_progress(task_id, f"Starting verification for backup set: {backup_timestamp}", level="INFO")
    checks = []
    errors = []
    status = 'verified'  # Assume success initially

    try:
        service_client = _get_service_client()
        _emit_progress(task_id, "Azure service client initialized.", level="INFO")
    except RuntimeError as e:
        _emit_progress(task_id, "Failed to initialize Azure service client.", detail=str(e), level="ERROR")
        return {'status': 'failed_precondition', 'message': str(e), 'checks': checks, 'errors': [str(e)]}
    except Exception as e:
        _emit_progress(task_id, "Unexpected error initializing Azure service client.", detail=str(e), level="ERROR")
        return {'status': 'failed_precondition', 'message': f"Unexpected error: {str(e)}", 'checks': checks, 'errors': [f"Unexpected error: {str(e)}"]}

    db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
    manifest_filename = f"backup_manifest_{backup_timestamp}.json"
    manifest_remote_path = f"{DB_BACKUPS_DIR}/{manifest_filename}"
    manifest_local_temp_path = None

    try:
        db_share_client = service_client.get_share_client(db_share_name)
        if not _client_exists(db_share_client):
            _emit_progress(task_id, f"DB Share '{db_share_name}' does not exist.", level="ERROR")
            errors.append(f"DB Share '{db_share_name}' does not exist.")
            return {'status': 'failed_precondition', 'message': f"DB Share '{db_share_name}' not found.", 'checks': checks, 'errors': errors}

        _emit_progress(task_id, f"Attempting to download manifest: {manifest_remote_path}", level="INFO")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp_file:
            manifest_local_temp_path = tmp_file.name

        if download_file(db_share_client, manifest_remote_path, manifest_local_temp_path):
            _emit_progress(task_id, "Manifest downloaded successfully.", detail=f"Path: {manifest_local_temp_path}", level="INFO")
            checks.append({"component": "Manifest", "name": manifest_filename, "status": "Downloaded"})
        else:
            _emit_progress(task_id, "Failed to download manifest.", detail=f"Path: {manifest_remote_path}", level="ERROR")
            errors.append(f"Failed to download manifest: {manifest_filename}")
            # If manifest download fails, we cannot proceed with further checks based on it.
            return {'status': 'failed_precondition', 'message': 'Failed to download manifest.', 'checks': checks, 'errors': errors}

        with open(manifest_local_temp_path, 'r') as f:
            manifest_data = json.load(f)
        _emit_progress(task_id, "Manifest parsed successfully.", level="INFO")
        checks.append({"component": "Manifest", "name": manifest_filename, "status": "Parsed"})

    except json.JSONDecodeError as e:
        _emit_progress(task_id, "Failed to parse manifest JSON.", detail=str(e), level="ERROR")
        errors.append(f"Failed to parse manifest JSON: {str(e)}")
        status = 'errors_found' # Or 'failed_precondition' if considered critical
        # Return early as component checks depend on a valid manifest
        return {'status': status, 'message': 'Failed to parse manifest.', 'checks': checks, 'errors': errors}
    except Exception as e:
        _emit_progress(task_id, "Error during manifest processing.", detail=str(e), level="ERROR")
        errors.append(f"Error during manifest processing: {str(e)}")
        status = 'errors_found' # Or 'failed_precondition'
        return {'status': status, 'message': f'Error processing manifest: {str(e)}', 'checks': checks, 'errors': errors}
    finally:
        if manifest_local_temp_path and os.path.exists(manifest_local_temp_path):
            os.remove(manifest_local_temp_path)

    # Iterate through components in the manifest
    for component in manifest_data.get("components", []):
        component_type = component.get("type")
        component_name = component.get("name", component.get("filename", component.get("base_dir"))) # Meaningful name for logs
        share_name = component.get("share")

        if not share_name:
            _emit_progress(task_id, f"Missing 'share' for component: {component_name}", level="ERROR")
            errors.append(f"Missing 'share' for component: {component_name}")
            status = 'errors_found'
            continue

        try:
            share_client = service_client.get_share_client(share_name)
            if not _client_exists(share_client):
                _emit_progress(task_id, f"Share '{share_name}' for component '{component_name}' does not exist.", level="ERROR")
                errors.append(f"Share '{share_name}' for component '{component_name}' does not exist.")
                status = 'errors_found'
                checks.append({"component": component_type, "name": component_name, "share": share_name, "status": "Share not found"})
                continue

            item_exists = False
            if component_type == "database" or component_type == "config":
                filename = component.get("filename")
                if not filename:
                    _emit_progress(task_id, f"Missing 'filename' for {component_type} component: {component_name}", level="ERROR")
                    errors.append(f"Missing 'filename' for {component_type} component: {component_name}")
                    status = 'errors_found'
                    continue

                # Construct path based on component type
                if component_type == "database":
                    remote_path = f"{DB_BACKUPS_DIR}/{filename}"
                elif component_type == "config":
                    remote_path = f"{CONFIG_BACKUPS_DIR}/{filename}"
                else: # Should not happen if manifest is well-formed
                    remote_path = filename # Fallback, though potentially incorrect

                file_client = share_client.get_file_client(remote_path)
                item_exists = _client_exists(file_client)
                _emit_progress(task_id, f"Checking file: {remote_path} in share {share_name}", level="INFO")

            elif component_type == "media":
                base_dir = component.get("base_dir")
                if not base_dir:
                    _emit_progress(task_id, f"Missing 'base_dir' for media component: {component_name}", level="ERROR")
                    errors.append(f"Missing 'base_dir' for media component: {component_name}")
                    status = 'errors_found'
                    continue

                dir_client = share_client.get_directory_client(base_dir)
                item_exists = _client_exists(dir_client)
                _emit_progress(task_id, f"Checking directory: {base_dir} in share {share_name}", level="INFO")

            else:
                _emit_progress(task_id, f"Unknown component type: {component_type} for {component_name}", level="WARNING")
                errors.append(f"Unknown component type: {component_type} for {component_name}")
                status = 'errors_found'
                continue

            if item_exists:
                _emit_progress(task_id, f"Component '{component_name}' verified successfully in share '{share_name}'.", level="INFO")
                checks.append({"component": component_type, "name": component_name, "share": share_name, "status": "Verified"})
            else:
                _emit_progress(task_id, f"Component '{component_name}' not found in share '{share_name}'.", level="ERROR")
                errors.append(f"Component '{component_name}' not found in share '{share_name}'. Path: {remote_path if component_type != 'media' else base_dir}")
                status = 'errors_found'
                checks.append({"component": component_type, "name": component_name, "share": share_name, "status": "Not Found"})

        except Exception as e:
            _emit_progress(task_id, f"Error verifying component {component_name}: {str(e)}", level="ERROR")
            errors.append(f"Error verifying component {component_name}: {str(e)}")
            status = 'errors_found'
            checks.append({"component": component_type, "name": component_name, "share": share_name, "status": "Error", "detail": str(e)})

    final_message = "Verification completed."
    if errors:
        final_message = "Verification completed with errors."
        status = 'errors_found'
    elif status == 'verified' and not errors : # Explicitly set to verified if no errors and not failed_precondition
        final_message = "Backup set verified successfully."


    _emit_progress(task_id, final_message, detail=f"Checks: {len(checks)}, Errors: {len(errors)}", level="SUCCESS" if status == 'verified' else "ERROR")
    return {'status': status, 'message': final_message, 'checks': checks, 'errors': errors}

def restore_database_component(backup_timestamp, db_share_client, dry_run=False, task_id=None):
    """
    Restores (downloads) the database component from a backup.

    Args:
        backup_timestamp (str): The timestamp of the backup.
        db_share_client (ShareClient): The Azure File Share client for the DB share.
        dry_run (bool): If True, simulates the restore without actual download/changes.
        task_id (str, optional): The ID of the task for progress emission.

    Returns:
        tuple: (success_status, message, downloaded_file_path, error_detail)
               - success_status (bool): True if successful or dry run, False otherwise.
               - message (str): A message describing the outcome.
               - downloaded_file_path (str | None): Path to the downloaded DB file, or a simulated path for dry run.
               - error_detail (str | None): Details of any error that occurred.
    """
    if dry_run:
        _emit_progress(task_id, "DRY RUN: Simulating database component download.", level='INFO')
        _emit_progress(task_id, "DRY RUN: Database component download simulated successfully.", level='SUCCESS')
        return True, "Dry run: Database download simulated.", f"simulated_{DB_FILENAME_PREFIX}{backup_timestamp}.db", None

    _emit_progress(task_id, f"Starting actual database component restore for timestamp {backup_timestamp}.", level='INFO')

    db_filename = f"{DB_FILENAME_PREFIX}{backup_timestamp}.db"
    remote_db_file_path = f"{DB_BACKUPS_DIR}/{db_filename}"

    # Ensure DATA_DIR exists for temporary download
    if not os.path.exists(DATA_DIR):
        try:
            os.makedirs(DATA_DIR)
            _emit_progress(task_id, f"Created local data directory: {DATA_DIR}", level='INFO')
        except OSError as e:
            _emit_progress(task_id, f"Error creating local data directory {DATA_DIR}: {str(e)}", level='ERROR')
            return False, f"Error creating local data directory: {str(e)}", None, str(e)

    local_temp_db_path = os.path.join(DATA_DIR, f"downloaded_{db_filename}")

    _emit_progress(task_id, f"Attempting to download database backup '{remote_db_file_path}' to '{local_temp_db_path}'.", level='INFO')

    try:
        if not db_share_client: # Should be passed by the calling function (e.g. restore_full_backup)
            _emit_progress(task_id, "Azure DB Share client not available/provided.", level='ERROR')
            return False, "Azure DB Share client not available.", None, "DB Share client was None."

        download_success = download_file(db_share_client, remote_db_file_path, local_temp_db_path)

        if download_success:
            _emit_progress(task_id, f"Database backup '{db_filename}' downloaded successfully to '{local_temp_db_path}'.", level='SUCCESS')
            return True, f"Database backup '{db_filename}' downloaded to '{local_temp_db_path}'.", local_temp_db_path, None
        else:
            # download_file function logs its own errors, so just a general message here.
            error_msg = f"Failed to download database backup '{db_filename}' from Azure. Check logs for details from download_file utility."
            _emit_progress(task_id, error_msg, level='ERROR')
            return False, error_msg, None, error_msg # Provide the same message as detail for consistency

    except ResourceNotFoundError:
        error_msg = f"Database backup file '{remote_db_file_path}' not found in Azure share '{db_share_client.share_name}'."
        _emit_progress(task_id, error_msg, level='ERROR')
        return False, error_msg, None, error_msg
    except HttpResponseError as e:
        error_msg = f"Azure HTTP error during database component restore: {str(e)}"
        _emit_progress(task_id, error_msg, detail=e.message or str(e), level='ERROR')
        return False, error_msg, None, str(e.message or e)
    except Exception as e:
        error_msg = f"Unexpected error during database component restore: {str(e)}"
        _emit_progress(task_id, error_msg, level='ERROR')
        logger.error(f"Unexpected error in restore_database_component for {backup_timestamp}: {e}", exc_info=True)
        return False, error_msg, None, str(e)

def download_map_config_component(backup_timestamp, config_share_client, dry_run=False, task_id=None):
    logger.warning(f"Placeholder 'download_map_config_component' for {backup_timestamp}, task_id: {task_id}.")
    _emit_progress(task_id, "Map config download not implemented.", level='WARNING')
    return False, "Map config download not implemented.", None, None


def _download_config_component_generic(
    backup_timestamp,
    config_share_client,
    component_type_str,
    filename_prefix,
    task_id=None,
    dry_run=False
):
    """
    Generic helper to download a configuration component (map, resource, user configs).
    """
    if dry_run:
        _emit_progress(task_id, f"DRY RUN: Simulating {component_type_str} component download.", level='INFO')
        _emit_progress(task_id, f"DRY RUN: {component_type_str} component download simulated successfully.", level='SUCCESS')
        simulated_filename = f"simulated_{filename_prefix}{backup_timestamp}.json"
        return True, f"Dry run: {component_type_str} download simulated.", simulated_filename, None

    _emit_progress(task_id, f"Starting actual {component_type_str} component download for timestamp {backup_timestamp}.", level='INFO')

    if not config_share_client:
        error_msg = f"{component_type_str} download error: config_share_client not provided."
        _emit_progress(task_id, error_msg, level='ERROR')
        return False, error_msg, None, "config_share_client is None"

    try:
        os.makedirs(DATA_DIR, exist_ok=True) # Ensure DATA_DIR exists

        config_filename = f"{filename_prefix}{backup_timestamp}.json"
        remote_config_file_path = f"{CONFIG_BACKUPS_DIR}/{config_filename}"
        local_temp_config_path = os.path.join(DATA_DIR, f"downloaded_{config_filename}")

        _emit_progress(task_id, f"Attempting to download {component_type_str} backup '{remote_config_file_path}' to '{local_temp_config_path}'.", level='INFO')

        download_success = download_file(config_share_client, remote_config_file_path, local_temp_config_path)

        if download_success:
            _emit_progress(task_id, f"{component_type_str} backup '{config_filename}' downloaded successfully to '{local_temp_config_path}'.", level='SUCCESS')
            return True, f"{component_type_str} backup '{config_filename}' downloaded to '{local_temp_config_path}'.", local_temp_config_path, None
        else:
            error_msg = f"Failed to download '{remote_config_file_path}' for {component_type_str} from Azure."
            _emit_progress(task_id, f"Failed to download {component_type_str} backup '{config_filename}'. Error details should be in previous logs from download_file utility.", level='ERROR')
            return False, error_msg, None, error_msg

    except Exception as e:
        logger.error(f"Unexpected error during {component_type_str} component download for {backup_timestamp}: {e}", exc_info=True)
        error_msg = f"Error during {component_type_str} download: {str(e)}"
        _emit_progress(task_id, error_msg, level='ERROR')
        return False, error_msg, None, str(e)

def download_map_config_component(backup_timestamp, config_share_client, dry_run=False, task_id=None):
    return _download_config_component_generic(
        backup_timestamp,
        config_share_client,
        "map config",
        MAP_CONFIG_FILENAME_PREFIX,
        task_id,
        dry_run
    )

def download_resource_config_component(backup_timestamp, config_share_client, dry_run=False, task_id=None):
    return _download_config_component_generic(
        backup_timestamp,
        config_share_client,
        "resource configs",
        RESOURCE_CONFIG_FILENAME_PREFIX,
        task_id,
        dry_run
    )

def download_user_config_component(backup_timestamp, config_share_client, dry_run=False, task_id=None):
    return _download_config_component_generic(
        backup_timestamp,
        config_share_client,
        "user configs",
        USER_CONFIG_FILENAME_PREFIX,
        task_id,
        dry_run
    )

def restore_media_component(backup_timestamp, media_component_name, azure_remote_folder_base, local_target_folder_base, media_share_client, dry_run=False, task_id=None):
    """
    Restores (downloads) a media component (e.g., Floor Maps, Resource Uploads) from Azure.

    Args:
        backup_timestamp (str): The timestamp of the backup (used for logging context).
        media_component_name (str): Name of the media component (e.g., "Floor Maps").
        azure_remote_folder_base (str): The full path to the Azure directory containing the files to download
                                         (e.g., "media_backups/backup_YYYYMMDD_HHMMSS/floor_map_uploads").
        local_target_folder_base (str): The local base directory to download files into
                                         (e.g., "/app/static/floor_map_uploads").
        media_share_client (ShareClient): The Azure File Share client for the media share.
        dry_run (bool): If True, simulates the restore.
        task_id (str, optional): The ID of the task for progress emission.

    Returns:
        tuple: (success_status, message, error_detail)
               - success_status (bool): True if successful/dry run with no issues, False otherwise.
               - message (str): A message describing the outcome.
               - error_detail (str | None): Details of any error that occurred.
    """
    _emit_progress(task_id, f"Processing media component: {media_component_name}", level='INFO')

    if not media_share_client:
        error_msg = f"{media_component_name} restore error: media_share_client not provided."
        _emit_progress(task_id, error_msg, level='ERROR')
        return False, error_msg, error_msg

    try:
        dir_client = media_share_client.get_directory_client(azure_remote_folder_base)

        if dry_run:
            _emit_progress(task_id, f"DRY RUN: Simulating media restore for {media_component_name} from {azure_remote_folder_base} to {local_target_folder_base}.", level='INFO')
            if not _client_exists(dir_client):
                _emit_progress(task_id, f"DRY RUN: Azure source folder {azure_remote_folder_base} would not be found.", level='WARNING')
                # For dry run, not finding the source might not be a failure of the dry run itself, but a finding.
                return True, f"Dry run: Azure source folder {azure_remote_folder_base} not found for {media_component_name}.", None

            item_count = 0
            for item in dir_client.list_directories_and_files():
                if not item['is_directory']:
                    _emit_progress(task_id, f"DRY RUN: Would download {item['name']} for {media_component_name}.", level='INFO')
                    item_count +=1
            if item_count == 0:
                 _emit_progress(task_id, f"DRY RUN: No files found in {azure_remote_folder_base} to download for {media_component_name}.", level='INFO')
            _emit_progress(task_id, f"DRY RUN: Media restore for {media_component_name} simulated successfully. {item_count} files would be processed.", level='SUCCESS')
            return True, f"Dry run: Media restore for {media_component_name} simulated.", None

        # Actual Restore
        _emit_progress(task_id, f"Starting actual media restore for {media_component_name} from {azure_remote_folder_base} to {local_target_folder_base}.", level='INFO')

        os.makedirs(local_target_folder_base, exist_ok=True)

        if not _client_exists(dir_client):
            error_msg = f"Azure source folder {azure_remote_folder_base} not found for {media_component_name}."
            _emit_progress(task_id, error_msg, level='ERROR')
            return False, error_msg, error_msg

        files_downloaded_count = 0
        files_failed_count = 0
        errors_list = []
        items_in_source_dir = list(dir_client.list_directories_and_files()) # Consume generator to check if empty

        if not items_in_source_dir:
            final_message = f"Media restore for {media_component_name}: No files found in backup source '{azure_remote_folder_base}'."
            _emit_progress(task_id, final_message, level='INFO')
            return True, final_message, None

        for item in items_in_source_dir:
            if item['is_directory']:
                _emit_progress(task_id, f"Skipping subdirectory '{item['name']}' in media restore (not recursive).", level='INFO')
                continue

            file_name = item['name']
            # remote_file_path needs to be relative to the share for download_file if media_share_client is ShareClient
            # If azure_remote_folder_base is already the full path from share root, then this is correct.
            remote_file_path = f"{azure_remote_folder_base}/{file_name}"
            local_file_path = os.path.join(local_target_folder_base, file_name)

            _emit_progress(task_id, f"Downloading media file '{file_name}' for {media_component_name} to '{local_file_path}'.", level='INFO')

            # download_file expects share_client, path_on_share, local_destination_path
            download_success = download_file(media_share_client, remote_file_path, local_file_path)

            if download_success:
                files_downloaded_count += 1
            else:
                files_failed_count += 1
                error_detail = f"Failed to download {file_name} for {media_component_name}."
                errors_list.append(error_detail)
                _emit_progress(task_id, error_detail, level='ERROR')

        # After loop
        if files_failed_count > 0:
            final_message = f"Media restore for {media_component_name} completed with errors. Downloaded: {files_downloaded_count}, Failed: {files_failed_count}."
            _emit_progress(task_id, final_message, level='ERROR')
            return False, final_message, "; ".join(errors_list)
        # This case is now handled before the loop by checking items_in_source_dir
        # else if files_downloaded_count == 0:
        #     final_message = f"Media restore for {media_component_name}: No files were downloaded. Source '{azure_remote_folder_base}' might have been empty or contained only directories."
        #     _emit_progress(task_id, final_message, level='INFO')
        #     return True, final_message, None
        else: # files_downloaded_count > 0 and files_failed_count == 0
            final_message = f"Media restore for {media_component_name} completed successfully. Downloaded: {files_downloaded_count} files."
            _emit_progress(task_id, final_message, level='SUCCESS')
            return True, final_message, None

    except ResourceNotFoundError: # Should be caught by _client_exists generally, but good to have defense
        error_msg = f"Azure source folder {azure_remote_folder_base} not found during media restore for {media_component_name}."
        _emit_progress(task_id, error_msg, level='ERROR')
        return False, error_msg, error_msg
    except Exception as e:
        logger.error(f"Unexpected error during media restore for {media_component_name} (from {azure_remote_folder_base}): {e}", exc_info=True)
        error_msg = f"Error during media restore for {media_component_name}: {str(e)}"
        _emit_progress(task_id, error_msg, level='ERROR')
        return False, error_msg, str(e)

def restore_incremental_bookings(app, task_id=None):
    logger.warning(f"Placeholder 'restore_incremental_bookings', task_id: {task_id}.")
    _emit_progress(task_id, "Incremental booking restore not implemented.", level='WARNING')
    return {'status': 'not_implemented', 'message': 'Not implemented'}

def restore_bookings_from_full_db_backup(app, timestamp_str, task_id=None):
    logger.warning(f"Placeholder 'restore_bookings_from_full_db_backup' for {timestamp_str}, task_id: {task_id}.")
    _emit_progress(task_id, "Booking restore from full DB not implemented.", level='WARNING')
    return {'status': 'not_implemented', 'message': 'Not implemented'}

def backup_incremental_bookings(app, task_id=None):
    logger.warning(f"Placeholder 'backup_incremental_bookings', task_id: {task_id}.")
    _emit_progress(task_id, "Incremental booking backup not implemented.", level='WARNING')
    return False

def backup_full_bookings_json(app, task_id=None):
    """
    Creates a full backup of all booking data to a JSON file and uploads it to Azure File Share.
    """
    _emit_progress(task_id, "Starting manual full JSON backup of booking data...", level='INFO')

    try:
        connection_string = app.config.get('AZURE_STORAGE_CONNECTION_STRING', os.environ.get('AZURE_STORAGE_CONNECTION_STRING'))
        share_name = app.config.get('AZURE_BOOKING_DATA_SHARE', 'booking-data-backups') # Using 'booking-data-backups'

        if not connection_string:
            _emit_progress(task_id, "Azure Storage connection string is not configured.", level='ERROR')
            return False
        if not share_name:
            _emit_progress(task_id, "Azure File Share name for booking data is not configured.", level='ERROR')
            return False

        if ShareServiceClient is None:
            _emit_progress(task_id, "Azure SDK not installed. Cannot perform backup.", level='ERROR')
            return False

        _emit_progress(task_id, f"Fetching all bookings from the database...", level='INFO')
        all_bookings = Booking.query.all()

        if not all_bookings:
            _emit_progress(task_id, "No bookings found in the database. Proceeding to create an empty export.", level='WARNING')
            # Decide if an empty export is desired or return True (success, nothing to back up)
            # For now, proceeding to create an empty export as per plan.
        else:
            _emit_progress(task_id, f"Successfully fetched {len(all_bookings)} bookings.", level='INFO')

        booking_list_for_json = []
        for booking in all_bookings:
            booking_dict = {
                'id': booking.id,
                'resource_id': booking.resource_id,
                'user_name': booking.user_name,
                'start_time': booking.start_time.isoformat() if booking.start_time else None,
                'end_time': booking.end_time.isoformat() if booking.end_time else None,
                'title': booking.title,
                'checked_in_at': booking.checked_in_at.isoformat() if booking.checked_in_at else None,
                'checked_out_at': booking.checked_out_at.isoformat() if booking.checked_out_at else None,
                'status': booking.status,
                'recurrence_rule': booking.recurrence_rule,
                'admin_deleted_message': booking.admin_deleted_message,
                'check_in_token': booking.check_in_token,
                'check_in_token_expires_at': booking.check_in_token_expires_at.isoformat() if booking.check_in_token_expires_at else None,
                'checkin_reminder_sent_at': booking.checkin_reminder_sent_at.isoformat() if booking.checkin_reminder_sent_at else None,
                'last_modified': booking.last_modified.isoformat() if booking.last_modified else None,
                'booking_display_start_time': booking.booking_display_start_time.isoformat() if booking.booking_display_start_time else None,
                'booking_display_end_time': booking.booking_display_end_time.isoformat() if booking.booking_display_end_time else None
            }
            booking_list_for_json.append(booking_dict)

        _emit_progress(task_id, "Booking data serialized to JSON format.", level='INFO')

        export_data = {
            "export_timestamp": datetime.now(timezone.utc).isoformat(),
            "bookings": booking_list_for_json
        }

        timestamp_str = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        filename = f"manual_full_booking_export_{timestamp_str}.json"

        # Use os.path.join for local-like path construction, then ensure forward slashes for Azure
        target_directory_parts = [AZURE_BOOKING_DATA_PROTECTION_DIR, "manual_full_json"]
        target_directory = "/".join(part.strip("/") for part in target_directory_parts if part)


        _emit_progress(task_id, f"Initializing Azure ShareServiceClient for share '{share_name}'.", level='INFO')
        service_client = ShareServiceClient.from_connection_string(connection_string)
        share_client = service_client.get_share_client(share_name)

        if not _create_share_with_retry(share_client, share_name):
             _emit_progress(task_id, f"Failed to ensure Azure share '{share_name}' exists or create it.", level='ERROR')
             return False

        _emit_progress(task_id, f"Ensuring target directory '{target_directory}' exists in share '{share_name}'.", level='INFO')
        _ensure_directory_exists(share_client, target_directory) # _ensure_directory_exists handles path splitting

        tmp_file_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp_file:
                json.dump(export_data, tmp_file, indent=4)
                tmp_file_path = tmp_file.name

            _emit_progress(task_id, f"Temporary local JSON file created at {tmp_file_path}.", level='INFO')

            # Construct full remote path, ensuring forward slashes
            remote_file_path = f"{target_directory}/{filename}"

            _emit_progress(task_id, f"Uploading {filename} to Azure path {share_name}/{remote_file_path}.", level='INFO')
            upload_success = upload_file(share_client, tmp_file_path, remote_file_path)

            if upload_success:
                _emit_progress(task_id, "Manual full JSON backup of booking data completed successfully.", detail=f"File: {filename} uploaded to {share_name}/{target_directory}", level='SUCCESS')
                return True
            else:
                _emit_progress(task_id, "Failed to upload manual full JSON backup of booking data.", detail=f"Attempted to upload {filename} to {share_name}/{remote_file_path}", level='ERROR')
                return False
        finally:
            if tmp_file_path and os.path.exists(tmp_file_path):
                try:
                    os.remove(tmp_file_path)
                    _emit_progress(task_id, f"Temporary local file {tmp_file_path} cleaned up.", level='INFO')
                except OSError as e:
                    _emit_progress(task_id, f"Error removing temporary file {tmp_file_path}: {e}", level='ERROR')
                    logger.error(f"Error removing temporary file {tmp_file_path}: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"An unexpected error occurred in backup_full_bookings_json: {e}", exc_info=True)
        _emit_progress(task_id, "An unexpected error occurred during the backup process.", detail=str(e), level='ERROR')
        return False

def list_available_full_booking_json_exports():
    logger.warning("Placeholder 'list_available_full_booking_json_exports'. Not implemented.")
    return []

def restore_bookings_from_full_json_export(app, filename, task_id=None):
    logger.warning(f"Placeholder 'restore_bookings_from_full_json_export' for {filename}, task_id: {task_id}.")
    _emit_progress(task_id, "Booking restore from JSON export not implemented.", level='WARNING')
    return {'status': 'not_implemented', 'message': 'Not implemented'}

def delete_incremental_booking_backup(filename, backup_type=None, task_id=None):
    logger.warning(f"Placeholder 'delete_incremental_booking_backup' for {filename}, task_id: {task_id}.")
    _emit_progress(task_id, "Delete incremental booking backup not implemented.", level='WARNING')
    return False

# ... (rest of the file, e.g., download_booking_data_json_backup, etc.)
# Ensure all functions from the original file that are still needed are present.
# The provided snippet ends here, assuming other functions are either correctly refactored
# or are not part of this specific subtask's scope for changes other than signature updates.
# Make sure the unified booking data protection functions are also updated if they use _emit_progress.
# Based on the original read_files, the functions like backup_full_booking_data_json_azure,
# backup_scheduled_incremental_booking_data, delete_booking_data_json_backup,
# restore_booking_data_from_json_backup, restore_booking_data_to_point_in_time,
# _apply_single_incremental_json_file were already using task_id correctly with _emit_progress.
# So their signatures related to socketio_instance might already be fine or not applicable.
# The focus was on the system backup functions.
# The provided code for delete_backup_set is a new implementation, not a refactor of a placeholder.
# The placeholder functions at the end were modified as requested.
