@echo off
rem Copy this file to scripts\codex_bridge.local.cmd and adjust it for your machine.
rem On Windows, prefer a non-WindowsApps entry such as:
rem C:\Users\<you>\AppData\Roaming\npm\codex.cmd

set "CODEX_BRIDGE_COMMAND=C:\path\to\codex.cmd"
set "CODEX_BRIDGE_HOST=127.0.0.1"
set "CODEX_BRIDGE_PORT=8765"
set "CODEX_BRIDGE_WORKDIR=%~dp0.codex-bridge-workdir"
set "CODEX_BRIDGE_DEFAULT_MODEL=gpt-5.4"
set "CODEX_BRIDGE_DEFAULT_REASONING_EFFORT=high"
set "CODEX_BRIDGE_API_TOKEN="
set "CODEX_BRIDGE_EXTRA_ARGS="
