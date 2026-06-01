// ============================================================
// Yuno Agent Platform — TypeScript Type Definitions
// ============================================================

export interface Agent {
  id: string;
  name: string;
  role: string;
  system_prompt: string;
  model: string;
  tools: string[];
  memory_settings: Record<string, unknown>;
  channels: string[];
  guardrails: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkflowNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: {
    label: string;
    node_type: string;
    agent_id?: string;
    config?: Record<string, unknown>;
  };
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  data?: Record<string, unknown>;
}

export interface Workflow {
  id: string;
  name: string;
  description?: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  is_template: boolean;
  template_type?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Execution {
  id: string;
  workflow_id?: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'waiting_human' | 'cancelled';
  trigger_type: string;
  trigger_data?: Record<string, unknown>;
  input_message: string;
  output_message?: string;
  current_node?: string;
  error_message?: string;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  estimated_cost: number;
  started_at?: string;
  completed_at?: string;
  created_at: string;
}

export interface Message {
  id: string;
  execution_id: string;
  agent_id?: string;
  sender_name: string;
  sender_type: 'user' | 'agent' | 'system' | 'tool';
  message_type: string;
  content: string;
  metadata: {
    tokens?: number;
    latency_ms?: number;
    model?: string;
    tool_name?: string;
  };
  created_at: string;
}

export interface DashboardStats {
  total_executions: number;
  running_executions: number;
  completed_executions: number;
  failed_executions: number;
  waiting_human: number;
  total_agents: number;
  total_workflows: number;
  total_tokens_today: number;
  total_cost_today: number;
}

export type WSEventType =
  | 'connected'
  | 'ping'
  | 'execution_started'
  | 'node_started'
  | 'node_completed'
  | 'agent_message'
  | 'token_chunk'
  | 'tool_call'
  | 'tool_result'
  | 'human_approval_needed'
  | 'execution_completed'
  | 'execution_failed'
  | 'cost_update';

export interface WSEvent {
  type: WSEventType;
  execution_id?: string;
  timestamp: string;
  data: Record<string, unknown>;
}

export type Tab = 'dashboard' | 'agents' | 'workflows' | 'monitor';

export const AVAILABLE_MODELS = [
  'gpt-4o-mini',
  'gpt-4o',
  'gpt-3.5-turbo',
  'gpt-4-turbo',
] as const;

export const AVAILABLE_TOOLS = [
  { id: 'web_search', label: 'Web Search', description: 'Search the web via Tavily' },
  { id: 'calculator', label: 'Calculator', description: 'Math expressions' },
  { id: 'datetime', label: 'DateTime', description: 'Current date/time' },
] as const;

export const NODE_TYPES_CONFIG = [
  { type: 'trigger', label: 'Trigger', color: '#6366f1', description: 'Workflow entry point' },
  { type: 'agent', label: 'Agent', color: '#0ea5e9', description: 'AI agent node' },
  { type: 'decision', label: 'Decision', color: '#f59e0b', description: 'Conditional routing' },
  { type: 'human_approval', label: 'Human Approval', color: '#8b5cf6', description: 'Pause for review' },
  { type: 'delay', label: 'Delay', color: '#64748b', description: 'Wait/rate limit' },
] as const;
