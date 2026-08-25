import { useState, useCallback, useEffect } from 'react';
import { useStore } from '@/store';
import { describeGlobal, describeSObject } from '@/services/salesforce-api';
import { getCached, setCache, CACHE_TTL } from '@/services/cache';

export function MetadataBrowserPage() {
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<'all' | 'standard' | 'custom'>('all');
  const [selectedFields, setSelectedFields] = useState<Set<string>>(new Set());
  const objectList = useStore((s) => s.objectList);
  const setObjectList = useStore((s) => s.setObjectList);
  const selectedObject = useStore((s) => s.selectedObject);
  const setSelectedObject = useStore((s) => s.setSelectedObject);
  const selectedObjectDescribe = useStore((s) => s.selectedObjectDescribe);
  const setSelectedObjectDescribe = useStore((s) => s.setSelectedObjectDescribe);
  const metadataLoading = useStore((s) => s.metadataLoading);
  const setMetadataLoading = useStore((s) => s.setMetadataLoading);
  const metadataError = useStore((s) => s.metadataError);
  const setMetadataError = useStore((s) => s.setMetadataError);
  const session = useStore((s) => s.session);
  const setCurrentSoql = useStore((s) => s.setCurrentSoql);
  const setActiveTab = useStore((s) => s.setActiveTab);

  useEffect(() => {
    if (objectList.length === 0 && session) {
      loadObjects();
    }
  }, [session]);

  const loadObjects = useCallback(async () => {
    if (!session) return;
    setMetadataLoading(true);
    setMetadataError(null);

    try {
      const cached = await getCached<typeof objectList>('global-describe', session.orgId);
      if (cached) {
        setObjectList(cached);
        setMetadataLoading(false);
        return;
      }

      const result = await describeGlobal();
      const queryable = result.sobjects.filter((o) => o.queryable);
      setObjectList(queryable);
      await setCache('global-describe', session.orgId, queryable, CACHE_TTL.GLOBAL_DESCRIBE);
    } catch (err) {
      setMetadataError(err instanceof Error ? err.message : 'Failed to load objects');
    } finally {
      setMetadataLoading(false);
    }
  }, [session, setObjectList, setMetadataLoading, setMetadataError]);

  const toggleField = useCallback((fieldName: string) => {
    setSelectedFields((prev) => {
      const next = new Set(prev);
      if (next.has(fieldName)) next.delete(fieldName);
      else next.add(fieldName);
      return next;
    });
  }, []);

  const selectObject = useCallback(
    async (objectName: string) => {
      if (!session) return;
      setSelectedObject(objectName);
      setSelectedFields(new Set());
      setMetadataLoading(true);

      try {
        const cached = await getCached<Awaited<ReturnType<typeof describeSObject>>>(
          `describe:${objectName}`,
          session.orgId
        );
        if (cached) {
          setSelectedObjectDescribe(cached);
          setMetadataLoading(false);
          return;
        }

        const describe = await describeSObject(objectName);
        setSelectedObjectDescribe(describe);
        await setCache(`describe:${objectName}`, session.orgId, describe, CACHE_TTL.OBJECT_DESCRIBE);
      } catch (err) {
        setMetadataError(err instanceof Error ? err.message : 'Failed to describe object');
      } finally {
        setMetadataLoading(false);
      }
    },
    [session, setSelectedObject, setSelectedObjectDescribe, setMetadataLoading, setMetadataError]
  );

  const openInSoql = useCallback(
    (objectName: string) => {
      const fields = selectedFields.size > 0
        ? Array.from(selectedFields).join(', ')
        : 'Id, Name';
      setCurrentSoql(`SELECT ${fields}\nFROM ${objectName}\nLIMIT 100`);
      setActiveTab('soql');
    },
    [setCurrentSoql, setActiveTab, selectedFields]
  );

  const filteredObjects = objectList.filter((obj) => {
    const matchesSearch =
      obj.name.toLowerCase().includes(search.toLowerCase()) ||
      obj.label.toLowerCase().includes(search.toLowerCase());
    const matchesFilter =
      filter === 'all' || (filter === 'custom' ? obj.custom : !obj.custom);
    return matchesSearch && matchesFilter;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: '1 1 0', overflow: 'hidden' }}>
      <div className="area">
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <input
            type="text"
            className="sf-input"
            placeholder="Search objects..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ flex: 1 }}
          />
          <div className="button-group">
            {(['all', 'standard', 'custom'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={filter === f ? 'highlighted' : ''}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
        </div>
        <span style={{ fontSize: '0.75rem', color: '#8c8c8c', fontStyle: 'italic' }}>
          {filteredObjects.length} objects
        </span>
      </div>

      {metadataError && <div className="error-message">{metadataError}</div>}

      <div style={{ display: 'flex', flex: '1 1 0', overflow: 'hidden' }}>
        {/* Object list */}
        <div className="metadata-object-list" style={{ width: '40%', borderRight: '1px solid #dddbda', overflow: 'auto' }}>
          {metadataLoading && !selectedObject && (
            <div style={{ padding: 12, color: '#8c8c8c', fontStyle: 'italic' }}>
              <span className="spinner" /> Loading objects...
            </div>
          )}
          {filteredObjects.map((obj) => (
            <button
              key={obj.name}
              onClick={() => selectObject(obj.name)}
              className={selectedObject === obj.name ? 'selected' : ''}
            >
              <div style={{ fontWeight: selectedObject === obj.name ? 700 : 400 }}>{obj.label}</div>
              <div style={{ fontSize: '0.75rem', color: '#706e6b' }}>{obj.name}</div>
            </button>
          ))}
        </div>

        {/* Field detail */}
        <div style={{ flex: 1, overflow: 'auto' }}>
          {selectedObjectDescribe ? (
            <>
              <div className="record-header">
                <div>
                  <h2>{selectedObjectDescribe.label}</h2>
                  <span className="record-meta">
                    {selectedObjectDescribe.name} &middot; {selectedObjectDescribe.fields.length} fields
                    {selectedFields.size > 0 && ` \u00b7 ${selectedFields.size} selected`}
                  </span>
                </div>
                <button onClick={() => openInSoql(selectedObjectDescribe.name)}>
                  Query{selectedFields.size > 0 ? ` (${selectedFields.size})` : ''}
                </button>
              </div>

              <table className="metadata-field-table">
                <thead>
                  <tr>
                    <th style={{ width: 30, textAlign: 'center' }}>
                      <input
                        type="checkbox"
                        checked={selectedFields.size > 0 && selectedFields.size === selectedObjectDescribe.fields.length}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedFields(new Set(selectedObjectDescribe.fields.map((f) => f.name)));
                          } else {
                            setSelectedFields(new Set());
                          }
                        }}
                        title="Select all / deselect all"
                      />
                    </th>
                    <th>Label</th>
                    <th>API Name</th>
                    <th>Type</th>
                    <th>Req</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedObjectDescribe.fields
                    .sort((a, b) => a.label.localeCompare(b.label))
                    .map((field) => (
                      <tr
                        key={field.name}
                        onClick={() => toggleField(field.name)}
                        style={{ cursor: 'pointer', background: selectedFields.has(field.name) ? '#e8f4fd' : undefined }}
                      >
                        <td style={{ textAlign: 'center' }}>
                          <input
                            type="checkbox"
                            checked={selectedFields.has(field.name)}
                            onChange={() => toggleField(field.name)}
                            onClick={(e) => e.stopPropagation()}
                          />
                        </td>
                        <td>{field.label}</td>
                        <td style={{ fontFamily: 'monospace', color: '#706e6b' }}>{field.name}</td>
                        <td><span className="type-badge">{field.type}</span></td>
                        <td style={{ textAlign: 'center' }}>{!field.nillable && field.createable ? '\u2713' : ''}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </>
          ) : (
            <div style={{ padding: 24, textAlign: 'center', color: '#8c8c8c', fontStyle: 'italic' }}>
              Select an object to view its fields
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
