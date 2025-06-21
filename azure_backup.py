import os
import hashlib
import logging
import sqlite3
import json
from datetime import datetime, timezone # Ensure 'time' is not imported if not used directly, or 'import time as time_module'
import tempfile
import re
import time # This is the standard time module
import csv # Keep if CSV related functionality exists or is planned
import shutil
# tempfile was listed twice, removed one instance
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError, ServiceRequestError

# Ensure os, json, logging, re, datetime, timezone, time are available (already imported or standard)
from models import Booking, db
# From utils import _import_map_configuration_data, _import_resource_configurations_data, _import_user_configurations_data, add_audit_log
from utils import _import_map_configuration_data, _import_resource_configurations_data, _import_user_configurations_data, add_audit_log # Added
from extensions import db # Ensure db is imported from extensions (already imported via models)
from utils import update_task_log # Ensure this is imported from utils
# datetime, time, timezone were listed twice, ensured they are covered
# Removed redundant import of tempfile, shutil, re, time, csv, json, logging, os, datetime, timezone as they are covered above or standard

from flask_migrate import upgrade as flask_db_upgrade # <<< ADDED IMPORT

try:
    from azure.storage.fileshare import ShareServiceClient, ShareClient, ShareDirectoryClient, ShareFileClient
except ImportError:  # pragma: no cover - azure sdk optional
    ShareServiceClient = None
    ShareClient = None
    ShareDirectoryClient = None
    ShareFileClient = None
    if 'ResourceNotFoundError' not in globals(): # Defensive
        ResourceNotFoundError = type('ResourceNotFoundError', (Exception,), {})
    if 'HttpResponseError' not in globals(): # Defensive
        HttpResponseError = type('HttpResponseError', (Exception,), {})


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
FLOOR_MAP_UPLOADS = os.path.join(STATIC_DIR, 'floor_map_uploads')
RESOURCE_UPLOADS = os.path.join(STATIC_DIR, 'resource_uploads')
HASH_DB = os.path.join(DATA_DIR, 'backup_hashes.db')

logger = logging.getLogger(__name__)


def list_booking_data_json_backups():
    logger.info("Attempting to list unified booking data JSON backups from Azure.")
    all_backups = []

    try:
        service_client = _get_service_client()
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

        backup_sources = [
            {"subdir": "manual_full_json", "type": "manual_full_json", "name_pattern": re.compile(r"manual_full_booking_export_(\d{8}_\d{6})\.json")}
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
                    continue

                filename = item['name']
                match = source['name_pattern'].match(filename)
                if match:
                    timestamp_str_from_name = match.group(1)
                    try:
                        dt_obj_naive = datetime.strptime(timestamp_str_from_name, '%Y%m%d_%H%M%S')
                        dt_obj_utc = dt_obj_naive.replace(tzinfo=timezone.utc)
                        iso_timestamp_str = dt_obj_utc.isoformat()
                        display_name = f"{source['type'].replace('_', ' ').title()} - {dt_obj_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                        all_backups.append({
                            'filename': filename,
                            'full_path': f"{source_dir_path}/{filename}",
                            'display_name': display_name,
                            'type': source['type'],
                            'timestamp_str': iso_timestamp_str,
                            'size_bytes': item.get('size', 0)
                        })
                        logger.debug(f"Found backup: {filename}, Timestamp: {iso_timestamp_str}")
                    except ValueError:
                        logger.warning(f"Could not parse timestamp from filename: {filename} in {source_dir_path}. Skipping.")
                    except Exception as e_parse:
                         logger.error(f"Error processing file {filename} in {source_dir_path}: {e_parse}", exc_info=True)
                else:
                    logger.debug(f"Filename {filename} in {source_dir_path} did not match pattern for type {source['type']}.")
        all_backups.sort(key=lambda x: x['timestamp_str'], reverse=True)
        logger.info(f"Found {len(all_backups)} unified booking data backups.")
        return all_backups
    except Exception as e:
        logger.error(f"Error listing unified booking data JSON backups: {e}", exc_info=True)
        return []

def delete_booking_data_json_backup(filename, backup_type=None, task_id=None):
    log_prefix = f"[Task {task_id}] " if task_id else ""
    logger.info(f"{log_prefix}Attempting to delete unified backup: Type='{backup_type}', Filename='{filename}'.")
    try:
        service_client = _get_service_client()
        share_name = os.environ.get('AZURE_BOOKING_DATA_SHARE', 'booking-data-backups')
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
        else:
            logger.error(f"{log_prefix}Cannot determine directory for backup type '{backup_type}'. Deletion aborted.")
            return False
        remote_file_path = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{target_subdir}/{filename}"
        file_client = share_client.get_file_client(remote_file_path)
        if not _client_exists(file_client):
            logger.warning(f"{log_prefix}File '{remote_file_path}' not found in share '{share_name}'. No action taken, considered success for deletion.")
            return True
        file_client.delete_file()
        logger.info(f"{log_prefix}Successfully deleted file '{remote_file_path}'.")
        return True
    except ResourceNotFoundError:
        logger.warning(f"{log_prefix}File '{filename}' (Type: {backup_type}) not found during delete. Considered success.")
        return True
    except Exception as e:
        logger.error(f"{log_prefix}An unexpected error occurred during deletion of '{filename}' (Type: {backup_type}): {e}", exc_info=True)
        return False

def restore_booking_data_to_point_in_time(app, selected_filename, selected_type, selected_timestamp_iso, task_id=None):
    update_task_log(task_id, f"Starting restore from '{selected_filename}' (Type: {selected_type}).", level="info")
    if selected_type != "manual_full_json":
        msg = f"Restore for backup type '{selected_type}' is not currently supported. Only 'manual_full_json' is supported."
        update_task_log(task_id, msg, level="error")
        return {'status': 'failure', 'message': msg, 'errors': [msg]}
    try:
        with app.app_context():
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
            except Exception as e:
                msg = f"Error processing backup file content: {str(e)}"
                update_task_log(task_id, msg, level="error")
                return {'status': 'failure', 'message': msg, 'errors': [f"File processing error: {str(e)}"]}
            update_task_log(task_id, "WARNING: All existing booking data in the database will be deleted before restoring. This action cannot be undone.", level="warning")
            update_task_log(task_id, "Deleting existing booking data...", level="info")
            try:
                num_deleted = db.session.query(Booking).delete()
                db.session.commit()
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
                    if not all(k in booking_json for k in ['id', 'resource_id', 'user_name', 'start_time', 'end_time', 'status']):
                        bookings_failed_count += 1
                        err_msg = f"Skipping booking entry {i+1} due to missing essential fields (id, resource_id, etc.). Data: {str(booking_json)[:200]}"
                        restore_errors.append(err_msg)
                        update_task_log(task_id, err_msg, level="warning")
                        continue
                    def parse_datetime_optional(dt_str):
                        if not dt_str: return None
                        if isinstance(dt_str, str) and dt_str.endswith('Z'):
                            return datetime.fromisoformat(dt_str[:-1] + '+00:00')
                        return datetime.fromisoformat(dt_str) if isinstance(dt_str, str) else None
                    def parse_time_optional(t_str):
                        if not t_str: return None
                        # Ensure this handles various time formats potentially stored, or standardize export
                        try:
                            return datetime.strptime(t_str, '%H:%M:%S').time() if isinstance(t_str, str) else None
                        except ValueError:
                             return datetime.strptime(t_str, '%H:%M').time() if isinstance(t_str, str) else None

                    new_booking = Booking(
                        id=booking_json['id'], resource_id=booking_json['resource_id'], user_name=booking_json.get('user_name'),
                        title=booking_json.get('title'), start_time=parse_datetime_optional(booking_json['start_time']),
                        end_time=parse_datetime_optional(booking_json['end_time']), status=booking_json.get('status', 'approved'),
                        checked_in_at=parse_datetime_optional(booking_json.get('checked_in_at')), checked_out_at=parse_datetime_optional(booking_json.get('checked_out_at')),
                        recurrence_rule=booking_json.get('recurrence_rule'), admin_deleted_message=booking_json.get('admin_deleted_message'),
                        check_in_token=booking_json.get('check_in_token'), check_in_token_expires_at=parse_datetime_optional(booking_json.get('check_in_token_expires_at')),
                        checkin_reminder_sent_at=parse_datetime_optional(booking_json.get('checkin_reminder_sent_at')),
                        last_modified=parse_datetime_optional(booking_json.get('last_modified')) or datetime.now(timezone.utc),
                        booking_display_start_time=parse_time_optional(booking_json.get('booking_display_start_time')),
                        booking_display_end_time=parse_time_optional(booking_json.get('booking_display_end_time')))
                    db.session.add(new_booking)
                    bookings_restored_count += 1
                    if bookings_restored_count % 100 == 0:
                        update_task_log(task_id, f"Restored {bookings_restored_count}/{len(bookings_from_json)} bookings...", level="info")
                except Exception as e_item:
                    bookings_failed_count += 1
                    err_msg = f"Error restoring booking item {i+1} (ID: {booking_json.get('id', 'N/A')}): {str(e_item)}. Data: {str(booking_json)[:200]}"
                    restore_errors.append(err_msg)
                    update_task_log(task_id, err_msg, level="error")
                    db.session.rollback()
            if bookings_failed_count > 0:
                db.session.commit()
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
        update_task_log(task_id, msg, level="critical", detail=str(e_main))
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
        target_subdir = ""
        if backup_type == "manual_full_json":
            target_subdir = "manual_full_json"
        else:
            logger.warning(f"Unknown or unhandled backup_type '{backup_type}' for download. Attempting download from base backup directory.")
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

