"""Initial schema

Revision ID: 001_initial
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tenants table
    op.create_table(
        'tenants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('plan', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tenants_id'), 'tenants', ['id'], unique=False)

    # Users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_tenant_id'), 'users', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # Analyses table
    op.create_table(
        'analyses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('scoring_version', sa.String(length=20), nullable=True),
        sa.Column('final_score', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_analyses_id'), 'analyses', ['id'], unique=False)
    op.create_index(op.f('ix_analyses_tenant_id'), 'analyses', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_analyses_user_id'), 'analyses', ['user_id'], unique=False)
    op.create_index(op.f('ix_analyses_status'), 'analyses', ['status'], unique=False)
    op.create_index(op.f('ix_analyses_created_at'), 'analyses', ['created_at'], unique=False)

    # Jobs table
    op.create_table(
        'jobs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('result', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('progress', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)

    # History table
    op.create_table(
        'history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('scoring_version', sa.String(length=20), nullable=True),
        sa.Column('feature_vector', sa.Text(), nullable=True),
        sa.Column('analysis_status', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_history_id'), 'history', ['id'], unique=False)
    op.create_index(op.f('ix_history_user_id'), 'history', ['user_id'], unique=False)

    # Usage counters table
    op.create_table(
        'usage_counters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.DateTime(), nullable=True),
        sa.Column('count', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_usage_counters_id'), 'usage_counters', ['id'], unique=False)
    op.create_index(op.f('ix_usage_counters_user_id'), 'usage_counters', ['user_id'], unique=False)
    op.create_index(op.f('ix_usage_counters_date'), 'usage_counters', ['date'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_usage_counters_date'), table_name='usage_counters')
    op.drop_index(op.f('ix_usage_counters_user_id'), table_name='usage_counters')
    op.drop_index(op.f('ix_usage_counters_id'), table_name='usage_counters')
    op.drop_table('usage_counters')

    op.drop_index(op.f('ix_history_user_id'), table_name='history')
    op.drop_index(op.f('ix_history_id'), table_name='history')
    op.drop_table('history')

    op.drop_index(op.f('ix_jobs_status'), table_name='jobs')
    op.drop_table('jobs')

    op.drop_index(op.f('ix_analyses_created_at'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_status'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_user_id'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_tenant_id'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_id'), table_name='analyses')
    op.drop_table('analyses')

    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_index(op.f('ix_users_tenant_id'), table_name='users')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_table('users')

    op.drop_index(op.f('ix_tenants_id'), table_name='tenants')
    op.drop_table('tenants')
