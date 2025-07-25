from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from models import db, MaintenanceSchedule
from auth import permission_required
from datetime import time, date

admin_api_maintenance_bp = Blueprint('admin_api_maintenance', __name__, url_prefix='/admin/api/maintenance')

@admin_api_maintenance_bp.route('/schedules', methods=['POST'])
@login_required
@permission_required('manage_maintenance')
def create_maintenance_schedule():
    data = request.get_json()

    # Basic validation
    if not data or not data.get('name') or not data.get('schedule_type'):
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        day_of_week = data.get('day_of_week')
        if isinstance(day_of_week, list):
            day_of_week = ','.join(day_of_week)
        day_of_month = data.get('day_of_month')
        if isinstance(day_of_month, list):
            day_of_month = ','.join(day_of_month)
        start_date = date.fromisoformat(data['start_date']) if data.get('start_date') else None
        end_date = date.fromisoformat(data['end_date']) if data.get('end_date') else None

        is_availability = data.get('is_availability')
        if isinstance(is_availability, str):
            is_availability = is_availability.lower() == 'true'

        floor_ids = data.get('floor_ids')
        if isinstance(floor_ids, list):
            floor_ids = ','.join(floor_ids)

        new_schedule = MaintenanceSchedule(
            name=data['name'],
            schedule_type=data['schedule_type'],
            day_of_week=day_of_week,
            day_of_month=day_of_month,
            start_date=start_date,
            end_date=end_date,
            is_availability=is_availability,
            resource_selection_type=data['resource_selection_type'],
            resource_ids=data.get('resource_ids'),
            building_id=data.get('building_id'),
            floor_ids=floor_ids
        )
        db.session.add(new_schedule)
        db.session.commit()
        return jsonify(id=new_schedule.id), 201
    except Exception as e:
        current_app.logger.error(f"Error creating maintenance schedule: {e}")
        db.session.rollback()
        return jsonify(error=str(e)), 500

@admin_api_maintenance_bp.route('/schedules', methods=['GET'])
@login_required
@permission_required('manage_maintenance')
def get_maintenance_schedules():
    try:
        schedules = MaintenanceSchedule.query.all()
        return jsonify([{
            'id': s.id,
            'name': s.name,
            'schedule_type': s.schedule_type,
            'day_of_week': s.day_of_week,
            'day_of_month': s.day_of_month,
            'start_date': s.start_date.isoformat() if s.start_date else None,
            'end_date': s.end_date.isoformat() if s.end_date else None,
            'is_availability': s.is_availability,
            'resource_selection_type': s.resource_selection_type,
            'resource_ids': s.resource_ids,
            'building_id': s.building_id,
            'floor_ids': s.floor_ids
        } for s in schedules])
    except Exception as e:
        current_app.logger.error(f"Error getting maintenance schedules: {e}")
        return jsonify(error=str(e)), 500

@admin_api_maintenance_bp.route('/schedules/<int:schedule_id>', methods=['PUT'])
@login_required
@permission_required('manage_maintenance')
def update_maintenance_schedule(schedule_id):
    schedule = MaintenanceSchedule.query.get_or_404(schedule_id)
    data = request.get_json()

    try:
        schedule.name = data.get('name', schedule.name)
        schedule.schedule_type = data.get('schedule_type', schedule.schedule_type)
        day_of_week = data.get('day_of_week')
        if isinstance(day_of_week, list):
            day_of_week = ','.join(day_of_week)
        schedule.day_of_week = day_of_week
        day_of_month = data.get('day_of_month')
        if isinstance(day_of_month, list):
            day_of_month = ','.join(day_of_month)
        schedule.day_of_month = day_of_month
        schedule.start_date = date.fromisoformat(data['start_date']) if data.get('start_date') else None
        schedule.end_date = date.fromisoformat(data['end_date']) if data.get('end_date') else None
        schedule.is_availability = data.get('is_availability', schedule.is_availability)
        schedule.resource_selection_type = data.get('resource_selection_type', schedule.resource_selection_type)
        schedule.resource_ids = data.get('resource_ids', schedule.resource_ids)
        schedule.building_id = data.get('building_id', schedule.building_id)
        floor_ids = data.get('floor_ids')
        if isinstance(floor_ids, list):
            floor_ids = ','.join(floor_ids)
        schedule.floor_ids = floor_ids

        db.session.commit()
        return jsonify({'message': 'Schedule updated successfully'})
    except Exception as e:
        current_app.logger.error(f"Error updating maintenance schedule {schedule_id}: {e}")
        db.session.rollback()
        return jsonify(error=str(e)), 500

@admin_api_maintenance_bp.route('/schedules/<int:schedule_id>', methods=['DELETE'])
@login_required
@permission_required('manage_maintenance')
def delete_maintenance_schedule(schedule_id):
    schedule = MaintenanceSchedule.query.get_or_404(schedule_id)
    try:
        db.session.delete(schedule)
        db.session.commit()
        return jsonify({'message': 'Schedule deleted successfully'})
    except Exception as e:
        current_app.logger.error(f"Error deleting maintenance schedule {schedule_id}: {e}")
        db.session.rollback()
        return jsonify(error=str(e)), 500
