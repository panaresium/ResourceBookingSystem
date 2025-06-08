import os
import json
from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user # Added current_user
from auth import permission_required

# Blueprint Configuration
admin_api_system_settings_bp = Blueprint('admin_api_system_settings', __name__, url_prefix='/api/admin/system-settings')

def get_map_opacity_value():
    """
    Retrieves the map opacity value.
    Priority:
    1. Value from MAP_OPACITY_CONFIG_FILE.
    2. Value from MAP_RESOURCE_OPACITY environment variable.
    3. Default value (0.7).
    """
    default_opacity = 0.7
    env_opacity_str = os.environ.get('MAP_RESOURCE_OPACITY')

    # Try from config file first
    config_file_path = current_app.config.get('MAP_OPACITY_CONFIG_FILE')
    if config_file_path:
        try:
            # Ensure config_file_path is an absolute path or correctly relative to the app's root
            # For simplicity, assuming it's an absolute path or correctly resolved by the app
            if not os.path.isabs(config_file_path):
                # This might be needed if DATA_DIR in config.py is not absolute
                # However, Path(basedir / 'data') should make it absolute.
                # For now, assume config_file_path is directly usable.
                pass

            if os.path.exists(config_file_path):
                with open(config_file_path, 'r') as f:
                    data = json.load(f)
                    opacity = data.get('map_resource_opacity')
                    if opacity is not None:
                        try:
                            opacity_float = float(opacity)
                            if 0.0 <= opacity_float <= 1.0:
                                return opacity_float
                            else:
                                current_app.logger.warning(f"Opacity value {opacity_float} from {config_file_path} is out of range (0.0-1.0).")
                        except ValueError:
                            current_app.logger.warning(f"Invalid opacity value '{opacity}' in {config_file_path}. Not a float.")
        except (IOError, json.JSONDecodeError, TypeError) as e: # Added TypeError for safety if config_file_path is None and os.path.exists is called
            current_app.logger.error(f"Error reading or parsing {config_file_path}: {e}")

    # Try from environment variable if not found or invalid in config file
    if env_opacity_str:
        try:
            env_opacity_float = float(env_opacity_str)
            if 0.0 <= env_opacity_float <= 1.0:
                return env_opacity_float
            else:
                current_app.logger.warning(f"MAP_RESOURCE_OPACITY environment variable value '{env_opacity_str}' is out of range (0.0-1.0).")
        except ValueError:
            current_app.logger.warning(f"MAP_RESOURCE_OPACITY environment variable '{env_opacity_str}' is not a valid float.")

    # Fallback to app config's direct MAP_RESOURCE_OPACITY if all else fails or is invalid
    # This covers the case where the env var was set but invalid, and no file config.
    # The config.py already has logic to set MAP_RESOURCE_OPACITY from env var or default.
    # This could be a simpler fallback.
    app_config_opacity = current_app.config.get('MAP_RESOURCE_OPACITY', default_opacity)
    if isinstance(app_config_opacity, (float, int)) and 0.0 <= app_config_opacity <= 1.0:
        return float(app_config_opacity)

    current_app.logger.debug(f"Falling back to default opacity {default_opacity} after checking file and env var.")
    return default_opacity


@admin_api_system_settings_bp.route('/map-opacity', methods=['GET', 'POST'])
@login_required
@permission_required('manage_system_settings') # Assuming a general permission for system settings
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

# Function to initialize this blueprint
def init_admin_api_system_settings_routes(app):
    app.register_blueprint(admin_api_system_settings_bp)

# Small adjustment to get_map_opacity_value:
# The original logic for MAP_RESOURCE_OPACITY in config.py already handles env var and default.
# So, get_map_opacity_value should prioritize file, then fall back to current_app.config['MAP_RESOURCE_OPACITY']
# which itself has the logic for env var and default.

# Revised get_map_opacity_value for clarity and to leverage existing config.py logic:
def get_map_opacity_value_revised():
    """
    Retrieves the map opacity value.
    Priority:
    1. Value from MAP_OPACITY_CONFIG_FILE (if configured and valid).
    2. Value from current_app.config['MAP_RESOURCE_OPACITY'] (which handles env var and default).
    """
    config_file_path = current_app.config.get('MAP_OPACITY_CONFIG_FILE')

    if config_file_path:
        try:
            if os.path.exists(config_file_path):
                with open(config_file_path, 'r') as f:
                    data = json.load(f)
                    opacity_val = data.get('map_resource_opacity')
                    if opacity_val is not None:
                        try:
                            opacity_float = float(opacity_val)
                            if 0.0 <= opacity_float <= 1.0:
                                current_app.logger.debug(f"Opacity {opacity_float} loaded from file {config_file_path}")
                                return opacity_float
                            else:
                                current_app.logger.warning(f"Opacity value {opacity_float} from {config_file_path} is out of range (0.0-1.0).")
                        except ValueError:
                            current_app.logger.warning(f"Invalid opacity value '{opacity_val}' in {config_file_path}. Not a float.")
        except (IOError, json.JSONDecodeError, TypeError) as e:
            current_app.logger.error(f"Error reading or parsing {config_file_path}: {e}. Falling back.")

    # Fallback to the value already processed by config.py (env var or its default)
    # config.py should ensure MAP_RESOURCE_OPACITY is always a valid float.
    default_from_config = current_app.config.get('MAP_RESOURCE_OPACITY', 0.7) # 0.7 is the ultimate fallback
    current_app.logger.debug(f"Falling back to app config opacity {default_from_config} (from env or default in config.py).")
    return default_from_config

# Replace the original get_map_opacity_value with the revised one in the route handler
# This is a bit hacky for the create_file_with_block tool, ideally the whole file is defined once.
# For the purpose of this tool, I'll comment out the old function and make sure the new one is used.
# The actual implementation will use the revised function.
# For this tool, I will define the revised function and then make sure the route calls it.
# The prompt's code had get_map_opacity_value, so I will stick to that name but use the revised logic.

# Corrected get_map_opacity_value using the revised logic:
def get_map_opacity_value(): # Renaming revised to original name
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

# The rest of the file is as provided in the prompt, using the corrected get_map_opacity_value above.
# The route manage_map_opacity will automatically use the corrected get_map_opacity_value.
# The init_admin_api_system_settings_routes function also remains the same.
# The Blueprint configuration also remains the same.
# No other changes to the provided code structure are needed other than the import and this function's logic.
