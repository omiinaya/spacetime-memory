/**
 * WebSocket subscription client for spacetime-memory.
 *
 * Connects to the WebSocket subscription server for real-time memory
 * update notifications.  Complements the polling-based ``DeltaSync``
 * with a push-based WebSocket subscription model.
 *
 * Usage:
 * ```typescript
 * import { WsSubscription } from "./ws_subscription";
 *
 * const ws = new WsSubscription("ws://127.0.0.1:8765");
 *
 * // Register callbacks
 * ws.on("memory", "insert", (event) => console.log("New memory:", event));
 * ws.on("kg_node", "*", (event) => console.log("Graph change:", event));
 *
 * // Connect (starts WebSocket)
 * ws.connect();
 *
 * // Later...
 * ws.disconnect();
 * ```
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** A single change event received via WebSocket. */
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

/** Connection stats. */
export interface WsSubscriptionStats {
  connected: boolean;
  uri: string;
  callbacks: number;
  messages_sent: number;
  errors: number;
  reconnects: number;
}

// ---------------------------------------------------------------------------
// WsSubscription
// ---------------------------------------------------------------------------

/**
 * WebSocket subscription client for real-time memory updates.
 *
 * Connects to the spacetime-memory WebSocket subscription server and
 * dispatches change events to registered callbacks via push-based
 * WebSocket, not polling.
 */
export class WsSubscription {
  private _uri: string;
  private _ws: WebSocket | null = null;
  private _subscriptions: Subscription[] = [];
  private _connected: boolean = false;
  private _running: boolean = false;
  private _messagesSent: number = 0;
  private _errors: number = 0;
  private _reconnects: number = 0;
  private _autoReconnect: boolean;
  private _reconnectDelay: number;
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private _outbox: object[] = [];

  /**
   * @param uri - WebSocket server URI (default: ws://127.0.0.1:8765).
   * @param autoReconnect - Automatically reconnect on disconnect (default: true).
   * @param reconnectDelay - Seconds to wait before reconnecting (default: 5).
   */
  constructor(
    uri: string = "ws://127.0.0.1:8765",
    autoReconnect: boolean = true,
    reconnectDelay: number = 5,
  ) {
    this._uri = uri;
    this._autoReconnect = autoReconnect;
    this._reconnectDelay = reconnectDelay;
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
  on(table: string = "*", operation: string = "*", callback: ChangeCallback): object {
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
   * Connect to the WebSocket server.
   *
   * If auto-reconnect is enabled, will automatically reconnect on
   * unexpected disconnection.
   */
  connect(): void {
    if (this._running) return;
    this._running = true;
    this._doConnect();
  }

  /**
   * Send a subscribe message to the server.
   */
  subscribe(workspaceId: string = "*", table: string = "*", operation: string = "*"): void {
    if (!this._connected) {
      console.warn("[WsSubscription] Cannot subscribe — not connected");
      return;
    }
    this._sendMessage({
      type: "subscribe",
      workspace_id: workspaceId,
      table,
      operation,
    });
  }

  /**
   * Remove a subscription filter from the server.
   */
  unsubscribe(workspaceId: string = "*", table: string = "*", operation: string = "*"): void {
    if (!this._connected) return;
    this._sendMessage({
      type: "unsubscribe",
      workspace_id: workspaceId,
      table,
      operation,
    });
  }

  /**
   * Disconnect from the WebSocket server and stop auto-reconnect.
   */
  disconnect(): void {
    this._running = false;
    this._autoReconnect = false;
    this._cleanup();
  }

  /** Current connection stats. */
  get stats(): WsSubscriptionStats {
    return {
      connected: this._connected,
      uri: this._uri,
      callbacks: this._subscriptions.length,
      messages_sent: this._messagesSent,
      errors: this._errors,
      reconnects: this._reconnects,
    };
  }

  /** Whether the WebSocket is currently connected. */
  get connected(): boolean {
    return this._connected;
  }

  // -----------------------------------------------------------------------
  // Internal
  // -----------------------------------------------------------------------

  private _doConnect(): void {
    if (this._reconnectTimer !== null) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }

    try {
      this._ws = new WebSocket(this._uri);
    } catch (err) {
      this._errors++;
      console.error(`[WsSubscription] Failed to create WebSocket: ${err}`);
      this._scheduleReconnect();
      return;
    }

    this._ws.onopen = () => {
      this._connected = true;
      console.log(`[WsSubscription] Connected to ${this._uri}`);

      // Drain any outbox that accumulated before connection
      this._drainOutbox();

      // Subscribe to all changes by default
      this._sendMessage({
        type: "subscribe",
        workspace_id: "*",
        table: "*",
        operation: "*",
      });
    };

    this._ws.onmessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data as string);
        this._handleMessage(msg);
      } catch (err) {
        this._errors++;
        console.debug(`[WsSubscription] Invalid message: ${err}`);
      }
    };

    this._ws.onerror = () => {
      this._errors++;
    };

    this._ws.onclose = () => {
      this._connected = false;
      this._ws = null;
      this._scheduleReconnect();
    };
  }

  private _scheduleReconnect(): void {
    if (!this._autoReconnect || !this._running) return;
    this._reconnects++;
    console.debug(`[WsSubscription] Reconnecting in ${this._reconnectDelay}s...`);
    this._reconnectTimer = setTimeout(() => {
      this._doConnect();
    }, this._reconnectDelay * 1000);
  }

  private _cleanup(): void {
    if (this._reconnectTimer !== null) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this._ws !== null) {
      this._ws.onclose = null; // prevent reconnect
      this._ws.close();
      this._ws = null;
    }
    this._connected = false;
  }

  private _sendMessage(msg: object): void {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(msg));
      this._messagesSent++;
    } else {
      // Queue for later when connection is established
      this._outbox.push(msg);
    }
  }

  private _drainOutbox(): void {
    while (this._outbox.length > 0) {
      const msg = this._outbox.shift();
      if (msg && this._ws) {
        this._ws.send(JSON.stringify(msg));
        this._messagesSent++;
      }
    }
  }

  private _handleMessage(msg: Record<string, unknown>): void {
    const msgType = msg.type as string;

    if (msgType === "change") {
      const eventRaw = msg.event as Record<string, unknown>;
      const event = this._parseEvent(eventRaw);
      this._dispatch(event);
    } else if (msgType === "error") {
      console.warn(`[WsSubscription] Server error: ${msg.message}`);
    } else if (msgType === "subscribed") {
      console.debug(`[WsSubscription] Subscribed to change events (count=${msg.count})`);
    } else if (msgType === "pong") {
      // keepalive response — nothing to do
    }
  }

  private _parseEvent(raw: Record<string, unknown>): ChangeEvent {
    const event: ChangeEvent = {
      id: (raw.id as string) ?? "",
      workspace_id: (raw.workspace_id as string) ?? "",
      table_name: (raw.table_name as string) ?? "",
      operation: (raw.operation as string) ?? "",
      record_id: (raw.record_id as string) ?? "",
      data_json: (raw.data_json as string) ?? "{}",
      created_at: (raw.created_at as number) ?? 0,
    };
    // Lazily deserialize data
    try {
      event.data = JSON.parse(event.data_json);
    } catch {
      event.data = {};
    }
    return event;
  }

  private _dispatch(event: ChangeEvent): void {
    for (const sub of this._subscriptions) {
      if (sub.table === "*" || sub.table === event.table_name) {
        if (sub.operation === "*" || sub.operation === event.operation) {
          try {
            sub.callback(event);
          } catch (err) {
            console.error(`[WsSubscription] Callback error: ${err}`);
          }
        }
      }
    }
  }
}
