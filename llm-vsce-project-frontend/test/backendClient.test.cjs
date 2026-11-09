const assert = require('node:assert/strict');
const { test } = require('node:test');
const http = require('node:http');
const { BackendClient, SessionRunner } = require('../out/backendClient.js');
const { webviewHtml } = require('../out/webviewHtml.js');
const { Script } = require('node:vm');

const snapshot = { path: 'main.py', uri: 'file:///project/main.py', content: 'print(1)', document_version: 3, content_hash: 'hash', is_dirty: true };
const request = { mode: 'agent', problem: { user_message: 'Explain the bug', failure_type: 'runtime_error', error_log: null, failing_tests: [] },
    context: { workspace_path: '/project', workspace_id: 'project', workspace_uri: 'file:///project', active_file: snapshot },
    preparation: { enabled: false, sbfl: { source_root: '.', test_ids: ['tests'] } }, repair: { enabled: false, test_targets: ['tests'] } };

async function serve(t, handler) {
    const server = http.createServer(async (req, res) => {
        try {
            let body = ''; for await (const part of req) { body += part; }
            const value = await handler(req.url, body ? JSON.parse(body) : undefined);
            res.writeHead(value?.httpCode || 200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify(value?.body || value));
        } catch (error) { res.writeHead(500); res.end(JSON.stringify({error: error.message})); }
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    t.after(() => { server.closeAllConnections(); return new Promise(resolve => server.close(resolve)); });
    return `http://127.0.0.1:${server.address().port}`;
}
function result() { return { session_id: 'session', status: 'completed', explanation: 'Diagnosis', patch: null, error: null, verification_status: null, base_hashes: {} }; }

test('session creation, synchronous run progress, file action and continuation', async t => {
    let runs = 0, reads = 0, polls = 0;
    const url = await serve(t, async (path, body) => {
        if (path === '/debug/sessions') { assert.deepEqual(body, request); return { session_id: 'session', status: 'created' }; }
        if (path.endsWith('/run')) { runs++; await new Promise(r => setTimeout(r, 50)); return { session_id: 'session', status: runs === 1 ? 'waiting_for_context' : 'completed' }; }
        if (path.endsWith('/actions')) { return [{ action_id: 'action', session_id: 'session', status: 'pending', request: { type: 'read_file', arguments: { path: 'helper.py' } } }]; }
        if (path.endsWith('/result') && path.includes('/actions/')) { assert.equal(body.result.file.is_dirty, true); assert.equal(body.result.file.path, 'helper.py'); return {status: 'completed'}; }
        if (path.endsWith('/result')) { return result(); }
        polls++; return { session_id: 'session', status: 'collecting_evidence' };
    });
    const progress = [];
    const output = await new SessionRunner(new BackendClient(url)).execute(request, async action => {
        reads++; assert.equal(action.request.arguments.path, 'helper.py');
        return {type: 'read_file', file: {...snapshot, path: 'helper.py'}};
    }, status => progress.push(status.status), 5);
    assert.equal(output.explanation, 'Diagnosis'); assert.equal(runs, 2); assert.equal(reads, 1);
    assert.ok(polls > 0); assert.ok(progress.includes('waiting_for_context'));
});

test('read failures are posted as structured errors instead of hanging', async t => {
    let runs = 0, submitted = false;
    const url = await serve(t, (path, body) => {
        if (path === '/debug/sessions') { return { session_id: 'session', status: 'created' }; }
        if (path.endsWith('/run')) { return {session_id: 'session', status: ++runs === 1 ? 'waiting_for_context' : 'completed'}; }
        if (path.endsWith('/actions')) { return [{action_id: 'a', session_id: 'session', status: 'pending', request: {type: 'read_file', arguments: {path: 'missing.py'}}}]; }
        if (path.includes('/actions/a/result')) { assert.equal(body.result.type, 'error'); assert.match(body.result.message, /missing/); submitted = true; return {}; }
        return result();
    });
    await new SessionRunner(new BackendClient(url)).execute(request, async () => { throw new Error('missing file'); }, () => undefined);
    assert.equal(submitted, true);
});

test('cancel calls the backend while a run request is still pending', async t => {
    let started, release;
    const ready = new Promise(r => { started = r; });
    const running = new Promise(r => { release = r; });
    let cancelled = false;
    const url = await serve(t, async path => {
        if (path === '/debug/sessions') { return {session_id: 'session', status: 'created'}; }
        if (path.endsWith('/run')) { started(); await running; return {session_id: 'session', status: 'cancelled'}; }
        if (path.endsWith('/cancel')) { cancelled = true; release(); return {session_id: 'session', status: 'cancelled'}; }
        return {session_id: 'session', status: 'collecting_evidence'};
    });
    const runner = new SessionRunner(new BackendClient(url));
    const outcome = runner.execute(request, async () => { throw new Error('unexpected read'); }, () => undefined).catch(error => error);
    await ready; await runner.cancel(); await outcome;
    assert.equal(cancelled, true); assert.equal(runner.controller.signal.aborted, true);
});

test('bad backend responses and unsupported URLs are explicit errors', async t => {
    assert.throws(() => new BackendClient('ftp://localhost'), /HTTP/);
    const url = await serve(t, () => ({ httpCode: 422, body: { detail: 'Invalid context' } }));
    await assert.rejects(new BackendClient(url).create(request), /422.*Invalid context/);
});

test('chat HTML has a nonce CSP and valid JavaScript without HTML insertion', () => {
    const html = webviewHtml();
    assert.match(html, /Content-Security-Policy/); assert.doesNotMatch(html, /innerHTML/);
    const script = html.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/)[1];
    new Script(script);
});
