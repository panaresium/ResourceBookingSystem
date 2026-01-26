import os
import json
import logging
import tempfile
import re
import time
import shutil
import zipfile
from io import BytesIO
from datetime import datetime, timezone

from models import Booking, db
from utils import (
    _import_map_configuration_data,
    _import_resource_configurations_data,
    _import_user_configurations_data,
    add_audit_log,
    _get_general_configurations_data,
    _import_general_configurations_data,
    save_unified_backup_schedule_settings,
    save_scheduler_settings_from_json_data,
    update_task_log
)
from r2_storage import r2_storage

logger = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
FLOOR_MAP_UPLOADS = os.path.join(STATIC_DIR, 'floor_map_uploads')
RESOURCE_UPLOADS = os.path.join(STATIC_DIR, 'resource_uploads')

# Naming conventions
FULL_BACKUP_PATTERN = re.compile(r"manual_full_booking_export_(\d{8}_\d{6})\.json")
INCREMENTAL_BACKUP_PATTERN = re.compile(r"incremental_booking_export_(\d{8}_\d{6})_for_(\d{8}_\d{6})\.json")

# Constants for backup directories
AZURE_BOOKING_DATA_PROTECTION_DIR = 'booking_data_protection_backups'
FULL_SYSTEM_BACKUPS_BASE_DIR = "full_system_backups"
INCREMENTAL_BACKUP_SUBDIR = "incremental_json"
COMPONENT_SUBDIR_DATABASE = "database"
COMPONENT_SUBDIR_CONFIGURATIONS = "configurations"
COMPONENT_SUBDIR_MEDIA = "media"
COMPONENT_SUBDIR_MANIFEST = "manifest"

# Prefixes
DB_FILENAME_PREFIX = 'site_'
MAP_CONFIG_FILENAME_PREFIX = 'map_config_'
RESOURCE_CONFIG_FILENAME_PREFIX = "resource_configs_"
USER_CONFIG_FILENAME_PREFIX = "user_configs_"
SCHEDULER_SETTINGS_FILENAME_PREFIX = "scheduler_settings_"
GENERAL_CONFIGS_FILENAME_PREFIX = "general_configs_"
UNIFIED_SCHEDULE_FILENAME_PREFIX = "unified_booking_backup_schedule_"


def _emit_progress(task_id, message, detail='', level='INFO'):
    if task_id:
        try:
            update_task_log(task_id, message, detail, level.lower())
        except Exception as e:
            logger.error(f"R2Backup: Failed to update task log for task {task_id}: {e}", exc_info=True)
    else:
        logger.info(f"R2Backup: {message} | {detail}")


def backup_full_bookings_json(app, task_id=None):
    """
    Creates a full backup of all booking data to a JSON file and uploads it to R2.
    """
    _emit_progress(task_id, "Starting manual full JSON backup of booking data...", level='INFO')

    try:
        if not r2_storage.client:
             _emit_progress(task_id, "R2 Storage client is not initialized.", level='ERROR')
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

        export_data = {
            "export_timestamp": datetime.now(timezone.utc).isoformat(),
            "bookings": booking_list_for_json
        }

        timestamp_str = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        filename = f"manual_full_booking_export_{timestamp_str}.json"

        # Path structure in R2: booking_data_protection_backups/manual_full_json/filename
        target_folder = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/manual_full_json"

        tmp_file_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp_file:
                json.dump(export_data, tmp_file, indent=4)
                tmp_file_path = tmp_file.name

            _emit_progress(task_id, f"Uploading {filename} to R2 path {target_folder}/{filename}.", level='INFO')
            upload_success = r2_storage.upload_file(tmp_file_path, filename, folder=target_folder)

            if upload_success:
                _emit_progress(task_id, "Manual full JSON backup of booking data completed successfully.", level='SUCCESS')
                return True
            else:
                _emit_progress(task_id, "Failed to upload manual full JSON backup of booking data.", level='ERROR')
                return False
        finally:
            if tmp_file_path and os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)

    except Exception as e:
        logger.error(f"An unexpected error occurred in backup_full_bookings_json: {e}", exc_info=True)
        _emit_progress(task_id, "An unexpected error occurred during the backup process.", detail=str(e), level='ERROR')
        return False


