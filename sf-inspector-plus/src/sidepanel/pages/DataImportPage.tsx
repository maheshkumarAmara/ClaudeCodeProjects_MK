import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from '@/store';
import { parseData } from '@/utils/data-parser';
import { describeGlobal, describeSObject } from '@/services/salesforce-api';
import { runImport, autoMapFields } from '@/services/import-service';
import { recordsToExcel, recordsToCsv } from '@/utils/csv-export';
import type { ImportFormat } from '@/utils/data-parser';
import type { ImportAction, ImportRecordResult } from '@/store/slices/import-slice';
import type { FieldDescribe } from '@/types/salesforce';
import type { DescribeGlobalSObjectResult } from '@/types/salesforce';

export function DataImportPage() {
  const objectName = useStore((s) => s.importObjectName);
  const setObjectName = useStore((s) => s.setImportObjectName);
  const action = useStore((s) => s.importAction);
  const setAction = useStore((s) => s.setImportAction);
  const format = useStore((s) => s.importFormat);
  const setFormat = useStore((s) => s.setImportFormat);
  const importData = useStore((s) => s.importData);
  const setImportData = useStore((s) => s.setImportData);
  const batchSize = useStore((s) => s.importBatchSize);
  const setBatchSize = useStore((s) => s.setImportBatchSize);
  const threads = useStore((s) => s.importThreads);
  const setThreads = useStore((s) => s.setImportThreads);
  const externalIdField = useStore((s) => s.importExternalIdField);
  const setExternalIdField = useStore((s) => s.setImportExternalIdField);
  const fieldMappings = useStore((s) => s.importFieldMappings);
  const setFieldMappings = useStore((s) => s.setImportFieldMappings);
  const importResults = useStore((s) => s.importResults);
  const setImportResults = useStore((s) => s.setImportResults);
  const updateImportResultsBatch = useStore((s) => s.updateImportResultsBatch);
  const isRunning = useStore((s) => s.importIsRunning);
  const setIsRunning = useStore((s) => s.setImportIsRunning);
  const importError = useStore((s) => s.importError);
  const setImportError = useStore((s) => s.setImportError);

  const [sfFields, setSfFields] = useState<FieldDescribe[]>([]);
  const [objectError, setObjectError] = useState<string | null>(null);
  const [copiedType, setCopiedType] = useState<string | null>(null);
  const cancelRef = useRef(false);

  const [allObjects, setAllObjects] = useState<DescribeGlobalSObjectResult[]>([]);
  const [showObjectDropdown, setShowObjectDropdown] = useState(false);
  const [objectSelectedIndex, setObjectSelectedIndex] = useState(0);
  const objectInputRef = useRef<HTMLInputElement>(null);

  const session = useStore((s) => s.session);

  useEffect(() => {
    if (!session) return;
    describeGlobal().then((result) => {
      setAllObjects(result.sobjects);
    }).catch(() => {});
  }, [session]);

  const filteredObjects = useMemo(() => {
    if (!objectName.trim()) return [];
    const lower = objectName.trim().toLowerCase();
    return allObjects
      .filter((o) => o.name.toLowerCase().includes(lower) || o.label.toLowerCase().includes(lower))
      .slice(0, 20);
  }, [objectName, allObjects]);

  const handleObjectSelect = useCallback((name: string) => {
    setObjectName(name);
    setShowObjectDropdown(false);
  }, [setObjectName]);

  const handleObjectKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (!showObjectDropdown || filteredObjects.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setObjectSelectedIndex((i) => Math.min(i + 1, filteredObjects.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setObjectSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      handleObjectSelect(filteredObjects[objectSelectedIndex].name);
    } else if (e.key === 'Escape') {
      setShowObjectDropdown(false);
    }
  }, [showObjectDropdown, filteredObjects, objectSelectedIndex, handleObjectSelect]);

  const parsed = useMemo(() => {
    if (!importData.trim()) return { columns: [], records: [] };
    try {
      return parseData(importData, format);
    } catch {
      return { columns: [], records: [] };
    }
  }, [importData, format]);

  useEffect(() => {
    if (!objectName.trim()) {
      setSfFields([]);
      setObjectError(null);
      return;
    }

    const timer = setTimeout(async () => {
      try {
        const describe = await describeSObject(objectName.trim());
        setSfFields(describe.fields);
        setObjectError(null);
      } catch (err) {
        setSfFields([]);
        const msg = err instanceof Error ? err.message : 'Failed to describe object';
        setObjectError(msg);
      }
    }, 500);

    return () => clearTimeout(timer);
  }, [objectName]);

  useEffect(() => {
    if (parsed.columns.length > 0 && sfFields.length > 0) {
      const mapped = autoMapFields(
        parsed.columns,
        sfFields.map((f) => ({ name: f.name, label: f.label }))
      );
      setFieldMappings(mapped);
    } else if (parsed.columns.length === 0) {
      setFieldMappings([]);
    }
  }, [parsed.columns, sfFields, setFieldMappings]);

  const updateMapping = useCallback(
    (column: string, sfField: string) => {
      setFieldMappings(
        fieldMappings.map((m) => (m.column === column ? { ...m, sfField } : m))
      );
    },
    [fieldMappings, setFieldMappings]
  );

  const counts = useMemo(() => {
    const c = { queued: 0, processing: 0, succeeded: 0, failed: 0 };
    for (const r of importResults) {
      c[r.status]++;
    }
    return c;
  }, [importResults]);

  const handleRunImport = useCallback(async () => {
    if (!objectName.trim() || parsed.records.length === 0 || isRunning) return;
    if (action === 'Upsert' && !externalIdField.trim()) {
      setImportError('External ID field is required for Upsert');
      return;
    }

    setImportError(null);
    setIsRunning(true);
    cancelRef.current = false;

    const results: ImportRecordResult[] = parsed.records.map((_, i) => ({
      index: i,
      status: 'queued' as const,
    }));
    setImportResults(results);

    try {
      await runImport({
        objectName: objectName.trim(),
        action,
        externalIdField: externalIdField.trim(),
        batchSize,
        threads,
        fieldMappings,
        records: parsed.records,
        onBatchUpdate: (updates) => updateImportResultsBatch(updates),
        shouldCancel: () => cancelRef.current,
      });
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Import failed');
    } finally {
      setIsRunning(false);
    }
  }, [
    objectName, parsed.records, isRunning, action, externalIdField,
    batchSize, threads, fieldMappings, setImportError, setIsRunning,
    setImportResults, updateImportResultsBatch,
  ]);

  const handleCancel = useCallback(() => {
    cancelRef.current = true;
  }, []);

  const handleRetryFailed = useCallback(async () => {
    if (isRunning) return;

    const failedRecords = importResults
      .filter((r) => r.status === 'failed')
      .map((r) => ({ index: r.index, record: parsed.records[r.index] }));

    if (failedRecords.length === 0) return;

    setIsRunning(true);
    cancelRef.current = false;

    const resetUpdates = failedRecords.map((r) => ({
      index: r.index,
      update: { status: 'queued' as const, error: undefined },
    }));
    updateImportResultsBatch(resetUpdates);

    try {
      await runImport({
        objectName: objectName.trim(),
        action,
        externalIdField: externalIdField.trim(),
        batchSize,
        threads,
        fieldMappings,
        records: failedRecords.map((r) => r.record),
        onBatchUpdate: (updates) => {
          const remapped = updates.map((u) => ({
            index: failedRecords[u.index].index,
            update: u.update,
          }));
          updateImportResultsBatch(remapped);
        },
        shouldCancel: () => cancelRef.current,
      });
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Retry failed');
    } finally {
      setIsRunning(false);
    }
  }, [
    isRunning, importResults, parsed.records, objectName, action,
    externalIdField, batchSize, threads, fieldMappings,
    setIsRunning, updateImportResultsBatch, setImportError,
  ]);

  const showCopiedFeedback = (type: string) => {
    setCopiedType(type);
    setTimeout(() => setCopiedType(null), 1500);
  };

  const handleCopyExcel = useCallback(() => {
    if (importResults.length === 0) return;
    const records = importResults.map((r) => ({
      '#': String(r.index + 1),
      Status: r.status,
      Id: r.id ?? '',
      Error: r.error ?? '',
    }));
    navigator.clipboard.writeText(recordsToExcel(records));
    showCopiedFeedback('excel');
  }, [importResults]);

  const handleCopyCsv = useCallback(() => {
    if (importResults.length === 0) return;
    const records = importResults.map((r) => ({
      '#': String(r.index + 1),
      Status: r.status,
      Id: r.id ?? '',
      Error: r.error ?? '',
    }));
    navigator.clipboard.writeText(recordsToCsv(records));
    showCopiedFeedback('csv');
  }, [importResults]);

  const formatPlaceholder = format === 'excel'
    ? 'Paste EXCEL data here\n(Tab-separated: Name\\tPhone\\nAcme\\t555-0100)'
    : format === 'csv'
    ? 'Paste CSV data here\n(Name,Phone\\nAcme,555-0100)'
    : 'Paste JSON data here\n[{"Name":"Acme","Phone":"555-0100"}]';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: '1 1 0', overflow: 'hidden' }}>
      <div className="import-panels">
        {/* Left Panel: Configure Import */}
        <div className="import-config area">
          <h1 style={{ margin: '0 0 8px 0' }}>Configure Import</h1>

          <table className="import-form-table">
            <tbody>
              <tr>
                <td className="form-label">Action</td>
                <td>
                  <select
                    className="sf-select"
                    value={action}
                    onChange={(e) => setAction(e.target.value as ImportAction)}
                  >
                    <option value="Insert">Insert</option>
                    <option value="Update">Update</option>
                    <option value="Upsert">Upsert</option>
                    <option value="Delete">Delete</option>
                  </select>
                </td>
              </tr>
              <tr>
                <td className="form-label">Object</td>
                <td style={{ position: 'relative' }}>
                  <input
                    ref={objectInputRef}
                    type="text"
                    className="sf-input"
                    value={objectName}
                    onChange={(e) => {
                      setObjectName(e.target.value);
                      setShowObjectDropdown(true);
                      setObjectSelectedIndex(0);
                    }}
                    onFocus={() => { if (objectName.trim()) setShowObjectDropdown(true); }}
                    onBlur={() => setTimeout(() => setShowObjectDropdown(false), 150)}
                    onKeyDown={handleObjectKeyDown}
                    placeholder="e.g. Account"
                    style={{ width: '100%' }}
                    autoComplete="off"
                  />
                  {showObjectDropdown && filteredObjects.length > 0 && (
                    <div className="autocomplete-dropdown" style={{ top: '100%', left: 0, marginTop: 2, width: '100%' }}>
                      {filteredObjects.map((obj, i) => (
                        <div
                          key={obj.name}
                          className={`autocomplete-item ${i === objectSelectedIndex ? 'selected' : ''}`}
                          onMouseDown={(e) => {
                            e.preventDefault();
                            handleObjectSelect(obj.name);
                          }}
                        >
                          <span className="autocomplete-label">{obj.name}</span>
                          <span className="autocomplete-detail">{obj.label}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {objectError && (
                    <div style={{ color: '#c23934', fontSize: '0.75rem', marginTop: 2 }}>
                      {objectError}
                    </div>
                  )}
                </td>
              </tr>
              {action === 'Upsert' && (
                <tr>
                  <td className="form-label">External ID</td>
                  <td>
                    <select
                      className="sf-select"
                      value={externalIdField}
                      onChange={(e) => setExternalIdField(e.target.value)}
                    >
                      <option value="">-- Select field --</option>
                      {sfFields
                        .filter((f) => f.externalId || f.type === 'id')
                        .map((f) => (
                          <option key={f.name} value={f.name}>
                            {f.name}
                          </option>
                        ))}
                    </select>
                  </td>
                </tr>
              )}
              <tr>
                <td className="form-label">Format</td>
                <td>
                  <div className="import-format-radios">
                    {(['excel', 'csv', 'json'] as ImportFormat[]).map((fmt) => (
                      <label key={fmt}>
                        <input
                          type="radio"
                          name="importFormat"
                          checked={format === fmt}
                          onChange={() => setFormat(fmt)}
                        />
                        {' '}{fmt === 'excel' ? 'Excel' : fmt.toUpperCase()}
                      </label>
                    ))}
                  </div>
                </td>
              </tr>
              <tr>
                <td className="form-label" style={{ verticalAlign: 'top', paddingTop: 8 }}>
                  Data
                </td>
                <td>
                  <textarea
                    className="query-input"
                    value={importData}
                    onChange={(e) => setImportData(e.target.value)}
                    placeholder={formatPlaceholder}
                    spellCheck={false}
                    style={{ minHeight: '6em' }}
                  />
                  {parsed.records.length > 0 && (
                    <div style={{ fontSize: '0.75rem', color: '#706e6b', marginTop: 2 }}>
                      {parsed.records.length} record{parsed.records.length !== 1 ? 's' : ''} parsed,{' '}
                      {parsed.columns.length} column{parsed.columns.length !== 1 ? 's' : ''}
                    </div>
                  )}
                </td>
              </tr>
              <tr>
                <td className="form-label">Batch size</td>
                <td>
                  <input
                    type="number"
                    className="sf-input"
                    value={batchSize}
                    onChange={(e) => setBatchSize(Number(e.target.value))}
                    min={1}
                    max={200}
                    style={{ width: 80 }}
                  />
                </td>
              </tr>
              <tr>
                <td className="form-label">Threads</td>
                <td>
                  <input
                    type="number"
                    className="sf-input"
                    value={threads}
                    onChange={(e) => setThreads(Number(e.target.value))}
                    min={1}
                    max={10}
                    style={{ width: 80 }}
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Right Panel: Field Mapping */}
        <div className="import-mapping area">
          <h1 style={{ margin: '0 0 8px 0' }}>Field Mapping</h1>

          {fieldMappings.length > 0 ? (
            <div className="import-mapping-table-container">
              <table className="import-mapping-table">
                <thead>
                  <tr>
                    <th>Column</th>
                    <th>Salesforce Field</th>
                  </tr>
                </thead>
                <tbody>
                  {fieldMappings.map((m) => (
                    <tr key={m.column} className={!m.sfField ? 'unmapped' : ''}>
                      <td>{m.column}</td>
                      <td>
                        <select
                          className="sf-select mapping-select"
                          value={m.sfField}
                          onChange={(e) => updateMapping(m.column, e.target.value)}
                        >
                          <option value="">-- Skip --</option>
                          {sfFields.map((f) => (
                            <option key={f.name} value={f.name}>
                              {f.name} ({f.label})
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div style={{ padding: 16, textAlign: 'center', color: '#8c8c8c', fontStyle: 'italic' }}>
              {!importData.trim()
                ? 'Paste data and enter an object name to see field mappings'
                : !objectName.trim()
                ? 'Enter an object name to auto-map fields'
                : objectError
                ? 'Fix the object name to load field mappings'
                : 'No columns detected'}
            </div>
          )}
        </div>
      </div>

      {importError && <div className="error-message">{importError}</div>}

      {/* Bottom Action Bar */}
      <div className="import-action-bar">
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <button
            className="highlighted"
            onClick={handleRunImport}
            disabled={
              isRunning ||
              !objectName.trim() ||
              parsed.records.length === 0 ||
              !!objectError
            }
          >
            {isRunning ? (
              <>
                <span className="spinner" /> Running...
              </>
            ) : (
              `Run ${action}`
            )}
          </button>

          {isRunning && (
            <button className="cancel-btn" onClick={handleCancel}>
              Cancel Queued
            </button>
          )}

          <button
            onClick={handleRetryFailed}
            disabled={isRunning || counts.failed === 0}
          >
            Retry Failed
          </button>

          <button
            onClick={handleCopyExcel}
            disabled={importResults.length === 0}
            style={copiedType === 'excel' ? { color: '#2e844a', borderColor: '#2e844a' } : undefined}
          >
            {copiedType === 'excel' ? 'Copied!' : 'Copy (Excel format)'}
          </button>

          <button
            onClick={handleCopyCsv}
            disabled={importResults.length === 0}
            style={copiedType === 'csv' ? { color: '#2e844a', borderColor: '#2e844a' } : undefined}
          >
            {copiedType === 'csv' ? 'Copied!' : 'Copy (CSV)'}
          </button>
        </div>

        <div className="import-status-counts">
          <span className="status-count queued">
            {counts.queued} Queued
          </span>
          <span className="status-count processing">
            {counts.processing} Processing
          </span>
          <span className="status-count succeeded">
            {counts.succeeded} Succeeded
          </span>
          <span className="status-count failed">
            {counts.failed} Failed
          </span>
        </div>
      </div>
    </div>
  );
}
