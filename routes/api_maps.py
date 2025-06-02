import os
import json
from datetime import datetime, timezone, date, time # Added time
from werkzeug.utils import secure_filename

from flask import Blueprint, jsonify, request, url_for, current_app
from flask_login import login_required, current_user
from sqlalchemy import func # For func.date in get_map_details

# Local imports
from extensions import db
from models import FloorMap, Resource, Booking
from auth import permission_required
# Assuming these utils will be moved to utils.py or are already there
from utils import add_audit_log, allowed_file, _get_map_configuration_data, _import_map_configuration_data

# Conditional import for Azure
try:
    from azure_backup import save_floor_map_to_share
except ImportError:
    save_floor_map_to_share = None

# Blueprint Configuration
api_maps_bp = Blueprint('api_maps', __name__, url_prefix='/api')

# Initialization function
def init_api_maps_routes(app):
    app.register_blueprint(api_maps_bp)

# --- Map API Routes ---

@api_maps_bp.route('/maps', methods=['GET'])
def get_public_floor_maps():
    try:
        maps = FloorMap.query.all()
        maps_list = []
        for m in maps:
            maps_list.append({
                'id': m.id,
                'name': m.name,
                'image_filename': m.image_filename,
                'location': m.location,
                'floor': m.floor,
                'image_url': url_for('static', filename=f'floor_map_uploads/{m.image_filename}', _external=False) # Ensure local URL
            })
        return jsonify(maps_list), 200
    except Exception as e:
        current_app.logger.exception("Error fetching public floor maps:")
        return jsonify({'error': 'Failed to fetch maps due to a server error.'}), 500

@api_maps_bp.route('/admin/maps', methods=['POST'])
@login_required
@permission_required('manage_floor_maps')
def upload_floor_map():
    if 'map_image' not in request.files:
        current_app.logger.warning("Map image missing in upload request.")
        return jsonify({'error': 'No map_image file part in the request.'}), 400

    file = request.files['map_image']
    map_name = request.form.get('map_name')
    location = request.form.get('location')
    floor = request.form.get('floor')

    if not map_name:
        current_app.logger.warning("Map name missing in upload request.")
        return jsonify({'error': 'map_name is required.'}), 400

    if file.filename == '':
        current_app.logger.warning("No file selected for map upload.")
        return jsonify({'error': 'No selected file.'}), 400

    if file and allowed_file(file.filename): # allowed_file from utils
        filename = secure_filename(file.filename)

        existing_map_by_filename = FloorMap.query.filter_by(image_filename=filename).first()
        existing_map_by_name = FloorMap.query.filter_by(name=map_name).first()

        if existing_map_by_filename:
            current_app.logger.warning(f"Attempt to upload map with duplicate filename: {filename}")
            return jsonify({'error': 'A map with this image filename already exists.'}), 409
        if existing_map_by_name:
            current_app.logger.warning(f"Attempt to upload map with duplicate name: {map_name}")
            return jsonify({'error': 'A map with this name already exists.'}), 409

        file_path = None
        try:
            # Use current_app.config for UPLOAD_FOLDER
            upload_folder = current_app.config.get('UPLOAD_FOLDER', os.path.join(current_app.root_path, 'static', 'floor_map_uploads'))
            if not os.path.exists(upload_folder): # Ensure folder exists
                os.makedirs(upload_folder)

            file_path = os.path.join(upload_folder, filename)
            file.save(file_path)

            if save_floor_map_to_share: # Conditional Azure upload
                try:
                    save_floor_map_to_share(file_path, filename)
                except Exception as azure_e:
                    current_app.logger.exception(f'Failed to upload floor map to Azure File Share: {azure_e}')
                    # Decide if this is a critical failure or just a warning

            new_map = FloorMap(name=map_name, image_filename=filename,
                               location=location, floor=floor)
            db.session.add(new_map)
            db.session.commit()
            current_app.logger.info(f"Floor map '{map_name}' uploaded successfully by {current_user.username}.")
            add_audit_log(action="CREATE_MAP_SUCCESS", details=f"Floor map '{map_name}' (ID: {new_map.id}) uploaded by {current_user.username}.")
            return jsonify({
                'id': new_map.id, 'name': new_map.name, 'image_filename': new_map.image_filename,
                'location': new_map.location, 'floor': new_map.floor,
                'image_url': url_for('static', filename=f'floor_map_uploads/{new_map.image_filename}', _external=False)
            }), 201
        except Exception as e:
            db.session.rollback()
            if file_path and os.path.exists(file_path):
                 os.remove(file_path)
                 current_app.logger.info(f"Cleaned up partially uploaded file: {file_path}")
            current_app.logger.exception(f"Error uploading floor map '{map_name}':")
            add_audit_log(action="CREATE_MAP_FAILED", details=f"Failed to upload floor map '{map_name}' by {current_user.username}. Error: {str(e)}")
            return jsonify({'error': f'Failed to upload map due to a server error: {str(e)}'}), 500
    else:
        current_app.logger.warning(f"File type not allowed for map upload: {file.filename}")
        return jsonify({'error': 'File type not allowed. Allowed types are: png, jpg, jpeg.'}), 400

