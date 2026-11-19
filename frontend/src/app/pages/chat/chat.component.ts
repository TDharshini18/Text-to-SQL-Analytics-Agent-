import { HttpErrorResponse } from '@angular/common/http';
import { Component, ElementRef, computed, inject, signal, viewChild } from '@angular/core';
import { Subscription } from 'rxjs';
import { AgentTraceComponent } from '../../components/agent-trace/agent-trace.component';
import { ChatInputComponent } from '../../components/chat-input/chat-input.component';
import { ResultsTableComponent } from '../../components/results-table/results-table.component';
import { SchemaPanelComponent } from '../../components/schema-panel/schema-panel.component';
import { SqlDisplayComponent } from '../../components/sql-display/sql-display.component';
import { miniMarkdown } from '../../format';
import { AgentEvent, Schema, Turn } from '../../models';
import { SqlAiService } from '../../services/sql-ai.service';

const EXAMPLES = [
  'Show me the top 5 customers by total revenue',
  'Which city has the most orders?',
  'What is the best-selling product category in 2026?',
  'Monthly revenue for 2025',
];

// The one page: tables on the left, the conversation on the right.
@Component({
  selector: 'app-chat',
  imports: [ChatInputComponent, SqlDisplayComponent, ResultsTableComponent, SchemaPanelComponent, AgentTraceComponent],
  template: `
    <div class="layout" [class.nav-open]="sidebarOpen()">
      <aside class="sidebar">
        <div class="brand">
          <span class="mark" aria-hidden="true"></span>
          <span>Text-to-SQL</span>
        </div>
        <button type="button" class="btn new-chat" (click)="newChat()" [disabled]="turns().length === 0">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg> New chat
        </button>
        <app-schema-panel
          [schema]="schema()"
          [error]="schemaError()"
          [linked]="lastLinked()"
          (insert)="input().append($event)"
        />
        <p class="foot">Read-only · queries are safety-checked</p>
      </aside>
      <div class="scrim" (click)="sidebarOpen.set(false)"></div>

      <div class="main">
        <header class="topbar">
          <button type="button" class="menu" (click)="sidebarOpen.set(!sidebarOpen())" aria-label="Show tables">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
          </button>
          <span class="brand"><span class="mark" aria-hidden="true"></span>Text-to-SQL</span>
        </header>

        <div class="scroll" #scroll>
          <div class="thread">
            @if (turns().length === 0) {
              <section class="welcome">
                <span class="label">Analytics agent</span>
                <h1>Ask your database a question.</h1>
                <p>
                  Plain English in. The agent links your question to the right tables, writes the SQL,
                  repairs it if the database rejects it, and explains the result.
                </p>
                <div class="examples">
                  @for (ex of examples; track ex; let i = $index) {
                    <button type="button" class="example" (click)="ask(ex)">
                      <span class="ex-n">{{ '0' + (i + 1) }}</span>
                      <span class="ex-text">{{ ex }}</span>
                      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
                    </button>
                  }
                </div>
              </section>
            }

            @for (t of turns(); track t.id; let i = $index) {
              <article class="turn">
                <header class="q">
                  <span class="q-n">{{ (i + 1).toString().padStart(2, '0') }}</span>
                  <h2>{{ t.question }}</h2>
                </header>

                <app-agent-trace [turn]="t" />

                @switch (t.status) {
                  @case ('error') {
                    <div class="error" role="alert">
                      <span class="label">Could not answer</span>
                      <p>{{ t.error!.message }}</p>
                      <button type="button" class="btn" (click)="retry(t)" [disabled]="busy()">Try again</button>
                    </div>
                    @if (t.error!.sql) {
                      <app-sql-display
                        [sql]="t.error!.sql"
                        [editable]="true"
                        [running]="sqlRunning() === t.id"
                        [runError]="sqlErrors()[t.id] ?? null"
                        (run)="runSql(t, $event)"
                      />
                    }
                    @if (t.edited; as e) {
                      <app-results-table [columns]="e.columns" [rows]="e.results" [truncated]="!!e.truncated" />
                    }
                  }
                  @case ('done') {
                    <div class="md explanation" [innerHTML]="md(t.response!.explanation)"></div>
                    <div class="review">
                      <app-sql-display
                        [sql]="t.edited?.sql ?? t.response!.sql"
                        [editable]="true"
                        [edited]="!!t.edited"
                        [running]="sqlRunning() === t.id"
                        [runError]="sqlErrors()[t.id] ?? null"
                        [version]="t.edited ? 'run' + t.edited.runs : ''"
                        (run)="runSql(t, $event)"
                        (reset)="resetSql(t)"
                      />
                      <app-results-table
                        [columns]="t.edited?.columns ?? t.response!.columns"
                        [rows]="t.edited?.results ?? t.response!.results"
                        [truncated]="!!(t.edited ? t.edited.truncated : t.response!.truncated)"
                      />
                    </div>
                  }
                }
              </article>
            }
          </div>
        </div>

        <footer class="composer">
          <app-chat-input [loading]="busy()" [lastQuestion]="lastQuestion()" (ask)="ask($event)" />
        </footer>
      </div>
    </div>
  `,
  styles: `
    :host { display: block; height: 100vh; height: 100dvh; }
    .layout { display: grid; grid-template-columns: 272px 1fr; height: 100%; }
    svg { fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: square; }

    /* Sidebar */
    .sidebar { display: flex; flex-direction: column; gap: 18px; padding: 20px 14px 14px; border-right: 1px solid var(--line-strong); background: var(--surface); overflow-y: auto; }
    .brand { display: flex; align-items: center; gap: 10px; padding: 0 4px; font-weight: 700; font-size: 15px; letter-spacing: -.01em; }
    .mark { width: 14px; height: 14px; background: var(--invert-bg); outline: 1px solid var(--line-strong); outline-offset: 2px; }
    .new-chat { justify-content: center; height: 36px; font-size: 13px; }
    app-schema-panel { flex: 1; }
    .foot { margin: 0; padding: 10px 4px 0; border-top: 1px solid var(--line); font-size: 11.5px; color: var(--muted); }
    .scrim { display: none; }

    /* Main column */
    .main { display: flex; flex-direction: column; min-width: 0; height: 100%; }
    .topbar { display: none; }
    .scroll { flex: 1; overflow-y: auto; }
    .thread { max-width: 860px; margin: 0 auto; padding: 40px 32px 24px; display: flex; flex-direction: column; gap: 56px; }
    .composer { padding: 12px 32px 16px; border-top: 1px solid var(--line); background: var(--bg); }
    .composer app-chat-input { display: block; max-width: 860px; margin: 0 auto; }

    /* Welcome */
    .welcome { padding: 6vh 0 0; animation: rise .3s ease-out; }
    h1 { margin: 12px 0 0; font-size: 40px; font-weight: 700; letter-spacing: -.035em; line-height: 1.1; }
    .welcome p { max-width: 560px; margin: 16px 0 36px; color: var(--muted); line-height: 1.6; }
    .examples { border-top: 1px solid var(--line-strong); }
    .example { width: 100%; display: flex; align-items: center; gap: 18px; padding: 16px 4px; border: 0; border-bottom: 1px solid var(--line); background: none; cursor: pointer; text-align: left; font-size: 15px; transition: padding .15s, background .15s; }
    .example:hover { background: var(--subtle); padding-left: 12px; }
    .ex-n { font-family: var(--mono); font-size: 11px; color: var(--faint); }
    .ex-text { flex: 1; }
    .example svg { width: 16px; height: 16px; opacity: 0; transition: opacity .15s; }
    .example:hover svg { opacity: 1; }

    /* A question and its answer */
    .turn { display: flex; flex-direction: column; gap: 16px; animation: rise .25s ease-out; }
    .q { display: flex; align-items: baseline; gap: 14px; padding-bottom: 14px; border-bottom: 1px solid var(--line-strong); }
    .q-n { font-family: var(--mono); font-size: 12px; color: var(--faint); }
    h2 { margin: 0; font-size: 22px; font-weight: 650; letter-spacing: -.02em; line-height: 1.3; word-wrap: break-word; min-width: 0; }
    .explanation { font-size: 15.5px; line-height: 1.7; }
    .review { display: flex; flex-direction: column; gap: 16px; }

    .error { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; padding: 16px; border: 1px solid var(--line-strong); border-left-width: 4px; }
    .error p { margin: 0; line-height: 1.55; }

    @keyframes rise { from { opacity: 0; transform: translateY(6px); } }

    /* Small screens: the sidebar slides in from the left */
    @media (max-width: 860px) {
      .layout { grid-template-columns: 1fr; }
      .sidebar { position: fixed; inset: 0 auto 0 0; width: 280px; z-index: 20; transform: translateX(-100%); transition: transform .2s ease; }
      .nav-open .sidebar { transform: none; }
      .nav-open .scrim { display: block; position: fixed; inset: 0; z-index: 10; background: rgba(0, 0, 0, .4); }
      .topbar { display: flex; align-items: center; gap: 8px; height: 52px; padding: 0 10px; border-bottom: 1px solid var(--line-strong); }
      .menu { display: grid; place-items: center; width: 36px; height: 36px; border: 0; background: none; cursor: pointer; }
      .menu svg { width: 20px; height: 20px; }
      .thread { padding: 24px 16px 16px; gap: 40px; }
      .composer { padding: 10px 12px 12px; }
      h1 { font-size: 30px; }
      h2 { font-size: 19px; }
    }

    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { animation: none !important; transition: none !important; }
    }
  `,
})
export class ChatComponent {
  private api = inject(SqlAiService);
  private scroll = viewChild.required<ElementRef<HTMLElement>>('scroll');
  input = viewChild.required(ChatInputComponent);
  private nextId = 1;
  private stream?: Subscription;

