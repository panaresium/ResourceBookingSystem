from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, exc as sqlalchemy_exc # Added sqlalchemy_exc for database errors

# Assuming these paths are correct relative to how the app is structured.
from auth import permission_required
from extensions import db
from models import Role, User, user_roles_table # User might be needed for audit logging or future role assignments
from utils import add_audit_log

api_roles_bp = Blueprint('api_roles', __name__, url_prefix='/api/admin/roles')

@api_roles_bp.route('', methods=['GET']) # Path becomes '' as prefix is /api/admin/roles
@login_required
@permission_required('manage_users') # Assuming 'manage_users' or a specific 'manage_roles' permission
def get_roles():
    """Gets all roles with user counts."""
    try:
        # Query to count users per role
        # Subquery to count users for each role
        users_count_subquery = db.session.query(
            user_roles_table.c.role_id,
            func.count(user_roles_table.c.user_id).label('user_count')
        ).group_by(user_roles_table.c.role_id).subquery()

        # Main query to get roles and join with user counts
        roles_with_counts = db.session.query(
            Role, users_count_subquery.c.user_count
        ).outerjoin(
            users_count_subquery, Role.id == users_count_subquery.c.role_id
        ).order_by(Role.name).all()

        roles_list = []
        for role, user_count in roles_with_counts:
            roles_list.append({
                'id': role.id,
                'name': role.name,
                'description': role.description,
                'permissions': role.permissions.split(',') if role.permissions else [],
                'user_count': user_count or 0
            })
        current_app.logger.info(f"User {current_user.username} fetched all roles.")
        return jsonify(roles_list), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching roles by {current_user.username}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to fetch roles due to a server error.'}), 500

@api_roles_bp.route('', methods=['POST']) # Path becomes ''
@login_required
@permission_required('manage_users')
def create_role():
    """Creates a new role."""
    data = request.get_json()
    if not data or not data.get('name'):
        current_app.logger.warning(f"User {current_user.username} attempt to create role with missing name.")
        return jsonify({'error': 'Role name is required.'}), 400

    name = data['name'].strip()
    description = data.get('description', '').strip()
    permissions_list = data.get('permissions', [])
    if not isinstance(permissions_list, list):
        current_app.logger.warning(f"User {current_user.username} attempt to create role with invalid permissions format for role {name}.")
        return jsonify({'error': 'Permissions must be a list of strings.'}), 400

    permissions_str = ','.join(sorted(list(set(p.strip() for p in permissions_list if p.strip()))))


    if Role.query.filter_by(name=name).first():
        current_app.logger.warning(f"User {current_user.username} attempt to create role with existing name: {name}.")
        return jsonify({'error': f"Role with name '{name}' already exists."}), 409 # 409 Conflict

    try:
        new_role = Role(name=name, description=description, permissions=permissions_str)
        db.session.add(new_role)
        db.session.commit()
        add_audit_log(action="CREATE_ROLE", details=f"Role '{name}' created by {current_user.username}.", user_id=current_user.id)
        current_app.logger.info(f"Role '{name}' created successfully by {current_user.username}.")
        # Prepare role data for response, similar to get_roles
        role_data = {
            'id': new_role.id,
            'name': new_role.name,
            'description': new_role.description,
            'permissions': new_role.permissions.split(',') if new_role.permissions else [],
            'user_count': 0 # New role has no users
        }
        return jsonify({'message': 'Role created successfully.', 'role': role_data}), 201
    except sqlalchemy_exc.IntegrityError as e: # Catch DB errors like unique constraint
        db.session.rollback()
        current_app.logger.error(f"Database integrity error creating role '{name}' by {current_user.username}: {e}", exc_info=True)
        # Check if it's specifically a unique constraint violation for 'name'
        if 'UNIQUE constraint failed: role.name' in str(e).lower(): # Vague check, specific DBs might differ
             return jsonify({'error': f"Role with name '{name}' already exists (database integrity)."}), 409
        return jsonify({'error': 'Database error during role creation.'}), 500
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating role '{name}' by {current_user.username}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to create role due to a server error.'}), 500

