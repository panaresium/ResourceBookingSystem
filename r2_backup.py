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


def restore_booking_data_to_point_in_time(app, selected_filename, selected_type, selected_timestamp_iso, task_id=None):
    """
    Restores booking data from a JSON export stored in R2.
    """
    _emit_progress(task_id, f"Starting restore from '{selected_filename}' (Type: {selected_type}).", level="info")

    if selected_type not in ["manual_full_json", "full"]:
        msg = f"Restore for backup type '{selected_type}' is not currently supported. Supported types: 'manual_full_json', 'full'."
        _emit_progress(task_id, msg, level="error")
        return {'status': 'failure', 'message': msg, 'errors': [msg]}

    try:
        with app.app_context():
            # 1. Download Content
            _emit_progress(task_id, f"Downloading backup file: {selected_filename}...", level="info")
            file_content_bytes = download_booking_data_json_backup(filename=selected_filename, backup_type=selected_type)

            if file_content_bytes is None:
                msg = f"Failed to download backup file '{selected_filename}' from R2."
                _emit_progress(task_id, msg, level="error")
                return {'status': 'failure', 'message': msg, 'errors': ["File download failed."]}

            # 2. Parse JSON
            try:
                file_content_str = file_content_bytes.decode('utf-8')
                backup_data = json.loads(file_content_str)
                bookings_from_json = backup_data.get("bookings", [])
                export_timestamp = backup_data.get("export_timestamp", "N/A")
                _emit_progress(task_id, f"Successfully parsed backup file. Exported at: {export_timestamp}. Contains {len(bookings_from_json)} bookings.", level="info")
            except json.JSONDecodeError as e:
                msg = f"Failed to parse JSON from backup file: {str(e)}"
                _emit_progress(task_id, msg, level="error")
                return {'status': 'failure', 'message': msg, 'errors': [f"JSON decode error: {str(e)}"]}

            # 3. Wipe Existing Data
            _emit_progress(task_id, "WARNING: All existing booking data will be deleted.", level="warning")
            try:
                num_deleted = db.session.query(Booking).delete()
                db.session.commit()
                _emit_progress(task_id, f"Successfully deleted {num_deleted} existing bookings.", level="info")
            except Exception as e:
                db.session.rollback()
                msg = f"Failed to delete existing bookings: {str(e)}"
                _emit_progress(task_id, msg, level="error")
                return {'status': 'failure', 'message': msg, 'errors': [f"DB delete error: {str(e)}"]}

            # 4. Import Data
            _emit_progress(task_id, f"Starting import of {len(bookings_from_json)} bookings...", level="info")
            bookings_restored_count = 0
            bookings_failed_count = 0
            restore_errors = []

            for i, booking_json in enumerate(bookings_from_json):
                try:
                    if not all(k in booking_json for k in ['id', 'resource_id', 'user_name', 'start_time', 'end_time', 'status']):
                        bookings_failed_count += 1
                        continue

                    def parse_dt(dt_str):
                        if not dt_str: return None
                        if isinstance(dt_str, str) and dt_str.endswith('Z'):
                            return datetime.fromisoformat(dt_str[:-1] + '+00:00')
                        return datetime.fromisoformat(dt_str) if isinstance(dt_str, str) else None

                    def parse_t(t_str):
                        if not t_str: return None
                        try:
                            return datetime.strptime(t_str, '%H:%M:%S').time()
                        except ValueError:
                            return datetime.strptime(t_str, '%H:%M').time()

                    new_booking = Booking(
                        id=booking_json['id'],
                        resource_id=booking_json['resource_id'],
                        user_name=booking_json.get('user_name'),
                        title=booking_json.get('title'),
                        start_time=parse_dt(booking_json['start_time']),
                        end_time=parse_dt(booking_json['end_time']),
                        status=booking_json.get('status', 'approved'),
                        checked_in_at=parse_dt(booking_json.get('checked_in_at')),
                        checked_out_at=parse_dt(booking_json.get('checked_out_at')),
                        recurrence_rule=booking_json.get('recurrence_rule'),
                        admin_deleted_message=booking_json.get('admin_deleted_message'),
                        check_in_token=booking_json.get('check_in_token'),
                        check_in_token_expires_at=parse_dt(booking_json.get('check_in_token_expires_at')),
                        checkin_reminder_sent_at=parse_dt(booking_json.get('checkin_reminder_sent_at')),
                        last_modified=parse_dt(booking_json.get('last_modified')) or datetime.now(timezone.utc),
                        booking_display_start_time=parse_t(booking_json.get('booking_display_start_time')),
                        booking_display_end_time=parse_t(booking_json.get('booking_display_end_time'))
                    )
                    db.session.add(new_booking)
                    bookings_restored_count += 1
                except Exception as e_item:
                    bookings_failed_count += 1
                    restore_errors.append(f"Row {i}: {str(e_item)}")

            if bookings_failed_count > 0:
                db.session.commit()
                msg = f"Restore partial. Restored: {bookings_restored_count}, Failed: {bookings_failed_count}."
                _emit_progress(task_id, msg, level="warning")
                return {'status': 'partial_success', 'message': msg, 'errors': restore_errors}
            else:
                db.session.commit()
                msg = f"Successfully restored {bookings_restored_count} bookings."
                _emit_progress(task_id, msg, level="success")
                return {'status': 'success', 'message': msg}

    except Exception as e:
        db.session.rollback()
        msg = f"Critical error during restore: {str(e)}"
        _emit_progress(task_id, msg, level="critical")
        return {'status': 'failure', 'message': msg, 'errors': [str(e)]}


