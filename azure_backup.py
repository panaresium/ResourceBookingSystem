import os
import hashlib
import logging
import sqlite3
import json
from datetime import datetime
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError # Added HttpResponseError

try:
    from azure.storage.fileshare import ShareServiceClient
    # ResourceNotFoundError and HttpResponseError are already imported above if SDK is present
except ImportError:  # pragma: no cover - azure sdk optional
    ShareServiceClient = None
    # Define ResourceNotFoundError and HttpResponseError as base Exception if SDK not present,
    # so try-except blocks later don't cause NameError.
    if 'ResourceNotFoundError' not in globals(): # Ensure it's not already defined
        ResourceNotFoundError = Exception
    if 'HttpResponseError' not in globals(): # Ensure it's not already defined
        HttpResponseError = Exception


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
FLOOR_MAP_UPLOADS = os.path.join(STATIC_DIR, 'floor_map_uploads')
RESOURCE_UPLOADS = os.path.join(STATIC_DIR, 'resource_uploads')
HASH_DB = os.path.join(DATA_DIR, 'backup_hashes.db')

# Module-level logger used for backup operations
logger = logging.getLogger(__name__)


# Constants for backup directories and prefixes
DB_BACKUPS_DIR = 'db_backups'
CONFIG_BACKUPS_DIR = 'config_backups'
MEDIA_BACKUPS_DIR_BASE = 'media_backups'
MAP_CONFIG_FILENAME_PREFIX = 'map_config_'
DB_FILENAME_PREFIX = 'site_'


def _get_service_client():
    connection_string = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
    if not connection_string:
        raise RuntimeError('AZURE_STORAGE_CONNECTION_STRING environment variable is required')
    if ShareServiceClient is None:
        raise RuntimeError('azure-storage-file-share package is not installed')
    return ShareServiceClient.from_connection_string(connection_string)


def _client_exists(client):

    """Return True if the given Share/File/Directory client exists."""
    if hasattr(client, 'exists'):
        return client.exists()
    check_methods = [
        'get_file_properties',
        'get_share_properties',
        'get_directory_properties'
    ]
    for name in check_methods:
        method = getattr(client, name, None)
        if not method:
            continue
        try:
            method()
            return True
        except ResourceNotFoundError:
            return False
        except Exception:
            continue
    return False

def _get_hash_conn():
    os.makedirs(os.path.dirname(HASH_DB), exist_ok=True)
    conn = sqlite3.connect(HASH_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS backup_hashes (filename TEXT PRIMARY KEY, filehash TEXT)"
    )
    return conn


def _load_hashes():
    conn = _get_hash_conn()
    cur = conn.execute("SELECT filename, filehash FROM backup_hashes")
    hashes = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()
    return hashes


def _save_hashes(hashes):
    conn = _get_hash_conn()
    conn.execute("DELETE FROM backup_hashes")
    conn.executemany(
        "INSERT OR REPLACE INTO backup_hashes(filename, filehash) VALUES (?, ?)",
        list(hashes.items()),
    )
    conn.commit()
    conn.close()


def _hash_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def _emit_progress(socketio_instance, task_id, event_name, message, detail=''):
    if socketio_instance and task_id:
        try:
            # Assuming 'level' is a new parameter for _emit_progress based on previous subtask's user feedback.
            # If _emit_progress definition doesn't support 'level', this will need adjustment.
            # For now, proceeding with the assumption it's supported.
            payload = {'task_id': task_id, 'status': message, 'detail': detail}
            if hasattr(_emit_progress, 'level_param_exists_marker'): # Check if level is a real param
                payload['level'] = detail.split(':')[0] if detail and ':' in detail else 'INFO' # Simplistic level derive
            socketio_instance.emit(event_name, payload)
            # logger.debug(f"Emitted {event_name} for {task_id}: {message} - {detail}")
        except Exception as e:
            logger.error(f"Failed to emit SocketIO event {event_name} for task {task_id}: {e}")

# Marker to indicate if the level parameter was considered during a refactor.
# This is a temporary solution for the agent to remember context across turns.
# In a real scenario, one would check the function signature directly.
_emit_progress.level_param_exists_marker = True

def _ensure_directory_exists(share_client, directory_path):
    """Ensure the specified directory exists on the share, creating it if necessary."""
    if not directory_path: # Cannot ensure empty or root path with this logic
        return
    dir_client = share_client.get_directory_client(directory_path)
    if not _client_exists(dir_client):
        try:
            dir_client.create_directory()
            logger.info(f"Created directory '{directory_path}' on share '{share_client.share_name}'.")
        except Exception as e:
            logger.error(f"Failed to create directory '{directory_path}' on share '{share_client.share_name}': {e}")
            raise


def upload_file(share_client, source_path, file_path):
    directory_path = os.path.dirname(file_path)
    if directory_path:
        directory_client = share_client.get_directory_client(directory_path)
        if not _client_exists(directory_client):
            try:
                logger.info(f"Attempting to create directory '{directory_path}' in share '{share_client.share_name}' from within upload_file.")
                directory_client.create_directory()
                logger.info(f"Successfully created directory '{directory_path}' in share '{share_client.share_name}'.")
            except Exception as e:
                logger.error(f"Failed to create directory '{directory_path}' in share '{share_client.share_name}' from within upload_file: {e}")
                raise RuntimeError(f"Failed to create parent directory '{directory_path}' for file '{file_path}'. Original error: {e}")
    file_client = share_client.get_file_client(file_path)
    with open(source_path, 'rb') as f:
        data = f.read()
    # ShareFileClient.upload_file does not support an 'overwrite' parameter.
    # Passing it causes a TypeError when the request is sent. Simply uploading
    # the data will overwrite the file if it already exists.
    file_client.upload_file(data)


def download_file(share_client, file_path, dest_path):
    file_client = share_client.get_file_client(file_path)
    if not _client_exists(file_client):
        return False
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    try:
        downloader = file_client.download_file()

        # Check for 0-byte file
        if downloader.properties.size == 0:
            with open(dest_path, 'wb') as f:
                pass # Create empty file
            logger.info(f"Successfully created empty file for 0-byte remote file '{file_path}' at '{dest_path}'.")
            return True

        # For non-empty files, proceed to read content
        content = downloader.readall()

        with open(dest_path, 'wb') as f:
            f.write(content)

        logger.info(f"Successfully downloaded '{file_path}' (size: {downloader.properties.size}) to '{dest_path}'.")
        return True

    except HttpResponseError as hre:
        # This will catch HTTP errors like 404 (ResourceNotFound, though _client_exists should catch this first),
        # 403 (Forbidden), 416 (InvalidRange), etc., that occur during download_file() or readall().
        logger.error(f"Failed to download file '{file_path}' from share '{share_client.share_name}'. "
                     f"Azure HTTP Error: {type(hre).__name__}, Status: {hre.status_code if hasattr(hre, 'status_code') else 'N/A'}, Details: {str(hre)}",
                     exc_info=True) # Log with full traceback
        return False
    except Exception as e:
        # Catch any other unexpected errors during download or file writing.
        logger.error(f"An unexpected error occurred downloading file '{file_path}' from share '{share_client.share_name}'. "
                     f"Exception: {type(e).__name__}, Details: {str(e)}",
                     exc_info=True) # Log with full traceback
        return False


def backup_database():
    service_client = _get_service_client()
    share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
    share_client = service_client.get_share_client(share_name)
    if not _client_exists(share_client):
        share_client.create_share()
    db_path = os.path.join(DATA_DIR, 'site.db')
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    file_name = f'site_{timestamp}.db'
    upload_file(share_client, db_path, file_name)
    return file_name


def save_floor_map_to_share(local_path, dest_filename=None):
    """Upload a single floor map file to the configured Azure File Share."""
    service_client = _get_service_client()
    share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media')
    share_client = service_client.get_share_client(share_name)
    if not _client_exists(share_client):
        share_client.create_share()
    if dest_filename is None:
        dest_filename = os.path.basename(local_path)
    file_path = f'floor_map_uploads/{dest_filename}'
    upload_file(share_client, local_path, file_path)


def backup_media():
    service_client = _get_service_client()
    share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media')
    share_client = service_client.get_share_client(share_name)
    if not _client_exists(share_client):
        share_client.create_share()
    # Upload floor map images
    for folder in (FLOOR_MAP_UPLOADS, RESOURCE_UPLOADS):
        if not os.path.isdir(folder):
            continue
        for fname in os.listdir(folder):
            fpath = os.path.join(folder, fname)
            if os.path.isfile(fpath):
                file_path = f'{os.path.basename(folder)}/{fname}'
                upload_file(share_client, fpath, file_path)


