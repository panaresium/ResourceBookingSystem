import os
import json
import io
import zipfile
from datetime import datetime, timezone, date, time # Added time
from werkzeug.utils import secure_filename

from flask import Blueprint, jsonify, request, url_for, current_app, send_file
from flask_login import login_required, current_user
from sqlalchemy import func # For func.date in get_map_details
from sqlalchemy.sql import func as sqlfunc # Added for explicit use of sqlfunc.trim/lower

# Local imports
from extensions import db
from models import FloorMap, Resource, Booking, Role # Role removed if no longer needed
from auth import permission_required
# Assuming these utils will be moved to utils.py or are already there
from utils import add_audit_log, allowed_file, _get_map_configuration_data, _import_map_configuration_data, check_resources_availability_for_user, get_detailed_map_availability_for_user, _get_map_configuration_data_zip

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

@api_maps_bp.route('/locations-availability', methods=['GET'])
@login_required
def get_locations_availability():
    date_str = request.args.get('date')
    target_date = None
    if date_str:
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            current_app.logger.warning(f"Invalid date format for locations-availability: {date_str}")
            return jsonify({'error': 'Invalid date format. Please use YYYY-MM-DD.'}), 400
    else:
        target_date = date.today()

    try:
        # Fetch unique location names
        locations_query = db.session.query(FloorMap.location).distinct().all()
        location_names = [loc[0] for loc in locations_query if loc[0]] # Ensure location is not None

        results = []
        # Define primary time slots (example: 8am-12pm, 1pm-5pm)
        # These should ideally be configurable or based on resource's operating hours if available
        primary_slots = [
            (time(8, 0), time(12, 0)),
            (time(13, 0), time(17, 0))
        ]

        for loc_name in location_names:
            location_available = False
            floor_maps_in_location = FloorMap.query.filter_by(location=loc_name).all()

            for floor_map in floor_maps_in_location:
                if location_available: # Already found an available resource in this location
                    break

                resources_on_map = Resource.query.filter(
                    Resource.floor_map_id == floor_map.id,
                    Resource.status == 'published'
                ).all()

                # Use the new helper function for the list of resources on this map
                if resources_on_map:
                    if check_resources_availability_for_user(resources_on_map, target_date, current_user, primary_slots, current_app.logger):
                        location_available = True
                        # Found an available resource in this location, no need to check other maps in this location
                        break

            results.append({"location_name": loc_name, "is_available": location_available})

        return jsonify(results), 200

    except Exception as e:
        current_app.logger.exception(f"Error fetching locations availability for date {target_date}:")
        return jsonify({'error': 'Failed to fetch locations availability due to a server error.'}), 500

