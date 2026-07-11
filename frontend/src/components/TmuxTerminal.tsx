import { useEffect, useMemo, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { apiWebSocketUrl } from '../api/auth';
import type { TmuxWorkspacePayload } from '../api/generated/v2Client';
import { terminalTheme } from './terminalTheme';

type Props = {
  active: boolean;
  canControl: boolean;
  sessionName: string;
  workspace?: TmuxWorkspacePayload;
};

function bridgeMessageText(value: unknown): string {
  if (!value || typeof value !== 'object') return '';
  const row = value as Record<string, unknown>;
  if (row.type === 'denied') {
    const decision = row.decision && typeof row.decision === 'object' ? row.decision as Record<string, unknown> : {};
    return `TMux attach denied: ${decision.required_permission || 'tmux_control'} permission required.`;
  }
  if (row.type === 'error') {
    return `TMux attach failed: ${row.code || 'unknown_error'}${row.session ? ` (${row.session})` : ''}`;
  }
  return '';
}

function tmuxWebSocketUrl(sessionName: string, workspace?: TmuxWorkspacePayload): string {
  const terminal = workspace?.terminal;
  const url = new URL(apiWebSocketUrl(terminal?.websocket_path || '/ws/tmux', { defaultPort: terminal?.default_legacy_port }));
  url.searchParams.set(terminal?.query_param || 'name', sessionName);
  url.searchParams.set('cols', '120');
  url.searchParams.set('rows', '40');
  return url.toString();
}

export default function TmuxTerminal({ active, canControl, sessionName, workspace }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [statusText, setStatusText] = useState('Detached');
  const url = useMemo(() => (sessionName ? tmuxWebSocketUrl(sessionName, workspace) : ''), [sessionName, workspace]);

  useEffect(() => {
    if (!active || !sessionName || !hostRef.current) {
      setConnected(false);
      setStatusText(sessionName ? 'Ready to attach' : 'Select a session');
      return undefined;
    }
    if (!canControl) {
      setStatusText('TMux control permission required');
      return undefined;
    }
    const terminal = new Terminal({
      cols: 120,
      rows: 40,
      cursorBlink: true,
      convertEol: true,
      fontFamily: 'IBM Plex Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
      fontSize: 13,
      theme: terminalTheme
    });
    terminal.open(hostRef.current);
    terminal.writeln(`Attaching to tmux session: ${sessionName}`);
    terminalRef.current = terminal;

    const socket = new WebSocket(url);
    socketRef.current = socket;
    socket.onopen = () => {
      setConnected(true);
      setStatusText('Attached');
    };
    socket.onerror = () => {
      setStatusText('Attach failed');
    };
    socket.onclose = (event) => {
      setConnected(false);
      const cleanClose = event.code === 1000 || event.code === 1001;
      const detail = event.reason || (cleanClose ? 'detached' : `closed ${event.code}`);
      setStatusText(cleanClose ? 'Detached' : 'Attach closed');
      terminal.writeln(`\r\n[tmux ${detail}]`);
    };
    socket.onmessage = (event) => {
      if (typeof event.data === 'string') {
        const trimmed = event.data.trim();
        if (trimmed.startsWith('{')) {
          try {
            const bridgeText = bridgeMessageText(JSON.parse(trimmed));
            if (bridgeText) {
              terminal.writeln(`\r\n${bridgeText}`);
              return;
            }
          } catch {
            // Not a bridge control message; write it to the terminal below.
          }
        }
        terminal.write(event.data);
      } else {
        terminal.write(new Uint8Array(event.data));
      }
    };
    terminal.onData((data) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(data);
      }
    });

    return () => {
      socket.close();
      terminal.dispose();
      socketRef.current = null;
      terminalRef.current = null;
      setConnected(false);
    };
  }, [active, canControl, sessionName, url]);

  return (
    <div className="terminalFrame tmuxAttachFrame" data-testid="tmux-attach-terminal">
      <div className="terminalStatus" data-testid="tmux-attach-status">
        {connected ? 'Connected' : statusText} · {sessionName || 'No session selected'}
      </div>
      <div ref={hostRef} className="terminalHost tmuxAttachHost" data-testid="tmux-attach-host" />
    </div>
  );
}
