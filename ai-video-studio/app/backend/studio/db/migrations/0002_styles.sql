-- Style library: reference images/videos analysed into a reusable visual style.

CREATE TABLE styles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    notes        TEXT NOT NULL DEFAULT '',            -- the user's own description
    status       TEXT NOT NULL DEFAULT 'new',         -- new | analyzing | ready | failed
    profile_json TEXT,                                -- analysis result (editable)
    refs_json    TEXT NOT NULL DEFAULT '[]',          -- reference files and extracted frames
    error        TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
