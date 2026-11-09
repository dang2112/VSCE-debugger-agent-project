import * as vscode from 'vscode';
import { DebugViewProvider } from './DebugViewProvider';

export function activate(context: vscode.ExtensionContext) {
    const provider = new DebugViewProvider();
    context.subscriptions.push(provider, vscode.window.registerWebviewViewProvider(DebugViewProvider.viewType, provider,
        { webviewOptions: { retainContextWhenHidden: true } }));
}
export function deactivate() {}
