import { useCallback, useEffect, useRef, useState } from 'react';
import { useStore } from '@/store';
import { describeGlobal, describeSObject } from '@/services/salesforce-api';
import { getCached, setCache, CACHE_TTL } from '@/services/cache';
import type { DescribeGlobalSObjectResult, FieldDescribe } from '@/types/salesforce';

export interface Suggestion {
  label: string;
  value: string;
  detail: string;
  kind: 'field' | 'object' | 'relationship' | 'function' | 'keyword' | 'dateLiteral' | 'snippet';
}

// ── SOQL Aggregate Functions ──
const AGGREGATE_FUNCTIONS: Suggestion[] = [
  { label: 'COUNT()', value: 'COUNT()', detail: 'Aggregate', kind: 'function' },
  { label: 'COUNT(field)', value: 'COUNT(', detail: 'Aggregate', kind: 'function' },
  { label: 'COUNT_DISTINCT(field)', value: 'COUNT_DISTINCT(', detail: 'Aggregate', kind: 'function' },
  { label: 'SUM(field)', value: 'SUM(', detail: 'Aggregate', kind: 'function' },
  { label: 'AVG(field)', value: 'AVG(', detail: 'Aggregate', kind: 'function' },
  { label: 'MIN(field)', value: 'MIN(', detail: 'Aggregate', kind: 'function' },
  { label: 'MAX(field)', value: 'MAX(', detail: 'Aggregate', kind: 'function' },
];

// ── SOQL Date Functions ──
const DATE_FUNCTIONS: Suggestion[] = [
  { label: 'CALENDAR_MONTH(field)', value: 'CALENDAR_MONTH(', detail: 'Date Function', kind: 'function' },
  { label: 'CALENDAR_QUARTER(field)', value: 'CALENDAR_QUARTER(', detail: 'Date Function', kind: 'function' },
  { label: 'CALENDAR_YEAR(field)', value: 'CALENDAR_YEAR(', detail: 'Date Function', kind: 'function' },
  { label: 'DAY_IN_MONTH(field)', value: 'DAY_IN_MONTH(', detail: 'Date Function', kind: 'function' },
  { label: 'DAY_IN_WEEK(field)', value: 'DAY_IN_WEEK(', detail: 'Date Function', kind: 'function' },
  { label: 'DAY_IN_YEAR(field)', value: 'DAY_IN_YEAR(', detail: 'Date Function', kind: 'function' },
  { label: 'DAY_ONLY(field)', value: 'DAY_ONLY(', detail: 'Date Function', kind: 'function' },
  { label: 'FISCAL_MONTH(field)', value: 'FISCAL_MONTH(', detail: 'Date Function', kind: 'function' },
  { label: 'FISCAL_QUARTER(field)', value: 'FISCAL_QUARTER(', detail: 'Date Function', kind: 'function' },
  { label: 'FISCAL_YEAR(field)', value: 'FISCAL_YEAR(', detail: 'Date Function', kind: 'function' },
  { label: 'HOUR_IN_DAY(field)', value: 'HOUR_IN_DAY(', detail: 'Date Function', kind: 'function' },
  { label: 'WEEK_IN_MONTH(field)', value: 'WEEK_IN_MONTH(', detail: 'Date Function', kind: 'function' },
  { label: 'WEEK_IN_YEAR(field)', value: 'WEEK_IN_YEAR(', detail: 'Date Function', kind: 'function' },
];

// ── SOQL Other Functions ──
const OTHER_FUNCTIONS: Suggestion[] = [
  { label: 'FORMAT(field)', value: 'FORMAT(', detail: 'Format Function', kind: 'function' },
  { label: 'toLabel(field)', value: 'toLabel(', detail: 'Label Function', kind: 'function' },
  { label: 'convertCurrency(field)', value: 'convertCurrency(', detail: 'Currency Function', kind: 'function' },
  { label: 'convertTimezone(field)', value: 'convertTimezone(', detail: 'Timezone Function', kind: 'function' },
  { label: 'GROUPING(field)', value: 'GROUPING(', detail: 'Grouping Function', kind: 'function' },
  { label: 'DISTANCE(loc1, loc2, unit)', value: 'DISTANCE(', detail: 'Geolocation', kind: 'function' },
  { label: 'GEOLOCATION(lat, lon)', value: 'GEOLOCATION(', detail: 'Geolocation', kind: 'function' },
];

