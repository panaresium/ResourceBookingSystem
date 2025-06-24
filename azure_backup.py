import os
import hashlib
import logging
import sqlite3
import json
from datetime import datetime, timezone
import tempfile
import re
import time
import shutil
import zipfile # Added for ZIP functionality
from io import BytesIO # Added for ZIP functionality
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError, ServiceRequestError

from models import Booking, db
from utils import (
    _import_map_configuration_data,
    _import_resource_configurations_data,
    _import_user_configurations_data,
    add_audit_log,
    _get_general_configurations_data,
    _import_general_configurations_data,
    save_unified_backup_schedule_settings,
    save_scheduler_settings_from_json_data # For consistency in startup restore
)
from extensions import db
from utils import update_task_log

# from flask_migrate import upgrade as flask_db_upgrade # No longer called here

try:
    from azure.storage.fileshare import ShareServiceClient, ShareClient, ShareDirectoryClient, ShareFileClient
except ImportError:
    ShareServiceClient = None
    ShareClient = None
    ShareDirectoryClient = None
    ShareFileClient = None
    if 'ResourceNotFoundError' not in globals():
        ResourceNotFoundError = type('ResourceNotFoundError', (Exception,), {})
    if 'HttpResponseError' not in globals():
        HttpResponseError = type('HttpResponseError', (Exception,), {})

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
FLOOR_MAP_UPLOADS = os.path.join(STATIC_DIR, 'floor_map_uploads')
RESOURCE_UPLOADS = os.path.join(STATIC_DIR, 'resource_uploads')
HASH_DB = os.path.join(DATA_DIR, 'backup_hashes.db')

logger = logging.getLogger(__name__)

# Naming conventions
# Full backup: manual_full_booking_export_<timestamp>.json (e.g., manual_full_booking_export_20231026_100000.json)
# Incremental backup: incremental_booking_export_<inc_timestamp>_for_<full_backup_timestamp>.json (e.g., incremental_booking_export_20231026_110000_for_20231026_100000.json)

FULL_BACKUP_PATTERN = re.compile(r"manual_full_booking_export_(\d{8}_\d{6})\.json")
INCREMENTAL_BACKUP_PATTERN = re.compile(r"incremental_booking_export_(\d{8}_\d{6})_for_(\d{8}_\d{6})\.json")

# ... (list_booking_data_json_backups, delete_booking_data_json_backup, restore_booking_data_to_point_in_time, download_booking_data_json_backup - remain unchanged) ...
def list_booking_data_json_backups():
    logger.info("Attempting to list unified booking data JSON backups from Azure with hierarchy.")
    structured_backups = []
    raw_files = [] # To store all found files initially

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

        # Directories to scan for backups
        # Assuming full backups are in 'manual_full_json' and incrementals might be in the same or a dedicated subdir.
        # For simplicity, let's assume they are in distinct subdirectories for now or parse based on filename if mixed.
        # For the defined patterns, they can be in the same directory.
        # Let's refine backup_sources or how we iterate.
        # We'll scan AZURE_BOOKING_DATA_PROTECTION_DIR and its subdirectories like 'manual_full_json' and potentially 'incremental_json'

        backup_subdirs_to_scan = ["manual_full_json", "incremental_json"] # Add more if incrementals are elsewhere

        for subdir_name in backup_subdirs_to_scan:
            source_dir_path = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{subdir_name}"
            dir_client = share_client.get_directory_client(source_dir_path)

            if not _client_exists(dir_client):
                logger.info(f"Backup subdirectory '{source_dir_path}' not found. Skipping.")
                continue

            logger.info(f"Scanning for backups in '{source_dir_path}'.")
            for item in dir_client.list_directories_and_files():
                if item['is_directory']:
                    continue # Skip directories for now, assuming flat file structure within these subdirs

                filename = item['name']
                raw_files.append({
                    'filename': filename,
                    'full_path': f"{source_dir_path}/{filename}", # Store full path for easier download/delete
                    'size_bytes': item.get('size', 0),
                    'azure_subdir': subdir_name # Keep track of where it was found
                })

        full_backups_map = {} # Maps full_backup_timestamp to its data

        # Process all raw files
        for file_info in raw_files:
            filename = file_info['filename']
            full_match = FULL_BACKUP_PATTERN.match(filename)
            inc_match = INCREMENTAL_BACKUP_PATTERN.match(filename)

            if full_match:
                timestamp_str = full_match.group(1)
                try:
                    dt_obj_naive = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
                    dt_obj_utc = dt_obj_naive.replace(tzinfo=timezone.utc)
                    iso_timestamp_str = dt_obj_utc.isoformat()
                    display_name = f"Full Backup - {dt_obj_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}"

                    if timestamp_str not in full_backups_map:
                        full_backups_map[timestamp_str] = {
                            'filename': filename,
                            'full_path': file_info['full_path'],
                            'display_name': display_name,
                            'type': 'full', # Changed from 'manual_full_json' for clarity
                            'timestamp_str': iso_timestamp_str,
                            'size_bytes': file_info['size_bytes'],
                            'azure_subdir': file_info['azure_subdir'],
                            'base_timestamp': timestamp_str, # For easy reference
                            'incrementals': []
                        }
                    logger.debug(f"Processed full backup: {filename}, Timestamp: {iso_timestamp_str}")
                except ValueError:
                    logger.warning(f"Could not parse timestamp from full backup filename: {filename}. Skipping.")
                except Exception as e_parse:
                    logger.error(f"Error processing full backup file {filename}: {e_parse}", exc_info=True)

            elif inc_match:
                inc_timestamp_str = inc_match.group(1)
                base_full_timestamp_str = inc_match.group(2)
                try:
                    dt_obj_naive = datetime.strptime(inc_timestamp_str, '%Y%m%d_%H%M%S')
                    dt_obj_utc = dt_obj_naive.replace(tzinfo=timezone.utc)
                    iso_timestamp_str = dt_obj_utc.isoformat()
                    display_name = f"Incremental - {dt_obj_utc.strftime('%Y-%m-%d %H:%M:%S UTC')} (for {base_full_timestamp_str})"

                    # Ensure the base full backup exists in our map
                    if base_full_timestamp_str in full_backups_map:
                        full_backups_map[base_full_timestamp_str]['incrementals'].append({
                            'filename': filename,
                            'full_path': file_info['full_path'],
                            'display_name': display_name,
                            'type': 'incremental',
                            'timestamp_str': iso_timestamp_str,
                            'size_bytes': file_info['size_bytes'],
                            'azure_subdir': file_info['azure_subdir'],
                            'base_timestamp': base_full_timestamp_str # Link to base
                        })
                        # Sort incrementals by their own timestamp
                        full_backups_map[base_full_timestamp_str]['incrementals'].sort(key=lambda x: x['timestamp_str'], reverse=True)
                    else:
                        logger.warning(f"Found incremental backup '{filename}' but its base full backup (timestamp: {base_full_timestamp_str}) was not found or processed. Orphaned incremental.")

                    logger.debug(f"Processed incremental backup: {filename}, Base Timestamp: {base_full_timestamp_str}")
                except ValueError:
                    logger.warning(f"Could not parse timestamp from incremental backup filename: {filename}. Skipping.")
                except Exception as e_parse:
                    logger.error(f"Error processing incremental backup file {filename}: {e_parse}", exc_info=True)

        # Convert map to list and sort full backups by timestamp
        structured_backups = sorted(full_backups_map.values(), key=lambda x: x['timestamp_str'], reverse=True)

        logger.info(f"Found {len(structured_backups)} full backups with their incrementals (if any).")
        return structured_backups

    except Exception as e:
        logger.error(f"Error listing structured booking data JSON backups: {e}", exc_info=True)
        return []


