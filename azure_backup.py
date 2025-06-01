
import os
import hashlib
import logging
import sqlite3
import json
from datetime import datetime
from azure.core.exceptions import ResourceNotFoundError

try:
    from azure.storage.fileshare import ShareServiceClient
    from azure.core.exceptions import ResourceNotFoundError
except ImportError:  # pragma: no cover - azure sdk optional
    ShareServiceClient = None
    ResourceNotFoundError = Exception


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
            socketio_instance.emit(event_name, {'task_id': task_id, 'status': message, 'detail': detail})
            # logger.debug(f"Emitted {event_name} for {task_id}: {message} - {detail}")
        except Exception as e:
            logger.error(f"Failed to emit SocketIO event {event_name} for task {task_id}: {e}")

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
            # Depending on requirements, might re-raise or handle more gracefully
            raise


def upload_file(share_client, source_path, file_path):
    directory_path = os.path.dirname(file_path)
    if directory_path:
        directory_client = share_client.get_directory_client(directory_path)
        if not _client_exists(directory_client):
            directory_client.create_directory()
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
    with open(dest_path, 'wb') as f:
        downloader = file_client.download_file()
        f.write(downloader.readall())
    return True


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


def create_full_backup(timestamp_str, map_config_data=None, socketio_instance=None, task_id=None):
    """
    Creates a full backup of the database, map configuration, and media files.

    Args:
        timestamp_str (str): The timestamp string in "YYYYMMDD_HHMMSS" format.
        map_config_data (dict, optional): Actual map configuration data to back up.
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
            file_client.upload_file(data=config_json_bytes, overwrite=True)
            logger.info(f"Successfully backed up map configuration to '{config_share_name}/{remote_config_path}'.")
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'Map configuration backup complete.')
        except Exception as e:
            logger.error(f"Failed to backup map configuration to '{config_share_name}/{remote_config_path}': {e}")
            _emit_progress(socketio_instance, task_id, 'backup_progress', 'Map configuration backup failed.', str(e))
            # Not setting overall_success = False for config backup failure, could be optional
    else:
        logger.warning(f"No map_config_data provided for timestamp {timestamp_str}. Skipping map configuration backup.")
        _emit_progress(socketio_instance, task_id, 'backup_progress', 'Map configuration backup skipped (no data provided).')

    # Media Backup (Floor Maps & Resource Uploads)
    media_share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media')
    media_share_client = service_client.get_share_client(media_share_name)
    if not _client_exists(media_share_client):
        logger.info(f"Creating share '{media_share_name}' for media backups.")
        media_share_client.create_share()

    # Backup FLOOR_MAP_UPLOADS
    remote_floor_map_dir = f"{MEDIA_BACKUPS_DIR_BASE}/floor_map_uploads_{timestamp_str}"
    _ensure_directory_exists(media_share_client, remote_floor_map_dir)
    if os.path.isdir(FLOOR_MAP_UPLOADS):
        for filename in os.listdir(FLOOR_MAP_UPLOADS):
            local_file_path = os.path.join(FLOOR_MAP_UPLOADS, filename)
            if os.path.isfile(local_file_path):
                remote_file_path = f"{remote_floor_map_dir}/{filename}"
                _emit_progress(socketio_instance, task_id, 'backup_progress', f'Backing up floor map: {filename}', local_file_path)
                try:
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

    _emit_progress(socketio_instance, task_id, 'backup_progress', f'Full backup function finished. Overall success: {overall_success}')
    return overall_success


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


def restore_full_backup(timestamp_str, socketio_instance=None, task_id=None):
    """
    Restores a full backup (database, map configuration, and media files) for a specific timestamp.

    Args:
        timestamp_str (str): The timestamp string (YYYYMMDD_HHMMSS) of the backup to restore.
        socketio_instance: Optional SocketIO instance for progress emitting.
        task_id: Optional task ID for SocketIO progress emitting.

    Returns:
        tuple: (path_to_restored_db_or_None, path_to_downloaded_map_config_or_None)
               Returns (None, None) if critical (DB) restoration fails.
    """
    logger.info(f"Starting full restore for timestamp: {timestamp_str}")
    _emit_progress(socketio_instance, task_id, 'restore_progress', 'Starting full restore processing...', f'Timestamp: {timestamp_str}')
    restored_db_path = None
    downloaded_map_config_json_path = None

    try:
        service_client = _get_service_client()

        # --- Database Restore ---
        db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
        db_share_client = service_client.get_share_client(db_share_name)

        if not _client_exists(db_share_client):
            logger.error(f"Database backup share '{db_share_name}' does not exist. Cannot restore.")
            _emit_progress(socketio_instance, task_id, 'restore_progress', f"Database backup share '{db_share_name}' does not exist. Cannot restore.", "ERROR")
            return None, None

        remote_db_filename = f"{DB_FILENAME_PREFIX}{timestamp_str}.db"
        azure_db_path = f"{DB_BACKUPS_DIR}/{remote_db_filename}"
        local_db_target_path = os.path.join(DATA_DIR, 'site.db')
        _emit_progress(socketio_instance, task_id, 'restore_progress', 'Restoring database...', f'{azure_db_path} to {local_db_target_path}')

        db_file_client = db_share_client.get_file_client(azure_db_path)
        if not _client_exists(db_file_client):
            logger.error(f"Database backup file '{azure_db_path}' not found on share '{db_share_name}'. Aborting restore.")
            _emit_progress(socketio_instance, task_id, 'restore_progress', f"Database backup file '{azure_db_path}' not found. Aborting.", "ERROR")
            return None, None

        logger.info(f"Restoring database from '{db_share_name}/{azure_db_path}' to '{local_db_target_path}'.")
        if download_file(db_share_client, azure_db_path, local_db_target_path):
            logger.info("Database restored successfully.")
            _emit_progress(socketio_instance, task_id, 'restore_progress', 'Database restore complete.')
            restored_db_path = local_db_target_path
        else:
            logger.error("Database restoration failed.")
            _emit_progress(socketio_instance, task_id, 'restore_progress', 'Database restore failed. Aborting.', "ERROR")
            return None, None # Critical failure

        # --- Map Configuration JSON Restore ---
        config_share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
        config_share_client = service_client.get_share_client(config_share_name)
        _emit_progress(socketio_instance, task_id, 'restore_progress', 'Processing map configuration restore...')

        if _client_exists(config_share_client):
            remote_config_filename = f"{MAP_CONFIG_FILENAME_PREFIX}{timestamp_str}.json"
            azure_config_path = f"{CONFIG_BACKUPS_DIR}/{remote_config_filename}"
            local_config_target_path = os.path.join(DATA_DIR, remote_config_filename)
            _emit_progress(socketio_instance, task_id, 'restore_progress', 'Downloading map configuration...', f'{azure_config_path} to {local_config_target_path}')

            config_file_client = config_share_client.get_file_client(azure_config_path)
            if _client_exists(config_file_client):
                logger.info(f"Restoring map configuration from '{config_share_name}/{azure_config_path}' to '{local_config_target_path}'.")
                if download_file(config_share_client, azure_config_path, local_config_target_path):
                    logger.info("Map configuration JSON restored successfully.")
                    _emit_progress(socketio_instance, task_id, 'restore_progress', 'Map configuration download complete.')
                    downloaded_map_config_json_path = local_config_target_path
                else:
                    logger.warning(f"Map configuration JSON restoration failed from '{azure_config_path}'.")
                    _emit_progress(socketio_instance, task_id, 'restore_progress', 'Map configuration download failed.', azure_config_path)
            else:
                logger.warning(f"Map configuration backup file '{azure_config_path}' not found on share '{config_share_name}'. Skipping.")
                _emit_progress(socketio_instance, task_id, 'restore_progress', 'Map configuration backup file not found. Skipping.', azure_config_path)
        else:
            logger.warning(f"Config backup share '{config_share_name}' does not exist. Skipping map configuration restore.")
            _emit_progress(socketio_instance, task_id, 'restore_progress', f"Config backup share '{config_share_name}' not found. Skipping map restore.")

        # --- Media Restore ---
        # Media restore failures do not change the primary return tuple of this function.
        media_share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media')
        media_share_client = service_client.get_share_client(media_share_name)

        if _client_exists(media_share_client):
            # Restore Floor Maps
            remote_floor_map_dir_path = f"{MEDIA_BACKUPS_DIR_BASE}/floor_map_uploads_{timestamp_str}"
            local_floor_map_dir = FLOOR_MAP_UPLOADS
            _emit_progress(socketio_instance, task_id, 'restore_progress', 'Restoring floor maps...', remote_floor_map_dir_path)

            logger.info(f"Attempting to restore floor maps from '{media_share_name}/{remote_floor_map_dir_path}' to '{local_floor_map_dir}'.")
            azure_floor_map_dir_client = media_share_client.get_directory_client(remote_floor_map_dir_path)
            if _client_exists(azure_floor_map_dir_client):
                _emit_progress(socketio_instance, task_id, 'restore_progress', f'Clearing local directory: {local_floor_map_dir}')
                if os.path.exists(local_floor_map_dir):
                    for filename in os.listdir(local_floor_map_dir):
                        file_to_delete = os.path.join(local_floor_map_dir, filename)
                        if os.path.isfile(file_to_delete):
                            os.remove(file_to_delete)
                else:
                    os.makedirs(local_floor_map_dir, exist_ok=True)

                for item in azure_floor_map_dir_client.list_directories_and_files():
                    if not item['is_directory']:
                        filename = item['name']
                        azure_file_path = f"{remote_floor_map_dir_path}/{filename}"
                        local_file_path = os.path.join(local_floor_map_dir, filename)
                        _emit_progress(socketio_instance, task_id, 'restore_progress', f'Restoring floor map: {filename}', local_file_path)
                        if download_file(media_share_client, azure_file_path, local_file_path):
                            logger.info(f"Restored floor map '{filename}' successfully.")
                        else:
                            logger.warning(f"Failed to restore floor map '{filename}' from '{azure_file_path}'.")
                            _emit_progress(socketio_instance, task_id, 'restore_progress', f'Failed to restore floor map: {filename}', azure_file_path)
                logger.info("Floor map restoration process finished.")
                _emit_progress(socketio_instance, task_id, 'restore_progress', 'Floor map restore phase complete.')
            else:
                logger.warning(f"Floor map backup directory '{remote_floor_map_dir_path}' not found on share '{media_share_name}'. Skipping floor map restore.")
                _emit_progress(socketio_instance, task_id, 'restore_progress', 'Floor map backup directory not found. Skipping.', remote_floor_map_dir_path)

            # Restore Resource Uploads
            remote_resource_uploads_dir_path = f"{MEDIA_BACKUPS_DIR_BASE}/resource_uploads_{timestamp_str}"
            local_resource_uploads_dir = RESOURCE_UPLOADS
            _emit_progress(socketio_instance, task_id, 'restore_progress', 'Restoring resource uploads...', remote_resource_uploads_dir_path)

            logger.info(f"Attempting to restore resource uploads from '{media_share_name}/{remote_resource_uploads_dir_path}' to '{local_resource_uploads_dir}'.")
            azure_resource_uploads_dir_client = media_share_client.get_directory_client(remote_resource_uploads_dir_path)
            if _client_exists(azure_resource_uploads_dir_client):
                _emit_progress(socketio_instance, task_id, 'restore_progress', f'Clearing local directory: {local_resource_uploads_dir}')
                if os.path.exists(local_resource_uploads_dir):
                    for filename in os.listdir(local_resource_uploads_dir):
                        file_to_delete = os.path.join(local_resource_uploads_dir, filename)
                        if os.path.isfile(file_to_delete):
                            os.remove(file_to_delete)
                else:
                    os.makedirs(local_resource_uploads_dir, exist_ok=True)

                for item in azure_resource_uploads_dir_client.list_directories_and_files():
                    if not item['is_directory']:
                        filename = item['name']
                        azure_file_path = f"{remote_resource_uploads_dir_path}/{filename}"
                        local_file_path = os.path.join(local_resource_uploads_dir, filename)
                        _emit_progress(socketio_instance, task_id, 'restore_progress', f'Restoring resource file: {filename}', local_file_path)
                        if download_file(media_share_client, azure_file_path, local_file_path):
                            logger.info(f"Restored resource upload '{filename}' successfully.")
                        else:
                            logger.warning(f"Failed to restore resource upload '{filename}' from '{azure_file_path}'.")
                            _emit_progress(socketio_instance, task_id, 'restore_progress', f'Failed to restore resource file: {filename}', azure_file_path)
                logger.info("Resource uploads restoration process finished.")
                _emit_progress(socketio_instance, task_id, 'restore_progress', 'Resource uploads restore phase complete.')
            else:
                logger.warning(f"Resource uploads backup directory '{remote_resource_uploads_dir_path}' not found on share '{media_share_name}'. Skipping resource uploads restore.")
                _emit_progress(socketio_instance, task_id, 'restore_progress', 'Resource uploads backup directory not found. Skipping.', remote_resource_uploads_dir_path)
        else:
            logger.warning(f"Media backup share '{media_share_name}' does not exist. Skipping media restore.")
            _emit_progress(socketio_instance, task_id, 'restore_progress', f"Media backup share '{media_share_name}' not found. Skipping media restore.")

        logger.info(f"Full restore process completed for timestamp: {timestamp_str}")
        _emit_progress(socketio_instance, task_id, 'restore_progress', 'Full restore file operations finished.')
        return restored_db_path, downloaded_map_config_json_path
    except Exception as e:
        logger.error(f"Error during full restore for timestamp {timestamp_str}: {e}")
        _emit_progress(socketio_instance, task_id, 'restore_progress', f'Critical error during restore: {str(e)}', "ERROR")
        return None, None


def delete_backup_set(timestamp_str):
    """
    Deletes a complete backup set for a given timestamp, including database,
    map configuration, and media files/directories.

    Args:
        timestamp_str (str): The timestamp string (YYYYMMDD_HHMMSS) of the backup set to delete.

    Returns:
        bool: True if all components were attempted to be deleted (some may not exist),
              False if a critical error occurred during setup.
    """
    logger.info(f"Attempting to delete backup set for timestamp: {timestamp_str}")
    try:
        service_client = _get_service_client()

        # Delete Database Backup
        db_share_name = os.environ.get('AZURE_DB_SHARE', 'db-backups')
        db_share_client = service_client.get_share_client(db_share_name)
        if _client_exists(db_share_client):
            db_backup_filename = f"{DB_FILENAME_PREFIX}{timestamp_str}.db"
            db_backup_path = f"{DB_BACKUPS_DIR}/{db_backup_filename}"
            db_file_client = db_share_client.get_file_client(db_backup_path)
            if _client_exists(db_file_client):
                try:
                    db_file_client.delete_file()
                    logger.info(f"Successfully deleted database backup '{db_backup_path}' from share '{db_share_name}'.")
                except Exception as e:
                    logger.error(f"Failed to delete database backup '{db_backup_path}' from share '{db_share_name}': {e}")
            else:
                logger.info(f"Database backup file '{db_backup_path}' not found on share '{db_share_name}'. Skipping deletion.")
        else:
            logger.warning(f"Database backup share '{db_share_name}' not found. Skipping DB backup deletion for set {timestamp_str}.")

        # Delete Map Configuration JSON Backup
        config_share_name = os.environ.get('AZURE_CONFIG_SHARE', 'config-backups')
        config_share_client = service_client.get_share_client(config_share_name)
        if _client_exists(config_share_client):
            config_backup_filename = f"{MAP_CONFIG_FILENAME_PREFIX}{timestamp_str}.json"
            config_backup_path = f"{CONFIG_BACKUPS_DIR}/{config_backup_filename}"
            config_file_client = config_share_client.get_file_client(config_backup_path)
            if _client_exists(config_file_client):
                try:
                    config_file_client.delete_file()
                    logger.info(f"Successfully deleted map configuration backup '{config_backup_path}' from share '{config_share_name}'.")
                except Exception as e:
                    logger.error(f"Failed to delete map configuration backup '{config_backup_path}' from share '{config_share_name}': {e}")
            else:
                logger.info(f"Map configuration backup file '{config_backup_path}' not found on share '{config_share_name}'. Skipping deletion.")
        else:
            logger.warning(f"Config backup share '{config_share_name}' not found. Skipping config backup deletion for set {timestamp_str}.")

        # Delete Media Backups
        media_share_name = os.environ.get('AZURE_MEDIA_SHARE', 'media')
        media_share_client = service_client.get_share_client(media_share_name)
        if _client_exists(media_share_client):
            # Delete Floor Maps Directory
            remote_floor_map_dir = f"{MEDIA_BACKUPS_DIR_BASE}/floor_map_uploads_{timestamp_str}"
            floor_map_dir_client = media_share_client.get_directory_client(remote_floor_map_dir)
            if _client_exists(floor_map_dir_client):
                try:
                    floor_map_dir_client.delete_directory()
                    logger.info(f"Successfully deleted floor map backup directory '{remote_floor_map_dir}' from share '{media_share_name}'.")
                except Exception as e:
                    logger.error(f"Failed to delete floor map backup directory '{remote_floor_map_dir}' from share '{media_share_name}': {e}")
            else:
                logger.info(f"Floor map backup directory '{remote_floor_map_dir}' not found on share '{media_share_name}'. Skipping deletion.")

            # Delete Resource Uploads Directory
            remote_resource_uploads_dir = f"{MEDIA_BACKUPS_DIR_BASE}/resource_uploads_{timestamp_str}"
            resource_uploads_dir_client = media_share_client.get_directory_client(remote_resource_uploads_dir)
            if _client_exists(resource_uploads_dir_client):
                try:
                    resource_uploads_dir_client.delete_directory()
                    logger.info(f"Successfully deleted resource uploads backup directory '{remote_resource_uploads_dir}' from share '{media_share_name}'.")
                except Exception as e:
                    logger.error(f"Failed to delete resource uploads backup directory '{remote_resource_uploads_dir}' from share '{media_share_name}': {e}")
            else:
                logger.info(f"Resource uploads backup directory '{remote_resource_uploads_dir}' not found on share '{media_share_name}'. Skipping deletion.")
        else:
            logger.warning(f"Media backup share '{media_share_name}' not found. Skipping media backup deletion for set {timestamp_str}.")

        logger.info(f"Deletion process for backup set {timestamp_str} completed.")
        return True
    except Exception as e:
        logger.error(f"Critical error during deletion of backup set for timestamp {timestamp_str}: {e}")
        return False


if __name__ == '__main__':
    main()
