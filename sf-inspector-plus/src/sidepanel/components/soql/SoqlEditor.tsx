import { useCallback, useRef, useMemo } from 'react';

const KEYWORDS = new Set([
  'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT',
  'ORDER', 'BY', 'GROUP', 'HAVING', 'LIMIT', 'OFFSET',
  'LIKE', 'IN', 'ASC', 'DESC', 'NULLS', 'FIRST', 'LAST',
  'TRUE', 'FALSE', 'NULL', 'WITH', 'USING', 'SCOPE',
  'FOR', 'UPDATE', 'TYPEOF', 'WHEN', 'THEN', 'ELSE', 'END',
  'COUNT', 'COUNT_DISTINCT', 'SUM', 'AVG', 'MIN', 'MAX',
  'FIELDS', 'ALL', 'STANDARD', 'CUSTOM',
  'INCLUDES', 'EXCLUDES', 'ROLLUP', 'CUBE',
  'FORMAT', 'TOLABEL', 'CONVERTCURRENCY', 'CONVERTTIMEZONE',
  'GROUPING', 'DISTANCE', 'GEOLOCATION',
  'CALENDAR_MONTH', 'CALENDAR_QUARTER', 'CALENDAR_YEAR',
  'DAY_IN_MONTH', 'DAY_IN_WEEK', 'DAY_IN_YEAR', 'DAY_ONLY',
  'FISCAL_MONTH', 'FISCAL_QUARTER', 'FISCAL_YEAR',
  'HOUR_IN_DAY', 'WEEK_IN_MONTH', 'WEEK_IN_YEAR',
  'SECURITY_ENFORCED', 'USER_MODE', 'SYSTEM_MODE',
  'DATA', 'CATEGORY', 'REFERENCE', 'VIEW',
  'TODAY', 'YESTERDAY', 'TOMORROW',
  'LAST_WEEK', 'THIS_WEEK', 'NEXT_WEEK',
  'LAST_MONTH', 'THIS_MONTH', 'NEXT_MONTH',
  'LAST_QUARTER', 'THIS_QUARTER', 'NEXT_QUARTER',
  'LAST_YEAR', 'THIS_YEAR', 'NEXT_YEAR',
  'LAST_90_DAYS', 'NEXT_90_DAYS',
  'LAST_N_DAYS', 'NEXT_N_DAYS', 'N_DAYS_AGO',
  'LAST_N_WEEKS', 'NEXT_N_WEEKS', 'N_WEEKS_AGO',
  'LAST_N_MONTHS', 'NEXT_N_MONTHS', 'N_MONTHS_AGO',
  'LAST_N_QUARTERS', 'NEXT_N_QUARTERS', 'N_QUARTERS_AGO',
  'LAST_N_YEARS', 'NEXT_N_YEARS', 'N_YEARS_AGO',
  'THIS_FISCAL_QUARTER', 'LAST_FISCAL_QUARTER', 'NEXT_FISCAL_QUARTER',
  'THIS_FISCAL_YEAR', 'LAST_FISCAL_YEAR', 'NEXT_FISCAL_YEAR',
  'LAST_N_FISCAL_QUARTERS', 'NEXT_N_FISCAL_QUARTERS', 'N_FISCAL_QUARTERS_AGO',
  'LAST_N_FISCAL_YEARS', 'NEXT_N_FISCAL_YEARS', 'N_FISCAL_YEARS_AGO',
]);

interface Token {
  text: string;
  type: 'keyword' | 'string' | 'number' | 'text';
}

function tokenize(soql: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;

  while (i < soql.length) {
    if (soql[i] === "'") {
      let j = i + 1;
      while (j < soql.length && soql[j] !== "'") j++;
      if (j < soql.length) j++;
      tokens.push({ text: soql.substring(i, j), type: 'string' });
      i = j;
    } else if (/[a-zA-Z_]/.test(soql[i])) {
      let j = i;
      while (j < soql.length && /[\w]/.test(soql[j])) j++;
      const word = soql.substring(i, j);
      tokens.push({
        text: word,
        type: KEYWORDS.has(word.toUpperCase()) ? 'keyword' : 'text',
      });
      i = j;
    } else if (/\d/.test(soql[i])) {
      let j = i;
      while (j < soql.length && /[\d.]/.test(soql[j])) j++;
      tokens.push({ text: soql.substring(i, j), type: 'number' });
      i = j;
    } else {
      let j = i;
      while (j < soql.length && !/[a-zA-Z_\d']/.test(soql[j])) j++;
      tokens.push({ text: soql.substring(i, j), type: 'text' });
      i = j;
    }
  }

  return tokens;
}

interface SoqlEditorProps {
  value: string;
  onChange: (value: string) => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  onBlur: () => void;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  placeholder?: string;
}

export function SoqlEditor({
  value,
  onChange,
  onKeyDown,
  onBlur,
  textareaRef,
  placeholder,
}: SoqlEditorProps) {
  const highlightRef = useRef<HTMLDivElement>(null);

  const highlighted = useMemo(() => {
    if (!value) return null;
    const tokens = tokenize(value);
    return tokens.map((token, i) => {
      switch (token.type) {
        case 'keyword':
          return <span key={i} className="soql-kw">{token.text}</span>;
        case 'string':
          return <span key={i} className="soql-str">{token.text}</span>;
        case 'number':
          return <span key={i} className="soql-num">{token.text}</span>;
        default:
          return <span key={i}>{token.text}</span>;
      }
    });
  }, [value]);

  const handleScroll = useCallback(() => {
    if (!textareaRef.current || !highlightRef.current) return;
    highlightRef.current.scrollTop = textareaRef.current.scrollTop;
    highlightRef.current.scrollLeft = textareaRef.current.scrollLeft;
  }, [textareaRef]);

  return (
    <div className="soql-editor-wrapper">
      <div className="soql-highlight-layer" ref={highlightRef}>
        {highlighted}
        {/* trailing newline so height matches textarea */}
        {value.endsWith('\n') ? '\n' : ''}
      </div>
      <textarea
        ref={textareaRef}
        className="soql-input-layer"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={onBlur}
        onScroll={handleScroll}
        placeholder={placeholder}
        spellCheck={false}
      />
    </div>
  );
}
