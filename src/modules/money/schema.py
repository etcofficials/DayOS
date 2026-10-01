"""Money schema (part of migration 8): a manual tracker; no bank connections.

Amounts are stored as integers in the currency's minor unit (for example paise or
cents) so totals are exact. The currency itself is a preference the user chooses.
"""

SCHEMA_V8_MONEY = """
CREATE TABLE money_categories (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL CHECK (length(trim(name)) > 0),
    kind       TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
    position   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (name, kind)
);

CREATE TABLE subscriptions (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL CHECK (length(trim(name)) > 0),
    amount      INTEGER NOT NULL CHECK (amount > 0),
    cycle       TEXT NOT NULL DEFAULT 'monthly' CHECK (cycle IN ('weekly', 'monthly', 'quarterly', 'yearly')),
    next_date   TEXT NOT NULL,
    category_id INTEGER REFERENCES money_categories(id) ON DELETE SET NULL,
    remind_days INTEGER NOT NULL DEFAULT 3 CHECK (remind_days BETWEEN 0 AND 30),
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    url         TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE money_entries (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
    amount          INTEGER NOT NULL CHECK (amount > 0),
    category_id     INTEGER REFERENCES money_categories(id) ON DELETE SET NULL,
    date            TEXT NOT NULL,
    note            TEXT NOT NULL DEFAULT '',
    subscription_id INTEGER REFERENCES subscriptions(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_money_entries_date ON money_entries(date);

CREATE TABLE money_budgets (
    id          INTEGER PRIMARY KEY,
    category_id INTEGER REFERENCES money_categories(id) ON DELETE CASCADE,
    amount      INTEGER NOT NULL CHECK (amount > 0),
    created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_money_budget_category ON money_budgets(COALESCE(category_id, 0));

CREATE TABLE savings_goals (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL CHECK (length(trim(name)) > 0),
    target      INTEGER NOT NULL CHECK (target > 0),
    saved       INTEGER NOT NULL DEFAULT 0 CHECK (saved >= 0),
    target_date TEXT,
    created_at  TEXT NOT NULL
)
"""

DEFAULT_CATEGORIES = {
    "expense": ["Food & groceries", "Transport", "Rent & bills", "Education", "Health", "Shopping", "Entertainment",
                "Subscriptions", "Other"],
    "income": ["Salary", "Pocket money", "Freelance", "Gifts", "Other"],
}

SEARCH_SOURCES_V8_MONEY = [
    ("subscriptions", "subscription", "{r}.name", "{r}.note"),
]
