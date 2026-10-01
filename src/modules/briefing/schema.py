"""Briefing schema (part of migration 8): which news articles you have read."""

SCHEMA_V8_BRIEFING = """
CREATE TABLE news_read (
    article_id TEXT PRIMARY KEY,
    read_at    TEXT NOT NULL
)
"""