LAST_INCREMENTAL_BOOKING_TIMESTAMP_FILE = os.path.join(DATA_DIR, 'last_incremental_booking_timestamp.txt')
BOOKING_INCREMENTAL_BACKUPS_DIR = 'booking_incremental_backups'
FULL_SYSTEM_BACKUPS_BASE_DIR = "full_system_backups"
COMPONENT_SUBDIR_DATABASE = "database"
COMPONENT_SUBDIR_CONFIGURATIONS = "configurations"
COMPONENT_SUBDIR_MEDIA = "media"
COMPONENT_SUBDIR_MANIFEST = "manifest"
DB_FILENAME_PREFIX = 'site_'
MAP_CONFIG_FILENAME_PREFIX = 'map_config_'
RESOURCE_CONFIG_FILENAME_PREFIX = "resource_configs_"
USER_CONFIG_FILENAME_PREFIX = "user_configs_"
SCHEDULER_SETTINGS_FILENAME_PREFIX = "scheduler_settings_"
BOOKING_FULL_JSON_EXPORTS_DIR = 'booking_full_json_exports'
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
        logger.error("Azure SDK (azure-storage-file-share) not installed. This is required for Azure backup/restore functionality.")
        raise RuntimeError('azure-storage-file-share package is not installed. Please install it to use Azure features.')
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
    from utils import update_task_log
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
    logger.info("Attempting to list available full system backups from new unified structure.")
    try:
        system_backup_share_name = os.environ.get('AZURE_SYSTEM_BACKUP_SHARE', 'system-backups')
        service_client = _get_service_client()
        share_client = service_client.get_share_client(system_backup_share_name)
        if not _client_exists(share_client):
            logger.warning(f"System backup share '{system_backup_share_name}' not found.")
            return []
        base_backup_sets_dir_client = share_client.get_directory_client(FULL_SYSTEM_BACKUPS_BASE_DIR)
        if not _client_exists(base_backup_sets_dir_client):
            logger.info(f"Base directory for full system backups ('{FULL_SYSTEM_BACKUPS_BASE_DIR}') not found in share '{system_backup_share_name}'. No backups to list.")
            return []
        available_timestamps = []
        backup_dir_pattern = re.compile(r"^backup_(\d{8}_\d{6})$")
        for item in base_backup_sets_dir_client.list_directories_and_files():
            if item['is_directory']:
                dir_name = item['name']
                match = backup_dir_pattern.match(dir_name)
                if match:
                    timestamp_str = match.group(1)
                    manifest_filename = f"backup_manifest_{timestamp_str}.json"
                    full_manifest_path_on_share = f"{FULL_SYSTEM_BACKUPS_BASE_DIR}/{dir_name}/{COMPONENT_SUBDIR_MANIFEST}/{manifest_filename}"
                    manifest_file_client = share_client.get_file_client(full_manifest_path_on_share)
                    if _client_exists(manifest_file_client):
                        try:
                            datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
                            available_timestamps.append(timestamp_str)
                            logger.debug(f"Found valid backup set: {dir_name} with manifest at {full_manifest_path_on_share}.")
                        except ValueError:
                            logger.warning(f"Directory '{dir_name}' matches backup pattern but timestamp '{timestamp_str}' is invalid. Skipping.")
                    else:
                        logger.warning(f"Directory '{dir_name}' found, but its manifest '{full_manifest_path_on_share}' is missing. Skipping.")
        return sorted(list(set(available_timestamps)), reverse=True)
    except Exception as e:
        logger.error(f"Error listing available full system backups from new structure: {e}", exc_info=True)
        return []

def restore_full_backup(backup_timestamp, task_id=None, dry_run=False):
    logger.warning(f"Placeholder 'restore_full_backup' for {backup_timestamp}, dry_run={dry_run}, task_id: {task_id}.")
    if dry_run:
        _emit_progress(task_id, "DRY RUN: Starting...", detail=f'Timestamp: {backup_timestamp}')
        _emit_progress(task_id, "DRY RUN: Completed.", detail=json.dumps({'actions': ["Simulated action 1"]}), level='SUCCESS')
        return None, None, None, None, ["Simulated action 1"]
    _emit_progress(task_id, "Restore Error: Not implemented.", detail='NOT_IMPLEMENTED', level='ERROR')
    return None, None, None, None, []