  examples = EXAMPLES;
  turns = signal<Turn[]>([]);
  busy = signal(false);
  schema = signal<Schema | null>(null);
  schemaError = signal(false);
  sidebarOpen = signal(false);
  sqlRunning = signal<number | null>(null);
  sqlErrors = signal<Record<number, string>>({});

  lastQuestion = computed(() => this.turns().at(-1)?.question ?? '');
  lastLinked = computed(() => {
    const ts = this.turns();
    for (let i = ts.length - 1; i >= 0; i--) if (ts[i].linking) return ts[i].linking!.tables;
    return [];
  });

  md = miniMarkdown;

  constructor() {
    this.api.schema().subscribe({
      next: (s) => this.schema.set(s),
      error: () => this.schemaError.set(true),
    });
  }

  ask(question: string) {
    if (this.busy()) return;
    const id = this.nextId++;
    this.turns.update((ts) => [...ts, { id, question, status: 'loading', current: 'Starting', attempts: [] }]);
    this.run(id, question);
  }

  retry(turn: Turn) {
    if (this.busy()) return;
    this.update(turn.id, () => ({
      status: 'loading', current: 'Starting', attempts: [], linking: undefined,
      widened: false, error: undefined, edited: undefined,
    }));
    this.run(turn.id, turn.question);
  }