@api_maps_bp.route('/admin/maps', methods=['GET'])
@login_required
@permission_required('manage_floor_maps')
def get_floor_maps():
    try:
        maps = FloorMap.query.all()
        maps_list = []
        for m in maps:
            maps_list.append({
                'id': m.id, 'name': m.name, 'image_filename': m.image_filename,
                'location': m.location, 'floor': m.floor,
                'image_url': url_for('static', filename=f'floor_map_uploads/{m.image_filename}', _external=False)
            })
        current_app.logger.info(f"Admin {current_user.username} fetched all floor maps.")
        return jsonify(maps_list), 200
    except Exception as e:
        current_app.logger.exception("Error fetching floor maps for admin:")
        return jsonify({'error': 'Failed to fetch maps due to a server error.'}), 500

@api_maps_bp.route('/admin/maps/<int:map_id>', methods=['DELETE'])
@login_required
@permission_required('manage_floor_maps')
def delete_floor_map(map_id):
    floor_map = FloorMap.query.get(map_id)
    if not floor_map:
        current_app.logger.warning(f"Attempt to delete non-existent floor map ID: {map_id} by user {current_user.username}")
        return jsonify({'error': 'Floor map not found.'}), 404

    map_name_for_log = floor_map.name
    image_filename_for_log = floor_map.image_filename
    upload_folder = current_app.config.get('UPLOAD_FOLDER', os.path.join(current_app.root_path, 'static', 'floor_map_uploads'))


    try:
        associated_resources = Resource.query.filter_by(floor_map_id=map_id).all()
        for resource in associated_resources:
            resource.floor_map_id = None
            resource.map_coordinates = None
        db.session.flush()
        db.session.delete(floor_map)

        if floor_map.image_filename:
            image_path = os.path.join(upload_folder, floor_map.image_filename)
            try:
                if os.path.exists(image_path):
                    os.remove(image_path)
                    current_app.logger.info(f"Successfully deleted map image file: {image_path}")
                else:
                    current_app.logger.warning(f"Map image file not found for deletion: {image_path}")
            except OSError as e_os:
                current_app.logger.error(f"Error deleting map image file {image_path}: {e_os}", exc_info=True)

        db.session.commit()
        current_app.logger.info(f"Floor map ID {map_id} ('{map_name_for_log}') and image '{image_filename_for_log}' deleted by {current_user.username}.")
        add_audit_log(action="DELETE_MAP_SUCCESS", details=f"Floor map ID {map_id} ('{map_name_for_log}', image: '{image_filename_for_log}') deleted by {current_user.username}.")
        return jsonify({'message': f"Floor map '{map_name_for_log}' deleted."}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error deleting floor map ID {map_id} ('{map_name_for_log}'):")
        add_audit_log(action="DELETE_MAP_FAILED", details=f"Failed to delete map ID {map_id} ('{map_name_for_log}') by {current_user.username}. Error: {str(e)}")
        return jsonify({'error': 'Failed to delete floor map due to a server error.'}), 500

@api_maps_bp.route('/admin/maps/export_configuration', methods=['GET'])
@login_required
@permission_required('manage_floor_maps')
def export_map_configuration():
    try:
        export_data = _get_map_configuration_data() # Assumes this util is available
        response = jsonify(export_data)
        response.headers['Content-Disposition'] = 'attachment; filename=map_configuration_export.json'
        response.mimetype = 'application/json'
        current_app.logger.info(f"User {current_user.username} exported map configuration.")
        add_audit_log(action="EXPORT_MAP_CONFIGURATION", details=f"User {current_user.username} exported map configuration.")
        return response
    except Exception as e:
        current_app.logger.exception("Error exporting map configuration:")
        add_audit_log(action="EXPORT_MAP_CONFIGURATION_FAILED", details=f"User {current_user.username} failed to export. Error: {str(e)}")
        return jsonify({'error': 'Failed to export map configuration.'}), 500

@api_maps_bp.route('/admin/maps/import_configuration', methods=['POST'])
@login_required
@permission_required('manage_floor_maps')
def import_map_configuration():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request.'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file.'}), 400
    if not file.filename.endswith('.json'):
        return jsonify({'error': 'File must be a JSON file.'}), 400
    try:
        config_data = json.load(file)
    except json.JSONDecodeError:
        return jsonify({'error': 'Invalid JSON file.'}), 400

    summary, status_code = _import_map_configuration_data(config_data) # Assumes this util is available
    return jsonify(summary), status_code

