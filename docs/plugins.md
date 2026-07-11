# Console Plugin Catalog

The plugin catalog is manifest based. The registry discovers JSON manifests
from directories configured in `config/console.json` under
`plugins.directories`. Manifests are loaded and validated, but plugin code is
not executed by this release slice. This is an inventory and compatibility
surface, not a third-party plugin runtime or lifecycle manager.

Supported extension points:

- `console.nav`
- `console.panel`
- `create.prompt_action`
- `code.session_action`
- `model.metadata_enricher`
- `dedicated.lifecycle_hook`
- `reporting.exporter`

Example manifest:

```json
{
  "id": "example-console-panel",
  "name": "Example Console Panel",
  "version": "0.1.0",
  "enabled": false,
  "extensions": [
    {"point": "console.panel", "target": "console", "label": "Example", "module": "example.console.panel"}
  ],
  "config": {}
}
```

Invalid manifests are reported with `status: invalid` and
`invalid_extensions`. Disabled manifests remain visible with `status:
disabled`. This lets operators audit third-party plugin inventory before any
future executable extension layer is enabled.