def create_incremental_booking_backup(app, task_id=None):
    log_prefix = f"[Task {task_id if task_id else 'ScheduledInc'}] "
    logger.info(f"{log_prefix}Starting creation of incremental booking backup.")
    if task_id: update_task_log(task_id, "Incremental backup process started.", level="info")

    if not r2_storage.client:
        err_msg = f"{log_prefix}R2 Storage client not initialized."
        logger.error(err_msg)
        if task_id: update_task_log(task_id, err_msg, level="critical")
        return False

    try:
        # 1. Find Latest Full Backup from R2
        full_backup_dir_prefix = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/manual_full_json/"
        files = r2_storage.list_files(prefix=full_backup_dir_prefix)

        latest_full_backup_file = None
        latest_full_backup_dt = None

        for item in files:
            # item['name'] contains the full key
            filename = os.path.basename(item['name'])
            match = FULL_BACKUP_PATTERN.match(filename)
            if match:
                ts_str = match.group(1)
                try:
                    dt_obj = datetime.strptime(ts_str, '%Y%m%d_%H%M%S').replace(tzinfo=timezone.utc)
                    if latest_full_backup_dt is None or dt_obj > latest_full_backup_dt:
                        latest_full_backup_dt = dt_obj
                        latest_full_backup_file = filename
                except ValueError:
                    pass

        if latest_full_backup_file is None or latest_full_backup_dt is None:
            err_msg = f"{log_prefix}No valid full backups found in R2. Cannot create incremental backup."
            logger.error(err_msg)
            if task_id: update_task_log(task_id, err_msg, level="error")
            return False

        full_backup_timestamp_str = latest_full_backup_dt.strftime('%Y%m%d_%H%M%S')
        logger.info(f"{log_prefix}Latest full backup identified: {latest_full_backup_file}")

        # 2. Determine "Since" Timestamp (using local state file)
        # Note: In a stateless Cloud Run env, this local file is ephemeral.
        # Ideally, we should check the latest INCREMENTAL backup in R2 to find the last timestamp.
        # But keeping it simple as per original logic, though we might want to improve this for Cloud Run.
        # Improvement: Scan R2 for latest incremental for this base.

        # Scan R2 for existing incrementals for this base
        inc_dir_prefix = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{INCREMENTAL_BACKUP_SUBDIR}/"
        inc_files = r2_storage.list_files(prefix=inc_dir_prefix)

        last_inc_ts_from_storage = None
        for item in inc_files:
             filename = os.path.basename(item['name'])
             match = INCREMENTAL_BACKUP_PATTERN.match(filename)
             if match:
                 inc_ts_str = match.group(1)
                 base_ts_str = match.group(2)
                 if base_ts_str == full_backup_timestamp_str:
                     try:
                         dt_inc = datetime.strptime(inc_ts_str, '%Y%m%d_%H%M%S').replace(tzinfo=timezone.utc)
                         if last_inc_ts_from_storage is None or dt_inc > last_inc_ts_from_storage:
                             last_inc_ts_from_storage = dt_inc
                     except ValueError:
                         pass

        since_timestamp_dt = latest_full_backup_dt
        if last_inc_ts_from_storage:
             since_timestamp_dt = last_inc_ts_from_storage
             logger.info(f"{log_prefix}Found previous incremental backup. Using 'since' timestamp: {since_timestamp_dt.isoformat()}")

        # 3. Fetch Incremental Booking Data
        bookings_to_backup = []
        with app.app_context():
            if since_timestamp_dt.tzinfo is not None:
                since_timestamp_naive_utc = since_timestamp_dt.astimezone(timezone.utc).replace(tzinfo=None)
            else:
                since_timestamp_naive_utc = since_timestamp_dt

            logger.info(f"{log_prefix}Querying bookings modified since: {since_timestamp_naive_utc}")

            modified_bookings = Booking.query.filter(Booking.last_modified >= since_timestamp_naive_utc).all()

            if since_timestamp_dt != latest_full_backup_dt:
                 bookings_to_backup = [b for b in modified_bookings if b.last_modified > since_timestamp_naive_utc]
            else:
                 bookings_to_backup = modified_bookings

        # 4. Handle No Changes
        if not bookings_to_backup:
            logger.info(f"{log_prefix}No new or modified bookings since {since_timestamp_dt.isoformat()}.")
            return True

        # 5. Serialize
        booking_list_for_json = []
        for booking in bookings_to_backup:
            booking_list_for_json.append({
                'id': booking.id, 'resource_id': booking.resource_id, 'user_name': booking.user_name,
                'start_time': booking.start_time.isoformat() if booking.start_time else None,
                'end_time': booking.end_time.isoformat() if booking.end_time else None,
                'title': booking.title, 'status': booking.status,
                'last_modified': booking.last_modified.isoformat() if booking.last_modified else None,
            })

        current_inc_time = datetime.now(timezone.utc)
        current_inc_ts_str = current_inc_time.strftime('%Y%m%d_%H%M%S')

        export_data = {
            "backup_type": "incremental",
            "creation_timestamp_iso": current_inc_time.isoformat(),
            "base_full_backup_filename": latest_full_backup_file,
            "incremental_since_timestamp_iso": since_timestamp_dt.isoformat(),
            "bookings": booking_list_for_json
        }

        # 6. Upload
        inc_filename = f"incremental_booking_export_{current_inc_ts_str}_for_{full_backup_timestamp_str}.json"
        target_folder = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{INCREMENTAL_BACKUP_SUBDIR}"

        tmp_file_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp_file:
                json.dump(export_data, tmp_file, indent=4)
                tmp_file_path = tmp_file.name

            logger.info(f"{log_prefix}Uploading incremental backup '{inc_filename}'")
            upload_success = r2_storage.upload_file(tmp_file_path, inc_filename, folder=target_folder)

            if not upload_success:
                 return False

            return True

        finally:
            if tmp_file_path and os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)

    except Exception as e:
        logger.error(f"{log_prefix}Error during incremental backup: {e}", exc_info=True)
        return False