@api_maps_bp.route('/map_details/<int:map_id>', methods=['GET'])
def get_map_details(map_id):
    date_str = request.args.get('date')
    target_date_obj = None
    if date_str:
        try:
            target_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            current_app.logger.warning(f"Invalid date format for map details: {date_str}")
            return jsonify({'error': 'Invalid date format. Please use YYYY-MM-DD.'}), 400
    else:
        target_date_obj = date.today()

    try:
        floor_map = FloorMap.query.get(map_id)
        if not floor_map:
            current_app.logger.warning(f"Map details requested for non-existent map ID: {map_id}")
            return jsonify({'error': 'Floor map not found.'}), 404

        map_details_response = {
            'id': floor_map.id, 'name': floor_map.name,
            'image_url': url_for('static', filename=f'floor_map_uploads/{floor_map.image_filename}', _external=False),
            'location': floor_map.location, 'floor': floor_map.floor
        }

        mapped_resources_query = Resource.query.filter(
            Resource.floor_map_id == map_id,
            Resource.map_coordinates.isnot(None),
            Resource.status == 'published'
        ).all()

        mapped_resources_list = []
        for resource in mapped_resources_query:
            bookings_on_date = Booking.query.filter(
                Booking.resource_id == resource.id,
                func.date(Booking.start_time) == target_date_obj # func.date needs sqlalchemy import
            ).all()
            bookings_info = [{'title': b.title, 'user_name': b.user_name,
                              'start_time': b.start_time.strftime('%H:%M:%S'),
                              'end_time': b.end_time.strftime('%H:%M:%S')} for b in bookings_on_date]

            resource_info = {
                'id': resource.id, 'name': resource.name, 'capacity': resource.capacity,
                'equipment': resource.equipment,
                'image_url': url_for('static', filename=f'resource_uploads/{resource.image_filename}', _external=False) if resource.image_filename else None,
                'map_coordinates': json.loads(resource.map_coordinates) if resource.map_coordinates else None,
                'booking_restriction': resource.booking_restriction, 'status': resource.status,
                'published_at': resource.published_at.isoformat() if resource.published_at else None,
                'allowed_user_ids': resource.allowed_user_ids,
                'roles': [{'id': role.id, 'name': role.name} for role in resource.roles],
                'bookings_on_date': bookings_info
            }
            mapped_resources_list.append(resource_info)

        current_app.logger.info(f"Fetched map details for map ID {map_id} for date {target_date_obj}.")
        return jsonify({
            'map_details': map_details_response,
            'mapped_resources': mapped_resources_list
        }), 200
    except Exception as e:
        current_app.logger.exception(f"Error fetching map details for map_id {map_id}:")
        return jsonify({'error': 'Failed to fetch map details due to a server error.'}), 500
