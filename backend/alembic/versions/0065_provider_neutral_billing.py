"""Add provider-neutral Dodo billing fields without deleting legacy financial data.

Revision ID: 0065
Revises: 0064
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve the old provider columns for rollback and historical reporting.
    # Their values are copied into the generic provider fields and explicitly
    # tagged as Razorpay history; all new application writes use provider='dodo'.
    op.add_column("subscriptions", sa.Column("provider", sa.String(32), nullable=False, server_default="dodo"))
    op.add_column("subscriptions", sa.Column("provider_subscription_id", sa.String(255), nullable=True))
    op.add_column("subscriptions", sa.Column("provider_checkout_session_id", sa.String(255), nullable=True))
    op.add_column("subscriptions", sa.Column("provider_customer_id", sa.String(255), nullable=True))
    op.add_column("subscriptions", sa.Column("provider_product_id", sa.String(255), nullable=True))
    op.add_column("subscriptions", sa.Column("provider_event_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("subscriptions", sa.Column("quoted_amount", sa.Integer(), nullable=True))
    op.add_column("subscriptions", sa.Column("discount_percent", sa.Integer(), nullable=False, server_default="0"))
    op.execute(
        "UPDATE subscriptions SET provider='razorpay', provider_subscription_id=razorpay_subscription_id"
    )
    op.create_unique_constraint(
        "uq_subscriptions_provider_subscription_id", "subscriptions", ["provider", "provider_subscription_id"]
    )
    op.create_unique_constraint(
        "uq_subscriptions_provider_checkout_id", "subscriptions", ["provider", "provider_checkout_session_id"]
    )

    op.add_column("payments", sa.Column("provider", sa.String(32), nullable=False, server_default="dodo"))
    op.add_column("payments", sa.Column("provider_payment_id", sa.String(255), nullable=True))
    op.add_column("payments", sa.Column("provider_event_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE payments SET provider='razorpay', provider_payment_id=razorpay_payment_id")
    op.create_unique_constraint("uq_payments_provider_payment_id", "payments", ["provider", "provider_payment_id"])

    op.create_table(
        "billing_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="processing"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "event_id", name="uq_billing_webhook_provider_event"),
    )
    op.create_index("ix_billing_webhook_events_status_received", "billing_webhook_events", ["status", "received_at"])

    op.create_table(
        "payment_refunds",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("payment_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_refund_id", sa.String(255), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "provider_refund_id", name="uq_payment_refunds_provider_id"),
    )
    op.create_index("ix_payment_refunds_payment_id", "payment_refunds", ["payment_id"])


def downgrade() -> None:
    bind = op.get_bind()
    has_provider_data = bind.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM subscriptions
             WHERE provider <> 'razorpay'
                OR provider_subscription_id IS DISTINCT FROM razorpay_subscription_id
                OR provider_checkout_session_id IS NOT NULL
                OR provider_customer_id IS NOT NULL
                OR provider_product_id IS NOT NULL
                OR provider_event_at IS NOT NULL
                OR quoted_amount IS NOT NULL
                OR discount_percent <> 0
            UNION ALL
            SELECT 1 FROM payments
             WHERE provider <> 'razorpay'
                OR provider_payment_id IS DISTINCT FROM razorpay_payment_id
                OR provider_event_at IS NOT NULL
            UNION ALL SELECT 1 FROM billing_webhook_events
            UNION ALL SELECT 1 FROM payment_refunds
        )
    """)).scalar_one()
    if has_provider_data:
        raise RuntimeError(
            "cannot downgrade billing revision 0065: provider-neutral payment, subscription, webhook, or refund data exists"
        )

    op.drop_index("ix_payment_refunds_payment_id", table_name="payment_refunds")
    op.drop_table("payment_refunds")
    op.drop_index("ix_billing_webhook_events_status_received", table_name="billing_webhook_events")
    op.drop_table("billing_webhook_events")
    op.drop_constraint("uq_payments_provider_payment_id", "payments", type_="unique")
    op.drop_column("payments", "provider_event_at")
    op.drop_column("payments", "provider_payment_id")
    op.drop_column("payments", "provider")
    op.drop_constraint("uq_subscriptions_provider_checkout_id", "subscriptions", type_="unique")
    op.drop_constraint("uq_subscriptions_provider_subscription_id", "subscriptions", type_="unique")
    for column in (
        "discount_percent", "quoted_amount", "provider_event_at", "provider_product_id", "provider_customer_id",
        "provider_checkout_session_id", "provider_subscription_id", "provider",
    ):
        op.drop_column("subscriptions", column)
