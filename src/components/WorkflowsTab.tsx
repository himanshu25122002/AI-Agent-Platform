import { useState, useEffect, useCallback } from 'react';
import ReactFlow, {
  addEdge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  Connection,
  Node,
  Edge,
  Handle,
  Position,
  NodeProps,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { workflowsApi, agentsApi } from '../api';
import { Workflow, Agent, NODE_TYPES_CONFIG } from '../types';

// ---- Custom Node Components --------------------------------

function AgentNodeComponent({ data, selected }: NodeProps) {
  return (
    <div className={`bg-gray-900 border-2 rounded-xl px-3 py-2.5 min-w-[140px] shadow-lg ${
      selected ? 'border-indigo-500' : 'border-blue-700/60'
    }`}>
      <Handle type="target" position={Position.Left} className="!bg-blue-500 !w-2.5 !h-2.5" />
      <div className="flex items-center gap-2">
        <div className="w-6 h-6 rounded-md bg-gradient-to-br from-blue-600 to-indigo-600 flex items-center justify-center text-xs">🤖</div>
        <div>
          <div className="text-xs font-semibold text-white">{data.label}</div>
          <div className="text-[10px] text-blue-400">Agent</div>
        </div>
      </div>
      {data.agent_id && (
        <div className="mt-1.5 text-[10px] text-gray-500 truncate max-w-[120px]">
          {data.agentName || 'Agent configured'}
        </div>
      )}
      <Handle type="source" position={Position.Right} className="!bg-blue-500 !w-2.5 !h-2.5" />
    </div>
  );
}

function TriggerNodeComponent({ data, selected }: NodeProps) {
  return (
    <div className={`bg-gray-900 border-2 rounded-xl px-3 py-2.5 min-w-[120px] shadow-lg ${
      selected ? 'border-indigo-500' : 'border-indigo-700/60'
    }`}>
      <div className="flex items-center gap-2">
        <div className="w-6 h-6 rounded-md bg-gradient-to-br from-indigo-600 to-violet-600 flex items-center justify-center text-xs">⚡</div>
        <div>
          <div className="text-xs font-semibold text-white">{data.label}</div>
          <div className="text-[10px] text-indigo-400">Trigger</div>
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-indigo-500 !w-2.5 !h-2.5" />
    </div>
  );
}

function DecisionNodeComponent({ data, selected }: NodeProps) {
  return (
    <div className={`bg-gray-900 border-2 rounded-xl px-3 py-2.5 min-w-[130px] shadow-lg ${
      selected ? 'border-indigo-500' : 'border-yellow-700/60'
    }`}>
      <Handle type="target" position={Position.Left} className="!bg-yellow-500 !w-2.5 !h-2.5" />
      <div className="flex items-center gap-2">
        <div className="w-6 h-6 rounded-md bg-gradient-to-br from-yellow-600 to-orange-600 flex items-center justify-center text-xs">⚖️</div>
        <div>
          <div className="text-xs font-semibold text-white">{data.label}</div>
          <div className="text-[10px] text-yellow-400">Decision</div>
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-yellow-500 !w-2.5 !h-2.5" />
    </div>
  );
}

function HumanApprovalNodeComponent({ data, selected }: NodeProps) {
  return (
    <div className={`bg-gray-900 border-2 rounded-xl px-3 py-2.5 min-w-[140px] shadow-lg ${
      selected ? 'border-indigo-500' : 'border-violet-700/60'
    }`}>
      <Handle type="target" position={Position.Left} className="!bg-violet-500 !w-2.5 !h-2.5" />
      <div className="flex items-center gap-2">
        <div className="w-6 h-6 rounded-md bg-gradient-to-br from-violet-600 to-purple-600 flex items-center justify-center text-xs">👤</div>
        <div>
          <div className="text-xs font-semibold text-white">{data.label}</div>
          <div className="text-[10px] text-violet-400">Human Approval</div>
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-violet-500 !w-2.5 !h-2.5" />
    </div>
  );
}

function DelayNodeComponent({ data, selected }: NodeProps) {
  return (
    <div className={`bg-gray-900 border-2 rounded-xl px-3 py-2.5 min-w-[120px] shadow-lg ${
      selected ? 'border-indigo-500' : 'border-gray-600'
    }`}>
      <Handle type="target" position={Position.Left} className="!bg-gray-500 !w-2.5 !h-2.5" />
      <div className="flex items-center gap-2">
        <div className="w-6 h-6 rounded-md bg-gradient-to-br from-gray-600 to-slate-600 flex items-center justify-center text-xs">⏱️</div>
        <div>
          <div className="text-xs font-semibold text-white">{data.label}</div>
          <div className="text-[10px] text-gray-400">Delay</div>
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-gray-500 !w-2.5 !h-2.5" />
    </div>
  );
}

const nodeTypes = {
  agentNode: AgentNodeComponent,
  triggerNode: TriggerNodeComponent,
  decisionNode: DecisionNodeComponent,
  humanApprovalNode: HumanApprovalNodeComponent,
  delayNode: DelayNodeComponent,
};

const NODE_TYPE_MAP: Record<string, string> = {
  agent: 'agentNode',
  trigger: 'triggerNode',
  decision: 'decisionNode',
  human_approval: 'humanApprovalNode',
  delay: 'delayNode',
};

// ---- Main Component ----------------------------------------

export default function WorkflowsTab() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selected, setSelected] = useState<Workflow | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [execResult, setExecResult] = useState<string>('');
  const [inputMessage, setInputMessage] = useState('');
  const [showInput, setShowInput] = useState(false);
  const [newNodeType, setNewNodeType] = useState('agent');
  const [newNodeAgent, setNewNodeAgent] = useState('');
  const [error, setError] = useState('');
  const [mode, setMode] = useState<'list' | 'builder'>('list');

  const load = async () => {
    try {
      const [wf, ag] = await Promise.all([workflowsApi.list(), agentsApi.list()]);
      setWorkflows(wf);
      setAgents(ag);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const openWorkflow = (wf: Workflow) => {
    setSelected(wf);
    const agentMap = Object.fromEntries(agents.map(a => [a.id, a.name]));
    const rfNodes: Node[] = wf.nodes.map((n) => ({
      id: n.id,
      type: NODE_TYPE_MAP[n.data.node_type] || 'agentNode',
      position: n.position,
      data: { ...n.data, agentName: n.data.agent_id ? agentMap[n.data.agent_id] : undefined },
    }));
    const rfEdges: Edge[] = wf.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.label,
      animated: true,
      style: { stroke: '#6366f1' },
    }));
    setNodes(rfNodes);
    setEdges(rfEdges);
    setMode('builder');
    setExecResult('');
  };

  const onConnect = useCallback((params: Connection) => {
    setEdges((eds) => addEdge({
      ...params,
      animated: true,
      style: { stroke: '#6366f1' },
    }, eds));
  }, [setEdges]);

  const addNode = () => {
    const agent = agents.find(a => a.id === newNodeAgent);
    const nodeTypeLabel = NODE_TYPES_CONFIG.find(n => n.type === newNodeType)?.label || newNodeType;
    const id = `${newNodeType}-${Date.now()}`;
    const newNode: Node = {
      id,
      type: NODE_TYPE_MAP[newNodeType] || 'agentNode',
      position: { x: 100 + nodes.length * 220, y: 200 },
      data: {
        label: agent?.name || nodeTypeLabel,
        node_type: newNodeType,
        agent_id: newNodeAgent || undefined,
        agentName: agent?.name,
      },
    };
    setNodes((ns) => [...ns, newNode]);
  };

  const saveWorkflow = async () => {
    if (!selected) return;
    setSaving(true);
    setError('');
    try {
      const saveNodes = nodes.map((n) => ({
        id: n.id,
        type: n.type,
        position: n.position,
        data: {
          label: n.data.label,
          node_type: n.data.node_type,
          agent_id: n.data.agent_id,
          config: n.data.config || {},
        },
      }));
      const saveEdges = edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        label: typeof e.label === 'string' ? e.label : undefined,
      }));
      await workflowsApi.update(selected.id, { nodes: saveNodes, edges: saveEdges });
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const executeWorkflow = async () => {
    if (!selected || !inputMessage.trim()) return;
    setExecuting(true);
    setExecResult('');
    setError('');
    try {
      const result = await workflowsApi.execute(selected.id, inputMessage.trim());
      setExecResult(
        `✅ Execution started!\nID: ${result.execution_id}\nConnect WebSocket: ${result.websocket_url}\nSwitch to Monitor tab to watch real-time.`
      );
      setShowInput(false);
      setInputMessage('');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Execution failed');
    } finally {
      setExecuting(false);
    }
  };

  const createNewWorkflow = async () => {
    const name = prompt('Workflow name:');
    if (!name?.trim()) return;
    try {
      const wf = await workflowsApi.create({ name: name.trim(), description: '', nodes: [], edges: [] });
      await load();
      openWorkflow(wf);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create');
    }
  };

  if (mode === 'builder' && selected) {
    return (
      <div className="flex flex-col" style={{ height: 'calc(100vh - 120px)' }}>
        {/* Builder Header */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-3 mb-3 flex items-center gap-3 flex-wrap">
          <button
            onClick={() => setMode('list')}
            className="text-gray-400 hover:text-white text-sm px-2 py-1 rounded hover:bg-gray-800 transition-colors"
          >
            ← Back
          </button>
          <div className="flex-1">
            <span className="text-sm font-semibold text-white">{selected.name}</span>
            {selected.is_template && <span className="ml-2 text-xs bg-indigo-900/50 text-indigo-300 px-1.5 py-0.5 rounded">Template</span>}
          </div>

          {/* Add Node */}
          <div className="flex items-center gap-2">
            <select
              className="bg-gray-800 border border-gray-700 text-xs text-gray-300 rounded px-2 py-1"
              value={newNodeType}
              onChange={(e) => { setNewNodeType(e.target.value); setNewNodeAgent(''); }}
            >
              {NODE_TYPES_CONFIG.map(n => <option key={n.type} value={n.type}>{n.label}</option>)}
            </select>
            {newNodeType === 'agent' && (
              <select
                className="bg-gray-800 border border-gray-700 text-xs text-gray-300 rounded px-2 py-1 max-w-[140px]"
                value={newNodeAgent}
                onChange={(e) => setNewNodeAgent(e.target.value)}
              >
                <option value="">Select Agent</option>
                {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            )}
            <button
              onClick={addNode}
              className="text-xs px-2.5 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded border border-gray-700 transition-colors"
            >
              + Add Node
            </button>
          </div>

          <button
            onClick={saveWorkflow}
            disabled={saving}
            className="text-xs px-3 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded disabled:opacity-50 transition-colors"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
          <button
            onClick={() => setShowInput(true)}
            className="text-xs px-3 py-1 bg-emerald-700 hover:bg-emerald-600 text-white rounded transition-colors"
          >
            ▶ Run
          </button>
        </div>

        {error && (
          <div className="bg-red-950/50 border border-red-700 rounded-lg p-2 text-red-300 text-xs mb-2">{error}</div>
        )}
        {execResult && (
          <div className="bg-emerald-950/50 border border-emerald-700 rounded-lg p-2 text-emerald-300 text-xs mb-2 whitespace-pre-line">{execResult}</div>
        )}

        {/* React Flow Canvas */}
        <div className="flex-1 bg-gray-950 rounded-xl border border-gray-800 overflow-hidden">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            nodeTypes={nodeTypes}
            fitView
            className="bg-gray-950"
            defaultEdgeOptions={{ animated: true, style: { stroke: '#4f46e5' } }}
          >
            <Background color="#374151" gap={20} />
            <Controls className="!bg-gray-900 !border-gray-700" />
            <MiniMap
              className="!bg-gray-900 !border-gray-700"
              nodeStrokeColor="#6366f1"
              nodeColor="#1f2937"
              maskColor="rgba(0,0,0,0.5)"
            />
          </ReactFlow>
        </div>

        {/* Tip */}
        <p className="text-xs text-gray-600 mt-2 text-center">
          Drag nodes to reposition · Click handles to connect · Delete key to remove selected
        </p>

        {/* Execute Modal */}
        {showInput && (
          <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4">
            <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-md p-5 space-y-4">
              <h2 className="font-semibold text-white">Run Workflow: {selected.name}</h2>
              <textarea
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500 resize-none"
                rows={4}
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                placeholder="Enter your message or task for the agents..."
              />
              <div className="flex gap-2">
                <button
                  onClick={() => setShowInput(false)}
                  className="flex-1 py-2 rounded-lg text-sm text-gray-400 hover:text-white bg-gray-800 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={executeWorkflow}
                  disabled={executing || !inputMessage.trim()}
                  className="flex-1 py-2 rounded-lg text-sm bg-indigo-600 hover:bg-indigo-500 text-white font-medium disabled:opacity-50 transition-colors"
                >
                  {executing ? 'Starting...' : '▶ Execute'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Workflows</h1>
          <p className="text-gray-400 text-sm mt-0.5">Visual workflow builder — drag, connect, execute</p>
        </div>
        <button
          onClick={createNewWorkflow}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors"
        >
          + New Workflow
        </button>
      </div>

      {error && (
        <div className="bg-red-950/50 border border-red-700 rounded-lg p-3 text-red-300 text-sm">{error}</div>
      )}

      {loading ? (
        <div className="text-center py-12 text-gray-600">Loading workflows...</div>
      ) : workflows.length === 0 ? (
        <div className="text-center py-12 bg-gray-900 border border-gray-800 rounded-xl">
          <div className="text-4xl mb-3">🔀</div>
          <p className="text-gray-400 font-medium">No workflows yet</p>
          <p className="text-gray-600 text-sm mt-1">Templates seed automatically on backend startup</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {workflows.map((wf) => (
            <div
              key={wf.id}
              className="bg-gray-900 border border-gray-800 hover:border-gray-700 rounded-xl p-4 flex flex-col gap-3 cursor-pointer transition-colors"
              onClick={() => openWorkflow(wf)}
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-white">{wf.name}</span>
                    {wf.is_template && (
                      <span className="text-xs bg-indigo-900/50 text-indigo-300 px-1.5 py-0.5 rounded">Template</span>
                    )}
                  </div>
                  {wf.description && (
                    <p className="text-xs text-gray-500 mt-1 line-clamp-2">{wf.description}</p>
                  )}
                </div>
                <span className="text-2xl ml-2">
                  {wf.template_type === 'research' ? '🔬' : wf.template_type === 'content' ? '✍️' : '🔀'}
                </span>
              </div>

              {/* Flow preview */}
              <div className="flex items-center gap-1 flex-wrap">
                {wf.nodes.slice(0, 5).map((n, i) => (
                  <span key={n.id} className="flex items-center gap-1">
                    {i > 0 && <span className="text-gray-700">→</span>}
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      n.data.node_type === 'trigger' ? 'bg-indigo-900/50 text-indigo-300' :
                      n.data.node_type === 'agent' ? 'bg-blue-900/50 text-blue-300' :
                      n.data.node_type === 'human_approval' ? 'bg-violet-900/50 text-violet-300' :
                      'bg-gray-800 text-gray-400'
                    }`}>
                      {n.data.label}
                    </span>
                  </span>
                ))}
                {wf.nodes.length > 5 && <span className="text-xs text-gray-600">+{wf.nodes.length - 5}</span>}
              </div>

              <div className="flex items-center gap-3 text-xs text-gray-600 border-t border-gray-800 pt-2">
                <span>{wf.nodes.length} nodes</span>
                <span>{wf.edges.length} edges</span>
                <span className="ml-auto text-indigo-400">Open →</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