def delete_booking_data_json_backup(filename, backup_type=None, task_id=None, base_timestamp_for_incremental=None):
    log_prefix = f"[Task {task_id}] " if task_id else ""
    logger.info(f"{log_prefix}Attempting to delete unified backup: Type='{backup_type}', Filename='{filename}'.")
    files_to_delete = []

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

        # Determine the primary file to delete and its subdir
        primary_file_azure_subdir = ""
        full_match = FULL_BACKUP_PATTERN.match(filename)
        inc_match = INCREMENTAL_BACKUP_PATTERN.match(filename)

        if backup_type == "full" or (not backup_type and full_match): # Deleting a full backup
            primary_file_azure_subdir = "manual_full_json" # Assuming full backups are here
            files_to_delete.append({'filename': filename, 'subdir': primary_file_azure_subdir})

            # If it's a full backup, find its incrementals
            full_backup_ts_match = FULL_BACKUP_PATTERN.match(filename)
            if full_backup_ts_match:
                full_backup_timestamp = full_backup_ts_match.group(1)
                logger.info(f"{log_prefix}Full backup specified. Searching for associated incrementals for base timestamp '{full_backup_timestamp}'.")

                # Scan relevant directories for incrementals
                incremental_scan_subdirs = ["incremental_json", "manual_full_json"] # Scan where incrementals might be
                for scan_subdir_name in incremental_scan_subdirs:
                    inc_dir_path = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{scan_subdir_name}"
                    dir_client = share_client.get_directory_client(inc_dir_path)
                    if _client_exists(dir_client):
                        for item in dir_client.list_directories_and_files():
                            if not item['is_directory']:
                                inc_file_match = INCREMENTAL_BACKUP_PATTERN.match(item['name'])
                                if inc_file_match and inc_file_match.group(2) == full_backup_timestamp:
                                    logger.info(f"{log_prefix}Found associated incremental: {item['name']} in {scan_subdir_name}")
                                    files_to_delete.append({'filename': item['name'], 'subdir': scan_subdir_name})

        elif backup_type == "incremental" or (not backup_type and inc_match): # Deleting a single incremental
            # Determine subdir for incremental. Assume 'incremental_json' or 'manual_full_json'
            # This part might need refinement if incrementals can be in multiple places.
            # For now, let's assume they are primarily in 'incremental_json' or check 'manual_full_json'
            # A more robust way would be to get the subdir from where it was listed.
            # However, this function is called with just filename and type.
            if os.path.exists(f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/incremental_json/{filename}"):
                 primary_file_azure_subdir = "incremental_json"
            else: # Fallback or assume it might be with full backups if not in dedicated dir
                 primary_file_azure_subdir = "manual_full_json"
            files_to_delete.append({'filename': filename, 'subdir': primary_file_azure_subdir})

        else: # Fallback for older type "manual_full_json" or if type is ambiguous
            logger.warning(f"{log_prefix}Backup type '{backup_type}' is ambiguous or unhandled for specific subdir. Defaulting to 'manual_full_json' for {filename}.")
            primary_file_azure_subdir = "manual_full_json"
            files_to_delete.append({'filename': filename, 'subdir': primary_file_azure_subdir})
            # No incremental deletion logic here for this ambiguous case to be safe.

        if not files_to_delete:
            logger.error(f"{log_prefix}No files identified for deletion for filename '{filename}' and type '{backup_type}'.")
            return False

        all_deleted_successfully = True
        for file_info in files_to_delete:
            f_name = file_info['filename']
            f_subdir = file_info['subdir']
            remote_file_path = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{f_subdir}/{f_name}"
            file_client = share_client.get_file_client(remote_file_path)

            try:
                if _client_exists(file_client):
                    file_client.delete_file()
                    logger.info(f"{log_prefix}Successfully deleted file '{remote_file_path}'.")
                else:
                    logger.warning(f"{log_prefix}File '{remote_file_path}' not found in share '{share_name}'. No action taken for this file.")
            except ResourceNotFoundError: # Should be caught by _client_exists, but as a safeguard
                logger.warning(f"{log_prefix}File '{f_name}' (Path: {remote_file_path}) not found during delete attempt. Considered success for this file.")
            except Exception as e_del:
                logger.error(f"{log_prefix}An unexpected error occurred during deletion of '{remote_file_path}': {e_del}", exc_info=True)
                all_deleted_successfully = False # Mark overall operation as failed

        return all_deleted_successfully

    except Exception as e:
        logger.error(f"{log_prefix}An unexpected error occurred during the deletion process for '{filename}' (Type: {backup_type}): {e}", exc_info=True)
        return False


def download_backup_set_as_zip(full_backup_filename, task_id=None):
    log_prefix = f"[Task {task_id}] " if task_id else ""
    logger.info(f"{log_prefix}Preparing to download backup set for full backup: {full_backup_filename}")

    zip_buffer = BytesIO()
    files_added_to_zip = []

    try:
        service_client = _get_service_client()
        share_name = os.environ.get('AZURE_BOOKING_DATA_SHARE', 'booking-data-backups')
        if not share_name:
            err_msg = f"{log_prefix}Azure share name for booking data backups is not configured (AZURE_BOOKING_DATA_SHARE)."
            logger.error(err_msg)
            if task_id: update_task_log(task_id, err_msg, level="error")
            raise ValueError("Azure share name not configured.")

        share_client = service_client.get_share_client(share_name)
        if not _client_exists(share_client):
            err_msg = f"{log_prefix}Azure share '{share_name}' not found."
            logger.warning(err_msg)
            if task_id: update_task_log(task_id, err_msg, level="error")
            raise ValueError(f"Azure share '{share_name}' not found.")

        # 1. Download the full backup file
        full_backup_ts_match = FULL_BACKUP_PATTERN.match(full_backup_filename)
        if not full_backup_ts_match:
            err_msg = f"{log_prefix}Invalid full backup filename format: {full_backup_filename}"
            logger.error(err_msg)
            if task_id: update_task_log(task_id, err_msg, level="error")
            raise ValueError("Invalid full backup filename format.")

        full_backup_timestamp = full_backup_ts_match.group(1)
        full_backup_azure_path = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/manual_full_json/{full_backup_filename}" # Assuming full backups are here

        logger.info(f"{log_prefix}Attempting to download full backup file: {full_backup_azure_path}")
        if task_id: update_task_log(task_id, f"Downloading full backup: {full_backup_filename}...", level="info")

        # Re-using download_booking_data_json_backup which has its own logging.
        # It expects backup_type="manual_full_json" to correctly find the subdir for full backups.
        full_backup_content = download_booking_data_json_backup(filename=full_backup_filename, backup_type="manual_full_json")

        if full_backup_content is None:
            err_msg = f"{log_prefix}Failed to download critical full backup file: {full_backup_filename}"
            logger.error(err_msg)
            if task_id: update_task_log(task_id, err_msg, level="critical")
            raise IOError(f"Failed to download full backup file: {full_backup_filename}. Cannot create ZIP.")

        files_added_to_zip.append({'name_in_zip': full_backup_filename, 'content': full_backup_content})
        logger.info(f"{log_prefix}Full backup file '{full_backup_filename}' downloaded successfully.")
        if task_id: update_task_log(task_id, f"Full backup '{full_backup_filename}' downloaded.", level="info")

        # 2. Find and download associated incremental backups
        logger.info(f"{log_prefix}Searching for incremental backups based on full backup timestamp: '{full_backup_timestamp}' (derived from full backup filename: '{full_backup_filename}')")
        if task_id: update_task_log(task_id, f"Searching for incremental backups for base timestamp '{full_backup_timestamp}'...", level="info")

        incremental_scan_subdirs = ["incremental_json", "manual_full_json"]
        incrementals_found_count = 0
        incrementals_added_to_zip_count = 0

        for scan_subdir_name in incremental_scan_subdirs:
            inc_dir_path_on_share = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{scan_subdir_name}"
            dir_client = share_client.get_directory_client(inc_dir_path_on_share)

            logger.debug(f"{log_prefix}Scanning directory for incrementals: '{inc_dir_path_on_share}'")
            if not _client_exists(dir_client):
                logger.info(f"{log_prefix}Incremental scan directory '{inc_dir_path_on_share}' does not exist. Skipping.")
                continue

            for item in dir_client.list_directories_and_files():
                if item['is_directory']:
                    continue

                inc_filename = item['name']
                logger.debug(f"{log_prefix}Checking file: '{inc_filename}' in subdir '{scan_subdir_name}'")
                inc_match = INCREMENTAL_BACKUP_PATTERN.match(inc_filename)

                if inc_match:
                    extracted_inc_ts = inc_match.group(1)
                    extracted_base_ts = inc_match.group(2)
                    logger.debug(f"{log_prefix}Incremental pattern matched for '{inc_filename}'. Extracted inc_ts: '{extracted_inc_ts}', base_ts: '{extracted_base_ts}'")

                    comparison_result = (extracted_base_ts == full_backup_timestamp)
                    logger.debug(f"{log_prefix}Comparing extracted base_ts '{extracted_base_ts}' with target full_backup_timestamp '{full_backup_timestamp}'. Match: {comparison_result}")

                    if comparison_result:
                        incrementals_found_count += 1
                        logger.info(f"{log_prefix}Found matching associated incremental: '{inc_filename}' in '{scan_subdir_name}'. Attempting download...")
                        if task_id: update_task_log(task_id, f"Downloading matching incremental: {inc_filename}...", level="info")

                        inc_backup_azure_path = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{scan_subdir_name}/{inc_filename}"
                        inc_file_client = share_client.get_file_client(inc_backup_azure_path)

                        try:
                            if _client_exists(inc_file_client):
                                download_stream = inc_file_client.download_file()
                                inc_content = download_stream.readall()
                                if inc_content:
                                    files_added_to_zip.append({'name_in_zip': inc_filename, 'content': inc_content})
                                    incrementals_added_to_zip_count +=1
                                    logger.info(f"{log_prefix}Incremental backup '{inc_filename}' downloaded and added to ZIP list.")
                                    if task_id: update_task_log(task_id, f"Incremental '{inc_filename}' downloaded and prepared for ZIP.", level="info")
                                else:
                                    logger.warning(f"{log_prefix}Incremental backup '{inc_filename}' downloaded but content is empty. Skipping this file for ZIP.")
                                    if task_id: update_task_log(task_id, f"Incremental '{inc_filename}' was empty. Skipped for ZIP.", level="warning")
                            else:
                                logger.warning(f"{log_prefix}Incremental backup file '{inc_backup_azure_path}' was listed but not found during download attempt. Skipping for ZIP.")
                                if task_id: update_task_log(task_id, f"Incremental '{inc_filename}' not found on download attempt. Skipped for ZIP.", level="warning")
                        except Exception as e_inc_dl:
                            logger.error(f"{log_prefix}Error downloading incremental file '{inc_filename}': {e_inc_dl}", exc_info=True)
                            if task_id: update_task_log(task_id, f"Error downloading incremental '{inc_filename}': {str(e_inc_dl)}. Skipped for ZIP.", level="error")
                else:
                    logger.debug(f"{log_prefix}File '{inc_filename}' did not match incremental pattern.")

        logger.info(f"{log_prefix}Incremental search complete. Found {incrementals_found_count} potential incrementals, added {incrementals_added_to_zip_count} to ZIP list.")
        if task_id: update_task_log(task_id, f"Found {incrementals_found_count} potential incrementals, added {incrementals_added_to_zip_count} to ZIP.", level="info")

        if not files_added_to_zip: # Should be caught by full_backup_content check, but as a safeguard
            err_msg = f"{log_prefix}No files (not even the full backup) were successfully prepared for zipping for base {full_backup_filename}."
            logger.warning(err_msg)
            if task_id: update_task_log(task_id, "No backup files could be prepared for the ZIP archive.", level="error")
            raise IOError("No backup files could be prepared for the ZIP archive.")

        # 3. Create ZIP file in memory
        logger.info(f"{log_prefix}Creating ZIP archive with {len(files_added_to_zip)} file(s).")
        if task_id: update_task_log(task_id, f"Creating ZIP archive with {len(files_added_to_zip)} file(s)...", level="info")

        try:
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for file_to_add in files_added_to_zip:
                    zf.writestr(file_to_add['name_in_zip'], file_to_add['content'])
        except Exception as e_zip:
            err_msg = f"{log_prefix}Error during ZIP file creation: {e_zip}"
            logger.error(err_msg, exc_info=True)
            if task_id: update_task_log(task_id, f"Error creating ZIP file: {str(e_zip)}", level="critical")
            raise IOError(f"Failed to create ZIP archive: {str(e_zip)}")

        zip_buffer.seek(0)
        logger.info(f"{log_prefix}ZIP archive created successfully in memory for {full_backup_filename}.")
        if task_id: update_task_log(task_id, "ZIP archive created successfully.", level="success")
        return zip_buffer

    except (ValueError, IOError) as e_val_io: # Catch config/setup errors or critical file IO errors
        logger.error(f"{log_prefix}Error preparing ZIP for backup set {full_backup_filename}: {e_val_io}", exc_info=True)
        if task_id: update_task_log(task_id, f"Failed to prepare ZIP: {str(e_val_io)}", level="critical")
        return None # Return None to indicate failure to the caller API
    except Exception as e_final: # Catch any other unexpected errors
        logger.error(f"{log_prefix}Unexpected error creating ZIP for backup set {full_backup_filename}: {e_final}", exc_info=True)
        if task_id: update_task_log(task_id, f"Unexpected critical error during ZIP creation: {str(e_final)}", level="critical")
        return None


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
        logger.debug(f"Inside download_booking_data_json_backup: received backup_type='{backup_type}' (type: {type(backup_type)}) for filename='{filename}'")

        if backup_type == "manual_full_json" or backup_type == "full": # Accept "full" as an alias
            logger.info(f"Condition `backup_type == 'manual_full_json' or backup_type == 'full'` met for backup_type: '{backup_type}'. Setting target_subdir.")
            target_subdir = "manual_full_json"
            if backup_type == "full": # This specific log was already there.
                logger.info(f"Backup type 'full' provided; interpreting as 'manual_full_json' for directory targeting.")
        else:
            logger.warning(f"Unknown or unhandled backup_type '{backup_type}' for download. Cannot determine target directory.")
            logger.error(f"Cannot determine directory for backup type '{backup_type}'. Download aborted.")
            return None

        if not target_subdir:
             logger.error(f"Logical error: Target subdirectory not set for backup type '{backup_type}' even after checks. This should not happen if type is 'full' or 'manual_full_json'. Download aborted.")
             return None

        logger.info(f"Determined target_subdir: '{target_subdir}' for backup_type: '{backup_type}'.")
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
GENERAL_CONFIGS_FILENAME_PREFIX = "general_configs_"
UNIFIED_SCHEDULE_FILENAME_PREFIX = "unified_booking_backup_schedule_"
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
    _emit_progress(task_id, "Restore Error: Not implemented.", detail='NOT_IMPLEMENTED', level='ERROR')
    # return None, None, None, None, [] # Old placeholder return

    _emit_progress(task_id, f"Starting full restore for backup timestamp: {backup_timestamp}", level="INFO")
    if dry_run:
        _emit_progress(task_id, "DRY RUN: Full restore process initiated.", level="INFO")
        # Simulate manifest download and component identification
        simulated_actions = [
            "DRY RUN: Would download manifest.",
            "DRY RUN: Would identify database component from manifest.",
            "DRY RUN: Would download database component.",
            "DRY RUN: Would identify map_config component from manifest.",
            "DRY RUN: Would download map_config component.",
            "DRY RUN: Would identify resource_configs component from manifest.",
            "DRY RUN: Would download resource_configs component.",
            "DRY RUN: Would identify user_configs component from manifest.",
            "DRY RUN: Would download user_configs component.",
            "DRY RUN: Would identify scheduler_settings component from manifest.",
            "DRY RUN: Would download scheduler_settings component.",
            "DRY RUN: Would identify general_configs component from manifest.",
            "DRY RUN: Would download general_configs component.",
            "DRY RUN: Would identify media component base path from manifest.",
            "DRY RUN: Media sub-components (floor_maps, resource_uploads) would be handled by restore_media_component later."
        ]
        for action in simulated_actions:
            _emit_progress(task_id, action, level="INFO")

        _emit_progress(task_id, "DRY RUN: Full restore simulation completed.", level="SUCCESS")
        # Return structure for dry run: (None for paths, but list of actions)
        # The calling function in api_system.py expects a dictionary for downloaded_components
        return {
            "local_temp_dir": "/tmp/simulated_dry_run_dir", # Placeholder
            "database_dump": "/tmp/simulated_dry_run_dir/sim_database.sql", # Placeholder
            "map_config": "/tmp/simulated_dry_run_dir/sim_map_config.json", # Placeholder
            "resource_configs": "/tmp/simulated_dry_run_dir/sim_resource_configs.json", # Placeholder
            "user_configs": "/tmp/simulated_dry_run_dir/sim_user_configs.json", # Placeholder
            "scheduler_settings": "/tmp/simulated_dry_run_dir/sim_scheduler_settings.json", # Placeholder
            "general_configs": "/tmp/simulated_dry_run_dir/sim_general_configs.json", # Placeholder
            "unified_booking_backup_schedule": "/tmp/simulated_dry_run_dir/sim_unified_booking_backup_schedule.json", # Placeholder
            "media_base_path_on_share": f"{FULL_SYSTEM_BACKUPS_BASE_DIR}/backup_{backup_timestamp}/{COMPONENT_SUBDIR_MEDIA}", # Placeholder for path on share
            "actions_summary": simulated_actions
        }

    # Actual restore logic
    downloaded_component_paths = {
        "database_dump": None,
        "map_config": None,
        "resource_configs": None,
        "user_configs": None,
        "scheduler_settings": None,
        "general_configs": None,
        "unified_booking_backup_schedule": None, # Added for unified schedule
        "media_base_path_on_share": None, # Store the base path on Azure for media, not a local download path
        "local_temp_dir": None,
        "actions_summary": []
    }
    actions_summary = downloaded_component_paths["actions_summary"]

    local_temp_dir = None
    try:
        service_client = _get_service_client()
        system_backup_share_name = os.environ.get('AZURE_SYSTEM_BACKUP_SHARE', 'system-backups')
        share_client = service_client.get_share_client(system_backup_share_name)

        if not _client_exists(share_client):
            msg = f"Azure share '{system_backup_share_name}' not found for restore."
            _emit_progress(task_id, msg, level="ERROR")
            actions_summary.append(msg)
            # No specific paths to return, but the structure is expected.
            return downloaded_component_paths # Return partially filled dict indicating failure at this stage

        local_temp_dir = tempfile.mkdtemp(prefix=f"restore_{backup_timestamp}_")
        downloaded_component_paths["local_temp_dir"] = local_temp_dir
        _emit_progress(task_id, f"Created temporary directory for downloads: {local_temp_dir}", level="INFO")
        actions_summary.append(f"Created temp dir: {local_temp_dir}")

        # 1. Download Manifest
        manifest_filename = f"backup_manifest_{backup_timestamp}.json"
        manifest_path_on_share = f"{FULL_SYSTEM_BACKUPS_BASE_DIR}/backup_{backup_timestamp}/{COMPONENT_SUBDIR_MANIFEST}/{manifest_filename}"
        local_manifest_path = os.path.join(local_temp_dir, manifest_filename)

        if not download_file(share_client, manifest_path_on_share, local_manifest_path):
            msg = f"Failed to download manifest: {manifest_path_on_share}"
            _emit_progress(task_id, msg, level="ERROR")
            actions_summary.append(msg)
            # shutil.rmtree(local_temp_dir) # Clean up temp dir on failure
            return downloaded_component_paths

        actions_summary.append(f"Manifest downloaded to {local_manifest_path}")
        _emit_progress(task_id, "Manifest downloaded. Parsing components...", level="INFO")

        with open(local_manifest_path, 'r', encoding='utf-8') as f_manifest:
            manifest_data = json.load(f_manifest)

        backup_root_on_share = f"{FULL_SYSTEM_BACKUPS_BASE_DIR}/backup_{backup_timestamp}"

        # 2. Download components based on manifest
        for component in manifest_data.get("components", []):
            comp_type = component.get("type")
            comp_name = component.get("name") # e.g., "database", "map_config", "general_configs"
            comp_path_in_backup = component.get("path_in_backup") # Relative path like "database/site_....db" or "configurations/general_configs_....json"

            if not comp_path_in_backup:
                _emit_progress(task_id, f"Component '{comp_name}' (Type: {comp_type}) missing 'path_in_backup' in manifest. Skipping.", level="WARNING")
                actions_summary.append(f"Skipped component '{comp_name}': missing path_in_backup.")
                continue

            full_path_on_share = f"{backup_root_on_share}/{comp_path_in_backup}"

            # Determine local download filename (use original filename from path_in_backup)
            local_filename = os.path.basename(comp_path_in_backup)
            local_download_target_path = os.path.join(local_temp_dir, local_filename)

            _emit_progress(task_id, f"Attempting to download component: {comp_name} (Type: {comp_type}) from {full_path_on_share}", level="INFO")

            if comp_type == "media": # Media is a directory, store its Azure base path for later processing
                # The manifest component for media should have path_in_backup like "media"
                # The actual subdirectories (floor_map_uploads, resource_uploads) are inside this.
                # We store the Azure path to the "media" directory of this backup set.
                downloaded_component_paths["media_base_path_on_share"] = full_path_on_share
                _emit_progress(task_id, f"Media base path on Azure identified: {full_path_on_share}. Actual files will be restored by specific media logic.", level="INFO")
                actions_summary.append(f"Media base path on Azure for component '{comp_name}': {full_path_on_share}")
                continue # Don't download the media directory itself as a single file.

            # For file-based components (db, configs)
            if download_file(share_client, full_path_on_share, local_download_target_path):
                _emit_progress(task_id, f"Component '{comp_name}' downloaded to {local_download_target_path}", level="SUCCESS")
                actions_summary.append(f"Downloaded '{comp_name}' to {local_download_target_path}")

                # Store path based on standardized keys
                if comp_type == "database":
                    downloaded_component_paths["database_dump"] = local_download_target_path
                elif comp_name == "map_config": # Match by name from manifest
                    downloaded_component_paths["map_config"] = local_download_target_path
                elif comp_name == "resource_configs":
                    downloaded_component_paths["resource_configs"] = local_download_target_path
                elif comp_name == "user_configs":
                    downloaded_component_paths["user_configs"] = local_download_target_path
                elif comp_name == "scheduler_settings":
                    downloaded_component_paths["scheduler_settings"] = local_download_target_path
                elif comp_name == "general_configs": # New general configurations
                    downloaded_component_paths["general_configs"] = local_download_target_path
                elif comp_name == "unified_booking_backup_schedule": # For unified schedule file
                     downloaded_component_paths["unified_booking_backup_schedule"] = local_download_target_path
                else:
                    _emit_progress(task_id, f"Unknown component name '{comp_name}' (Type: {comp_type}) in manifest during download mapping. File downloaded but not assigned to a standard key.", level="WARNING")
                    actions_summary.append(f"Downloaded unknown component '{comp_name}' to {local_download_target_path}")
            else:
                msg = f"Failed to download component '{comp_name}' from {full_path_on_share}"
                _emit_progress(task_id, msg, level="ERROR")
                actions_summary.append(msg)
                # Depending on criticality, you might set an overall failure flag here.
                # For now, allow continuing to download other components.

        _emit_progress(task_id, "All listed components processed for download.", level="INFO")
        actions_summary.append("Component download phase complete.")
        # The local_temp_dir should NOT be cleaned up here; the caller (api_system.py) will use these files.
        # Caller is responsible for cleanup.

    except Exception as e:
        error_msg = f"Critical error during full restore download phase: {str(e)}"
        _emit_progress(task_id, error_msg, level="CRITICAL", detail=traceback.format_exc())
        actions_summary.append(error_msg)
        if local_temp_dir and os.path.exists(local_temp_dir):
            try:
                shutil.rmtree(local_temp_dir) # Attempt cleanup on critical error
                _emit_progress(task_id, f"Cleaned up temp dir {local_temp_dir} due to error.", level="INFO")
            except Exception as e_clean:
                _emit_progress(task_id, f"Error cleaning up temp dir {local_temp_dir}: {str(e_clean)}", level="ERROR")
        downloaded_component_paths["local_temp_dir"] = None # Nullify if cleaned or failed to create
        # Return partially filled dict indicating failure
        return downloaded_component_paths

    return downloaded_component_paths


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
                (user_configs_data, "user_configs", USER_CONFIG_FILENAME_PREFIX),
            ]
            # Add general configurations (BookingSettings)
            general_configs_data = _get_general_configurations_data() # Fetch general configs
            if general_configs_data and not general_configs_data.get('error'):
                configs_to_backup_dynamically.append(
                    (general_configs_data, "general_configs", GENERAL_CONFIGS_FILENAME_PREFIX)
                )
            else:
                _emit_progress(task_id, "Failed to retrieve general configurations (BookingSettings) for backup.",
                               detail=general_configs_data.get('message', 'Unknown error during fetch.'), level='ERROR')
                # Decide if this is a critical failure. For now, log and continue.
                # overall_success = False # Uncomment if this should fail the entire backup.

            for config_data, name, prefix in configs_to_backup_dynamically:
                _emit_progress(task_id, f"AzureBackup: Checking dynamic config component '{name}'. Data is None: {config_data is None}. Data is empty (if applicable): {not config_data if isinstance(config_data, (list, dict)) else 'N/A'}", level='DEBUG')
                if not config_data or (isinstance(config_data, dict) and config_data.get('error')): # Also check for error flag from _get_general_configurations_data
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

            # Backup unified_booking_backup_schedule.json
            unified_schedule_local_path = os.path.join(DATA_DIR, 'unified_booking_backup_schedule.json')
            _emit_progress(task_id, f"Checking for unified_booking_backup_schedule.json at {unified_schedule_local_path}", level='INFO')
            if os.path.exists(unified_schedule_local_path):
                unified_schedule_filename = f"{UNIFIED_SCHEDULE_FILENAME_PREFIX}{timestamp_str}.json"
                remote_unified_schedule_file_path = f"{remote_config_dir}/{unified_schedule_filename}"
                _emit_progress(task_id, f"Attempting to backup unified_booking_backup_schedule.json to {remote_unified_schedule_file_path}", level='INFO')
                if upload_file(share_client, unified_schedule_local_path, remote_unified_schedule_file_path):
                    _emit_progress(task_id, "unified_booking_backup_schedule.json backup successful.", level='SUCCESS')
                    backed_up_items.append({"type": "config", "name": "unified_booking_backup_schedule", "filename": unified_schedule_filename, "path_in_backup": f"{COMPONENT_SUBDIR_CONFIGURATIONS}/{unified_schedule_filename}"})
                else:
                    _emit_progress(task_id, "unified_booking_backup_schedule.json backup failed.", level='ERROR')
                    overall_success = False # Optionally mark as failure
            else:
                _emit_progress(task_id, "unified_booking_backup_schedule.json not found locally, skipping its backup.", level='WARNING')

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