def create_incremental_booking_backup(app, task_id=None):
    # ... (code from previous step) ...
    log_prefix = f"[Task {task_id if task_id else 'ScheduledInc'}] "
    logger.info(f"{log_prefix}Starting creation of incremental booking backup.")
    if task_id: update_task_log(task_id, "Incremental backup process started.", level="info")

    if not r2_storage.client:
        return False # Error handled in r2_storage logs

    try:
        # 1. Find Latest Full Backup from R2
        full_backup_dir_prefix = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/manual_full_json/"
        files = r2_storage.list_files(prefix=full_backup_dir_prefix)

        latest_full_backup_file = None
        latest_full_backup_dt = None

        for item in files:
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
            if task_id: update_task_log(task_id, "No base full backup found.", level="error")
            return False

        full_backup_timestamp_str = latest_full_backup_dt.strftime('%Y%m%d_%H%M%S')

        # 2. Determine "Since" Timestamp
        # For simplicity in this R2 port, we start by checking if any incrementals exist for this base.
        # Ideally we'd parse them to find the latest timestamp.
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

        since_timestamp_dt = last_inc_ts_from_storage if last_inc_ts_from_storage else latest_full_backup_dt

        # 3. Fetch Data
        bookings_to_backup = []
        with app.app_context():
            if since_timestamp_dt.tzinfo is not None:
                since_timestamp_naive_utc = since_timestamp_dt.astimezone(timezone.utc).replace(tzinfo=None)
            else:
                since_timestamp_naive_utc = since_timestamp_dt

            modified_bookings = Booking.query.filter(Booking.last_modified >= since_timestamp_naive_utc).all()
            if since_timestamp_dt != latest_full_backup_dt:
                 bookings_to_backup = [b for b in modified_bookings if b.last_modified > since_timestamp_naive_utc]
            else:
                 bookings_to_backup = modified_bookings

        if not bookings_to_backup:
            return True

        # 5. Serialize & Upload (Simplified)
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

        inc_filename = f"incremental_booking_export_{current_inc_ts_str}_for_{full_backup_timestamp_str}.json"
        target_folder = f"{AZURE_BOOKING_DATA_PROTECTION_DIR}/{INCREMENTAL_BACKUP_SUBDIR}"

        tmp_file_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp_file:
                json.dump(export_data, tmp_file, indent=4)
                tmp_file_path = tmp_file.name

            r2_storage.upload_file(tmp_file_path, inc_filename, folder=target_folder)
            return True
        finally:
            if tmp_file_path and os.path.exists(tmp_file_path): os.remove(tmp_file_path)

    except Exception:
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
    _emit_progress(task_id, "Starting database backup component...", level='INFO')
    # For PostgreSQL in Cloud Run, standard practice is NOT to dump the DB here but rely on Cloud SQL backups.
    # However, for the "System Backup" feature to be complete as a portable snapshot, we should export data.
    # Since pg_dump might not be available, we can skip or use a JSON data export as a fallback "database" component.
    # For now, we will SKIP the DB file backup for Postgres environments to avoid complex dependencies,
    # and rely on the JSON config exports + separate Booking Data exports.
    # If SQLite exists locally, we back it up.

    local_db_path = os.path.join(DATA_DIR, 'site.db')
    if os.path.exists(local_db_path) and 'sqlite' in str(db.engine.url):
         db_backup_filename = f"{DB_FILENAME_PREFIX}{timestamp_str}.db"
         remote_db_dir = f"{current_backup_root_path}/{COMPONENT_SUBDIR_DATABASE}"
         if r2_storage.upload_file(local_db_path, db_backup_filename, folder=remote_db_dir):
             backed_up_items.append({"type": "database", "filename": db_backup_filename, "path_in_backup": f"{COMPONENT_SUBDIR_DATABASE}/{db_backup_filename}"})
    else:
         _emit_progress(task_id, "Database file backup skipped (PostgreSQL/Cloud SQL used). Use Cloud Console for DB backups.", level='INFO')

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

