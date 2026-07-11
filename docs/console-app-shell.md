# ConsoleApp Application Shell

`src/console/app.py` introduces `ConsoleApp`, the console application shell.
It owns dependency lookup, request counters, HTTP server binding, and startup /
shutdown lifecycle hooks.

## Current Migration State

`image-studio.py` remains the compatibility composition root while service
construction is migrated incrementally. `StudioHandler` now prefers
`self.server.app` for normal request handling and falls back to existing module
globals when tests or legacy callers instantiate the handler without an app.

The app currently owns:

- startup hooks for token creation, proxy startup, and Dedicated policy worker
- shutdown cleanup for terminal sessions
- request counters
- auth, rate limit, quota, audit, API handler, template, metrics, static image,
  wallpaper, and auth-session dependencies used by `StudioHandler`
- HTTP server construction with `server.app` binding

## Usage

`main()` builds the app and starts the server:

```python
app = build_console_app()
console_token = app.startup()
server = app.make_server(args.host, args.port, StudioHandler)
```

Tests can instantiate `ConsoleApp` directly with fake dependencies:

```python
app = ConsoleApp("test-console", "1", dependencies={
    "console_status": lambda: {"status": "ok"}
})
```

## Migration Rule

New handler-facing dependencies should be added to `build_console_app()` and
accessed through `self.app_call(...)`. Existing global functions remain only as
compatibility fallbacks until the composition root is fully moved into
`src/console/app.py`.
