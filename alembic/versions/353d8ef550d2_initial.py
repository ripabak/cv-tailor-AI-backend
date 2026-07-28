"""initial

Revision ID: 353d8ef550d2
Revises: 
Create Date: 2026-07-28 21:43:23.051558

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '353d8ef550d2'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('user',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_user_email'), 'user', ['email'], unique=True)
    op.create_index(op.f('ix_user_id'), 'user', ['id'], unique=False)

    op.create_table('template',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('html_code', sa.Text(), nullable=False),
        sa.Column('creator_id', sa.Integer(), nullable=True),
        sa.Column('is_published', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['creator_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_template_id'), 'template', ['id'], unique=False)

    op.create_table('user_cv',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['template_id'], ['template.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_user_cv_id'), 'user_cv', ['id'], unique=False)

    op.create_table('cv_version',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_cv_id', sa.Integer(), nullable=False),
        sa.Column('html_content', sa.Text(), nullable=False),
        sa.Column('parent_version_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['parent_version_id'], ['cv_version.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_cv_id'], ['user_cv.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_cv_version_id'), 'cv_version', ['id'], unique=False)

    op.add_column('user_cv',
        sa.Column('current_version_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_user_cv_current_version', 'user_cv', 'cv_version',
        ['current_version_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_user_cv_current_version', 'user_cv', type_='foreignkey')
    op.drop_column('user_cv', 'current_version_id')
    op.drop_index(op.f('ix_cv_version_id'), table_name='cv_version')
    op.drop_table('cv_version')
    op.drop_index(op.f('ix_user_cv_id'), table_name='user_cv')
    op.drop_table('user_cv')
    op.drop_index(op.f('ix_template_id'), table_name='template')
    op.drop_table('template')
    op.drop_index(op.f('ix_user_id'), table_name='user')
    op.drop_index(op.f('ix_user_email'), table_name='user')
    op.drop_table('user')
