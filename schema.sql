-- MVP Plan: SCHEMA.sql
-- This file defines the minimal database schema for the Telegram Bot System MVP.
-- Total tables: 6

-- Week 1 Tables

-- Table to store user accounts, points, and referral information.
CREATE TABLE users (
    user_id BIGINT PRIMARY KEY,
    points INTEGER NOT NULL DEFAULT 10,
    referred_by BIGINT REFERENCES users(user_id),
    is_unlimited BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE users IS 'Stores user accounts, points, referral status, and unlimited access rights.';
COMMENT ON COLUMN users.user_id IS 'Telegram user ID (Primary Key).';
COMMENT ON COLUMN users.points IS 'Number of points the user has.';
COMMENT ON COLUMN users.referred_by IS 'The user_id of the user who referred this user.';
COMMENT ON COLUMN users.is_unlimited IS 'Flag indicating if the user has unlimited points (typically by being a group admin).';

-- Table to act as a simple job queue for background processing.
CREATE TABLE jobs (
    job_id BIGSERIAL PRIMARY KEY,
    job_type VARCHAR(50) NOT NULL,
    payload JSONB,
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- e.g., pending, processing, completed, failed
    retries INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE jobs IS 'A simple, table-based job queue for asynchronous background tasks.';
COMMENT ON COLUMN jobs.job_type IS 'The type of job to be processed (e.g., ''process_dm'', ''approve_join_request'').';
COMMENT ON COLUMN jobs.payload IS 'The data required to execute the job (e.g., webhook content).';
COMMENT ON COLUMN jobs.status IS 'The current status of the job.';
COMMENT ON COLUMN jobs.retries IS 'The number of times this job has been attempted.';

-- Table for webhook deduplication to prevent processing the same event multiple times.
CREATE TABLE processed_webhooks (
    update_id BIGINT PRIMARY KEY,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE processed_webhooks IS 'Used for webhook deduplication. Stores the update_id of each processed Telegram webhook.';
-- Week 2 Tables

-- Table to store information about groups managed by the bot.
  CREATE TABLE groups (
      group_id BIGINT PRIMARY KEY,
      admin_user_id BIGINT NOT NULL REFERENCES users(user_id),
      is_active BOOLEAN NOT NULL DEFAULT TRUE,
      title VARCHAR(255),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  );

COMMENT ON COLUMN groups.group_id IS 'The Telegram chat ID of the group (Primary Key).';
COMMENT ON COLUMN groups.admin_user_id IS 'The user_id of the user who registered the group and has admin rights.';
  COMMENT ON COLUMN groups.is_active IS 'Flag to easily enable/disable message sending to this group.';
  COMMENT ON COLUMN groups.title IS 'The title of the Telegram group.';
 -- Table to store TGMS-managed groups with full lifecycle management
 CREATE TABLE managed_groups (
     group_id BIGINT PRIMARY KEY,
     admin_user_id BIGINT REFERENCES users(user_id),
     title VARCHAR(255),
     phase VARCHAR(20) NOT NULL DEFAULT 'growth', -- growth, monitoring
     is_active BOOLEAN NOT NULL DEFAULT TRUE,
     final_message_allowed BOOLEAN NOT NULL DEFAULT TRUE,
     member_count INTEGER DEFAULT 0,
     consecutive_failures INTEGER DEFAULT 0,
     created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
     updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
 );
 
 COMMENT ON TABLE managed_groups IS 'Groups managed by TGMS worker with full lifecycle tracking.';
 COMMENT ON COLUMN managed_groups.phase IS 'Current phase: growth (actively growing) or monitoring (stable).';
COMMENT ON COLUMN managed_groups.final_message_allowed IS 'Whether broadcasting is allowed to this group.';
COMMENT ON COLUMN managed_groups.consecutive_failures IS 'Count of consecutive send failures (auto-deactivate at 3).';
 
 -- Table for bot health monitoring
 CREATE TABLE bot_health (
     bot_name VARCHAR(50) PRIMARY KEY,
     status VARCHAR(20) NOT NULL, -- healthy, degraded, down
     last_activity TEXT,
     updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
 );
 
 COMMENT ON TABLE bot_health IS 'Tracks health status of bot workers.';
  
  
  -- Table to log join requests for auditing and to prevent duplicate processing.
  CREATE TABLE join_requests (
      request_id BIGSERIAL PRIMARY KEY,
      user_id BIGINT NOT NULL,
      chat_id BIGINT NOT NULL,
      username VARCHAR(255),
      status VARCHAR(20) NOT NULL DEFAULT 'pending', -- e.g., pending, approved, failed
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE (user_id, chat_id, status) -- Prevents duplicate entries for the same user/chat/status
  );

COMMENT ON TABLE join_requests IS 'Logs all incoming chat join requests.';
COMMENT ON COLUMN join_requests.status IS 'The status of the join request.';
COMMENT ON COLUMN join_requests.username IS 'Telegram username of the requesting user.';


  -- Table to track messages sent by the bot for debugging and analysis.
  CREATE TABLE sent_messages (
      message_id BIGSERIAL PRIMARY KEY,
      chat_id BIGINT NOT NULL,
      telegram_message_id BIGINT,
      debug_code VARCHAR(50) UNIQUE,
      sent_at TIMESTAMPTZ NOT NULL DEFAULT now()
  );

COMMENT ON TABLE sent_messages IS 'A log of all messages sent by the broadcasting service.';
COMMENT ON COLUMN sent_messages.debug_code IS 'A unique code appended to messages for tracking.';

  -- Create indexes for performance
  CREATE INDEX idx_jobs_status_created_at ON jobs(status, created_at);
  CREATE INDEX idx_jobs_type_status ON jobs(job_type, status);
  CREATE INDEX idx_groups_is_active ON groups(is_active);
  CREATE INDEX idx_managed_groups_is_active ON managed_groups(is_active);
  CREATE INDEX idx_managed_groups_phase ON managed_groups(phase);
  CREATE INDEX idx_join_requests_chat_id ON join_requests(chat_id);
  CREATE INDEX idx_join_requests_status ON join_requests(status);

-- Create a function to update the `updated_at` timestamp on jobs
CREATE OR REPLACE FUNCTION trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_timestamp
BEFORE UPDATE ON jobs
FOR EACH ROW
EXECUTE PROCEDURE trigger_set_timestamp();