// ── FIELDS() shortcuts ──
const FIELDS_FUNCTIONS: Suggestion[] = [
  { label: 'FIELDS(ALL)', value: 'FIELDS(ALL)', detail: 'All fields', kind: 'function' },
  { label: 'FIELDS(STANDARD)', value: 'FIELDS(STANDARD)', detail: 'Standard fields', kind: 'function' },
  { label: 'FIELDS(CUSTOM)', value: 'FIELDS(CUSTOM)', detail: 'Custom fields', kind: 'function' },
];

const ALL_SELECT_FUNCTIONS = [...AGGREGATE_FUNCTIONS, ...DATE_FUNCTIONS, ...OTHER_FUNCTIONS, ...FIELDS_FUNCTIONS];

// ── SOQL Keywords (clause starters) ──
const CLAUSE_KEYWORDS: Suggestion[] = [
  { label: 'FROM', value: 'FROM ', detail: 'Clause', kind: 'keyword' },
  { label: 'WHERE', value: 'WHERE ', detail: 'Clause', kind: 'keyword' },
  { label: 'AND', value: 'AND ', detail: 'Operator', kind: 'keyword' },
  { label: 'OR', value: 'OR ', detail: 'Operator', kind: 'keyword' },
  { label: 'NOT', value: 'NOT ', detail: 'Operator', kind: 'keyword' },
  { label: 'ORDER BY', value: 'ORDER BY ', detail: 'Clause', kind: 'keyword' },
  { label: 'GROUP BY', value: 'GROUP BY ', detail: 'Clause', kind: 'keyword' },
  { label: 'GROUP BY ROLLUP', value: 'GROUP BY ROLLUP(', detail: 'Clause', kind: 'keyword' },
  { label: 'GROUP BY CUBE', value: 'GROUP BY CUBE(', detail: 'Clause', kind: 'keyword' },
  { label: 'HAVING', value: 'HAVING ', detail: 'Clause', kind: 'keyword' },
  { label: 'LIMIT', value: 'LIMIT ', detail: 'Clause', kind: 'keyword' },
  { label: 'OFFSET', value: 'OFFSET ', detail: 'Clause', kind: 'keyword' },
  { label: 'ASC', value: 'ASC ', detail: 'Sort Order', kind: 'keyword' },
  { label: 'DESC', value: 'DESC ', detail: 'Sort Order', kind: 'keyword' },
  { label: 'NULLS FIRST', value: 'NULLS FIRST ', detail: 'Sort Nulls', kind: 'keyword' },
  { label: 'NULLS LAST', value: 'NULLS LAST ', detail: 'Sort Nulls', kind: 'keyword' },
  { label: 'LIKE', value: 'LIKE ', detail: 'Operator', kind: 'keyword' },
  { label: 'IN', value: 'IN (', detail: 'Operator', kind: 'keyword' },
  { label: 'NOT IN', value: 'NOT IN (', detail: 'Operator', kind: 'keyword' },
  { label: 'INCLUDES', value: 'INCLUDES (', detail: 'Multi-picklist', kind: 'keyword' },
  { label: 'EXCLUDES', value: 'EXCLUDES (', detail: 'Multi-picklist', kind: 'keyword' },
  { label: 'FOR UPDATE', value: 'FOR UPDATE', detail: 'Locking', kind: 'keyword' },
  { label: 'FOR REFERENCE', value: 'FOR REFERENCE', detail: 'Tracking', kind: 'keyword' },
  { label: 'FOR VIEW', value: 'FOR VIEW', detail: 'Tracking', kind: 'keyword' },
  { label: 'USING SCOPE', value: 'USING SCOPE ', detail: 'Scope', kind: 'keyword' },
  { label: 'WITH DATA CATEGORY', value: 'WITH DATA CATEGORY ', detail: 'Filter', kind: 'keyword' },
  { label: 'WITH SECURITY_ENFORCED', value: 'WITH SECURITY_ENFORCED ', detail: 'Security', kind: 'keyword' },
  { label: 'WITH USER_MODE', value: 'WITH USER_MODE ', detail: 'Security', kind: 'keyword' },
  { label: 'WITH SYSTEM_MODE', value: 'WITH SYSTEM_MODE ', detail: 'Security', kind: 'keyword' },
  { label: 'TYPEOF', value: 'TYPEOF ', detail: 'Polymorphic', kind: 'keyword' },
  { label: 'WHEN', value: 'WHEN ', detail: 'TYPEOF clause', kind: 'keyword' },
  { label: 'THEN', value: 'THEN ', detail: 'TYPEOF clause', kind: 'keyword' },
  { label: 'ELSE', value: 'ELSE ', detail: 'TYPEOF clause', kind: 'keyword' },
  { label: 'END', value: 'END ', detail: 'TYPEOF clause', kind: 'keyword' },
  { label: 'TRUE', value: 'TRUE', detail: 'Boolean', kind: 'keyword' },
  { label: 'FALSE', value: 'FALSE', detail: 'Boolean', kind: 'keyword' },
  { label: 'NULL', value: 'NULL', detail: 'Null literal', kind: 'keyword' },
];