def backup_if_changed():
    """Backup the SQLite database and media files only when their hashes change.

    The database file lives in ``data/site.db`` and is not committed to the
    repository. This function uploads that file along with any images under
    ``static/floor_map_uploads`` and ``static/resource_uploads`` to the
    configured Azure File Shares.
    """
    hashes = _load_hashes()
    service_client = _get_service_client()

    # Database backup
    db_share = os.environ.get('AZURE_DB_SHARE', 'db-backups')
    db_client = service_client.get_share_client(db_share)
    if not _client_exists(db_client):
        db_client.create_share()
    db_local = os.path.join(DATA_DIR, 'site.db')
    db_rel = 'site.db'
    db_hash = _hash_file(db_local) if os.path.exists(db_local) else None
    if db_hash is None:
        logger.warning("Database file not found: %s", db_local)
    elif hashes.get(db_rel) != db_hash:
        upload_file(db_client, db_local, db_rel)
        hashes[db_rel] = db_hash
        logger.info("Uploaded database '%s' to share '%s'", db_rel, db_share)
    else:
        logger.info("Database unchanged; skipping upload")

    # Media backup
    media_share = os.environ.get('AZURE_MEDIA_SHARE', 'media')
    media_client = service_client.get_share_client(media_share)
    if not _client_exists(media_client):
        media_client.create_share()
    for folder in (FLOOR_MAP_UPLOADS, RESOURCE_UPLOADS):
        if not os.path.isdir(folder):
            continue
        for fname in os.listdir(folder):
            fpath = os.path.join(folder, fname)
            if not os.path.isfile(fpath):
                continue
            rel = f"{os.path.basename(folder)}/{fname}"
            f_hash = _hash_file(fpath)
            if hashes.get(rel) != f_hash:
                upload_file(media_client, fpath, rel)
                hashes[rel] = f_hash
                logger.info("Uploaded media file '%s' to share '%s'", rel, media_share)


    _save_hashes(hashes)


def restore_from_share():
    """Download DB and media files from Azure File Share if available."""
    service_client = _get_service_client()

    db_share = os.environ.get('AZURE_DB_SHARE', 'db-backups')
    db_client = service_client.get_share_client(db_share)
    if _client_exists(db_client):
        download_file(db_client, 'site.db', os.path.join(DATA_DIR, 'site.db'))

    media_share = os.environ.get('AZURE_MEDIA_SHARE', 'media')
    media_client = service_client.get_share_client(media_share)
    if _client_exists(media_client):
        for prefix in ('floor_map_uploads', 'resource_uploads'):
            directory_client = media_client.get_directory_client(prefix)
            if not _client_exists(directory_client):
                continue
            for item in directory_client.list_directories_and_files():
                file_path = f"{prefix}/{item['name']}"
                dest = os.path.join(STATIC_DIR, prefix, item['name'])
                download_file(media_client, file_path, dest)


def main():
    """Run an incremental backup when executed as a script."""
    backup_if_changed()
    print('Backup completed.')


