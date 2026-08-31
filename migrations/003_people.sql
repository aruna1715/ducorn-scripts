-- One place that decides what a person is called.
--
-- Today three separate pieces of code turn an email into a name, all the same
-- way and all independently:
--
--   main.py       current_user():  email.split("@")[0]
--   index.html    _who(email):     String(email).split('@')[0]
--   index.html    the user chip:   _me.name, from current_user()
--
-- which is why the Founder's Corner says "aruna1715". Nobody is called that.
-- Fixing it in one of those three places would leave the other two disagreeing,
-- and a name that renders differently in two panels of the same screen is worse
-- than one that is wrong consistently.
--
-- So: a table. The API reads it and returns a name; the dashboard displays what
-- it is given rather than deriving its own.

CREATE TABLE IF NOT EXISTS people (
    email        TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    -- For the avatar chip. NULL means "use the first letter of display_name",
    -- which is right for most people and wrong for anyone who goes by initials.
    initials     TEXT,
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE people IS
    'Display names for the humans who use DuCorn. The API resolves an email '
    'through here; nothing else should split an email to make a name.';

-- Seed from emails that have already appeared, so no existing note loses its
-- attribution. display_name starts as the local part — exactly what is shown
-- now, so applying this migration changes nothing until the names are set.
INSERT INTO people (email, display_name)
SELECT DISTINCT created_by, split_part(created_by, '@', 1)
FROM founder_notes
WHERE created_by IS NOT NULL AND created_by <> ''
ON CONFLICT (email) DO NOTHING;

INSERT INTO people (email, display_name)
SELECT DISTINCT done_by, split_part(done_by, '@', 1)
FROM founder_notes
WHERE done_by IS NOT NULL AND done_by <> ''
ON CONFLICT (email) DO NOTHING;

INSERT INTO people (email, display_name)
VALUES ('vnk@inno-growth.com', 'Vijay')
ON CONFLICT (email) DO NOTHING;

-- The remaining names are not mine to guess. After applying, set them:
--
--   UPDATE people SET display_name='Aruna' WHERE email LIKE 'aruna%';
--   SELECT email, display_name FROM people ORDER BY email;
--
-- An email with no row here still renders as its local part, so a new person
-- appearing is untidy rather than broken.
