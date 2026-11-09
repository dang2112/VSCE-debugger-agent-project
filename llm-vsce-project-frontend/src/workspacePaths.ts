import * as path from 'node:path';
import { realpath, stat } from 'node:fs/promises';

export function relativeWorkspacePath(value: string): string {
    const normalized = value.replace(/\\/g, '/');
    if (!normalized || normalized === '.' || normalized.includes('\0') || normalized.includes(':') ||
        path.posix.isAbsolute(normalized) || normalized.split('/').some(p => p === '..' || p === '')) {
        throw new Error('File requests must use a workspace-relative path without parent traversal.');
    }
    if (normalized.split('/').some(p => (p.startsWith('.') && p !== '.github') ||
        ['node_modules', 'venv', '__pycache__', 'session_memory'].includes(p))) {
        throw new Error('Hidden, dependency, and session files are not available to the agent.');
    }
    return normalized;
}
export async function containedFile(root: string, relative: string): Promise<string> {
    const normalized = relativeWorkspacePath(relative);
    const actualRoot = await realpath(root);
    const target = await realpath(path.join(actualRoot, normalized));
    const difference = path.relative(actualRoot, target);
    if (!difference || path.isAbsolute(difference) || difference.split(path.sep).includes('..')) {
        throw new Error('Requested file resolves outside this session’s workspace.');
    }
    const info = await stat(target);
    if (!info.isFile() || info.size > 1_000_000) {
        throw new Error('Requested file is not a regular file under the 1 MB limit.');
    }
    return path.join(root, normalized); // Preserve editor URI identity and unsaved buffers.
}