@api_maps_bp.route('/maps-availability', methods=['GET'])
@login_required
def get_maps_availability():
    date_str = request.args.get('date')
    target_date = None
    if date_str:
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            current_app.logger.warning(f"Invalid date format for maps-availability: {date_str}")
            return jsonify({'error': 'Invalid date format. Please use YYYY-MM-DD.'}), 400
    else:
        target_date = date.today()

    try:
        all_floor_maps = FloorMap.query.all()
        results = []

        primary_slots = [
            (time(8, 0), time(12, 0)),
            (time(13, 0), time(17, 0))
        ]

        for floor_map_item in all_floor_maps:
            availability_status = "low" # Default status

            resources_on_map = Resource.query.filter(
                Resource.floor_map_id == floor_map_item.id,
                Resource.status == 'published'
            ).all()

            if not resources_on_map:
                availability_status = "low"
            else:
                details = get_detailed_map_availability_for_user(
                    resources_on_map,
                    target_date,
                    current_user,
                    primary_slots,
                    current_app.logger
                )
                total_slots = details.get('total_primary_slots', 0)
                available_slots = details.get('available_primary_slots_for_user', 0)

                if total_slots == 0:
                    availability_status = "low"
                else:
                    percentage = (available_slots / total_slots) * 100
                    if percentage >= 50:
                        availability_status = "high"
                    elif percentage > 0:
                        availability_status = "medium"
                    else: # percentage == 0
                        availability_status = "low"

            results.append({
                "map_id": floor_map_item.id,
                "map_name": floor_map_item.name,
                "location": floor_map_item.location,
                "floor": floor_map_item.floor,
                "availability_status": availability_status
            })

        return jsonify(results), 200

    except Exception as e:
        current_app.logger.exception(f"Error fetching maps availability for date {target_date}:")
        return jsonify({'error': 'Failed to fetch maps availability due to a server error.'}), 500


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
                'offset_x': m.offset_x,
                'offset_y': m.offset_y,
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
    offset_x_str = request.form.get('offset_x', '0')
    offset_y_str = request.form.get('offset_y', '0')

    try:
        offset_x = int(offset_x_str)
    except ValueError:
        offset_x = 0
    try:
        offset_y = int(offset_y_str)
    except ValueError:
        offset_y = 0

    if not map_name:
        current_app.logger.warning("Map name missing in upload request.")
        return jsonify({'error': 'map_name is required.'}), 400

    if file.filename == '':
        current_app.logger.warning("No file selected for map upload.")
        return jsonify({'error': 'No selected file.'}), 400

    if file and allowed_file(file.filename):
        original_filename = file.filename
        filename = secure_filename(original_filename).lower()
        current_app.logger.info(f"Upload attempt: original='{original_filename}', standardized='{filename}' by user '{current_user.username}'")

        # Check using the standardized filename
        existing_map_by_filename = FloorMap.query.filter_by(image_filename=filename).first()
        if existing_map_by_filename:
            current_app.logger.warning(f"Duplicate check: Found existing map by standardized filename '{filename}'. ID: {existing_map_by_filename.id}")
            return jsonify({'error': 'A map with this image filename (or similar after standardization) already exists.'}), 409
        else:
            current_app.logger.info(f"Duplicate check: No existing map found for standardized filename '{filename}'. Proceeding with upload.")

        # Note: existing_map_by_name check can remain as is, as map names might have legitimate case differences.
        existing_map_by_name = FloorMap.query.filter_by(name=map_name).first()
        if existing_map_by_name: # This check is fine as is
            current_app.logger.warning(f"Attempt to upload map with duplicate name: {map_name}")
            return jsonify({'error': 'A map with this name already exists.'}), 409

        file_path = None
        try:
            # Use current_app.config for UPLOAD_FOLDER
            upload_folder = current_app.config.get('UPLOAD_FOLDER', os.path.join(current_app.root_path, 'static', 'floor_map_uploads'))
            if not os.path.exists(upload_folder): # Ensure folder exists
                os.makedirs(upload_folder)

            # Use standardized filename for saving
            file_path = os.path.join(upload_folder, filename) # Standardized
            current_app.logger.info(f"Saving uploaded file to: {file_path}")
            file.save(file_path)

            if save_floor_map_to_share: # Conditional Azure upload
                try:
                    current_app.logger.info(f"Attempting to save '{filename}' to Azure File Share.")
                    save_floor_map_to_share(file_path, filename) # Standardized
                    current_app.logger.info(f"Successfully saved '{filename}' to Azure File Share.")
                except Exception as azure_e:
                    current_app.logger.exception(f'Failed to upload floor map to Azure File Share: {azure_e}')
                    # Decide if this is a critical failure or just a warning

            current_app.logger.info(f"Creating FloorMap object with name='{map_name}', image_filename='{filename}', location='{location}', floor='{floor}', offset_x={offset_x}, offset_y={offset_y}")
            new_map = FloorMap(name=map_name, image_filename=filename, # Use standardized filename
                               location=location, floor=floor,
                               offset_x=offset_x, offset_y=offset_y) # Assuming offsets are handled

            current_app.logger.info(f"Adding FloorMap instance to session: {new_map!r}") # Use !r for repr
            db.session.add(new_map)

            current_app.logger.info(f"Attempting to commit session for new map: {new_map.name}, image: {new_map.image_filename}")
            db.session.commit() # Commit first

            # Log success AFTER commit (already moved in previous fix)
            current_app.logger.info(f"DB Commit successful for map '{new_map.name}'. ID: {new_map.id}")
            add_audit_log(action="CREATE_MAP_SUCCESS", details=f"Floor map '{map_name}' (ID: {new_map.id}, image: {filename}, Offsets: ({offset_x},{offset_y})) uploaded by {current_user.username}.")

            return jsonify({
                'id': new_map.id, 'name': new_map.name, 'image_filename': new_map.image_filename, # This is the standardized filename
                'location': new_map.location, 'floor': new_map.floor,
                'offset_x': new_map.offset_x, 'offset_y': new_map.offset_y, # Already included
                'image_url': url_for('static', filename=f'floor_map_uploads/{new_map.image_filename}', _external=False) # Uses standardized filename
            }), 201
        except Exception as e:
            db.session.rollback()
            if file_path and os.path.exists(file_path):
                 os.remove(file_path)
                 current_app.logger.info(f"Cleaned up partially uploaded file: {file_path} (original: {original_filename})")
            current_app.logger.error(f"Error during DB commit or file handling for map '{map_name}' (standardized filename: '{filename}'). Exception: {str(e)}", exc_info=True)
            add_audit_log(action="CREATE_MAP_FAILED", details=f"Failed to upload floor map '{map_name}' (original filename: {original_filename}) by {current_user.username}. Error: {str(e)}")
            return jsonify({'error': f'Failed to upload map due to a server error: {str(e)}'}), 500
    else:
        # Ensure original_filename is defined for this log, even if allowed_file is false early
        original_filename_for_log = file.filename if hasattr(file, 'filename') else "Unknown"
        current_app.logger.warning(f"File type not allowed for map upload: {original_filename_for_log}")
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
                'offset_x': m.offset_x, 'offset_y': m.offset_y,
                'image_url': url_for('static', filename=f'floor_map_uploads/{m.image_filename}', _external=False)
                # 'assigned_role_ids' removed
            })
        current_app.logger.info(f"Admin {current_user.username} fetched all floor maps.") # Log message reverted
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
        zip_buffer, zip_filename = _get_map_configuration_data_zip()
        if zip_buffer is None or zip_filename is None:
            current_app.logger.error(f"Failed to generate map configuration ZIP for user {current_user.username}. _get_map_configuration_data_zip returned None.")
            add_audit_log(action="EXPORT_MAP_CONFIGURATION_FAILED", details=f"User {current_user.username} failed to export map configuration (ZIP generation error).")
            return jsonify({'error': 'Failed to generate map configuration export file.'}), 500

        current_app.logger.info(f"User {current_user.username} successfully generated map configuration ZIP: {zip_filename}.")
        add_audit_log(action="EXPORT_MAP_CONFIGURATION", details=f"User {current_user.username} exported map configuration as ZIP: {zip_filename}.")

        return send_file(
            zip_buffer,
            as_attachment=True,
            download_name=zip_filename,
            mimetype='application/zip'
        )
    except Exception as e:
        current_app.logger.exception("Error exporting map configuration as ZIP:")
        add_audit_log(action="EXPORT_MAP_CONFIGURATION_FAILED", details=f"User {current_user.username} failed to export map configuration as ZIP. Error: {str(e)}")
        return jsonify({'error': 'Failed to export map configuration due to an unexpected server error.'}), 500

