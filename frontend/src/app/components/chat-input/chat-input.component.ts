import { Component, ElementRef, input, output, signal, viewChild } from '@angular/core';

// Growing text box + send button. Enter sends, Shift+Enter adds a line, Up recalls the last question.
@Component({
  selector: 'app-chat-input',
  template: `
    <form class="box" (submit)="$event.preventDefault(); submit()">
      <textarea
        #box
        rows="1"
        [value]="text()"
        (input)="onInput(box.value)"
        (keydown)="onKey($event)"
        placeholder="Ask a question about your data"
        aria-label="Your question"
        autocomplete="off"
      ></textarea>
      <button type="submit" class="send" [disabled]="loading() || !text().trim()" aria-label="Send question">
        @if (loading()) {
          <span class="spinner" aria-hidden="true"></span>
        } @else {
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
        }
      </button>
    </form>
    <p class="hint"><kbd>Enter</kbd> send <kbd>Shift</kbd>+<kbd>Enter</kbd> new line <kbd>↑</kbd> last question <kbd>/</kbd> focus</p>
  `,
  styles: `
    .box { display: flex; align-items: flex-end; border: 1px solid var(--line-strong); background: var(--surface); transition: box-shadow .12s; }
    .box:focus-within { box-shadow: 4px 4px 0 var(--line-strong); }
    textarea { flex: 1; resize: none; border: 0; outline: 0; background: transparent; font-size: 15px; line-height: 1.5; padding: 14px 16px; max-height: 200px; }
    textarea::placeholder { color: var(--faint); }
    .send { flex: none; width: 52px; height: 52px; display: grid; place-items: center; border: 0; border-left: 1px solid var(--line-strong); background: var(--invert-bg); color: var(--invert-text); cursor: pointer; }
    .send:disabled { background: var(--surface); color: var(--faint); cursor: default; }
    .send:hover:not(:disabled) svg { transform: translateX(2px); }
    svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: square; transition: transform .12s; }
    .spinner { width: 14px; height: 14px; border: 2px solid currentColor; border-right-color: transparent; border-radius: 50% !important; animation: spin .7s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .hint { display: flex; justify-content: center; align-items: center; gap: 5px; margin: 8px 0 0; font-size: 11.5px; color: var(--muted); }
    kbd { font-family: var(--mono); font-size: 10.5px; padding: 1px 5px; border: 1px solid var(--line); color: var(--text); }
    kbd + kbd { margin-left: -2px; }
    @media (max-width: 640px) { .hint { display: none; } }
  `,
  host: { '(document:keydown)': 'onGlobalKey($event)' },
})
export class ChatInputComponent {
  loading = input(false);
  lastQuestion = input('');
  ask = output<string>();
  text = signal('');
  private box = viewChild.required<ElementRef<HTMLTextAreaElement>>('box');

  onInput(value: string) {
    this.text.set(value);
    this.resize();
  }

  onKey(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      this.submit();
    } else if (event.key === 'ArrowUp' && !this.text() && this.lastQuestion()) {
      event.preventDefault();
      this.setText(this.lastQuestion());
    }
  }

  // "/" anywhere on the page focuses the box (unless you're already typing somewhere).
  onGlobalKey(event: KeyboardEvent) {
    const tag = (event.target as HTMLElement)?.tagName;
    if (event.key === '/' && tag !== 'TEXTAREA' && tag !== 'INPUT') {
      event.preventDefault();
      this.focus();
    }
  }

  submit() {
    const q = this.text().trim();
    if (!q || this.loading()) return;
    this.ask.emit(q);
    this.setText('');
  }

  focus() {
    this.box().nativeElement.focus();
  }

  /** Adds a word (e.g. a column name clicked in the sidebar) to the question. */
  append(word: string) {
    const current = this.text();
    this.setText(current && !current.endsWith(' ') ? `${current} ${word}` : current + word);
    this.focus();
  }

  private setText(value: string) {
    this.text.set(value);
    this.box().nativeElement.value = value;
    this.resize();
  }

  private resize() {
    const el = this.box().nativeElement;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }
}
