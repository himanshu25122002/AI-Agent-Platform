// ============================================================
// Yuno Agent Platform — API Client
// Thin wrapper around fetch — no axios needed
// ============================================================

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const BASE_URL = (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000/api';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(error.error || error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

// ---- Agents ------------------------------------------------
export const agentsApi = {
  list: () => request<import('./types').Agent[]>('/agents'),
  get: (id: string) => request<import('./types').Agent>(`/agents/${id}`),
  create: (data: unknown) => request<import('./types').Agent>('/agents', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  update: (id: string, data: unknown) => request<import('./types').Agent>(`/agents/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  }),
  delete: (id: string) => request<{ success: boolean }>(`/agents/${id}`, { method: 'DELETE' }),
  test: (id: string, prompt: string) => request<{ success: boolean; data: unknown }>(`/agents/${id}/test`, {
    method: 'POST',
    body: JSON.stringify({ prompt }),
  }),
};

// ---- Workflows ---------------------------------------------
export const workflowsApi = {
  list: () => request<import('./types').Workflow[]>('/workflows'),
  templates: () => request<import('./types').Workflow[]>('/workflows/templates'),
  get: (id: string) => request<import('./types').Workflow>(`/workflows/${id}`),
  create: (data: unknown) => request<import('./types').Workflow>('/workflows', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  update: (id: string, data: unknown) => request<import('./types').Workflow>(`/workflows/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  }),
  delete: (id: string) => request<{ success: boolean }>(`/workflows/${id}`, { method: 'DELETE' }),
  execute: (id: string, input_message: string) =>
    request<{ execution_id: string; websocket_url: string }>(`/workflows/${id}/execute`, {
      method: 'POST',
      body: JSON.stringify({ input_message }),
    }),
  validate: (id: string) => request<{ is_valid: boolean; errors: string[] }>(`/workflows/${id}/validate`),
};

// ---- Executions --------------------------------------------
export const executionsApi = {
  list: (status?: string) => request<import('./types').Execution[]>(
    `/executions${status ? `?status_filter=${status}` : ''}`
  ),
  get: (id: string) => request<import('./types').Execution>(`/executions/${id}`),
  messages: (id: string) => request<import('./types').Message[]>(`/executions/${id}/messages`),
  approve: (id: string, approved: boolean, feedback?: string) =>
    request<{ success: boolean }>(`/executions/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approved, feedback }),
    }),
  cancel: (id: string) => request<{ success: boolean }>(`/executions/${id}/cancel`, { method: 'POST' }),
};

// ---- Monitoring --------------------------------------------
export const monitoringApi = {
  stats: () => request<import('./types').DashboardStats>('/monitoring/stats'),
  recentMessages: () => request<import('./types').Message[]>('/monitoring/messages/recent'),
};

// ---- Health ------------------------------------------------
export const healthApi = {
  check: async () => {
    try {
      const response = await fetch(`${BASE_URL.replace('/api', '')}/health`);
      return await response.json();
    } catch {
      return {
        status: 'unreachable',
        services: {
          database: false,
          redis: false,
        },
      };
    }
  },
};
