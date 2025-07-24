import os
import json
from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from auth import permission_required
from models import BookingSettings
from extensions import db
from utils import get_map_opacity_value

# Blueprint Configuration
api_system_settings_bp = Blueprint('api_system_settings', __name__, url_prefix='/api/system-settings')

@api_system_settings_bp.route('/booking-lead-days', methods=['GET'])
def get_booking_lead_days():
    """
    Returns the maximum number of days in the future a booking can be made.
    """
    settings = BookingSettings.query.first()
    if settings and settings.max_booking_days_in_future is not None:
        return jsonify({'max_booking_days_in_future': settings.max_booking_days_in_future})
    else:
        return jsonify({'max_booking_days_in_future': 365})


@api_system_settings_bp.route('/map-opacity', methods=['GET', 'POST'])
@login_required
@permission_required('manage_system_settings')
def manage_map_opacity():
    config_file_path = current_app.config.get('MAP_OPACITY_CONFIG_FILE')

    if request.method == 'POST':
        if not config_file_path:
            return jsonify({'error': 'MAP_OPACITY_CONFIG_FILE path not configured in the application.'}), 500

        data = request.get_json()
        if not data or 'opacity' not in data:
            return jsonify({'error': 'Missing "opacity" in request data.'}), 400

        try:
            new_opacity = float(data['opacity'])
            if not (0.0 <= new_opacity <= 1.0):
                return jsonify({'error': 'Opacity value must be between 0.0 and 1.0.'}), 400
        except ValueError:
            return jsonify({'error': 'Invalid opacity value. Must be a float.'}), 400

        try:
            # Ensure directory for the config file exists
            config_dir = os.path.dirname(config_file_path)
            if config_dir: # Only create if dirname is not empty (e.g. not just a filename)
                 os.makedirs(config_dir, exist_ok=True)

            with open(config_file_path, 'w') as f:
                json.dump({'map_resource_opacity': new_opacity}, f)
            current_app.logger.info(f"Map resource opacity updated to {new_opacity} by user {current_user.username if hasattr(current_user, 'username') else 'Unknown'}")
            return jsonify({'message': 'Map opacity updated successfully.', 'opacity': new_opacity}), 200
        except IOError as e:
            current_app.logger.error(f"Failed to write map opacity to {config_file_path}: {e}")
            return jsonify({'error': f'Failed to save opacity setting: {str(e)}'}), 500
        except Exception as e: # Catch any other unexpected errors during file write
            current_app.logger.error(f"An unexpected error occurred while writing map opacity to {config_file_path}: {e}")
            return jsonify({'error': f'An unexpected error occurred: {str(e)}'}), 500

    # GET request
    current_opacity = get_map_opacity_value()
    return jsonify({'opacity': current_opacity}), 200

def init_api_system_settings_routes(app):
    app.register_blueprint(api_system_settings_bp)
