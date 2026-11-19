// Small text helpers shared by the components. The output is passed to
// [innerHTML], so everything is HTML-escaped first and Angular sanitizes it again.

export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// The explanation uses a little Markdown: **bold**, `code` and "- " bullet lists.
export function miniMarkdown(text: string): string {
  const inline = (s: string) =>
    escapeHtml(s)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

  const out: string[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) out.push(`<ul>${list.map((li) => `<li>${li}</li>`).join('')}</ul>`);
    list = [];
  };
  // The model sometimes uses narrow/no-break spaces (U+202F, U+00A0...), which render as odd gaps.
  const clean = text.replace(/[    ]/g, ' ').trim();
  for (const line of clean.split('\n')) {
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (bullet) {
      list.push(inline(bullet[1]));
    } else {
      flush();
      out.push(inline(line.trim()));
    }
  }
  flush();
  return out.join('<br>').replace(/<br>(<ul>)/g, '$1').replace(/(<\/ul>)<br>/g, '$1');
}

const KEYWORDS = new Set(
  ('select from where group by order having limit offset join left right inner outer full cross on as and or not ' +
    'in is null like between case when then else end distinct with union all desc asc over partition exists')
    .split(' '),
);
const FUNCTIONS = new Set(
  'count sum avg min max round strftime date datetime coalesce ifnull lower upper length substr cast total abs'.split(' '),
);
const CLAUSES = /\s+(FROM|WHERE|GROUP BY|ORDER BY|HAVING|LIMIT|(?:LEFT |RIGHT |INNER |CROSS |FULL )?(?:OUTER )?JOIN|UNION(?: ALL)?)\b/gi;

// Puts each main clause on its own line (one-line SQL only) and colours the tokens.
export function highlightSql(sql: string): string {
  // Split out string literals so nothing inside them gets changed.
  const parts = sql.trim().split(/('(?:[^']|'')*')/);
  const oneLine = !sql.trim().includes('\n');
  return parts
    .map((part, i) => {
      if (i % 2 === 1) return `<span class="str">${escapeHtml(part)}</span>`;
      const text = oneLine ? part.replace(CLAUSES, (_, c: string) => `\n${c.toUpperCase()}`) : part;
      return escapeHtml(text).replace(/\b([A-Za-z_]+|\d+(?:\.\d+)?)\b(\s*\()?/g, (m, word: string, paren?: string) => {
        const lower = word.toLowerCase();
        if (/^\d/.test(word)) return `<span class="num">${word}</span>${paren ?? ''}`;
        if (paren && FUNCTIONS.has(lower)) return `<span class="fn">${word}</span>${paren}`;
        if (KEYWORDS.has(lower)) return `<span class="kw">${word}</span>${paren ?? ''}`;
        return m;
      });
    })
    .join('');
}

// Numbers get thousands separators from 10,000 up (so years and IDs stay as they are);
// pass `group` to decide for a whole table column at once.
// en-US grouping (485,800) matches how the model writes numbers in its explanation.
export function formatCell(value: unknown, group?: boolean): string {
  if (value === null || value === undefined) return 'NULL';
  if (typeof value === 'number') {
    return value.toLocaleString('en-US', {
      maximumFractionDigits: 2,
      useGrouping: group ?? Math.abs(value) >= 10000,
    });
  }
  return String(value);
}

export function prettyLabel(column: string): string {
  const s = column.replace(/_/g, ' ').trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function toCsv(columns: string[], rows: unknown[][]): string {
  const cell = (v: unknown) => {
    const s = v === null || v === undefined ? '' : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns, ...rows].map((r) => r.map(cell).join(',')).join('\n');
}