@api_roles_bp.route('/<int:role_id>', methods=['PUT']) # Path becomes '/<int:role_id>'
@login_required
@permission_required('manage_users')
def update_role(role_id):
    """Updates an existing role."""
    role = db.session.get(Role, role_id)
    if not role:
        current_app.logger.warning(f"User {current_user.username} attempt to update non-existent role ID: {role_id}.")
        return jsonify({'error': 'Role not found.'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided for update.'}), 400

    original_name = role.name # For audit logging

    if 'name' in data:
        new_name = data['name'].strip()
        if not new_name:
            return jsonify({'error': 'Role name cannot be empty.'}), 400
        # Check if new name conflicts with another existing role
        existing_role_with_new_name = Role.query.filter(Role.name == new_name, Role.id != role_id).first()
        if existing_role_with_new_name:
            current_app.logger.warning(f"User {current_user.username} attempt to update role ID {role_id} to existing name: {new_name}.")
            return jsonify({'error': f"Another role with name '{new_name}' already exists."}), 409
        role.name = new_name

    if 'description' in data:
        role.description = data['description'].strip()

    if 'permissions' in data:
        permissions_list = data.get('permissions', [])
        if not isinstance(permissions_list, list):
            return jsonify({'error': 'Permissions must be a list of strings.'}), 400
        role.permissions = ','.join(sorted(list(set(p.strip() for p in permissions_list if p.strip()))))

    try:
        db.session.commit()
        add_audit_log(action="UPDATE_ROLE", details=f"Role '{original_name}' (ID: {role_id}) updated by {current_user.username}. New data: {data}", user_id=current_user.id)
        current_app.logger.info(f"Role '{role.name}' (ID: {role_id}) updated successfully by {current_user.username}.")
        # Prepare role data for response, similar to get_roles
        # Need to fetch user_count for this specific role
        user_count_result = db.session.query(func.count(User.roles.property.secondary.c.user_id)).filter(User.roles.property.secondary.c.role_id == role.id).scalar()

        role_data = {
            'id': role.id,
            'name': role.name,
            'description': role.description,
            'permissions': role.permissions.split(',') if role.permissions else [],
            'user_count': user_count_result or 0
        }
        return jsonify({'message': 'Role updated successfully.', 'role': role_data}), 200
    except sqlalchemy_exc.IntegrityError as e: # Catch DB errors like unique constraint
        db.session.rollback()
        current_app.logger.error(f"Database integrity error updating role ID {role_id} by {current_user.username}: {e}", exc_info=True)
        if 'UNIQUE constraint failed: role.name' in str(e).lower():
             return jsonify({'error': f"Another role with name '{data.get('name', role.name)}' already exists (database integrity)."}), 409
        return jsonify({'error': 'Database error during role update.'}), 500
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating role ID {role_id} by {current_user.username}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to update role due to a server error.'}), 500

@api_roles_bp.route('/<int:role_id>', methods=['DELETE']) # Path becomes '/<int:role_id>'
@login_required
@permission_required('manage_users')
def delete_role(role_id):
    """Deletes a role."""
    role = db.session.get(Role, role_id)
    if not role:
        current_app.logger.warning(f"User {current_user.username} attempt to delete non-existent role ID: {role_id}.")
        return jsonify({'error': 'Role not found.'}), 404

    # Prevent deletion of role if it's assigned to any users
    if role.users.count() > 0: # Accessing the backref 'users' from User model
        current_app.logger.warning(f"User {current_user.username} attempt to delete role '{role.name}' (ID: {role_id}) which is assigned to users.")
        return jsonify({'error': f"Cannot delete role '{role.name}' as it is currently assigned to {role.users.count()} user(s)."}), 400 # Bad Request or Conflict 409

    # Prevent deletion of a potential "Super Admin" or critical system role by name (example)
    if role.name.lower() == 'super admin': # Example of a protected role
        current_app.logger.warning(f"User {current_user.username} attempt to delete protected role: {role.name}.")
        return jsonify({'error': 'Cannot delete the Super Admin role.'}), 403 # Forbidden

    try:
        role_name_for_audit = role.name # Capture before deletion
        db.session.delete(role)
        db.session.commit()
        add_audit_log(action="DELETE_ROLE", details=f"Role '{role_name_for_audit}' (ID: {role_id}) deleted by {current_user.username}.", user_id=current_user.id)
        current_app.logger.info(f"Role '{role_name_for_audit}' (ID: {role_id}) deleted successfully by {current_user.username}.")
        return jsonify({'message': f"Role '{role_name_for_audit}' deleted successfully."}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting role ID {role_id} by {current_user.username}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to delete role due to a server error.'}), 500

def init_api_roles_routes(app):
    app.register_blueprint(api_roles_bp)
