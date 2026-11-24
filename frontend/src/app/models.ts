// ---------- Backend shapes ----------

export interface SqlAttempt {
  n: number;
  sql: string;
  ok: boolean;
  error?: string;
  rows?: number;
  ms?: number;
  note?: string; // e.g. returned no rows and was sent back for review
}

export interface LinkingInfo {
  tables: string[];
  columns: Record<string, string[]>;
  values: { table: string; column: string; value: string }[];
  reasons: Record<string, string[]>;
  method: string;
  total_tables: number;
}

export interface ChatResponse {
  question: string;
  sql: string;
  columns: string[];
  results: unknown[][];
  explanation: string;
  truncated?: boolean;
  trace?: { linking: LinkingInfo; attempts: SqlAttempt[]; widened: boolean; total_ms: number };
}

export interface RunSqlResponse {
  sql: string;
  columns: string[];
  results: unknown[][];
  truncated?: boolean;
}

// One line of the /chat/stream response.
export type AgentEvent =
  | { type: 'status'; step: 'schema' | 'linking' | 'generating' | 'explaining'; message: string }
  | ({ type: 'linking' } & LinkingInfo)
  | ({ type: 'attempt' } & SqlAttempt)
  | { type: 'widened'; message: string }
  | { type: 'result'; response: ChatResponse }
  | { type: 'error'; message: string; sql?: string };

export interface SchemaColumn {
  name: string;
  type: string;
  primary_key: boolean;
}

export interface SchemaTable {
  name: string;
  columns: SchemaColumn[];
  foreign_keys: { column: string; references: string }[];
  sample_rows: unknown[][];
}

export interface Schema {
  database?: string;
  tables: SchemaTable[];
}

// An earlier question and the SQL that answered it, sent so follow-ups make sense.
export interface HistoryTurn {
  question: string;
  sql: string;
}

// ---------- UI state ----------

// One question and everything the agents did for it.
export interface Turn {
  id: number;
  question: string;
  status: 'loading' | 'done' | 'error';
  current?: string; // live status line while loading
  linking?: LinkingInfo;
  attempts: SqlAttempt[];
  widened?: boolean;
  response?: ChatResponse;
  error?: { message: string; sql?: string };
  // The user can edit the SQL and run it again; the new result replaces the shown one.
  edited?: { sql: string; columns: string[]; results: unknown[][]; truncated?: boolean; runs: number };
}
