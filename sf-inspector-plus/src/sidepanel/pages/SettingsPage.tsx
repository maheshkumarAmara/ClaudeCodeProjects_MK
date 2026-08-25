import { useStore } from '@/store';
import { clearCache } from '@/services/cache';

export function SettingsPage() {
  const session = useStore((s) => s.session);
  const addToast = useStore((s) => s.addToast);

  const handleClearCache = async () => {
    await clearCache(session?.orgId);
    addToast({ message: 'Cache cleared', type: 'success' });
  };

  return (
    <div className="settings-area">
      <h2>Options</h2>

      <div className="settings-section">
        <h3>Connection</h3>
        {session ? (
          <div style={{ fontSize: '0.8125rem' }}>
            <div style={{ marginBottom: 4 }}>
              <span style={{ color: '#706e6b' }}>Instance:</span>{' '}
              {session.instanceUrl}
            </div>
            <div style={{ marginBottom: 4 }}>
              <span style={{ color: '#706e6b' }}>Org ID:</span>{' '}
              {session.orgId}
            </div>
            <div>
              <span style={{ color: '#706e6b' }}>API Version:</span>{' '}
              v{session.apiVersion}
            </div>
          </div>
        ) : (
          <p style={{ color: '#8c8c8c', fontStyle: 'italic' }}>
            Not connected. Navigate to a Salesforce page to connect.
          </p>
        )}
      </div>

      <div className="settings-section">
        <h3>Cache</h3>
        <button onClick={handleClearCache}>Clear Cache</button>
        <p style={{ fontSize: '0.75rem', color: '#706e6b', marginTop: 4 }}>
          Clears cached object descriptions and metadata for the current org.
        </p>
      </div>

      <div className="settings-section">
        <h3>About</h3>
        <p style={{ fontSize: '0.8125rem' }}>SF Inspector Plus v0.1.0</p>
        <p style={{ fontSize: '0.75rem', color: '#706e6b', marginTop: 2 }}>
          Companion extension for Salesforce Inspector
        </p>
      </div>
    </div>
  );
}