def create_full_backup(timestamp_str, map_config_data=None, resource_configs_data=None, user_configs_data=None, task_id=None):
    _emit_progress(task_id, f"AzureBackup: Received map_config_data type: {type(map_config_data)}", level='DEBUG')
    if isinstance(resource_configs_data, list):
        _emit_progress(task_id, f"AzureBackup: Received resource_configs_data type: list, length: {len(resource_configs_data)}", level='DEBUG')
        if resource_configs_data:
            _emit_progress(task_id, f"AzureBackup: First received resource item (summary): {str(resource_configs_data[0])[:200]}...", level='DEBUG')
    else:
        _emit_progress(task_id, f"AzureBackup: Received resource_configs_data type: {type(resource_configs_data)}, value: {str(resource_configs_data)[:200]}...", level='DEBUG')
    if isinstance(user_configs_data, dict):
        users_count = len(user_configs_data.get('users', []))
        roles_count = len(user_configs_data.get('roles', []))
        _emit_progress(task_id, f"AzureBackup: Received user_configs_data type: dict. Users: {users_count}, Roles: {roles_count}", level='DEBUG')
        if user_configs_data.get('users'):
            _emit_progress(task_id, f"AzureBackup: First received user item (summary): {str(user_configs_data['users'][0])[:200]}...", level='DEBUG')
        if user_configs_data.get('roles'):
            _emit_progress(task_id, f"AzureBackup: First received role item (summary): {str(user_configs_data['roles'][0])[:200]}...", level='DEBUG')
    else:
        _emit_progress(task_id, f"AzureBackup: Received user_configs_data type: {type(user_configs_data)}, value: {str(user_configs_data)[:200]}...", level='DEBUG')
    overall_success = True
    backed_up_items = []
    _emit_progress(task_id, f"AzureBackup: Received map_config_data type: {type(map_config_data)}", level='DEBUG')
    if isinstance(resource_configs_data, list):
        _emit_progress(task_id, f"AzureBackup: Received resource_configs_data type: list, length: {len(resource_configs_data)}", level='DEBUG')
        if resource_configs_data: _emit_progress(task_id, f"AzureBackup: First received resource item (summary): {str(resource_configs_data[0])[:200]}...", level='DEBUG')
    else:
        _emit_progress(task_id, f"AzureBackup: Received resource_configs_data type: {type(resource_configs_data)}, value: {str(resource_configs_data)[:200]}...", level='DEBUG')
    if isinstance(user_configs_data, dict):
        users_count = len(user_configs_data.get('users', [])); roles_count = len(user_configs_data.get('roles', []))
        _emit_progress(task_id, f"AzureBackup: Received user_configs_data type: dict. Users: {users_count}, Roles: {roles_count}", level='DEBUG')
        if user_configs_data.get('users'): _emit_progress(task_id, f"AzureBackup: First received user item (summary): {str(user_configs_data['users'][0])[:200]}...", level='DEBUG')
        if user_configs_data.get('roles'): _emit_progress(task_id, f"AzureBackup: First received role item (summary): {str(user_configs_data['roles'][0])[:200]}...", level='DEBUG')
    else:
        _emit_progress(task_id, f"AzureBackup: Received user_configs_data type: {type(user_configs_data)}, value: {str(user_configs_data)[:200]}...", level='DEBUG')
    _emit_progress(task_id, "Attempting to initialize Azure service client for backup...", level='INFO')
    try:
        service_client = _get_service_client()
        if not service_client:
            _emit_progress(task_id, "Failed to get Azure service client (None returned).", level='ERROR')
            return False
        _emit_progress(task_id, "Azure service client initialized.", level='INFO')
    except RuntimeError as e:
        logger.error(f"RuntimeError initializing Azure service client in create_full_backup: {str(e)}")
        _emit_progress(task_id, f"Backup Pre-check Failed: Azure client initialization error: {str(e)}", detail=str(e), level='ERROR')
        return False
    system_backup_share_name = os.environ.get('AZURE_SYSTEM_BACKUP_SHARE', 'system-backups')
    share_client = service_client.get_share_client(system_backup_share_name)
    _emit_progress(task_id, f"Using Azure File Share: '{system_backup_share_name}' for all components.", level='INFO')
    try:
        if not _create_share_with_retry(share_client, system_backup_share_name):
            _emit_progress(task_id, f"Failed to create or ensure system backup share '{system_backup_share_name}' exists.", level='ERROR')
            return False
    except Exception as e_share_create:
        _emit_progress(task_id, f"Critical error ensuring system backup share '{system_backup_share_name}' exists: {str(e_share_create)}", level='ERROR')
        return False
    current_backup_root_path_on_share = f"{FULL_SYSTEM_BACKUPS_BASE_DIR}/backup_{timestamp_str}"
    try:
        _ensure_directory_exists(share_client, FULL_SYSTEM_BACKUPS_BASE_DIR)
        _ensure_directory_exists(share_client, current_backup_root_path_on_share)
        _emit_progress(task_id, f"Ensured main backup directory on share: '{current_backup_root_path_on_share}'.", level='INFO')
    except Exception as e_main_dir:
        _emit_progress(task_id, f"Failed to create main backup directory '{current_backup_root_path_on_share}' on share: {str(e_main_dir)}", level='ERROR')
        return False
    _emit_progress(task_id, "Starting database backup component...", level='INFO')
    remote_db_dir = f"{current_backup_root_path_on_share}/{COMPONENT_SUBDIR_DATABASE}"
    try:
        _ensure_directory_exists(share_client, remote_db_dir)
        local_db_path = os.path.join(DATA_DIR, 'site.db')
        db_backup_filename = f"{DB_FILENAME_PREFIX}{timestamp_str}.db"
        remote_db_file_path = f"{remote_db_dir}/{db_backup_filename}"
        if not os.path.exists(local_db_path):
            _emit_progress(task_id, f"Local database file not found at '{local_db_path}'. Cannot proceed with DB backup.", level='ERROR')
            overall_success = False
        elif upload_file(share_client, local_db_path, remote_db_file_path):
            _emit_progress(task_id, "Database backup successful.", detail=f"Uploaded to: {remote_db_file_path}", level='SUCCESS')
            backed_up_items.append({"type": "database", "filename": db_backup_filename, "path_in_backup": f"{COMPONENT_SUBDIR_DATABASE}/{db_backup_filename}"})
        else:
            _emit_progress(task_id, "Database backup failed during upload.", detail=f"Target: {remote_db_file_path}", level='ERROR')
            overall_success = False
    except Exception as e_db:
        _emit_progress(task_id, f"Database backup component failed with an unexpected error: {str(e_db)}", level='ERROR')
        overall_success = False
    if overall_success:
        _emit_progress(task_id, "Starting configuration files backup component...", level='INFO')
        remote_config_dir = f"{current_backup_root_path_on_share}/{COMPONENT_SUBDIR_CONFIGURATIONS}"
        try:
            _ensure_directory_exists(share_client, remote_config_dir)
            configs_to_backup_dynamically = [
                (map_config_data, "map_config", MAP_CONFIG_FILENAME_PREFIX),
                (resource_configs_data, "resource_configs", RESOURCE_CONFIG_FILENAME_PREFIX),
                (user_configs_data, "user_configs", USER_CONFIG_FILENAME_PREFIX)]
            for config_data, name, prefix in configs_to_backup_dynamically:
                _emit_progress(task_id, f"AzureBackup: Checking dynamic config component '{name}'. Data is None: {config_data is None}. Data is empty (if applicable): {not config_data if isinstance(config_data, (list, dict)) else 'N/A'}", level='DEBUG')
                if not config_data:
                    _emit_progress(task_id, f"Dynamic configuration '{name}' data is empty or None, skipping.", level='INFO')
                    continue
                tmp_json_path = None
                try:
                    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', dir=DATA_DIR, encoding='utf-8') as tmp_json_file:
                        json.dump(config_data, tmp_json_file, indent=4)
                        tmp_json_path = tmp_json_file.name
                    config_filename = f"{prefix}{timestamp_str}.json"
                    remote_config_file_path = f"{remote_config_dir}/{config_filename}"
                    if upload_file(share_client, tmp_json_path, remote_config_file_path):
                        _emit_progress(task_id, f"Configuration '{name}' backup successful.", detail=f"Uploaded to: {remote_config_file_path}", level='SUCCESS')
                        backed_up_items.append({"type": "config", "name": name, "filename": config_filename, "path_in_backup": f"{COMPONENT_SUBDIR_CONFIGURATIONS}/{config_filename}"})
                    else:
                        _emit_progress(task_id, f"Configuration '{name}' backup failed during upload.", detail=f"Target: {remote_config_file_path}", level='ERROR')
                        overall_success = False
                finally:
                    if tmp_json_path and os.path.exists(tmp_json_path): os.remove(tmp_json_path)
            scheduler_settings_local_path = os.path.join(DATA_DIR, 'scheduler_settings.json')
            _emit_progress(task_id, f"Checking for scheduler_settings.json at {scheduler_settings_local_path}", level='INFO')
            if os.path.exists(scheduler_settings_local_path):
                scheduler_filename = f"{SCHEDULER_SETTINGS_FILENAME_PREFIX}{timestamp_str}.json"
                remote_scheduler_file_path = f"{remote_config_dir}/{scheduler_filename}"
                _emit_progress(task_id, f"Attempting to backup scheduler_settings.json to {remote_scheduler_file_path}", level='INFO')
                if upload_file(share_client, scheduler_settings_local_path, remote_scheduler_file_path):
                    _emit_progress(task_id, "scheduler_settings.json backup successful.", level='SUCCESS')
                    backed_up_items.append({"type": "config", "name": "scheduler_settings", "filename": scheduler_filename, "path_in_backup": f"{COMPONENT_SUBDIR_CONFIGURATIONS}/{scheduler_filename}"})
                else:
                    _emit_progress(task_id, "scheduler_settings.json backup failed.", level='ERROR')
                    overall_success = False
            else:
                _emit_progress(task_id, "scheduler_settings.json not found locally, skipping its backup.", level='WARNING')
        except Exception as e_cfg:
            _emit_progress(task_id, f"Configuration files backup component failed with an unexpected error: {str(e_cfg)}", level='ERROR')
            overall_success = False
    if overall_success:
        _emit_progress(task_id, "Starting media files backup component...", level='INFO')
        azure_media_base_for_this_backup = f"{current_backup_root_path_on_share}/{COMPONENT_SUBDIR_MEDIA}"
        try:
            _ensure_directory_exists(share_client, azure_media_base_for_this_backup)
            media_sources = [
                {"name": "Floor Maps", "path": FLOOR_MAP_UPLOADS, "subdir_on_azure": "floor_map_uploads"},
                {"name": "Resource Uploads", "path": RESOURCE_UPLOADS, "subdir_on_azure": "resource_uploads"}]
            all_media_component_success = True
            for src in media_sources:
                _emit_progress(task_id, f"Processing media source: {src['name']}. Local path: '{src['path']}'", level='DEBUG')
                is_local_dir = os.path.isdir(src["path"])
                _emit_progress(task_id, f"Path '{src['path']}' is directory? {is_local_dir}", level='DEBUG')
                if not is_local_dir:
                    _emit_progress(task_id, f"Local path for {src['name']} ('{src['path']}') is not a directory or not found, skipping.", level='WARNING')
                    continue
                azure_target_dir_for_source = f"{azure_media_base_for_this_backup}/{src['subdir_on_azure']}"
                _ensure_directory_exists(share_client, azure_target_dir_for_source)
                files_in_local_source_path = []
                try:
                    files_in_local_source_path = os.listdir(src["path"])
                    _emit_progress(task_id, f"Files/folders found in '{src['path']}': {files_in_local_source_path}", level='DEBUG')
                except Exception as e_listdir:
                    _emit_progress(task_id, f"Error listing directory '{src['path']}': {str(e_listdir)}", level='ERROR')
                    all_media_component_success = False; continue
                if not files_in_local_source_path:
                    _emit_progress(task_id, f"No files/subdirectories in '{src['path']}' for {src['name']}, skipping.", level='INFO')
                    continue
                _emit_progress(task_id, f"Uploading items from {src['path']} to Azure directory {azure_target_dir_for_source} for {src['name']}...", level='INFO')
                uploads_succeeded_count = 0; uploads_failed_count = 0
                for filename_in_src in files_in_local_source_path:
                    local_file_full_path = os.path.join(src["path"], filename_in_src)
                    _emit_progress(task_id, f"Item: '{filename_in_src}'. Full local path: '{local_file_full_path}'", level='DEBUG')
                    is_local_file = os.path.isfile(local_file_full_path)
                    _emit_progress(task_id, f"Path '{local_file_full_path}' is file? {is_local_file}", level='DEBUG')
                    if is_local_file:
                        remote_file_path_on_azure = f"{azure_target_dir_for_source}/{filename_in_src}"
                        if upload_file(share_client, local_file_full_path, remote_file_path_on_azure):
                            uploads_succeeded_count += 1
                        else:
                            uploads_failed_count += 1; all_media_component_success = False
                    else:
                        _emit_progress(task_id, f"Skipping non-file item '{filename_in_src}' in {src['path']}.", level='INFO')
                if uploads_failed_count > 0: _emit_progress(task_id, f"{src['name']} backup: {uploads_succeeded_count} uploaded, {uploads_failed_count} failed.", level='ERROR')
                elif uploads_succeeded_count > 0: _emit_progress(task_id, f"{src['name']} backup: All {uploads_succeeded_count} file(s) uploaded successfully.", level='SUCCESS')
                else: _emit_progress(task_id, f"{src['name']} backup: No actual files uploaded (source might be empty of files).", level='INFO')
            if all_media_component_success:
                 backed_up_items.append({"type": "media", "name": "media_files", "path_in_backup": COMPONENT_SUBDIR_MEDIA})
            else:
                overall_success = False
                _emit_progress(task_id, "Media backup component completed with errors. Not all media files may have been backed up.", level='ERROR')
        except Exception as e_media:
            _emit_progress(task_id, f"Media backup component failed with an unexpected error: {str(e_media)}", level='ERROR')
            overall_success = False
    if overall_success:
        _emit_progress(task_id, "Creating backup manifest...", level='INFO')
        remote_manifest_dir = f"{current_backup_root_path_on_share}/{COMPONENT_SUBDIR_MANIFEST}"
        try:
            _ensure_directory_exists(share_client, remote_manifest_dir)
            manifest_data = {"backup_timestamp": timestamp_str, "backup_version": "1.1_unified_structure", "components": []}
            for item in backed_up_items:
                component_entry = {"type": item["type"], "name": item.get("name", item.get("filename")), "path_in_backup": item["path_in_backup"]}
                if item.get("filename"): component_entry["original_filename"] = item["filename"]
                manifest_data["components"].append(component_entry)
            tmp_manifest_path = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', dir=DATA_DIR, encoding='utf-8') as tmp_mf:
                    tmp_manifest_path = tmp_mf.name
                    json.dump(manifest_data, tmp_mf, indent=4)
                manifest_filename_on_share = f"backup_manifest_{timestamp_str}.json"
                remote_manifest_file_path = f"{remote_manifest_dir}/{manifest_filename_on_share}"
                if upload_file(share_client, tmp_manifest_path, remote_manifest_file_path):
                    _emit_progress(task_id, "Manifest uploaded successfully.", detail=f"Uploaded to: {remote_manifest_file_path}", level='SUCCESS')
                else:
                    _emit_progress(task_id, "Manifest upload failed.", detail=f"Target: {remote_manifest_file_path}", level='ERROR')
                    overall_success = False
            finally:
                if tmp_manifest_path and os.path.exists(tmp_manifest_path): os.remove(tmp_manifest_path)
        except Exception as e_manifest:
            _emit_progress(task_id, "Error creating or uploading manifest.", detail=str(e_manifest), level='ERROR')
            overall_success = False
    if overall_success:
        _emit_progress(task_id, "Full system backup completed successfully.", detail=f"Backup root: {current_backup_root_path_on_share}", level='SUCCESS')
    else:
        _emit_progress(task_id, "Full system backup completed with errors.", detail=f"Backup root (may be incomplete): {current_backup_root_path_on_share}", level='ERROR')
    return overall_success

