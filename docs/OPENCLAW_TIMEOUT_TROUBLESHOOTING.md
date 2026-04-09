# OpenClaw Timeout Troubleshooting

Use this note when OpenClaw times out before it can call any `rockburst-*` tool.

## Symptom Split

- If `rockburst_agent_briefing` fails but a no-tool prompt still answers, debug the plugin or backend.
- If even `Reply with exactly: hi` times out, debug the model layer first.

## What We Confirmed In This Workspace

- `openclaw` was configured to use `openai/gpt-5.4`.
- The timeout reproduced on pure no-tool prompts, so the plugin was not the first failure point.
- `Resolve-DnsName api.openai.com` returned `127.229.0.118` and `fd00:696e:6974:6578::8d:a6`.
- Those are private/special-use addresses, so OpenClaw blocked the request before it reached the OpenAI API.
- `OPENAI_API_KEY` and `DASHSCOPE_API_KEY` were also set to the same value, which is unsafe and usually incorrect.

## Quick Checks

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\diagnose-openclaw.ps1
```

That script checks:

- the OpenClaw CLI path and version
- the configured default model
- the currently available models
- whether `OPENAI_API_KEY` and `DASHSCOPE_API_KEY` are both set and identical
- whether Node/OpenClaw is actually using proxy env vars
- whether a local proxy such as `127.0.0.1:7897` is listening
- whether a Node fetch works in the current shell and with the detected proxy
- whether `api.openai.com` resolves to a special-use IP
- whether the local backend health endpoint is up

## Practical Fixes

1. Do not force `openai/gpt-5.4` unless this machine can reach a real OpenAI endpoint.
2. Fix DNS or proxy routing first if `api.openai.com` resolves to `127.x.x.x`, `10.x.x.x`, `192.168.x.x`, `172.16-31.x.x`, or `fd00::/8`.
3. Do not reuse a DashScope key as `OPENAI_API_KEY`.
4. If Windows has a proxy but Node does not, run OpenClaw through `scripts/openclaw-with-proxy.ps1` or export `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, and `NODE_USE_ENV_PROXY=1`.
5. After plugin setup, choose a reachable model yourself with OpenClaw instead of relying on this repo to overwrite it for you.
6. If the model path is fixed but tools still fail, then start the backend and debug `http://127.0.0.1:8000`.

## Related Files

- `openclaw/rockburst-config.batch.json`
- `openclaw/openclaw.example.json5`
- `scripts/start-demo.ps1`
- `scripts/diagnose-openclaw.ps1`
- `scripts/openclaw-with-proxy.ps1`