// ── USING SCOPE values ──
const SCOPE_VALUES: Suggestion[] = [
  { label: 'Delegated', value: 'Delegated', detail: 'Scope', kind: 'keyword' },
  { label: 'Everything', value: 'Everything', detail: 'Scope', kind: 'keyword' },
  { label: 'Mine', value: 'Mine', detail: 'Scope', kind: 'keyword' },
  { label: 'MineAndMyGroups', value: 'MineAndMyGroups', detail: 'Scope', kind: 'keyword' },
  { label: 'My_Territory', value: 'My_Territory', detail: 'Scope', kind: 'keyword' },
  { label: 'My_Team_Territory', value: 'My_Team_Territory', detail: 'Scope', kind: 'keyword' },
  { label: 'Team', value: 'Team', detail: 'Scope', kind: 'keyword' },
];

// ── Date Literals ──
const DATE_LITERALS: Suggestion[] = [
  { label: 'YESTERDAY', value: 'YESTERDAY', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'TODAY', value: 'TODAY', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'TOMORROW', value: 'TOMORROW', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'LAST_WEEK', value: 'LAST_WEEK', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'THIS_WEEK', value: 'THIS_WEEK', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'NEXT_WEEK', value: 'NEXT_WEEK', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'LAST_MONTH', value: 'LAST_MONTH', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'THIS_MONTH', value: 'THIS_MONTH', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'NEXT_MONTH', value: 'NEXT_MONTH', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'LAST_90_DAYS', value: 'LAST_90_DAYS', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'NEXT_90_DAYS', value: 'NEXT_90_DAYS', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'THIS_QUARTER', value: 'THIS_QUARTER', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'LAST_QUARTER', value: 'LAST_QUARTER', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'NEXT_QUARTER', value: 'NEXT_QUARTER', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'THIS_YEAR', value: 'THIS_YEAR', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'LAST_YEAR', value: 'LAST_YEAR', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'NEXT_YEAR', value: 'NEXT_YEAR', detail: 'Date Literal', kind: 'dateLiteral' },
  { label: 'THIS_FISCAL_QUARTER', value: 'THIS_FISCAL_QUARTER', detail: 'Fiscal', kind: 'dateLiteral' },
  { label: 'LAST_FISCAL_QUARTER', value: 'LAST_FISCAL_QUARTER', detail: 'Fiscal', kind: 'dateLiteral' },
  { label: 'NEXT_FISCAL_QUARTER', value: 'NEXT_FISCAL_QUARTER', detail: 'Fiscal', kind: 'dateLiteral' },
  { label: 'THIS_FISCAL_YEAR', value: 'THIS_FISCAL_YEAR', detail: 'Fiscal', kind: 'dateLiteral' },
  { label: 'LAST_FISCAL_YEAR', value: 'LAST_FISCAL_YEAR', detail: 'Fiscal', kind: 'dateLiteral' },
  { label: 'NEXT_FISCAL_YEAR', value: 'NEXT_FISCAL_YEAR', detail: 'Fiscal', kind: 'dateLiteral' },
  { label: 'LAST_N_DAYS:n', value: 'LAST_N_DAYS:', detail: 'Relative Date', kind: 'dateLiteral' },
  { label: 'NEXT_N_DAYS:n', value: 'NEXT_N_DAYS:', detail: 'Relative Date', kind: 'dateLiteral' },
  { label: 'N_DAYS_AGO:n', value: 'N_DAYS_AGO:', detail: 'Relative Date', kind: 'dateLiteral' },
  { label: 'LAST_N_WEEKS:n', value: 'LAST_N_WEEKS:', detail: 'Relative Date', kind: 'dateLiteral' },
  { label: 'NEXT_N_WEEKS:n', value: 'NEXT_N_WEEKS:', detail: 'Relative Date', kind: 'dateLiteral' },
  { label: 'N_WEEKS_AGO:n', value: 'N_WEEKS_AGO:', detail: 'Relative Date', kind: 'dateLiteral' },
  { label: 'LAST_N_MONTHS:n', value: 'LAST_N_MONTHS:', detail: 'Relative Date', kind: 'dateLiteral' },
  { label: 'NEXT_N_MONTHS:n', value: 'NEXT_N_MONTHS:', detail: 'Relative Date', kind: 'dateLiteral' },
  { label: 'N_MONTHS_AGO:n', value: 'N_MONTHS_AGO:', detail: 'Relative Date', kind: 'dateLiteral' },
  { label: 'LAST_N_QUARTERS:n', value: 'LAST_N_QUARTERS:', detail: 'Relative Date', kind: 'dateLiteral' },
  { label: 'NEXT_N_QUARTERS:n', value: 'NEXT_N_QUARTERS:', detail: 'Relative Date', kind: 'dateLiteral' },
  { label: 'N_QUARTERS_AGO:n', value: 'N_QUARTERS_AGO:', detail: 'Relative Date', kind: 'dateLiteral' },
  { label: 'LAST_N_YEARS:n', value: 'LAST_N_YEARS:', detail: 'Relative Date', kind: 'dateLiteral' },
  { label: 'NEXT_N_YEARS:n', value: 'NEXT_N_YEARS:', detail: 'Relative Date', kind: 'dateLiteral' },
  { label: 'N_YEARS_AGO:n', value: 'N_YEARS_AGO:', detail: 'Relative Date', kind: 'dateLiteral' },
  { label: 'LAST_N_FISCAL_QUARTERS:n', value: 'LAST_N_FISCAL_QUARTERS:', detail: 'Relative Fiscal', kind: 'dateLiteral' },
  { label: 'NEXT_N_FISCAL_QUARTERS:n', value: 'NEXT_N_FISCAL_QUARTERS:', detail: 'Relative Fiscal', kind: 'dateLiteral' },
  { label: 'N_FISCAL_QUARTERS_AGO:n', value: 'N_FISCAL_QUARTERS_AGO:', detail: 'Relative Fiscal', kind: 'dateLiteral' },
  { label: 'LAST_N_FISCAL_YEARS:n', value: 'LAST_N_FISCAL_YEARS:', detail: 'Relative Fiscal', kind: 'dateLiteral' },
  { label: 'NEXT_N_FISCAL_YEARS:n', value: 'NEXT_N_FISCAL_YEARS:', detail: 'Relative Fiscal', kind: 'dateLiteral' },
  { label: 'N_FISCAL_YEARS_AGO:n', value: 'N_FISCAL_YEARS_AGO:', detail: 'Relative Fiscal', kind: 'dateLiteral' },
];

