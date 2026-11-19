import { Component, computed, input, signal } from '@angular/core';
import { formatCell, prettyLabel, toCsv } from '../../format';

// The query results: one large figure for a single value, otherwise a sortable table.
@Component({
  selector: 'app-results-table',
  template: `
    <div class="head">
      <span class="label">
        Result · {{ rows().length }} {{ rows().length === 1 ? 'row' : 'rows' }}{{ truncated() ? ' (limit reached)' : '' }}
      </span>
      @if (rows().length > 0) {
        <div class="actions">
          <button type="button" class="btn quiet" (click)="copyCsv()">{{ copied() ? 'Copied' : 'Copy CSV' }}</button>
          <button type="button" class="btn quiet" (click)="downloadCsv()">Download</button>
        </div>
      }
    </div>

    @if (rows().length === 0) {
      <p class="empty">The query ran but returned no rows.</p>
    } @else if (single()) {
      <div class="stat">
        <span class="stat-value">{{ fmt(rows()[0][0]) }}</span>
        <span class="stat-label">{{ label(columns()[0]) }}</span>
      </div>
    } @else {
      <div class="wrap">
        <table>
          <thead>
            <tr>
              <th class="idx">#</th>
              @for (col of columns(); track $index) {
                <th [class.num]="numeric()[$index]">
                  <button type="button" (click)="sortBy($index)" [attr.aria-sort]="sortAria($index)">
                    {{ label(col) }}
                    <span class="arrow">{{ sort()?.col === $index ? (sort()!.dir === 1 ? '↑' : '↓') : '' }}</span>
                  </button>
                </th>
              }
            </tr>
          </thead>
          <tbody>
            @for (row of sorted(); track $index) {
              <tr>
                <td class="idx">{{ $index + 1 }}</td>
                @for (cell of row; track $index) {
                  <td [class.num]="numeric()[$index]" [class.null]="cell === null">{{ fmt(cell, grouped()[$index]) }}</td>
                }
              </tr>
            }
          </tbody>
        </table>
      </div>
    }
  `,
  styles: `
    :host { display: block; }
    .head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; min-height: 26px; }
    .actions { display: flex; gap: 6px; }
    .actions .btn { height: 26px; padding: 0 10px; font-size: 11.5px; }
    .empty { margin: 0; padding: 16px; border: 1px solid var(--line); color: var(--muted); font-size: 14px; }
    .stat { display: flex; flex-direction: column; gap: 4px; padding: 20px 22px; border: 1px solid var(--line-strong); }
    .stat-value { font-size: 40px; font-weight: 700; letter-spacing: -.03em; line-height: 1; font-variant-numeric: tabular-nums; }
    .stat-label { font-size: 13px; color: var(--muted); }
    .wrap { max-height: 420px; overflow: auto; border: 1px solid var(--line); }
    table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
    th { position: sticky; top: 0; z-index: 1; background: var(--surface); border-bottom: 1px solid var(--line-strong); text-align: left; padding: 0; }
    th button { width: 100%; display: flex; align-items: center; gap: 4px; padding: 10px 14px; border: 0; background: none; cursor: pointer; font-size: 11.5px; font-weight: 600; letter-spacing: .03em; text-transform: uppercase; color: var(--muted); white-space: nowrap; text-align: inherit; }
    th button:hover { color: var(--text); }
    th.num button { justify-content: flex-end; }
    .arrow { display: inline-block; width: 10px; color: var(--text); }
    td { padding: 9px 14px; border-bottom: 1px solid var(--line); }
    tbody tr:last-child td { border-bottom: 0; }
    tbody tr:hover td { background: var(--subtle); }
    .idx { width: 1%; padding-right: 6px; color: var(--faint); font-family: var(--mono); font-size: 11px; text-align: right; }
    th.idx { padding: 10px 6px 10px 14px; font-family: var(--mono); font-size: 11px; font-weight: 500; color: var(--faint); }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .null { color: var(--faint); font-family: var(--mono); font-size: 12px; }
  `,
})
export class ResultsTableComponent {
  columns = input.required<string[]>();
  rows = input.required<unknown[][]>();
  truncated = input(false);
  copied = signal(false);
  sort = signal<{ col: number; dir: 1 | -1 } | null>(null);

  single = computed(() => this.rows().length === 1 && this.columns().length === 1);

  // A column is numeric when every non-null value in it is a number.
  numeric = computed(() =>
    this.columns().map((_, i) => {
      const values = this.rows().map((r) => r[i]).filter((v) => v !== null && v !== undefined);
      return values.length > 0 && values.every((v) => typeof v === 'number');
    }),
  );

  // Use thousands separators for a whole column when any of its numbers is 10,000 or more.
  grouped = computed(() =>
    this.columns().map((_, i) => this.rows().some((r) => typeof r[i] === 'number' && Math.abs(r[i] as number) >= 10000)),
  );

  sorted = computed(() => {
    const s = this.sort();
    if (!s) return this.rows();
    return [...this.rows()].sort((a, b) => {
      const x = a[s.col], y = b[s.col];
      if (x === y) return 0;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))) * s.dir;
    });
  });

  fmt = formatCell;
  label = prettyLabel;

  sortBy(col: number) {
    const s = this.sort();
    if (!s || s.col !== col) this.sort.set({ col, dir: 1 });
    else if (s.dir === 1) this.sort.set({ col, dir: -1 });
    else this.sort.set(null); // third click: back to the query's own order
  }

  sortAria(col: number) {
    const s = this.sort();
    return s?.col === col ? (s.dir === 1 ? 'ascending' : 'descending') : null;
  }

  copyCsv() {
    navigator.clipboard?.writeText(toCsv(this.columns(), this.sorted())).then(() => {
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 1500);
    });
  }

  downloadCsv() {
    const blob = new Blob([toCsv(this.columns(), this.sorted())], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'results.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  }
}
