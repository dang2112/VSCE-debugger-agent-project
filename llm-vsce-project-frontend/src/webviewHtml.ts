import { randomBytes } from 'node:crypto';

// This script is static. Source code, logs and model replies are inserted with textContent only.
export const chatScript = String.raw`
const vscode = acquireVsCodeApi();
const byId = id => document.getElementById(id);
const saved = vscode.getState() || {};
let messages = saved.version === 2 && Array.isArray(saved.messages) ? saved.messages.slice(-8) : [];
let running = false;
let pendingNode;
let currentSource = '';
let lastSubmitted;
const feed = byId('messages');
const fields = ['prompt', 'traceback', 'tests'];
const draft = saved.draft || {};
for (const id of fields) { byId(id).value = typeof draft[id] === 'string' ? draft[id] : ''; }
function save() {
    vscode.setState({version: 2, messages, draft: {prompt: byId('prompt').value, traceback: byId('traceback').value, tests: byId('tests').value}});
}
function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined) { node.textContent = String(text); }
    return node;
}
function scrollDown() { const viewport = byId('conversation'); viewport.scrollTop = viewport.scrollHeight; }
function removePending() { if (pendingNode) { pendingNode.remove(); pendingNode = undefined; } }
function setPending(text) {
    if (!pendingNode) {
        pendingNode = element('article', 'message assistant pending');
        pendingNode.append(element('div', 'avatar', '*'), element('p', 'pending-text', text));
        feed.append(pendingNode);
    } else { pendingNode.lastElementChild.textContent = text; }
    scrollDown();
}
function render(item) {
    const user = item.role === 'You';
    const article = element('article', 'message ' + (user ? 'user' : 'assistant'));
    const body = element('div', 'message-body');
    body.append(element('div', 'message-author', item.role));
    if (user && Array.isArray(item.sections)) {
        for (const section of item.sections) {
            const block = element('section', 'message-section');
            block.append(element('h3', '', section.label), element('pre', section.code ? 'code-text' : 'prose', section.text));
            body.append(block);
        }
        if (item.source) { body.append(element('div', 'message-source', 'Attached: ' + item.source)); }
    } else { body.append(element('pre', 'prose', item.text || '')); }
    if (item.verification) {
        const badge = element('span', 'verdict', 'Verification: ' + item.verification);
        badge.dataset.verdict = item.verification;
        body.append(badge);
    }
    if (!user) { article.append(element('div', 'avatar', item.role === 'Error' ? '!' : '*')); }
    article.append(body); feed.append(article);
}
function refresh() {
    removePending(); feed.replaceChildren();
    for (const item of messages) { render(item); }
    byId('welcome').hidden = messages.length > 0;
    scrollDown();
}
function clearResults() {
    byId('results').hidden = true;
    byId('patch').disabled = true;
    byId('verification').disabled = true;
}
function busy(value, canCancel = value) {
    running = value;
    byId('send').disabled = value;
    byId('cancel').hidden = !value;
    byId('cancel').disabled = !canCancel;
    byId('newSession').disabled = value;
    byId('choose').disabled = value;
    for (const id of fields) { byId(id).disabled = value; }
    byId('mode').disabled = value;
    byId('repair').disabled = value || byId('mode').value !== 'agent';
    byId('sendLabel').textContent = value ? 'Debugging' : 'Debug';
}
function append(item) {
    messages.push(item); messages = messages.slice(-8); refresh(); save();
}
function resetSession() {
    if (running) { return; }
    messages = []; lastSubmitted = undefined;
    for (const id of fields) { byId(id).value = ''; }
    byId('status').textContent = 'Ready for a new session';
    byId('sessionId').textContent = '';
    clearResults(); refresh(); save();
    vscode.postMessage({type: 'newSession'});
    byId('prompt').focus();
}
function submit() {
    if (running) { return; }
    const request = byId('prompt').value.trim();
    if (!request) { byId('status').textContent = 'Describe the issue before debugging.'; byId('prompt').focus(); return; }
    const errorLog = byId('traceback').value;
    const failingTests = byId('tests').value;
    lastSubmitted = {userMessage: request, errorLog, failingTests};
    // Every Debug is a separate backend session. Never mix an old run into this transcript.
    messages = [{role: 'You', source: currentSource, sections: [
        {label: 'Request', text: request, code: false},
        {label: 'Error output', text: errorLog.trim() || 'Not provided', code: true},
        {label: 'Failing tests', text: failingTests.trim() || 'Not provided', code: true},
    ]}];
    clearResults(); refresh(); save(); busy(true, false);
    byId('status').textContent = 'Attaching active source file...';
    byId('sessionId').textContent = '';
    setPending('Preparing your debugging session...');
    vscode.postMessage({type: 'debug', ...lastSubmitted, mode: byId('mode').value,
        repair: byId('mode').value === 'agent' && byId('repair').checked});
}
byId('newSession').addEventListener('click', resetSession);
byId('send').addEventListener('click', submit);
byId('choose').addEventListener('click', () => vscode.postMessage({type: 'chooseFile'}));
for (const id of fields) {
    byId(id).addEventListener('input', save);
    byId(id).addEventListener('keydown', event => {
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); submit(); }
    });
}
byId('mode').addEventListener('change', () => { byId('repair').disabled = byId('mode').value !== 'agent'; });
byId('cancel').addEventListener('click', () => { byId('cancel').disabled = true; vscode.postMessage({type: 'cancel'}); });
byId('patch').addEventListener('click', () => vscode.postMessage({type: 'viewPatch'}));
byId('verification').addEventListener('click', () => vscode.postMessage({type: 'viewVerification'}));
window.addEventListener('message', event => {
    const message = event.data;
    if (message.type === 'settings') {
        byId('mode').value = message.mode; byId('repair').checked = message.repair;
        byId('repair').disabled = running || message.mode !== 'agent';
    }
    if (message.type === 'source') {
        currentSource = message.path;
        const name = String(message.path).split(String.fromCharCode(92)).join('/').split('/').pop();
        byId('source').textContent = name;
        byId('source').title = message.path;
    }
    if (message.type === 'started') {
        if (messages[0] && messages[0].role === 'You') { messages[0].source = message.source; }
        // Inputs clear only after the extension has captured a valid source snapshot.
        for (const id of fields) { byId(id).value = ''; }
        refresh(); save(); busy(true); setPending('Inspecting the project and collecting evidence...');
    }
    if (message.type === 'progress') {
        byId('status').textContent = message.status + (message.attempt ? ' - attempt ' + message.attempt : '');
        if (message.sessionId) { byId('sessionId').textContent = message.sessionId; }
        if (running) { setPending(message.status); }
    }
    if (message.type === 'debugResult') {
        removePending();
        append({role: message.result.status === 'failed' ? 'Error' : 'Debugger',
            text: String(message.result.explanation || message.result.error || 'No explanation returned.').slice(0, 100000),
            verification: message.result.verification_status || null});
        byId('status').textContent = message.result.status;
        byId('sessionId').textContent = message.result.session_id;
        byId('results').hidden = false; byId('patch').disabled = !message.result.patch; byId('verification').disabled = false;
        busy(false);
    }
    if (message.type === 'restoreResult') {
        byId('results').hidden = false; byId('patch').disabled = !message.result.patch; byId('verification').disabled = false;
    }
    if (message.type === 'debugError') {
        removePending(); append({role: 'Error', text: message.error});
        byId('status').textContent = 'Session could not finish'; busy(false);
    }
    if (message.type === 'finished') { removePending(); busy(false); }
});
refresh(); busy(false); vscode.postMessage({type: 'ready'});
`;

