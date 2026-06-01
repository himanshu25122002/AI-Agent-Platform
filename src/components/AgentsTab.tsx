import { useState, useEffect } from 'react';
import { agentsApi } from '../api';
import { Agent, AVAILABLE_MODELS, AVAILABLE_TOOLS } from '../types';

const EMPTY_FORM = {
  name: '',
  role: '',
  system_prompt: '',
  model: 'gpt-4o-mini' as string,
  tools: [] as string[],
  channels: ['web'] as string[],
  memory_settings: { type: 'buffer', window: 10 },
  guardrails: { max_iterations: 5, timeout_seconds: 60 },
};

type FormState = typeof EMPTY_FORM;

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${color}`}>
      {label}
    </span>
  );
}

function AgentForm({
  initial,
  onSave,
  onCancel,
}: {
  initial: FormState;
  onSave: (data: FormState) => Promise<void>;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<FormState>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      await onSave(form);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const toggleTool = (tool: string) => {
    setForm((f) => ({
      ...f,
      tools: f.tools.includes(tool)
        ? f.tools.filter((t) => t !== tool)
        : [...f.tools, tool],
    }));
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div className="bg-red-950/50 border border-red-700 rounded-lg p-3 text-red-300 text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-xs text-gray-400 mb-1">Name *</label>
          <input
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            placeholder="Research Agent"
            required
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Role *</label>
          <input
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
            value={form.role}
            onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
            placeholder="researcher"
            required
          />
        </div>
      </div>

      <div>
        <label className="block text-xs text-gray-400 mb-1">System Prompt *</label>
        <textarea
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500 resize-none"
          rows={4}
          value={form.system_prompt}
          onChange={(e) => setForm((f) => ({ ...f, system_prompt: e.target.value }))}
          placeholder="You are an expert researcher. Gather comprehensive, accurate information..."
          required
        />
        <p className="text-xs text-gray-600 mt-1">{form.system_prompt.length} chars — min 10</p>
      </div>

      <div>
        <label className="block text-xs text-gray-400 mb-1">Model</label>
        <select
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
          value={form.model}
          onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}
        >
          {AVAILABLE_MODELS.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-xs text-gray-400 mb-2">Tools</label>
        <div className="flex flex-wrap gap-2">
          {AVAILABLE_TOOLS.map((tool) => (
            <button
              key={tool.id}
              type="button"
              onClick={() => toggleTool(tool.id)}
              className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${
                form.tools.includes(tool.id)
                  ? 'bg-indigo-600 border-indigo-500 text-white'
                  : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600'
              }`}
              title={tool.description}
            >
              {tool.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs text-gray-400 mb-1">Max Iterations</label>
          <input
            type="number"
            min={1}
            max={20}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
            value={(form.guardrails as Record<string, number>).max_iterations ?? 5}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                guardrails: { ...f.guardrails, max_iterations: parseInt(e.target.value) },
              }))
            }
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Timeout (sec)</label>
          <input
            type="number"
            min={10}
            max={300}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
            value={(form.guardrails as Record<string, number>).timeout_seconds ?? 60}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                guardrails: { ...f.guardrails, timeout_seconds: parseInt(e.target.value) },
              }))
            }
          />
        </div>
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 rounded-lg text-sm bg-indigo-600 hover:bg-indigo-500 text-white font-medium disabled:opacity-50 transition-colors"
        >
          {saving ? 'Saving...' : 'Save Agent'}
        </button>
      </div>
    </form>
  );
}

