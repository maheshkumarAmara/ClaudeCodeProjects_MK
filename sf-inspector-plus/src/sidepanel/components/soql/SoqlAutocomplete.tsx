import { useEffect, useRef, useState } from 'react';
import type { Suggestion } from '@/hooks/useSoqlAutocomplete';

interface SoqlAutocompleteProps {
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  suggestions: Suggestion[];
  selectedIndex: number;
  isOpen: boolean;
  onSelect: (suggestion: Suggestion) => void;
}

function getCursorCoords(
  textarea: HTMLTextAreaElement,
  position: number
): { top: number; left: number } {
  const mirror = document.createElement('div');
  const style = window.getComputedStyle(textarea);

  mirror.style.position = 'absolute';
  mirror.style.visibility = 'hidden';
  mirror.style.whiteSpace = 'pre-wrap';
  mirror.style.wordWrap = 'break-word';
  mirror.style.overflow = 'hidden';
  mirror.style.width = style.width;
  mirror.style.height = style.height;
  mirror.style.fontFamily = style.fontFamily;
  mirror.style.fontSize = style.fontSize;
  mirror.style.fontWeight = style.fontWeight;
  mirror.style.lineHeight = style.lineHeight;
  mirror.style.letterSpacing = style.letterSpacing;
  mirror.style.padding = style.padding;
  mirror.style.border = style.border;
  mirror.style.boxSizing = style.boxSizing;

  const textBefore = textarea.value.substring(0, position);
  const textNode = document.createTextNode(textBefore);
  const span = document.createElement('span');
  span.textContent = '\u200b';

  mirror.appendChild(textNode);
  mirror.appendChild(span);
  document.body.appendChild(mirror);

  const spanRect = span.getBoundingClientRect();
  const mirrorRect = mirror.getBoundingClientRect();

  const top = spanRect.top - mirrorRect.top - textarea.scrollTop;
  const left = spanRect.left - mirrorRect.left - textarea.scrollLeft;

  document.body.removeChild(mirror);

  return { top, left };
}

export function SoqlAutocomplete({
  textareaRef,
  suggestions,
  selectedIndex,
  isOpen,
  onSelect,
}: SoqlAutocompleteProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ top: 0, left: 0 });

  useEffect(() => {
    if (!isOpen || !textareaRef.current) return;
    const textarea = textareaRef.current;
    const coords = getCursorCoords(textarea, textarea.selectionStart);
    setPosition({
      top: coords.top + parseInt(window.getComputedStyle(textarea).lineHeight || '20') + 2,
      left: Math.min(coords.left, textarea.offsetWidth - 260),
    });
  }, [isOpen, textareaRef, suggestions]);

  useEffect(() => {
    if (!listRef.current) return;
    const selected = listRef.current.children[selectedIndex] as HTMLElement;
    if (selected) {
      selected.scrollIntoView({ block: 'nearest' });
    }
  }, [selectedIndex]);

  if (!isOpen || suggestions.length === 0) return null;

  return (
    <div
      className="autocomplete-dropdown"
      style={{ top: position.top, left: Math.max(0, position.left) }}
      ref={listRef}
    >
      {suggestions.map((s, i) => (
        <div
          key={`${s.value}-${i}`}
          className={`autocomplete-item ${i === selectedIndex ? 'selected' : ''}`}
          onMouseDown={(e) => {
            e.preventDefault();
            onSelect(s);
          }}
          onMouseEnter={() => {
            // Allow mouse to highlight without affecting keyboard selection
          }}
        >
          <span className="autocomplete-label">
            {s.kind === 'relationship' && <span className="rel-icon">→ </span>}
            {s.label}
          </span>
          <span className="autocomplete-detail">{s.detail}</span>
        </div>
      ))}
    </div>
  );
}