def download_general_config_component(share_client: ShareClient, full_path_on_share: str, task_id: str = None, dry_run: bool = False):
    """Downloads the general configurations JSON file from Azure to a local temporary path."""
    if dry_run:
        _emit_progress(task_id, "DRY RUN: Simulating general configurations component download.", level='INFO')
        # Return a success-like tuple with a simulated path
        return True, "Dry run: General configurations download simulated.", f"simulated_downloaded_general_configs.json", None

    _emit_progress(task_id, f"Starting general configurations component download from '{full_path_on_share}'.", level='INFO')

    base_filename = os.path.basename(full_path_on_share) if full_path_on_share else "general_configs.json"
    local_filename = f"downloaded_{base_filename}" # e.g., downloaded_general_configs_YYYYMMDD_HHMMSS.json

    # Ensure DATA_DIR is defined (it should be at the module level)
    # If DATA_DIR is not suitable for temp files, use tempfile.gettempdir() or a dedicated app temp folder.
    # For consistency with other download functions, using DATA_DIR for now.
    local_temp_path = os.path.join(DATA_DIR, local_filename)
    os.makedirs(DATA_DIR, exist_ok=True) # Ensure DATA_DIR exists

    if download_file(share_client, full_path_on_share, local_temp_path):
        _emit_progress(task_id, f"General configurations downloaded successfully to '{local_temp_path}'.", level='SUCCESS')
        return True, f"General configurations downloaded to '{local_temp_path}'.", local_temp_path, None
    else:
        error_msg = f"Failed to download general configurations from '{full_path_on_share}'."
        _emit_progress(task_id, error_msg, level='ERROR')
        return False, error_msg, None, error_msg