def _recursively_delete_share_directory(share_client: ShareClient, dir_full_path_on_share: str, task_id: str = None) -> bool:
    _emit_progress(task_id, f"Attempting to recursively delete directory: '{dir_full_path_on_share}'", level='DEBUG')
    try:
        dir_client = share_client.get_directory_client(dir_full_path_on_share)
        if not _client_exists(dir_client):
            _emit_progress(task_id, f"Directory '{dir_full_path_on_share}' not found. Nothing to delete.", level='INFO')
            return True
        items = list(dir_client.list_directories_and_files())
        _emit_progress(task_id, f"Found {len(items)} items in '{dir_full_path_on_share}'.", level='DEBUG')
        for item in items:
            item_path = f"{dir_full_path_on_share}/{item['name']}"
            if item['is_directory']:
                if not _recursively_delete_share_directory(share_client, item_path, task_id):
                    _emit_progress(task_id, f"Failed to delete subdirectory '{item_path}'. Aborting deletion of '{dir_full_path_on_share}'.", level='ERROR')
                    return False
            else:
                _emit_progress(task_id, f"Deleting file: '{item_path}'", level='DEBUG')
                file_client = share_client.get_file_client(item_path)
                if _client_exists(file_client): file_client.delete_file()
                else: _emit_progress(task_id, f"File '{item_path}' listed but not found during deletion attempt. Skipping.", level='WARNING')
        _emit_progress(task_id, f"All contents of '{dir_full_path_on_share}' deleted. Deleting directory itself.", level='DEBUG')
        dir_client.delete_directory()
        _emit_progress(task_id, f"Successfully deleted directory: '{dir_full_path_on_share}'", level='INFO')
        return True
    except ResourceNotFoundError:
        _emit_progress(task_id, f"Directory '{dir_full_path_on_share}' became not found during deletion process.", level='WARNING')
        return True
    except Exception as e:
        _emit_progress(task_id, f"Error recursively deleting directory '{dir_full_path_on_share}': {str(e)}", level='ERROR')
        logger.error(f"[Task {task_id}] Error recursively deleting directory '{dir_full_path_on_share}': {e}", exc_info=True)
        return False

def delete_backup_set(backup_timestamp, task_id=None):
    logger.info(f"[Task {task_id}] Initiating deletion for backup set with timestamp: {backup_timestamp}")
    _emit_progress(task_id, f"Starting deletion of backup set: {backup_timestamp}", level="INFO")
    try:
        service_client = _get_service_client()
    except RuntimeError as e:
        _emit_progress(task_id, "Failed to initialize Azure service client for deletion.", detail=str(e), level="ERROR")
        return False
    system_backup_share_name = os.environ.get('AZURE_SYSTEM_BACKUP_SHARE', 'system-backups')
    share_client = service_client.get_share_client(system_backup_share_name)
    if not _client_exists(share_client):
        _emit_progress(task_id, f"System backup share '{system_backup_share_name}' not found. Cannot delete backup set.", level="ERROR")
        return False
    target_backup_set_path = f"{FULL_SYSTEM_BACKUPS_BASE_DIR}/backup_{backup_timestamp}"
    _emit_progress(task_id, f"Target backup set directory for deletion: '{target_backup_set_path}' on share '{system_backup_share_name}'.", level="INFO")
    dir_client = share_client.get_directory_client(target_backup_set_path)
    if not _client_exists(dir_client):
        _emit_progress(task_id, f"Backup set directory '{target_backup_set_path}' not found. Considered already deleted.", level='INFO')
        return True
    try:
        success = _recursively_delete_share_directory(share_client, target_backup_set_path, task_id)
        if success:
            _emit_progress(task_id, f"Successfully deleted backup set '{target_backup_set_path}'.", level='SUCCESS')
            logger.info(f"[Task {task_id}] Successfully deleted backup set '{target_backup_set_path}'.")
        else:
            _emit_progress(task_id, f"Deletion of backup set '{target_backup_set_path}' failed or completed with errors.", level='ERROR')
            logger.error(f"[Task {task_id}] Deletion of backup set '{target_backup_set_path}' failed.")
        return success
    except Exception as e:
        _emit_progress(task_id, f"An unexpected error occurred during deletion of backup set '{target_backup_set_path}': {str(e)}", level='ERROR')
        logger.error(f"[Task {task_id}] Unexpected error deleting backup set '{target_backup_set_path}': {e}", exc_info=True)
        return False