def create_full_backup(timestamp_str, map_config_data=None, resource_configs_data=None, user_configs_data=None, task_id=None, socketio_instance=None):
    """
    Creates a full system backup (DB, Configs, Media) and uploads to R2.
    """
    overall_success = True
    backed_up_items = []

    if not r2_storage.client:
        _emit_progress(task_id, "R2 Storage client not initialized.", level='ERROR')
        return False

    current_backup_root_path = f"{FULL_SYSTEM_BACKUPS_BASE_DIR}/backup_{timestamp_str}"

    # 1. Database Backup
    # Note: For SQLite, we just copy the file. For Postgres, we should ideally dump it.
    # Since we are moving to Postgres, this part needs to handle Postgres dump if possible,
    # or rely on an external DB backup solution.
    # For now, let's assume we are dumping the configured DB or just the SQLite file if still present locally.
    # Given the prompt says "SQLite to postgresdb", we should probably use pg_dump here if using Postgres.
    # However, running pg_dump inside a container might require pg_dump installed.
    # Let's check if we can simply skip DB backup here if it's managed cloud SQL, or try to dump.

    _emit_progress(task_id, "Starting database backup component...", level='INFO')
    db_backup_filename = f"{DB_FILENAME_PREFIX}{timestamp_str}.sql" # Changing to .sql assuming pg_dump
    remote_db_dir = f"{current_backup_root_path}/{COMPONENT_SUBDIR_DATABASE}"

    # Check if we are using Postgres
    db_url = os.environ.get('DATABASE_URL', '')
    if 'postgres' in db_url:
        # Attempt pg_dump
        try:
             # We need to construct a pg_dump command.
             # WARNING: This requires pg_dump to be installed in the environment.
             # If not, we might need to skip this or use a python library.
             # For simplicity in this plan, let's assume we might need to skip or provide a warning if pg_dump fails.
             # But let's try to do it properly if possible.

             # Env vars for pg_dump
             env_copy = os.environ.copy()
             # We assume DATABASE_URL has credentials.

             # Actually, creating a pg_dump file might be complex securely here.
             # Let's fallback to the user requirement: "DB will handle data backup by itself".
             # So we might NOT need to backup the DB file here if using Cloud SQL / Postgres.
             # But the prompt said: "However, import and export option should be there for easier migration tasks later."

             # Let's try to export data to JSON as a "database backup" which is portable.
             # Or stick to the requirement that DB handles itself, but we provide "Export" which is what backup_full_bookings_json does.

             # For this "Full System Backup" function (which seems to be about restoring the *application state*),
             # maybe we just backup the configs and media?
             # The legacy code backed up SQLite.

             # Let's add a placeholder for DB export or skip it if using cloud DB.
             _emit_progress(task_id, "Using PostgreSQL/Cloud DB. Skipping binary DB file backup (managed by DB provider or separate process).", level='INFO')
             # We won't add it to backed_up_items, or we add a metadata marker.

        except Exception as e:
             _emit_progress(task_id, f"Error preparing DB backup: {e}", level='WARNING')
    else:
        # Fallback for SQLite (local dev)
        local_db_path = os.path.join(DATA_DIR, 'site.db')
        if os.path.exists(local_db_path):
             db_backup_filename = f"{DB_FILENAME_PREFIX}{timestamp_str}.db"
             if r2_storage.upload_file(local_db_path, db_backup_filename, folder=remote_db_dir):
                 backed_up_items.append({"type": "database", "filename": db_backup_filename, "path_in_backup": f"{COMPONENT_SUBDIR_DATABASE}/{db_backup_filename}"})

    # 2. Configuration Files
    _emit_progress(task_id, "Starting configuration files backup...", level='INFO')
    remote_config_dir = f"{current_backup_root_path}/{COMPONENT_SUBDIR_CONFIGURATIONS}"

    configs = [
        (map_config_data, "map_config", MAP_CONFIG_FILENAME_PREFIX),
        (resource_configs_data, "resource_configs", RESOURCE_CONFIG_FILENAME_PREFIX),
        (user_configs_data, "user_configs", USER_CONFIG_FILENAME_PREFIX)
    ]

    # Add general configs
    general_configs_data = _get_general_configurations_data()
    if general_configs_data and not general_configs_data.get('error'):
        configs.append((general_configs_data, "general_configs", GENERAL_CONFIGS_FILENAME_PREFIX))

    for config_data, name, prefix in configs:
        if not config_data or (isinstance(config_data, dict) and config_data.get('error')):
            continue

        config_filename = f"{prefix}{timestamp_str}.json"

        try:
             with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp_file:
                json.dump(config_data, tmp_file, indent=4)
                tmp_path = tmp_file.name

             if r2_storage.upload_file(tmp_path, config_filename, folder=remote_config_dir):
                  backed_up_items.append({"type": "config", "name": name, "filename": config_filename, "path_in_backup": f"{COMPONENT_SUBDIR_CONFIGURATIONS}/{config_filename}"})
             else:
                  overall_success = False

             os.remove(tmp_path)
        except Exception as e:
             logger.error(f"Error backing up config {name}: {e}")
             overall_success = False

    # 3. Media Files
    _emit_progress(task_id, "Starting media files backup...", level='INFO')
    azure_media_base = f"{current_backup_root_path}/{COMPONENT_SUBDIR_MEDIA}"

    media_sources = [
        {"name": "Floor Maps", "path": FLOOR_MAP_UPLOADS, "subdir": "floor_map_uploads"},
        {"name": "Resource Uploads", "path": RESOURCE_UPLOADS, "subdir": "resource_uploads"}
    ]

    all_media_success = True
    for src in media_sources:
        if not os.path.isdir(src["path"]):
            continue

        target_dir = f"{azure_media_base}/{src['subdir']}"
        for fname in os.listdir(src["path"]):
            fpath = os.path.join(src["path"], fname)
            if os.path.isfile(fpath):
                if not r2_storage.upload_file(fpath, fname, folder=target_dir):
                    all_media_success = False

    if all_media_success:
         backed_up_items.append({"type": "media", "name": "media_files", "path_in_backup": COMPONENT_SUBDIR_MEDIA})
    else:
         overall_success = False

    # 4. Manifest
    if overall_success:
        manifest_data = {
            "backup_timestamp": timestamp_str,
            "backup_version": "2.0_r2_structure",
            "components": backed_up_items
        }

        manifest_filename = f"backup_manifest_{timestamp_str}.json"
        remote_manifest_dir = f"{current_backup_root_path}/{COMPONENT_SUBDIR_MANIFEST}"

        try:
             with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp_file:
                json.dump(manifest_data, tmp_file, indent=4)
                tmp_path = tmp_file.name

             if r2_storage.upload_file(tmp_path, manifest_filename, folder=remote_manifest_dir):
                 _emit_progress(task_id, "Manifest uploaded successfully.", level='SUCCESS')
             else:
                 overall_success = False

             os.remove(tmp_path)
        except Exception as e:
             logger.error(f"Error creating manifest: {e}")
             overall_success = False

    return overall_success


