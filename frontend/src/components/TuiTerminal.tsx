import { useEffect, useMemo, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { apiWebSocketUrl } from '../api/auth';
import { terminalTheme } from './terminalTheme';

const MAX_RECONNECT_ATTEMPTS = 3;
const RECONNECT_DELAY_MS = 3000;

type Props = {
  clientId: string;
  controller: boolean;
};

export default function TuiTerminal({ clientId, controller }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const controllerRef = useRef(controller);
  const retryCountRef = useRef(0);
  const retryTimerRef = useRef<number | null>(null);
  const [connected, setConnected] = useState(false);
  const url = useMemo(() => {
    return apiWebSocketUrl(`/v2/console/tui/ws?client_id=${encodeURIComponent(clientId)}`);
  }, [clientId]);

  useEffect(() => {
    controllerRef.current = controller;
    if (terminalRef.current) {
      terminalRef.current.options.disableStdin = !controller;
    }
  }, [controller]);

  useEffect(() => {
    if (!hostRef.current) return;
    let disposed = false;
    const terminal = new Terminal({
      cursorBlink: true,
      convertEol: true,
      disableStdin: !controllerRef.current,
      fontFamily: '"IBM Plex Mono", Menlo, "DejaVu Sans Mono", "Bitstream Vera Sans Mono", Courier, monospace',
      fontSize: 13,
      theme: terminalTheme
    });
    terminal.open(hostRef.current);
    terminal.writeln('Connecting to MDE LLM-PROXY TUI...');
    terminalRef.current = terminal;
    retryCountRef.current = 0;

    const connect = () => {
      if (disposed) return;
      const socket = new WebSocket(url);
      socket.binaryType = 'arraybuffer';
      socketRef.current = socket;
      socket.onopen = () => {
        if (disposed) return;
        retryCountRef.current = 0;
        setConnected(true);
      };
      socket.onerror = () => {
        if (disposed) return;
        setConnected(false);
      };
      socket.onclose = () => {
        if (disposed) return;
        setConnected(false);
        if (retryCountRef.current < MAX_RECONNECT_ATTEMPTS) {
          retryCountRef.current += 1;
          terminal.writeln('\r\n[Connection lost — retrying in 3s]');
          retryTimerRef.current = window.setTimeout(connect, RECONNECT_DELAY_MS);
        } else {
          terminal.writeln('\r\n[Connection lost — reopen this panel to retry]');
        }
      };
      socket.onmessage = (event) => {
        if (disposed) return;
        if (typeof event.data === 'string') {
          terminal.writeln(`\r\n${event.data}`);
        } else {
          terminal.write(new Uint8Array(event.data));
        }
      };
    };
    connect();

    terminal.onData((data) => {
      const socket = socketRef.current;
      if (controllerRef.current && socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input', data }));
      }
    });
    return () => {
      disposed = true;
      if (retryTimerRef.current !== null) {
        window.clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
      socketRef.current?.close();
      socketRef.current = null;
      terminal.dispose();
      terminalRef.current = null;
      setConnected(false);
    };
  }, [url]);

  return (
    <div className="terminalFrame" data-testid="tui-terminal">
      <div className="terminalStatus" data-testid="tui-terminal-status">{connected ? 'Connected' : 'Disconnected'} · {controller ? 'Controller' : 'Read-only'}</div>
      <div ref={hostRef} className="terminalHost" data-testid="tui-terminal-host" />
    </div>
  );
}
