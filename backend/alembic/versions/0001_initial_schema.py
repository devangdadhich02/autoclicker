"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("admin", "operator", "viewer", name="userrole"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "automation_jobs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_url", sa.String(2048), nullable=False),
        sa.Column(
            "status",
            sa.Enum("idle", "running", "paused", "error", "stopped", "recovering", name="jobstatus"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("restart_count", sa.Integer(), nullable=False),
        sa.Column("total_actions_executed", sa.Integer(), nullable=False),
        sa.Column("total_leads_detected", sa.Integer(), nullable=False),
        sa.Column("browser_profile_name", sa.String(255), nullable=True),
        sa.Column("scheduler_cron", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_automation_jobs_owner_id", "automation_jobs", ["owner_id"])

    op.create_table(
        "keywords",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column(
            "match_type",
            sa.Enum("exact", "contains", "regex", "starts_with", "ends_with", name="matchtype"),
            nullable=False,
        ),
        sa.Column("case_sensitive", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("location_filter", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("match_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["automation_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_keywords_job_id", "keywords", ["job_id"])

    op.create_table(
        "action_rules",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "action_type",
            sa.Enum(
                "click", "navigate", "fill_form", "extract_text", "screenshot",
                "wait", "scroll", "webhook", "notify", "mark_important",
                "open_inquiry", "copy_lead", name="actiontype",
            ),
            nullable=False,
        ),
        sa.Column("selector", sa.String(1000), nullable=True),
        sa.Column("fallback_selector", sa.String(1000), nullable=True),
        sa.Column("target_url", sa.String(2048), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=False),
        sa.Column("delay_after_ms", sa.Integer(), nullable=False),
        sa.Column("execution_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["automation_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_action_rules_job_id", "action_rules", ["job_id"])

    op.create_table(
        "event_logs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column(
            "severity",
            sa.Enum("debug", "info", "warning", "error", "critical", name="eventseverity"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("screenshot_path", sa.String(500), nullable=True),
        sa.Column("keyword_matched", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["automation_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_logs_job_id", "event_logs", ["job_id"])
    op.create_index("ix_event_logs_event_type", "event_logs", ["event_type"])

    op.create_table(
        "browser_sessions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "idle", "crashed", "closed", "recovering", name="sessionstatus"),
            nullable=False,
        ),
        sa.Column("browser_type", sa.String(50), nullable=False),
        sa.Column("current_url", sa.String(2048), nullable=True),
        sa.Column("profile_path", sa.String(500), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("last_activity", sa.DateTime(timezone=True), nullable=True),
        sa.Column("crash_count", sa.Integer(), nullable=False),
        sa.Column("last_crash_reason", sa.Text(), nullable=True),
        sa.Column("cookies_snapshot", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["automation_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_browser_sessions_job_id", "browser_sessions", ["job_id"])

    op.create_table(
        "settings",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_secret", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_settings_key", "settings", ["key"], unique=True)


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_table("browser_sessions")
    op.drop_table("event_logs")
    op.drop_table("action_rules")
    op.drop_table("keywords")
    op.drop_table("automation_jobs")
    op.drop_table("users")
