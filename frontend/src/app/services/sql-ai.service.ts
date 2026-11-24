import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { AgentEvent, HistoryTurn, RunSqlResponse, Schema } from '../models';

// Talks to the FastAPI backend.
const API_URL = 'http://localhost:8000';

@Injectable({ providedIn: 'root' })
export class SqlAiService {
  private http = inject(HttpClient);

  schema(): Observable<Schema> {
    return this.http.get<Schema>(`${API_URL}/schema`);
  }

  runSql(sql: string): Observable<RunSqlResponse> {
    return this.http.post<RunSqlResponse>(`${API_URL}/run-sql`, { sql });
  }

  /** Streams the agent's steps (one JSON object per line) as they happen. */
  askStream(question: string, history: HistoryTurn[] = []): Observable<AgentEvent> {
    return new Observable<AgentEvent>((sub) => {
      const ctrl = new AbortController();
      (async () => {
        let res: Response;
        try {
          res = await fetch(`${API_URL}/chat/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, history }),
            signal: ctrl.signal,
          });
        } catch {
          sub.next({ type: 'error', message: 'Cannot reach the backend. Is it running on http://localhost:8000?' });
          sub.complete();
          return;
        }
        if (!res.ok || !res.body) {
          let message = `Request failed (HTTP ${res.status}).`;
          try {
            const body = await res.json();
            if (typeof body.detail === 'string') message = body.detail;
          } catch {}
          sub.next({ type: 'error', message });
          sub.complete();
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';
          for (const line of lines) if (line.trim()) sub.next(JSON.parse(line));
        }
        if (buffer.trim()) sub.next(JSON.parse(buffer));
        sub.complete();
      })().catch((e) => {
        if (!ctrl.signal.aborted) sub.next({ type: 'error', message: `Stream failed: ${e}` });
        sub.complete();
      });
      return () => ctrl.abort();
    });
  }
}
