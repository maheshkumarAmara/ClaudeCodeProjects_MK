import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { useStore } from '@/store';
import { describeSObject, getRecord, updateRecord } from '@/services/salesforce-api';
import type { Message } from '@/types/messages';

export function RecordInspectorPage() {
  const [recordIdInput, setRecordIdInput] = useState('');
  const [objectNameInput, setObjectNameInput] = useState('');
  const [fieldFilter, setFieldFilter] = useState('');
  const [showObjectDropdown, setShowObjectDropdown] = useState(false);
  const [objectSelectedIndex, setObjectSelectedIndex] = useState(0);
  const objectInputRef = useRef<HTMLInputElement>(null);
  const currentRecord = useStore((s) => s.currentRecord);
  const objectDescribe = useStore((s) => s.objectDescribe);
  const editedFields = useStore((s) => s.editedFields);
  const isEditing = useStore((s) => s.isEditing);
  const isLoading = useStore((s) => s.isLoading);
  const recordError = useStore((s) => s.recordError);
  const setCurrentRecord = useStore((s) => s.setCurrentRecord);
  const setObjectDescribe = useStore((s) => s.setObjectDescribe);
  const setEditedField = useStore((s) => s.setEditedField);
  const setIsEditing = useStore((s) => s.setIsEditing);
  const setIsLoading = useStore((s) => s.setIsLoading);
  const setRecordError = useStore((s) => s.setRecordError);
  const resetEdits = useStore((s) => s.resetEdits);
  const addToast = useStore((s) => s.addToast);
  const objectList = useStore((s) => s.objectList);

  const filteredObjects = useMemo(() => {
    if (!objectNameInput.trim() || !showObjectDropdown) return [];
    const q = objectNameInput.toLowerCase();
    return objectList
      .filter((o) => o.name.toLowerCase().includes(q) || o.label.toLowerCase().includes(q))
      .slice(0, 20);
  }, [objectNameInput, objectList, showObjectDropdown]);

  useEffect(() => {
    const listener = (message: Message) => {
      if (message.type === 'PAGE_NAVIGATED' && message.payload.recordId && message.payload.objectName) {
        setRecordIdInput(message.payload.recordId);
        setObjectNameInput(message.payload.objectName);
        loadRecord(message.payload.objectName, message.payload.recordId);
      }
    };
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, []);

  const loadRecord = useCallback(
    async (objName: string, recId: string) => {
      if (!objName || !recId) return;
      setIsLoading(true);
      setRecordError(null);
      resetEdits();

      try {
        const describe = await describeSObject(objName);
        setObjectDescribe(describe);
        const fields = describe.fields.map((f) => f.name);
        const record = await getRecord(objName, recId, fields);
        setCurrentRecord(record);
      } catch (err) {
        setRecordError(err instanceof Error ? err.message : 'Failed to load record');
      } finally {
        setIsLoading(false);
      }
    },
    [setIsLoading, setRecordError, resetEdits, setObjectDescribe, setCurrentRecord]
  );

  const handleSave = useCallback(async () => {
    if (!currentRecord || !objectDescribe || Object.keys(editedFields).length === 0) return;
    setIsLoading(true);
    try {
      await updateRecord(objectDescribe.name, currentRecord.Id, editedFields);
      addToast({ message: 'Record saved', type: 'success' });
      await loadRecord(objectDescribe.name, currentRecord.Id);
    } catch (err) {
      setRecordError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setIsLoading(false);
    }
  }, [currentRecord, objectDescribe, editedFields, setIsLoading, setRecordError, addToast, loadRecord]);

  const handleLoad = () => {
    if (objectNameInput && recordIdInput) {
      loadRecord(objectNameInput, recordIdInput);
    }
  };

  const selectObjectFromDropdown = useCallback((name: string) => {
    setObjectNameInput(name);
    setShowObjectDropdown(false);
  }, []);

  const handleObjectKeyDown = (e: React.KeyboardEvent) => {
    if (showObjectDropdown && filteredObjects.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setObjectSelectedIndex((i) => Math.min(i + 1, filteredObjects.length - 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setObjectSelectedIndex((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        selectObjectFromDropdown(filteredObjects[objectSelectedIndex].name);
        return;
      }
      if (e.key === 'Escape') {
        setShowObjectDropdown(false);
        return;
      }
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      handleLoad();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleLoad();
    }
  };

  const filteredFields = objectDescribe?.fields
    .filter((f) => f.name !== 'attributes')
    .filter((f) =>
      !fieldFilter ||
      f.label.toLowerCase().includes(fieldFilter.toLowerCase()) ||
      f.name.toLowerCase().includes(fieldFilter.toLowerCase())
    )
    .sort((a, b) => a.label.localeCompare(b.label));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: '1 1 0', overflow: 'hidden' }}>
      <div className="area">
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <div style={{ flex: 1, position: 'relative' }}>
            <input
              ref={objectInputRef}
              type="text"
              className="sf-input"
              placeholder="Object (e.g. Account)"
              value={objectNameInput}
              onChange={(e) => {
                setObjectNameInput(e.target.value);
                setShowObjectDropdown(true);
                setObjectSelectedIndex(0);
              }}
              onKeyDown={handleObjectKeyDown}
              onFocus={() => { if (objectNameInput.trim()) setShowObjectDropdown(true); }}
              onBlur={() => setTimeout(() => setShowObjectDropdown(false), 150)}
              style={{ width: '100%' }}
              autoComplete="off"
            />
            {showObjectDropdown && filteredObjects.length > 0 && (
              <div className="autocomplete-dropdown" style={{ top: '100%', left: 0, right: 0, marginTop: 2 }}>
                {filteredObjects.map((obj, i) => (
                  <div
                    key={obj.name}
                    className={`autocomplete-item${i === objectSelectedIndex ? ' selected' : ''}`}
                    onMouseDown={() => selectObjectFromDropdown(obj.name)}
                    onMouseEnter={() => setObjectSelectedIndex(i)}
                  >
                    <span className="autocomplete-label">{obj.name}</span>
                    <span className="autocomplete-detail">{obj.label}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <input
            type="text"
            className="sf-input"
            placeholder="Record ID"
            value={recordIdInput}
            onChange={(e) => setRecordIdInput(e.target.value)}
            onKeyDown={handleKeyDown}
            style={{ flex: 1 }}
          />
          <button
            className="highlighted"
            onClick={handleLoad}
            disabled={isLoading || !objectNameInput || !recordIdInput}
          >
            {isLoading ? <><span className="spinner" /> Loading...</> : 'Load'}
          </button>
        </div>
      </div>

      {recordError && <div className="error-message">{recordError}</div>}

      {currentRecord && objectDescribe && !isLoading && (
        <>
          <div className="record-header">
            <div>
              <h2>{(currentRecord.Name as string) || currentRecord.Id}</h2>
              <span className="record-meta">
                {objectDescribe.label} &middot; {currentRecord.Id}
              </span>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              {isEditing ? (
                <>
                  <button
                    className="highlighted"
                    onClick={handleSave}
                    disabled={Object.keys(editedFields).length === 0}
                  >
                    Save
                  </button>
                  <button onClick={resetEdits}>Cancel</button>
                </>
              ) : (
                <button onClick={() => setIsEditing(true)}>Edit</button>
              )}
            </div>
          </div>

          <div style={{ padding: '6px 12px' }}>
            <input
              type="text"
              className="sf-input"
              placeholder="Filter fields..."
              value={fieldFilter}
              onChange={(e) => setFieldFilter(e.target.value)}
              style={{ width: '100%' }}
            />
          </div>

          <div style={{ flex: '1 1 0', overflow: 'auto' }}>
            <table className="record-field-table">
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                {filteredFields?.map((field) => {
                  const value = editedFields[field.name] ?? currentRecord[field.name];
                  const isEditable = isEditing && field.updateable;
                  return (
                    <tr key={field.name}>
                      <td className="field-label" title={field.name}>
                        {field.label}
                        {field.custom && <span className="custom-marker">*</span>}
                      </td>
                      <td>
                        {isEditable ? (
                          field.type === 'boolean' ? (
                            <input
                              type="checkbox"
                              checked={Boolean(value)}
                              onChange={(e) => setEditedField(field.name, e.target.checked)}
                              style={{ width: '1rem', height: '1rem' }}
                            />
                          ) : field.type === 'picklist' ? (
                            <select
                              value={String(value ?? '')}
                              onChange={(e) => setEditedField(field.name, e.target.value)}
                            >
                              <option value="">--None--</option>
                              {field.picklistValues
                                .filter((pv) => pv.active)
                                .map((pv) => (
                                  <option key={pv.value} value={pv.value}>{pv.label}</option>
                                ))}
                            </select>
                          ) : (
                            <input
                              type="text"
                              value={String(value ?? '')}
                              onChange={(e) => setEditedField(field.name, e.target.value)}
                            />
                          )
                        ) : (
                          <span style={!field.updateable ? { color: '#c9c7c5' } : undefined}>
                            {value == null ? '' : String(value)}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!currentRecord && !isLoading && !recordError && (
        <div style={{ padding: 24, textAlign: 'center', color: '#8c8c8c', fontStyle: 'italic' }}>
          Enter an object name and record ID, or navigate to a record in Salesforce
        </div>
      )}
    </div>
  );
}
