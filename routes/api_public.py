from flask import Blueprint, jsonify
from utils import get_map_opacity_value

# Blueprint for public, unauthenticated API endpoints
api_public_bp = Blueprint('api_public', __name__, url_prefix='/api/public')

@api_public_bp.route('/system-settings/map-opacity', methods=['GET'])
def get_public_map_opacity():
    """
    Public endpoint to retrieve the map resource opacity.
    This endpoint is unauthenticated and safe to expose publicly.
    """
    opacity = get_map_opacity_value()
    return jsonify({'opacity': opacity})

def init_api_public_routes(app):
    app.register_blueprint(api_public_bp)