def create_full_backup(timestamp_str, map_config_data=None, resource_configs_data=None, user_configs_data=None, socketio_instance=None, task_id=None):
    """
    Creates a full backup of the database, map configuration, and media files.

    Args:
        timestamp_str (str): The timestamp string in "YYYYMMDD_HHMMSS" format.
        map_config_data (dict, optional): Actual map configuration data to back up.
        resource_configs_data (list, optional): Resource configurations data.
        user_configs_data (dict, optional): User and Role configurations data.
        socketio_instance: Optional SocketIO instance for progress emitting.
        task_id: Optional task ID for SocketIO progress emitting.
    """
    _emit_progress(socketio_instance, task_id, 'backup_progress', 'Starting full backup processing...', f'Timestamp: {timestamp_str}')
    logger.info(f"Starting full backup for timestamp: {timestamp_str}")
    service_client = _get_service_client()
    overall_success = True

    # Database Backup
    db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
    db_share_client = service_client.get_share_client(db_share_name)
    if not _client_exists(db_share_client):
        logger.info(f"Creating share '{db_share_name}' for database backups.")
        db_share_client.create_share()

    _ensure_directory_exists(db_share_client, DB_BACKUPS_DIR)

    remote_db_filename = f"{DB_FILENAME_PREFIX}{timestamp_str}.db"
    remote_db_path = f"{DB_BACKUPS_DIR}/{remote_db_filename}"
    local_db_path = os.path.join(DATA_DIR, 'site.db')
    _emit_progress(socketio_instance, task_id, 'backup_progress', 'Backing up database...', f'{local_db_path} to {db_share_name}/{remote_db_path}')

    if os.path.exists(local_db_path):
        try:
            logger.info(f"Attempting database backup: Share='{db_share_client.share_name}', Path='{remote_db_path}', LocalSource='{local_db_path}'")
            upload_file(db_share_client, local_db_path, remote_db_path)
            logger.info(f"Successfully backed up database to '{db_share_name}/{remote_db_path}'.")
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'Database backup complete.')
        except Exception as e:
            logger.error(f"Failed to backup database to '{db_share_name}/{remote_db_path}': {e}")
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'Database backup failed.', str(e))
            overall_success = False
    else:
        logger.warning(f"Local database file not found at '{local_db_path}'. Skipping database backup.")
        _emit_progress(socketio_instance, task_id, 'backup_progress', 'Database backup skipped (local file not found).')
        overall_success = False # Deem DB backup essential for overall success

    # Map Configuration JSON Backup
    config_share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
    config_share_client = service_client.get_share_client(config_share_name)
    if not _client_exists(config_share_client):
        logger.info(f"Creating share '{config_share_name}' for config backups.")
        config_share_client.create_share()

    _ensure_directory_exists(config_share_client, CONFIG_BACKUPS_DIR)

    remote_config_filename = f"{MAP_CONFIG_FILENAME_PREFIX}{timestamp_str}.json"
    remote_config_path = f"{CONFIG_BACKUPS_DIR}/{remote_config_filename}"
    _emit_progress(socketio_instance, task_id, 'backup_progress', 'Backing up map configuration...', f'To {config_share_name}/{remote_config_path}')

    if map_config_data:
        try:
            # Ensure parent directory for the file itself is created by get_file_client logic
            # This is usually handled by upload_file, but here we use file_client directly.
            # Parent dir of remote_config_path is CONFIG_BACKUPS_DIR, which is already ensured.
            file_client = config_share_client.get_file_client(remote_config_path)
            config_json_bytes = json.dumps(map_config_data, indent=2).encode('utf-8')
            logger.info(f"Attempting map configuration backup: Share='{config_share_client.share_name}', Path='{remote_config_path}'")
            file_client.upload_file(data=config_json_bytes)
            logger.info(f"Successfully backed up map configuration to '{config_share_name}/{remote_config_path}'.")
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'Map configuration backup complete.')
        except Exception as e:
            logger.error(f"Failed to backup map configuration to '{config_share_name}/{remote_config_path}': {e}", exc_info=True)
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'Map configuration backup failed.', str(e))
            overall_success = False # If map config was provided but failed to upload
    else:
        logger.warning(f"No map_config_data provided for timestamp {timestamp_str}. Skipping map configuration backup.")
        _emit_progress(socketio_instance, task_id, 'backup_progress', 'Map configuration backup skipped (no data provided).')

    # Resource Configurations Backup
    remote_resource_configs_filename = f"resource_configs_{timestamp_str}.json"
    remote_resource_configs_path = f"{CONFIG_BACKUPS_DIR}/{remote_resource_configs_filename}"
    _emit_progress(socketio_instance, task_id, 'backup_progress', 'Backing up resource configurations...', f'To {config_share_name}/{remote_resource_configs_path}')
    if resource_configs_data: # resource_configs_data is the list passed to the function
        try:
            resource_configs_json_bytes = json.dumps(resource_configs_data, indent=2).encode('utf-8')
            # config_share_client is already initialized from map config backup section
            file_client_rc = config_share_client.get_file_client(remote_resource_configs_path)
            logger.info(f"Attempting resource configurations backup: Share='{config_share_client.share_name}', Path='{remote_resource_configs_path}'")
            file_client_rc.upload_file(data=resource_configs_json_bytes) # No overwrite=True
            logger.info(f"Successfully backed up resource configurations to '{config_share_name}/{remote_resource_configs_path}'.")
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'Resource configurations backup complete.')
        except Exception as e:
            logger.error(f"Failed to backup resource configurations to '{config_share_name}/{remote_resource_configs_path}': {e}", exc_info=True)
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'Resource configurations backup failed.', str(e))
            overall_success = False # If resource configs were provided but failed to upload
    else:
        logger.warning(f"No resource_configs_data provided for timestamp {timestamp_str}. Skipping resource configurations backup.")
        _emit_progress(socketio_instance, task_id, 'backup_progress', 'Resource configurations backup skipped (no data).')

    # User and Role Configurations Backup
    remote_user_configs_filename = f"user_configs_{timestamp_str}.json"
    remote_user_configs_path = f"{CONFIG_BACKUPS_DIR}/{remote_user_configs_filename}"
    _emit_progress(socketio_instance, task_id, 'backup_progress', 'Backing up user/role configurations...', f'To {config_share_name}/{remote_user_configs_path}')
    if user_configs_data: # user_configs_data is the dict {'users': [...], 'roles': [...]}
        try:
            user_configs_json_bytes = json.dumps(user_configs_data, indent=2).encode('utf-8')
            file_client_uc = config_share_client.get_file_client(remote_user_configs_path)
            logger.info(f"Attempting user/role configurations backup: Share='{config_share_client.share_name}', Path='{remote_user_configs_path}'")
            file_client_uc.upload_file(data=user_configs_json_bytes) # No overwrite=True
            logger.info(f"Successfully backed up user/role configurations to '{config_share_name}/{remote_user_configs_path}'.")
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'User/role configurations backup complete.')
        except Exception as e:
            logger.error(f"Failed to backup user/role configurations to '{config_share_name}/{remote_user_configs_path}': {e}", exc_info=True)
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'User/role configurations backup failed.', str(e))
            overall_success = False # If user configs were provided but failed to upload
    else:
        logger.warning(f"No user_configs_data provided for timestamp {timestamp_str}. Skipping user/role configurations backup.")
        _emit_progress(socketio_instance, task_id, 'backup_progress', 'User/role configurations backup skipped (no data).')

    # Media Backup (Floor Maps & Resource Uploads)
    media_share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media')
    media_share_client = service_client.get_share_client(media_share_name)
    if not _client_exists(media_share_client):
        logger.info(f"Creating share '{media_share_name}' for media backups.")
        media_share_client.create_share()

    # Ensure the base directory for all media backups exists first
    logger.info(f"Checking/Creating base media backup directory '{MEDIA_BACKUPS_DIR_BASE}' on share '{media_share_name}'.")
    media_base_dir_client = media_share_client.get_directory_client(MEDIA_BACKUPS_DIR_BASE)
    if not _client_exists(media_base_dir_client):
        try:
            logger.info(f"Base media backup directory '{MEDIA_BACKUPS_DIR_BASE}' not found on share '{media_share_name}'. Attempting to create.")
            media_base_dir_client.create_directory()
            logger.info(f"Successfully created base media backup directory '{MEDIA_BACKUPS_DIR_BASE}' on share '{media_share_name}'.")
        except Exception as e:
            logger.error(f"CRITICAL: Failed to create base media backup directory '{MEDIA_BACKUPS_DIR_BASE}' on share '{media_share_name}': {e}", exc_info=True)
            raise RuntimeError(f"Could not create base media backup directory '{MEDIA_BACKUPS_DIR_BASE}'. Error: {e}")
    else:
        logger.info(f"Base media backup directory '{MEDIA_BACKUPS_DIR_BASE}' already exists on share '{media_share_name}'.")

    # Backup FLOOR_MAP_UPLOADS
    remote_floor_map_dir = f"{MEDIA_BACKUPS_DIR_BASE}/floor_map_uploads_{timestamp_str}"
    # Now, _ensure_directory_exists should correctly create 'floor_map_uploads_TIMESTAMP' inside 'media_backups'
    _ensure_directory_exists(media_share_client, remote_floor_map_dir)
    if os.path.isdir(FLOOR_MAP_UPLOADS):
        for filename in os.listdir(FLOOR_MAP_UPLOADS):
            local_file_path = os.path.join(FLOOR_MAP_UPLOADS, filename)
            if os.path.isfile(local_file_path):
                remote_file_path = f"{remote_floor_map_dir}/{filename}"
                _emit_progress(socketio_instance, task_id, 'backup_progress', f'Backing up floor map: {filename}', local_file_path)
                try:
                    logger.info(f"Attempting floor map backup: Share='{media_share_client.share_name}', Path='{remote_file_path}', LocalSource='{local_file_path}'")
                    upload_file(media_share_client, local_file_path, remote_file_path)
                    logger.info(f"Successfully backed up media file to '{media_share_name}/{remote_file_path}'.")
                except Exception as e:
                    logger.error(f"Failed to backup media file '{local_file_path}' to '{media_share_name}/{remote_file_path}': {e}")
                    _emit_progress(socketio_instance, task_id, 'backup_progress', f'Failed to backup floor map: {filename}', str(e))
    else:
        logger.warning(f"Local directory for floor maps not found at '{FLOOR_MAP_UPLOADS}'. Skipping floor map backup.")
        _emit_progress(socketio_instance, task_id, 'backup_progress', 'Floor map backup skipped (directory not found).')
    _emit_progress(socketio_instance, task_id, 'backup_progress', 'Floor map backup phase complete.')

    # Backup RESOURCE_UPLOADS
    remote_resource_uploads_dir = f"{MEDIA_BACKUPS_DIR_BASE}/resource_uploads_{timestamp_str}"
    _ensure_directory_exists(media_share_client, remote_resource_uploads_dir)
    if os.path.isdir(RESOURCE_UPLOADS):
        for filename in os.listdir(RESOURCE_UPLOADS):
            local_file_path = os.path.join(RESOURCE_UPLOADS, filename)
            if os.path.isfile(local_file_path):
                remote_file_path = f"{remote_resource_uploads_dir}/{filename}"
                _emit_progress(socketio_instance, task_id, 'backup_progress', f'Backing up resource file: {filename}', local_file_path)
                try:
                    logger.info(f"Attempting resource image backup: Share='{media_share_client.share_name}', Path='{remote_file_path}', LocalSource='{local_file_path}'")
                    upload_file(media_share_client, local_file_path, remote_file_path)
                    logger.info(f"Successfully backed up media file to '{media_share_name}/{remote_file_path}'.")
                except Exception as e:
                    logger.error(f"Failed to backup media file '{local_file_path}' to '{media_share_name}/{remote_file_path}': {e}")
                    _emit_progress(socketio_instance, task_id, 'backup_progress', f'Failed to backup resource file: {filename}', str(e))
    else:
        logger.warning(f"Local directory for resource uploads not found at '{RESOURCE_UPLOADS}'. Skipping resource uploads backup.")
        _emit_progress(socketio_instance, task_id, 'backup_progress', 'Resource uploads backup skipped (directory not found).')
    _emit_progress(socketio_instance, task_id, 'backup_progress', 'Resource uploads backup phase complete.')

    _emit_progress(socketio_instance, task_id, 'backup_progress', f'Main backup process completed. Overall success so far: {overall_success}')

    if overall_success:
        _emit_progress(socketio_instance, task_id, 'backup_progress', 'Checking retention policy...')
        try:
            retention_days_str = os.environ.get('BACKUP_RETENTION_DAYS')
            if not retention_days_str:
                logger.info("BACKUP_RETENTION_DAYS not set. Skipping retention policy.")
                _emit_progress(socketio_instance, task_id, 'backup_progress', 'Retention policy skipped (not configured).')
                return overall_success

            try:
                retention_days = int(retention_days_str)
            except ValueError:
                logger.error(f"Invalid BACKUP_RETENTION_DAYS value: '{retention_days_str}'. Must be an integer.")
                _emit_progress(socketio_instance, task_id, 'backup_progress', f'Retention policy error (invalid config value: {retention_days_str}).')
                return overall_success # Still return true as backup itself was successful

            if retention_days <= 0:
                logger.info(f"Backup retention is disabled (BACKUP_RETENTION_DAYS={retention_days}). Skipping.")
                _emit_progress(socketio_instance, task_id, 'backup_progress', 'Retention policy skipped (disabled).')
                return overall_success

            logger.info(f"Applying backup retention policy: Keep last {retention_days} days/sets.")
            _emit_progress(socketio_instance, task_id, 'backup_progress', f'Applying retention: keep last {retention_days} backups.')
            available_backups = list_available_backups() # Sorted newest first

            if len(available_backups) > retention_days:
                backups_to_delete_count = len(available_backups) - retention_days
                logger.info(f"Found {len(available_backups)} backups. Need to delete {backups_to_delete_count} oldest backup(s).")
                _emit_progress(socketio_instance, task_id, 'backup_progress', f'Found {len(available_backups)} backups, deleting {backups_to_delete_count} oldest ones.')

                timestamps_to_delete = available_backups[retention_days:]

                for ts_to_delete in timestamps_to_delete:
                    logger.info(f"Retention policy: Deleting backup set for timestamp {ts_to_delete}.")
                    _emit_progress(socketio_instance, task_id, 'backup_progress', f'Retention: Deleting backup set {ts_to_delete}')
                    delete_success = delete_backup_set(ts_to_delete) # delete_backup_set has its own logging for success/failure of individual components
                    _emit_progress(socketio_instance, task_id, 'backup_progress', f'Deletion of {ts_to_delete} {"completed" if delete_success else "had issues"}.')
            else:
                logger.info(f"Number of available backups ({len(available_backups)}) is within retention limit ({retention_days}). No old backups to delete.")
                _emit_progress(socketio_instance, task_id, 'backup_progress', 'No old backups to delete due to retention policy.')
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'Retention policy check complete.')
        except Exception as e:
            logger.error(f"Error during backup retention policy execution: {e}", exc_info=True)
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'Error during retention policy execution.', str(e))
            # Do not change overall_success here, as the backup itself was successful.
            # Retention is a secondary operation.

    # --- Manifest Creation ---
    if overall_success: # Only create manifest if all primary backup operations were successful
        _emit_progress(socketio_instance, task_id, 'backup_progress', 'Creating backup manifest...')
        logger.info(f"Creating backup manifest for timestamp: {timestamp_str}")
        manifest_data = {'timestamp': timestamp_str, 'files': [], 'media_directories_expected': []}

        # Database entry in manifest
        if os.path.exists(local_db_path): # Check if DB was actually backed up
            try:
                db_hash = _hash_file(local_db_path)
                manifest_data['files'].append({
                    'path': remote_db_path, # remote_db_path defined earlier in the function
                    'type': 'database',
                    'sha256': db_hash,
                    'share': db_share_name
                })
            except Exception as e:
                logger.error(f"Failed to hash local database for manifest: {e}")
                _emit_progress(socketio_instance, task_id, 'backup_progress', 'Error hashing database for manifest.', str(e))
                # Potentially mark manifest as incomplete or skip it

        # Map Configuration entry in manifest
        if map_config_data: # Check if map_config_data was provided and presumably uploaded
            try:
                config_json_bytes = json.dumps(map_config_data, indent=2).encode('utf-8')
                config_hash = hashlib.sha256(config_json_bytes).hexdigest()
                manifest_data['files'].append({
                    'path': remote_config_path, # remote_config_path defined earlier
                    'type': 'map_config',
                    'sha256': config_hash,
                    'share': config_share_name
                })
            except Exception as e:
                logger.error(f"Failed to hash map configuration for manifest: {e}")
                _emit_progress(socketio_instance, task_id, 'backup_progress', 'Error hashing map_config for manifest.', str(e))

        # Resource Configurations entry in manifest
        if resource_configs_data: # Check if data was provided and presumably uploaded
            try:
                # Re-serialize to get bytes for hash, or use stored bytes if available
                rc_bytes_for_hash = json.dumps(resource_configs_data, indent=2).encode('utf-8')
                rc_hash = hashlib.sha256(rc_bytes_for_hash).hexdigest()
                manifest_data['files'].append({
                    'path': remote_resource_configs_path, # Defined earlier in the function
                    'type': 'resource_configs',
                    'sha256': rc_hash,
                    'share': config_share_name # Defined earlier
                })
            except Exception as e:
                logger.error(f"Failed to hash resource_configs for manifest: {e}")
                _emit_progress(socketio_instance, task_id, 'backup_progress', 'Error hashing resource_configs for manifest.', str(e))

        # User Configurations entry in manifest
        if user_configs_data: # Check if data was provided and presumably uploaded
            try:
                uc_bytes_for_hash = json.dumps(user_configs_data, indent=2).encode('utf-8')
                uc_hash = hashlib.sha256(uc_bytes_for_hash).hexdigest()
                manifest_data['files'].append({
                    'path': remote_user_configs_path, # Defined earlier
                    'type': 'user_configs',
                    'sha256': uc_hash,
                    'share': config_share_name # Defined earlier
                })
            except Exception as e:
                logger.error(f"Failed to hash user_configs for manifest: {e}")
                _emit_progress(socketio_instance, task_id, 'backup_progress', 'Error hashing user_configs for manifest.', str(e))

        # Media Directories entries in manifest
        if os.path.isdir(FLOOR_MAP_UPLOADS):
            num_floor_maps = len([name for name in os.listdir(FLOOR_MAP_UPLOADS) if os.path.isfile(os.path.join(FLOOR_MAP_UPLOADS, name))])
            manifest_data['media_directories_expected'].append({
                'path': remote_floor_map_dir, # remote_floor_map_dir defined earlier
                'type': 'floor_maps',
                'expected_file_count': num_floor_maps,
                'share': media_share_name
            })

        if os.path.isdir(RESOURCE_UPLOADS):
            num_resource_uploads = len([name for name in os.listdir(RESOURCE_UPLOADS) if os.path.isfile(os.path.join(RESOURCE_UPLOADS, name))])
            manifest_data['media_directories_expected'].append({
                'path': remote_resource_uploads_dir, # remote_resource_uploads_dir defined earlier
                'type': 'resource_uploads',
                'expected_file_count': num_resource_uploads,
                'share': media_share_name
            })

        # Upload Manifest File (to DB share for simplicity)
        manifest_filename = f"backup_manifest_{timestamp_str}.json"
        remote_manifest_path = f"{DB_BACKUPS_DIR}/{manifest_filename}"
        try:
            manifest_json_bytes = json.dumps(manifest_data, indent=2).encode('utf-8')
            # db_share_client is already defined and initialized
            manifest_file_client = db_share_client.get_file_client(remote_manifest_path)
            logger.info(f"Attempting manifest upload: Share='{db_share_client.share_name}', Path='{remote_manifest_path}'")
            manifest_file_client.upload_file(data=manifest_json_bytes, overwrite=True)
            logger.info(f"Successfully uploaded backup manifest to '{db_share_name}/{remote_manifest_path}'.")
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'Backup manifest uploaded successfully.')
        except Exception as e:
            logger.error(f"Error during backup manifest creation or upload to '{db_share_name}/{remote_manifest_path}': {e}", exc_info=True)
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'Backup manifest creation/upload FAILED.', str(e))
            overall_success = False # Crucial change

    if overall_success:
        _emit_progress(socketio_instance, task_id, 'backup_progress', f'Backup completed with overall success: True', 'SUCCESS')
    else:
        _emit_progress(socketio_instance, task_id, 'backup_progress', f'Backup completed with overall success: False. Check server logs for details.', 'ERROR')
    return overall_success