def list_booking_data_json_backups():
    """
    Lists booking data backups from R2.
    """
    logger.info("Listing booking data backups from R2...")
    try:
        if not r2_storage.client:
             return []

        prefix = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/"
        files = r2_storage.list_files(prefix=prefix)

        structured_backups = []
        full_backups_map = {}

        for file_info in files:
            full_path = file_info['name']
            filename = os.path.basename(full_path)

            full_match = FULL_BACKUP_PATTERN.match(filename)
            inc_match = INCREMENTAL_BACKUP_PATTERN.match(filename)

            if full_match:
                ts_str = full_match.group(1)
                try:
                    dt = datetime.strptime(ts_str, '%Y%m%d_%H%M%S').replace(tzinfo=timezone.utc)
                    if ts_str not in full_backups_map:
                        full_backups_map[ts_str] = {
                            'filename': filename,
                            'display_name': f"Full Backup - {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}",
                            'type': 'full',
                            'timestamp_str': dt.isoformat(),
                            'size_bytes': file_info['size'],
                            'incrementals': []
                        }
                except ValueError:
                    pass
            elif inc_match:
                # We can store incrementals and link them later if needed
                pass

        # Sort and return
        structured_backups = sorted(full_backups_map.values(), key=lambda x: x['timestamp_str'], reverse=True)
        return structured_backups

    except Exception as e:
        logger.error(f"Error listing backups: {e}", exc_info=True)
        return []