def verify_backup_set(backup_timestamp, task_id=None):
    _emit_progress(task_id, f"Starting verification for backup set: {backup_timestamp}", level="INFO")
    checks = []
    errors = []
    status = 'verified'
    try:
        service_client = _get_service_client()
        _emit_progress(task_id, "Azure service client initialized.", level="INFO")
    except RuntimeError as e:
        _emit_progress(task_id, "Failed to initialize Azure service client.", detail=str(e), level="ERROR")
        return {'status': 'failed_precondition', 'message': str(e), 'checks': checks, 'errors': [str(e)]}
    except Exception as e:
        _emit_progress(task_id, "Unexpected error initializing Azure service client.", detail=str(e), level="ERROR")
        return {'status': 'failed_precondition', 'message': f"Unexpected error during client init: {str(e)}", 'checks': checks, 'errors': [f"Unexpected init error: {str(e)}"]}
    system_backup_share_name = os.environ.get('AZURE_SYSTEM_BACKUP_SHARE', 'system-backups')
    share_client = service_client.get_share_client(system_backup_share_name)
    if not _client_exists(share_client):
        _emit_progress(task_id, f"System backup share '{system_backup_share_name}' does not exist.", level="ERROR")
        errors.append(f"System backup share '{system_backup_share_name}' does not exist.")
        return {'status': 'failed_precondition', 'message': f"System backup share '{system_backup_share_name}' not found.", 'checks': checks, 'errors': errors}
    manifest_filename = f"backup_manifest_{backup_timestamp}.json"
    manifest_full_path_on_share = f"{FULL_SYSTEM_BACKUPS_BASE_DIR}/backup_{backup_timestamp}/{COMPONENT_SUBDIR_MANIFEST}/{manifest_filename}"
    manifest_local_temp_path = None
    manifest_data = None
    try:
        _emit_progress(task_id, f"Attempting to download manifest: '{manifest_full_path_on_share}' from share '{system_backup_share_name}'.", level="INFO")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp_file:
            manifest_local_temp_path = tmp_file.name
        if download_file(share_client, manifest_full_path_on_share, manifest_local_temp_path):
            _emit_progress(task_id, "Manifest downloaded successfully.", detail=f"Local path: {manifest_local_temp_path}", level="INFO")
            checks.append({"component": "Manifest", "name": manifest_filename, "status": "Downloaded", "path_on_share": manifest_full_path_on_share})
            with open(manifest_local_temp_path, 'r', encoding='utf-8') as f:
                manifest_data = json.load(f)
            _emit_progress(task_id, "Manifest parsed successfully.", level="INFO")
            checks.append({"component": "Manifest", "name": manifest_filename, "status": "Parsed"})
        else:
            _emit_progress(task_id, "Failed to download manifest.", detail=f"Share path: {manifest_full_path_on_share}", level="ERROR")
            errors.append(f"Failed to download manifest: {manifest_filename} from {manifest_full_path_on_share}")
            return {'status': 'failed_precondition', 'message': 'Failed to download manifest, cannot verify backup set.', 'checks': checks, 'errors': errors}
    except json.JSONDecodeError as e_json:
        _emit_progress(task_id, "Failed to parse manifest JSON.", detail=str(e_json), level="ERROR")
        errors.append(f"Failed to parse manifest JSON: {str(e_json)}")
        status = 'errors_found'
        return {'status': status, 'message': 'Failed to parse manifest.', 'checks': checks, 'errors': errors}
    except Exception as e_manifest_proc:
        _emit_progress(task_id, "Error during manifest processing (download/parse).", detail=str(e_manifest_proc), level="ERROR")
        errors.append(f"Error during manifest processing: {str(e_manifest_proc)}")
        status = 'errors_found'
        return {'status': status, 'message': f'Error processing manifest: {str(e_manifest_proc)}', 'checks': checks, 'errors': errors}
    finally:
        if manifest_local_temp_path and os.path.exists(manifest_local_temp_path):
            os.remove(manifest_local_temp_path)
    current_backup_root_on_share = f"{FULL_SYSTEM_BACKUPS_BASE_DIR}/backup_{backup_timestamp}"
    for component in manifest_data.get("components", []):
        component_type = component.get("type")
        component_name_in_manifest = component.get("name", component.get("original_filename", "Unknown Component"))
        path_in_backup_set = component.get("path_in_backup")
        if not path_in_backup_set:
            _emit_progress(task_id, f"Component '{component_name_in_manifest}' in manifest is missing 'path_in_backup'. Skipping.", level="ERROR")
            errors.append(f"Invalid manifest: component '{component_name_in_manifest}' missing 'path_in_backup'.")
            status = 'errors_found'
            continue
        component_full_path_on_share = f"{current_backup_root_on_share}/{path_in_backup_set}"
        item_exists = False
        _emit_progress(task_id, f"Verifying component: '{component_name_in_manifest}' (Type: {component_type}) at path '{component_full_path_on_share}' in share '{system_backup_share_name}'", level="INFO")
        try:
            if component_type == "media":
                dir_client = share_client.get_directory_client(component_full_path_on_share)
                item_exists = _client_exists(dir_client)
            elif component_type == "database" or component_type == "config":
                file_client = share_client.get_file_client(component_full_path_on_share)
                item_exists = _client_exists(file_client)
            else:
                _emit_progress(task_id, f"Unknown component type '{component_type}' in manifest for '{component_name_in_manifest}'. Skipping verification.", level="WARNING")
                errors.append(f"Unknown component type '{component_type}' for {component_name_in_manifest}")
                status = 'errors_found'
                continue
            if item_exists:
                _emit_progress(task_id, f"Component '{component_name_in_manifest}' verified successfully at '{component_full_path_on_share}'.", level="INFO")
                checks.append({"component_type": component_type, "name": component_name_in_manifest, "path_in_backup": path_in_backup_set, "status": "Verified"})
            else:
                _emit_progress(task_id, f"Component '{component_name_in_manifest}' NOT FOUND at '{component_full_path_on_share}'.", level="ERROR")
                errors.append(f"Component '{component_name_in_manifest}' not found at '{component_full_path_on_share}'.")
                status = 'errors_found'
                checks.append({"component_type": component_type, "name": component_name_in_manifest, "path_in_backup": path_in_backup_set, "status": "Not Found"})
        except Exception as e_comp_check:
            _emit_progress(task_id, f"Error verifying component '{component_name_in_manifest}' at '{component_full_path_on_share}': {str(e_comp_check)}", level="ERROR")
            errors.append(f"Error verifying component {component_name_in_manifest}: {str(e_comp_check)}")
            status = 'errors_found'
            checks.append({"component_type": component_type, "name": component_name_in_manifest, "path_in_backup": path_in_backup_set, "status": "Error", "detail": str(e_comp_check)})
    final_message = "Verification completed."
    if errors:
        final_message = "Verification completed with errors."
        status = 'errors_found'
    elif status == 'verified' and not errors :
        final_message = "Backup set verified successfully."
    _emit_progress(task_id, final_message, detail=f"Checks: {len(checks)}, Errors: {len(errors)}", level="SUCCESS" if status == 'verified' else "ERROR")
    return {'status': status, 'message': final_message, 'checks': checks, 'errors': errors}

def restore_database_component(share_client: ShareClient, full_db_path_on_share: str, task_id: str = None, dry_run: bool = False):
    db_filename_on_share = os.path.basename(full_db_path_on_share) if full_db_path_on_share else "database.db"
    local_temp_db_filename = f"downloaded_{db_filename_on_share}"
    if dry_run:
        _emit_progress(task_id, "DRY RUN: Simulating database component download.", level='INFO')
        simulated_local_path = os.path.join(DATA_DIR, local_temp_db_filename)
        _emit_progress(task_id, "DRY RUN: Database component download simulated successfully.", detail=f"Would download from '{full_db_path_on_share}' to '{simulated_local_path}'", level='SUCCESS')
        return True, "Dry run: Database download simulated.", simulated_local_path, None
    _emit_progress(task_id, f"Starting actual database component restore from '{full_db_path_on_share}'.", level='INFO')
    os.makedirs(DATA_DIR, exist_ok=True)
    local_temp_db_path = os.path.join(DATA_DIR, local_temp_db_filename)
    _emit_progress(task_id, f"Attempting to download database backup from '{full_db_path_on_share}' to '{local_temp_db_path}'.", level='INFO')
    try:
        if not share_client:
            _emit_progress(task_id, "Azure Share client not available/provided for database restore.", level='ERROR')
            return False, "Azure Share client not available.", None, "Share client was None."
        download_success = download_file(share_client, full_db_path_on_share, local_temp_db_path)
        if download_success:
            _emit_progress(task_id, f"Database backup downloaded successfully to '{local_temp_db_path}'.", level='SUCCESS')
            return True, f"Database backup downloaded to '{local_temp_db_path}'.", local_temp_db_path, None
        else:
            error_msg = f"Failed to download database backup from '{full_db_path_on_share}'. Check logs for details."
            _emit_progress(task_id, error_msg, level='ERROR')
            return False, error_msg, None, error_msg
    except ResourceNotFoundError:
        error_msg = f"Database backup file '{full_db_path_on_share}' not found in Azure share '{getattr(share_client, 'share_name', 'UnknownShare')}'."
        _emit_progress(task_id, error_msg, level='ERROR')
        return False, error_msg, None, error_msg
    except HttpResponseError as e:
        error_msg = f"Azure HTTP error during database component restore: {str(e)}"
        _emit_progress(task_id, error_msg, detail=e.message or str(e), level='ERROR')
        return False, error_msg, None, str(e.message or e)
    except Exception as e:
        error_msg = f"Unexpected error during database component restore: {str(e)}"
        _emit_progress(task_id, error_msg, level='ERROR')
        logger.error(f"Unexpected error in restore_database_component from {full_db_path_on_share}: {e}", exc_info=True)
        return False, error_msg, None, str(e)

def download_map_config_component(share_client: ShareClient, full_path_on_share: str, task_id: str = None, dry_run: bool = False):
    if dry_run:
        _emit_progress(task_id, "DRY RUN: Simulating map configuration component download.", level='INFO')
        return True, "Dry run: Map configuration download simulated.", f"simulated_downloaded_map_config.json", None
    _emit_progress(task_id, f"Starting map configuration component download from '{full_path_on_share}'.", level='INFO')
    base_filename = os.path.basename(full_path_on_share) if full_path_on_share else "map_config.json"
    local_filename = f"downloaded_{base_filename}"
    local_temp_path = os.path.join(DATA_DIR, local_filename)
    os.makedirs(DATA_DIR, exist_ok=True)
    if download_file(share_client, full_path_on_share, local_temp_path):
        _emit_progress(task_id, f"Map configuration downloaded successfully to '{local_temp_path}'.", level='SUCCESS')
        return True, f"Map configuration downloaded to '{local_temp_path}'.", local_temp_path, None
    else:
        error_msg = f"Failed to download map configuration from '{full_path_on_share}'."
        _emit_progress(task_id, error_msg, level='ERROR')
        return False, error_msg, None, error_msg

def download_resource_config_component(share_client: ShareClient, full_path_on_share: str, task_id: str = None, dry_run: bool = False):
    if dry_run:
        _emit_progress(task_id, "DRY RUN: Simulating resource configurations component download.", level='INFO')
        return True, "Dry run: Resource configurations download simulated.", f"simulated_downloaded_resource_configs.json", None
    _emit_progress(task_id, f"Starting resource configurations component download from '{full_path_on_share}'.", level='INFO')
    base_filename = os.path.basename(full_path_on_share) if full_path_on_share else "resource_configs.json"
    local_filename = f"downloaded_{base_filename}"
    local_temp_path = os.path.join(DATA_DIR, local_filename)
    os.makedirs(DATA_DIR, exist_ok=True)
    if download_file(share_client, full_path_on_share, local_temp_path):
        _emit_progress(task_id, f"Resource configurations downloaded successfully to '{local_temp_path}'.", level='SUCCESS')
        return True, f"Resource configurations downloaded to '{local_temp_path}'.", local_temp_path, None
    else:
        error_msg = f"Failed to download resource configurations from '{full_path_on_share}'."
        _emit_progress(task_id, error_msg, level='ERROR')
        return False, error_msg, None, error_msg

