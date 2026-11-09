const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const {relativeWorkspacePath, containedFile} = require('../out/workspacePaths.js');

test('rejects absolute, parent, hidden and dependency paths', () => {
    for (const value of ['../secret.py', '/secret.py', 'C:\\secret.py', '.env', 'a/../../b.py', 'node_modules/a.py']) {
        assert.throws(() => relativeWorkspacePath(value), undefined, value);
    }
    assert.equal(relativeWorkspacePath('src\\main.py'), 'src/main.py');
});

test('contained regular files are readable; directories and oversized files are rejected', async t => {
    const root = await fs.mkdtemp(path.join(os.tmpdir(), 'debugger-path-'));
    t.after(() => fs.rm(root, {recursive: true, force: true}));
    await fs.writeFile(path.join(root, 'main.py'), 'x = 1');
    assert.equal(await containedFile(root, 'main.py'), path.join(root, 'main.py'));
    await fs.mkdir(path.join(root, 'folder'));
    await assert.rejects(containedFile(root, 'folder'), /regular file/);
    await fs.writeFile(path.join(root, 'large.py'), Buffer.alloc(1_000_001));
    await assert.rejects(containedFile(root, 'large.py'), /1 MB/);
});

test('rejects a symlink to a file outside the workspace', async t => {
    const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'debugger-link-'));
    t.after(() => fs.rm(temporary, {recursive: true, force: true}));
    const root = path.join(temporary, 'project'); await fs.mkdir(root);
    const outside = path.join(temporary, 'outside.py'); await fs.writeFile(outside, 'private');
    try { await fs.symlink(outside, path.join(root, 'escape.py')); }
    catch (error) { if (error.code === 'EPERM') { t.skip('Symlink creation is unavailable'); return; } throw error; }
    await assert.rejects(containedFile(root, 'escape.py'), /outside/);
});