def download_booking_data_json_backup(filename, backup_type=None):
    """
    Downloads a specific backup file content.
    """
    folder = ""
    if backup_type == "manual_full_json" or backup_type == "full":
        folder = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/manual_full_json"
    elif backup_type == "incremental":
        folder = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{INCREMENTAL_BACKUP_SUBDIR}"

    content = r2_storage.download_file(filename, folder=folder)
    return content

# Placeholder functions to maintain compatibility with existing imports if needed,
# or they should be removed/updated in the calling code.
def backup_if_changed(app=None):
    return False

def list_available_backups():
    # Similar logic to list_booking_data_json_backups but for system backups
    return []

def restore_full_backup(backup_timestamp, task_id=None, dry_run=False):
    # This would implement the download logic from R2 using r2_storage.download_file
    # similar to the Azure implementation but simplified.
    _emit_progress(task_id, "Restore not fully implemented in R2 refactor yet.", level='WARNING')
    return {}

def delete_booking_data_json_backup(filename, backup_type=None, task_id=None):
    # R2 deletion logic
    folder = ""
    if backup_type == "manual_full_json" or backup_type == "full":
        folder = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/manual_full_json"
    elif backup_type == "incremental":
        folder = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{INCREMENTAL_BACKUP_SUBDIR}"

    return r2_storage.delete_file(filename, folder=folder)

def save_floor_map_to_share(local_path, filename):
    """
    Uploads a floor map to the 'floor_map_uploads' folder in R2.
    Used by api_maps.py for immediate persistence.
    """
    if not r2_storage.client:
        return False

    return r2_storage.upload_file(local_path, filename, folder='floor_map_uploads')

# Dummy functions to prevent import errors in api_system.py until full logic is migrated
def verify_backup_set(*args, **kwargs):
    return {'status': 'not_implemented', 'message': 'Not implemented for R2 yet.'}

def delete_backup_set(*args, **kwargs):
    return False

def _get_service_client(*args, **kwargs):
    return None

def _client_exists(*args, **kwargs):
    return True # Mock for now

def restore_database_component(*args, **kwargs): return False, "Not Implemented", None, None
def download_map_config_component(*args, **kwargs): return False, "Not Implemented", None, None
def download_resource_config_component(*args, **kwargs): return False, "Not Implemented", None, None
def download_user_config_component(*args, **kwargs): return False, "Not Implemented", None, None
def download_scheduler_settings_component(*args, **kwargs): return False, "Not Implemented", None, None
def download_general_config_component(*args, **kwargs): return False, "Not Implemented", None, None
def download_unified_schedule_component(*args, **kwargs): return False, "Not Implemented", None, None
def restore_media_component(*args, **kwargs): return False, "Not Implemented", None
def restore_bookings_from_full_db_backup(*args, **kwargs): return False, "Not Implemented"
def backup_incremental_bookings(*args, **kwargs): return False
def restore_booking_data_to_point_in_time(*args, **kwargs): return {'status': 'not_implemented', 'message': 'Not implemented'}
def download_file(*args, **kwargs): return False
def download_backup_set_as_zip(*args, **kwargs): return None