// ── Common SOQL Snippets ──
const SOQL_SNIPPETS: Suggestion[] = [
  { label: 'SELECT Id, Name FROM', value: 'SELECT Id, Name FROM ', detail: 'Snippet', kind: 'snippet' },
  { label: 'SELECT COUNT() FROM', value: 'SELECT COUNT() FROM ', detail: 'Snippet', kind: 'snippet' },
  { label: 'ORDER BY CreatedDate DESC', value: 'ORDER BY CreatedDate DESC', detail: 'Snippet', kind: 'snippet' },
  { label: 'ORDER BY LastModifiedDate DESC', value: 'ORDER BY LastModifiedDate DESC', detail: 'Snippet', kind: 'snippet' },
  { label: 'LIMIT 100', value: 'LIMIT 100', detail: 'Snippet', kind: 'snippet' },
  { label: 'LIMIT 200', value: 'LIMIT 200', detail: 'Snippet', kind: 'snippet' },
];

// ── Context Detection ──

type SoqlContext = 'select' | 'from' | 'where' | 'orderby' | 'groupby' | 'having' | 'scope' | 'keyword' | 'none';

function extractObjectName(soql: string): string | null {
  const match = soql.match(/\bFROM\s+(\w+)/i);
  return match ? match[1] : null;
}

