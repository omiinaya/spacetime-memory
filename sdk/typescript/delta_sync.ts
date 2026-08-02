/**
 * Real-time delta sync gateway for spacetime-memory.
 *
 * Polls the ``change_event`` table at high frequency and dispatches callbacks
 * to local subscribers. Supports per-table, per-operation callbacks.
 *
 * Usage:
 * ```typescript
 * const client = new Client(...);
 * const ds = client.deltaSync;
 *
 * // Register callbacks
 * ds.on("memory", "insert", (event) => console.log("New memory:", event));
 * ds.on("kg_node", "*", (event) => console.log("Graph change:", event));
 *
 * // Start polling (background interval)
 * ds.start();
 *
 * // Later...
 * ds.stop();
 * ```
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** A single change event from the STDB change_event table. */
export interface ChangeEvent {
  id: string;
  workspace_id: string;
  /** The table that changed: "memory", "kg_node", "kg_edge", "note", etc. */
  table_name: string;
  /** The operation: "insert", "update", "delete" */
  operation: string;
  /** Primary key of the changed record */
  record_id: string;
  /** JSON-encoded snapshot of the record *after* the operation */
  data_json: string;
  /** Monotonic microsecond timestamp */
  created_at: number;

  /** Deserialized record data (lazy). */
  data?: Record<string, unknown>;
}

/** Callback type for change events. */
export type ChangeCallback = (event: ChangeEvent) => void;

/** Internal subscription entry. */
interface Subscription {
  token: object;
  table: string;
  operation: string;
  callback: ChangeCallback;
}

/** Polling stats. */
export interface DeltaSyncStats {
  running: boolean;
  cursor: number;
  polls: number;
  errors: number;
  poll_interval: number;
  callbacks: number;
}

// ---------------------------------------------------------------------------
// DeltaSync
// ---------------------------------------------------------------------------

/**
 * Poll the ``change_event`` table and dispatch callbacks.
 *
 * Requires a client instance that exposes `_call` (for reducers) and
 * `_sql` (for queries). The TypeScript SDK Client satisfies this.
 */
export class DeltaSync {
  private _client: any;
  private _pollInterval: number;
  private _cursor: number = 0;
  private _subscriptions: Subscription[] = [];
  private _running: boolean = false;
  private _timerId: ReturnType<typeof setInterval> | null = null;
  private _polls: number = 0;
  private _errors: number = 0;

  /**
   * @param client - A Client instance (needs `_call` and `_sql` methods).
   * @param pollInterval - Seconds between polls (default 0.1 = 100ms).
   * @param autoStart - Start polling immediately on construction.
   */
  constructor(
    client: any,
    pollInterval: number = 0.1,
    autoStart: boolean = false,
  ) {
    this._client = client;
    this._pollInterval = Math.max(0.01, pollInterval);
    if (autoStart) {
      this.start();
    }
  }

  // -----------------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------------

  /**
   * Register a callback for change events.
   *
   * @param table - Table name ("memory", "kg_node", "kg_edge", "note",
   *                "profile", "document", or "*" for all tables).
   * @param operation - Operation ("insert", "update", "delete", or "*" for all).
   * @param callback - Callback receiving a ChangeEvent.
   * @returns A token to pass to `off()` to unregister.
   */
  on(table: string, operation: string = "*", callback: ChangeCallback): object {
    const token = {};
    this._subscriptions.push({ token, table, operation, callback });
    return token;
  }

  /**
   * Unregister a callback by its token.
   */
  off(token: object): void {
    this._subscriptions = this._subscriptions.filter((s) => s.token !== token);
  }

  /**
   * Start polling in a background interval.
   */
  start(): void {
    if (this._running) return;
    this._running = true;

    // Bootstrap: get initial cursor
    this._bootstrapCursor()
      .then(() => {
        // Start the polling interval
        this._timerId = setInterval(() => this._poll(), this._pollInterval * 1000);
      })
      .catch((err) => {
        console.warn(`[DeltaSync] Bootstrap failed: ${err}`);
        // Start anyway with cursor=0
        this._timerId = setInterval(() => this._poll(), this._pollInterval * 1000);
      });
  }

  /**
   * Stop polling and clear the interval.
   */
  stop(): void {
    this._running = false;
    if (this._timerId !== null) {
      clearInterval(this._timerId);
      this._timerId = null;
    }
  }

  /** Current polling stats. */
  get stats(): DeltaSyncStats {
    return {
      running: this._running,
      cursor: this._cursor,
      polls: this._polls,
      errors: this._errors,
      poll_interval: this._pollInterval,
      callbacks: this._subscriptions.length,
    };
  }

  // -----------------------------------------------------------------------
  // Internal
  // -----------------------------------------------------------------------

  private async _bootstrapCursor(): Promise<void> {
    await this._client._call("get_latest_change_cursor", []);
    const rows = await this._client._sql(
      "SELECT events_json FROM change_event_result WHERE since_cursor = 0",
    );
    if (rows && rows.length > 0) {
      const data = JSON.parse((rows[0].events_json as string) ?? "{}");
      this._cursor = ((data as Record<string, unknown>).cursor as number) ?? 0;
    }
  }

  private async _poll(): Promise<void> {
    if (!this._running) return;
    try {
      await this._client._call("get_changes_since", [this._cursor]);
      const rows = await this._client._sql(
        `SELECT events_json FROM change_event_result WHERE since_cursor = ${this._cursor}`,
      );
      if (rows && rows.length > 0) {
        const rawJson = rows[0].events_json as string;
        if (rawJson) {
          const eventsRaw = JSON.parse(rawJson) as Record<string, unknown>[];
          if (eventsRaw.length > 0) {
            const events: ChangeEvent[] = eventsRaw.map((e) => {
              const event: ChangeEvent = {
                id: e.id as string,
                workspace_id: (e.workspace_id as string) ?? "",
                table_name: (e.table_name as string) ?? "",
                operation: (e.operation as string) ?? "",
                record_id: (e.record_id as string) ?? "",
                data_json: (e.data_json as string) ?? "{}",
                created_at: (e.created_at as number) ?? 0,
              };
              // Lazily deserialize data
              try {
                event.data = JSON.parse(event.data_json);
              } catch {
                event.data = {};
              }
              return event;
            });

            for (const event of events) {
              this._dispatch(event);
            }

            // Update cursor to the last event's timestamp
            this._cursor = events[events.length - 1].created_at;
          }
        }
      }
      this._polls++;
    } catch (err) {
      this._errors++;
      console.debug(`[DeltaSync] Poll error: ${err}`);
    }
  }

  private _dispatch(event: ChangeEvent): void {
    for (const sub of this._subscriptions) {
      if (sub.table === "*" || sub.table === event.table_name) {
        if (sub.operation === "*" || sub.operation === event.operation) {
          try {
            sub.callback(event);
          } catch (err) {
            console.error(`[DeltaSync] Callback error: ${err}`);
          }
        }
      }
    }
  }
}
