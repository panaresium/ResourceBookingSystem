
def save_floor_map_to_share(local_path, filename):
    """
    Uploads a floor map to the 'floor_map_uploads' folder in R2.
    Used by api_maps.py for immediate persistence.
    """
    if not r2_storage.client:
        return False

    return r2_storage.upload_file(local_path, filename, folder='floor_map_uploads')
