from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from sqlalchemy import func # For func.lower in create_resource, and func.ilike in get_all_users

# Local imports
from extensions import db
from models import User, Role # Assuming Role is needed for export/import and updates
from utils import add_audit_log
from auth import permission_required

# Blueprint Configuration
api_users_bp = Blueprint('api_users', __name__, url_prefix='/api')

# Initialization function
def init_api_users_routes(app):
    app.register_blueprint(api_users_bp)

@api_users_bp.route('/profile', methods=['PUT'])
@login_required
def update_profile():
    """Update current user's email or password."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    email = data.get('email')
    password = data.get('password')
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    phone = data.get('phone')
    section = data.get('section')
    department = data.get('department')
    position = data.get('position')

    # Check if any data was submitted
    if not any(data.values()): # Will be True if all values are None or empty strings after .get()
        # More specific check:
    # if email is None and password is None and first_name is None and last_name is None and phone is None and section is None and department is None and position is None:
        # Check if all relevant fields are None or empty (if get() returned default None)
        relevant_fields = ['email', 'password', 'first_name', 'last_name', 'phone', 'section', 'department', 'position']
        if all(data.get(field) is None or data.get(field) == '' for field in relevant_fields if data.get(field) is not None): # handles if key not present vs key is present and empty
             # Correction: if all provided fields are effectively empty or not provided.
             # A better check: if no fields that can be updated were provided with actual values.
            provided_values = {k: v for k, v in data.items() if v is not None and v != ''}
            if not provided_values:
                 return jsonify({'error': 'No changes submitted.'}), 400


    if email:
        if '@' not in email or '.' not in email.split('@')[-1]:
            return jsonify({'error': 'Invalid email format.'}), 400
        existing = User.query.filter(User.id != current_user.id).filter_by(email=email.strip()).first()
        if existing:
            return jsonify({'error': f"Email '{email.strip()}' already registered."}), 409
        current_user.email = email.strip()
    elif 'email' in data and data['email'] == '': # Explicitly setting email to empty is not allowed
        return jsonify({'error': 'Email cannot be empty.'}), 400


    if password:
        current_user.set_password(password)

    # Update new fields
    # For nullable string fields, an empty string from payload should translate to None or empty string in DB
    # based on how model handles it. Assuming empty string is acceptable or will be converted to None by ORM if needed.
    current_user.first_name = first_name.strip() if first_name is not None else None
    current_user.last_name = last_name.strip() if last_name is not None else None
    current_user.phone = phone.strip() if phone is not None else None
    current_user.section = section.strip() if section is not None else None
    current_user.department = department.strip() if department is not None else None
    current_user.position = position.strip() if position is not None else None

    try:
        db.session.commit()
        user_data = {
            'id': current_user.id,
            'username': current_user.username,
            'email': current_user.email,
            'first_name': current_user.first_name,
            'last_name': current_user.last_name,
            'phone': current_user.phone,
            'section': current_user.section,
            'department': current_user.department,
            'position': current_user.position
        }
        current_app.logger.info(f"User {current_user.username} updated their profile.")
        log_details = f"User {current_user.username} updated profile. "
        if email: log_details += f"Email changed. "
        if password: log_details += f"Password changed. "
        # Could add more details about which specific text fields changed if necessary
        if any([first_name, last_name, phone, section, department, position]):
            log_details += "Other profile fields updated."

        add_audit_log(action="UPDATE_PROFILE", details=log_details, user_id=current_user.id)
        return jsonify({'success': True, 'user': user_data, 'message': 'Profile updated.'}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error updating profile for user {current_user.username}:")
        add_audit_log(action="UPDATE_PROFILE_FAILED", details=f"User {current_user.username} failed to update profile. Error: {str(e)}", user_id=current_user.id)
        return jsonify({'error': 'Failed to update profile due to a server error.'}), 500

@api_users_bp.route('/admin/users', methods=['GET'])
@login_required
@permission_required('manage_users')
def get_all_users():
    try:
        username_filter = request.args.get('username_filter')
        is_admin_filter = request.args.get('is_admin')
        role_id_filter = request.args.get('role_id', type=int)

        query = User.query

        if username_filter:
            query = query.filter(User.username.ilike(f"%{username_filter}%"))

        if is_admin_filter is not None and is_admin_filter != '':
            val = is_admin_filter.lower()
            if val in ['true', '1', 'yes']:
                query = query.filter_by(is_admin=True)
            elif val in ['false', '0', 'no']:
                query = query.filter_by(is_admin=False)
            else:
                return jsonify({'error': 'Invalid is_admin value. Use true or false.'}), 400

        if role_id_filter:
            query = query.join(User.roles).filter(Role.id == role_id_filter)

        users = query.all()

        users_list = [{
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'is_admin': u.is_admin,
            'google_id': u.google_id,
            'roles': [{'id': role.id, 'name': role.name} for role in u.roles]
        } for u in users]
        current_app.logger.info(f"Admin user {current_user.username} fetched users list with filters.")
        return jsonify(users_list), 200
    except Exception as e:
        current_app.logger.exception("Error fetching all users:")
        return jsonify({'error': 'Failed to fetch users due to a server error.'}), 500

@api_users_bp.route('/admin/users', methods=['POST'])
@login_required
@permission_required('manage_users')
def create_user():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    is_admin = data.get('is_admin', False)

    if not username or not username.strip():
        return jsonify({'error': 'Username is required.'}), 400
    if not email or not email.strip():
        return jsonify({'error': 'Email is required.'}), 400
    if not password:
        return jsonify({'error': 'Password is required.'}), 400

    if '@' not in email or '.' not in email.split('@')[-1]:
        return jsonify({'error': 'Invalid email format.'}), 400

    if User.query.filter(func.lower(User.username) == func.lower(username.strip())).first():
        return jsonify({'error': f"Username '{username}' already exists."}), 409
    if User.query.filter(func.lower(User.email) == func.lower(email.strip())).first():
        return jsonify({'error': f"Email '{email}' already registered."}), 409

    new_user = User(username=username.strip(), email=email.strip(), is_admin=is_admin)
    new_user.set_password(password)

    try:
        db.session.add(new_user)
        db.session.commit()
        current_app.logger.info(f"User '{new_user.username}' created successfully by {current_user.username}.")
        add_audit_log(action="CREATE_USER_SUCCESS", details=f"User '{new_user.username}' (ID: {new_user.id}) created by {current_user.username}. Admin: {new_user.is_admin}.")
        return jsonify({
            'id': new_user.id,
            'username': new_user.username,
            'email': new_user.email,
            'is_admin': new_user.is_admin,
            'google_id': new_user.google_id,
            'roles': [{'id': role.id, 'name': role.name} for role in new_user.roles]
        }), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error creating user '{username}':")
        add_audit_log(action="CREATE_USER_FAILED", details=f"Failed to create user '{username}' by {current_user.username}. Error: {str(e)}")
        return jsonify({'error': 'Failed to create user due to a server error.'}), 500

@api_users_bp.route('/admin/users/<int:user_id>', methods=['PUT'])
@login_required
@permission_required('manage_users')
def update_user(user_id):
    user_to_update = User.query.get(user_id)
    if not user_to_update:
        return jsonify({'error': 'User not found.'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    if 'username' in data and data['username'] and data['username'].strip() and user_to_update.username != data['username'].strip():
        if User.query.filter(User.id != user_id).filter(func.lower(User.username) == func.lower(data['username'].strip())).first():
            return jsonify({'error': f"Username '{data['username'].strip()}' already exists."}), 409
        user_to_update.username = data['username'].strip()

    if 'email' in data and data['email'] and data['email'].strip() and user_to_update.email != data['email'].strip():
        if '@' not in data['email'] or '.' not in data['email'].split('@')[-1]:
            return jsonify({'error': 'Invalid email format.'}), 400
        if User.query.filter(User.id != user_id).filter(func.lower(User.email) == func.lower(data['email'].strip())).first():
            return jsonify({'error': f"Email '{data['email'].strip()}' already registered."}), 409
        user_to_update.email = data['email'].strip()

    if 'password' in data and data['password']:
        user_to_update.set_password(data['password'])
        current_app.logger.info(f"Password updated for user ID {user_id} by {current_user.username}.")

    if 'is_admin' in data and isinstance(data['is_admin'], bool):
        if user_to_update.id == current_user.id and not data['is_admin']:
            num_admins_flag = User.query.filter_by(is_admin=True).count()
            if num_admins_flag == 1:
                current_app.logger.warning(f"Admin user {current_user.username} attempted to remove their own admin status (is_admin flag) as the sole admin flag holder.")
        user_to_update.is_admin = data['is_admin']

    if 'role_ids' in data:
        role_ids = data.get('role_ids', [])
        if not isinstance(role_ids, list):
            return jsonify({'error': 'role_ids must be a list of integers.'}), 400

        new_roles = []
        for r_id in role_ids:
            if not isinstance(r_id, int):
                return jsonify({'error': f'Invalid role ID type: {r_id}. Must be integer.'}), 400
            role = Role.query.get(r_id)
            if not role:
                return jsonify({'error': f'Role with ID {r_id} not found.'}), 400
            new_roles.append(role)

        admin_role = Role.query.filter_by(name="Administrator").first()
        if admin_role:
            is_removing_admin_role_from_this_user = admin_role not in new_roles and admin_role in user_to_update.roles
            if is_removing_admin_role_from_this_user and user_to_update.id == current_user.id:
                users_with_admin_role = User.query.filter(User.roles.any(id=admin_role.id)).all()
                if len(users_with_admin_role) == 1 and users_with_admin_role[0].id == user_to_update.id:
                    current_app.logger.warning(f"Admin user {current_user.username} attempted to remove their own 'Administrator' role as the sole holder of this role.")
                    return jsonify({'error': 'Cannot remove the "Administrator" role from the only user holding it.'}), 403
        user_to_update.roles = new_roles
        current_app.logger.info(f"Roles updated for user ID {user_id} by {current_user.username}. New roles: {[r.name for r in new_roles]}")

    try:
        db.session.commit()
        current_app.logger.info(f"User ID {user_id} ('{user_to_update.username}') updated successfully by {current_user.username}.")
        add_audit_log(action="UPDATE_USER_SUCCESS", details=f"User '{user_to_update.username}' (ID: {user_id}) updated by {current_user.username}. Data: {str(data)}")
        return jsonify({
            'id': user_to_update.id, 'username': user_to_update.username, 'email': user_to_update.email,
            'is_admin': user_to_update.is_admin, 'google_id': user_to_update.google_id,
            'roles': [{'id': role.id, 'name': role.name} for role in user_to_update.roles]
        }), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error updating user {user_id}:")
        add_audit_log(action="UPDATE_USER_FAILED", details=f"Failed to update user ID {user_id} by {current_user.username}. Error: {str(e)}")
        return jsonify({'error': 'Failed to update user due to a server error.'}), 500

@api_users_bp.route('/admin/users/<int:user_id>', methods=['DELETE'])
@login_required
@permission_required('manage_users')
def delete_user(user_id):
    user_to_delete = User.query.get(user_id)
    if not user_to_delete:
        return jsonify({'error': 'User not found.'}), 404

    if current_user.id == user_to_delete.id:
        current_app.logger.warning(f"Admin user {current_user.username} attempted to delete their own account (ID: {user_id}) via admin endpoint.")
        return jsonify({'error': 'Admins cannot delete their own account through this endpoint.'}), 403

    if user_to_delete.is_admin:
        num_admins = User.query.filter_by(is_admin=True).count()
        if num_admins == 1:
            current_app.logger.warning(f"Admin user {current_user.username} attempted to delete the only admin user (ID: {user_id}, Username: {user_to_delete.username}).")
            return jsonify({'error': 'Cannot delete the only admin user in the system (based on is_admin flag).'}), 403

    admin_role = Role.query.filter_by(name="Administrator").first()
    if admin_role and admin_role in user_to_delete.roles:
        users_with_admin_role = User.query.filter(User.roles.any(id=admin_role.id)).all()
        if len(users_with_admin_role) == 1 and users_with_admin_role[0].id == user_to_delete.id:
            current_app.logger.warning(f"Admin user {current_user.username} attempted to delete the only user with 'Administrator' role (ID: {user_id}, Username: {user_to_delete.username}).")
            return jsonify({'error': "Cannot delete the only user with the 'Administrator' role."}), 403

    username_for_log = user_to_delete.username
    try:
        db.session.delete(user_to_delete)
        db.session.commit()
        current_app.logger.info(f"User ID {user_id} ('{username_for_log}') deleted successfully by {current_user.username}.")
        add_audit_log(action="DELETE_USER_SUCCESS", details=f"User '{username_for_log}' (ID: {user_id}) deleted by '{current_user.username}'.")
        return jsonify({'message': f"User '{username_for_log}' (ID: {user_id}) deleted successfully."}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error deleting user {user_id}:")
        add_audit_log(action="DELETE_USER_FAILED", details=f"Failed to delete user ID {user_id} ('{username_for_log}') by {current_user.username}. Error: {str(e)}")
        return jsonify({'error': 'Failed to delete user due to a server error.'}), 500

@api_users_bp.route('/admin/users/<int:user_id>/assign_google_auth', methods=['POST'])
@login_required
@permission_required('manage_users')
def assign_google_auth(user_id):
    user_to_update = User.query.get(user_id)
    if not user_to_update:
        return jsonify({'error': 'User not found.'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    google_id_to_assign = data.get('google_id')
    if not google_id_to_assign or not isinstance(google_id_to_assign, str) or not google_id_to_assign.strip():
        return jsonify({'error': 'google_id is required and must be a non-empty string.'}), 400

    google_id_to_assign = google_id_to_assign.strip()

    existing_user_with_google_id = User.query.filter(User.google_id == google_id_to_assign, User.id != user_id).first()
    if existing_user_with_google_id:
        current_app.logger.warning(f"Attempt to assign already used Google ID '{google_id_to_assign}' to user {user_id}. It's already linked to user {existing_user_with_google_id.id}.")
        return jsonify({'error': f"Google ID '{google_id_to_assign}' is already associated with another user (ID: {existing_user_with_google_id.id}, Username: {existing_user_with_google_id.username})."}), 409

    user_to_update.google_id = google_id_to_assign
    user_to_update.google_email = None

    try:
        db.session.commit()
        current_app.logger.info(f"Google ID '{google_id_to_assign}' assigned to user ID {user_id} ('{user_to_update.username}') by {current_user.username}.")
        add_audit_log(action="ASSIGN_GOOGLE_AUTH_SUCCESS", details=f"Google ID '{google_id_to_assign}' assigned by {current_user.username} to user '{user_to_update.username}' (ID: {user_id}).")
        return jsonify({
            'id': user_to_update.id, 'username': user_to_update.username, 'email': user_to_update.email,
            'is_admin': user_to_update.is_admin, 'google_id': user_to_update.google_id,
            'google_email': user_to_update.google_email,
            'roles': [{'id': role.id, 'name': role.name} for role in user_to_update.roles]
        }), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error assigning Google ID to user {user_id}:")
        add_audit_log(action="ASSIGN_GOOGLE_AUTH_FAILED", details=f"Failed to assign Google ID by {current_user.username} to user ID {user_id}. Error: {str(e)}")
        return jsonify({'error': 'Failed to assign Google ID due to a server error.'}), 500

@api_users_bp.route('/admin/users/bulk', methods=['DELETE'])
@login_required
@permission_required('manage_users')
def delete_users_bulk():
    data = request.get_json()
    if not data or 'ids' not in data or not isinstance(data['ids'], list):
        return jsonify({'error': 'Invalid input. "ids" list required.'}), 400

    ids = data['ids']
    deleted_ids = []
    skipped_ids = []
    errors = []

    for uid in ids:
        if not isinstance(uid, int):
            errors.append({'id': uid, 'error': 'Invalid ID type, must be integer.'})
            skipped_ids.append(uid)
            continue

        user = User.query.get(uid)
        if not user:
            skipped_ids.append(uid)
            errors.append({'id': uid, 'error': 'User not found.'})
            continue

        if user.id == current_user.id:
            skipped_ids.append(uid)
            errors.append({'id': uid, 'error': 'Cannot delete current user.'})
            continue

        # Safeguards similar to single delete
        if user.is_admin:
            num_admins = User.query.filter_by(is_admin=True).count()
            if num_admins == 1 and user.id == User.query.filter_by(is_admin=True).first().id : # Check if it's THE only one
                skipped_ids.append(uid)
                errors.append({'id': uid, 'error': 'Cannot delete the only admin user (is_admin flag).'})
                continue

        admin_role = Role.query.filter_by(name="Administrator").first()
        if admin_role and admin_role in user.roles:
            users_with_admin_role = User.query.filter(User.roles.any(id=admin_role.id)).all()
            if len(users_with_admin_role) == 1 and users_with_admin_role[0].id == user.id:
                skipped_ids.append(uid)
                errors.append({'id': uid, 'error': 'Cannot delete the only user with "Administrator" role.'})
                continue

        db.session.delete(user)
        deleted_ids.append(uid)
        add_audit_log(action="BULK_DELETE_USER", details=f"User ID {uid} ('{user.username}') deleted by {current_user.username} in bulk operation.")

    try:
        db.session.commit()
        current_app.logger.info(f"Bulk user deletion by {current_user.username}. Deleted: {deleted_ids}, Skipped: {skipped_ids}, Errors: {len(errors)}")
        return jsonify({'deleted': deleted_ids, 'skipped': skipped_ids, 'errors': errors}), 200 if not errors else 207
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error deleting users in bulk:")
        add_audit_log(action="BULK_DELETE_USER_FAILED", details=f"Bulk user deletion by {current_user.username} failed. Error: {str(e)}")
        return jsonify({'error': 'Failed to delete users due to a server error.'}), 500

@api_users_bp.route('/admin/users/export', methods=['GET'])
@login_required
@permission_required('manage_users')
def export_users():
    users = User.query.all()
    roles = Role.query.all() # Also export roles for context

    users_data = []
    for u in users:
        users_data.append({
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'is_admin': u.is_admin, # Legacy admin flag
            'google_id': u.google_id,
            'google_email': u.google_email,
            'password_hash': u.password_hash, # Include for full backup, though sensitive
            'role_ids': [r.id for r in u.roles]
        })

    roles_data = []
    for r in roles:
        roles_data.append({
            'id': r.id,
            'name': r.name,
            'description': r.description,
            'permissions': r.permissions
        })

    export_data = {'users': users_data, 'roles': roles_data}
    add_audit_log(action="EXPORT_USERS", details=f"User {current_user.username} exported user and role data.")
    return jsonify(export_data), 200

@api_users_bp.route('/admin/users/import', methods=['POST'])
@login_required
@permission_required('manage_users')
def import_users():
    data = request.get_json()
    if not data or ('users' not in data and 'roles' not in data) : # Check if at least users or roles are present
        return jsonify({'error': 'Invalid input. "users" and/or "roles" list required.'}), 400

    users_data = data.get('users', [])
    roles_data = data.get('roles', [])

    if not isinstance(users_data, list) or not isinstance(roles_data, list):
        return jsonify({'error': 'Users and roles data must be lists.'}), 400

    # Process Roles First (Create or Update)
    # This is important so that users can be assigned to newly imported roles.
    created_roles_count = 0
    updated_roles_count = 0
    role_errors = []
    imported_role_map = {} # Maps old ID from import file to new/existing ID in DB

    for role_item in roles_data:
        role_name = role_item.get('name')
        if not role_name:
            role_errors.append({'role_data': role_item, 'error': 'Role name is required.'})
            continue

        role = Role.query.filter(func.lower(Role.name) == func.lower(role_name)).first()
        if role: # Update existing role
            role.description = role_item.get('description', role.description)
            # Be careful with permissions, especially for "Administrator"
            if role.name == "Administrator":
                if role_item.get('permissions') and role_item.get('permissions') != "all_permissions": # "all" in previous code, "all_permissions" in new
                     role_errors.append({'role_data': role_item, 'error': 'Cannot change permissions of Administrator role from "all_permissions".'})
                     continue # Skip this role update
            else:
                 role.permissions = role_item.get('permissions', role.permissions)
            updated_roles_count += 1
        else: # Create new role
            role = Role(
                name=role_name,
                description=role_item.get('description'),
                permissions=role_item.get('permissions')
            )
            db.session.add(role)
            created_roles_count +=1

        try:
            db.session.flush() # Flush to get ID if new
            if 'id' in role_item: # Store mapping if old ID was present
                imported_role_map[role_item['id']] = role.id
        except Exception as e:
            db.session.rollback()
            role_errors.append({'role_data': role_item, 'error': f'DB error processing role: {str(e)}'})
            if role in db.session.new: created_roles_count -=1
            elif role in db.session.dirty: updated_roles_count -=1


    # Process Users (Create or Update)
    created_users_count = 0
    updated_users_count = 0
    user_errors = []

    for user_item in users_data:
        username = user_item.get('username')
        email = user_item.get('email')

        if not username or not email:
            user_errors.append({'user_data': user_item, 'error': 'Username and email are required for each user.'})
            continue

        user = User.query.filter(func.lower(User.username) == func.lower(username)).first()
        original_user_id_from_import = user_item.get('id') # For role mapping

        if user: # Update existing user by username
            # Check for email collision if email is changing
            if user.email.lower() != email.lower():
                if User.query.filter(func.lower(User.email) == func.lower(email), User.id != user.id).first():
                    user_errors.append({'user_data': user_item, 'error': f'Email {email} already exists for another user.'})
                    continue
                user.email = email

            if 'password_hash' in user_item and user_item['password_hash']: # If hash is provided, use it directly
                 user.password_hash = user_item['password_hash']
            elif 'password' in user_item and user_item['password']: # If plaintext password, hash it
                 user.set_password(user_item['password'])

            user.is_admin = user_item.get('is_admin', user.is_admin) # Legacy admin
            user.google_id = user_item.get('google_id', user.google_id)
            user.google_email = user_item.get('google_email', user.google_email)
            updated_users_count +=1
        else: # Create new user
            if User.query.filter(func.lower(User.email) == func.lower(email)).first():
                user_errors.append({'user_data': user_item, 'error': f'Email {email} already exists for another user (cannot create new).'})
                continue

            user = User(username=username, email=email)
            if 'password_hash' in user_item and user_item['password_hash']:
                 user.password_hash = user_item['password_hash']
            elif 'password' in user_item and user_item['password']:
                 user.set_password(user_item['password'])
            else:
                user_errors.append({'user_data': user_item, 'error': 'Password or password_hash required for new user.'})
                continue # Skip this user

            user.is_admin = user_item.get('is_admin', False)
            user.google_id = user_item.get('google_id')
            user.google_email = user_item.get('google_email')
            db.session.add(user)
            created_users_count +=1

        # Assign roles
        if 'role_ids' in user_item and isinstance(user_item['role_ids'], list):
            new_user_roles = []
            for old_role_id in user_item['role_ids']:
                new_role_id = imported_role_map.get(old_role_id) # Try to map old ID to new/existing DB ID
                role_obj = None
                if new_role_id:
                    role_obj = Role.query.get(new_role_id)

                if role_obj:
                    new_user_roles.append(role_obj)
                else: # If role_id from import file wasn't in the imported roles_data or couldn't be mapped
                    user_errors.append({'user_data': user_item, 'error': f'Role ID {old_role_id} referenced by user not found or could not be mapped.'})
            user.roles = new_user_roles

        try:
            db.session.flush() # Flush to resolve user object for audit logging, or catch early errors
        except Exception as e:
            db.session.rollback()
            user_errors.append({'user_data': user_item, 'error': f'DB error processing user: {str(e)}'})
            if user in db.session.new: created_users_count -=1
            elif user in db.session.dirty: updated_users_count -=1

    try:
        db.session.commit()
        add_audit_log(action="IMPORT_USERS_ROLES", details=f"User {current_user.username} imported users and roles. Roles (C:{created_roles_count},U:{updated_roles_count}). Users (C:{created_users_count},U:{updated_users_count}). Errors (R:{len(role_errors)},U:{len(user_errors)})")
        return jsonify({
            'message': 'Import process finished.',
            'roles_created': created_roles_count, 'roles_updated': updated_roles_count, 'role_errors': role_errors,
            'users_created': created_users_count, 'users_updated': updated_users_count, 'user_errors': user_errors
        }), 200 if not role_errors and not user_errors else 207
    except Exception as e_commit:
        db.session.rollback()
        current_app.logger.exception("Error committing imported users/roles:")
        return jsonify({'error': f'Failed to commit imported users/roles due to a server error: {str(e_commit)}'}), 500

@api_users_bp.route('/admin/users/export/csv', methods=['GET'])
@login_required
@permission_required('manage_users')
def export_users_csv():
    try:
        users = User.query.all()

        # Using StringIO to build CSV in memory
        import csv
        import io

        si = io.StringIO()
        cw = csv.writer(si)

        # Header row
        headers = ['id', 'username', 'email', 'is_admin', 'roles']
        cw.writerow(headers)

        for user in users:
            role_names = ",".join(sorted([role.name for role in user.roles]))
            row = [
                user.id,
                user.username,
                user.email,
                str(user.is_admin).lower(), # 'true' or 'false'
                role_names
            ]
            cw.writerow(row)

        output = si.getvalue()
        si.close()

        from flask import make_response
        response = make_response(output)
        response.headers["Content-Disposition"] = "attachment; filename=users_export.csv"
        response.headers["Content-type"] = "text/csv"

        add_audit_log(action="EXPORT_USERS_CSV", details=f"User {current_user.username} exported all users to CSV. Count: {len(users)}.")
        current_app.logger.info(f"User {current_user.username} exported {len(users)} users to CSV.")
        return response

    except Exception as e:
        current_app.logger.exception("Error exporting users to CSV:")
        # Fallback error response if something goes wrong during CSV generation
        return jsonify({'error': f'Failed to export users to CSV due to a server error: {str(e)}'}), 500


@api_users_bp.route('/admin/users/import/csv', methods=['POST'])
@login_required
@permission_required('manage_users')
def import_users_csv():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request.'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected for upload.'}), 400

    if not file.filename.lower().endswith('.csv') and file.mimetype != 'text/csv':
        return jsonify({'error': 'Invalid file type. Please upload a CSV file.'}), 400

    created_count = 0
    updated_count = 0
    errors = []

    try:
        import csv
        import io

        # Read the file content into a string buffer
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_reader = csv.DictReader(stream) # Use DictReader for easy header access

        if not csv_reader.fieldnames:
            return jsonify({'error': 'CSV file is empty or has no headers.'}), 400

        expected_headers = ['username', 'email'] # Password is required for new, optional for existing
        missing_headers = [h for h in expected_headers if h not in csv_reader.fieldnames]
        if missing_headers:
            return jsonify({'error': f'Missing required CSV headers: {", ".join(missing_headers)}'}), 400

        # Optional headers: password, is_admin, role_names

        users_to_process = []
        for row_num, row in enumerate(csv_reader, start=2): # Start from 2 because of header
            users_to_process.append({'data': row, 'row_num': row_num})

        # Note: For simplicity, this implementation processes one user at a time and commits.
        # A more robust bulk operation might add all to session and commit once,
        # but error handling for individual users within a large batch becomes more complex to map back.
        # The existing JSON import also flushes per user/role, then one final commit. We'll follow a similar pattern.

        for item in users_to_process:
            row_data = item['data']
            row_num = item['row_num']

            username = row_data.get('username', '').strip()
            email = row_data.get('email', '').strip()
            password = row_data.get('password') # Keep as is, don't strip for now
            is_admin_str = row_data.get('is_admin', '').strip().lower()
            role_names_str = row_data.get('role_names', '').strip()

            if not username:
                errors.append({'row': row_num, 'error': 'Username is required.'})
                continue
            if not email:
                errors.append({'row': row_num, 'error': 'Email is required.'})
                continue

            if '@' not in email or '.' not in email.split('@')[-1]:
                errors.append({'row': row_num, 'username': username, 'error': 'Invalid email format.'})
                continue

            user = User.query.filter(func.lower(User.username) == func.lower(username)).first()
            if not user: # Try by email if not found by username
                user = User.query.filter(func.lower(User.email) == func.lower(email)).first()

            is_new_user = user is None

            if is_new_user:
                if not password:
                    errors.append({'row': row_num, 'username': username, 'error': 'Password is required for new users.'})
                    continue
                # Check for username/email uniqueness before creating
                if User.query.filter(func.lower(User.username) == func.lower(username)).first():
                     errors.append({'row': row_num, 'username': username, 'error': f"Username '{username}' already exists."})
                     continue
                if User.query.filter(func.lower(User.email) == func.lower(email)).first():
                    errors.append({'row': row_num, 'username': username, 'error': f"Email '{email}' already registered."})
                    continue

                user = User(username=username, email=email)
                user.set_password(password)
                db.session.add(user)
            else: # Existing user
                # Email change validation
                if user.email.lower() != email.lower():
                    if User.query.filter(User.id != user.id).filter(func.lower(User.email) == func.lower(email)).first():
                        errors.append({'row': row_num, 'username': username, 'error': f"Email '{email}' already registered by another user."})
                        continue
                    user.email = email
                # Password update
                if password: # Only update password if provided
                    user.set_password(password)

            # Set is_admin
            if is_admin_str: # Only process if is_admin column is present and has a value
                if is_admin_str == 'true':
                    # Safeguard for demoting last admin
                    if user.is_admin and not True: # if current user is admin and new value is False
                         if user.id == current_user.id and User.query.filter_by(is_admin=True).count() == 1:
                            errors.append({'row': row_num, 'username': username, 'error': 'Cannot remove your own admin status as the sole admin.'})
                            # db.session.rollback() # Rollback this specific user change - REMOVED
                            continue
                    user.is_admin = True
                elif is_admin_str == 'false':
                    user.is_admin = False
                else:
                    errors.append({'row': row_num, 'username': username, 'error': f"Invalid value for is_admin: '{is_admin_str}'. Use 'true' or 'false'."})
                    # Potentially skip this user or just this field update. For now, let's skip user.
                    # db.session.rollback() - REMOVED
                    continue

            # Role handling
            if role_names_str: # If role_names column is present and not empty
                new_user_roles = []
                role_names_list = [name.strip() for name in role_names_str.split(',') if name.strip()]
                found_all_roles = True
                for role_name in role_names_list:
                    role_obj = Role.query.filter(func.lower(Role.name) == func.lower(role_name)).first()
                    if not role_obj:
                        errors.append({'row': row_num, 'username': username, 'error': f"Role '{role_name}' not found."})
                        found_all_roles = False
                        break
                    new_user_roles.append(role_obj)

                if not found_all_roles:
                    # db.session.rollback() # Rollback changes for this user if a role was not found - REMOVED
                    continue

                # Safeguard for removing last admin role
                admin_role_db = Role.query.filter_by(name="Administrator").first()
                if admin_role_db:
                    is_removing_admin_role = admin_role_db in user.roles and admin_role_db not in new_user_roles
                    if is_removing_admin_role and user.id == current_user.id:
                        users_with_admin_role = User.query.filter(User.roles.any(id=admin_role_db.id)).count()
                        if users_with_admin_role == 1:
                            errors.append({'row': row_num, 'username': username, 'error': 'Cannot remove your own "Administrator" role as the sole holder.'})
                            # db.session.rollback() - REMOVED
                            continue
                user.roles = new_user_roles
            elif 'role_names' in csv_reader.fieldnames: # If 'role_names' header exists but string is empty, clear roles
                 user.roles = []


            try:
                db.session.flush() # Use flush to catch potential DB errors before final commit per user
                if is_new_user:
                    created_count += 1
                else:
                    updated_count += 1
            except Exception as e_flush:
                db.session.rollback()
                errors.append({'row': row_num, 'username': username, 'error': f'DB error processing user: {str(e_flush)}'})
                if is_new_user and user in db.session.new: db.session.expunge(user) # remove from session if new and failed

        # Final commit for all processed users
        db.session.commit()

        action_details = f"CSV Import by {current_user.username}. Created: {created_count}, Updated: {updated_count}, Errors: {len(errors)}"
        add_audit_log(action="IMPORT_USERS_CSV", details=action_details)
        current_app.logger.info(action_details)

        status_code = 200 if not errors else 207 # OK or Multi-Status
        return jsonify({
            'message': 'CSV import process finished.',
            'users_created': created_count,
            'users_updated': updated_count,
            'errors': errors
        }), status_code

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error during CSV user import by {current_user.username}:")
        add_audit_log(action="IMPORT_USERS_CSV_FAILED", details=f"CSV Import by {current_user.username} failed. Error: {str(e)}")
        return jsonify({'error': f'Failed to import users from CSV due to a server error: {str(e)}'}), 500


@api_users_bp.route('/admin/users/bulk_add_pattern', methods=['POST'])
@login_required
@permission_required('manage_users')
def bulk_add_users_pattern():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid input. JSON data expected.'}), 400

    username_prefix = (data.get('username_prefix') or '').strip()
    username_suffix = (data.get('username_suffix') or '').strip() # Optional custom suffix for username
    start_number = data.get('start_number')
    count = data.get('count')
    email_domain = (data.get('email_domain') or '').strip() # e.g., example.com
    email_pattern = (data.get('email_pattern') or '').strip() # e.g., {username}@example.com
    default_password = data.get('default_password')
    is_admin = data.get('is_admin', False)
    role_ids = data.get('role_ids', [])

    # Basic Validations
    if not username_prefix:
        return jsonify({'error': 'Username prefix is required.'}), 400
    if not isinstance(start_number, int) or start_number < 0:
        return jsonify({'error': 'Start number must be a non-negative integer.'}), 400
    if not isinstance(count, int) or not (1 <= count <= 100): # Max 100 users at a time
        return jsonify({'error': 'Count must be an integer between 1 and 100.'}), 400
    if not default_password:
        return jsonify({'error': 'Default password is required.'}), 400
    if not email_domain and not email_pattern:
        return jsonify({'error': 'Either Email Domain or Email Pattern is required.'}), 400
    if email_domain and email_pattern: # Only one should be provided
        return jsonify({'error': 'Provide either Email Domain or Email Pattern, not both.'}), 400
    if email_pattern and "{username}" not in email_pattern:
        return jsonify({'error': 'Email Pattern must contain "{username}" placeholder.'}), 400


    resolved_roles = []
    if role_ids:
        if not isinstance(role_ids, list):
            return jsonify({'error': 'role_ids must be a list of integers.'}), 400
        for r_id in role_ids:
            if not isinstance(r_id, int):
                return jsonify({'error': f'Invalid role ID type: {r_id}. Must be integer.'}), 400
            role = Role.query.get(r_id)
            if not role:
                return jsonify({'error': f'Role with ID {r_id} not found.'}), 400
            resolved_roles.append(role)

    added_count = 0
    errors_warnings = []
    users_to_add_in_db = []

    for i in range(count):
        current_num = start_number + i
        # Pad number if prefix suggests (e.g. user001 vs user1 - for now, simple concatenation)
        # More complex padding (e.g. to 3 digits) could be added if username_prefix ends with digits itself
        # For simplicity, using the number as is.
        generated_username = f"{username_prefix}{current_num}{username_suffix}"

        generated_email = ""
        if email_domain:
            generated_email = f"{generated_username}@{email_domain}"
        elif email_pattern:
            generated_email = email_pattern.replace("{username}", generated_username)

        # Validate generated email format (basic check)
        if '@' not in generated_email or '.' not in generated_email.split('@')[-1]:
            errors_warnings.append({'username_attempt': generated_username, 'email_attempt': generated_email, 'error': 'Generated email is invalid.'})
            continue

        # Check for conflicts
        if User.query.filter(func.lower(User.username) == func.lower(generated_username)).first():
            errors_warnings.append({'username': generated_username, 'error': 'Username already exists.'})
            continue
        if User.query.filter(func.lower(User.email) == func.lower(generated_email)).first():
            errors_warnings.append({'username': generated_username, 'email': generated_email, 'error': 'Email already registered.'})
            continue

        new_user = User(username=generated_username, email=generated_email, is_admin=is_admin)
        new_user.set_password(default_password)
        if resolved_roles:
            new_user.roles = resolved_roles

        users_to_add_in_db.append(new_user)

    if users_to_add_in_db:
        try:
            db.session.add_all(users_to_add_in_db)
            db.session.commit()
            added_count = len(users_to_add_in_db)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error committing pattern bulk add users: {str(e)}")
            # Add errors for all users that were supposed to be added in this batch
            for user_obj in users_to_add_in_db:
                 errors_warnings.append({'username': user_obj.username, 'email': user_obj.email, 'error': f'Database error during final commit: {str(e)}'})
            # Return immediately if the commit fails for the batch
            add_audit_log(action="BULK_ADD_PATTERN_FAILED", details=f"Pattern bulk add by {current_user.username} failed during commit. Attempted: {len(users_to_add_in_db)}, Errors: {len(errors_warnings)}")
            return jsonify({
                'message': 'Bulk user add with pattern failed during commit.',
                'users_added': 0,
                'errors_warnings': errors_warnings
            }), 500

    action_details = f"Pattern Bulk Add by {current_user.username}. Target count: {count}, Added: {added_count}, Skipped/Errors: {len(errors_warnings)}"
    add_audit_log(action="BULK_ADD_PATTERN", details=action_details)
    current_app.logger.info(action_details)

    status_code = 201 if added_count > 0 and not errors_warnings else 207 if errors_warnings else 200
    return jsonify({
        'message': 'Bulk user add with pattern operation completed.',
        'users_added': added_count,
        'errors_warnings': errors_warnings # Use 'errors_warnings' to indicate some might be skips not hard errors
    }), status_code


@api_users_bp.route('/admin/users/bulk_add', methods=['POST'])
@login_required
@permission_required('manage_users')
def bulk_add_users():
    data = request.get_json()
    if not data or not isinstance(data, list):
        return jsonify({'error': 'Invalid input. JSON list of users expected.'}), 400

    added_count = 0
    errors = []
    users_to_add = []

    for user_data in data:
        username = user_data.get('username')
        email = user_data.get('email')
        password = user_data.get('password')
        is_admin = user_data.get('is_admin', False)
        role_ids = user_data.get('role_ids', [])

        if not username or not username.strip():
            errors.append({'user_data': user_data, 'error': 'Username is required.'})
            continue
        if not email or not email.strip():
            errors.append({'user_data': user_data, 'error': 'Email is required.'})
            continue
        if not password:
            errors.append({'user_data': user_data, 'error': 'Password is required.'})
            continue

        username = username.strip()
        email = email.strip()

        if '@' not in email or '.' not in email.split('@')[-1]:
            errors.append({'user_data': user_data, 'error': 'Invalid email format.'})
            continue

        if User.query.filter(func.lower(User.username) == func.lower(username)).first():
            errors.append({'user_data': user_data, 'error': f"Username '{username}' already exists."})
            continue
        if User.query.filter(func.lower(User.email) == func.lower(email)).first():
            errors.append({'user_data': user_data, 'error': f"Email '{email}' already registered."})
            continue

        if not isinstance(role_ids, list):
            errors.append({'user_data': user_data, 'error': 'role_ids must be a list of integers.'})
            continue

        new_user = User(username=username, email=email, is_admin=is_admin)
        new_user.set_password(password)

        resolved_roles = []
        valid_roles = True
        for r_id in role_ids:
            if not isinstance(r_id, int):
                errors.append({'user_data': user_data, 'error': f'Invalid role ID type: {r_id}. Must be integer.'})
                valid_roles = False
                break
            role = Role.query.get(r_id)
            if not role:
                errors.append({'user_data': user_data, 'error': f'Role with ID {r_id} not found.'})
                valid_roles = False
                break
            resolved_roles.append(role)

        if not valid_roles:
            continue

        new_user.roles = resolved_roles
        users_to_add.append(new_user)

    if users_to_add:
        try:
            db.session.add_all(users_to_add)
            db.session.commit()
            added_count = len(users_to_add)
            add_audit_log(action="BULK_ADD_USERS_SUCCESS", details=f"{added_count} users added by {current_user.username}. Errors: {len(errors)}")
        except Exception as e:
            db.session.rollback()
            # All users in this batch failed to commit, so add errors for them
            for user_obj in users_to_add:
                 errors.append({'user_data': {'username': user_obj.username, 'email': user_obj.email}, 'error': f'Database error during commit: {str(e)}'})
            users_to_add.clear() # Clear the list as they were not added
            add_audit_log(action="BULK_ADD_USERS_FAILED", details=f"Failed to add users in bulk by {current_user.username}. Error: {str(e)}. Initial errors: {len(errors) - len(users_to_add)}")
            # Return immediately if the commit fails for the batch
            return jsonify({
                'message': 'Bulk user add operation failed during commit.',
                'users_added': 0,
                'errors': errors
            }), 500

    status_code = 201 if added_count > 0 and not errors else 207 if errors else 200
    return jsonify({
        'message': 'Bulk user add operation completed.',
        'users_added': added_count,
        'errors': errors
    }), status_code


@api_users_bp.route('/admin/users/bulk_edit', methods=['PUT'])
@login_required
@permission_required('manage_users')
def bulk_edit_users():
    data = request.get_json()
    if not data or not isinstance(data, list):
        return jsonify({'error': 'Invalid input. JSON list of user updates expected.'}), 400

    updated_count = 0
    errors = []
    users_to_update_in_session = [] # Keep track of users modified in this batch for potential rollback

    for user_data in data:
        user_id = user_data.get('id')
        if not user_id or not isinstance(user_id, int):
            errors.append({'user_data': user_data, 'error': 'User ID is required and must be an integer.'})
            continue

        user_to_update = User.query.get(user_id)
        if not user_to_update:
            errors.append({'id': user_id, 'error': 'User not found.'})
            continue

        users_to_update_in_session.append(user_to_update) # Add to list for session management

        # Username validation
        if 'username' in user_data and user_data['username'] and user_data['username'].strip() and \
           user_to_update.username != user_data['username'].strip():
            new_username = user_data['username'].strip()
            if User.query.filter(User.id != user_id).filter(func.lower(User.username) == func.lower(new_username)).first():
                errors.append({'id': user_id, 'error': f"Username '{new_username}' already exists."})
                continue
            user_to_update.username = new_username

        # Email validation
        if 'email' in user_data and user_data['email'] and user_data['email'].strip() and \
           user_to_update.email != user_data['email'].strip():
            new_email = user_data['email'].strip()
            if '@' not in new_email or '.' not in new_email.split('@')[-1]:
                errors.append({'id': user_id, 'error': 'Invalid email format.'})
                continue
            if User.query.filter(User.id != user_id).filter(func.lower(User.email) == func.lower(new_email)).first():
                errors.append({'id': user_id, 'error': f"Email '{new_email}' already registered."})
                continue
            user_to_update.email = new_email

        # Password update
        if 'password' in user_data and user_data['password']:
            user_to_update.set_password(user_data['password'])

        # is_admin update (with safeguards)
        if 'is_admin' in user_data and isinstance(user_data['is_admin'], bool):
            if user_to_update.id == current_user.id and not user_data['is_admin']:
                num_admins_flag = User.query.filter_by(is_admin=True).count()
                if num_admins_flag == 1:
                    errors.append({'id': user_id, 'error': 'Cannot remove your own admin status (is_admin flag) as the sole admin.'})
                    continue
            user_to_update.is_admin = user_data['is_admin']

        # Role updates (with safeguards)
        if 'role_ids' in user_data:
            role_ids = user_data.get('role_ids', [])
            if not isinstance(role_ids, list):
                errors.append({'id': user_id, 'error': 'role_ids must be a list of integers.'})
                continue

            new_roles = []
            valid_roles = True
            for r_id in role_ids:
                if not isinstance(r_id, int):
                    errors.append({'id': user_id, 'error': f'Invalid role ID type: {r_id}. Must be integer.'})
                    valid_roles = False
                    break
                role = Role.query.get(r_id)
                if not role:
                    errors.append({'id': user_id, 'error': f'Role with ID {r_id} not found.'})
                    valid_roles = False
                    break
                new_roles.append(role)

            if not valid_roles:
                continue

            admin_role = Role.query.filter_by(name="Administrator").first()
            if admin_role:
                is_removing_admin_role_from_this_user = admin_role not in new_roles and admin_role in user_to_update.roles
                if is_removing_admin_role_from_this_user and user_to_update.id == current_user.id:
                    users_with_admin_role = User.query.filter(User.roles.any(id=admin_role.id)).all()
                    if len(users_with_admin_role) == 1 and users_with_admin_role[0].id == user_to_update.id:
                        errors.append({'id': user_id, 'error': 'Cannot remove your own "Administrator" role as the sole holder of this role.'})
                        continue
            user_to_update.roles = new_roles

        # If no errors for this user so far, it's a successful update for counting purposes
        # Note: errors list might contain errors for *other* users from previous iterations.
        # We check if the current user_id is in any error dict.
        if not any(err.get('id') == user_id for err in errors):
            updated_count += 1
            # db.session.add(user_to_update) # Not strictly necessary if object is already in session and modified

    if updated_count > 0 : # Only commit if there were successful updates
        try:
            db.session.commit()
            add_audit_log(action="BULK_EDIT_USERS_SUCCESS", details=f"{updated_count} users updated by {current_user.username}. Errors: {len(errors)}")
        except Exception as e:
            db.session.rollback()
            # If commit fails, it affects all users attempted in this batch.
            # We can't easily tell which specific user caused the commit failure without more granular checks.
            # Add a general error message.
            # For simplicity, we don't add individual errors for each user that was part of the failed batch here,
            # as they might have passed individual validations.
            current_app.logger.error(f"Bulk edit commit failed: {str(e)}")
            add_audit_log(action="BULK_EDIT_USERS_FAILED", details=f"Failed to update users in bulk by {current_user.username} during commit. Error: {str(e)}. Attempted: {updated_count}, Initial errors: {len(errors)}")
            return jsonify({
                'message': 'Bulk user edit operation failed during commit.',
                'users_updated': 0, # No users were truly updated if commit failed
                'errors': errors + [{'id': 'general', 'error': f'Database error during commit: {str(e)}'}]
            }), 500

    status_code = 200 if not errors else 207
    return jsonify({
        'message': 'Bulk user edit operation completed.',
        'users_updated': updated_count,
        'errors': errors
    }), status_code
