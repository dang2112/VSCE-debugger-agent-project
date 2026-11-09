/** Session API contracts used by the extension. All paths are workspace-relative. */
export type DebugMode = 'direct' | 'two-thinking-times' | 'agent';
export interface SourceSnapshot {
    path: string; uri: string; content: string; document_version: number;
    content_hash: string; is_dirty: boolean;
}
export interface SessionRequest {
    mode: DebugMode;
    problem: { user_message: string; failure_type: 'runtime_error' | 'test_failure'; error_log: string | null; failing_tests: string[] };
    context: { workspace_path: string; workspace_id: string; workspace_uri: string; active_file: SourceSnapshot };
    preparation: { enabled: boolean; sbfl: { source_root: string; test_ids: string[] } };
    repair: { enabled: boolean; test_targets: string[] };
}
export interface SessionStatus {
    session_id: string; status: string; patch_attempt?: number; max_patch_attempts?: number;
    pending_actions?: number; agent_turns?: number;
}
export interface WorkspaceAction {
    action_id: string; session_id: string; status: string;
    request: { type: string; arguments: { path?: string } };
}
export type ActionResult = { type: 'read_file'; file: SourceSnapshot } | { type: 'error'; code: string; message: string };
export interface DebugResult {
    session_id: string; status: string; explanation: string | null; patch: string | null;
    verification_status: string | null; error: string | null; base_hashes: Record<string, string>;
    verification?: unknown; diagnosis?: unknown; baseline?: unknown;
}

export class BackendClient {
    private readonly baseUrl: string;
    constructor(url: string, private readonly timeoutMs = 900_000) {
        const parsed = new URL(url);
        if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password || parsed.search || parsed.hash) {
            throw new Error('Configure a valid HTTP(S) backend URL without credentials, query, or fragment.');
        }
        this.baseUrl = parsed.toString().replace(/\/$/, '');
    }
    async request<T>(path: string, body?: unknown, signal?: AbortSignal, timeout = 15_000): Promise<T> {
        try {
            const response = await fetch(this.baseUrl + path, {
                method: body === undefined ? 'GET' : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: body === undefined ? undefined : JSON.stringify(body),
                signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(timeout)]) : AbortSignal.timeout(timeout),
            });
            const text = await response.text();
            if (!response.ok) {
                throw new Error(`Backend returned ${response.status}: ${text.slice(0, 2000)}`);
            }
            return JSON.parse(text) as T;
        } catch (error) {
            if (signal?.aborted) { throw new Error('Request cancelled.'); }
            if (error instanceof Error && error.message.startsWith('Backend returned')) { throw error; }
            throw new Error(`Cannot complete request to ${this.baseUrl}: ${error instanceof Error ? error.message : String(error)}. Check that the backend is running.`);
        }
    }
    create(request: SessionRequest, signal?: AbortSignal) {
        return this.request<SessionStatus>('/debug/sessions', request, signal);
    }
    run(id: string, signal?: AbortSignal) {
        return this.request<SessionStatus>(`/debug/sessions/${encodeURIComponent(id)}/run`, {}, signal, this.timeoutMs);
    }
    status(id: string, signal?: AbortSignal) {
        return this.request<SessionStatus>(`/debug/sessions/${encodeURIComponent(id)}`, undefined, signal);
    }
    actions(id: string, signal?: AbortSignal) {
        return this.request<WorkspaceAction[]>(`/debug/sessions/${encodeURIComponent(id)}/actions`, undefined, signal);
    }
    submit(id: string, actionId: string, result: ActionResult, signal?: AbortSignal) {
        return this.request(`/debug/sessions/${encodeURIComponent(id)}/actions/${encodeURIComponent(actionId)}/result`, { result }, signal);
    }
    result(id: string, signal?: AbortSignal) {
        return this.request<DebugResult>(`/debug/sessions/${encodeURIComponent(id)}/result`, undefined, signal);
    }
    cancel(id: string) { return this.request<SessionStatus>(`/debug/sessions/${encodeURIComponent(id)}/cancel`, {}); }
}

/** /run is synchronous; progress polling remains active while that HTTP request runs. */
export class SessionRunner {
    readonly controller = new AbortController();
    sessionId?: string;
    private cancelRequested = false;
    private cancelPromise?: Promise<void>;
    constructor(private readonly client: BackendClient) {}
    async cancel(): Promise<void> {
        this.cancelRequested = true;
        if (!this.cancelPromise && this.sessionId) {
            this.cancelPromise = this.client.cancel(this.sessionId).then(() => undefined);
        }
        try { await this.cancelPromise; }
        finally { this.controller.abort(); }
    }
    async execute(request: SessionRequest, read: (action: WorkspaceAction) => Promise<ActionResult>,
        progress: (status: SessionStatus) => void, pollMs = 600): Promise<DebugResult> {
        // Keep create's response even if cancelled, so a newly created session can be cancelled too.
        const created = await this.client.create(request);
        this.sessionId = created.session_id;
        if (this.cancelRequested) { await this.cancel(); throw new Error('Request cancelled.'); }
        progress(created);
        const signal = this.controller.signal;
        let polling = false;
        const timer = setInterval(() => {
            if (polling || signal.aborted) { return; }
            polling = true;
            void this.client.status(created.session_id, signal).then(progress).catch(() => undefined)
                .finally(() => { polling = false; });
        }, pollMs);
        try {
            for (let cycle = 0; cycle < 100; cycle++) {
                if (signal.aborted) { throw new Error('Request cancelled.'); }
                const status = await this.client.run(created.session_id, signal);
                progress(status);
                if (['completed', 'failed', 'cancelled'].includes(status.status)) {
                    return await this.client.result(created.session_id, signal);
                }
                if (status.status !== 'waiting_for_context') {
                    throw new Error(`Unexpected backend state: ${status.status}. Session: ${created.session_id}`);
                }
                const actions = await this.client.actions(created.session_id, signal);
                if (!actions.length) { continue; } // Results may have been submitted by another client.
                for (const action of actions) {
                    if (action.session_id !== created.session_id || action.status !== 'pending') {
                        throw new Error('Backend returned an action for the wrong session or state.');
                    }
                    let result: ActionResult;
                    try { result = await read(action); }
                    catch (error) {
                        result = { type: 'error', code: 'file_read_failed', message: error instanceof Error ? error.message : String(error) };
                    }
                    if (signal.aborted) { throw new Error('Request cancelled.'); }
                    await this.client.submit(created.session_id, action.action_id, result, signal);
                }
            }
            throw new Error(`Session ${created.session_id} exceeded the extension continuation limit.`);
        } finally { clearInterval(timer); }
    }
}