def restore_full_backup(backup_timestamp, task_id=None, dry_run=False):
    """
    Downloads all components of a full system backup from R2.
    Returns paths to downloaded files.
    """
    _emit_progress(task_id, f"Starting Full System Restore {'DRY RUN ' if dry_run else ''}for {backup_timestamp}...", level='INFO')

    if not r2_storage.client:
        return {}

    local_temp_dir = tempfile.mkdtemp(prefix=f"restore_{backup_timestamp}_")
    downloaded_component_paths = {
        "local_temp_dir": local_temp_dir,
        "actions_summary": []
    }

    backup_root_path = f"{FULL_SYSTEM_BACKUPS_BASE_DIR}/backup_{backup_timestamp}"
    manifest_filename = f"backup_manifest_{backup_timestamp}.json"

    # 1. Download Manifest
    manifest_local_path = os.path.join(local_temp_dir, manifest_filename)
    if not r2_storage.download_file(manifest_filename, folder=f"{backup_root_path}/{COMPONENT_SUBDIR_MANIFEST}", target_path=manifest_local_path):
        _emit_progress(task_id, "Failed to download manifest.", level='ERROR')
        return downloaded_component_paths

    with open(manifest_local_path, 'r') as f:
        manifest = json.load(f)

    for component in manifest.get('components', []):
        comp_type = component['type']
        comp_name = component.get('name', comp_type)
        path_in_backup = component['path_in_backup']

        if comp_type == 'media':
            # Media is handled separately by restore_media_component, just verify it exists
            downloaded_component_paths["media_base_path_on_share"] = f"{backup_root_path}/{COMPONENT_SUBDIR_MEDIA}"
            downloaded_component_paths["actions_summary"].append(f"Identified media component at {path_in_backup}")
            continue

        local_filename = os.path.basename(path_in_backup)
        local_path = os.path.join(local_temp_dir, local_filename)

        # In dry run, we just simulate the download path presence
        if dry_run:
            open(local_path, 'a').close() # Touch file
            downloaded_component_paths["actions_summary"].append(f"Simulated download of {comp_name} to {local_path}")
        else:
            # Download file
            # R2 storage takes key, so we need full key from backup root
            full_key = f"{backup_root_path}/{path_in_backup}"
            # But download_file helper might expect folder/filename.
            # Let's use boto3 directly or adapt usage. r2_storage.download_file uses key = folder/filename
            # path_in_backup is like 'configurations/map_config_....json'
            # backup_root_path is 'full_system_backups/backup_timestamp'

            # r2_storage.download_file joins folder + / + filename.
            # So if we pass folder=backup_root_path and filename=path_in_backup, it might work if path_in_backup doesn't start with /
            if r2_storage.download_file(path_in_backup, folder=backup_root_path, target_path=local_path):
                downloaded_component_paths["actions_summary"].append(f"Downloaded {comp_name} to {local_path}")
            else:
                _emit_progress(task_id, f"Failed to download {comp_name}", level='ERROR')
                continue

        # Map to specific keys expected by api_system
        if comp_name == 'map_config': downloaded_component_paths['map_config'] = local_path
        elif comp_name == 'resource_configs': downloaded_component_paths['resource_configs'] = local_path
        elif comp_name == 'user_configs': downloaded_component_paths['user_configs'] = local_path
        elif comp_name == 'scheduler_settings': downloaded_component_paths['scheduler_settings'] = local_path
        elif comp_name == 'general_configs': downloaded_component_paths['general_configs'] = local_path
        elif comp_type == 'database': downloaded_component_paths['database_dump'] = local_path

    return downloaded_component_paths

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

