# Contributing

Run these checks after changing code:

```bash
python3 -m py_compile do-anthropic-proxy.py
python3 -m py_compile image-studio.py matts-image matts-console.py
bash -n claude-DO.sh claude-codex claude-deepseek claude-deepseek-v4 claude-glm claude-mistral claude-sd35
./claude-DO.sh --restart --list-models
./claude-DO.sh --test-models
./matts-console.py --no-open
```

For proxy changes, verify:

- `/v1/models` exposes only the current Matts Value Set models and aliases.
- `/v1/messages` translates Claude Code requests to DigitalOcean chat completions.
- `/v1/images/generations` still routes Stable Diffusion requests.
- cost and budget endpoints keep returning valid JSON.
