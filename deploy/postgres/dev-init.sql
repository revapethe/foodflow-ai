-- Only for the loopback-bound development instance with trust authentication.
-- Outside this workspace, provision a restricted LOGIN using secure DBA tooling.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'foodflow_reader') THEN
    CREATE ROLE foodflow_reader LOGIN;
  END IF;
END $$;
