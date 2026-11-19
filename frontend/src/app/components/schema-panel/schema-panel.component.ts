import { Component, input, output, signal } from '@angular/core';
import { Schema } from '../../models';

// Sidebar list of the database's tables and columns. Tables used by the latest answer are marked.
@Component({
  selector: 'app-schema-panel',
  template: `
    <div class="head">
      <span class="label">Database</span>
      @if (schema()?.database; as db) { <span class="db" [title]="db">{{ db }}</span> }
    </div>
    @if (error()) {
      <p class="muted">Could not load the tables. Is the backend running?</p>
    } @else if (!schema()) {
      <div class="skeleton"></div>
      <div class="skeleton short"></div>
      <div class="skeleton"></div>
    } @else {
      <ul class="tables">
        @for (t of schema()!.tables; track t.name) {
          <li [class.linked]="linked().includes(t.name)">
            <button type="button" class="table" (click)="toggle(t.name)" [attr.aria-expanded]="open().has(t.name)">
              <svg class="chev" [class.rot]="open().has(t.name)" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
              <span class="name">{{ t.name }}</span>
              @if (linked().includes(t.name)) { <span class="tag" title="Used in the latest answer">linked</span> }
              <span class="n">{{ t.columns.length }}</span>
            </button>
            @if (open().has(t.name)) {
              <ul class="cols">
                @for (c of t.columns; track c.name) {
                  <li>
                    <button type="button" class="col" (click)="insert.emit(c.name)" [title]="'Add ' + c.name + ' to your question'">
                      <span>{{ c.name }}</span>
                      @if (c.primary_key) { <span class="key" title="Primary key">PK</span> }
                      @if (fk(t.name, c.name); as ref) { <span class="key" [title]="'References ' + ref">FK</span> }
                      <span class="type">{{ c.type.toLowerCase() }}</span>
                    </button>
                  </li>
                }
              </ul>
            }
          </li>
        }
      </ul>
    }
  `,
  styles: `
    :host { display: block; }
    .head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; padding: 0 4px 10px; border-bottom: 1px solid var(--line); margin-bottom: 6px; }
    .db { font-family: var(--mono); font-size: 11px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .muted { margin: 8px 4px; font-size: 13px; color: var(--muted); }
    ul { list-style: none; margin: 0; padding: 0; }
    .table { width: 100%; display: flex; align-items: center; gap: 8px; padding: 8px 6px; border: 0; border-left: 2px solid transparent; background: transparent; cursor: pointer; font-size: 13.5px; text-align: left; }
    .table:hover { background: var(--subtle); }
    .linked > .table { border-left-color: var(--line-strong); font-weight: 600; }
    .name { flex: 1; font-family: var(--mono); font-size: 12.5px; }
    .tag { font-family: var(--mono); font-size: 9.5px; letter-spacing: .06em; text-transform: uppercase; padding: 1px 5px; background: var(--invert-bg); color: var(--invert-text); font-weight: 500; }
    .n { font-family: var(--mono); font-size: 11px; color: var(--faint); font-weight: 400; }
    svg { flex: none; width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 2.2; stroke-linecap: square; color: var(--muted); transition: transform .15s; }
    .chev.rot { transform: rotate(90deg); }
    .cols { margin: 0 0 6px 12px; border-left: 1px solid var(--line); }
    .col { width: 100%; display: flex; align-items: center; gap: 6px; padding: 5px 8px 5px 14px; border: 0; background: none; cursor: pointer; text-align: left; font-family: var(--mono); font-size: 12px; }
    .col:hover { background: var(--subtle); }
    .col > span:first-child { flex: 1; overflow: hidden; text-overflow: ellipsis; }
    .key { font-size: 9.5px; padding: 0 4px; border: 1px solid var(--line-strong); }
    .type { color: var(--faint); font-size: 11px; }
    .skeleton { height: 28px; margin: 8px 0; background: var(--subtle); animation: pulse 1.2s ease-in-out infinite; }
    .skeleton.short { width: 70%; }
    @keyframes pulse { 50% { opacity: .5; } }
  `,
})
export class SchemaPanelComponent {
  schema = input<Schema | null>(null);
  error = input(false);
  linked = input<string[]>([]);
  insert = output<string>();
  open = signal<Set<string>>(new Set());

  toggle(name: string) {
    const next = new Set(this.open());
    next.has(name) ? next.delete(name) : next.add(name);
    this.open.set(next);
  }

  fk(table: string, column: string): string | null {
    const t = this.schema()?.tables.find((x) => x.name === table);
    return t?.foreign_keys.find((f) => f.column === column)?.references ?? null;
  }
}
