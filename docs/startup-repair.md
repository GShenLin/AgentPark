# Windows startup recovery

`Restart.bat` delegates to an independent hidden PowerShell worker. The wrapper's
successful exit means restart was accepted; it does not claim the new server is ready.

The worker stops the previous workspace processes and runs the canonical
`build_and_run.bat`. Startup output is captured separately from the interactive
Companion console, so its terminal input/output handles remain intact. The launcher
records the new server PID and waits up to 90 seconds for its PID file and
`/api/system/status` to agree on that process. A listening port or a different
AgentPark instance is not sufficient evidence of readiness.

When stopping/building/startup fails, the worker runs `scripts/repair_startup.bat`,
which only requires the Python bootstrap, and starts `python -m src.startup_repair`.
The repair Companion runs directly through the Agent node, without the web backend
or Companion MCP. It receives restart/build/dependency/server log tails and can read
the complete logs with local tools. Its working directory is the AgentPark project;
its tools are local file reading/writing, search, patching and terminal execution.
Remote bindings, MCP servers, skills and plugins from the interactive Companion are
not included in this dedicated startup repair context.

The repair process uses the explicit `provider_id` and `model` from the canonical
Companion configuration in the configured memories directory. Settings > Companion
offers Provider ID and Model ID separately and rejects missing/incompatible model
bindings on save. Incomplete existing settings remain readable so they can be edited.
Recovery does not silently choose another Provider or Model.

After the repair turn exits, the worker reruns `build_and_run.bat` and verifies
readiness again. The model does not launch another restart worker itself. Up to
three repair turns are allowed; persistent startup failure or a failed repair
process exits with an error and retains the evidence. A model response saying
"fixed" is not treated as successful startup.

Evidence is retained in UTF-8 under `.runtime/`:

- `restart-worker-<pid>.log`: phases, failed build output and repair output.
- `restart-build-<pid>-<attempt>.log`: each startup attempt's complete output.
- `agentpark-server.log` / `agentpark-server.err.log`: most recent server output.
- `startup-repair/<session>/`: repair configuration (no Provider credentials),
  failure context and persisted conversation.

The recovery process still requires a usable Python environment, importable Agent
runtime, valid Companion model configuration and a reachable model Provider. If
these fail, the traceback is recorded and recovery stops explicitly. Failure to
create the independent Windows worker cannot be handled by that worker.

Verification uses isolated temporary workspaces and fake build/repair executables
to exercise retries without stopping the running project or invoking paid models.
The canonical build script is also tested with a deliberately failing npm fixture;
HTTP readiness is tested against a real local HTTP test server with PID mismatch
checks. Frontend tests cover model selection and Provider changes.