def verify_backup_set(timestamp_str, socketio_instance=None, task_id=None):
    """
    Verifies a backup set against its manifest.

    Args:
        timestamp_str (str): The timestamp of the backup set to verify.
        socketio_instance: Optional SocketIO instance for progress.
        task_id: Optional task ID for SocketIO.

    Returns:
        dict: A dictionary containing verification results.
    """
    verification_results = {
        'timestamp': timestamp_str,
        'status': 'pending', # Possible statuses: pending, manifest_missing, manifest_corrupt, failed_verification, verified_present
        'checks': [], # List of dicts detailing each check
        'errors': []  # List of error messages
    }
    component_name = f"BackupSetVerify-{timestamp_str}"

    def _emit_verify_progress(status_msg, detail='', level="INFO"):
        logger.info(f"[{component_name}] {status_msg} {detail}")
        if socketio_instance and task_id:
            _emit_progress(socketio_instance, task_id, 'backup_verification_progress', status_msg, detail)

    _emit_verify_progress(f"Starting verification for backup set: {timestamp_str}")

    try:
        service_client = _get_service_client()
        db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
        db_share_client = service_client.get_share_client(db_share_name)

        if not _client_exists(db_share_client):
            msg = f"Database share '{db_share_name}' not found."
            verification_results['errors'].append(msg)
            verification_results['status'] = 'failed_verification'
            _emit_verify_progress(msg, level="ERROR")
            return verification_results

        # 1. Download and Parse Manifest
        manifest_filename = f"backup_manifest_{timestamp_str}.json"
        remote_manifest_path = f"{DB_BACKUPS_DIR}/{manifest_filename}"
        manifest_file_client = db_share_client.get_file_client(remote_manifest_path)

        if not _client_exists(manifest_file_client):
            msg = f"Manifest file '{remote_manifest_path}' not found on share '{db_share_name}'."
            verification_results['errors'].append(msg)
            verification_results['status'] = 'manifest_missing'
            _emit_verify_progress(msg, level="ERROR")
            return verification_results

        manifest_data = None
        try:
            downloader = manifest_file_client.download_file()
            manifest_bytes = downloader.readall()
            manifest_data = json.loads(manifest_bytes.decode('utf-8'))
            _emit_verify_progress("Manifest downloaded and parsed successfully.")
            verification_results['checks'].append({'item': 'manifest', 'status': 'found_and_parsed', 'path': remote_manifest_path})
        except Exception as e:
            msg = f"Error downloading or parsing manifest '{remote_manifest_path}': {e}"
            verification_results['errors'].append(msg)
            verification_results['status'] = 'manifest_corrupt'
            _emit_verify_progress(msg, level="ERROR")
            return verification_results

        # 2. Verify Files from Manifest (manifest_data['files'])
        config_share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups') # Used if map_config is in manifest
        config_share_client = service_client.get_share_client(config_share_name) # Initialize once

        for file_entry in manifest_data.get('files', []):
            entry_path = file_entry.get('path')
            entry_type = file_entry.get('type')
            entry_share_name = file_entry.get('share')
            # entry_hash = file_entry.get('sha256') # For future checksum verification

            check_item = {'item': entry_path, 'type': entry_type, 'status': 'unknown'}
            _emit_verify_progress(f"Verifying file: {entry_path} (type: {entry_type})")

            target_share_client = None
            if entry_share_name == db_share_name:
                target_share_client = db_share_client
            elif entry_share_name == config_share_name:
                target_share_client = config_share_client
            else:
                msg = f"Unknown share '{entry_share_name}' for file '{entry_path}' in manifest."
                verification_results['errors'].append(msg)
                check_item['status'] = 'error_unknown_share'
                _emit_verify_progress(msg, level="ERROR")
                verification_results['checks'].append(check_item)
                continue

            if not _client_exists(target_share_client):
                msg = f"Share '{entry_share_name}' for file '{entry_path}' does not exist."
                verification_results['errors'].append(msg)
                check_item['status'] = 'error_share_missing'
                _emit_verify_progress(msg, level="ERROR")
                verification_results['checks'].append(check_item)
                continue

            file_client_to_check = target_share_client.get_file_client(entry_path)
            if _client_exists(file_client_to_check):
                check_item['status'] = 'found'
                # Optional: Add checksum verification here if feasible in future
                # For now, presence is the main check.
            else:
                msg = f"Missing file: {entry_path} on share {entry_share_name}"
                verification_results['errors'].append(msg)
                check_item['status'] = 'missing'
            verification_results['checks'].append(check_item)
            _emit_verify_progress(f"File {entry_path}: {check_item['status']}")

        # 3. Verify Media Directories from Manifest (manifest_data['media_directories_expected'])
        media_share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media') # Used for media
        media_share_client = service_client.get_share_client(media_share_name)

        for dir_entry in manifest_data.get('media_directories_expected', []):
            dir_path = dir_entry.get('path')
            dir_type = dir_entry.get('type')
            expected_count = dir_entry.get('expected_file_count')
            entry_share_name = dir_entry.get('share')

            check_item = {'item': dir_path, 'type': dir_type, 'status': 'unknown', 'expected_count': expected_count, 'actual_count': 0}
            _emit_verify_progress(f"Verifying media directory: {dir_path} (type: {dir_type})")

            if entry_share_name != media_share_name:
                msg = f"Manifest inconsistency: Media directory '{dir_path}' expected on share '{media_share_name}' but manifest says '{entry_share_name}'."
                verification_results['errors'].append(msg)
                check_item['status'] = 'error_share_mismatch'
                _emit_verify_progress(msg, level="ERROR")
                verification_results['checks'].append(check_item)
                continue

            if not _client_exists(media_share_client):
                msg = f"Media share '{media_share_name}' for directory '{dir_path}' does not exist."
                verification_results['errors'].append(msg)
                check_item['status'] = 'error_share_missing'
                _emit_verify_progress(msg, level="ERROR")
                verification_results['checks'].append(check_item)
                continue

            dir_client_to_check = media_share_client.get_directory_client(dir_path)
            if _client_exists(dir_client_to_check):
                try:
                    remote_files = list(dir_client_to_check.list_directories_and_files())
                    actual_count = len([f for f in remote_files if not f['is_directory']])
                    check_item['actual_count'] = actual_count
                    if actual_count == expected_count:
                        check_item['status'] = 'found_count_match'
                    else:
                        msg = f"File count mismatch for {dir_path}: Expected {expected_count}, Found {actual_count}."
                        verification_results['errors'].append(msg) # Considered an error for verification
                        check_item['status'] = 'found_count_mismatch'
                        _emit_verify_progress(msg, level="WARNING")
                except Exception as e:
                    msg = f"Error listing files in remote directory '{dir_path}': {e}"
                    verification_results['errors'].append(msg)
                    check_item['status'] = 'error_listing_files'
                    _emit_verify_progress(msg, level="ERROR")
            else:
                msg = f"Missing media directory: {dir_path} on share {media_share_name}"
                verification_results['errors'].append(msg)
                check_item['status'] = 'missing'
            verification_results['checks'].append(check_item)
            _emit_verify_progress(f"Directory {dir_path}: {check_item['status']}")

        # 4. Determine Overall Status
        if verification_results['errors']:
            verification_results['status'] = 'failed_verification'
        else:
            verification_results['status'] = 'verified_present'

        _emit_verify_progress(f"Verification finished for {timestamp_str}. Status: {verification_results['status']}", level="INFO" if verification_results['status'] == 'verified_present' else "ERROR")

    except Exception as e:
        msg = f"Critical error during backup verification for {timestamp_str}: {e}"
        logger.error(msg, exc_info=True)
        verification_results['errors'].append(msg)
        verification_results['status'] = 'critical_error'
        _emit_verify_progress(msg, level="CRITICAL")

    return verification_results


