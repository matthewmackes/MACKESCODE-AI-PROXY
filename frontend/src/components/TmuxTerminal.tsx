import { useEffect, useMemo, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { apiWebSocketUrl } from '../api/auth';
import type { TmuxWorkspacePayload } from '../api/generated/v2Client';

type Props = {
  active: boolean;
  canControl: boolean;
  sessionName: string;
  workspace?: TmuxWorkspacePayload;
};

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
      theme: { background: '#0b0d10', foreground: '#f4f4f4' }
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
    socket.onclose = () => {
      setConnected(false);
      setStatusText('Detached');
      terminal.writeln('\r\n[tmux detached]');
    };
    socket.onmessage = (event) => {
      if (typeof event.data === 'string') {
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
