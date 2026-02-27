"""Migrate legacy phone columns to contact_phones table.

Revision ID: 002
Revises: 001
Create Date: 2026-02-27

Copies phone_primary, phone_mobile, phone_work from contacts into the
normalized contact_phones table. Idempotent via ON CONFLICT DO NOTHING.
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # mobile phones
    op.execute("""
        INSERT INTO contact_phones (contact_id, type, number)
        SELECT c.id, 'mobile', c.phone_mobile
        FROM contacts c
        WHERE c.phone_mobile IS NOT NULL AND c.phone_mobile != ''
          AND NOT EXISTS (
              SELECT 1 FROM contact_phones cp
              WHERE cp.contact_id = c.id AND cp.number = c.phone_mobile
          )
        ON CONFLICT (contact_id, number) DO NOTHING
    """)
    # home/primary phones
    op.execute("""
        INSERT INTO contact_phones (contact_id, type, number)
        SELECT c.id, 'home', c.phone_primary
        FROM contacts c
        WHERE c.phone_primary IS NOT NULL AND c.phone_primary != ''
          AND NOT EXISTS (
              SELECT 1 FROM contact_phones cp
              WHERE cp.contact_id = c.id AND cp.number = c.phone_primary
          )
        ON CONFLICT (contact_id, number) DO NOTHING
    """)
    # work phones
    op.execute("""
        INSERT INTO contact_phones (contact_id, type, number)
        SELECT c.id, 'work', c.phone_work
        FROM contacts c
        WHERE c.phone_work IS NOT NULL AND c.phone_work != ''
          AND NOT EXISTS (
              SELECT 1 FROM contact_phones cp
              WHERE cp.contact_id = c.id AND cp.number = c.phone_work
          )
        ON CONFLICT (contact_id, number) DO NOTHING
    """)


def downgrade() -> None:
    # Data migration — downgrade is a no-op.
    # Legacy columns (phone_primary, phone_mobile, phone_work) remain populated.
    pass