function getSoqlContext(soql: string, cursorPos: number): SoqlContext {
  const before = soql.substring(0, cursorPos).toUpperCase();

  const lastKeyword = findLastKeyword(before);

  if (!lastKeyword) {
    if (before.trim().length === 0) return 'keyword';
    return 'none';
  }

  switch (lastKeyword.keyword) {
    case 'SELECT':
      return 'select';
    case 'FROM':
      return isObjectComplete(before, lastKeyword.index) ? 'keyword' : 'from';
    case 'WHERE':
    case 'AND':
    case 'OR':
    case 'NOT':
      return 'where';
    case 'ORDER BY':
      return 'orderby';
    case 'GROUP BY':
    case 'GROUP BY ROLLUP':
    case 'GROUP BY CUBE':
      return 'groupby';
    case 'HAVING':
      return 'having';
    case 'USING SCOPE':
      return 'scope';
    case 'LIMIT':
    case 'OFFSET':
      return 'none';
    default:
      return 'keyword';
  }
}

function findLastKeyword(text: string): { keyword: string; index: number } | null {
  const keywords = [
    'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT',
    'ORDER BY', 'GROUP BY ROLLUP', 'GROUP BY CUBE', 'GROUP BY',
    'HAVING', 'LIMIT', 'OFFSET', 'USING SCOPE',
    'FOR UPDATE', 'FOR REFERENCE', 'FOR VIEW',
    'WITH SECURITY_ENFORCED', 'WITH USER_MODE', 'WITH SYSTEM_MODE',
    'WITH DATA CATEGORY', 'WITH',
  ];

  let latest: { keyword: string; index: number } | null = null;

  for (const kw of keywords) {
    const regex = new RegExp(`\\b${kw.replace(/ /g, '\\s+')}\\b`, 'gi');
    let match;
    while ((match = regex.exec(text)) !== null) {
      if (!latest || match.index > latest.index) {
        latest = { keyword: kw, index: match.index };
      }
    }
  }

  return latest;
}

function isObjectComplete(before: string, fromIndex: number): boolean {
  const afterFrom = before.substring(fromIndex + 4).trim();
  const parts = afterFrom.split(/\s+/);
  return parts.length > 1 && parts[0].length > 0;
}

function getPartialWord(soql: string, cursorPos: number): { word: string; start: number } {
  let start = cursorPos;
  while (start > 0) {
    const ch = soql[start - 1];
    if (/[\w.]/.test(ch)) {
      start--;
    } else {
      break;
    }
  }
  return { word: soql.substring(start, cursorPos), start };
}

function formatFieldDetail(field: FieldDescribe): string {
  if (field.type === 'reference') {
    return `ref → ${field.referenceTo.join(', ')}`;
  }
  if (field.length > 0 && ['string', 'textarea', 'phone', 'email', 'url'].includes(field.type)) {
    return `${field.type}(${field.length})`;
  }
  return field.type;
}

function filterByPrefix(items: Suggestion[], prefix: string): Suggestion[] {
  if (!prefix) return items;
  const lower = prefix.toLowerCase();
  return items.filter(
    (s) => s.label.toLowerCase().startsWith(lower) || s.value.toLowerCase().startsWith(lower)
  );
}

// ── Hook ──

