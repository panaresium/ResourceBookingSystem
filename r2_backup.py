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

# Constants for backup directories
FULL_SYSTEM_BACKUPS_BASE_DIR = "full_system_backups"
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


def list_available_backups():
    """
    Lists full system backups from R2.
    Returns a list of timestamp strings (e.g. ['20230101_120000', ...]) sorted newest first.
    """
    if not r2_storage.client:
        logger.error("R2 Storage client not initialized for list_available_backups.")
        return []

    backups = set()
    try:
        # We look for manifest files to identify valid backups
        # Path pattern: full_system_backups/backup_{timestamp}/manifest/backup_manifest_{timestamp}.json
        # Prefix: full_system_backups/
        files = r2_storage.list_files(prefix=FULL_SYSTEM_BACKUPS_BASE_DIR)

        for file_info in files:
            key = file_info['name']
            # Regex to extract timestamp from key
            # key example: full_system_backups/backup_20230101_120000/manifest/backup_manifest_20230101_120000.json
            match = re.search(r'backup_(\d{8}_\d{6})/', key)
            if match:
                backups.add(match.group(1))

        # Sort desc
        return sorted(list(backups), reverse=True)
    except Exception as e:
        logger.error(f"Error listing available backups: {e}", exc_info=True)
        return []



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

def download_file(client, path, local_path):
    # Generic wrapper
    folder = os.path.dirname(path)
    filename = os.path.basename(path)
    return r2_storage.download_file(filename, folder=folder, target_path=local_path)

def download_backup_set_as_zip(*args, **kwargs): return None