@api_maps_bp.route('/admin/maps/import_configuration', methods=['POST'])
@login_required
@permission_required('manage_floor_maps')
def import_map_configuration():
    if 'file' not in request.files:
        current_app.logger.warning("Import map configuration: No file part in request.")
        return jsonify({'error': 'No file part in the request.'}), 400

    file = request.files['file']
    original_filename = file.filename

    if original_filename == '':
        current_app.logger.warning("Import map configuration: No file selected.")
        return jsonify({'error': 'No selected file.'}), 400

    if not original_filename.endswith('.zip'):
        current_app.logger.warning(f"Import map configuration: Invalid file type '{original_filename}'. Must be a ZIP file.")
        return jsonify({'error': 'Invalid file type. File must be a ZIP archive (.zip).'}), 400

    try:
        zip_file_bytes = io.BytesIO(file.read())
        config_data = None

        with zipfile.ZipFile(zip_file_bytes, 'r') as zip_ref:
            if 'map_configuration.json' not in zip_ref.namelist():
                current_app.logger.error("Import map configuration: 'map_configuration.json' not found in ZIP.")
                add_audit_log(action="IMPORT_MAP_CONFIGURATION_FAILED", details=f"User {current_user.username} failed to import from ZIP '{original_filename}': map_configuration.json missing.")
                return jsonify({'error': "'map_configuration.json' not found in the uploaded ZIP file."}), 400

            try:
                json_data_str = zip_ref.read('map_configuration.json')
                config_data = json.loads(json_data_str)
                current_app.logger.info("Successfully extracted and parsed 'map_configuration.json' from ZIP.")
            except json.JSONDecodeError as json_err:
                current_app.logger.error(f"Import map configuration: Invalid JSON in 'map_configuration.json'. Error: {json_err}")
                add_audit_log(action="IMPORT_MAP_CONFIGURATION_FAILED", details=f"User {current_user.username} failed to import from ZIP '{original_filename}': Invalid JSON in map_configuration.json.")
                return jsonify({'error': f'Invalid JSON format in map_configuration.json: {str(json_err)}'}), 400

            # Determine upload folder path (consistent with _get_map_configuration_data_zip)
            upload_folder_maps = current_app.config.get('UPLOAD_FOLDER_MAPS')
            if not upload_folder_maps:
                static_folder = os.path.join(current_app.root_path, 'static')
                default_map_upload_subpath = 'floor_map_uploads'
                potential_path_static = os.path.join(static_folder, default_map_upload_subpath)
                if os.path.isdir(potential_path_static):
                    upload_folder_maps = potential_path_static
                else:
                    generic_upload_folder = current_app.config.get('UPLOAD_FOLDER')
                    if generic_upload_folder and os.path.isdir(generic_upload_folder):
                        potential_path_generic = os.path.join(generic_upload_folder, default_map_upload_subpath)
                        if os.path.isdir(potential_path_generic):
                            upload_folder_maps = potential_path_generic
                        else:
                            upload_folder_maps = generic_upload_folder
                    else:
                        upload_folder_maps = potential_path_static # Default to static subpath

            os.makedirs(upload_folder_maps, exist_ok=True)
            current_app.logger.info(f"Ensured image upload folder exists: {upload_folder_maps}")

            extracted_images_count = 0
            for member_name in zip_ref.namelist():
                if member_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')) and member_name != 'map_configuration.json':
                    s_filename = secure_filename(os.path.basename(member_name)) # Use os.path.basename to avoid issues with paths in zip
                    if not s_filename: # secure_filename might return empty if input is odd
                        current_app.logger.warning(f"Skipping image file with potentially insecure or empty name after sanitization: '{member_name}'")
                        continue

                    image_save_path = os.path.join(upload_folder_maps, s_filename)
                    try:
                        image_data = zip_ref.read(member_name)
                        with open(image_save_path, 'wb') as f_img:
                            f_img.write(image_data)
                        current_app.logger.info(f"Extracted and saved map image: {s_filename} to {image_save_path}")
                        extracted_images_count += 1
                    except Exception as e_img_save:
                        current_app.logger.error(f"Error saving image '{s_filename}' from ZIP to '{image_save_path}': {e_img_save}", exc_info=True)
                        # Decide if this is a critical error. For now, log and continue.
                        # Could collect these errors and report them in summary.

        # Proceed with data import using the extracted config_data
        summary, status_code = _import_map_configuration_data(config_data)

        # Add details about ZIP processing to summary if possible, or just log
        log_message = f"User {current_user.username} imported map configuration from ZIP '{original_filename}'. Images extracted: {extracted_images_count}."
        if 'message' in summary:
            summary['message'] = f"ZIP Import: {summary['message']} (Extracted {extracted_images_count} images from '{original_filename}')"

        current_app.logger.info(log_message + f" Import status: {status_code}")
        if status_code < 300: # Typically 200, 201, 207 for success/partial success
            add_audit_log(action="IMPORT_MAP_CONFIGURATION_SUCCESS", details=log_message)
        else: # 400, 500 for failures
            add_audit_log(action="IMPORT_MAP_CONFIGURATION_FAILED", details=log_message + f" Errors: {summary.get('errors', 'N/A')}")

        return jsonify(summary), status_code

    except zipfile.BadZipFile:
        current_app.logger.error(f"Import map configuration: Bad ZIP file uploaded ('{original_filename}').")
        add_audit_log(action="IMPORT_MAP_CONFIGURATION_FAILED", details=f"User {current_user.username} failed to import from ZIP '{original_filename}': Bad ZIP file.")
        return jsonify({'error': 'Uploaded file is not a valid ZIP archive or is corrupted.'}), 400
    except Exception as e:
        current_app.logger.exception(f"An unexpected error occurred during map configuration import from ZIP '{original_filename}':")
        add_audit_log(action="IMPORT_MAP_CONFIGURATION_FAILED", details=f"User {current_user.username} an unexpected error occurred during import from ZIP '{original_filename}'. Error: {str(e)}")
        return jsonify({'error': f'An unexpected error occurred during import: {str(e)}'}), 500

