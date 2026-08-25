import { useEffect } from 'react';
import { useStore } from '@/store';
import type { ActiveTab } from '@/store/slices/ui-slice';
import type { Message } from '@/types/messages';
import { DataExportPage } from './pages/DataExportPage';
import { DataImportPage } from './pages/DataImportPage';
import { RecordInspectorPage } from './pages/RecordInspectorPage';
import { MetadataBrowserPage } from './pages/MetadataBrowserPage';
import { SettingsPage } from './pages/SettingsPage';

const TABS: { id: ActiveTab; label: string }[] = [
  { id: 'soql', label: 'Data Export' },
  { id: 'import', label: 'Data Import' },
  { id: 'record', label: 'Record' },
  { id: 'metadata', label: 'Metadata' },
  { id: 'settings', label: 'Options' },
];

export function App() {
  const activeTab = useStore((s) => s.activeTab);
  const setActiveTab = useStore((s) => s.setActiveTab);
  const session = useStore((s) => s.session);
  const isConnected = useStore((s) => s.isConnected);
  const setSession = useStore((s) => s.setSession);

  useEffect(() => {
    const requestSession = () => {
      chrome.runtime.sendMessage({ type: 'SESSION_REQUEST' }).then((response) => {
        if (response?.sid) {
          setSession(response);
        }
      }).catch(() => {
        // Service worker not ready, retry
        setTimeout(requestSession, 1000);
      });
    };

    requestSession();

    const listener = (message: Message) => {
      if (message.type === 'SESSION_EXTRACTED') {
        setSession(message.payload);
      } else if (message.type === 'PAGE_NAVIGATED' && message.payload.recordId) {
        setActiveTab('record');
      }
    };

    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, [setSession, setActiveTab]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="header-bar">
        <svg width="36" height="36" viewBox="0 0 100 100" style={{ flexShrink: 0 }}>
          <g transform="translate(50,50)">
            {/* Center diamond */}
            <polygon points="0,-6 6,0 0,6 -6,0" fill="#00B4AE" />
            {/* Cardinal – 4 large diamonds (N, E, S, W) */}
            <polygon points="0,-9 7,0 0,9 -7,0" transform="translate(0,-24)" fill="#2A9D8F" />
            <polygon points="0,-9 7,0 0,9 -7,0" transform="translate(24,0)" fill="#00A7B5" />
            <polygon points="0,-9 7,0 0,9 -7,0" transform="translate(0,24)" fill="#0096C7" />
            <polygon points="0,-9 7,0 0,9 -7,0" transform="translate(-24,0)" fill="#339E90" />
            {/* Diagonal – 4 medium diamonds (NE, SE, SW, NW) */}
            <polygon points="0,-7 5.5,0 0,7 -5.5,0" transform="translate(17,-17)" fill="#45C4A8" />
            <polygon points="0,-7 5.5,0 0,7 -5.5,0" transform="translate(17,17)" fill="#00B0CC" />
            <polygon points="0,-7 5.5,0 0,7 -5.5,0" transform="translate(-17,17)" fill="#00A3C4" />
            <polygon points="0,-7 5.5,0 0,7 -5.5,0" transform="translate(-17,-17)" fill="#3BBD9E" />
            {/* Inner ring – 8 small diamonds between center and outer */}
            <polygon points="0,-5 4,0 0,5 -4,0" transform="translate(0,-13)" fill="#3CB8A0" />
            <polygon points="0,-5 4,0 0,5 -4,0" transform="translate(9,-9)" fill="#36BDB0" />
            <polygon points="0,-5 4,0 0,5 -4,0" transform="translate(13,0)" fill="#00B4BE" />
            <polygon points="0,-5 4,0 0,5 -4,0" transform="translate(9,9)" fill="#00ABCA" />
            <polygon points="0,-5 4,0 0,5 -4,0" transform="translate(0,13)" fill="#009EC8" />
            <polygon points="0,-5 4,0 0,5 -4,0" transform="translate(-9,9)" fill="#00A5BE" />
            <polygon points="0,-5 4,0 0,5 -4,0" transform="translate(-13,0)" fill="#2DB5A0" />
            <polygon points="0,-5 4,0 0,5 -4,0" transform="translate(-9,-9)" fill="#38B89A" />
          </g>
        </svg>
        <span style={{ fontSize: '1.25rem', fontWeight: 400, color: '#6D6E71', letterSpacing: '0.5px', marginLeft: 4 }}>rubrik</span>
        <h1>SF Inspector</h1>
        {isConnected && session && (
          <span className="org-info">
            {new URL(session.instanceUrl).hostname}
          </span>
        )}
        <div className="flex-right">
          <span style={{ fontSize: '0.75rem', color: '#706e6b' }}>
            {isConnected ? `API v${session?.apiVersion}` : ''}
          </span>
        </div>
      </div>

      <div className="tab-nav">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={activeTab === tab.id ? 'active' : ''}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div style={{ flex: '1 1 0', overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
        {activeTab === 'soql' && <DataExportPage />}
        {activeTab === 'import' && <DataImportPage />}
        {activeTab === 'record' && <RecordInspectorPage />}
        {activeTab === 'metadata' && <MetadataBrowserPage />}
        {activeTab === 'settings' && <SettingsPage />}
      </div>

      <div className="status-bar">
        <span className={`status-indicator ${isConnected ? 'connected' : 'disconnected'}`} />
        <span>
          {isConnected && session
            ? `Connected to ${new URL(session.instanceUrl).hostname}`
            : 'Not connected \u2014 navigate to a Salesforce page'}
        </span>
      </div>
    </div>
  );
}