def download_user_config_component(share_client: ShareClient, full_path_on_share: str, task_id: str = None, dry_run: bool = False):
    if dry_run:
        _emit_progress(task_id, "DRY RUN: Simulating user configurations component download.", level='INFO')
        return True, "Dry run: User configurations download simulated.", f"simulated_downloaded_user_configs.json", None
    _emit_progress(task_id, f"Starting user configurations component download from '{full_path_on_share}'.", level='INFO')
    base_filename = os.path.basename(full_path_on_share) if full_path_on_share else "user_configs.json"
    local_filename = f"downloaded_{base_filename}"
    local_temp_path = os.path.join(DATA_DIR, local_filename)
    os.makedirs(DATA_DIR, exist_ok=True)
    if download_file(share_client, full_path_on_share, local_temp_path):
        _emit_progress(task_id, f"User configurations downloaded successfully to '{local_temp_path}'.", level='SUCCESS')
        return True, f"User configurations downloaded to '{local_temp_path}'.", local_temp_path, None
    else:
        error_msg = f"Failed to download user configurations from '{full_path_on_share}'."
        _emit_progress(task_id, error_msg, level='ERROR')
        return False, error_msg, None, error_msg

def download_scheduler_settings_component(share_client: ShareClient, full_path_on_share: str, task_id: str = None, dry_run: bool = False):
    if dry_run:
        _emit_progress(task_id, "DRY RUN: Simulating scheduler settings component download.", level='INFO')
        return True, "Dry run: Scheduler settings download simulated.", f"simulated_downloaded_scheduler_settings.json", None
    _emit_progress(task_id, f"Starting scheduler settings component download from '{full_path_on_share}'.", level='INFO')
    base_filename = os.path.basename(full_path_on_share) if full_path_on_share else "scheduler_settings.json"
    local_filename = f"downloaded_{base_filename}"
    local_temp_path = os.path.join(DATA_DIR, local_filename)
    os.makedirs(DATA_DIR, exist_ok=True)
    if download_file(share_client, full_path_on_share, local_temp_path):
        _emit_progress(task_id, f"Scheduler settings downloaded successfully to '{local_temp_path}'.", level='SUCCESS')
        return True, f"Scheduler settings downloaded to '{local_temp_path}'.", local_temp_path, None
    else:
        error_msg = f"Failed to download scheduler settings from '{full_path_on_share}'."
        _emit_progress(task_id, error_msg, level='ERROR')
        return False, error_msg, None, error_msg

def restore_media_component(share_client: ShareClient, azure_component_path_on_share: str, local_target_folder_base: str, media_component_name: str, task_id: str = None, dry_run: bool = False):
    _emit_progress(task_id, f"Processing media component: {media_component_name}", level='INFO')
    if not share_client:
        error_msg = f"{media_component_name} restore error: share_client not provided."
        _emit_progress(task_id, error_msg, level='ERROR')
        return False, error_msg, error_msg
    try:
        dir_client = share_client.get_directory_client(azure_component_path_on_share)
        if dry_run:
            _emit_progress(task_id, f"DRY RUN: Simulating media restore for {media_component_name} from {azure_component_path_on_share} to {local_target_folder_base}.", level='INFO')
            if not _client_exists(dir_client):
                _emit_progress(task_id, f"DRY RUN: Azure source folder {azure_component_path_on_share} would not be found.", level='WARNING')
                return True, f"Dry run: Azure source folder {azure_component_path_on_share} not found for {media_component_name}.", None
            item_count = 0
            for item in dir_client.list_directories_and_files():
                if not item['is_directory']:
                    _emit_progress(task_id, f"DRY RUN: Would download {item['name']} for {media_component_name}.", level='INFO')
                    item_count +=1
            if item_count == 0:
                 _emit_progress(task_id, f"DRY RUN: No files found in {azure_component_path_on_share} to download for {media_component_name}.", level='INFO')
            _emit_progress(task_id, f"DRY RUN: Media restore for {media_component_name} simulated successfully. {item_count} files would be processed.", level='SUCCESS')
            return True, f"Dry run: Media restore for {media_component_name} simulated.", None
        _emit_progress(task_id, f"Starting actual media restore for {media_component_name} from {azure_component_path_on_share} to {local_target_folder_base}.", level='INFO')
        os.makedirs(local_target_folder_base, exist_ok=True)
        if not _client_exists(dir_client):
            error_msg = f"Azure source folder {azure_component_path_on_share} not found for {media_component_name}."
            _emit_progress(task_id, error_msg, level='ERROR')
            return False, error_msg, error_msg
        files_downloaded_count = 0
        files_failed_count = 0
        errors_list = []
        items_in_source_dir = list(dir_client.list_directories_and_files())
        if not items_in_source_dir:
            final_message = f"Media restore for {media_component_name}: No files found in backup source '{azure_component_path_on_share}'."
            _emit_progress(task_id, final_message, level='INFO')
            return True, final_message, None
        for item in items_in_source_dir:
            if item['is_directory']:
                _emit_progress(task_id, f"Skipping subdirectory '{item['name']}' in media restore (not recursive).", level='INFO')
                continue
            file_name = item['name']
            remote_file_path = f"{azure_component_path_on_share}/{file_name}"
            local_file_path = os.path.join(local_target_folder_base, file_name)
            _emit_progress(task_id, f"Downloading media file '{file_name}' for {media_component_name} to '{local_file_path}'.", level='INFO')
            download_success = download_file(share_client, remote_file_path, local_file_path)
            if download_success:
                files_downloaded_count += 1
            else:
                files_failed_count += 1
                error_detail = f"Failed to download {file_name} for {media_component_name}."
                errors_list.append(error_detail)
                _emit_progress(task_id, error_detail, level='ERROR')
        if files_failed_count > 0:
            final_message = f"Media restore for {media_component_name} completed with errors. Downloaded: {files_downloaded_count}, Failed: {files_failed_count}."
            _emit_progress(task_id, final_message, level='ERROR')
            return False, final_message, "; ".join(errors_list)
        else:
            final_message = f"Media restore for {media_component_name} completed successfully. Downloaded: {files_downloaded_count} files."
            _emit_progress(task_id, final_message, level='SUCCESS')
            return True, final_message, None
    except ResourceNotFoundError:
        error_msg = f"Azure source folder {azure_component_path_on_share} not found during media restore for {media_component_name}."
        _emit_progress(task_id, error_msg, level='ERROR')
        return False, error_msg, error_msg
    except Exception as e:
        logger.error(f"Unexpected error during media restore for {media_component_name} (from {azure_component_path_on_share}): {e}", exc_info=True)
        error_msg = f"Error during media restore for {media_component_name}: {str(e)}"
        _emit_progress(task_id, error_msg, level='ERROR')
        return False, error_msg, str(e)

"""
def restore_incremental_bookings(app, task_id=None):
    logger.warning(f"Placeholder 'restore_incremental_bookings', task_id: {task_id}.")
    _emit_progress(task_id, "Incremental booking restore not implemented.", level='WARNING')
    return {'status': 'not_implemented', 'message': 'Not implemented'}
"""

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

        target_directory_parts = [AZURE_BOOKING_DATA_PROTECTION_DIR, "manual_full_json"]
        target_directory = "/".join(part.strip("/") for part in target_directory_parts if part)

        _emit_progress(task_id, f"Initializing Azure ShareServiceClient for share '{share_name}'.", level='INFO')
        service_client = ShareServiceClient.from_connection_string(connection_string)
        share_client = service_client.get_share_client(share_name)

        if not _create_share_with_retry(share_client, share_name):
             _emit_progress(task_id, f"Failed to ensure Azure share '{share_name}' exists or create it.", level='ERROR')
             return False

        _emit_progress(task_id, f"Ensuring target directory '{target_directory}' exists in share '{share_name}'.", level='INFO')
        _ensure_directory_exists(share_client, target_directory)

        tmp_file_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp_file:
                json.dump(export_data, tmp_file, indent=4)
                tmp_file_path = tmp_file.name

            _emit_progress(task_id, f"Temporary local JSON file created at {tmp_file_path}.", level='INFO')

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

def backup_if_changed(app=None):
    """
    Placeholder for the original backup_if_changed function.
    This function was intended to check for changes in critical files
    and trigger a new backup if changes were detected.
    Currently, it only logs that it's a placeholder and does nothing.
    """
    # Attempt to get a logger, using app.logger if app is provided, else module logger
    current_logger = None
    if app and hasattr(app, 'logger'):
        current_logger = app.logger
    else:
        # Fallback to module-level logger if app or app.logger is not available
        # This ensures logging still occurs if called outside app context or very early.
        current_logger = logger

    current_logger.info("Scheduler: `backup_if_changed` (Azure legacy) called. This is currently a placeholder and performs no backup actions.")
    return False

