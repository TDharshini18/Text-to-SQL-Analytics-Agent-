import { Component, computed, effect, input, output, signal, untracked } from '@angular/core';
import { highlightSql } from '../../format';

// The generated SQL: highlighted, copyable, and editable so the user can fix it and run it again.
@Component({
  selector: 'app-sql-display',
  template: `
    <div class="box" [class.editing]="editing()">
      <div class="bar">
        <span class="label">SQL{{ edited() ? ' · edited' : '' }}</span>
        <div class="actions">
          @if (editing()) {
            <button type="button" class="btn quiet" (click)="cancel()">Cancel</button>
            <button type="button" class="btn solid" (click)="submit()" [disabled]="running() || !draft().trim()">
              {{ running() ? 'Running…' : 'Run' }}
            </button>
          } @else {
            @if (edited()) {
              <button type="button" class="btn quiet" (click)="reset.emit()">Reset</button>
            }
            <button type="button" class="btn quiet" (click)="copy()">{{ copied() ? 'Copied' : 'Copy' }}</button>
            @if (editable()) {
              <button type="button" class="btn quiet" (click)="startEdit()">Edit</button>
            }
          }
        </div>
      </div>
      @if (editing()) {
        <textarea
          class="editor"
          spellcheck="false"
          [value]="draft()"
          (input)="draft.set($any($event.target).value)"
          (keydown.control.enter)="submit()"
          (keydown.meta.enter)="submit()"
          aria-label="Edit SQL"
        ></textarea>
        <p class="hint">Ctrl + Enter to run · read-only, the same safety check applies</p>
      } @else {
        <pre class="sql"><code [innerHTML]="html()"></code></pre>
      }
      @if (runError()) {
        <p class="err">{{ runError() }}</p>
      }
    </div>
  `,
  styles: `
    .box { border: 1px solid var(--line); background: var(--subtle); }
    .box.editing { border-color: var(--line-strong); }
    .bar { display: flex; align-items: center; justify-content: space-between; gap: 8px; height: 40px; padding: 0 6px 0 14px; border-bottom: 1px solid var(--line); background: var(--surface); }
    .actions { display: flex; gap: 6px; }
    .actions .btn { height: 26px; padding: 0 10px; font-size: 11.5px; }
    pre { margin: 0; padding: 14px 16px; overflow-x: auto; font-family: var(--mono); font-size: 12.5px; line-height: 1.7; white-space: pre-wrap; }
    .editor { display: block; width: 100%; min-height: 160px; margin: 0; padding: 14px 16px; border: 0; outline: 0; resize: vertical; background: var(--surface); font-family: var(--mono); font-size: 12.5px; line-height: 1.7; }
    .hint { margin: 0; padding: 6px 14px; border-top: 1px solid var(--line); font-size: 11.5px; color: var(--muted); }
    .err { margin: 0; padding: 10px 14px; border-top: 1px solid var(--line-strong); font-family: var(--mono); font-size: 12px; background: var(--surface); }
  `,
})
export class SqlDisplayComponent {
  sql = input.required<string>();
  editable = input(false);
  edited = input(false);
  running = input(false);
  runError = input<string | null>(null);
  run = output<string>();
  reset = output<void>();
  version = input('');

  html = computed(() => highlightSql(this.sql()));
  editing = signal(false);
  draft = signal('');
  copied = signal(false);

  startEdit() {
    this.draft.set(this.sql());
    this.editing.set(true);
  }

  cancel() {
    this.editing.set(false);
  }

  submit() {
    const sql = this.draft().trim();
    if (!sql || this.running()) return;
    this.run.emit(sql);
  }

  constructor() {
    // The parent changes `version` after an edited query ran successfully: close the editor.
    effect(() => {
      if (this.version()) untracked(() => this.editing.set(false));
    });
  }

  copy() {
    navigator.clipboard?.writeText(this.sql()).then(() => {
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 1500);
    });
  }
}