# Dummy functions/Wrappers to match expected signatures in api_system
def verify_backup_set(*args, **kwargs):
    return {'status': 'not_implemented', 'message': 'Not implemented for R2 yet.'}

def delete_backup_set(*args, **kwargs):
    return False

def _get_service_client(*args, **kwargs):
    return None

def _client_exists(*args, **kwargs):
    return True

# These need to do nothing or return success for the flow to proceed in api_system
# But actual work is done in restore_full_backup which returns paths.
# The api_system.py uses these for "Selective Restore" which calls them individually.
# So we SHOULD implement them if we want Selective Restore to work.
# For now, implementing basic wrapper around r2_storage.download_file

def restore_database_component(client, full_path, task_id=None, dry_run=False):
    # full_path includes 'full_system_backups/backup_ts/database/file.db'
    # We need to extract filename and 'folder' for r2_storage
    if dry_run: return True, "Dry run success", "simulated_path.db", None

    filename = os.path.basename(full_path)
    folder = os.path.dirname(full_path)
    local_path = os.path.join(DATA_DIR, filename)

    if r2_storage.download_file(filename, folder=folder, target_path=local_path):
        return True, "Success", local_path, None
    return False, "Failed download", None, "Download error"

def download_component_generic(full_path, dry_run=False):
    if dry_run: return True, "Dry run", "sim_path.json", None
    filename = os.path.basename(full_path)
    folder = os.path.dirname(full_path)
    local_path = os.path.join(DATA_DIR, filename)
    if r2_storage.download_file(filename, folder=folder, target_path=local_path):
        return True, "Success", local_path, None
    return False, "Failed", None, "Error"

def download_map_config_component(client, path, task_id=None, dry_run=False): return download_component_generic(path, dry_run)
def download_resource_config_component(client, path, task_id=None, dry_run=False): return download_component_generic(path, dry_run)
def download_user_config_component(client, path, task_id=None, dry_run=False): return download_component_generic(path, dry_run)
def download_scheduler_settings_component(client, path, task_id=None, dry_run=False): return download_component_generic(path, dry_run)
def download_general_config_component(client, path, task_id=None, dry_run=False): return download_component_generic(path, dry_run)
def download_unified_schedule_component(client, path, task_id=None, dry_run=False): return download_component_generic(path, dry_run)

def restore_media_component(share_client, azure_component_path_on_share, local_target_folder_base, media_component_name, task_id=None, dry_run=False):
    # share_client is ignored (R2 uses global client)
    # azure_component_path_on_share is the prefix in R2 (e.g. full_system_backups/backup_ts/media/floor_map_uploads)

    if dry_run: return True, "Dry run media", None

    files = r2_storage.list_files(prefix=azure_component_path_on_share)
    count = 0
    for f in files:
        key = f['name']
        filename = os.path.basename(key)
        if r2_storage.download_file(key, folder=None, target_path=os.path.join(local_target_folder_base, filename)):
            count += 1

    return True, f"Restored {count} files", None

def restore_bookings_from_full_db_backup(*args, **kwargs): return False, "Not Implemented"
def backup_incremental_bookings(*args, **kwargs): return False
def download_file(client, path, local_path):
    # Generic wrapper
    folder = os.path.dirname(path)
    filename = os.path.basename(path)
    return r2_storage.download_file(filename, folder=folder, target_path=local_path)

def download_backup_set_as_zip(*args, **kwargs): return None
