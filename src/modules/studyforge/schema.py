"""StudyForge tables (schema migration 4).

Hierarchy: course → nodes (subject / unit / chapter / topic / objective, any depth the
user wants) → questions, flashcards and study material linked to nodes.

Provenance is explicit everywhere:
* documents keep their file name, SHA-256, session/version and import problems;
* questions record ``origin`` (official / imported / user / ai) and ``verified``;
* blueprints record ``status`` (verified / provisional / user) and their source;
* test items store a snapshot of each question so later edits never rewrite a past test.
"""

from __future__ import annotations

SCHEMA_V4 = """
CREATE TABLE sf_courses (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL CHECK (length(trim(name)) > 0),
    kind        TEXT NOT NULL DEFAULT 'custom' CHECK (kind IN ('school', 'college', 'exam', 'skill', 'custom')),
    session     TEXT NOT NULL DEFAULT '',
    authority   TEXT NOT NULL DEFAULT '',
    level       TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE sf_documents (
    id               INTEGER PRIMARY KEY,
    course_id        INTEGER REFERENCES sf_courses(id) ON DELETE CASCADE,
    title            TEXT NOT NULL CHECK (length(trim(title)) > 0),
    filename         TEXT NOT NULL DEFAULT '',
    path             TEXT NOT NULL DEFAULT '',
    kind             TEXT NOT NULL DEFAULT 'other' CHECK (kind IN ('syllabus', 'textbook', 'sample_paper', 'marking_scheme',
                     'notes', 'revision_sheet', 'chapter_list', 'other')),
    official         INTEGER NOT NULL DEFAULT 0 CHECK (official IN (0, 1)),
    sha256           TEXT NOT NULL DEFAULT '',
    pages            INTEGER NOT NULL DEFAULT 0,
    text_chars       INTEGER NOT NULL DEFAULT 0,
    session          TEXT NOT NULL DEFAULT '',
    authority        TEXT NOT NULL DEFAULT '',
    syllabus_version TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'parsed' CHECK (status IN ('parsed', 'partial', 'unreadable')),
    problems         TEXT NOT NULL DEFAULT '[]',
    imported_at      TEXT NOT NULL
);
CREATE INDEX idx_sf_documents_course ON sf_documents(course_id);

CREATE TABLE sf_document_pages (
    document_id INTEGER NOT NULL REFERENCES sf_documents(id) ON DELETE CASCADE,
    page        INTEGER NOT NULL,
    text        TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (document_id, page)
);

CREATE TABLE sf_nodes (
    id            INTEGER PRIMARY KEY,
    course_id     INTEGER NOT NULL REFERENCES sf_courses(id) ON DELETE CASCADE,
    parent_id     INTEGER REFERENCES sf_nodes(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL CHECK (kind IN ('subject', 'unit', 'chapter', 'topic', 'objective')),
    title         TEXT NOT NULL CHECK (length(trim(title)) > 0),
    position      INTEGER NOT NULL DEFAULT 0,
    subject_id    INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    exam_date     TEXT,
    weight        REAL,
    source_doc_id INTEGER REFERENCES sf_documents(id) ON DELETE SET NULL,
    source_ref    TEXT NOT NULL DEFAULT '',
    confidence    REAL,
    notes         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE INDEX idx_sf_nodes_course ON sf_nodes(course_id, parent_id, position);

CREATE TABLE sf_questions (
    id            INTEGER PRIMARY KEY,
    course_id     INTEGER REFERENCES sf_courses(id) ON DELETE CASCADE,
    node_id       INTEGER REFERENCES sf_nodes(id) ON DELETE SET NULL,
    qtype         TEXT NOT NULL CHECK (qtype IN ('mcq', 'multi', 'assertion', 'tf', 'fill', 'match', 'numerical',
                  'vsa', 'sa', 'la', 'case', 'source', 'competency', 'application', 'diagram')),
    difficulty    INTEGER NOT NULL DEFAULT 2 CHECK (difficulty BETWEEN 1 AND 5),
    marks         REAL NOT NULL DEFAULT 1 CHECK (marks > 0),
    text          TEXT NOT NULL CHECK (length(trim(text)) > 0),
    options       TEXT NOT NULL DEFAULT '[]',
    answer        TEXT NOT NULL DEFAULT '',
    explanation   TEXT NOT NULL DEFAULT '',
    rubric        TEXT NOT NULL DEFAULT '[]',
    origin        TEXT NOT NULL DEFAULT 'user' CHECK (origin IN ('official', 'imported', 'user', 'ai')),
    verified      INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    source_doc_id INTEGER REFERENCES sf_documents(id) ON DELETE SET NULL,
    source_ref    TEXT NOT NULL DEFAULT '',
    tags          TEXT NOT NULL DEFAULT '',
    media_path    TEXT NOT NULL DEFAULT '',
    content_hash  TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE (course_id, content_hash)
);
CREATE INDEX idx_sf_questions_node ON sf_questions(node_id, qtype);

CREATE TABLE sf_blueprints (
    id             INTEGER PRIMARY KEY,
    course_id      INTEGER REFERENCES sf_courses(id) ON DELETE CASCADE,
    subject_node_id INTEGER REFERENCES sf_nodes(id) ON DELETE SET NULL,
    name           TEXT NOT NULL CHECK (length(trim(name)) > 0),
    session        TEXT NOT NULL DEFAULT '',
    max_marks      REAL NOT NULL CHECK (max_marks > 0),
    duration_min   INTEGER NOT NULL CHECK (duration_min > 0),
    instructions   TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'user' CHECK (status IN ('verified', 'provisional', 'user')),
    source_doc_id  INTEGER REFERENCES sf_documents(id) ON DELETE SET NULL,
    source_note    TEXT NOT NULL DEFAULT '',
    version        TEXT NOT NULL DEFAULT '',
    sections       TEXT NOT NULL DEFAULT '[]',
    coverage       TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE sf_tests (
    id           INTEGER PRIMARY KEY,
    course_id    INTEGER REFERENCES sf_courses(id) ON DELETE CASCADE,
    blueprint_id INTEGER REFERENCES sf_blueprints(id) ON DELETE SET NULL,
    title        TEXT NOT NULL CHECK (length(trim(title)) > 0),
    mode         TEXT NOT NULL DEFAULT 'practice' CHECK (mode IN ('practice', 'timed')),
    duration_min INTEGER,
    total_marks  REAL NOT NULL DEFAULT 0,
    config       TEXT NOT NULL DEFAULT '{}',
    instructions TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE TABLE sf_test_items (
    id           INTEGER PRIMARY KEY,
    test_id      INTEGER NOT NULL REFERENCES sf_tests(id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    section      TEXT NOT NULL DEFAULT '',
    question_id  INTEGER REFERENCES sf_questions(id) ON DELETE SET NULL,
    snapshot     TEXT NOT NULL,
    marks        REAL NOT NULL CHECK (marks > 0),
    choice_group INTEGER
);
CREATE INDEX idx_sf_test_items ON sf_test_items(test_id, position);

CREATE TABLE sf_attempts (
    id           INTEGER PRIMARY KEY,
    test_id      INTEGER NOT NULL REFERENCES sf_tests(id) ON DELETE CASCADE,
    started_at   TEXT NOT NULL,
    submitted_at TEXT,
    elapsed_s    INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'submitted', 'marked')),
    score        REAL,
    max_score    REAL,
    has_estimates INTEGER NOT NULL DEFAULT 0 CHECK (has_estimates IN (0, 1))
);
CREATE INDEX idx_sf_attempts_test ON sf_attempts(test_id, started_at);

CREATE TABLE sf_answers (
    attempt_id INTEGER NOT NULL REFERENCES sf_attempts(id) ON DELETE CASCADE,
    item_id    INTEGER NOT NULL REFERENCES sf_test_items(id) ON DELETE CASCADE,
    response   TEXT NOT NULL DEFAULT '',
    flagged    INTEGER NOT NULL DEFAULT 0 CHECK (flagged IN (0, 1)),
    marks      REAL,
    marker     TEXT NOT NULL DEFAULT 'none' CHECK (marker IN ('none', 'auto', 'self', 'ai')),
    correct    INTEGER,
    feedback   TEXT NOT NULL DEFAULT '',
    time_s     INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (attempt_id, item_id)
);

CREATE TABLE sf_topic_state (
    node_id        INTEGER PRIMARY KEY REFERENCES sf_nodes(id) ON DELETE CASCADE,
    ease           REAL NOT NULL DEFAULT 2.5,
    interval_days  INTEGER NOT NULL DEFAULT 0,
    due_date       TEXT,
    last_practiced TEXT,
    reps           INTEGER NOT NULL DEFAULT 0,
    lapses         INTEGER NOT NULL DEFAULT 0,
    attempts       INTEGER NOT NULL DEFAULT 0,
    correct        REAL NOT NULL DEFAULT 0,
    confidence     INTEGER CHECK (confidence IS NULL OR confidence BETWEEN 1 AND 5),
    manual_due     INTEGER NOT NULL DEFAULT 0 CHECK (manual_due IN (0, 1)),
    updated_at     TEXT NOT NULL
);
CREATE INDEX idx_sf_topic_due ON sf_topic_state(due_date);

CREATE TABLE sf_review_log (
    id         INTEGER PRIMARY KEY,
    node_id    INTEGER NOT NULL REFERENCES sf_nodes(id) ON DELETE CASCADE,
    date       TEXT NOT NULL,
    source     TEXT NOT NULL CHECK (source IN ('test', 'recall', 'manual', 'flashcard')),
    score      REAL NOT NULL CHECK (score BETWEEN 0 AND 1),
    detail     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_sf_review_log ON sf_review_log(node_id, date);

CREATE TABLE sf_flashcards (
    id            INTEGER PRIMARY KEY,
    course_id     INTEGER REFERENCES sf_courses(id) ON DELETE CASCADE,
    node_id       INTEGER REFERENCES sf_nodes(id) ON DELETE SET NULL,
    kind          TEXT NOT NULL DEFAULT 'card' CHECK (kind IN ('card', 'formula', 'definition', 'keyterm', 'qa')),
    front         TEXT NOT NULL CHECK (length(trim(front)) > 0),
    back          TEXT NOT NULL DEFAULT '',
    source_ref    TEXT NOT NULL DEFAULT '',
    ai_generated  INTEGER NOT NULL DEFAULT 0 CHECK (ai_generated IN (0, 1)),
    reviewed      INTEGER NOT NULL DEFAULT 1 CHECK (reviewed IN (0, 1)),
    ease          REAL NOT NULL DEFAULT 2.5,
    interval_days INTEGER NOT NULL DEFAULT 0,
    due_date      TEXT,
    reps          INTEGER NOT NULL DEFAULT 0,
    lapses        INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX idx_sf_cards_due ON sf_flashcards(course_id, due_date);

CREATE TABLE sf_materials (
    id            INTEGER PRIMARY KEY,
    course_id     INTEGER REFERENCES sf_courses(id) ON DELETE CASCADE,
    node_id       INTEGER REFERENCES sf_nodes(id) ON DELETE SET NULL,
    kind          TEXT NOT NULL DEFAULT 'notes' CHECK (kind IN ('notes', 'summary', 'formula_sheet', 'definitions',
                  'keyterms')),
    title         TEXT NOT NULL CHECK (length(trim(title)) > 0),
    body          TEXT NOT NULL DEFAULT '',
    source_doc_id INTEGER REFERENCES sf_documents(id) ON DELETE SET NULL,
    source_ref    TEXT NOT NULL DEFAULT '',
    ai_generated  INTEGER NOT NULL DEFAULT 0 CHECK (ai_generated IN (0, 1)),
    reviewed      INTEGER NOT NULL DEFAULT 1 CHECK (reviewed IN (0, 1)),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE sf_mistake_categories (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(trim(name)) > 0),
    builtin INTEGER NOT NULL DEFAULT 0 CHECK (builtin IN (0, 1))
);

ALTER TABLE mistakes ADD COLUMN node_id INTEGER REFERENCES sf_nodes(id) ON DELETE SET NULL;
ALTER TABLE mistakes ADD COLUMN question_id INTEGER REFERENCES sf_questions(id) ON DELETE SET NULL;
ALTER TABLE mistakes ADD COLUMN user_answer TEXT NOT NULL DEFAULT '';
ALTER TABLE mistakes ADD COLUMN expected_answer TEXT NOT NULL DEFAULT '';
ALTER TABLE mistakes ADD COLUMN explanation TEXT NOT NULL DEFAULT '';
ALTER TABLE mistakes ADD COLUMN category TEXT NOT NULL DEFAULT '';
ALTER TABLE mistakes ADD COLUMN next_review TEXT;
ALTER TABLE mistakes ADD COLUMN reviews INTEGER NOT NULL DEFAULT 0;
ALTER TABLE mistakes ADD COLUMN attempt_id INTEGER REFERENCES sf_attempts(id) ON DELETE SET NULL;
ALTER TABLE study_sessions ADD COLUMN node_id INTEGER REFERENCES sf_nodes(id) ON DELETE SET NULL;

INSERT INTO sf_mistake_categories (name, builtin) VALUES
    ('Conceptual misunderstanding', 1), ('Calculation error', 1), ('Formula error', 1),
    ('Memory or recall error', 1), ('Misread question', 1), ('Incomplete explanation', 1),
    ('Unit or notation error', 1), ('Time-management issue', 1)
"""

SEARCH_SOURCES_V4 = [
    ("sf_questions", "question", "substr({r}.text, 1, 200)", "{r}.explanation || ' ' || {r}.tags || ' ' || {r}.answer"),
    ("sf_nodes", "course", "{r}.title", "{r}.notes"),
    ("sf_flashcards", "flashcard", "{r}.front", "{r}.back"),
    ("sf_materials", "material", "{r}.title", "{r}.body"),
]

EXPORT_TABLES = [
    "sf_courses", "sf_documents", "sf_document_pages", "sf_nodes", "sf_questions", "sf_blueprints", "sf_tests",
    "sf_test_items", "sf_attempts", "sf_answers", "sf_topic_state", "sf_review_log", "sf_flashcards", "sf_materials",
    "sf_mistake_categories",
]
