import { useState, useEffect } from 'react';
import { monitoringApi, healthApi } from '../api';
import { DashboardStats, Tab } from '../types';

interface Props {
  onNavigate: (tab: Tab) => void;
}

function StatCard({ label, value, sub, color }: {
  label: string; value: string | number; sub?: string; color: string;
}) {
  return (
    <div className={`bg-gray-900 border border-gray-800 rounded-xl p-4 flex flex-col gap-1`}>
      <span className="text-xs text-gray-500 uppercase tracking-wide">{label}</span>
      <span className={`text-3xl font-bold ${color}`}>{value}</span>
      {sub && <span className="text-xs text-gray-500">{sub}</span>}
    </div>
  );
}

export default function DashboardTab({ onNavigate }: Props) {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [health, setHealth] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const [s, h] = await Promise.all([
        monitoringApi.stats(),
        healthApi.check(),
      ]);
      setStats(s);
      setHealth(h.services || {});
    } catch {
      // Backend offline — show placeholder
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); const i = setInterval(load, 10000); return () => clearInterval(i); }, []);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <p className="text-gray-400 text-sm mt-1">
          AI Agent Orchestration Platform — Real-time system overview
        </p>
      </div>

      {/* Architecture Overview */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">
          System Architecture
        </h2>
        <div className="overflow-x-auto">
          <div className="flex items-center gap-2 min-w-max">
            {[
              { label: 'Telegram / Web', icon: '💬', color: 'bg-blue-900/40 border-blue-700' },
              { label: '→', icon: '', color: '' },
              { label: 'FastAPI', icon: '⚡', color: 'bg-green-900/40 border-green-700' },
              { label: '→', icon: '', color: '' },
              { label: 'Redis Queue', icon: '📮', color: 'bg-red-900/40 border-red-700' },
              { label: '→', icon: '', color: '' },
              { label: 'LangGraph Worker', icon: '🧠', color: 'bg-violet-900/40 border-violet-700' },
              { label: '→', icon: '', color: '' },
              { label: 'PostgreSQL', icon: '🗄️', color: 'bg-yellow-900/40 border-yellow-700' },
            ].map((item, i) =>
              item.label === '→'
                ? <span key={i} className="text-gray-600 text-lg font-light">→</span>
                : (
                  <div key={i} className={`border rounded-lg px-3 py-2 text-xs font-medium text-white ${item.color}`}>
                    <div className="text-base mb-0.5">{item.icon}</div>
                    {item.label}
                  </div>
                )
            )}
          </div>
        </div>
        <p className="text-xs text-gray-600 mt-3">
          Webhook → Queue → Worker → LangGraph ensures Telegram responds in &lt;100ms.
          Redis Pub/Sub bridges worker events to WebSocket for real-time monitoring.
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard label="Total Executions" value={loading ? '—' : (stats?.total_executions ?? 0)} color="text-white" />
        <StatCard label="Running" value={loading ? '—' : (stats?.running_executions ?? 0)} color="text-emerald-400" sub="active now" />
        <StatCard label="Completed" value={loading ? '—' : (stats?.completed_executions ?? 0)} color="text-blue-400" />
        <StatCard label="Failed" value={loading ? '—' : (stats?.failed_executions ?? 0)} color="text-red-400" />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard label="Active Agents" value={loading ? '—' : (stats?.total_agents ?? 0)} color="text-violet-400" />
        <StatCard label="Workflows" value={loading ? '—' : (stats?.total_workflows ?? 0)} color="text-indigo-400" />
        <StatCard label="Tokens Today" value={loading ? '—' : (stats?.total_tokens_today ?? 0).toLocaleString()} color="text-yellow-400" />
        <StatCard label="Cost Today" value={loading ? '—' : `$${(stats?.total_cost_today ?? 0).toFixed(4)}`} color="text-orange-400" />
      </div>

      {/* Services Health */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">
          Service Health
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { key: 'database', label: 'PostgreSQL', icon: '🗄️' },
            { key: 'redis', label: 'Redis', icon: '📮' },
            { key: 'openai', label: 'OpenAI', icon: '🤖' },
            { key: 'telegram', label: 'Telegram', icon: '✈️' },
          ].map(({ key, label, icon }) => (
            <div key={key} className={`flex items-center gap-2 p-3 rounded-lg border ${
              health[key] === true ? 'bg-emerald-950/50 border-emerald-800' :
              health[key] === false ? 'bg-red-950/50 border-red-800' :
              'bg-gray-800 border-gray-700'
            }`}>
              <span className="text-base">{icon}</span>
              <div>
                <div className="text-xs font-medium text-white">{label}</div>
                <div className={`text-xs ${
                  health[key] === true ? 'text-emerald-400' :
                  health[key] === false ? 'text-red-400' : 'text-gray-500'
                }`}>
                  {health[key] === true ? 'Online' : health[key] === false ? 'Offline' : 'Unknown'}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Quick Actions */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">
          Quick Start
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {[
            {
              title: '1. Create an Agent',
              desc: 'Configure name, role, system prompt, model, and tools',
              action: 'Go to Agents →',
              tab: 'agents' as Tab,
              color: 'from-violet-600 to-indigo-600',
            },
            {
              title: '2. Build a Workflow',
              desc: 'Connect agents visually with React Flow drag-and-drop builder',
              action: 'Go to Workflows →',
              tab: 'workflows' as Tab,
              color: 'from-blue-600 to-cyan-600',
            },
            {
              title: '3. Monitor Execution',
              desc: 'Watch agents collaborate in real-time via WebSocket stream',
              action: 'Go to Monitor →',
              tab: 'monitor' as Tab,
              color: 'from-emerald-600 to-teal-600',
            },
          ].map((item) => (
            <button
              key={item.tab}
              onClick={() => onNavigate(item.tab)}
              className="text-left p-4 bg-gray-800 hover:bg-gray-750 border border-gray-700 hover:border-gray-600 rounded-xl transition-all group"
            >
              <div className={`inline-block text-xs font-bold px-2 py-0.5 rounded bg-gradient-to-r ${item.color} text-white mb-2`}>
                {item.title}
              </div>
              <p className="text-gray-400 text-xs leading-relaxed">{item.desc}</p>
              <p className="text-indigo-400 text-xs mt-2 group-hover:text-indigo-300">{item.action}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Tech Stack */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          Tech Stack Decisions
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
          {[
            { tech: 'LangGraph', reason: 'Native async, built-in checkpointing, conditional edges, HITL interrupt()', color: 'text-violet-400' },
            { tech: 'Redis + RQ', reason: 'Webhook→Queue ensures Telegram responds in <100ms. Pub/Sub bridges worker→WebSocket', color: 'text-red-400' },
            { tech: 'FastAPI', reason: 'Async-native, WebSocket support, auto OpenAPI docs, type-safe via Pydantic', color: 'text-green-400' },
            { tech: 'PostgreSQL', reason: 'ACID compliance, JSONB for flexible agent config, LangGraph checkpoint storage', color: 'text-yellow-400' },
            { tech: 'React Flow', reason: 'Visual workflow builder with draggable nodes, edge connections, zoom/pan', color: 'text-blue-400' },
            { tech: 'astream_events()', reason: 'Token-by-token streaming from LLM → Redis Pub/Sub → WebSocket → UI', color: 'text-orange-400' },
          ].map(({ tech, reason, color }) => (
            <div key={tech} className="flex gap-2">
              <span className={`font-bold min-w-fit ${color}`}>{tech}</span>
              <span className="text-gray-500">{reason}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
