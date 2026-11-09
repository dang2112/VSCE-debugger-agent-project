const assert = require('node:assert/strict');
const {test} = require('node:test');
const {runInNewContext} = require('node:vm');
const {chatScript, webviewHtml} = require('../out/webviewHtml');

class Element {
    constructor() { this.children = []; this.listeners = {}; this.dataset = {}; this.value = ''; this.disabled = false; this.hidden = false; this.scrollHeight = 500; this._text = ''; }
    get textContent() { return this._text + this.children.map(c => c.textContent).join(' '); }
    set textContent(value) { this._text = String(value); this.children = []; }
    get lastElementChild() { return this.children.at(-1); }
    append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }
    replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
    remove() { if (this.parent) { this.parent.children = this.parent.children.filter(n => n !== this); } }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    fire(name, event = {}) { if (!this.disabled) { this.listeners[name]?.(event); } }
    focus() { this.focused = true; }
}
function ui(previous = {}) {
    const elements = new Map();
    const get = id => { if (!elements.has(id)) { elements.set(id, new Element()); } return elements.get(id); };
    get('mode').value = 'agent';
    const posts = []; let state; let handler;
    runInNewContext(chatScript, {
        document: {getElementById: get, createElement: () => new Element()},
        window: {addEventListener: (name, fn) => { if (name === 'message') { handler = fn; } }},
        acquireVsCodeApi: () => ({getState: () => previous, setState: s => {state = JSON.parse(JSON.stringify(s));}, postMessage: p => posts.push(JSON.parse(JSON.stringify(p)))}),
    });
    return {get, posts, state: () => state, send: data => handler({data})};
}

test('Debug joins three sections in one user message while preserving structured API fields', () => {
    const app = ui();
    app.send({type:'source',path:'C:\\project\\pricing.py'});
    assert.equal(app.get('source').textContent, 'pricing.py');
    app.get('prompt').value = 'Fix the checkout'; app.get('traceback').value = 'AssertionError: 90 != 85';
    app.get('tests').value = 'tests/test_checkout.py::test_case';
    app.get('send').fire('click');
    const user = app.state().messages;
    assert.equal(user.length, 1); assert.equal(user[0].sections.length, 3);
    assert.deepEqual(user[0].sections.map(s => s.text), ['Fix the checkout','AssertionError: 90 != 85','tests/test_checkout.py::test_case']);
    const posted = app.posts.at(-1);
    assert.equal(posted.type, 'debug'); assert.equal(posted.userMessage,'Fix the checkout');
    assert.equal(posted.errorLog, 'AssertionError: 90 != 85');
    assert.equal(posted.failingTests,'tests/test_checkout.py::test_case');
    app.send({type:'started',source:'pricing.py'});
    for (const name of ['prompt','traceback','tests']) { assert.equal(app.get(name).value, ''); }
    assert.equal(app.state().messages[0].source, 'pricing.py');
});

test('New session clears chat, every input, status and stale result controls', () => {
    const app = ui();
    app.get('prompt').value='Old request'; app.get('send').fire('click'); app.send({type:'started',source:'a.py'});
    app.send({type:'debugResult',result:{session_id:'old',status:'completed',explanation:'Previous answer',patch:'diff',verification_status:'passed'}});
    app.get('prompt').value='Draft'; app.get('traceback').value='Old error'; app.get('tests').value='Old test';
    app.get('newSession').fire('click');
    assert.deepEqual(app.state().messages, []);
    for (const name of ['prompt','traceback','tests']) { assert.equal(app.get(name).value,''); }
    assert.equal(app.get('results').hidden,true); assert.equal(app.get('patch').disabled,true);
    assert.equal(app.get('verification').disabled,true); assert.equal(app.get('sessionId').textContent,'');
    assert.equal(app.posts.at(-1).type,'newSession'); assert.equal(app.get('welcome').hidden,false);
});

test('the next Debug replaces a completed run rather than mixing transcripts', () => {
    const app=ui();
    app.get('prompt').value='First request'; app.get('send').fire('click'); app.send({type:'started',source:'a.py'});
    app.send({type:'debugResult',result:{status:'completed',session_id:'one',explanation:'First answer',patch:null}});
    app.get('prompt').value='Second request'; app.get('send').fire('click');
    assert.equal(app.state().messages.length,1);
    assert.equal(app.state().messages[0].sections[0].text,'Second request');
    assert.doesNotMatch(app.get('messages').textContent,/First answer/);
});

test('running sessions cannot be reset and empty requests do not erase a result', () => {
    const app=ui();
    app.get('prompt').value='Request'; app.get('send').fire('click');
    app.get('newSession').fire('click');
    assert.equal(app.state().messages.length,1);
    app.send({type:'debugResult',result:{status:'completed',session_id:'one',explanation:'Answer',patch:null}});
    app.get('prompt').value=''; app.get('send').fire('click');
    assert.equal(app.state().messages.length,2);
    assert.equal(app.get('prompt').focused,true);
});

test('HTML presents one composer with three labelled inputs and a Debug action', () => {
    const html=webviewHtml();
    assert.match(html,/aria-label="Debug message"/);
    for (const id of ['prompt','traceback','tests']) { assert.match(html,new RegExp('textarea id="'+id+'"')); }
    assert.match(html,/id="sendLabel">Debug/); assert.match(html,/New session/);
    assert.doesNotMatch(html,/innerHTML/);
});
