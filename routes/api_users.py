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

    if not email and not password:
        return jsonify({'error': 'No changes submitted.'}), 400

    if email:
        if '@' not in email or '.' not in email.split('@')[-1]:
            return jsonify({'error': 'Invalid email format.'}), 400
        existing = User.query.filter(User.id != current_user.id).filter_by(email=email.strip()).first()
        if existing:
            return jsonify({'error': f"Email '{email.strip()}' already registered."}), 409
        current_user.email = email.strip()

    if password:
        current_user.set_password(password)

    try:
        db.session.commit()
        user_data = {'id': current_user.id, 'username': current_user.username, 'email': current_user.email}
        current_app.logger.info(f"User {current_user.username} updated their profile.")
        add_audit_log(action="UPDATE_PROFILE", details=f"User {current_user.username} updated their profile. Email: {email}, Password changed: {'yes' if password else 'no'}", user_id=current_user.id)
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

@api_users_bp.route('/api/admin/users/import', methods=['POST'])
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
