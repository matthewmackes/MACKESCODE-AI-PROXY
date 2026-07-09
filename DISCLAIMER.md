# Disclaimer

This project is a private-operator tool for local Claude Code routing, model
experimentation, and DigitalOcean Serverless/Dedicated Inference automation. It
is not a managed service and does not provide a warranty, uptime guarantee, cost
guarantee, or security guarantee.

The operator is responsible for:

- protecting model access keys, DigitalOcean tokens, console tokens, JWT
  sessions, endpoint credentials, and runtime logs
- understanding which LLM provider receives each prompt or source-code payload
- monitoring DigitalOcean billing, Dedicated Inference runtime, and teardown
  behavior
- validating model access and regional GPU availability before relying on
  automation
- keeping the console off untrusted networks unless authentication and role
  controls are configured appropriately

Dedicated Inference can create paid cloud resources. The platform includes
budget guards, idle teardown, audit logs, lifecycle feedback, and cost meters,
but the operator remains responsible for cloud account charges and manual
cleanup if automation or external APIs fail.
