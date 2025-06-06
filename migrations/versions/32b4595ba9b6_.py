"""empty message

Revision ID: 32b4595ba9b6
Revises:
Create Date: 2025-06-03 07:53:30.528348

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '32b4595ba9b6'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()

    if 'booking_settings' not in tables:
        op.create_table('booking_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('allow_past_bookings', sa.Boolean(), nullable=True),
        sa.Column('max_booking_days_in_future', sa.Integer(), nullable=True),
        sa.Column('allow_multiple_resources_same_time', sa.Boolean(), nullable=True),
        sa.Column('max_bookings_per_user', sa.Integer(), nullable=True),
        sa.Column('enable_check_in_out', sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )

    if 'floor_map' not in tables:
        op.create_table('floor_map',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('image_filename', sa.String(length=255), nullable=False),
        sa.Column('location', sa.String(length=100), nullable=True),
        sa.Column('floor', sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('image_filename')
        )

    if 'role' not in tables:
        op.create_table('role',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('permissions', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
        )

    if 'user' not in tables:
        op.create_table('user',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=80), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('password_hash', sa.String(length=256), nullable=False),
        sa.Column('is_admin', sa.Boolean(), nullable=False),
        sa.Column('google_id', sa.String(length=200), nullable=True),
        sa.Column('google_email', sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('google_id'),
        sa.UniqueConstraint('username')
        )

    if 'audit_log' not in tables:
        op.create_table('audit_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('username', sa.String(length=80), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
        )

    if 'resource' not in tables:
        op.create_table('resource',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('capacity', sa.Integer(), nullable=True),
        sa.Column('equipment', sa.String(length=200), nullable=True),
        sa.Column('tags', sa.String(length=200), nullable=True),
        sa.Column('booking_restriction', sa.String(length=50), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('allowed_user_ids', sa.Text(), nullable=True),
        sa.Column('image_filename', sa.String(length=255), nullable=True),
        sa.Column('is_under_maintenance', sa.Boolean(), nullable=False),
        sa.Column('maintenance_until', sa.DateTime(), nullable=True),
        sa.Column('max_recurrence_count', sa.Integer(), nullable=True),
        sa.Column('scheduled_status', sa.String(length=50), nullable=True),
        sa.Column('scheduled_status_at', sa.DateTime(), nullable=True),
        sa.Column('floor_map_id', sa.Integer(), nullable=True),
        sa.Column('map_coordinates', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['floor_map_id'], ['floor_map.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
        )

    if 'user_roles' not in tables:
        op.create_table('user_roles',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['role.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('user_id', 'role_id')
        )

    if 'booking' not in tables:
        op.create_table('booking',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('resource_id', sa.Integer(), nullable=False),
        sa.Column('user_name', sa.String(length=100), nullable=True),
        sa.Column('start_time', sa.DateTime(), nullable=False),
        sa.Column('end_time', sa.DateTime(), nullable=False),
        sa.Column('title', sa.String(length=100), nullable=True),
        sa.Column('checked_in_at', sa.DateTime(), nullable=True),
        sa.Column('checked_out_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('recurrence_rule', sa.String(length=200), nullable=True),
        sa.Column('admin_deleted_message', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['resource_id'], ['resource.id'], ),
        sa.PrimaryKeyConstraint('id')
        )

    if 'resource_roles' not in tables:
        op.create_table('resource_roles',
        sa.Column('resource_id', sa.Integer(), nullable=False),
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['resource_id'], ['resource.id'], ),
        sa.ForeignKeyConstraint(['role_id'], ['role.id'], ),
        sa.PrimaryKeyConstraint('resource_id', 'role_id')
        )

    if 'waitlist_entry' not in tables:
        op.create_table('waitlist_entry',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('resource_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['resource_id'], ['resource.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('waitlist_entry')
    op.drop_table('resource_roles')
    op.drop_table('booking')
    op.drop_table('user_roles')
    op.drop_table('resource')
    op.drop_table('audit_log')
    op.drop_table('user')
    op.drop_table('role')
    op.drop_table('floor_map')
    op.drop_table('booking_settings')
    # ### end Alembic commands ###
