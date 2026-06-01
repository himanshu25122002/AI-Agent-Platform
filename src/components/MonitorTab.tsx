import { useState, useEffect, useRef, useCallback } from 'react';
import { executionsApi, workflowsApi } from '../api';
import { Execution, Message, WSEvent, Workflow } from '../types';

const WS_BASE = ((import.meta as unknown) as { env?: Record<string, string> }).env?.VITE_WS_URL || 'ws://localhost:8000/ws';

function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, string> = {
    running: 'bg-emerald-900/60 text-emerald-300 border-emerald-800',
    completed: 'bg-blue-900/60 text-blue-300 border-blue-800',
    failed: 'bg-red-900/60 text-red-300 border-red-800',
    pending: 'bg-yellow-900/60 text-yellow-300 border-yellow-800',
    waiting_human: 'bg-violet-900/60 text-violet-300 border-violet-800',
    cancelled: 'bg-gray-800 text-gray-400 border-gray-700',
  };
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded border font-medium ${cfg[status] || 'bg-gray-800 text-gray-400 border-gray-700'}`}>
      {status.replace('_', ' ')}
    </span>
  );
}

function EventRow({ event }: { event: WSEvent & { _seq?: number } }) {
  const icons: Record<string, string> = {
    execution_started: '🚀',
    node_started: '▶',
    node_completed: '✓',
    agent_message: '🤖',
    token_chunk: '💬',
    tool_call: '🔧',
    tool_result: '📤',
    human_approval_needed: '👤',
    execution_completed: '✅',
    execution_failed: '❌',
    cost_update: '💰',
    connected: '🔌',
    ping: '🏓',
  };

  const colors: Record<string, string> = {
    execution_started: 'text-indigo-400',
    node_started: 'text-blue-400',
    node_completed: 'text-blue-300',
    agent_message: 'text-emerald-400',
    token_chunk: 'text-gray-500',
    tool_call: 'text-yellow-400',
    tool_result: 'text-yellow-300',
    human_approval_needed: 'text-violet-400',
    execution_completed: 'text-emerald-400',
    execution_failed: 'text-red-400',
    cost_update: 'text-orange-400',
    connected: 'text-gray-500',
    ping: 'text-gray-700',
  };

  if (event.type === 'ping') return null;

  const renderContent = () => {
    const d = event.data;
    switch (event.type) {
      case 'agent_message':
        return (
          <div>
            <span className="font-semibold text-white">{String(d.agent || '')}: </span>
            <span className="text-gray-300">{String(d.content || '').slice(0, 200)}{String(d.content || '').length > 200 ? '...' : ''}</span>
            {d.tokens ? <span className="ml-2 text-xs text-gray-600">[{String(d.tokens)} tokens]</span> : null}
          </div>
        );
      case 'tool_call':
        return <span>Tool: <span className="text-yellow-300">{String(d.tool || '')}</span> — {String(d.input || '').slice(0, 100)}</span>;
      case 'tool_result':
        return <span>Result from <span className="text-yellow-300">{String(d.tool || '')}</span>: {String(d.output || '').slice(0, 100)}</span>;
      case 'cost_update':
        return <span>Tokens: {String(d.total_tokens || 0)} · Cost: ${Number(d.estimated_cost || 0).toFixed(6)}</span>;
      case 'execution_completed':
        return <span>Output: {String(d.output || '').slice(0, 200)}</span>;
      case 'execution_failed':
        return <span className="text-red-300">Error: {String(d.error || '')}</span>;
      case 'node_started':
        return <span>Node: <span className="text-white">{String(d.node || '')}</span></span>;
      case 'human_approval_needed':
        return <span className="text-violet-300">⏸ Waiting for human approval — use /executions/&#123;id&#125;/approve</span>;
      default:
        return <span>{JSON.stringify(d).slice(0, 150)}</span>;
    }
  };

  return (
    <div className="flex gap-2 py-1.5 border-b border-gray-900 text-xs">
      <span className="text-base w-5 flex-shrink-0">{icons[event.type] || '·'}</span>
      <span className={`flex-shrink-0 font-mono min-w-[150px] ${colors[event.type] || 'text-gray-500'}`}>
        {event.type}
      </span>
      <span className="text-gray-400 flex-1 leading-relaxed">{renderContent()}</span>
      <span className="text-gray-700 flex-shrink-0 font-mono">
        {new Date(event.timestamp).toLocaleTimeString()}
      </span>
    </div>
  );
}

export default function MonitorTab() {
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [events, setEvents] = useState<(WSEvent & { _seq?: number })[]>([]);
  const [selectedExec, setSelectedExec] = useState<Execution | null>(null);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [wsStatus, setWsStatus] = useState<'disconnected' | 'connecting' | 'connected'>('disconnected');
  const [liveTokens, setLiveTokens] = useState(0);
  const [liveCost, setLiveCost] = useState(0);
  const [currentNode, setCurrentNode] = useState('');
  const [approving, setApproving] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const eventsEndRef = useRef<HTMLDivElement | null>(null);
  const seqRef = useRef(0);
  const [tab, setTab] = useState<'events' | 'messages'>('events');

  const load = async () => {
    try {
      const [execs, wf] = await Promise.all([
        executionsApi.list(),
        workflowsApi.list(),
      ]);
      setExecutions(execs);
      setWorkflows(wf);
    } catch {
      // Backend offline
    }
  };

  useEffect(() => { load(); const i = setInterval(load, 5000); return () => clearInterval(i); }, []);

  const subscribeToExecution = useCallback((exec: Execution) => {
    // Close existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }

    setSelectedExec(exec);
    setEvents([]);
    setLiveTokens(exec.total_tokens);
    setLiveCost(exec.estimated_cost);
    setCurrentNode(exec.current_node || '');

    // Load existing messages
    executionsApi.messages(exec.id).then(setMessages).catch(() => setMessages([]));

    // Connect WebSocket
    setWsStatus('connecting');
    const ws = new WebSocket(`${WS_BASE}/${exec.id}`);
    wsRef.current = ws;

    ws.onopen = () => setWsStatus('connected');
    ws.onclose = () => setWsStatus('disconnected');
    ws.onerror = () => setWsStatus('disconnected');

    ws.onmessage = (e) => {
      try {
        const event: WSEvent = JSON.parse(e.data);
        const seq = ++seqRef.current;
        setEvents((prev) => [...prev.slice(-200), { ...event, _seq: seq }]); // Keep last 200

        // Update live metrics
        if (event.type === 'cost_update') {
          setLiveTokens(Number(event.data.total_tokens || 0));
          setLiveCost(Number(event.data.estimated_cost || 0));
        }
        if (event.type === 'node_started') {
          setCurrentNode(String(event.data.node || ''));
        }

        // Reload on terminal events
        if (event.type === 'execution_completed' || event.type === 'execution_failed') {
          load();
          executionsApi.messages(exec.id).then(setMessages).catch(() => {});
        }
      } catch {
        // Invalid JSON
      }
    };
  }, []);

  useEffect(() => {
    if (eventsEndRef.current) {
      eventsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [events]);

  useEffect(() => {
    return () => { wsRef.current?.close(); };
  }, []);

  const handleApprove = async (approved: boolean) => {
    if (!selectedExec) return;
    setApproving(true);
    try {
      await executionsApi.approve(selectedExec.id, approved);
    } catch (e) {
      console.error(e);
    } finally {
      setApproving(false);
    }
  };

  const workflowName = (id?: string | null) => {
    if (!id) return 'Unknown';
    return workflows.find(w => w.id === id)?.name || id.slice(0, 8);
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-white">Monitor</h1>
        <p className="text-gray-400 text-sm mt-0.5">Real-time execution monitoring via WebSocket</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4" style={{ minHeight: '70vh' }}>
        {/* Left: Execution List */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl flex flex-col">
          <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <span className="text-sm font-semibold text-white">Executions</span>
            <button onClick={load} className="text-xs text-gray-500 hover:text-gray-300">Refresh</button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {executions.length === 0 ? (
              <div className="p-4 text-center text-gray-600 text-sm">
                No executions yet. Run a workflow to start.
              </div>
            ) : (
              executions.map((exec) => (
                <button
                  key={exec.id}
                  onClick={() => subscribeToExecution(exec)}
                  className={`w-full text-left px-4 py-3 border-b border-gray-800 hover:bg-gray-800/50 transition-colors ${
                    selectedExec?.id === exec.id ? 'bg-indigo-950/30 border-l-2 border-l-indigo-500' : ''
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-gray-300 font-mono">{exec.id.slice(0, 8)}…</span>
                    <StatusBadge status={exec.status} />
                  </div>
                  <div className="text-xs text-gray-500 truncate">{exec.input_message}</div>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-[10px] text-gray-600">{workflowName(exec.workflow_id)}</span>
                    <span className="text-[10px] text-gray-700">·</span>
                    <span className="text-[10px] text-gray-600">
                      {exec.trigger_type === 'telegram' ? '✈️ Telegram' : '🖥 Manual'}
                    </span>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Right: Event Stream */}
        <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-xl flex flex-col">
          {/* Header */}
          <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-3">
              <span className="text-sm font-semibold text-white">
                {selectedExec ? `Execution: ${selectedExec.id.slice(0, 8)}…` : 'Select an execution'}
              </span>
              <div className={`flex items-center gap-1.5 text-xs ${
                wsStatus === 'connected' ? 'text-emerald-400' :
                wsStatus === 'connecting' ? 'text-yellow-400' : 'text-gray-600'
              }`}>
                <div className={`w-1.5 h-1.5 rounded-full ${
                  wsStatus === 'connected' ? 'bg-emerald-400 animate-pulse' :
                  wsStatus === 'connecting' ? 'bg-yellow-400 animate-pulse' : 'bg-gray-600'
                }`} />
                {wsStatus}
              </div>
            </div>

            {/* Live Metrics */}
            {selectedExec && (
              <div className="flex items-center gap-3 text-xs">
                {currentNode && (
                  <span className="bg-blue-900/40 text-blue-300 border border-blue-800 px-2 py-0.5 rounded text-[10px]">
                    ▶ {currentNode}
                  </span>
                )}
                <span className="text-yellow-400 font-mono">{liveTokens.toLocaleString()} tkns</span>
                <span className="text-orange-400 font-mono">${liveCost.toFixed(5)}</span>
              </div>
            )}
          </div>

          {/* Human Approval Banner */}
          {selectedExec?.status === 'waiting_human' && (
            <div className="mx-4 mt-3 bg-violet-950/40 border border-violet-700 rounded-lg p-3 flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold text-violet-300">👤 Human Approval Required</div>
                <div className="text-xs text-violet-400 mt-0.5">Review agent output and approve to continue</div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handleApprove(false)}
                  disabled={approving}
                  className="px-3 py-1.5 text-xs rounded-lg bg-red-900/50 text-red-300 hover:bg-red-800/50 border border-red-700 disabled:opacity-50"
                >
                  Reject
                </button>
                <button
                  onClick={() => handleApprove(true)}
                  disabled={approving}
                  className="px-3 py-1.5 text-xs rounded-lg bg-emerald-900/50 text-emerald-300 hover:bg-emerald-800/50 border border-emerald-700 disabled:opacity-50"
                >
                  Approve
                </button>
              </div>
            </div>
          )}

          {/* Tabs */}
          <div className="flex border-b border-gray-800 px-4 pt-2">
            {(['events', 'messages'] as const).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`text-xs px-3 py-1.5 border-b-2 transition-colors -mb-px ${
                  tab === t ? 'border-indigo-500 text-white' : 'border-transparent text-gray-500 hover:text-gray-300'
                }`}
              >
                {t === 'events' ? `Live Events (${events.length})` : `Messages (${messages.length})`}
              </button>
            ))}
          </div>

          {/* Event Stream */}
          <div className="flex-1 overflow-y-auto p-4 font-mono" style={{ minHeight: '300px', maxHeight: '55vh' }}>
            {!selectedExec ? (
              <div className="text-center py-12 text-gray-600 font-sans">
                <div className="text-3xl mb-3">📡</div>
                <p>Click an execution to start monitoring</p>
                <p className="text-xs mt-1 text-gray-700">WebSocket connects to execution stream</p>
              </div>
            ) : tab === 'events' ? (
              events.length === 0 ? (
                <div className="text-center py-8 text-gray-600 font-sans text-sm">
                  {wsStatus === 'connecting' ? 'Connecting...' : 'Waiting for events...'}
                </div>
              ) : (
                <>
                  {events.map((ev) => (
                    <EventRow key={ev._seq} event={ev} />
                  ))}
                  <div ref={eventsEndRef} />
                </>
              )
            ) : (
              messages.length === 0 ? (
                <div className="text-center py-8 text-gray-600 font-sans text-sm">No messages yet</div>
              ) : (
                <div className="space-y-3 font-sans">
                  {messages.map((msg) => (
                    <div key={msg.id} className={`p-3 rounded-lg text-sm ${
                      msg.sender_type === 'user' ? 'bg-indigo-950/40 border border-indigo-900' :
                      msg.sender_type === 'agent' ? 'bg-gray-800 border border-gray-700' :
                      'bg-gray-850 border border-gray-800'
                    }`}>
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className={`text-xs font-semibold ${
                          msg.sender_type === 'agent' ? 'text-emerald-400' :
                          msg.sender_type === 'user' ? 'text-indigo-400' : 'text-gray-500'
                        }`}>
                          {msg.sender_type === 'agent' ? '🤖' : msg.sender_type === 'user' ? '👤' : '⚙️'} {msg.sender_name}
                        </span>
                        {msg.metadata?.tokens && (
                          <span className="text-[10px] text-gray-600">[{msg.metadata.tokens} tokens]</span>
                        )}
                        <span className="ml-auto text-[10px] text-gray-700">
                          {new Date(msg.created_at).toLocaleTimeString()}
                        </span>
                      </div>
                      <p className="text-gray-300 leading-relaxed text-xs whitespace-pre-wrap">
                        {msg.content}
                      </p>
                    </div>
                  ))}
                </div>
              )
            )}
          </div>

          {/* Output Panel */}
          {selectedExec?.output_message && (
            <div className="border-t border-gray-800 p-4">
              <div className="text-xs text-gray-500 mb-1.5 font-semibold uppercase tracking-wide">Final Output</div>
              <div className="bg-gray-800 rounded-lg p-3 text-sm text-gray-300 max-h-32 overflow-y-auto leading-relaxed whitespace-pre-wrap font-sans">
                {selectedExec.output_message}
              </div>
              <div className="flex gap-4 mt-2 text-xs text-gray-600">
                <span>Tokens: {selectedExec.total_tokens.toLocaleString()}</span>
                <span>Cost: ${selectedExec.estimated_cost.toFixed(6)}</span>
                <span>Trigger: {selectedExec.trigger_type}</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
