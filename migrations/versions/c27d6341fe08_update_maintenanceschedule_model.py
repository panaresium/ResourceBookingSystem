"""Update MaintenanceSchedule model

Revision ID: c27d6341fe08
Revises: 44d956e882f7
Create Date: 2025-07-24 03:37:09.889475

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c27d6341fe08'
down_revision = '44d956e882f7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('maintenance_schedule',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('schedule_type', sa.String(length=50), nullable=False),
    sa.Column('day_of_week', sa.String(length=50), nullable=True),
    sa.Column('day_of_month', sa.String(length=200), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('is_availability', sa.Boolean(), nullable=False),
    sa.Column('resource_selection_type', sa.String(length=50), nullable=False),
    sa.Column('resource_ids', sa.Text(), nullable=True),
    sa.Column('building_id', sa.Integer(), nullable=True),
    sa.Column('floor_ids', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('maintenance_schedule')
