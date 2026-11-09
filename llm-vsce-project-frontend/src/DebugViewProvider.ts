import * as vscode from 'vscode';
import * as path from 'node:path';
import { createHash } from 'node:crypto';
import { BackendClient, SessionRunner, SessionRequest, DebugMode, DebugResult, SourceSnapshot } from './backendClient';
import { containedFile, relativeWorkspacePath } from './workspacePaths';
import { webviewHtml } from './webviewHtml';

export class DebugViewProvider implements vscode.WebviewViewProvider, vscode.Disposable {
    static readonly viewType = 'pythonDebugAgent.debugView';
    private view?: vscode.WebviewView;
    private lastDocument?: vscode.TextDocument;
    private runner?: SessionRunner;
    private starting = false;
    private lastResult?: DebugResult;
    private readonly disposables: vscode.Disposable[] = [];
    private readonly output = vscode.window.createOutputChannel('Python Debug Agent');

    constructor() {
        this.rememberEditor(vscode.window.activeTextEditor);
        this.disposables.push(this.output, vscode.window.onDidChangeActiveTextEditor(editor => this.rememberEditor(editor)));
    }
    private rememberEditor(editor: vscode.TextEditor | undefined) {
        if (editor?.document.languageId === 'python' && editor.document.uri.scheme === 'file') {
            this.lastDocument = editor.document;
            void this.view?.webview.postMessage({ type: 'source', path: editor.document.uri.fsPath });
        }
    }
    resolveWebviewView(view: vscode.WebviewView): void {
        this.view = view;
        view.webview.options = { enableScripts: true, localResourceRoots: [] };
        view.webview.html = webviewHtml();
        const receiver = view.webview.onDidReceiveMessage((message: unknown) => {
            void this.handleMessage(message).catch(error => this.send({ type: 'debugError', error: this.errorText(error) }));
        });
        view.onDidDispose(() => {
            receiver.dispose();
            if (this.view === view) { this.view = undefined; }
            void this.runner?.cancel().catch(error => this.output.appendLine(this.errorText(error)));
        });
    }
    private send(message: unknown) { void this.view?.webview.postMessage(message); }
    private errorText(error: unknown): string { return error instanceof Error ? error.message : String(error); }
    private async handleMessage(raw: unknown) {
        if (!raw || typeof raw !== 'object' || !('type' in raw)) { return; }
        const message = raw as Record<string, unknown>;
        switch (message.type) {
            case 'ready': {
                const config = vscode.workspace.getConfiguration('pythonDebugAgent', this.lastDocument?.uri);
                this.send({ type: 'settings', mode: config.get<DebugMode>('mode', 'agent'), repair: config.get<boolean>('repairEnabled', false) });
                this.send({ type: 'source', path: this.lastDocument?.uri.fsPath || 'Open a Python file in your project.' });
                if (this.lastResult) { this.send({ type: 'restoreResult', result: this.lastResult }); }
                break;
            }
            case 'chooseFile': {
                const files = await vscode.window.showOpenDialog({ canSelectMany: false, filters: { Python: ['py'] },
                    defaultUri: vscode.workspace.workspaceFolders?.[0]?.uri });
                if (files?.[0]) {
                    const document = await vscode.workspace.openTextDocument(files[0]);
                    await vscode.window.showTextDocument(document, { preserveFocus: true });
                    this.lastDocument = document;
                    this.send({ type: 'source', path: document.uri.fsPath });
                }
                break;
            }
            case 'debug': {
                if (this.runner || this.starting) { throw new Error('A debug session is already starting or running.'); }
                this.starting = true;
                try { await this.debug(message); } finally { this.starting = false; }
                break;
            }
            case 'newSession':
                if (this.runner || this.starting) { throw new Error('Cancel the current session before clearing it.'); }
                this.lastResult = undefined;
                break;
            case 'cancel':
                if (this.runner) {
                    this.send({ type: 'progress', status: 'Cancelling…' });
                    await this.runner.cancel();
                }
                break;
            case 'viewPatch':
                if (this.lastResult?.patch) {
                    const document = await vscode.workspace.openTextDocument({ language: 'diff', content: this.lastResult.patch });
                    await vscode.window.showTextDocument(document, { preview: false });
                }
                break;
            case 'viewVerification':
                if (this.lastResult) {
                    const document = await vscode.workspace.openTextDocument({ language: 'json', content: JSON.stringify({
                        session_id: this.lastResult.session_id, status: this.lastResult.status,
                        verification_status: this.lastResult.verification_status, base_hashes: this.lastResult.base_hashes,
                        diagnosis: this.lastResult.diagnosis, baseline: this.lastResult.baseline,
                        verification: this.lastResult.verification, error: this.lastResult.error,
                    }, null, 2) });
                    await vscode.window.showTextDocument(document, { preview: false });
                }
                break;
        }
    }
    private async snapshot(document: vscode.TextDocument, root: vscode.WorkspaceFolder, requestedPath?: string): Promise<SourceSnapshot> {
        const relative = requestedPath || path.relative(root.uri.fsPath, document.uri.fsPath).split(path.sep).join('/');
        relativeWorkspacePath(relative);
        await containedFile(root.uri.fsPath, relative);
        const content = document.getText();
        if (Buffer.byteLength(content, 'utf8') > 1_000_000) { throw new Error('Source snapshot exceeds the 1 MB limit.'); }
        return { path: relative, uri: document.uri.toString(), content, document_version: document.version,
            is_dirty: document.isDirty, content_hash: createHash('sha256').update(content, 'utf8').digest('hex') };
    }
    private async debug(message: Record<string, unknown>) {
        if (this.runner) { throw new Error('A session is already running. Cancel it before starting another.'); }
        if (!vscode.workspace.isTrusted) { throw new Error('Trust this workspace before running debugging tools or project tests.'); }
        this.rememberEditor(vscode.window.activeTextEditor);
        const document = this.lastDocument;
        if (!document || document.isClosed || document.languageId !== 'python' || document.uri.scheme !== 'file') {
            throw new Error('Open or choose a local Python file to debug.');
        }
        const root = vscode.workspace.getWorkspaceFolder(document.uri);
        if (!root || root.uri.scheme !== 'file') { throw new Error('Open the script’s containing project folder in this VS Code window.'); }
        const userMessage = typeof message.userMessage === 'string' ? message.userMessage.trim() : '';
        const errorLog = typeof message.errorLog === 'string' ? message.errorLog : '';
        if (!userMessage || userMessage.length > 8000 || errorLog.length > 40000) {
            throw new Error('Enter a request under 8000 characters and a traceback under 40000 characters.');
        }
        const mode = message.mode as DebugMode;
        if (!['agent', 'direct', 'two-thinking-times'].includes(mode)) { throw new Error('Choose a valid debug mode.'); }
        const failingTests = typeof message.failingTests === 'string' ? message.failingTests.split(/\r?\n/).map(s => s.trim()).filter(Boolean) : [];
        if (failingTests.length > 100) { throw new Error('Specify at most 100 failing test selectors.'); }
        for (const test of failingTests) { relativeWorkspacePath(test.split('::')[0]); }
        const config = vscode.workspace.getConfiguration('pythonDebugAgent', root.uri);
        const testTargets = config.get<string[]>('testTargets', ['tests']);
        for (const test of testTargets) {
            const target = test.split('::')[0];
            if (target !== '.') { relativeWorkspacePath(target); }
        }
        const source = await this.snapshot(document, root);
        const request: SessionRequest = {
            mode, problem: { user_message: userMessage, failure_type: failingTests.length ? 'test_failure' : 'runtime_error',
                error_log: errorLog || null, failing_tests: failingTests },
            context: { workspace_path: root.uri.fsPath, workspace_id: root.uri.toString(), workspace_uri: root.uri.toString(), active_file: source },
            preparation: { enabled: mode === 'agent' && config.get<boolean>('sbflEnabled', true),
                sbfl: { source_root: config.get<string>('sourceRoot', '.'), test_ids: testTargets } },
            repair: { enabled: mode === 'agent' && message.repair === true, test_targets: testTargets },
        };
        const client = new BackendClient(config.get<string>('backendUrl', 'http://127.0.0.1:8000'));
        const runner = new SessionRunner(client);
        this.runner = runner;
        this.lastResult = undefined;
        this.send({ type: 'started', source: source.path });
        this.output.appendLine(`Starting ${mode} session for ${root.uri.fsPath}/${source.path}`);
        try {
            const result = await runner.execute(request, async action => {
                if (!vscode.workspace.isTrusted) { throw new Error('Workspace trust was revoked.'); }
                if (action.request.type !== 'read_file' || typeof action.request.arguments.path !== 'string') {
                    return { type: 'error', code: 'unsupported_action', message: 'The extension supports source file reads. Test execution is performed by the local backend.' };
                }
                const relative = relativeWorkspacePath(action.request.arguments.path);
                const filename = await containedFile(root.uri.fsPath, relative);
                const requested = await vscode.workspace.openTextDocument(vscode.Uri.file(filename));
                return { type: 'read_file', file: await this.snapshot(requested, root, relative) };
            }, status => {
                if (this.runner === runner) {
                    this.send({ type: 'progress', status: status.status.replace(/_/g, ' '), sessionId: status.session_id,
                        attempt: status.patch_attempt, turns: status.agent_turns });
                }
            });
            this.lastResult = result;
            this.output.appendLine(`Session ${result.session_id}: ${result.status}; verification=${result.verification_status || 'not requested'}`);
            this.send({ type: 'debugResult', result });
        } catch (error) {
            let detail = this.errorText(error);
            if (!runner.controller.signal.aborted && runner.sessionId) {
                try {
                    const result = await client.result(runner.sessionId);
                    if (result.status === 'failed') {
                        this.lastResult = result;
                        this.send({ type: 'debugResult', result });
                        return;
                    }
                    await runner.cancel();
                } catch (cancelError) { detail += ` Session ${runner.sessionId}: ${this.errorText(cancelError)}`; }
            }
            this.output.appendLine(detail);
            this.send({ type: 'debugError', error: detail });
        } finally {
            if (this.runner === runner) { this.runner = undefined; }
            this.send({ type: 'finished' });
        }
    }
    dispose(): void {
        void this.runner?.cancel().catch(() => undefined);
        for (const disposable of this.disposables) { disposable.dispose(); }
    }
}
