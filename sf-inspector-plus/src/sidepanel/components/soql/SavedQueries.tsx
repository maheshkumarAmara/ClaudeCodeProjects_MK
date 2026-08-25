import { useCallback, useEffect, useRef, useState } from 'react';
import { useStore } from '@/store';

interface SavedQueriesProps {
  onSelect: (soql: string) => void;
}

export function SavedQueries({ onSelect }: SavedQueriesProps) {
  const savedQueries = useStore((s) => s.savedQueries);
  const deleteSavedQuery = useStore((s) => s.deleteSavedQuery);
  const session = useStore((s) => s.session);
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const orgQueries = session
    ? savedQueries.filter((q) => q.orgId === session.orgId)
    : savedQueries;

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

  const handleSelect = useCallback(
    (soql: string) => {
      onSelect(soql);
      setOpen(false);
    },
    [onSelect]
  );

  const handleDelete = useCallback(
    (e: React.MouseEvent, id: string) => {
      e.stopPropagation();
      deleteSavedQuery(id);
    },
    [deleteSavedQuery]
  );

  return (
    <div style={{ position: 'relative' }} ref={panelRef}>
      <button onClick={() => setOpen(!open)} className={open ? 'active' : ''}>
        Saved ({orgQueries.length})
      </button>

      {open && (
        <div className="dropdown-panel" style={{ right: 0, minWidth: 300 }}>
          <div className="dropdown-list">
            {orgQueries.length === 0 ? (
              <div className="dropdown-empty">No saved queries yet</div>
            ) : (
              orgQueries.map((q) => (
                <div
                  key={q.id}
                  className="dropdown-item"
                  onClick={() => handleSelect(q.soql)}
                >
                  <div className="dropdown-item-content">
                    <span className="saved-query-name">{q.name}</span>
                    <span className="dropdown-item-soql">
                      {q.soql.length > 70
                        ? q.soql.substring(0, 70) + '...'
                        : q.soql}
                    </span>
                  </div>
                  <button
                    className="delete-btn"
                    onClick={(e) => handleDelete(e, q.id)}
                    title="Delete saved query"
                  >
                    &times;
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
