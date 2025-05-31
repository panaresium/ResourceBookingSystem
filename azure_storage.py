import os
from datetime import datetime

try:
    from azure.storage.blob import BlobServiceClient
except ImportError:  # pragma: no cover - optional dependency
    BlobServiceClient = None

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
FLOOR_MAP_UPLOADS = os.path.join(STATIC_DIR, 'floor_map_uploads')
RESOURCE_UPLOADS = os.path.join(STATIC_DIR, 'resource_uploads')


def _get_service_client():
    connection_string = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
    if not connection_string:
        raise RuntimeError('AZURE_STORAGE_CONNECTION_STRING environment variable is required')
    if BlobServiceClient is None:
        raise RuntimeError('azure-storage-blob package is not installed')
    return BlobServiceClient.from_connection_string(connection_string)


def _get_container_client(service_client, container_name):
    container_client = service_client.get_container_client(container_name)
    if not container_client.exists():
        container_client.create_container()
    return container_client


def upload_database(versioned=False):
    service_client = _get_service_client()
    container_name = os.environ.get('AZURE_DB_CONTAINER', 'db-backups')
    container_client = _get_container_client(service_client, container_name)
    db_path = os.path.join(DATA_DIR, 'site.db')
    if versioned:
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        blob_name = f'site_{timestamp}.db'
    else:
        blob_name = 'site.db'
    with open(db_path, 'rb') as f:
        container_client.upload_blob(name=blob_name, data=f, overwrite=True)
    return blob_name


def download_database():
    service_client = _get_service_client()
    container_name = os.environ.get('AZURE_DB_CONTAINER', 'db-backups')
    container_client = _get_container_client(service_client, container_name)
    blob_name = 'site.db'
    blob_client = container_client.get_blob_client(blob_name)
    if not blob_client.exists():
        raise RuntimeError('Database blob not found in Azure storage')
    download_stream = blob_client.download_blob()
    os.makedirs(DATA_DIR, exist_ok=True)
    db_path = os.path.join(DATA_DIR, 'site.db')
    with open(db_path, 'wb') as f:
        f.write(download_stream.readall())
    return db_path


def upload_media():
    service_client = _get_service_client()
    container_name = os.environ.get('AZURE_MEDIA_CONTAINER', 'media')
    container_client = _get_container_client(service_client, container_name)
    for folder in (FLOOR_MAP_UPLOADS, RESOURCE_UPLOADS):
        if not os.path.isdir(folder):
            continue
        for fname in os.listdir(folder):
            fpath = os.path.join(folder, fname)
            if os.path.isfile(fpath):
                blob_name = f'{os.path.basename(folder)}/{fname}'
                with open(fpath, 'rb') as f:
                    container_client.upload_blob(name=blob_name, data=f, overwrite=True)


def download_media():
    service_client = _get_service_client()
    container_name = os.environ.get('AZURE_MEDIA_CONTAINER', 'media')
    container_client = _get_container_client(service_client, container_name)
    for blob in container_client.list_blobs():
        parts = blob.name.split('/', 1)
        if len(parts) != 2:
            continue
        prefix, fname = parts
        if prefix not in ('floor_map_uploads', 'resource_uploads'):
            continue
        local_dir = FLOOR_MAP_UPLOADS if prefix == 'floor_map_uploads' else RESOURCE_UPLOADS
        os.makedirs(local_dir, exist_ok=True)
        download_stream = container_client.download_blob(blob)
        with open(os.path.join(local_dir, fname), 'wb') as f:
            f.write(download_stream.readall())