@api_maps_bp.route('/map_details/<int:map_id>', methods=['GET'])
@login_required
def get_map_details(map_id):
    active_booking_statuses_for_conflict_map_details = ['approved', 'pending', 'checked_in', 'confirmed']

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
            'location': floor_map.location, 'floor': floor_map.floor,
            'offset_x': floor_map.offset_x, 'offset_y': floor_map.offset_y
        }

        mapped_resources_query = Resource.query.filter(
            Resource.floor_map_id == map_id,
            Resource.map_coordinates.isnot(None),
            Resource.status == 'published'
        ).all()

        mapped_resources_list = []
        # user_role_ids = [role.id for role in current_user.roles] # This will be generated inside the loop now as user_role_ids_set

        for resource in mapped_resources_query:
            current_user_can_book_flag = False # Default deny

            if current_user.is_admin:
                current_app.logger.debug(f"User {current_user.username} is admin. Map access granted for resource {resource.id} via admin override.")
                current_user_can_book_flag = True
            elif not resource.roles: # No roles assigned to resource, public for authenticated users
                current_app.logger.debug(f"Resource {resource.id} has no specific roles assigned (resource.roles is empty). Granting map access (public for authenticated users).")
                current_user_can_book_flag = True
            else: # Resource has roles, check for overlap
                user_role_ids_set = {user_role.id for user_role in current_user.roles}
                resource_role_ids_set = {res_role.id for res_role in resource.roles}
                current_app.logger.debug(f"Resource {resource.id} (resource.roles): Comparing user roles {user_role_ids_set} with resource's assigned roles {resource_role_ids_set}.")
                if not user_role_ids_set.isdisjoint(resource_role_ids_set):
                    current_app.logger.debug(f"Resource {resource.id} (resource.roles): Overlap found. Map access granted.")
                    current_user_can_book_flag = True
                else:
                    current_app.logger.debug(f"Resource {resource.id} (resource.roles): No overlap. Map access denied.")
                    current_user_can_book_flag = False # Explicitly set, though already default

            bookings_on_date = Booking.query.filter(
                Booking.resource_id == resource.id,
                func.date(Booking.start_time) == target_date_obj,
                sqlfunc.trim(sqlfunc.lower(Booking.status)).in_(active_booking_statuses_for_conflict_map_details)
            ).all()
            bookings_info = [{'title': b.title, 'user_name': b.user_name,
                              'start_time': b.start_time.strftime('%H:%M:%S'),
                              'end_time': b.end_time.strftime('%H:%M:%S')} for b in bookings_on_date]

            # Parse map_coordinates (which no longer contains allowed_role_ids)
            parsed_map_coords = json.loads(resource.map_coordinates) if resource.map_coordinates else None

            resource_info = {
                'id': resource.id, 'name': resource.name, 'capacity': resource.capacity,
                'equipment': resource.equipment,
                'image_url': url_for('static', filename=f'resource_uploads/{resource.image_filename}', _external=False) if resource.image_filename else None,
                'map_coordinates': parsed_map_coords,
                'booking_restriction': resource.booking_restriction, 'status': resource.status,
                'published_at': resource.published_at.isoformat() if resource.published_at else None,
                'allowed_user_ids': resource.allowed_user_ids,
                'is_under_maintenance': resource.is_under_maintenance,
                'maintenance_until': resource.maintenance_until.isoformat() if resource.maintenance_until else None,
                'bookings_on_date': bookings_info,
                'current_user_can_book': current_user_can_book_flag
            }

            # Populate 'roles' for display directly from resource.roles
            allowed_roles_info_display = [{'id': role.id, 'name': role.name} for role in resource.roles]
            resource_info['roles'] = allowed_roles_info_display

            mapped_resources_list.append(resource_info)

        current_app.logger.info(f"User {current_user.username} fetched map details for map ID {map_id} for date {target_date_obj}. Total resources processed: {len(mapped_resources_list)}.")
        return jsonify({
            'map_details': map_details_response,
            'mapped_resources': mapped_resources_list
        }), 200
    except Exception as e:
        current_app.logger.exception(f"Error fetching map details for map_id {map_id}:")
        return jsonify({'error': 'Failed to fetch map details due to a server error.'}), 500

