from flask import Blueprint, redirect, current_app, abort
from r2_storage import r2_storage

legacy_file_proxy_bp = Blueprint('legacy_file_proxy', __name__)

@legacy_file_proxy_bp.route('/static/resource_uploads/<path:filename>')
def resource_upload_proxy(filename):
    if current_app.config.get('STORAGE_PROVIDER') == 'r2':
        url = r2_storage.generate_presigned_url(filename, 'resource_uploads')
        if url:
            return redirect(url, code=302)
    # If not R2, or URL generation failed, let it fall through
    # (though explicit route might block default static handler, so we abort 404 here
    # if we assume this route ONLY handles R2 proxying.
    # If we want fallback to local static, we shouldn't have defined this route overlapping with static_folder,
    # OR we need to serve the file manually here if it exists locally.
    # Given the requirements, we enforce new stack, so local files might not exist).
    abort(404)

@legacy_file_proxy_bp.route('/static/floor_map_uploads/<path:filename>')
def floor_map_upload_proxy(filename):
    if current_app.config.get('STORAGE_PROVIDER') == 'r2':
        url = r2_storage.generate_presigned_url(filename, 'floor_map_uploads')
        if url:
            return redirect(url, code=302)
    abort(404)

def init_legacy_file_proxy_routes(app):
    app.register_blueprint(legacy_file_proxy_bp)