def restore_database_component(timestamp_str, db_share_client, dry_run=False, socketio_instance=None, task_id=None):
    """
    Restores the database from a backup.

    Returns:
        tuple: (success_bool, message_str, actions_list, restored_db_path_or_placeholder_str)
    """
    actions = []
    dry_run_prefix = "DRY RUN: " if dry_run else ""
    component_name = "Database"
    restored_db_path = None

    _emit_progress(socketio_instance, task_id, 'restore_progress', f'{dry_run_prefix}Starting {component_name} restore component...', f'Timestamp: {timestamp_str}')

    remote_db_filename = f"{DB_FILENAME_PREFIX}{timestamp_str}.db"
    azure_db_path = f"{DB_BACKUPS_DIR}/{remote_db_filename}"
    local_db_target_path = os.path.join(DATA_DIR, 'site.db')

    db_file_client = db_share_client.get_file_client(azure_db_path)

    if not _client_exists(db_file_client):
        err_msg = f"{dry_run_prefix}{component_name} backup file '{azure_db_path}' not found on share '{db_share_client.share_name}'."
        logger.error(err_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', err_msg, "ERROR")
        if dry_run: actions.append(err_msg)
        return False, err_msg, actions, None

    if dry_run:
        action_msg = f"DRY RUN: Would download {component_name} from '{db_share_client.share_name}/{azure_db_path}' to '{local_db_target_path}'."
        actions.append(action_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', action_msg)
        logger.info(action_msg)
        restored_db_path = "DRY_RUN_DB_PATH_PLACEHOLDER"
        success_msg = f"DRY RUN: {component_name} component finished."
        _emit_progress(socketio_instance, task_id, 'restore_progress', success_msg)
        logger.info(success_msg)
        return True, success_msg, actions, restored_db_path
    else:
        _emit_progress(socketio_instance, task_id, 'restore_progress', f'Restoring {component_name}...', f'{azure_db_path} to {local_db_target_path}')
        logger.info(f"Restoring {component_name} from '{db_share_client.share_name}/{azure_db_path}' to '{local_db_target_path}'.")
        if download_file(db_share_client, azure_db_path, local_db_target_path):
            success_msg = f"{component_name} restored successfully."
            logger.info(success_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', f'{component_name} download complete.')
            restored_db_path = local_db_target_path
            return True, success_msg, actions, restored_db_path
        else:
            err_msg = f"{component_name} restoration failed during download."
            logger.error(err_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', err_msg, "ERROR")
            return False, err_msg, actions, None


def download_map_config_component(timestamp_str, config_share_client, dry_run=False, socketio_instance=None, task_id=None):
    """
    Downloads the map configuration JSON from a backup.

    Returns:
        tuple: (success_bool, message_str, actions_list, downloaded_config_path_or_placeholder_str)
    """
    actions = []
    dry_run_prefix = "DRY RUN: " if dry_run else ""
    component_name = "Map Configuration"
    downloaded_config_path = None

    _emit_progress(socketio_instance, task_id, 'restore_progress', f'{dry_run_prefix}Starting {component_name} download component...', f'Timestamp: {timestamp_str}')

    remote_config_filename = f"{MAP_CONFIG_FILENAME_PREFIX}{timestamp_str}.json"
    azure_config_path = f"{CONFIG_BACKUPS_DIR}/{remote_config_filename}"
    # Note: DATA_DIR is a global constant
    local_config_target_path = os.path.join(DATA_DIR, remote_config_filename)

    config_file_client = config_share_client.get_file_client(azure_config_path)

    if not _client_exists(config_file_client):
        warn_msg = f"{dry_run_prefix}{component_name} backup file '{azure_config_path}' not found on share '{config_share_client.share_name}'. Skipping."
        logger.warning(warn_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg, azure_config_path)
        if dry_run: actions.append(warn_msg)
        # This is not a critical failure for the overall restore, so return True.
        return True, warn_msg, actions, None

    if dry_run:
        action_msg = f"DRY RUN: Would download {component_name} from '{config_share_client.share_name}/{azure_config_path}' to '{local_config_target_path}'."
        actions.append(action_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', action_msg)
        logger.info(action_msg)
        downloaded_config_path = "DRY_RUN_MAP_CONFIG_PATH_PLACEHOLDER"
        success_msg = f"DRY RUN: {component_name} component finished (simulated download)."
        _emit_progress(socketio_instance, task_id, 'restore_progress', success_msg)
        logger.info(success_msg)
        return True, success_msg, actions, downloaded_config_path
    else:
        _emit_progress(socketio_instance, task_id, 'restore_progress', f'Downloading {component_name}...', f'{azure_config_path} to {local_config_target_path}')
        logger.info(f"Downloading {component_name} from '{config_share_client.share_name}/{azure_config_path}' to '{local_config_target_path}'.")
        if download_file(config_share_client, azure_config_path, local_config_target_path):
            success_msg = f"{component_name} JSON downloaded successfully."
            logger.info(success_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', f'{component_name} download complete.')
            downloaded_config_path = local_config_target_path
            return True, success_msg, actions, downloaded_config_path
        else:
            # Log as warning because map config might be optional for some restore scenarios.
            warn_msg = f"{component_name} JSON download failed from '{azure_config_path}'."
            logger.warning(warn_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg, "WARNING")
            return True, warn_msg, actions, None # Non-critical failure, return True


def download_resource_configs_component(timestamp_str, config_share_client, dry_run=False, socketio_instance=None, task_id=None):
    """
    Downloads the resource configurations JSON from a backup.

    Returns:
        tuple: (success_bool, message_str, actions_list, downloaded_config_path_or_placeholder_str)
    """
    actions = []
    dry_run_prefix = "DRY RUN: " if dry_run else ""
    component_name = "Resource Configurations"
    downloaded_config_path = None

    _emit_progress(socketio_instance, task_id, 'restore_progress', f'{dry_run_prefix}Starting {component_name} download component...', f'Timestamp: {timestamp_str}')

    remote_config_filename = f"resource_configs_{timestamp_str}.json" # Changed filename
    azure_config_path = f"{CONFIG_BACKUPS_DIR}/{remote_config_filename}"
    local_config_target_path = os.path.join(DATA_DIR, remote_config_filename) # DATA_DIR is global

    config_file_client = config_share_client.get_file_client(azure_config_path)

    if not _client_exists(config_file_client):
        warn_msg = f"{dry_run_prefix}{component_name} backup file '{azure_config_path}' not found on share '{config_share_client.share_name}'. Skipping."
        logger.warning(warn_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg, azure_config_path)
        if dry_run: actions.append(warn_msg)
        return True, warn_msg, actions, None # Not critical failure

    if dry_run:
        action_msg = f"DRY RUN: Would download {component_name} from '{config_share_client.share_name}/{azure_config_path}' to '{local_config_target_path}'."
        actions.append(action_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', action_msg)
        logger.info(action_msg)
        downloaded_config_path = "DRY_RUN_RESOURCE_CONFIGS_PATH_PLACEHOLDER" # Placeholder
        success_msg = f"DRY RUN: {component_name} component finished (simulated download)."
        _emit_progress(socketio_instance, task_id, 'restore_progress', success_msg)
        logger.info(success_msg)
        return True, success_msg, actions, downloaded_config_path
    else:
        _emit_progress(socketio_instance, task_id, 'restore_progress', f'Downloading {component_name}...', f'{azure_config_path} to {local_config_target_path}')
        logger.info(f"Downloading {component_name} from '{config_share_client.share_name}/{azure_config_path}' to '{local_config_target_path}'.")
        if download_file(config_share_client, azure_config_path, local_config_target_path):
            success_msg = f"{component_name} JSON downloaded successfully."
            logger.info(success_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', f'{component_name} download complete.')
            downloaded_config_path = local_config_target_path
            return True, success_msg, actions, downloaded_config_path
        else:
            warn_msg = f"{component_name} JSON download failed from '{azure_config_path}'." # Non-critical
            logger.warning(warn_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg, "WARNING")
            return True, warn_msg, actions, None


def download_user_configs_component(timestamp_str, config_share_client, dry_run=False, socketio_instance=None, task_id=None):
    """
    Downloads the user and role configurations JSON from a backup.

    Returns:
        tuple: (success_bool, message_str, actions_list, downloaded_config_path_or_placeholder_str)
    """
    actions = []
    dry_run_prefix = "DRY RUN: " if dry_run else ""
    component_name = "User/Role Configurations" # Changed component name
    downloaded_config_path = None

    _emit_progress(socketio_instance, task_id, 'restore_progress', f'{dry_run_prefix}Starting {component_name} download component...', f'Timestamp: {timestamp_str}')

    remote_config_filename = f"user_configs_{timestamp_str}.json" # Changed filename
    azure_config_path = f"{CONFIG_BACKUPS_DIR}/{remote_config_filename}"
    local_config_target_path = os.path.join(DATA_DIR, remote_config_filename)

    config_file_client = config_share_client.get_file_client(azure_config_path)

    if not _client_exists(config_file_client):
        warn_msg = f"{dry_run_prefix}{component_name} backup file '{azure_config_path}' not found on share '{config_share_client.share_name}'. Skipping."
        logger.warning(warn_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg, azure_config_path)
        if dry_run: actions.append(warn_msg)
        return True, warn_msg, actions, None

    if dry_run:
        action_msg = f"DRY RUN: Would download {component_name} from '{config_share_client.share_name}/{azure_config_path}' to '{local_config_target_path}'."
        actions.append(action_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', action_msg)
        logger.info(action_msg)
        downloaded_config_path = "DRY_RUN_USER_CONFIGS_PATH_PLACEHOLDER" # Placeholder
        success_msg = f"DRY RUN: {component_name} component finished (simulated download)."
        _emit_progress(socketio_instance, task_id, 'restore_progress', success_msg)
        logger.info(success_msg)
        return True, success_msg, actions, downloaded_config_path
    else:
        _emit_progress(socketio_instance, task_id, 'restore_progress', f'Downloading {component_name}...', f'{azure_config_path} to {local_config_target_path}')
        logger.info(f"Downloading {component_name} from '{config_share_client.share_name}/{azure_config_path}' to '{local_config_target_path}'.")
        if download_file(config_share_client, azure_config_path, local_config_target_path):
            success_msg = f"{component_name} JSON downloaded successfully."
            logger.info(success_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', f'{component_name} download complete.')
            downloaded_config_path = local_config_target_path
            return True, success_msg, actions, downloaded_config_path
        else:
            warn_msg = f"{component_name} JSON download failed from '{azure_config_path}'."
            logger.warning(warn_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg, "WARNING")
            return True, warn_msg, actions, None


def restore_media_component(timestamp_str, media_type_name, local_target_dir, remote_media_subdir_base, media_share_client, dry_run=False, socketio_instance=None, task_id=None):
    """
    Restores a specific type of media files (e.g., FloorMaps, ResourceUploads).

    Args:
        timestamp_str (str): The backup timestamp.
        media_type_name (str): User-friendly name of the media type (e.g., "Floor Maps").
        local_target_dir (str): The local directory to restore files to (e.g., FLOOR_MAP_UPLOADS).
        remote_media_subdir_base (str): The base name for the remote subdirectory
                                        (e.g., "floor_map_uploads" which becomes "floor_map_uploads_{timestamp_str}").
        media_share_client: The Azure ShareClient for media.
        dry_run (bool): If True, simulate operations.
        socketio_instance: Optional SocketIO instance.
        task_id: Optional task ID for SocketIO.

    Returns:
        tuple: (success_bool, message_str, actions_list)
    """
    actions = []
    dry_run_prefix = "DRY RUN: " if dry_run else ""

    _emit_progress(socketio_instance, task_id, 'restore_progress', f'{dry_run_prefix}Starting {media_type_name} restore component...', f'Timestamp: {timestamp_str}')

    remote_media_dir_path = f"{MEDIA_BACKUPS_DIR_BASE}/{remote_media_subdir_base}_{timestamp_str}"
    azure_media_dir_client = media_share_client.get_directory_client(remote_media_dir_path)

    if not _client_exists(azure_media_dir_client):
        warn_msg = f"{dry_run_prefix}{media_type_name} backup directory '{remote_media_dir_path}' not found on share '{media_share_client.share_name}'. Skipping."
        logger.warning(warn_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg, remote_media_dir_path)
        if dry_run: actions.append(warn_msg)
        return True, warn_msg, actions # Not a critical failure

    if dry_run:
        action_msg = f"DRY RUN: Would clear local directory: {local_target_dir}"
        actions.append(action_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', action_msg)
        logger.info(action_msg)

        # Simulate listing and downloading files
        try:
            # To list files in dry run, we still need to query the remote directory
            item_count = 0
            for item in azure_media_dir_client.list_directories_and_files():
                if not item['is_directory']:
                    item_count +=1
                    filename = item['name']
                    azure_file_path = f"{remote_media_dir_path}/{filename}"
                    local_file_path = os.path.join(local_target_dir, filename)
                    action_msg_file = f"DRY RUN: Would download media file '{filename}' from '{azure_file_path}' to '{local_file_path}'."
                    actions.append(action_msg_file)
                    _emit_progress(socketio_instance, task_id, 'restore_progress', action_msg_file)
                    logger.info(action_msg_file)
            if item_count == 0:
                 actions.append(f"DRY RUN: No files found in remote directory {remote_media_dir_path} to download.")

        except Exception as e:
            err_msg = f"DRY RUN: Error listing files in {remote_media_dir_path}: {e}"
            logger.error(err_msg)
            actions.append(err_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', err_msg, "ERROR")
            # Continue, as this is a dry run, but report the issue.

        success_msg = f"DRY RUN: {media_type_name} component finished (simulated operations)."
        _emit_progress(socketio_instance, task_id, 'restore_progress', success_msg)
        logger.info(success_msg)
        return True, success_msg, actions
    else:
        _emit_progress(socketio_instance, task_id, 'restore_progress', f'Clearing local directory: {local_target_dir}')
        if os.path.exists(local_target_dir):
            for filename in os.listdir(local_target_dir):
                file_to_delete = os.path.join(local_target_dir, filename)
                if os.path.isfile(file_to_delete):
                    try:
                        os.remove(file_to_delete)
                    except Exception as e:
                        logger.error(f"Failed to delete local file {file_to_delete}: {e}")
                        _emit_progress(socketio_instance, task_id, 'restore_progress', f"Error deleting local file {file_to_delete}", str(e))
                        # Decide if this is critical enough to stop this component
        else:
            os.makedirs(local_target_dir, exist_ok=True)

        files_downloaded = 0
        files_failed = 0
        for item in azure_media_dir_client.list_directories_and_files():
            if not item['is_directory']:
                filename = item['name']
                azure_file_path = f"{remote_media_dir_path}/{filename}"
                local_file_path = os.path.join(local_target_dir, filename)
                _emit_progress(socketio_instance, task_id, 'restore_progress', f'Restoring {media_type_name} file: {filename}', local_file_path)
                if download_file(media_share_client, azure_file_path, local_file_path):
                    logger.info(f"Restored {media_type_name} file '{filename}' successfully.")
                    files_downloaded +=1
                else:
                    logger.warning(f"Failed to restore {media_type_name} file '{filename}' from '{azure_file_path}'.")
                    _emit_progress(socketio_instance, task_id, 'restore_progress', f'Failed to restore {media_type_name} file: {filename}', "WARNING")
                    files_failed +=1

        final_msg = f"{media_type_name.capitalize()} restoration: {files_downloaded} files downloaded, {files_failed} failed."
        logger.info(final_msg)
        _emit_progress(socketio_instance, task_id, 'restore_progress', final_msg)
        return files_failed == 0, final_msg, actions # Success if no files failed


def list_available_backups():
    """
    Lists available backup timestamps based on the presence of database backup files.

    Returns:
        list: A sorted list of unique timestamp strings (YYYYMMDD_HHMMSS), most recent first.
              Returns an empty list if no backups are found or if there's an error.
    """
    logger.info("Attempting to list available backups.")
    try:
        service_client = _get_service_client()
        db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
        share_client = service_client.get_share_client(db_share_name)

        if not _client_exists(share_client):
            logger.warning(f"Backup share '{db_share_name}' does not exist. No backups to list.")
            return []

        db_backup_dir_client = share_client.get_directory_client(DB_BACKUPS_DIR)

        if not _client_exists(db_backup_dir_client):
            logger.warning(f"Database backup directory '{DB_BACKUPS_DIR}' does not exist on share '{db_share_name}'. No backups to list.")
            return []

        timestamps = set()
        for item in db_backup_dir_client.list_directories_and_files():
            if item['is_directory']:
                continue
            filename = item['name']
            if filename.startswith(DB_FILENAME_PREFIX) and filename.endswith('.db'):
                try:
                    # Extract YYYYMMDD_HHMMSS part
                    timestamp_str = filename[len(DB_FILENAME_PREFIX):-len('.db')]
                    # Basic validation of timestamp format (15 chars, YYYYMMDD_HHMMSS)
                    if len(timestamp_str) == 15 and timestamp_str[8] == '_':
                        datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S') # Validate format
                        timestamps.add(timestamp_str)
                    else:
                        logger.warning(f"Skipping file with unexpected name format: {filename}")
                except ValueError:
                    logger.warning(f"Skipping file with invalid timestamp format: {filename}")

        sorted_timestamps = sorted(list(timestamps), reverse=True)
        logger.info(f"Found {len(sorted_timestamps)} available backup timestamps.")
        return sorted_timestamps
    except Exception as e:
        logger.error(f"Error listing available backups: {e}")
        return []


def restore_full_backup(timestamp_str, dry_run=False, socketio_instance=None, task_id=None):
    """
    Restores a full backup (database, map configuration, and media files) for a specific timestamp.

    Args:
        timestamp_str (str): The timestamp string (YYYYMMDD_HHMMSS) of the backup to restore.
        dry_run (bool): If True, simulates restore operations without making changes.
        socketio_instance: Optional SocketIO instance for progress emitting.
        task_id: Optional task ID for SocketIO progress emitting.

    Returns:
        tuple: (path_to_restored_db_or_None, path_to_downloaded_map_config_or_None, path_to_downloaded_resource_configs_or_None, path_to_downloaded_user_configs_or_None, actions_list)
               Returns (None, None, None, None, actions_list) if critical (DB) restoration fails.
               actions_list contains strings describing operations if dry_run is True.
    """
    overall_actions_list = []
    dry_run_prefix = "DRY RUN: " if dry_run else ""
    final_restored_db_path = None
    final_downloaded_map_config_path = None
    final_downloaded_resource_configs_path = None
    final_downloaded_user_configs_path = None

    logger.info(f"{dry_run_prefix}Starting full restore for timestamp: {timestamp_str}")
    _emit_progress(socketio_instance, task_id, 'restore_progress', f"{dry_run_prefix}Starting full restore processing...", f'Timestamp: {timestamp_str}')

    try:
        service_client = _get_service_client()

        # --- Database Restore Component ---
        db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
        db_share_client = service_client.get_share_client(db_share_name)

        if not _client_exists(db_share_client):
            err_msg = f"{dry_run_prefix}Database backup share '{db_share_name}' does not exist. Cannot proceed with any restore operations."
            logger.error(err_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', err_msg, "ERROR")
            if dry_run: overall_actions_list.append(err_msg)
            return None, None, overall_actions_list

        db_success, db_message, db_actions, db_output_path = restore_database_component(
            timestamp_str, db_share_client, dry_run, socketio_instance, task_id
        )
        if dry_run: overall_actions_list.extend(db_actions)
        final_restored_db_path = db_output_path # This will be placeholder in dry_run, actual path otherwise

        if not db_success: # Critical failure if DB component fails
            logger.error(f"{dry_run_prefix}Database restore component failed: {db_message}. Aborting full restore.")
            _emit_progress(socketio_instance, task_id, 'restore_progress', f"{dry_run_prefix}Database restore failed. Full restore aborted.", "ERROR")
            return None, None, None, None, overall_actions_list # Return None for paths, include actions gathered so far

        # --- Map Configuration Download Component ---
        config_share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
        config_share_client = service_client.get_share_client(config_share_name)

        if _client_exists(config_share_client):
            map_success, map_message, map_actions, map_output_path = download_map_config_component(
                timestamp_str, config_share_client, dry_run, socketio_instance, task_id
            )
            if dry_run: overall_actions_list.extend(map_actions)
            final_downloaded_map_config_path = map_output_path
            if not map_success: # Log warning, but continue as it's not deemed critical
                 logger.warning(f"{dry_run_prefix}Map configuration download component reported issues: {map_message}")
        else:
            warn_msg = f"{dry_run_prefix}Config backup share '{config_share_name}' does not exist. Skipping map configuration download."
            logger.warning(warn_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg)
            if dry_run: overall_actions_list.append(warn_msg)

        # --- Resource Configurations Download Component ---
        if _client_exists(config_share_client): # Check if config share itself exists
            rc_success, rc_message, rc_actions, rc_output_path = download_resource_configs_component(
                timestamp_str, config_share_client, dry_run, socketio_instance, task_id
            )
            if dry_run: overall_actions_list.extend(rc_actions)
            final_downloaded_resource_configs_path = rc_output_path
            if not rc_success: logger.warning(f"{dry_run_prefix}Resource configs download component reported issues: {rc_message}")
        # No else here, as config_share_client existence is checked above for map_config already.

        # --- User Configurations Download Component ---
        if _client_exists(config_share_client):
            uc_success, uc_message, uc_actions, uc_output_path = download_user_configs_component(
                timestamp_str, config_share_client, dry_run, socketio_instance, task_id
            )
            if dry_run: overall_actions_list.extend(uc_actions)
            final_downloaded_user_configs_path = uc_output_path
            if not uc_success: logger.warning(f"{dry_run_prefix}User configs download component reported issues: {uc_message}")
        # No else here, as config_share_client existence is checked above for map_config already.

        # --- Media Restore Components ---
        media_share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media')
        media_share_client = service_client.get_share_client(media_share_name)

        if _client_exists(media_share_client):
            # Restore Floor Maps
            fm_success, fm_message, fm_actions = restore_media_component(
                timestamp_str, "FloorMaps", FLOOR_MAP_UPLOADS, "floor_map_uploads",
                media_share_client, dry_run, socketio_instance, task_id
            )
            if dry_run: overall_actions_list.extend(fm_actions)
            if not fm_success: logger.warning(f"{dry_run_prefix}FloorMaps restore component reported issues: {fm_message}")

            # Restore Resource Uploads
            ru_success, ru_message, ru_actions = restore_media_component(
                timestamp_str, "ResourceUploads", RESOURCE_UPLOADS, "resource_uploads",
                media_share_client, dry_run, socketio_instance, task_id
            )
            if dry_run: overall_actions_list.extend(ru_actions)
            if not ru_success: logger.warning(f"{dry_run_prefix}ResourceUploads restore component reported issues: {ru_message}")
        else:
            warn_msg = f"{dry_run_prefix}Media backup share '{media_share_name}' does not exist. Skipping all media restore."
            logger.warning(warn_msg)
            _emit_progress(socketio_instance, task_id, 'restore_progress', warn_msg)
            if dry_run: overall_actions_list.append(warn_msg)

        logger.info(f"{dry_run_prefix}Full restore process completed for timestamp: {timestamp_str}")
        _emit_progress(socketio_instance, task_id, 'restore_progress', f'{dry_run_prefix}Full restore operations finished.')
        return final_restored_db_path, final_downloaded_map_config_path, final_downloaded_resource_configs_path, final_downloaded_user_configs_path, overall_actions_list

    except Exception as e:
        err_msg_final = f"{dry_run_prefix}Critical error during full restore orchestration for timestamp {timestamp_str}: {e}"
        logger.error(err_msg_final, exc_info=True)
        _emit_progress(socketio_instance, task_id, 'restore_progress', err_msg_final, "ERROR")
        if dry_run: overall_actions_list.append(err_msg_final)
        return None, None, None, None, overall_actions_list


def delete_backup_set(timestamp_str, socketio_instance=None, task_id=None):
    """
    Deletes a complete backup set for a given timestamp, including database,
    map configuration, manifest, and media files/directories.

    Args:
        timestamp_str (str): The timestamp string (YYYYMMDD_HHMMSS) of the backup set to delete.
        socketio_instance: Optional SocketIO instance for progress emitting.
        task_id: Optional task ID for SocketIO progress emitting.

    Returns:
        bool: True if all critical components were attempted to be deleted (some may not exist),
              False if a critical error occurred during setup or essential component deletion.
    """
    event_name = 'backup_delete_progress'
    log_prefix = f"[Task {task_id if task_id else 'N/A'}] "
    logger.info(f"{log_prefix}Attempting to delete backup set for timestamp: {timestamp_str}")
    _emit_progress(socketio_instance, task_id, event_name, f"Starting deletion for backup set: {timestamp_str}")

    overall_success = True
    critical_component_processed = False # Tracks if critical components (DB, Manifest) were processed (deleted or confirmed not found)

    try:
        service_client = _get_service_client()

        # --- Helper: Delete File ---
        def _delete_file_if_exists(share_client, file_path, component_name, share_name_for_log, is_critical=False):
            nonlocal overall_success, critical_component_processed
            _emit_progress(socketio_instance, task_id, event_name, f"Checking for {component_name}...", file_path)
            file_client = share_client.get_file_client(file_path)
            if _client_exists(file_client):
                try:
                    file_client.delete_file()
                    logger.info(f"{log_prefix}Successfully deleted {component_name} '{file_path}' from share '{share_name_for_log}'.")
                    _emit_progress(socketio_instance, task_id, event_name, f"{component_name} deleted.", "SUCCESS")
                    if is_critical: critical_component_processed = True
                    return True
                except Exception as e:
                    logger.error(f"{log_prefix}Failed to delete {component_name} '{file_path}' from share '{share_name_for_log}'. Exception: {type(e).__name__}, Details: {str(e)}", exc_info=True)
                    _emit_progress(socketio_instance, task_id, event_name, f"Failed to delete {component_name} ({type(e).__name__})", f"ERROR: {str(e)}")
                    if is_critical: overall_success = False # Failure to delete an existing critical file is a failure
                    return False
            else:
                logger.info(f"{log_prefix}{component_name} file '{file_path}' not found on share '{share_name_for_log}'. Skipping deletion.")
                _emit_progress(socketio_instance, task_id, event_name, f"{component_name} not found, skipping.", "INFO")
                if is_critical: critical_component_processed = True
                return True # Not finding an optional or even critical file isn't a failure of the delete *operation*

        # --- Helper: Delete Directory ---
        def _delete_directory_if_exists(share_client, dir_path, component_name, share_name_for_log, is_critical=False):
            nonlocal overall_success # `critical_component_processed` not used here as directories are media, not critical for this flag
            _emit_progress(socketio_instance, task_id, event_name, f"Checking for {component_name} directory...", dir_path)
            dir_client = share_client.get_directory_client(dir_path)
            dir_path_for_emit = dir_path # Used for emit messages, as dir_path might be modified by loop

            if _client_exists(dir_client):
                try:
                    # List and delete files within the directory first
                    items_in_dir = list(dir_client.list_directories_and_files())
                    logger.info(f"{log_prefix}Found {len(items_in_dir)} items in directory '{dir_path}'.")
                    _emit_progress(socketio_instance, task_id, event_name, f"Found {len(items_in_dir)} items in {component_name} directory '{dir_path_for_emit}'. Attempting to delete contents.")

                    for item in items_in_dir:
                        item_name_for_log = item['name']
                        if item['is_directory']:
                            # Note: Current backup structure does not create sub-directories within these media backup dirs.
                            # If it did, recursive deletion would be needed here.
                            # For now, log a warning if a sub-directory is unexpectedly found.
                            logger.warning(f"{log_prefix}Unexpected sub-directory '{item_name_for_log}' found in '{dir_path}'. This structure is not standard. Skipping this sub-directory.")
                            _emit_progress(socketio_instance, task_id, event_name, f"Skipping unexpected sub-directory '{item_name_for_log}' in '{dir_path_for_emit}'.", "WARNING")
                            continue # Skip to next item

                        # It's a file, attempt to delete it
                        file_in_dir_client = dir_client.get_file_client(item_name_for_log)
                        try:
                            logger.info(f"{log_prefix}Attempting to delete file '{item_name_for_log}' in directory '{dir_path}'.")
                            _emit_progress(socketio_instance, task_id, event_name, f"Deleting file {item_name_for_log} in {dir_path_for_emit} for {component_name}")
                            file_in_dir_client.delete_file()
                            logger.info(f"{log_prefix}Successfully deleted file '{item_name_for_log}' in directory '{dir_path}'.")
                            _emit_progress(socketio_instance, task_id, event_name, f"Deleted file {item_name_for_log} in {dir_path_for_emit}", "SUCCESS")
                        except Exception as e_file:
                            logger.error(f"{log_prefix}Failed to delete file '{item_name_for_log}' in directory '{dir_path}'. Exception: {type(e_file).__name__}, Details: {str(e_file)}", exc_info=True)
                            _emit_progress(socketio_instance, task_id, event_name, f"Error deleting file {item_name_for_log} in {dir_path_for_emit}", f"ERROR: {str(e_file)}")
                            overall_success = False # Failure to delete a file within directory means directory delete will fail
                            return False # Critical failure for this helper's operation

                    # All contents attempted to be deleted, now delete the main directory
                    logger.info(f"{log_prefix}Attempting to delete main directory '{dir_path}' for {component_name}.")
                    dir_client.delete_directory()
                    logger.info(f"{log_prefix}Successfully deleted {component_name} directory '{dir_path}' from share '{share_name_for_log}'.")
                    _emit_progress(socketio_instance, task_id, event_name, f"{component_name} directory and its contents deleted.", "SUCCESS")
                    return True
                except Exception as e: # Catch error during list_directories_and_files or final delete_directory
                    logger.error(f"{log_prefix}Failed to delete {component_name} directory '{dir_path}' or its contents from share '{share_name_for_log}'. Exception: {type(e).__name__}, Details: {str(e)}", exc_info=True)
                    _emit_progress(socketio_instance, task_id, event_name, f"Failed to delete {component_name} directory ({type(e).__name__})", f"ERROR: {str(e)}")
                    overall_success = False
                    return False
            else:
                logger.info(f"{log_prefix}{component_name} directory '{dir_path}' not found on share '{share_name_for_log}'. Skipping deletion.")
                _emit_progress(socketio_instance, task_id, event_name, f"{component_name} directory not found, skipping.", "INFO")
                return True # Not finding directory is not a failure of delete operation

        # --- Main Deletion Logic ---
        db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
        db_share_client = service_client.get_share_client(db_share_name)
        if _client_exists(db_share_client):
            db_backup_filename = f"{DB_FILENAME_PREFIX}{timestamp_str}.db"
            db_backup_path = f"{DB_BACKUPS_DIR}/{db_backup_filename}"
            if not _delete_file_if_exists(db_share_client, db_backup_path, "Database Backup", db_share_name, is_critical=True):
                overall_success = False

            manifest_filename = f"backup_manifest_{timestamp_str}.json"
            manifest_path = f"{DB_BACKUPS_DIR}/{manifest_filename}"
            if not _delete_file_if_exists(db_share_client, manifest_path, "Backup Manifest", db_share_name, is_critical=True):
                overall_success = False
        else:
            logger.warning(f"{log_prefix}Database backup share '{db_share_name}' not found. Skipping DB and Manifest backup deletion for set {timestamp_str}.")
            _emit_progress(socketio_instance, task_id, event_name, f"Database share '{db_share_name}' not found. Skipping DB & Manifest.", "WARNING")
            overall_success = False # If DB share is missing, it's a significant issue
            critical_component_processed = False # Explicitly mark critical components as not processed

        # Delete Map Configuration JSON Backup
        config_share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
        config_share_client = service_client.get_share_client(config_share_name)
        if _client_exists(config_share_client):
            config_backup_filename = f"{MAP_CONFIG_FILENAME_PREFIX}{timestamp_str}.json"
            config_backup_path = f"{CONFIG_BACKUPS_DIR}/{config_backup_filename}"
            if not _delete_file_if_exists(config_share_client, config_backup_path, "Map Configuration Backup", config_share_name):
                # Not critical enough to set overall_success = False, but good to note if needed
                pass
        else:
            logger.info(f"{log_prefix}Config backup share '{config_share_name}' not found. Skipping config backup deletion for set {timestamp_str}.")
            _emit_progress(socketio_instance, task_id, event_name, f"Config share '{config_share_name}' not found. Skipping map config.", "INFO")

        # Delete Media Backups
        media_share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media')
        media_share_client = service_client.get_share_client(media_share_name)
        if _client_exists(media_share_client):
            remote_floor_map_dir = f"{MEDIA_BACKUPS_DIR_BASE}/floor_map_uploads_{timestamp_str}"
            if not _delete_directory_if_exists(media_share_client, remote_floor_map_dir, "Floor Map Backup", media_share_name):
                overall_success = False # If directory existed and failed to delete, consider it a failure for overall

            remote_resource_uploads_dir = f"{MEDIA_BACKUPS_DIR_BASE}/resource_uploads_{timestamp_str}"
            if not _delete_directory_if_exists(media_share_client, remote_resource_uploads_dir, "Resource Uploads Backup", media_share_name):
                overall_success = False # If directory existed and failed to delete, consider it a failure for overall
        else:
            logger.info(f"{log_prefix}Media backup share '{media_share_name}' not found. Skipping media backup deletion for set {timestamp_str}.")
            _emit_progress(socketio_instance, task_id, event_name, f"Media share '{media_share_name}' not found. Skipping media.", "INFO")

        # Final check on critical component processing
        if not critical_component_processed and not _client_exists(db_share_client):
            # This condition confirms if DB share was missing AND thus critical components were never attempted.
            # overall_success is already False from the DB share check, this is an additional log.
            logger.error(f"{log_prefix}Critical backup components (DB or Manifest on DB Share) could not be processed because the share '{db_share_name}' was missing.")
            _emit_progress(socketio_instance, task_id, event_name, "Critical components could not be processed due to missing DB share.", "ERROR")
        elif not critical_component_processed and _client_exists(db_share_client):
            # This case implies DB share existed, but both DB and Manifest files were not found.
            # This is not necessarily an error for the delete operation itself.
            logger.info(f"{log_prefix}Critical components (DB and Manifest) were not found on share '{db_share_name}', but share exists. Assuming already deleted or not part of this backup.")


        final_status_detail = "SUCCESS" if overall_success else "FAILURE" # FAILURE if any part of deletion of existing items failed OR critical share missing
        logger.info(f"{log_prefix}Deletion process for backup set {timestamp_str} completed. Overall success: {overall_success}")
        _emit_progress(socketio_instance, task_id, event_name, "Backup set deletion process finished.", final_status_detail)
        return overall_success

    except Exception as e:
        logger.error(f"{log_prefix}Critical error during deletion of backup set for timestamp {timestamp_str}: {e}", exc_info=True)
        _emit_progress(socketio_instance, task_id, event_name, f"Critical error during backup set deletion: {str(e)}", "CRITICAL_ERROR")
        return False


if __name__ == '__main__':
    main()
