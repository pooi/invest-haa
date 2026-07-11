"""Add live order audit records."""

from sqlalchemy import inspect

from alembic import op

from invest_haa.db import LiveOrderModel

revision = "0002_live_orders"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "live_orders" not in inspect(bind).get_table_names():
        LiveOrderModel.__table__.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    if "live_orders" in inspect(bind).get_table_names():
        LiveOrderModel.__table__.drop(bind=bind)