export default function AgentsTab() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Agent | null>(null);
  const [testAgent, setTestAgent] = useState<Agent | null>(null);
  const [testPrompt, setTestPrompt] = useState('');
  const [testResult, setTestResult] = useState<string>('');
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    try {
      const data = await agentsApi.list();
      setAgents(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load agents');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async (form: FormState) => {
    await agentsApi.create(form);
    setShowForm(false);
    load();
  };

  const handleUpdate = async (form: FormState) => {
    if (!editing) return;
    await agentsApi.update(editing.id, form);
    setEditing(null);
    load();
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Deactivate this agent?')) return;
    await agentsApi.delete(id);
    load();
  };

  const handleTest = async () => {
    if (!testAgent || !testPrompt) return;
    setTesting(true);
    setTestResult('');
    try {
      const result = await agentsApi.test(testAgent.id, testPrompt);
      if (result.success && result.data) {
        const d = result.data as Record<string, unknown>;
        setTestResult(String(d.response || 'No response'));
      }
    } catch (e: unknown) {
      setTestResult(`Error: ${e instanceof Error ? e.message : 'Test failed'}`);
    } finally {
      setTesting(false);
    }
  };

  const MODEL_COLORS: Record<string, string> = {
    'gpt-4o': 'bg-emerald-900/50 text-emerald-300',
    'gpt-4o-mini': 'bg-blue-900/50 text-blue-300',
    'gpt-3.5-turbo': 'bg-yellow-900/50 text-yellow-300',
    'gpt-4-turbo': 'bg-violet-900/50 text-violet-300',
  };

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Agents</h1>
          <p className="text-gray-400 text-sm mt-0.5">
            {agents.length} agent{agents.length !== 1 ? 's' : ''} configured
          </p>
        </div>
        <button
          onClick={() => { setShowForm(true); setEditing(null); }}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors"
        >
          + New Agent
        </button>
      </div>

      {error && (
        <div className="bg-red-950/50 border border-red-700 rounded-lg p-3 text-red-300 text-sm">
          {error} — Is the backend running?
        </div>
      )}

      {/* Create / Edit Form */}
      {(showForm || editing) && (
        <div className="bg-gray-900 border border-indigo-700/50 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-indigo-400 mb-4">
            {editing ? `Edit: ${editing.name}` : 'Create New Agent'}
          </h2>
          <AgentForm
            initial={editing
              ? { name: editing.name, role: editing.role, system_prompt: editing.system_prompt, model: editing.model, tools: editing.tools, channels: editing.channels, memory_settings: editing.memory_settings as typeof EMPTY_FORM['memory_settings'], guardrails: editing.guardrails as typeof EMPTY_FORM['guardrails'] }
              : EMPTY_FORM
            }
            onSave={editing ? handleUpdate : handleCreate}
            onCancel={() => { setShowForm(false); setEditing(null); }}
          />
        </div>
      )}

      {/* Agents Grid */}
      {loading ? (
        <div className="text-center py-12 text-gray-600">Loading agents...</div>
      ) : agents.length === 0 ? (
        <div className="text-center py-12 bg-gray-900 border border-gray-800 rounded-xl">
          <div className="text-4xl mb-3">🤖</div>
          <p className="text-gray-400 font-medium">No agents yet</p>
          <p className="text-gray-600 text-sm mt-1">Templates are seeded automatically on backend startup</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {agents.map((agent) => (
            <div
              key={agent.id}
              className="bg-gray-900 border border-gray-800 rounded-xl p-4 flex flex-col gap-3 hover:border-gray-700 transition-colors"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-600 to-indigo-600 flex items-center justify-center text-sm font-bold text-white">
                    {agent.name[0]}
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-white">{agent.name}</div>
                    <div className="text-xs text-gray-500">{agent.role}</div>
                  </div>
                </div>
                <div className={`w-2 h-2 rounded-full mt-1 ${agent.is_active ? 'bg-emerald-400' : 'bg-gray-600'}`} />
              </div>

              <p className="text-xs text-gray-400 line-clamp-2 leading-relaxed">
                {agent.system_prompt}
              </p>

              <div className="flex flex-wrap gap-1.5">
                <Badge label={agent.model} color={MODEL_COLORS[agent.model] || 'bg-gray-800 text-gray-300'} />
                {agent.tools.map((t) => (
                  <Badge key={t} label={t} color="bg-gray-800 text-gray-400" />
                ))}
              </div>

              <div className="flex gap-2 pt-1 border-t border-gray-800">
                <button
                  onClick={() => { setTestAgent(agent); setTestResult(''); setTestPrompt(''); }}
                  className="flex-1 text-xs py-1.5 rounded-md bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white transition-colors"
                >
                  Test
                </button>
                <button
                  onClick={() => { setEditing(agent); setShowForm(false); }}
                  className="flex-1 text-xs py-1.5 rounded-md bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white transition-colors"
                >
                  Edit
                </button>
                <button
                  onClick={() => handleDelete(agent.id)}
                  className="flex-1 text-xs py-1.5 rounded-md bg-red-950/50 hover:bg-red-900/50 text-red-400 hover:text-red-300 transition-colors"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Test Modal */}
      {testAgent && (
        <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-white">Test: {testAgent.name}</h2>
              <button onClick={() => setTestAgent(null)} className="text-gray-500 hover:text-white text-xl leading-none">×</button>
            </div>
            <textarea
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500 resize-none"
              rows={3}
              value={testPrompt}
              onChange={(e) => setTestPrompt(e.target.value)}
              placeholder="Enter a test prompt..."
            />
            <button
              onClick={handleTest}
              disabled={testing || !testPrompt}
              className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {testing ? 'Testing...' : 'Run Test'}
            </button>
            {testResult && (
              <div className="bg-gray-800 rounded-lg p-3 text-sm text-gray-300 max-h-60 overflow-y-auto whitespace-pre-wrap leading-relaxed">
                {testResult}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
