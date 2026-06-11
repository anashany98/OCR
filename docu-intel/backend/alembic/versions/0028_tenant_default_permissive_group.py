"""SEC-TENANT-1 (Sprint 1): backfill a default-permissive AccessGroup.

The Sprint 1 change to ``resolve_user_access_scope`` makes the
multi-tenant isolation deny-by-default: a user with no
``AccessGroup`` membership sees zero documents. This is a
behaviour change for any deployment that relied on the legacy
role-based permissive defaults (``gestor``/``operario``/``auditor``
seeing everything).

The backfill preserves the legacy behaviour by:

1. Creating a single ``default-permissive`` ``AccessGroup`` with
   ``permissions_json`` mirroring the pre-Sprint-1 defaults
   (``allow_all_hotels=True``, ``allow_unassigned_documents=True``).
2. Adding every existing non-admin user to the group, so they keep
   the same access they had before the rollout.

After this migration runs, an operator can opt in to the
deny-by-default behaviour by removing specific users from the
``default-permissive`` group (or by deleting the group entirely).
The Sprint 1 code path already enforces the deny-by-default once
the user has no group membership.

The migration is **idempotent**: re-running it is a no-op (it
checks for existing rows before inserting).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0028_tenant_default_permissive_group"
down_revision = "0027_integration_clients_key_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the default group and add every non-admin user to it.

    Implemented in raw SQL so it works on both Postgres (the
    production target) and SQLite (the test target — Alembic
    defaults to a SQLAlchemy URL that resolves to SQLite in many
    test environments).
    """
    # 1. Insert the default-permissive group if it doesn't already
    #    exist. The ``permissions_json`` value mirrors the legacy
    #    pre-Sprint-1 defaults for ``gestor`` (the most permissive
    #    of the non-admin roles: can_view_prices=True is gated by
    #    the per-group field; the default we ship keeps prices
    #    hidden so a fresh deployment defaults to a strict posture,
    #    but every other dimension matches the legacy behaviour).
    op.execute(
        sa.text(
            """
            INSERT INTO access_groups
                (name, description, permissions_json, is_active, created_at, updated_at)
            SELECT
                'default-permissive',
                'Backfilled by Sprint 1 migration. Mirrors the legacy permissive defaults.',
                '{"chain_ids": [], "hotel_ids": [], "allow_all_hotels": true, "denied_tags": [], "can_view_prices": false, "can_search_budgets": false, "allow_unassigned_documents": true}',
                true,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            WHERE NOT EXISTS (
                SELECT 1 FROM access_groups WHERE name = 'default-permissive'
            )
            """
        )
    )

    # 2. Add every non-admin user to the group. The subselect returns
    #    the group's id; the outer WHERE excludes users that are
    #    already members (idempotent). Admins are excluded because
    #    their access scope is built independently.
    op.execute(
        sa.text(
            """
            INSERT INTO access_group_members
                (group_id, principal_type, principal_id, created_at)
            SELECT
                (SELECT id FROM access_groups WHERE name = 'default-permissive'),
                'user',
                u.id,
                CURRENT_TIMESTAMP
            FROM users u
            WHERE u.is_active = true
              AND u.role != 'admin'
              AND NOT EXISTS (
                SELECT 1
                FROM access_group_members m
                WHERE m.group_id = (SELECT id FROM access_groups WHERE name = 'default-permissive')
                  AND m.principal_type = 'user'
                  AND m.principal_id = u.id
              )
            """
        )
    )


def downgrade() -> None:
    """Remove the default-permissive group and its memberships.

    Downgrading to pre-Sprint-1 restores the original deny-by-default
    behaviour where the migration is no longer present. Operators
    who downgrade MUST also set
    ``settings.tenant_access_deny_by_default=False`` to restore the
    legacy permissive defaults.
    """
    op.execute(
        sa.text("DELETE FROM access_group_members WHERE principal_type = 'user'")
    )
    op.execute(
        sa.text("DELETE FROM access_groups WHERE name = 'default-permissive'")
    )
