import { useCallback, useEffect, useRef, useState } from 'react';
import { useStore } from '@/store';

interface QueryHistoryProps {
  onSelect: (soql: string) => void;
}

export function QueryHistory({ onSelect }: QueryHistoryProps) {
  const queryHistory = useStore((s) => s.queryHistory);
  const toggleHistoryStarred = useStore((s) => s.toggleHistoryStarred);
  const session = useStore((s) => s.session);
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<'all' | 'starred'>('all');
  const panelRef = useRef<HTMLDivElement>(null);

  const orgHistory = session
    ? queryHistory
        .map((h, i) => ({ ...h, originalIndex: i }))
        .filter((h) => h.orgId === session.orgId)
    : queryHistory.map((h, i) => ({ ...h, originalIndex: i }));

  const filtered =
    filter === 'starred'
      ? orgHistory.filter((h) => h.starred)
      : orgHistory;

  const sorted = [...filtered].sort((a, b) => {
    if (a.starred && !b.starred) return -1;
    if (!a.starred && b.starred) return 1;
    return 0;
  });

  const starredCount = orgHistory.filter((h) => h.starred).length;

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  const formatTime = (ts: number) => {
    const d = new Date(ts);
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const handleSelect = useCallback(
    (soql: string) => {
      onSelect(soql);
      setOpen(false);
    },
    [onSelect]
  );

  const handleToggleStar = useCallback(
    (e: React.MouseEvent, originalIndex: number) => {
      e.stopPropagation();
      toggleHistoryStarred(originalIndex);
    },
    [toggleHistoryStarred]
  );

  if (orgHistory.length === 0) return null;

  return (
    <div style={{ position: 'relative' }} ref={panelRef}>
      <button onClick={() => setOpen(!open)} className={open ? 'active' : ''}>
        History ({orgHistory.length})
      </button>

      {open && (
        <div className="dropdown-panel" style={{ right: 0, minWidth: 340 }}>
          <div className="dropdown-filter-bar">
            <button
              className={`filter-pill ${filter === 'all' ? 'active' : ''}`}
              onClick={() => setFilter('all')}
            >
              All
            </button>
            <button
              className={`filter-pill ${filter === 'starred' ? 'active' : ''}`}
              onClick={() => setFilter('starred')}
            >
              Starred ({starredCount})
            </button>
          </div>

          <div className="dropdown-list">
            {sorted.length === 0 ? (
              <div className="dropdown-empty">
                {filter === 'starred' ? 'No starred queries' : 'No history yet'}
              </div>
            ) : (
              sorted.map((entry) => (
                <div
                  key={entry.originalIndex}
                  className="dropdown-item"
                  onClick={() => handleSelect(entry.soql)}
                >
                  <button
                    className="star-btn"
                    onClick={(e) => handleToggleStar(e, entry.originalIndex)}
                    title={entry.starred ? 'Unstar' : 'Star'}
                  >
                    {entry.starred ? '\u2605' : '\u2606'}
                  </button>
                  <div className="dropdown-item-content">
                    <span className="dropdown-item-meta">
                      {formatTime(entry.timestamp)} ({entry.rowCount})
                    </span>
                    <span className="dropdown-item-soql">
                      {entry.soql.length > 80
                        ? entry.soql.substring(0, 80) + '...'
                        : entry.soql}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