  newChat() {
    this.stream?.unsubscribe();
    this.busy.set(false);
    this.turns.set([]);
    this.sqlErrors.set({});
    this.sidebarOpen.set(false);
    this.input().focus();
  }

  runSql(turn: Turn, sql: string) {
    this.sqlRunning.set(turn.id);
    this.setSqlError(turn.id, null);
    this.api.runSql(sql).subscribe({
      next: (res) => {
        this.update(turn.id, (t) => ({
          edited: { sql: res.sql, columns: res.columns, results: res.results, truncated: res.truncated, runs: (t.edited?.runs ?? 0) + 1 },
        }));
        this.sqlRunning.set(null);
      },
      error: (err: HttpErrorResponse) => {
        const msg = err.status === 0 ? 'Cannot reach the backend.' : (err.error?.detail ?? `HTTP ${err.status}`);
        this.setSqlError(turn.id, String(msg));
        this.sqlRunning.set(null);
      },
    });
  }

  resetSql(turn: Turn) {
    this.update(turn.id, () => ({ edited: undefined }));
    this.setSqlError(turn.id, null);
  }

  private run(id: number, question: string) {
    this.busy.set(true);
    this.scrollToBottom();
    this.stream = this.api.askStream(question).subscribe({
      next: (e) => this.onEvent(id, e),
      complete: () => {
        // A stream that ends without a result or an error is still a failure.
        const t = this.turns().find((x) => x.id === id);
        if (t?.status === 'loading') {
          this.update(id, () => ({ status: 'error', error: { message: 'The response ended unexpectedly.' } }));
        }
        this.busy.set(false);
        this.scrollToBottom();
        this.input().focus();
      },
    });
  }

  private onEvent(id: number, e: AgentEvent) {
    switch (e.type) {
      case 'status':
        this.update(id, () => ({ current: e.message }));
        break;
      case 'linking': {
        const { type, ...linking } = e;
        this.update(id, () => ({ linking }));
        break;
      }
      case 'attempt': {
        const { type, ...attempt } = e;
        this.update(id, (t) => ({ attempts: [...t.attempts, attempt] }));
        break;
      }
      case 'widened':
        this.update(id, () => ({ widened: true }));
        break;
      case 'result':
        this.update(id, () => ({ status: 'done', response: e.response, current: undefined }));
        break;
      case 'error':
        this.update(id, () => ({ status: 'error', error: { message: e.message, sql: e.sql }, current: undefined }));
        break;
    }
    this.scrollToBottom(true);
  }

  private update(id: number, patch: (t: Turn) => Partial<Turn>) {
    this.turns.update((ts) => ts.map((t) => (t.id === id ? { ...t, ...patch(t) } : t)));
  }

  private setSqlError(id: number, msg: string | null) {
    this.sqlErrors.update((m) => {
      const next = { ...m };
      if (msg) next[id] = msg;
      else delete next[id];
      return next;
    });
  }

  // Follow new content, but don't yank the view if the user scrolled up to read.
  private scrollToBottom(onlyIfNear = false) {
    const el = this.scroll().nativeElement;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 200;
    if (onlyIfNear && !near) return;
    setTimeout(() => el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }));
  }
}
