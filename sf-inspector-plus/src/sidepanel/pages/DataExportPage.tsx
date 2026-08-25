import { useCallback, useRef, useState } from 'react';
import { useStore } from '@/store';
import { query, queryMore } from '@/services/salesforce-api';
import {
  recordsToCsv,
  recordsToExcel,
  recordsToJson,
  downloadCsv,
} from '@/utils/csv-export';
import { ResultsTable } from '../components/soql/ResultsTable';
import { QueryHistory } from '../components/soql/QueryHistory';
import { SavedQueries } from '../components/soql/SavedQueries';
import { SoqlAutocomplete } from '../components/soql/SoqlAutocomplete';
import { SoqlEditor } from '../components/soql/SoqlEditor';
import { useSoqlAutocomplete } from '@/hooks/useSoqlAutocomplete';
import type { QueryResult } from '@/types/salesforce';

export function DataExportPage() {
  const currentSoql = useStore((s) => s.currentSoql);
  const setCurrentSoql = useStore((s) => s.setCurrentSoql);
  const queryResults = useStore((s) => s.queryResults);
  const setQueryResults = useStore((s) => s.setQueryResults);
  const isExecuting = useStore((s) => s.isExecuting);
  const setIsExecuting = useStore((s) => s.setIsExecuting);
  const queryError = useStore((s) => s.queryError);
  const setQueryError = useStore((s) => s.setQueryError);
  const addToHistory = useStore((s) => s.addToHistory);
  const saveQuery = useStore((s) => s.saveQuery);
  const session = useStore((s) => s.session);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [useToolingApi, setUseToolingApi] = useState(false);
  const [addDeletedRecords, setAddDeletedRecords] = useState(false);
  const [queryTimeMs, setQueryTimeMs] = useState<number | null>(null);
  const [resultFilter, setResultFilter] = useState('');
  const [copiedType, setCopiedType] = useState<string | null>(null);

  const autocomplete = useSoqlAutocomplete(textareaRef, currentSoql, setCurrentSoql);

  const handleSaveQuery = useCallback(() => {
    if (!currentSoql.trim() || !session) return;
    const name = window.prompt('Enter a name for this query:');
    if (!name?.trim()) return;
    saveQuery(name.trim(), currentSoql, session.orgId);
  }, [currentSoql, session, saveQuery]);

  const executeQuery = useCallback(async () => {
    if (!currentSoql.trim() || isExecuting) return;
    setIsExecuting(true);
    setQueryError(null);
    setQueryTimeMs(null);

    const start = performance.now();
    try {
      const results = await query(currentSoql, {
        useToolingApi,
        includeDeleted: addDeletedRecords,
      });
      setQueryTimeMs(Math.round(performance.now() - start));
      setQueryResults(results);
      if (session) {
        addToHistory({
          soql: currentSoql,
          timestamp: Date.now(),
          orgId: session.orgId,
          rowCount: results.totalSize,
        });
      }
    } catch (err) {
      setQueryTimeMs(Math.round(performance.now() - start));
      const msg = err instanceof Error ? err.message : 'Query failed';
      setQueryError(msg);
      setQueryResults(null);
    } finally {
      setIsExecuting(false);
    }
  }, [currentSoql, isExecuting, session, useToolingApi, addDeletedRecords, setIsExecuting, setQueryError, setQueryResults, addToHistory]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (autocomplete.handleKeyDown(e)) return;
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        executeQuery();
      }
    },
    [executeQuery, autocomplete]
  );

  const showCopiedFeedback = (type: string) => {
    setCopiedType(type);
    setTimeout(() => setCopiedType(null), 1500);
  };

  const copyToClipboard = useCallback(async (text: string, type: string) => {
    try {
      await navigator.clipboard.writeText(text);
      showCopiedFeedback(type);
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      showCopiedFeedback(type);
    }
  }, []);

  const handleCopyExcel = useCallback(() => {
    if (!queryResults?.records) return;
    const excel = recordsToExcel(queryResults.records as Record<string, unknown>[]);
    copyToClipboard(excel, 'excel');
  }, [queryResults, copyToClipboard]);

  const handleCopyCsv = useCallback(() => {
    if (!queryResults?.records) return;
    const csv = recordsToCsv(queryResults.records as Record<string, unknown>[]);
    copyToClipboard(csv, 'csv');
  }, [queryResults, copyToClipboard]);

  const handleCopyJson = useCallback(() => {
    if (!queryResults?.records) return;
    const json = recordsToJson(queryResults.records as Record<string, unknown>[]);
    copyToClipboard(json, 'json');
  }, [queryResults, copyToClipboard]);

  const handleDownload = useCallback(() => {
    if (!queryResults?.records) return;
    const csv = recordsToCsv(queryResults.records as Record<string, unknown>[]);
    downloadCsv(csv, `export_${Date.now()}.csv`);
  }, [queryResults]);

  const handleLoadMore = useCallback(async () => {
    if (!queryResults?.nextRecordsUrl || isExecuting) return;
    setIsExecuting(true);
    try {
      const more = await queryMore(queryResults.nextRecordsUrl);
      setQueryResults({
        ...more,
        records: [...queryResults.records, ...more.records],
        totalSize: queryResults.totalSize,
      } as QueryResult);
    } catch (err) {
      setQueryError(err instanceof Error ? err.message : 'Failed to load more');
    } finally {
      setIsExecuting(false);
    }
  }, [queryResults, isExecuting, setIsExecuting, setQueryResults, setQueryError]);

  const handleSelectHistory = useCallback(
    (soql: string) => {
      setCurrentSoql(soql);
      if (textareaRef.current) {
        textareaRef.current.focus();
      }
    },
    [setCurrentSoql]
  );

  const filteredRecords = queryResults?.records
    ? resultFilter
      ? queryResults.records.filter((r) =>
          JSON.stringify(r).toLowerCase().includes(resultFilter.toLowerCase())
        )
      : queryResults.records
    : [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: '1 1 0', overflow: 'hidden' }}>
      {/* ── Export Query Area ── */}
      <div className="area">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <h1 style={{ margin: 0 }}>Export Query</h1>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <SavedQueries onSelect={handleSelectHistory} />
            <QueryHistory onSelect={handleSelectHistory} />
          </div>
        </div>

        <div className="query-options">
          <label>
            <input
              type="checkbox"
              checked={addDeletedRecords}
              onChange={(e) => setAddDeletedRecords(e.target.checked)}
            />
            {' '}Add deleted records?
          </label>
          <label>
            <input
              type="checkbox"
              checked={useToolingApi}
              onChange={(e) => setUseToolingApi(e.target.checked)}
            />
            {' '}Tooling API?
          </label>
        </div>

        <div style={{ position: 'relative' }}>
          <SoqlEditor
            textareaRef={textareaRef}
            value={currentSoql}
            onChange={setCurrentSoql}
            onKeyDown={handleKeyDown}
            onBlur={() => setTimeout(() => autocomplete.close(), 150)}
            placeholder="SELECT Id, Name FROM Account LIMIT 100"
          />
          <SoqlAutocomplete
            textareaRef={textareaRef}
            suggestions={autocomplete.suggestions}
            selectedIndex={autocomplete.selectedIndex}
            isOpen={autocomplete.isOpen}
            onSelect={autocomplete.insertSuggestion}
          />
        </div>

        {/* Action buttons row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
          <div style={{ flex: 1 }} />
          <button
            onClick={handleSaveQuery}
            disabled={!currentSoql.trim() || !session}
            title="Save this query for later"
          >
            Save Query
          </button>
          <button
            className="highlighted"
            onClick={executeQuery}
            disabled={isExecuting || !currentSoql.trim()}
          >
            {isExecuting ? <><span className="spinner" /> Running...</> : 'Run Export'}
          </button>
          <button onClick={() => {
            const formatted = currentSoql
              .replace(/\s+/g, ' ')
              .replace(/ ?(SELECT|FROM|WHERE|AND|OR|ORDER BY|GROUP BY|HAVING|LIMIT|OFFSET) /gi,
                (_m, kw: string) => '\n' + kw.toUpperCase() + ' ')
              .trim();
            setCurrentSoql(formatted);
          }}>
            Format Query
          </button>
          <button onClick={handleDownload} disabled={!queryResults?.records?.length}>
            Export Query
          </button>
        </div>
      </div>

      {/* Error */}
      {queryError && (
        <div className="error-message">{queryError}</div>
      )}

      {/* ── Export Result Area ── */}
      <div className="result-area">
        <div className="result-bar" style={{ flexWrap: 'wrap', gap: 6 }}>
          <h1 style={{ margin: 0, marginRight: 8 }}>Export Result</h1>

          {queryResults && (
            <>
              <button
                onClick={handleCopyExcel}
                style={copiedType === 'excel' ? { color: '#2e844a', borderColor: '#2e844a' } : undefined}
              >
                {copiedType === 'excel' ? 'Copied!' : 'Copy (Excel format)'}
              </button>
              <button
                onClick={handleCopyCsv}
                style={copiedType === 'csv' ? { color: '#2e844a', borderColor: '#2e844a' } : undefined}
              >
                {copiedType === 'csv' ? 'Copied!' : 'Copy (CSV)'}
              </button>
              <button
                onClick={handleCopyJson}
                style={copiedType === 'json' ? { color: '#2e844a', borderColor: '#2e844a' } : undefined}
              >
                {copiedType === 'json' ? 'Copied!' : 'Copy (JSON)'}
              </button>
              <button onClick={handleDownload} title="Download as CSV file">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#0070d2" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ verticalAlign: 'middle' }}>
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
              </button>
            </>
          )}

          <div className="flex-right">
            {queryResults && (
              <>
                <div style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#919191" strokeWidth="2" style={{ position: 'absolute', left: 8 }}>
                    <circle cx="11" cy="11" r="8" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  </svg>
                  <input
                    type="text"
                    className="sf-input"
                    placeholder="Filter Results"
                    value={resultFilter}
                    onChange={(e) => setResultFilter(e.target.value)}
                    style={{ paddingLeft: 28, width: 130, height: 28, fontSize: '0.75rem' }}
                  />
                </div>

                <span className="result-info" style={{ whiteSpace: 'nowrap' }}>
                  Exported {filteredRecords.length}
                  {queryResults.totalSize > queryResults.records.length
                    ? ` of ${queryResults.totalSize}`
                    : ''}
                  {' '}record{queryResults.totalSize !== 1 ? 's' : ''}
                  {queryTimeMs != null && (
                    <span style={{ marginLeft: 6, color: '#706e6b' }}>
                      {queryTimeMs < 1000 ? `${queryTimeMs}ms` : `${(queryTimeMs / 1000).toFixed(1)}s`}
                    </span>
                  )}
                </span>

                {!queryResults.done && queryResults.nextRecordsUrl && (
                  <button
                    onClick={handleLoadMore}
                    disabled={isExecuting}
                    style={{ height: 28, lineHeight: '28px', fontSize: '0.75rem', padding: '0 10px' }}
                  >
                    {isExecuting ? 'Loading...' : 'Load More'}
                  </button>
                )}

                {isExecuting && (
                  <button
                    className="cancel-btn"
                    onClick={() => setIsExecuting(false)}
                    style={{ height: 28, lineHeight: '28px', fontSize: '0.75rem', padding: '0 10px' }}
                  >
                    Stop
                  </button>
                )}
              </>
            )}
          </div>
        </div>

        <div className="result-table-container">
          {filteredRecords.length > 0 ? (
            <ResultsTable
              results={{ ...queryResults!, records: filteredRecords }}
            />
          ) : queryResults?.done ? (
            <div style={{ padding: 16, textAlign: 'center', color: '#8c8c8c', fontStyle: 'italic' }}>
              {resultFilter ? 'No matching records' : 'No records found'}
            </div>
          ) : !queryResults && !queryError ? (
            <div style={{ padding: 16, textAlign: 'center', color: '#8c8c8c', fontStyle: 'italic' }}>
              Enter a SOQL query and click Run Export or press Ctrl+Enter
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