@api_maps_bp.route('/admin/maps/<int:map_id>/offsets', methods=['PUT'])
@login_required
@permission_required('manage_floor_maps')
def update_floor_map_offsets(map_id):
    floor_map = FloorMap.query.get(map_id)
    if not floor_map:
        current_app.logger.warning(f"Attempt to update offsets for non-existent floor map ID: {map_id} by user {current_user.username}")
        return jsonify({'error': 'Floor map not found.'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid request. JSON data expected.'}), 400

    offset_x_updated = False
    offset_y_updated = False

    if 'offset_x' in data:
        try:
            new_offset_x = int(data['offset_x'])
            if floor_map.offset_x != new_offset_x:
                floor_map.offset_x = new_offset_x
                offset_x_updated = True
        except ValueError:
            return jsonify({'error': 'Invalid offset_x value. Must be an integer.'}), 400

    if 'offset_y' in data:
        try:
            new_offset_y = int(data['offset_y'])
            if floor_map.offset_y != new_offset_y:
                floor_map.offset_y = new_offset_y
                offset_y_updated = True
        except ValueError:
            return jsonify({'error': 'Invalid offset_y value. Must be an integer.'}), 400

    if not offset_x_updated and not offset_y_updated:
        return jsonify({'message': 'No offset changes provided or values are the same.', 'map': {
            'id': floor_map.id,
            'name': floor_map.name,
            'offset_x': floor_map.offset_x,
            'offset_y': floor_map.offset_y
        }}), 200

    try:
        db.session.commit()
        current_app.logger.info(f"Offsets for floor map ID {map_id} ('{floor_map.name}') updated by {current_user.username}. New offsets: X={floor_map.offset_x}, Y={floor_map.offset_y}")
        add_audit_log(
            action="UPDATE_MAP_OFFSETS_SUCCESS",
            details=f"Offsets for floor map ID {map_id} ('{floor_map.name}') updated to X:{floor_map.offset_x}, Y:{floor_map.offset_y} by {current_user.username}.",
            user_id=current_user.id,
            username=current_user.username
        )
        return jsonify({
            'message': 'Floor map offsets updated successfully.',
            'map': {
                'id': floor_map.id,
                'name': floor_map.name,
                'offset_x': floor_map.offset_x,
                'offset_y': floor_map.offset_y
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error updating offsets for floor map ID {map_id}:")
        add_audit_log(
            action="UPDATE_MAP_OFFSETS_FAILED",
            details=f"Failed to update offsets for map ID {map_id} by {current_user.username}. Error: {str(e)}",
            user_id=current_user.id,
            username=current_user.username
        )
        return jsonify({'error': f'Failed to update map offsets due to a server error: {str(e)}'}), 500
# Removed the update_map_roles endpoint that was here.
