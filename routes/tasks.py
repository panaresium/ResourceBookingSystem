from flask import Blueprint, jsonify, request, current_app
from scheduler_tasks import (
    auto_checkout_overdue_bookings,
    cancel_unchecked_bookings,
    send_checkin_reminders,
    auto_release_unclaimed_bookings,
    apply_scheduled_resource_status_changes
)
import os

tasks_bp = Blueprint('tasks', __name__)

def verify_task_secret():
    """
    Verifies that the request contains the correct X-Task-Secret header.
    Returns True if valid, False otherwise.
    """
    expected_secret = os.environ.get('TASK_SECRET')
    if not expected_secret:
        current_app.logger.warning("TASK_SECRET environment variable not set. Rejecting task request.")
        return False

    auth_header = request.headers.get('X-Task-Secret')
    if not auth_header or auth_header != expected_secret:
        current_app.logger.warning("Invalid or missing X-Task-Secret header.")
        return False

    return True

@tasks_bp.route('/tasks/auto_checkout', methods=['POST'])
def trigger_auto_checkout():
    if not verify_task_secret():
        return jsonify({'error': 'Unauthorized'}), 401

    current_app.logger.info("Triggering auto_checkout_overdue_bookings via webhook.")
    try:
        auto_checkout_overdue_bookings(current_app)
        return jsonify({'status': 'success', 'message': 'Auto checkout task completed.'}), 200
    except Exception as e:
        current_app.logger.error(f"Error in auto_checkout task: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@tasks_bp.route('/tasks/auto_cancel', methods=['POST'])
def trigger_auto_cancel():
    if not verify_task_secret():
        return jsonify({'error': 'Unauthorized'}), 401

    current_app.logger.info("Triggering cancel_unchecked_bookings via webhook.")
    try:
        cancel_unchecked_bookings(current_app)
        return jsonify({'status': 'success', 'message': 'Auto cancel task completed.'}), 200
    except Exception as e:
        current_app.logger.error(f"Error in auto_cancel task: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@tasks_bp.route('/tasks/checkin_reminders', methods=['POST'])
def trigger_checkin_reminders():
    if not verify_task_secret():
        return jsonify({'error': 'Unauthorized'}), 401

    current_app.logger.info("Triggering send_checkin_reminders via webhook.")
    try:
        send_checkin_reminders(current_app)
        return jsonify({'status': 'success', 'message': 'Check-in reminders task completed.'}), 200
    except Exception as e:
        current_app.logger.error(f"Error in checkin_reminders task: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@tasks_bp.route('/tasks/auto_release', methods=['POST'])
def trigger_auto_release():
    if not verify_task_secret():
        return jsonify({'error': 'Unauthorized'}), 401

    current_app.logger.info("Triggering auto_release_unclaimed_bookings via webhook.")
    try:
        auto_release_unclaimed_bookings(current_app)
        return jsonify({'status': 'success', 'message': 'Auto release task completed.'}), 200
    except Exception as e:
        current_app.logger.error(f"Error in auto_release task: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@tasks_bp.route('/tasks/apply_resource_status', methods=['POST'])
def trigger_apply_resource_status():
    if not verify_task_secret():
        return jsonify({'error': 'Unauthorized'}), 401

    current_app.logger.info("Triggering apply_scheduled_resource_status_changes via webhook.")
    try:
        apply_scheduled_resource_status_changes(current_app)
        return jsonify({'status': 'success', 'message': 'Resource status update task completed.'}), 200
    except Exception as e:
        current_app.logger.error(f"Error in apply_resource_status task: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