export function useSoqlAutocomplete(
  textareaRef: React.RefObject<HTMLTextAreaElement | null>,
  soql: string,
  setSoql: (soql: string) => void
) {
  const session = useStore((s) => s.session);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const [objectNames, setObjectNames] = useState<DescribeGlobalSObjectResult[]>([]);
  const [fieldCache, setFieldCache] = useState<Map<string, FieldDescribe[]>>(new Map());
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(null);

  useEffect(() => {
    if (!session) return;
    (async () => {
      const cached = await getCached<DescribeGlobalSObjectResult[]>('global-describe', session.orgId);
      if (cached) {
        setObjectNames(cached);
        return;
      }
      try {
        const result = await describeGlobal();
        const queryable = result.sobjects.filter((o) => o.queryable);
        setObjectNames(queryable);
        await setCache('global-describe', session.orgId, queryable, CACHE_TTL.GLOBAL_DESCRIBE);
      } catch {
        // autocomplete just won't have object suggestions
      }
    })();
  }, [session]);

  const loadFields = useCallback(
    async (objectName: string): Promise<FieldDescribe[]> => {
      if (fieldCache.has(objectName.toLowerCase())) {
        return fieldCache.get(objectName.toLowerCase())!;
      }
      if (!session) return [];

      const cached = await getCached<{ fields: FieldDescribe[] }>(
        `describe:${objectName}`,
        session.orgId
      );
      if (cached) {
        setFieldCache((prev) => new Map(prev).set(objectName.toLowerCase(), cached.fields));
        return cached.fields;
      }

      try {
        const describe = await describeSObject(objectName);
        await setCache(`describe:${objectName}`, session.orgId, describe, CACHE_TTL.OBJECT_DESCRIBE);
        setFieldCache((prev) => new Map(prev).set(objectName.toLowerCase(), describe.fields));
        return describe.fields;
      } catch {
        return [];
      }
    },
    [session, fieldCache]
  );

  const buildFieldSuggestions = useCallback(
    async (word: string, includeFunctions: boolean): Promise<Suggestion[]> => {
      const objName = extractObjectName(soql);
      const items: Suggestion[] = [];
      const filter = word.toLowerCase();

      if (objName) {
        const fields = await loadFields(objName);
        const dotParts = word.split('.');

        if (dotParts.length > 1) {
          const relName = dotParts.slice(0, -1).join('.');
          const partial = dotParts[dotParts.length - 1].toLowerCase();
          const relField = fields.find(
            (f) => f.relationshipName?.toLowerCase() === relName.toLowerCase()
          );
          if (relField && relField.referenceTo.length > 0) {
            const relFields = await loadFields(relField.referenceTo[0]);
            items.push(
              ...relFields
                .filter((f) => f.name.toLowerCase().startsWith(partial))
                .slice(0, 15)
                .map((f) => ({
                  label: `${relName}.${f.name}`,
                  value: `${relName}.${f.name}`,
                  detail: formatFieldDetail(f),
                  kind: 'field' as const,
                }))
            );
          }
          return items;
        }

        const fieldItems = fields
          .filter((f) => f.name.toLowerCase().includes(filter) || f.label.toLowerCase().includes(filter))
          .slice(0, 15)
          .map((f) => ({
            label: f.name,
            value: f.name,
            detail: formatFieldDetail(f),
            kind: 'field' as const,
          }));
        items.push(...fieldItems);

        const relItems = fields
          .filter(
            (f) =>
              f.relationshipName &&
              (f.relationshipName.toLowerCase().includes(filter) ||
               f.name.toLowerCase().includes(filter))
          )
          .slice(0, 8)
          .map((f) => ({
            label: `${f.relationshipName}.`,
            value: `${f.relationshipName}.`,
            detail: `→ ${f.referenceTo.join(', ')}`,
            kind: 'relationship' as const,
          }));
        items.push(...relItems);
      }

      if (includeFunctions && word.length >= 1) {
        items.push(...filterByPrefix(ALL_SELECT_FUNCTIONS, filter));
      }

      return items;
    },
    [soql, loadFields]
  );

  const updateSuggestions = useCallback(async () => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const cursorPos = textarea.selectionStart;
    const context = getSoqlContext(soql, cursorPos);
    const { word } = getPartialWord(soql, cursorPos);

    if (context === 'none' || word.length === 0) {
      setSuggestions([]);
      setIsOpen(false);
      return;
    }

    let items: Suggestion[] = [];

    switch (context) {
      case 'select': {
        items = await buildFieldSuggestions(word, true);
        break;
      }

      case 'from': {
        const filter = word.toLowerCase();
        items = objectNames
          .filter((o) => o.name.toLowerCase().startsWith(filter) || o.label.toLowerCase().startsWith(filter))
          .slice(0, 15)
          .map((o) => ({
            label: o.name,
            value: o.name,
            detail: o.custom ? 'Custom Object' : 'Standard Object',
            kind: 'object' as const,
          }));
        break;
      }

      case 'where':
      case 'having': {
        items = await buildFieldSuggestions(word, true);
        const dlMatches = filterByPrefix(DATE_LITERALS, word);
        const kwMatches = filterByPrefix(
          CLAUSE_KEYWORDS.filter((k) => ['AND', 'OR', 'NOT', 'IN', 'NOT IN', 'LIKE', 'INCLUDES', 'EXCLUDES', 'TRUE', 'FALSE', 'NULL'].includes(k.label)),
          word
        );
        items.push(...dlMatches.slice(0, 8), ...kwMatches);
        break;
      }

      case 'orderby':
      case 'groupby': {
        items = await buildFieldSuggestions(word, true);
        if (context === 'orderby') {
          const orderKw = filterByPrefix(
            CLAUSE_KEYWORDS.filter((k) => ['ASC', 'DESC', 'NULLS FIRST', 'NULLS LAST'].includes(k.label)),
            word
          );
          items.push(...orderKw);
        }
        break;
      }

      case 'scope': {
        items = filterByPrefix(SCOPE_VALUES, word);
        break;
      }

      case 'keyword': {
        items = filterByPrefix(CLAUSE_KEYWORDS, word);
        if (soql.trim().length === 0 || word.toLowerCase().startsWith('s')) {
          items.push(...filterByPrefix(SOQL_SNIPPETS, word));
        }
        break;
      }
    }

    items = items.slice(0, 20);
    setSuggestions(items);
    setSelectedIndex(0);
    setIsOpen(items.length > 0);
  }, [soql, textareaRef, objectNames, buildFieldSuggestions]);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(updateSuggestions, 150);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [updateSuggestions]);

  const insertSuggestion = useCallback(
    (suggestion: Suggestion) => {
      const textarea = textareaRef.current;
      if (!textarea) return;

      const cursorPos = textarea.selectionStart;
      const { start } = getPartialWord(soql, cursorPos);
      const newSoql = soql.substring(0, start) + suggestion.value + soql.substring(cursorPos);
      setSoql(newSoql);

      const newCursorPos = start + suggestion.value.length;
      requestAnimationFrame(() => {
        textarea.focus();
        textarea.setSelectionRange(newCursorPos, newCursorPos);
      });

      setIsOpen(false);
      setSuggestions([]);
    },
    [soql, setSoql, textareaRef]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent): boolean => {
      if (!isOpen || suggestions.length === 0) return false;

      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          setSelectedIndex((i) => (i + 1) % suggestions.length);
          return true;
        case 'ArrowUp':
          e.preventDefault();
          setSelectedIndex((i) => (i - 1 + suggestions.length) % suggestions.length);
          return true;
        case 'Tab':
        case 'Enter':
          if (isOpen && suggestions.length > 0) {
            e.preventDefault();
            insertSuggestion(suggestions[selectedIndex]);
            return true;
          }
          return false;
        case 'Escape':
          e.preventDefault();
          setIsOpen(false);
          return true;
        default:
          return false;
      }
    },
    [isOpen, suggestions, selectedIndex, insertSuggestion]
  );

  const close = useCallback(() => {
    setIsOpen(false);
    setSuggestions([]);
  }, []);

  return {
    suggestions,
    selectedIndex,
    isOpen,
    handleKeyDown,
    insertSuggestion,
    close,
  };
}
