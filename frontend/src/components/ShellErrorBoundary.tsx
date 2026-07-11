import React, { ErrorInfo, ReactNode } from 'react';
import { V2_RESETTABLE_WORKSPACE_KEYS } from '../pages/HeroPages';

export const V2_FATAL_ERROR_DIAGNOSTIC_KEY = 'matts-v2-fatal-error-diagnostic';

type ShellErrorBoundaryState = {
  error: Error | null;
};

function clearRecoverableShellState(): void {
  try {
    V2_RESETTABLE_WORKSPACE_KEYS.forEach((key) => window.sessionStorage.removeItem(key));
    window.sessionStorage.removeItem(V2_FATAL_ERROR_DIAGNOSTIC_KEY);
  } catch {
    // Recovery should still continue when browser storage is unavailable.
  }
}

export class ShellErrorBoundary extends React.Component<{ children: ReactNode }, ShellErrorBoundaryState> {
  state: ShellErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ShellErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('V2 shell render failure', error, info.componentStack);
  }

  reload = () => {
    clearRecoverableShellState();
    window.location.reload();
  };

  resetWorkspace = () => {
    clearRecoverableShellState();
    if (window.location.hash !== '#chat') window.history.replaceState(null, '', '#chat');
    this.setState({ error: null });
  };

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="fatalShell" data-testid="v2-fatal-error-boundary">
        <div className="fatalShellPanel">
          <span className="fatalShellMark">
            <img className="carbonIcon" src="/branding/Mackes-Carbon/scalable/apps/ai-governance--tracked.svg" alt="" aria-hidden="true" />
          </span>
          <div>
            <p className="eyebrow">Shell Recovery</p>
            <h1>V2 recovered from a render failure</h1>
            <p>The shell caught a fatal interface error before the page went blank. Reset the saved workspace state or reload the browser session.</p>
          </div>
          <pre className="fatalShellDetail">{this.state.error.message || 'Unknown render failure'}</pre>
          <div className="fatalShellActions">
            <button className="primaryButton" type="button" onClick={this.resetWorkspace}>Reset Workspace</button>
            <button className="secondaryButton" type="button" onClick={this.reload}>Reload</button>
          </div>
        </div>
      </div>
    );
  }
}
