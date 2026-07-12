import { useEffect, useMemo, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { apiWebSocketUrl } from '../api/auth';
import { terminalTheme } from './terminalTheme';

type Props = {
  clientId: string;
  controller: boolean;
};

export default function TuiTerminal({ clientId, controller }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const url = useMemo(() => {
    return apiWebSocketUrl(`/v2/console/tui/ws?client_id=${encodeURIComponent(clientId)}`);
  }, [clientId]);

  useEffect(() => {
    if (!hostRef.current) return;
    const terminal = new Terminal({
      cursorBlink: true,
      convertEol: true,
      disableStdin: !controller,
      fontFamily: '"IBM Plex Mono", Menlo, "DejaVu Sans Mono", "Bitstream Vera Sans Mono", Courier, monospace',
      fontSize: 13,
      theme: terminalTheme
    });
    terminal.open(hostRef.current);
    terminal.writeln('Connecting to MDE LLM-PROXY TUI...');
    terminalRef.current = terminal;

    const socket = new WebSocket(url);
    socket.binaryType = 'arraybuffer';
    socketRef.current = socket;
    socket.onopen = () => setConnected(true);
    socket.onclose = () => {
      setConnected(false);
      terminal.writeln('\r\n[TUI disconnected]');
    };
    socket.onmessage = (event) => {
      if (typeof event.data === 'string') {
        terminal.writeln(`\r\n${event.data}`);
      } else {
        terminal.write(new Uint8Array(event.data));
      }
    };
    terminal.onData((data) => {
      if (controller && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input', data }));
      }
    });
    return () => {
      socket.close();
      terminal.dispose();
    };
  }, [controller, url]);

  return (
    <div className="terminalFrame" data-testid="tui-terminal">
      <div className="terminalStatus" data-testid="tui-terminal-status">{connected ? 'Connected' : 'Disconnected'} · {controller ? 'Controller' : 'Read-only'}</div>
      <div ref={hostRef} className="terminalHost" data-testid="tui-terminal-host" />
    </div>
  );
}