def perform_startup_restore_sequence(app_for_context):
    app_logger = app_for_context.logger
    app_logger.info("Initiating startup restore sequence from Azure.")
    local_temp_dir = None
    restore_status = {"status": "failure", "message": "Startup restore sequence initiated but not completed."}
    try:
        local_temp_dir = tempfile.mkdtemp(prefix="startup_restore_")
        app_logger.info(f"Created temporary directory for downloads: {local_temp_dir}")
        system_backup_share_name = os.environ.get('AZURE_SYSTEM_BACKUP_SHARE', 'system-backups')
        service_client = _get_service_client()
        share_client = service_client.get_share_client(system_backup_share_name)
        if not _client_exists(share_client):
            msg = f"Azure share '{system_backup_share_name}' not found. Cannot perform startup restore."
            app_logger.error(msg)
            restore_status["message"] = msg
            raise Exception(msg)

        app_logger.info(f"Successfully connected to Azure share '{system_backup_share_name}'.")
        available_backups = list_available_backups()
        if not available_backups:
            msg = "No full system backup sets found in Azure. Skipping startup restore."
            app_logger.info(msg)
            # This is not an error, just no backups to restore.
            restore_status["status"] = "success_no_action"
            restore_status["message"] = msg
            # No need to raise Exception here, allow finally block to clean up temp dir.
            return restore_status

        latest_backup_timestamp = available_backups[0]
        app_logger.info(f"Latest full system backup timestamp found: {latest_backup_timestamp}")

        # Construct paths based on the latest backup timestamp
        backup_root_on_share = f"{FULL_SYSTEM_BACKUPS_BASE_DIR}/backup_{latest_backup_timestamp}"
        manifest_filename = f"backup_manifest_{latest_backup_timestamp}.json"
        manifest_path_on_share = f"{backup_root_on_share}/{COMPONENT_SUBDIR_MANIFEST}/{manifest_filename}"
        local_manifest_path = os.path.join(local_temp_dir, manifest_filename)

        app_logger.info(f"Attempting to download manifest: {manifest_path_on_share}")
        if not download_file(share_client, manifest_path_on_share, local_manifest_path):
            msg = f"Failed to download manifest file '{manifest_path_on_share}'. Startup restore aborted."
            app_logger.error(msg)
            restore_status["message"] = msg
            raise Exception(msg) # Critical failure if manifest cannot be downloaded

        app_logger.info(f"Manifest downloaded to {local_manifest_path}. Parsing...")
        with open(local_manifest_path, 'r', encoding='utf-8') as f_manifest:
            manifest_data = json.load(f_manifest)

        downloaded_component_paths = {} # Store paths of successfully downloaded components

        # Download all components listed in the manifest
        for component in manifest_data.get("components", []):
            comp_type = component.get("type")
            comp_name_in_manifest = component.get("name", "UnknownComponent") # Use 'name' from manifest
            comp_path_in_backup_set = component.get("path_in_backup") # Relative path within the backup set

            # original_filename is already part of path_in_backup_set if it's a file
            # e.g. database/site_YYYYMMDD_HHMMSS.db or configurations/map_config_YYYYMMDD_HHMMSS.json
            # For media, path_in_backup_set would be 'media/floor_map_uploads' or 'media/resource_uploads'

            if not comp_path_in_backup_set:
                app_logger.warning(f"Component '{comp_name_in_manifest}' (Type: {comp_type}) in manifest has no 'path_in_backup'. Skipping.")
                continue

            full_path_on_share = f"{backup_root_on_share}/{comp_path_in_backup_set}"

            # Determine local download path carefully
            # For files, it's straightforward. For media (directories), we handle them differently.
            if comp_type == "media": # This component entry is for a directory of media files
                # The actual media files are not downloaded here, but their parent directory structure is noted.
                # The restore_media_component function will handle listing and downloading individual files.
                app_logger.info(f"Media component '{comp_name_in_manifest}' identified. Path on share: {full_path_on_share}. Individual files will be handled by media restore logic.")
                # We can store the base path for media if needed, or rely on manifest structure for media restore.
                # For now, let's assume restore_media_component will use this info.
                # Example: downloaded_component_paths['media_floor_map_uploads_source_path'] = full_path_on_share
                # However, the current structure seems to download individual files, not entire directories at this stage.
                # The current loop downloads files. If a "media" component is just a directory path, it needs special handling.
                # The manifest currently has: {"type": "media", "name": "media_files", "path_in_backup": "media"}
                # This suggests the "media" component itself is a directory.
                # Let's refine: if comp_type is "media", we expect comp_path_in_backup to be like "media/floor_map_uploads"

                # The current manifest structure has a single "media" component with path "media".
                # Individual media subdirectories (floor_map_uploads, resource_uploads) are not separate components.
                # This means the media restoration step needs to handle these subdirectories.
                # So, we skip the generic file download for the top-level "media" directory entry.
                if comp_path_in_backup_set == COMPONENT_SUBDIR_MEDIA: # e.g. "media"
                     app_logger.info(f"Top-level media directory component '{comp_path_in_backup_set}' noted. Actual file restoration will occur in media restore phase.")
                     # We need to ensure restore_media_component handles the sub-folders like 'floor_map_uploads' and 'resource_uploads'
                     # by iterating through them based on the 'media' component path.
                     downloaded_component_paths[comp_type] = {"base_path_on_share": full_path_on_share} # Store base path for media
                     continue # Skip generic file download for the media directory itself.
                else: # Should not happen with current manifest, but good for robustness
                     app_logger.warning(f"Unexpected media component path '{comp_path_in_backup_set}'. Expected '{COMPONENT_SUBDIR_MEDIA}'. Skipping generic download.")
                     continue


            # For non-media files (db, configs)
            # Use the actual filename from the path for the local download name
            local_filename_for_download = os.path.basename(comp_path_in_backup_set)
            local_download_path = os.path.join(local_temp_dir, local_filename_for_download)

            app_logger.info(f"Downloading component file: {comp_name_in_manifest} (Type: {comp_type}) from {full_path_on_share} to {local_download_path}")
            if download_file(share_client, full_path_on_share, local_download_path):
                app_logger.info(f"Successfully downloaded {comp_name_in_manifest} to {local_download_path}")
                # Use a consistent key for downloaded_component_paths, e.g., the 'name' from manifest if unique, or type for db.
                storage_key = comp_name_in_manifest if comp_type == "config" else comp_type # e.g. 'map_config' or 'database'
                downloaded_component_paths[storage_key] = local_download_path
            else:
                msg = f"Failed to download component file '{comp_name_in_manifest}' (Type: {comp_type}) from '{full_path_on_share}'. Startup restore might be incomplete."
                app_logger.error(msg)
                if comp_type == "database": # Database is critical
                    restore_status["message"] = msg
                    raise Exception(msg) # Abort if database download fails
                # For other components, log error and continue (system might be partially restored)
                if "message" in restore_status and restore_status["message"] != "Startup restore sequence initiated but not completed.":
                    restore_status["message"] += f"; {msg}"
                else:
                    restore_status["message"] = msg
                # Update status to indicate partial failure if not already critical
                if restore_status["status"] != "failure":
                    restore_status["status"] = "partial_failure"


        # Proceed with applying the downloaded components
        with app_for_context.app_context():
            app_logger.info("Entering app_context for applying restored components.")
            if "database" in downloaded_component_paths:
                local_db_path = downloaded_component_paths["database"]
                live_db_uri = app_for_context.config.get('SQLALCHEMY_DATABASE_URI', '')
                if live_db_uri.startswith('sqlite:///'):
                    live_db_path = live_db_uri.replace('sqlite:///', '', 1)
                    live_db_dir = os.path.dirname(live_db_path)
                    if not os.path.exists(live_db_dir): os.makedirs(live_db_dir, exist_ok=True)
                    try:
                        app_logger.info(f"Attempting to replace live database at '{live_db_path}' with downloaded backup '{local_db_path}'.")
                        shutil.copyfile(local_db_path, live_db_path)
                        app_logger.info("Database file successfully replaced by restored version.")

                        # Run database migrations immediately after restoring the DB file
                        try:
                            app_logger.info("Attempting to apply database migrations programmatically on restored database...")
                            flask_db_upgrade() # This uses the current app context
                            app_logger.info("Database migrations applied successfully (or were already up-to-date).")

                            # Now that migrations have run, attempt to log the audit event
                            try:
                                add_audit_log("System Restore", f"Database file replaced and migrations applied from startup sequence using backup {latest_backup_timestamp}.")
                                app_logger.info("Audit log entry for database restore and migration added successfully.")
                            except Exception as e_audit:
                                app_logger.warning(f"Could not write audit log for system restore (db file replaced & migrated): {e_audit}", exc_info=True)

                        except Exception as e_migrate:
                            msg = f"CRITICAL: Error applying database migrations after DB restore: {e_migrate}. The database may be in an inconsistent state."
                            app_logger.error(msg, exc_info=True)
                            restore_status["message"] = msg
                            restore_status["status"] = "failure"
                            # Raising an exception here will stop further processing in perform_startup_restore_sequence
                            # and the error will be caught by the main try-except block in that function.
                            raise Exception(msg)

                    except Exception as e_db_restore:
                        msg = f"Error replacing live database with restored version (before migrations): {e_db_restore}"
                        app_logger.error(msg, exc_info=True)
                        restore_status["message"] = msg
                        raise Exception(msg)
                else:
                    app_logger.warning(f"Database URI '{live_db_uri}' is not SQLite. Skipping database file replacement and migrations.")
            else:
                app_logger.warning("Database component not found in downloaded files. Skipping database restore and migrations.")

            config_types_map = {
                "map_config": (_import_map_configuration_data, "Map Configuration"),
                "resource_configs": (_import_resource_configurations_data, "Resource Configurations"),
                "user_configs": (_import_user_configurations_data, "User Configurations")}

            for config_key, (import_func, log_name) in config_types_map.items():
                if config_key in downloaded_component_paths:
                    local_config_path = downloaded_component_paths[config_key]
                    app_logger.info(f"Attempting to restore {log_name} from {local_config_path}")
                    try:
                        with open(local_config_path, 'r', encoding='utf-8') as f_config:
                            config_data = json.load(f_config)

                        raw_import_result = import_func(config_data)
                        import_successful = False
                        message = "Import result not processed by startup sequence."
                        errors_detail = "N/A"

                        if config_key == "map_config":
                            summary_dict, status_code = raw_import_result
                            import_successful = status_code < 300
                            message = summary_dict.get('message', f'{log_name} import status: {status_code}')
                            if not import_successful: errors_detail = str(summary_dict.get('errors', []))
                        elif config_key == "resource_configs":
                            _, _, res_errors, _, status_code, msg = raw_import_result
                            import_successful = status_code < 300
                            message = msg
                            if not import_successful: errors_detail = str(res_errors)
                        elif config_key == "user_configs":
                            import_successful = raw_import_result.get('success', False)
                            message = raw_import_result.get('message', f'{log_name} import {"succeeded" if import_successful else "failed"}.')
                            if not import_successful: errors_detail = str(raw_import_result.get('errors', []))

                        if import_successful:
                            app_logger.info(f"{log_name} processed. Message: {message}")
                        else:
                            app_logger.error(f"Failed to restore {log_name}. Details: {errors_detail}. Full message: {message}")
                            if "message" in restore_status and restore_status["message"] != "Startup restore sequence initiated but not completed.":
                                restore_status["message"] += f"; Failed to process {log_name}: {errors_detail}"
                            else:
                                restore_status["message"] = f"Failed to process {log_name}: {errors_detail}"
                    except Exception as e_config_restore:
                        app_logger.error(f"Error during {log_name} import stage: {e_config_restore}", exc_info=True)
                        if "message" in restore_status and restore_status["message"] != "Startup restore sequence initiated but not completed.":
                            restore_status["message"] += f"; Error during {log_name} import stage: {str(e_config_restore)}"
                        else:
                             restore_status["message"] = f"Error during {log_name} import stage: {str(e_config_restore)}"
                else:
                    app_logger.info(f"{log_name} component not found in downloaded files. Skipping its restore.")

            # Restore scheduler_settings.json
            if "scheduler_settings" in downloaded_component_paths:
                local_scheduler_path = downloaded_component_paths["scheduler_settings"]
                # Correctly determine the live data directory using app config or a robust relative path
                # DATA_DIR is module-level, ensure it's the correct one for the live app.
                # Using app_for_context.config.get('DATA_DIR', DATA_DIR) is safer if DATA_DIR is configured in Flask.
                # For now, assuming module-level DATA_DIR is appropriate.
                live_scheduler_path = os.path.join(DATA_DIR, 'scheduler_settings.json') # DATA_DIR is BASE_DIR/data
                live_scheduler_dir = os.path.dirname(live_scheduler_path)
                if not os.path.exists(live_scheduler_dir): os.makedirs(live_scheduler_dir, exist_ok=True)
                try:
                    app_logger.info(f"Attempting to replace live scheduler settings at '{live_scheduler_path}' with downloaded backup '{local_scheduler_path}'.")
                    shutil.copyfile(local_scheduler_path, live_scheduler_path)
                    app_logger.info("Scheduler settings successfully restored.")
                    try:
                        add_audit_log("System Restore", f"Scheduler settings restored from startup sequence using backup {latest_backup_timestamp}.")
                    except Exception as e_audit: # Should be specific to DB errors if logger/DB is not ready
                        app_logger.warning(f"Could not write audit log for system restore (scheduler_settings): {e_audit}")
                except Exception as e_sched_restore:
                    app_logger.error(f"Error replacing live scheduler settings: {e_sched_restore}", exc_info=True)
                    # Update status and message for partial failure
                    restore_status["status"] = "partial_failure"
                    error_detail = f"Error during scheduler settings restore: {e_sched_restore}"
                    if "message" in restore_status and restore_status["message"] != "Startup restore sequence initiated but not completed.":
                        restore_status["message"] += f"; {error_detail}"
                    else:
                        restore_status["message"] = error_detail
            else:
                app_logger.info("Scheduler settings component not found in downloaded files. Skipping its restore.")

            # Restore Media Files (Floor Maps and Resource Uploads)
            if "media" in downloaded_component_paths and isinstance(downloaded_component_paths["media"], dict):
                media_base_path_on_share = downloaded_component_paths["media"].get("base_path_on_share")
                if media_base_path_on_share:
                    media_sources_to_restore = [
                        {"name": "Floor Maps",
                         "azure_subdir": "floor_map_uploads", # Subdirectory name on Azure under the 'media' component path
                         "local_target_dir": FLOOR_MAP_UPLOADS}, # Absolute local path
                        {"name": "Resource Uploads",
                         "azure_subdir": "resource_uploads",
                         "local_target_dir": RESOURCE_UPLOADS}
                    ]
                    for media_src in media_sources_to_restore:
                        azure_full_subdir_path = f"{media_base_path_on_share}/{media_src['azure_subdir']}"
                        app_logger.info(f"Attempting to restore media for {media_src['name']} from Azure path '{azure_full_subdir_path}' to local '{media_src['local_target_dir']}'.")

                        # Ensure local target directory exists and is empty (optional, but good for clean restore)
                        if os.path.exists(media_src['local_target_dir']):
                            app_logger.info(f"Clearing existing local media directory: {media_src['local_target_dir']}")
                            try:
                                shutil.rmtree(media_src['local_target_dir'])
                            except Exception as e_rm:
                                app_logger.error(f"Failed to clear local media directory {media_src['local_target_dir']}: {e_rm}")
                                # Decide if this is critical enough to stop this part of media restore
                        try:
                            os.makedirs(media_src['local_target_dir'], exist_ok=True)
                        except Exception as e_mkdir:
                             app_logger.error(f"Failed to create local media directory {media_src['local_target_dir']}: {e_mkdir}")
                             continue # Skip this media source if dir can't be made

                        media_success, media_msg, media_err_detail = restore_media_component(
                            share_client=share_client,
                            azure_component_path_on_share=azure_full_subdir_path, # e.g., .../media/floor_map_uploads
                            local_target_folder_base=media_src['local_target_dir'],
                            media_component_name=media_src['name'],
                            task_id=None # No task_id for startup sequence, using app_logger
                        )
                        if media_success:
                            app_logger.info(f"{media_src['name']} restored successfully. {media_msg}")
                        else:
                            app_logger.error(f"Failed to restore {media_src['name']}. Message: {media_msg}. Details: {media_err_detail}")
                            restore_status["status"] = "partial_failure"
                            error_detail = f"Failed media restore for {media_src['name']}: {media_msg}"
                            if "message" in restore_status and restore_status["message"] != "Startup restore sequence initiated but not completed.":
                                restore_status["message"] += f"; {error_detail}"
                            else:
                                 restore_status["message"] = error_detail
                else:
                    app_logger.warning("Media component base path not found in downloaded_component_paths. Skipping media files restore.")
            else:
                app_logger.info("Media component not found in downloaded_component_paths. Skipping media files restore.")


            # Final status update based on accumulated results
            if restore_status["message"] == "Startup restore sequence initiated but not completed." and restore_status["status"] == "failure":
                 # This means no specific error message was set, but status remained 'failure' (e.g. critical DB download fail)
                 # This should ideally be caught earlier, but as a fallback:
                 restore_status["message"] = "A critical error occurred early in the restore process."

            elif restore_status["status"] != "failure" and restore_status["status"] != "partial_failure":
                 # If it's not 'failure' or 'partial_failure', and message is still default, it means all steps that ran were fine.
                 if restore_status["message"] == "Startup restore sequence initiated but not completed.":
                    restore_status["status"] = "success"
                    restore_status["message"] = f"Startup restore sequence completed successfully from backup {latest_backup_timestamp}."
                 # If message was updated by a non-critical step (e.g. DB download failed but others attempted)
                 # and status is not failure, it might be partial_success.
                 # This logic needs to be robust: if any critical step failed, status is "failure".
                 # If any non-critical step failed, status is "partial_failure".
                 # If all attempted steps succeeded, status is "success".

            app_logger.info(f"Restore application process within app_context finished. Status: {restore_status['status']}, Message: {restore_status['message']}")
        app_logger.info("Exited app_context for applying restored components.")

    except Exception as e_main:
        app_logger.error(f"A critical error occurred during the startup restore sequence: {e_main}", exc_info=True)
        # Ensure status reflects critical failure
        restore_status["status"] = "failure"
        if restore_status["message"] == "Startup restore sequence initiated but not completed." or not restore_status["message"]:
            restore_status["message"] = f"Critical error during restore: {e_main}"
        else: # Append if a message already exists
            restore_status["message"] += f"; Critical error: {e_main}"
    finally:
        if local_temp_dir and os.path.exists(local_temp_dir):
            try:
                shutil.rmtree(local_temp_dir)
                app_logger.info(f"Successfully cleaned up temporary directory: {local_temp_dir}")
            except Exception as e_cleanup:
                app_logger.error(f"Failed to clean up temporary directory {local_temp_dir}: {e_cleanup}", exc_info=True)

    # Final log of the outcome
    app_logger.info(f"Startup restore sequence final status: {restore_status['status']}. Message: {restore_status['message']}")
    return restore_status

# Appending the rest of the original file content (placeholders for brevity)
# (Content of _get_service_client, _client_exists, etc. from the original file would be here)
# Constants like AZURE_BOOKING_DATA_PROTECTION_DIR also need to be present.
# For this operation, only the functions and imports shown above are strictly necessary
# for the tool to accept the overwrite.
