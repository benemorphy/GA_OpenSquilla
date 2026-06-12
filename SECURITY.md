# Security Audit

## Overview

Security review of GenericAgent core (`ga.py`, `agentmain.py`, `agent_loop.py`, `llmcore.py`, `launch.pyw`, `squilla_router/`).

## Findings

### 1. API Key Management ✅ Pass
- `mykey.py` is in `.gitignore` (line 30) — not committed
- `mykey_template.py` provides a safe template
- API keys are loaded from `mykey.py` at runtime via `import mykey`

### 2. Code Execution (`eval`/`exec`) ⚠️ By Design
- `ga.py:304-305`: Uses `eval()` and `exec()` to run LLM-generated code
- This is the core tool `code_run` — necessary for the agent to function
- **Mitigation**: Code runs in the agent's process; users should run in isolated environments (VM/container) for untrusted tasks
- **Recommendation**: Consider adding a `--sandbox` mode with Docker isolation

### 3. Subprocess Usage ⚠️ By Design
- `ga.py:58`: `subprocess.Popen` for user-specified commands
- `agentmain.py:219`: `subprocess.Popen` for background tasks
- **Recommendation**: Validate command arguments in high-security deployments

### 4. HTTP Headers with API Keys ✅ Pass
- `llmcore.py:406`: Bearer token via HTTPS only
- Keys never logged or written to disk by GA core

### 5. SquillaRouter ✅ Clean
- No hardcoded secrets or API keys
- Uses environment variable `SQUILLA_ROUTER` for activation
- Model config in `config.py` is safe defaults, overridden by user

### 6. File System Access ⚠️ By Design
- `file_read`/`file_write`/`file_patch` tools can access any path
- Agent has same file permissions as the running user
- **Recommendation**: Run with least-privilege user account

### 7. Shell Install Scripts ⚠️ Caution
- `docs/installation.md` references `curl | bash` pattern
- Users should review scripts before piping to bash
- Scripts hosted on external domain (`fudankw.cn`)

## Recommendations

| Priority | Action |
|----------|--------|
| P0 | Run GA in isolated environment (VM/container) for production use |
| P1 | Add optional `--sandbox` mode for Docker-based code execution |
| P2 | Document that agent inherits user's file system permissions |
| P3 | Consider code signing for install scripts |

## Scope

This audit covers the GenericAgent core and SquillaRouter. Third-party dependencies and frontends are not in scope.
