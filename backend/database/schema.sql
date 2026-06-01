-- ============================================================
-- Yuno Agent Platform — PostgreSQL Schema
-- Version: 1.0.0
--
-- Design principles:
-- - 4 core tables (agents, workflows, executions, messages)
-- - JSONB for flexible configuration fields
-- - UUID primary keys (no integer sequences to coordinate)
-- - Soft deletes (is_active flag)
-- - Timezone-aware timestamps (TIMESTAMPTZ)
-- - Indexes on all foreign keys and frequently filtered columns
-- ============================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- AGENTS
-- Stores agent configuration. JSONB for tools/memory/guardrails
-- because these evolve independently of schema migrations.
-- ============================================================
CREATE TABLE IF NOT EXISTS agents (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name              VARCHAR(100) NOT NULL,
    role              VARCHAR(100) NOT NULL,
    system_prompt     TEXT         NOT NULL,
    model             VARCHAR(50)  NOT NULL DEFAULT 'gpt-4o-mini',

    -- JSONB fields for flexible configuration
    tools             JSONB        NOT NULL DEFAULT '[]',
    memory_settings   JSONB        NOT NULL DEFAULT '{"type": "buffer", "window": 10}',
    channels          JSONB        NOT NULL DEFAULT '["web"]',
    guardrails        JSONB        NOT NULL DEFAULT '{"max_iterations": 5, "timeout_seconds": 60}',

    is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agents_name ON agents(name);
CREATE INDEX IF NOT EXISTS idx_agents_active ON agents(is_active);


-- ============================================================
-- WORKFLOWS
-- Stores the full workflow graph as React Flow JSON.
-- One table for both user workflows and pre-built templates.
-- ============================================================
CREATE TABLE IF NOT EXISTS workflows (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(100) NOT NULL,
    description   TEXT,

    -- Complete React Flow graph stored as JSON
    nodes         JSONB        NOT NULL DEFAULT '[]',
    edges         JSONB        NOT NULL DEFAULT '[]',

    -- Template management
    is_template   BOOLEAN      NOT NULL DEFAULT FALSE,
    template_type VARCHAR(50),   -- 'research', 'content'

    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflows_name ON workflows(name);
CREATE INDEX IF NOT EXISTS idx_workflows_template ON workflows(is_template);
CREATE INDEX IF NOT EXISTS idx_workflows_active ON workflows(is_active);


-- ============================================================
-- EXECUTIONS
-- Each row = one workflow run.
-- LangGraph checkpoints stored in its own table (auto-managed).
-- ============================================================
CREATE TABLE IF NOT EXISTS executions (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id       UUID        REFERENCES workflows(id) ON DELETE SET NULL,

    -- Status lifecycle: pending → running → completed | failed | waiting_human | cancelled
    status            VARCHAR(20)  NOT NULL DEFAULT 'pending',

    -- What triggered this execution
    trigger_type      VARCHAR(20)  NOT NULL DEFAULT 'manual',   -- manual, telegram, schedule
    trigger_data      JSONB,                                     -- {chat_id: 123, username: "alice"}

    -- Input/Output
    input_message     TEXT         NOT NULL,
    output_message    TEXT,
    current_node      VARCHAR(100),   -- Live tracking: which node is executing
    error_message     TEXT,

    -- Cost tracking (OpenAI pricing)
    total_tokens      INTEGER      NOT NULL DEFAULT 0,
    prompt_tokens     INTEGER      NOT NULL DEFAULT 0,
    completion_tokens INTEGER      NOT NULL DEFAULT 0,
    estimated_cost    DECIMAL(10,6) NOT NULL DEFAULT 0,

    -- Timing
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_executions_status ON executions(status);
CREATE INDEX IF NOT EXISTS idx_executions_workflow ON executions(workflow_id);
CREATE INDEX IF NOT EXISTS idx_executions_created ON executions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_executions_trigger ON executions(trigger_type);


-- ============================================================
-- MESSAGES
-- All communications within an execution:
-- - Agent-to-agent messages
-- - Tool calls and results
-- - User inputs
-- - System events
-- ============================================================
CREATE TABLE IF NOT EXISTS messages (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id  UUID        NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    agent_id      UUID        REFERENCES agents(id) ON DELETE SET NULL,

    sender_name   VARCHAR(100) NOT NULL,
    sender_type   VARCHAR(20)  NOT NULL,   -- user, agent, system, tool
    message_type  VARCHAR(30)  NOT NULL DEFAULT 'text',  -- text, tool_call, tool_result, handoff, error
    content       TEXT         NOT NULL,

    -- Per-message metadata: {tokens: 150, latency_ms: 823, model: "gpt-4o-mini"}
    metadata      JSONB        NOT NULL DEFAULT '{}',

    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_execution ON messages(execution_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent_id);
CREATE INDEX IF NOT EXISTS idx_messages_type ON messages(sender_type, message_type);


-- ============================================================
-- AUTO-UPDATE updated_at TRIGGER
-- Automatically keeps updated_at current on any UPDATE.
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_agents_updated_at
    BEFORE UPDATE ON agents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_workflows_updated_at
    BEFORE UPDATE ON workflows
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();


-- ============================================================
-- NOTE: LangGraph checkpoint tables are created automatically
-- by langgraph-checkpoint-postgres when the first execution runs.
-- They store the complete graph state for persistence & memory.
-- Do not manually create: checkpoint_blobs, checkpoint_writes,
-- checkpoint_migrations tables.
-- ============================================================