def download_unified_schedule_component(share_client: ShareClient, full_path_on_share: str, task_id: str = None, dry_run: bool = False):
    """Downloads the unified_booking_backup_schedule.json file from Azure to a local temporary path."""
    if dry_run:
        _emit_progress(task_id, "DRY RUN: Simulating unified backup schedule component download.", level='INFO')
        return True, "Dry run: Unified backup schedule download simulated.", "simulated_downloaded_unified_schedule.json", None

    _emit_progress(task_id, f"Starting unified backup schedule component download from '{full_path_on_share}'.", level='INFO')

    base_filename = os.path.basename(full_path_on_share) if full_path_on_share else "unified_booking_backup_schedule.json"
    local_filename = f"downloaded_{base_filename}"

    local_temp_path = os.path.join(DATA_DIR, local_filename) # Using DATA_DIR for consistency
    os.makedirs(DATA_DIR, exist_ok=True)

    if download_file(share_client, full_path_on_share, local_temp_path):
        _emit_progress(task_id, f"Unified backup schedule downloaded successfully to '{local_temp_path}'.", level='SUCCESS')
        return True, f"Unified backup schedule downloaded to '{local_temp_path}'.", local_temp_path, None
    else:
        error_msg = f"Failed to download unified backup schedule from '{full_path_on_share}'."
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
    # Initialize with a more neutral/optimistic status, will be changed if errors occur
    restore_status = {"status": "success", "message": "Startup restore sequence initiated."}
    # Track if any component actually failed to set partial_failure correctly
    any_component_failed_apply = False

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
            restore_status["status"] = "failure" # Critical early failure
            raise Exception(msg)

        app_logger.info(f"Successfully connected to Azure share '{system_backup_share_name}'.")
        available_backups = list_available_backups()
        if not available_backups:
            msg = "No full system backup sets found in Azure. Skipping startup restore."
            app_logger.info(msg)
            restore_status["status"] = "success_no_action"
            restore_status["message"] = msg
            return restore_status

        latest_backup_timestamp = available_backups[0]
        app_logger.info(f"Latest full system backup timestamp found: {latest_backup_timestamp}")

        backup_root_on_share = f"{FULL_SYSTEM_BACKUPS_BASE_DIR}/backup_{latest_backup_timestamp}"
        manifest_filename = f"backup_manifest_{latest_backup_timestamp}.json"
        manifest_path_on_share = f"{backup_root_on_share}/{COMPONENT_SUBDIR_MANIFEST}/{manifest_filename}"
        local_manifest_path = os.path.join(local_temp_dir, manifest_filename)

        app_logger.info(f"Attempting to download manifest: {manifest_path_on_share}")
        if not download_file(share_client, manifest_path_on_share, local_manifest_path):
            msg = f"Failed to download manifest file '{manifest_path_on_share}'. Startup restore aborted."
            app_logger.error(msg)
            restore_status["message"] = msg
            restore_status["status"] = "failure" # Critical
            raise Exception(msg)

        app_logger.info(f"Manifest downloaded to {local_manifest_path}. Parsing...")
        with open(local_manifest_path, 'r', encoding='utf-8') as f_manifest:
            manifest_data = json.load(f_manifest)

        downloaded_component_paths = {}

        for component in manifest_data.get("components", []):
            comp_type = component.get("type")
            comp_name_in_manifest = component.get("name", "UnknownComponent")
            comp_path_in_backup_set = component.get("path_in_backup")

            if not comp_path_in_backup_set:
                app_logger.warning(f"Component '{comp_name_in_manifest}' (Type: {comp_type}) in manifest has no 'path_in_backup'. Skipping.")
                continue
            full_path_on_share = f"{backup_root_on_share}/{comp_path_in_backup_set}"
            if comp_type == "media":
                app_logger.info(f"Media component '{comp_name_in_manifest}' identified. Path on share: {full_path_on_share}. Individual files will be handled by media restore logic.")
                if comp_path_in_backup_set == COMPONENT_SUBDIR_MEDIA:
                     downloaded_component_paths[comp_type] = {"base_path_on_share": full_path_on_share}
                else:
                     app_logger.warning(f"Unexpected media component path '{comp_path_in_backup_set}'. Expected '{COMPONENT_SUBDIR_MEDIA}'. Skipping.")
                continue
            local_filename_for_download = os.path.basename(comp_path_in_backup_set)
            local_download_path = os.path.join(local_temp_dir, local_filename_for_download)
            app_logger.info(f"Downloading component file: {comp_name_in_manifest} (Type: {comp_type}) from {full_path_on_share} to {local_download_path}")
            if download_file(share_client, full_path_on_share, local_download_path):
                app_logger.info(f"Successfully downloaded {comp_name_in_manifest} to {local_download_path}")
                storage_key = comp_name_in_manifest if comp_type == "config" else comp_type
                downloaded_component_paths[storage_key] = local_download_path
            else:
                msg = f"Failed to download component file '{comp_name_in_manifest}' (Type: {comp_type}) from '{full_path_on_share}'. Startup restore might be incomplete."
                app_logger.error(msg)
                restore_status["message"] = msg # Update message
                restore_status["status"] = "partial_failure" # Mark as partial
                any_component_failed_apply = True # Track failure
                if comp_type == "database":
                    app_logger.critical("CRITICAL: Database component download failed. Aborting restore sequence.")
                    restore_status["status"] = "failure"
                    raise Exception(msg)

        # --- Apply downloaded components ---
        with app_for_context.app_context():
            app_logger.info("STARTUP_RESTORE_LOG: Entering app_context for applying restored components.")

            # 1. Database
            if "database" in downloaded_component_paths:
                local_db_path = downloaded_component_paths["database"]
                live_db_uri = app_for_context.config.get('SQLALCHEMY_DATABASE_URI', '')
                app_logger.info(f"STARTUP_RESTORE_LOG: Attempting to restore Database from {local_db_path}")
                if live_db_uri.startswith('sqlite:///'):
                    live_db_path = live_db_uri.replace('sqlite:///', '', 1)
                    live_db_dir = os.path.dirname(live_db_path)
                    if not os.path.exists(live_db_dir): os.makedirs(live_db_dir, exist_ok=True)
                    try:
                        shutil.copyfile(local_db_path, live_db_path)
                        app_logger.info("STARTUP_RESTORE_LOG: Database file successfully replaced by restored version.")
                        # Migrations are handled by init_setup.py after this function.
                        try:
                            add_audit_log("System Restore", f"Database file replaced from startup sequence using backup {latest_backup_timestamp}. Migrations to be run by init_setup.")
                            app_logger.info("STARTUP_RESTORE_LOG: Database replacement audit log successful.")
                        except Exception as e_audit:
                            app_logger.warning(f"STARTUP_RESTORE_LOG: Could not write audit log for system restore (db file replaced): {e_audit}", exc_info=True)
                    except Exception as e_db_restore:
                        msg = f"Error replacing live database with restored version: {e_db_restore}"
                        app_logger.error(f"STARTUP_RESTORE_LOG: {msg}", exc_info=True)
                        restore_status["message"] = msg
                        restore_status["status"] = "failure" # DB copy is critical
                        any_component_failed_apply = True
                        raise Exception(msg)
                else:
                    app_logger.warning(f"STARTUP_RESTORE_LOG: Database URI '{live_db_uri}' is not SQLite. Skipping database file replacement.")
            else:
                app_logger.warning("STARTUP_RESTORE_LOG: Database component not found in downloaded files. Skipping database restore.")

            app_logger.info("STARTUP_RESTORE_LOG: Starting JSON config application phase.")

            # 2. Map, Resource, User Configs
            config_types_map = {
                "map_config": (_import_map_configuration_data, "Map Configuration"),
                "resource_configs": (_import_resource_configurations_data, "Resource Configurations"),
                "user_configs": (_import_user_configurations_data, "User Configurations")}

            app_logger.info(f"STARTUP_RESTORE_LOG: Before map/resource/user config loop. Downloaded keys: {list(downloaded_component_paths.keys())}")
            for config_key, (import_func, log_name) in config_types_map.items():
                app_logger.info(f"STARTUP_RESTORE_LOG: In loop, checking config_key: {config_key}")
                if config_key in downloaded_component_paths:
                    local_config_path = downloaded_component_paths[config_key]
                    app_logger.info(f"STARTUP_RESTORE_LOG: Attempting to restore {log_name} from {local_config_path}")
                    try:
                        with open(local_config_path, 'r', encoding='utf-8') as f_config:
                            config_data = json.load(f_config)
                        raw_import_result = import_func(config_data)
                        import_successful = False
                        message = f"{log_name} import result not fully processed."
                        errors_detail = "N/A"

                        if config_key == "map_config":
                            summary_dict, status_code = raw_import_result
                            import_successful = status_code < 300
                            message = summary_dict.get('message', f'{log_name} import status: {status_code}')
                            if not import_successful: errors_detail = str(summary_dict.get('errors', []))
                        elif config_key == "resource_configs":
                            _, _, res_errors, _, status_code, msg_res = raw_import_result
                            import_successful = status_code < 300
                            message = msg_res
                            if not import_successful: errors_detail = str(res_errors)
                        elif config_key == "user_configs":
                            summary_user = raw_import_result # This returns a dict
                            import_successful = summary_user.get('success', False)
                            message = summary_user.get('message', f'{log_name} import {"succeeded" if import_successful else "failed"}.')
                            if not import_successful: errors_detail = str(summary_user.get('errors', []))

                        if import_successful:
                            app_logger.info(f"STARTUP_RESTORE_LOG: {log_name} processed successfully. Message: {message}")
                        else:
                            any_component_failed_apply = True
                            restore_status["status"] = "partial_failure"
                            app_logger.error(f"STARTUP_RESTORE_LOG: Failed to restore {log_name}. Details: {errors_detail}. Full message: {message}")
                            restore_status["message"] = f"{restore_status.get('message','')}; Failed to process {log_name}: {errors_detail or message}"

                    except Exception as e_config_restore:
                        any_component_failed_apply = True
                        restore_status["status"] = "partial_failure"
                        app_logger.error(f"STARTUP_RESTORE_LOG: Error during {log_name} import stage: {e_config_restore}", exc_info=True)
                        restore_status["message"] = f"{restore_status.get('message','')}; Error during {log_name} import: {str(e_config_restore)}"
                else:
                    app_logger.info(f"STARTUP_RESTORE_LOG: {log_name} component not found in downloaded_component_paths. Skipping its restore.")

            # 3. Scheduler Settings
            app_logger.info("STARTUP_RESTORE_LOG: Checking for scheduler_settings component.")
            if "scheduler_settings" in downloaded_component_paths:
                local_scheduler_path = downloaded_component_paths["scheduler_settings"]
                app_logger.info(f"STARTUP_RESTORE_LOG: Attempting to restore Scheduler Settings from {local_scheduler_path}")
                try:
                    with open(local_scheduler_path, 'r', encoding='utf-8') as f_sched:
                        scheduler_data = json.load(f_sched)
                    summary_sched, status_sched = save_scheduler_settings_from_json_data(scheduler_data)
                    app_logger.info(f"STARTUP_RESTORE_LOG: save_scheduler_settings_from_json_data result - Status: {status_sched}, Summary: {summary_sched}")
                    if status_sched < 300:
                        app_logger.info(f"STARTUP_RESTORE_LOG: Scheduler settings applied: {summary_sched.get('message', 'Success')}")
                        add_audit_log("System Restore", f"Scheduler settings restored from startup using backup {latest_backup_timestamp}. Status: {summary_sched.get('message', 'Success')}")
                    else:
                        any_component_failed_apply = True
                        restore_status["status"] = "partial_failure"
                        app_logger.error(f"STARTUP_RESTORE_LOG: Failed to restore Scheduler Settings: {summary_sched.get('message', 'Unknown error')}. Errors: {summary_sched.get('errors', [])}")
                        restore_status["message"] = f"{restore_status.get('message','')}; Failed Scheduler Settings: {summary_sched.get('message', 'Unknown')}"
                except Exception as e_sched_restore:
                    any_component_failed_apply = True
                    restore_status["status"] = "partial_failure"
                    app_logger.error(f"STARTUP_RESTORE_LOG: Error during Scheduler Settings import stage: {e_sched_restore}", exc_info=True)
                    restore_status["message"] = f"{restore_status.get('message','')}; Error Scheduler Settings: {str(e_sched_restore)}"
            else:
                app_logger.info("STARTUP_RESTORE_LOG: Scheduler settings component not found. Skipping.")

            # 4. General Configurations (BookingSettings)
            app_logger.info("STARTUP_RESTORE_LOG: Checking for General Configurations (BookingSettings) component.")
            if "general_configs" in downloaded_component_paths:
                local_general_configs_path = downloaded_component_paths["general_configs"]
                app_logger.info(f"STARTUP_RESTORE_LOG: Attempting to restore General Configurations from {local_general_configs_path}")
                try:
                    with open(local_general_configs_path, 'r', encoding='utf-8') as f_gc:
                        general_configs_data = json.load(f_gc)
                    summary_gc, status_gc = _import_general_configurations_data(general_configs_data)
                    app_logger.info(f"STARTUP_RESTORE_LOG: _import_general_configurations_data result - Status: {status_gc}, Summary: {summary_gc}")
                    if status_gc < 300:
                        app_logger.info(f"STARTUP_RESTORE_LOG: General Configurations applied: {summary_gc.get('message', 'Success')}")
                        add_audit_log("System Restore", f"General Configurations (BookingSettings) restored from startup using backup {latest_backup_timestamp}. Status: {summary_gc.get('message', 'Success')}")
                    else:
                        any_component_failed_apply = True
                        restore_status["status"] = "partial_failure"
                        app_logger.error(f"STARTUP_RESTORE_LOG: Failed to restore General Configurations: {summary_gc.get('message', 'Unknown error')}. Errors: {summary_gc.get('errors', [])}")
                        restore_status["message"] = f"{restore_status.get('message','')}; Failed General Configs: {summary_gc.get('message', 'Unknown')}"
                except Exception as e_gc_restore:
                    any_component_failed_apply = True
                    restore_status["status"] = "partial_failure"
                    app_logger.error(f"STARTUP_RESTORE_LOG: Error during General Configurations import stage: {e_gc_restore}", exc_info=True)
                    restore_status["message"] = f"{restore_status.get('message','')}; Error General Configs: {str(e_gc_restore)}"
            else:
                app_logger.info("STARTUP_RESTORE_LOG: General Configurations component not found. Skipping.")

            # 5. Unified Booking Backup Schedule Settings
            app_logger.info("STARTUP_RESTORE_LOG: Checking for Unified Booking Backup Schedule component.")
            if "unified_booking_backup_schedule" in downloaded_component_paths:
                local_unified_sched_path = downloaded_component_paths["unified_booking_backup_schedule"]
                app_logger.info(f"STARTUP_RESTORE_LOG: Attempting to restore Unified Schedule from {local_unified_sched_path}")
                try:
                    with open(local_unified_sched_path, 'r', encoding='utf-8') as f_us:
                        unified_sched_data = json.load(f_us)
                    save_success, save_message = save_unified_backup_schedule_settings(unified_sched_data)
                    app_logger.info(f"STARTUP_RESTORE_LOG: save_unified_backup_schedule_settings result - Success: {save_success}, Message: {save_message}")
                    if save_success:
                        app_logger.info(f"STARTUP_RESTORE_LOG: Unified Backup Schedule settings applied: {save_message}")
                        add_audit_log("System Restore", f"Unified Backup Schedule restored from startup using backup {latest_backup_timestamp}. Status: {save_message}")
                    else:
                        any_component_failed_apply = True
                        restore_status["status"] = "partial_failure"
                        app_logger.error(f"STARTUP_RESTORE_LOG: Failed to restore Unified Backup Schedule: {save_message}")
                        restore_status["message"] = f"{restore_status.get('message','')}; Failed Unified Schedule: {save_message}"
                except Exception as e_us_restore:
                    any_component_failed_apply = True
                    restore_status["status"] = "partial_failure"
                    app_logger.error(f"STARTUP_RESTORE_LOG: Error during Unified Backup Schedule import stage: {e_us_restore}", exc_info=True)
                    restore_status["message"] = f"{restore_status.get('message','')}; Error Unified Schedule: {str(e_us_restore)}"
            else:
                app_logger.info("STARTUP_RESTORE_LOG: Unified Backup Schedule component not found. Skipping.")

            # 6. Media Files
            app_logger.info("STARTUP_RESTORE_LOG: Checking for Media component.")
            if "media" in downloaded_component_paths and isinstance(downloaded_component_paths["media"], dict):
                media_component_info = downloaded_component_paths["media"]
                media_base_path_on_share = media_component_info.get("base_path_on_share")
                app_logger.info(f"STARTUP_RESTORE_LOG: Media base_path_on_share: {media_base_path_on_share}")
                if media_base_path_on_share:
                    media_sources_to_restore = [
                        {"name": "Floor Maps", "azure_subdir": "floor_map_uploads", "local_target_dir": FLOOR_MAP_UPLOADS},
                        {"name": "Resource Uploads", "azure_subdir": "resource_uploads", "local_target_dir": RESOURCE_UPLOADS}
                    ]
                    for media_src in media_sources_to_restore:
                        azure_full_subdir_path = f"{media_base_path_on_share}/{media_src['azure_subdir']}"
                        app_logger.info(f"STARTUP_RESTORE_LOG: Attempting to restore media for {media_src['name']} from Azure path '{azure_full_subdir_path}' to local '{media_src['local_target_dir']}'.")
                        if os.path.exists(media_src['local_target_dir']):
                            app_logger.info(f"STARTUP_RESTORE_LOG: Clearing existing local media directory: {media_src['local_target_dir']}")
                            try: shutil.rmtree(media_src['local_target_dir'])
                            except Exception as e_rm: app_logger.error(f"STARTUP_RESTORE_LOG: Failed to clear local media directory {media_src['local_target_dir']}: {e_rm}")
                        try: os.makedirs(media_src['local_target_dir'], exist_ok=True)
                        except Exception as e_mkdir: app_logger.error(f"STARTUP_RESTORE_LOG: Failed to create local media directory {media_src['local_target_dir']}: {e_mkdir}"); continue

                        media_success, media_msg, media_err_detail = restore_media_component(
                            share_client=share_client, azure_component_path_on_share=azure_full_subdir_path,
                            local_target_folder_base=media_src['local_target_dir'], media_component_name=media_src['name']
                        )
                        if media_success:
                            app_logger.info(f"STARTUP_RESTORE_LOG: {media_src['name']} restored successfully. {media_msg}")
                        else:
                            any_component_failed_apply = True
                            restore_status["status"] = "partial_failure"
                            app_logger.error(f"STARTUP_RESTORE_LOG: Failed to restore {media_src['name']}. Message: {media_msg}. Details: {media_err_detail}")
                            restore_status["message"] = f"{restore_status.get('message','')}; Failed media {media_src['name']}: {media_msg}"
                else:
                    app_logger.warning("STARTUP_RESTORE_LOG: Media component base path not found. Skipping media files restore.")
            else:
                app_logger.info("STARTUP_RESTORE_LOG: Media component not found. Skipping media files restore.")

            # Final status update
            if not any_component_failed_apply and restore_status["status"] != "failure": # Check if it wasn't changed from initial "success"
                restore_status["status"] = "success"
                restore_status["message"] = f"Startup restore sequence completed successfully from backup {latest_backup_timestamp}."
            elif any_component_failed_apply and restore_status["status"] != "failure":
                 restore_status["status"] = "partial_failure"
                 # Message would have been built up by failing components
                 if restore_status["message"] == "Startup restore sequence initiated.": # If only warnings, not errors that change message
                     restore_status["message"] = f"Startup restore sequence for {latest_backup_timestamp} completed with some warnings or non-critical issues."


            app_logger.info(f"STARTUP_RESTORE_LOG: Restore application process within app_context finished. Status: {restore_status['status']}, Message: {restore_status['message']}")
        app_logger.info("STARTUP_RESTORE_LOG: Exited app_context for applying restored components.")

    except Exception as e_main:
        app_logger.error(f"STARTUP_RESTORE_LOG: A critical error occurred during the startup restore sequence: {e_main}", exc_info=True)
        restore_status["status"] = "failure"
        # Ensure message reflects the main error if it's still the default or append
        if restore_status.get("message") == "Startup restore sequence initiated." or not restore_status.get("message"):
            restore_status["message"] = f"Critical error during restore: {str(e_main)}"
        else:
            restore_status["message"] = f"{restore_status.get('message','')}; Critical error: {str(e_main)}"
    finally:
        if local_temp_dir and os.path.exists(local_temp_dir):
            try:
                shutil.rmtree(local_temp_dir)
                app_logger.info(f"Successfully cleaned up temporary directory: {local_temp_dir}")
            except Exception as e_cleanup:
                app_logger.error(f"Failed to clean up temporary directory {local_temp_dir}: {e_cleanup}", exc_info=True)

    app_logger.info(f"STARTUP_RESTORE_LOG: Startup restore sequence final status: {restore_status['status']}. Message: {restore_status['message']}")
    return restore_status

# ... (rest of the file: create_full_backup, _recursively_delete_share_directory, etc. remain unchanged) ...
# ... (download_component functions, verify_backup_set, delete_backup_set, etc. remain unchanged) ...
# ... (backup_full_bookings_json, backup_if_changed remain unchanged) ...
# ... (utility functions like _get_service_client, _client_exists, _emit_progress, _ensure_directory_exists, _create_share_with_retry, upload_file, download_file remain unchanged) ...
# ... (constants at the end of the file, if any, remain unchanged) ...
