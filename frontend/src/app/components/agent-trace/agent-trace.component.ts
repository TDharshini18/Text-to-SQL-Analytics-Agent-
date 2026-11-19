import { Component, computed, input, signal } from '@angular/core';
import { Turn } from '../../models';

type StepState = 'waiting' | 'running' | 'done' | 'failed';

// What the agents did for one question: schema linking, each SQL attempt (with the
// database error that triggered a repair) and the explanation. Live while running.
@Component({
  selector: 'app-agent-trace',
  template: `
    <div class="trace" [class.open]="expanded()">
      <button type="button" class="summary" (click)="open.set(!open())" [disabled]="live()" [attr.aria-expanded]="expanded()">
        <span class="label">Agent steps</span>
        <span class="sum-text">
          @if (live()) {
            <span class="pulse" aria-hidden="true"></span>{{ turn().current }}
          } @else {
            {{ summary() }}
          }
        </span>
        @if (!live()) {
          <svg class="chev" [class.rot]="expanded()" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
        }
      </button>

      @if (expanded()) {
        <ol class="steps">
          <!-- 1. Schema linking -->
          <li [attr.data-state]="linkState()">
            <span class="num">01</span>
            <div class="content">
              <div class="title">Schema linking
                @if (turn().linking; as l) {
                  <span class="meta">{{ l.tables.length }} of {{ l.total_tables }} tables · {{ methodText(l.method) }}</span>
                }
              </div>
              @if (turn().linking; as l) {
                <div class="chips">
                  @for (t of l.tables; track t) {
                    <span class="chip" [title]="(l.reasons[t] || []).join('; ')">
                      {{ t }}@if (l.columns[t]?.length) {<span class="cols">.{{ l.columns[t].join(', ') }}</span>}
                    </span>
                  }
                </div>
                @for (v of l.values; track v.value + v.column) {
                  <div class="note">Value <b>"{{ v.value }}"</b> found in {{ v.table }}.{{ v.column }}</div>
                }
              }
            </div>
          </li>

          <!-- 2. SQL generation + self-correction -->
          <li [attr.data-state]="sqlState()">
            <span class="num">02</span>
            <div class="content">
              <div class="title">SQL generation
                @if (repairs() > 0) {
                  <span class="meta">{{ repairs() }} {{ repairs() === 1 ? 'repair' : 'repairs' }} from execution feedback</span>
                }
              </div>
              @for (a of turn().attempts; track a.n) {
                <div class="attempt" [class.failed]="!a.ok || a.note">
                  <div class="att-head">
                    <span class="att-n">Attempt {{ a.n }}</span>
                    @if (a.ok && a.note) {
                      <span>Executed · 0 rows · sent back to check its filters</span>
                    } @else if (a.ok) {
                      <span>Executed · {{ a.rows }} {{ a.rows === 1 ? 'row' : 'rows' }} · {{ a.ms }} ms</span>
                    } @else {
                      <span>Failed, error sent back to the SQL agent</span>
                    }
                  </div>
                  @if (!a.ok) {
                    <pre class="error">{{ a.error }}</pre>
                    <details>
                      <summary>Failed query</summary>
                      <pre class="code">{{ a.sql }}</pre>
                    </details>
                  }
                </div>
              }
              @if (turn().widened) {
                <div class="note">Linked schema was missing a table or column, so the repair used the full schema.</div>
              }
            </div>
          </li>

          <!-- 3. Explanation -->
          <li [attr.data-state]="explainState()">
            <span class="num">03</span>
            <div class="content"><div class="title">Explanation</div></div>
          </li>
        </ol>
      }
    </div>
  `,
  styles: `
    .trace { border: 1px solid var(--line); }
    .summary { width: 100%; display: flex; align-items: center; gap: 14px; padding: 10px 14px; border: 0; background: var(--surface); cursor: pointer; text-align: left; }
    .summary:disabled { cursor: default; }
    .summary:hover:not(:disabled) { background: var(--subtle); }
    .sum-text { flex: 1; display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); }
    .chev { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: square; transition: transform .15s; }
    .chev.rot { transform: rotate(180deg); }
    .pulse { width: 8px; height: 8px; background: var(--text); animation: pulse 1s ease-in-out infinite; }
    @keyframes pulse { 50% { opacity: .15; } }

    .steps { list-style: none; margin: 0; padding: 4px 14px 14px; border-top: 1px solid var(--line); }
    li { display: flex; gap: 14px; padding: 12px 0 0; }
    .num { flex: none; width: 26px; height: 22px; display: grid; place-items: center; border: 1px solid var(--line); font-family: var(--mono); font-size: 11px; color: var(--faint); }
    li[data-state='running'] .num { border-color: var(--line-strong); color: var(--text); animation: pulse 1s ease-in-out infinite; }
    li[data-state='done'] .num { background: var(--invert-bg); border-color: var(--invert-bg); color: var(--invert-text); }
    li[data-state='failed'] .num { border-color: var(--line-strong); color: var(--text); text-decoration: line-through; }
    li[data-state='waiting'] .title { color: var(--faint); }
    .content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px; }
    .title { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 10px; font-size: 13.5px; font-weight: 600; line-height: 22px; }
    .meta { font-weight: 400; font-size: 12.5px; color: var(--muted); }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; }
    .chip { padding: 3px 8px; border: 1px solid var(--line-strong); font-family: var(--mono); font-size: 11.5px; }
    .chip .cols { color: var(--muted); }
    .note { font-size: 12.5px; color: var(--muted); }
    .note b { color: var(--text); font-weight: 600; }
    .attempt { border-left: 2px solid var(--line-strong); padding: 2px 0 2px 12px; font-size: 12.5px; display: flex; flex-direction: column; gap: 6px; }
    .attempt.failed { border-left-style: dashed; }
    .att-head { display: flex; flex-wrap: wrap; gap: 4px 12px; color: var(--muted); }
    .att-n { font-weight: 600; color: var(--text); }
    pre { margin: 0; padding: 8px 10px; overflow-x: auto; white-space: pre-wrap; font-family: var(--mono); font-size: 11.5px; line-height: 1.6; }
    .error { border: 1px solid var(--line-strong); background: var(--surface); }
    .code { background: var(--subtle); border: 1px solid var(--line); margin-top: 6px; }
    details summary { cursor: pointer; color: var(--muted); font-size: 12px; }
    details summary:hover { color: var(--text); }
  `,
})
export class AgentTraceComponent {
  turn = input.required<Turn>();
  open = signal(false);

