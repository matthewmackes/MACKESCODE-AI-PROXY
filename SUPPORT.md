# Support

This repository is maintained for private/operator use.

## Getting Help

Start with:

- `README.md` for setup and operation
- `SECURITY.md` for tokens, runtime state, roles, and incident response
- `RELEASE.md` for upgrade, rollback, and health validation
- `GOVERNANCE.md` for architectural locks and work rules
- `docs/NEEDS-OPERATOR.md` for items that require live resources or decisions

Useful local diagnostics:

```bash
./claude-DO.sh --doctor
./claude-DO.sh --list-models
scripts/health-validate.py --allow-degraded-console
scripts/release-check.sh
```

## Security Issues

Do not post access keys, DigitalOcean tokens, console URLs with tokens, trace
logs, billing payloads, or Dedicated endpoint credentials in public issues or
chat. Follow `SECURITY.md` for vulnerability and incident guidance.
