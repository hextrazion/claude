-- Initial schema. Timestamps are ISO-8601 UTC strings.

CREATE TABLE settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE ideas (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    title              TEXT NOT NULL,
    niche              TEXT NOT NULL DEFAULT '',
    central_question   TEXT NOT NULL DEFAULT '',
    hook               TEXT NOT NULL DEFAULT '',
    description        TEXT NOT NULL DEFAULT '',
    appeal             TEXT NOT NULL DEFAULT '',
    visual_approach    TEXT NOT NULL DEFAULT '',
    est_duration_s     REAL,
    research_needs     TEXT NOT NULL DEFAULT '',
    accuracy_concerns  TEXT NOT NULL DEFAULT '',
    score              REAL,
    status             TEXT NOT NULL DEFAULT 'new',   -- new | favorite | rejected | approved | produced
    fingerprint        TEXT NOT NULL DEFAULT '',
    duplicate_of       INTEGER,
    duplicate_score    REAL,
    project_id         INTEGER,
    source             TEXT NOT NULL DEFAULT 'groq',  -- groq | manual
    model              TEXT,
    batch_id           TEXT,
    notes              TEXT NOT NULL DEFAULT '',
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX ideas_status ON ideas(status);

CREATE TABLE projects (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id           INTEGER REFERENCES ideas(id) ON DELETE SET NULL,
    title             TEXT NOT NULL,
    slug              TEXT NOT NULL,
    folder            TEXT NOT NULL,
    niche             TEXT NOT NULL DEFAULT '',
    stage             TEXT NOT NULL DEFAULT 'idea',      -- idea | research | script | scene_plan | production | assembly | review | complete
    status            TEXT NOT NULL DEFAULT 'idle',      -- idle | queued | running | waiting_approval | failed | cancelled | completed
    status_message    TEXT NOT NULL DEFAULT '',
    overrides_json    TEXT NOT NULL DEFAULT '{}',
    research_json     TEXT,
    research_status   TEXT NOT NULL DEFAULT 'none',      -- none | running | completed | skipped | failed
    script_json       TEXT,
    script_status     TEXT NOT NULL DEFAULT 'none',      -- none | draft | approved
    factcheck_json    TEXT,
    scene_plan_status TEXT NOT NULL DEFAULT 'none',      -- none | draft | approved
    narration_json    TEXT,
    narration_status  TEXT NOT NULL DEFAULT 'none',      -- none | running | completed | failed | stale
    export_json       TEXT,
    export_status     TEXT NOT NULL DEFAULT 'none',      -- none | running | completed | failed | stale
    qc_json           TEXT,
    assembly_approved INTEGER NOT NULL DEFAULT 0,
    review_status     TEXT NOT NULL DEFAULT 'none',      -- none | approved | rejected
    review_note       TEXT NOT NULL DEFAULT '',
    origin            TEXT NOT NULL DEFAULT 'manual',    -- manual | automation
    archived          INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE scenes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    idx              INTEGER NOT NULL,
    narration        TEXT NOT NULL DEFAULT '',
    visual_objective TEXT NOT NULL DEFAULT '',
    prompt           TEXT NOT NULL DEFAULT '',
    negative_prompt  TEXT NOT NULL DEFAULT '',
    camera           TEXT NOT NULL DEFAULT '',
    subject_motion   TEXT NOT NULL DEFAULT '',
    environment      TEXT NOT NULL DEFAULT '',
    style            TEXT NOT NULL DEFAULT '',
    duration_s       REAL NOT NULL DEFAULT 4,
    needs_image      INTEGER NOT NULL DEFAULT 0,
    image_prompt     TEXT NOT NULL DEFAULT '',
    transition       TEXT NOT NULL DEFAULT 'cut',
    settings_json    TEXT NOT NULL DEFAULT '{}',
    image_status     TEXT NOT NULL DEFAULT 'none',       -- none | queued | running | completed | failed
    image_path       TEXT,
    clip_status      TEXT NOT NULL DEFAULT 'none',       -- none | queued | running | completed | failed | stale
    clip_path        TEXT,
    clip_meta_json   TEXT,
    flags_json       TEXT NOT NULL DEFAULT '[]',
    updated_at       TEXT NOT NULL,
    UNIQUE(project_id, idx)
);

CREATE TABLE jobs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    scene_id          INTEGER REFERENCES scenes(id) ON DELETE SET NULL,
    kind              TEXT NOT NULL,
    lane              TEXT NOT NULL,                     -- gpu | api | cpu
    status            TEXT NOT NULL DEFAULT 'pending',   -- pending | running | paused | completed | failed | cancelled
    position          REAL NOT NULL,
    attempts          INTEGER NOT NULL DEFAULT 0,
    max_attempts      INTEGER NOT NULL DEFAULT 3,
    payload_json      TEXT NOT NULL DEFAULT '{}',
    result_json       TEXT,
    error_message     TEXT,
    error_detail      TEXT,
    error_kind        TEXT,
    provider          TEXT,
    external_id       TEXT,
    progress          REAL,
    progress_message  TEXT,
    cancel_requested  INTEGER NOT NULL DEFAULT 0,
    next_attempt_at   TEXT,
    created_at        TEXT NOT NULL,
    started_at        TEXT,
    finished_at       TEXT,
    updated_at        TEXT NOT NULL
);
CREATE INDEX jobs_status ON jobs(status, lane, position);
CREATE INDEX jobs_project ON jobs(project_id);

CREATE TABLE activity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    level       TEXT NOT NULL,                           -- info | warning | error
    category    TEXT NOT NULL,
    message     TEXT NOT NULL,
    detail      TEXT,
    project_id  INTEGER,
    job_id      INTEGER
);
CREATE INDEX activity_ts ON activity(ts);

CREATE TABLE api_usage (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT NOT NULL,
    provider       TEXT NOT NULL,
    model          TEXT,
    operation      TEXT NOT NULL,
    ok             INTEGER NOT NULL,
    status_code    INTEGER,
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    characters     INTEGER,
    cost_usd       REAL,
    duration_ms    INTEGER,
    error          TEXT,
    project_id     INTEGER
);
CREATE INDEX api_usage_ts ON api_usage(provider, ts);

CREATE TABLE cache (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT
);