  live = computed(() => this.turn().status === 'loading');
  expanded = computed(() => this.live() || this.open());
  repairs = computed(() => this.turn().attempts.filter((a) => !a.ok || a.note).length);

  linkState = computed<StepState>(() => (this.turn().linking ? 'done' : this.live() ? 'running' : 'failed'));
  sqlState = computed<StepState>(() => {
    const t = this.turn();
    if (t.attempts.some((a) => a.ok)) return 'done';
    if (!t.linking) return 'waiting';
    return this.live() ? 'running' : 'failed';
  });
  explainState = computed<StepState>(() => {
    const t = this.turn();
    if (t.status === 'done') return 'done';
    if (!t.attempts.some((a) => a.ok)) return 'waiting';
    return this.live() ? 'running' : 'failed';
  });

  summary = computed(() => {
    const t = this.turn();
    const parts: string[] = [];
    if (t.linking) parts.push(`${t.linking.tables.length}/${t.linking.total_tables} tables linked`);
    if (t.attempts.length) {
      const r = this.repairs();
      parts.push(r === 0 ? 'SQL ran first time' : `${r} ${r === 1 ? 'repair' : 'repairs'}`);
    }
    const ms = t.response?.trace?.total_ms;
    if (ms !== undefined) parts.push(`${(ms / 1000).toFixed(1)} s`);
    return parts.join(' · ') || 'No steps recorded';
  });

  methodText(method: string) {
    const names: Record<string, string> = { lexical: 'names', value: 'stored values', llm: 'LLM', fallback: 'no match, all tables' };
    return method.split('+').map((m) => names[m] ?? m).join(' + ');
  }
}