export function webviewHtml(): string {
    const nonce = randomBytes(18).toString('base64');
    return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}'; style-src 'nonce-${nonce}';">
<title>Debugger</title><style nonce="${nonce}">
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
[hidden] { display: none !important; }
html, body { height: 100%; margin: 0; }
body { color: var(--vscode-foreground); background: var(--vscode-sideBar-background, var(--vscode-editor-background)); font-family: var(--vscode-font-family); font-size: 13px; }
button, textarea, select { font: inherit; }
button { cursor: pointer; }
button:disabled { cursor: default; opacity: .45; }
button:focus-visible, textarea:focus-visible, select:focus-visible, summary:focus-visible { outline: 2px solid var(--vscode-focusBorder); outline-offset: 3px; }
.app { height: 100%; display: flex; flex-direction: column; }
.topbar { display: flex; align-items: center; justify-content: space-between; padding: 15px 16px; border-bottom: 1px solid var(--vscode-panel-border, transparent); flex-shrink: 0; }
.brand { display: flex; align-items: center; gap: 9px; font-weight: 600; letter-spacing: -.2px; }
.brand-mark, .avatar { display: grid; place-items: center; width: 25px; height: 25px; border: 1px solid var(--vscode-widget-border, #8885); border-radius: 8px; font-family: var(--vscode-editor-font-family); }
.quiet { color: var(--vscode-descriptionForeground); background: transparent; border: none; padding: 5px 7px; border-radius: 6px; font-size: 11px; }
.quiet:hover:not(:disabled) { color: var(--vscode-foreground); background: var(--vscode-list-hoverBackground); }
.conversation { flex: 1; min-height: 100px; overflow-y: auto; padding: 20px 16px; scrollbar-gutter: stable; }
#messages { max-width: 760px; margin: 0 auto; }
.welcome { min-height: 140px; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; max-width: 330px; margin: auto; }
.welcome .brand-mark { width: 40px; height: 40px; font-size: 18px; border-radius: 13px; margin-bottom: 15px; }
.welcome h1 { font-size: 19px; font-weight: 550; letter-spacing: -.5px; margin: 0 0 9px; }
.welcome p { color: var(--vscode-descriptionForeground); font-size: 12px; line-height: 1.65; margin: 0; }
.message { display: flex; align-items: flex-start; gap: 10px; margin: 0 0 24px; }
.message.user { justify-content: flex-end; }
.message-body { min-width: 0; flex: 1; }
.user .message-body { flex: initial; width: min(100%, 640px); border: 1px solid var(--vscode-widget-border, #8884); background: var(--vscode-input-background); padding: 13px 15px; border-radius: 16px 16px 4px 16px; }
.message-author { font-size: 11px; font-weight: 600; margin-bottom: 11px; }
.message-section + .message-section { border-top: 1px solid var(--vscode-widget-border, #8883); margin-top: 11px; padding-top: 11px; }
.message-section h3 { text-transform: uppercase; color: var(--vscode-descriptionForeground); font-size: 9px; letter-spacing: .8px; font-weight: 500; margin: 0 0 5px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; line-height: 1.7; }
.prose { font: inherit; line-height: 1.75; }
.code-text { font-family: var(--vscode-editor-font-family); font-size: 11px; }
.message-source { color: var(--vscode-descriptionForeground); font-size: 10px; margin-top: 11px; overflow-wrap: anywhere; }
.assistant .avatar { flex-shrink: 0; font-size: 20px; }
.pending { align-items: center; color: var(--vscode-descriptionForeground); }
.pending-text { margin: 0; font-size: 12px; }
.pending .avatar { animation: pulse 1.5s infinite; }
@keyframes pulse { 50% { opacity: .35; } }
@media (prefers-reduced-motion: reduce) { .pending .avatar { animation: none; } }
.verdict { display: inline-block; margin-top: 12px; padding: 3px 8px; border: 1px solid var(--vscode-widget-border, #8885); border-radius: 20px; font-size: 10px; color: var(--vscode-descriptionForeground); }
.verdict[data-verdict="passed"] { color: var(--vscode-testing-iconPassed, #68b881); }
.verdict[data-verdict="failed"] { color: var(--vscode-testing-iconFailed, #e77); }
.dock { flex-shrink: 0; padding: 0 12px 10px; max-height: 65%; overflow-y: auto; }
.composer { max-width: 760px; margin: auto; border: 1px solid var(--vscode-widget-border, #8885); border-radius: 16px; background: var(--vscode-input-background); overflow: hidden; }
.attachment { display: flex; align-items: center; gap: 7px; padding: 9px 12px; border-bottom: 1px solid var(--vscode-widget-border, #8883); }
.file-tag { font-family: var(--vscode-editor-font-family); font-size: 10px; color: var(--vscode-descriptionForeground); }
#source { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; font-size: 11px; }
.compose-section { padding: 10px 13px 8px; }
.compose-section + .compose-section { border-top: 1px solid var(--vscode-widget-border, #8883); }
.compose-section label { display: block; color: var(--vscode-descriptionForeground); font-size: 9px; letter-spacing: .8px; text-transform: uppercase; margin-bottom: 4px; }
.compose-section label span { float: right; opacity: .65; text-transform: none; letter-spacing: 0; }
textarea { display: block; width: 100%; padding: 0; resize: vertical; min-height: 32px; max-height: 150px; border: 0; color: var(--vscode-input-foreground); background: transparent; outline: none; line-height: 1.5; }
textarea::placeholder { color: var(--vscode-input-placeholderForeground); }
#traceback, #tests { font-family: var(--vscode-editor-font-family); font-size: 11px; }
.composer-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 11px 10px; border-top: 1px solid var(--vscode-widget-border, #8883); }
.toolbar-hint { color: var(--vscode-descriptionForeground); font-size: 10px; }
.primary { display: inline-flex; align-items: center; gap: 7px; padding: 7px 13px; border-radius: 9px; border: none; font-weight: 550; background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
.primary:hover:not(:disabled) { background: var(--vscode-button-hoverBackground); }
.primary svg { width: 13px; height: 13px; }
#options { max-width: 760px; margin: 8px auto 0; color: var(--vscode-descriptionForeground); font-size: 11px; }
#options summary { cursor: pointer; padding: 3px; }
.settings-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 8px 3px 2px; }
select { color: var(--vscode-dropdown-foreground); background: var(--vscode-dropdown-background); border: 1px solid var(--vscode-dropdown-border); border-radius: 5px; padding: 3px; max-width: 100%; }
.repair-label { display: flex; gap: 5px; align-items: center; }
.footer { max-width: 760px; margin: 6px auto 0; color: var(--vscode-descriptionForeground); font-size: 10px; line-height: 1.6; }
#status { margin: 0; } #sessionId { font-size: 9px; overflow-wrap: anywhere; opacity: .7; }
#results { max-width: 760px; margin: 0 auto 8px; display: flex; gap: 4px; }
@media (max-width: 280px) { .topbar { padding: 10px; } .conversation { padding: 15px 10px; } .toolbar-hint { display: none; } .composer-toolbar { justify-content: flex-end; } }
</style></head><body><div class="app">
<header class="topbar"><div class="brand"><span class="brand-mark" aria-hidden="true">{ }</span>Debugger</div>
<button id="newSession" class="quiet" title="Clear chat, inputs and results for a fresh session">+ New session</button></header>
<main class="conversation" id="conversation"><div id="welcome" class="welcome"><div class="brand-mark" aria-hidden="true">{ }</div>
<h1>What's going wrong?</h1><p>Describe the issue below. Your active Python file is attached automatically when you debug.</p></div>
<div id="messages" role="log" aria-label="Current debug session" aria-live="polite"></div></main>
<div class="dock"><div id="results" hidden><button id="patch" class="quiet" disabled>Review patch</button><button id="verification" class="quiet" disabled>Session details</button></div>
<div class="composer" role="group" aria-label="Debug message">
<div class="attachment"><span class="file-tag" aria-hidden="true">PY</span><span id="source" title="Active source file">Open a Python file</span><button id="choose" class="quiet" title="Choose a different Python source file">Change</button></div>
<div class="compose-section"><label for="prompt">01 / Request <span>required</span></label><textarea id="prompt" rows="2" maxlength="8000" placeholder="What happens, and what should happen instead?"></textarea></div>
<div class="compose-section"><label for="traceback">02 / Error output <span>optional</span></label><textarea id="traceback" rows="2" maxlength="40000" placeholder="Paste a traceback or error message..."></textarea></div>
<div class="compose-section"><label for="tests">03 / Failing tests <span>optional</span></label><textarea id="tests" rows="1" placeholder="tests/test_example.py::test_case"></textarea></div>
<div class="composer-toolbar"><span class="toolbar-hint">Ctrl / Cmd + Enter to debug</span><div><button id="cancel" class="quiet" disabled hidden>Cancel</button>
<button id="send" class="primary"><span id="sendLabel">Debug</span><svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M8 13V3M3.5 7.5 8 3l4.5 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></button></div></div>
</div>
<details id="options"><summary>Debug options</summary><div class="settings-row"><label for="mode">Mode</label><select id="mode"><option value="agent">Agent</option><option value="direct">Direct analysis</option><option value="two-thinking-times">Analysis + review</option></select>
<label class="repair-label"><input id="repair" type="checkbox">Generate and verify a patch</label></div></details>
<div class="footer"><p id="status" role="status">Each Debug starts a fresh session. Patches are reviewed before applying.</p><div id="sessionId"></div></div>
</div></div><script nonce="${nonce}">${chatScript}</script></body></html>`;
}
