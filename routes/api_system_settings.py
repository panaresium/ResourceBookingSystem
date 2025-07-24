import os
import json
from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from auth import permission_required
from models import BookingSettings
from extensions import db

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

def get_map_opacity_value():
    """
    Retrieves the map opacity value.
    Priority:
    1. Value from MAP_OPACITY_CONFIG_FILE (if configured and valid).
    2. Value from current_app.config['MAP_RESOURCE_OPACITY'] (which handles env var and default).
    """
    config_file_path = current_app.config.get('MAP_OPACITY_CONFIG_FILE')

    if config_file_path: # Ensure path is configured
        try:
            # Ensure config_file_path is usable, Path objects from config.py should be fine
            if os.path.exists(config_file_path):
                with open(config_file_path, 'r') as f:
                    data = json.load(f)
                    opacity_val = data.get('map_resource_opacity')
                    if opacity_val is not None: # Check if key exists
                        try:
                            opacity_float = float(opacity_val)
                            if 0.0 <= opacity_float <= 1.0:
                                current_app.logger.debug(f"Opacity {opacity_float} loaded from file {config_file_path}")
                                return opacity_float
                            else:
                                current_app.logger.warning(f"Opacity value {opacity_float} from {config_file_path} is out of range (0.0-1.0). File value ignored.")
                        except ValueError:
                            current_app.logger.warning(f"Invalid opacity value '{opacity_val}' in {config_file_path}. Not a float. File value ignored.")
        except (IOError, json.JSONDecodeError, TypeError) as e: # Catch errors related to file access/parsing
            current_app.logger.error(f"Error reading/parsing {config_file_path}: {e}. Fallback will be used.")
        except Exception as e: # Catch any other unexpected errors
            current_app.logger.error(f"Unexpected error with config file {config_file_path}: {e}. Fallback will be used.")

    # Fallback to the value already processed by config.py (env var or its default in config.py)
    default_from_config = current_app.config.get('MAP_RESOURCE_OPACITY') # Should exist due to config.py
    if default_from_config is None: # Should not happen if config.py is loaded correctly
        current_app.logger.error("MAP_RESOURCE_OPACITY not found in app.config. This is unexpected. Using hardcoded default 0.7.")
        return 0.7

    current_app.logger.debug(f"Using opacity from app.config['MAP_RESOURCE_OPACITY']: {default_from_config} (derived from env var or default in config.py).")
    return default_from_config

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
