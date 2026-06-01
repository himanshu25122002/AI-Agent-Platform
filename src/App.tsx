import { useState, useEffect } from 'react';
import AgentsTab from './components/AgentsTab';
import WorkflowsTab from './components/WorkflowsTab';
import MonitorTab from './components/MonitorTab';
import DashboardTab from './components/DashboardTab';
import { Tab } from './types';
import { healthApi } from './api';

const NAV_ITEMS: { id: Tab; label: string; icon: string }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: '📊' },
  { id: 'agents', label: 'Agents', icon: '🤖' },
  { id: 'workflows', label: 'Workflows', icon: '🔀' },
  { id: 'monitor', label: 'Monitor', icon: '📡' },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');
  const [backendStatus, setBackendStatus] = useState<'checking' | 'online' | 'offline'>('checking');

  useEffect(() => {
    const check = async () => {
      try {
        const result = await healthApi.check();
        setBackendStatus(result.status === 'unreachable' ? 'offline' : 'online');
      } catch {
        setBackendStatus('offline');
      }
    };
    check();
    const interval = setInterval(check, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">
      {/* ---- Top Navigation Bar ---- */}
      <header className="bg-gray-900 border-b border-gray-800 sticky top-0 z-50">
        <div className="max-w-screen-2xl mx-auto px-4 h-14 flex items-center justify-between">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center text-sm font-bold">
              Y
            </div>
            <div>
              <span className="font-semibold text-white text-sm">Yuno</span>
              <span className="text-gray-400 text-xs ml-1.5">Agent Platform</span>
            </div>
          </div>

          {/* Nav Tabs */}
          <nav className="flex items-center gap-1">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors flex items-center gap-1.5 ${
                  activeTab === item.id
                    ? 'bg-indigo-600 text-white'
                    : 'text-gray-400 hover:text-white hover:bg-gray-800'
                }`}
              >
                <span>{item.icon}</span>
                <span className="hidden sm:inline">{item.label}</span>
              </button>
            ))}
          </nav>

          {/* Status indicator */}
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${
              backendStatus === 'online' ? 'bg-emerald-400 animate-pulse' :
              backendStatus === 'offline' ? 'bg-red-400' : 'bg-yellow-400 animate-pulse'
            }`} />
            <span className="text-xs text-gray-400 hidden sm:inline">
              {backendStatus === 'online' ? 'Backend Online' :
               backendStatus === 'offline' ? 'Backend Offline' : 'Connecting...'}
            </span>
          </div>
        </div>
      </header>

      {/* ---- Offline Banner ---- */}
      {backendStatus === 'offline' && (
        <div className="bg-amber-900/50 border-b border-amber-700 px-4 py-2 text-center text-amber-300 text-xs">
          ⚠️ Backend not reachable at <code className="bg-amber-900/60 px-1 rounded">http://localhost:8000</code>.
          Start the FastAPI server to enable full functionality. UI runs in demo mode.
        </div>
      )}

      {/* ---- Main Content ---- */}
      <main className="flex-1 max-w-screen-2xl mx-auto w-full px-4 py-6">
        {activeTab === 'dashboard' && <DashboardTab onNavigate={setActiveTab} />}
        {activeTab === 'agents' && <AgentsTab />}
        {activeTab === 'workflows' && <WorkflowsTab />}
        {activeTab === 'monitor' && <MonitorTab />}
      </main>

      {/* ---- Footer ---- */}
      <footer className="border-t border-gray-800 bg-gray-900 py-3 px-4 text-center">
        <p className="text-gray-600 text-xs">
          Yuno AI Agent Orchestration Platform · LangGraph + FastAPI + React Flow
        </p>
      </footer>
    </div>
  );
}
