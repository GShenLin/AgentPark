# Windows startup recovery

`Restart.bat` delegates to an independent hidden PowerShell worker. The wrapper's
successful exit means restart was accepted; it does not claim the new server is ready.

The worker stops the previous workspace processes and launches the canonical
`build_and_run.bat` once. The build launcher owns startup, standalone Companion
recovery and up to three repair attempts, so direct launches get the same recovery
as restarts. The worker never runs a second recovery loop.

The launcher always retains a startup transcript under `.runtime/` (or the explicit
`AGENTPARK_STARTUP_LOG` path). Startup and repair output are captured separately
from the interactive Companion console, preserving terminal handles. A failed
attempt invokes `scripts/repair_startup.bat`, which needs only the Python bootstrap,
and starts `python -m src.startup_repair`. The repair Companion runs through the
Agent node without the web backend. Startup errors do not pause before recovery.

After repair, the launcher rebuilds and waits up to 90 seconds for its new server's
PID file and `/api/system/status` to agree on that process. A listening port or a
different AgentPark instance is not sufficient evidence of readiness.

The canonical Companion configuration stores a `profile_id` referencing an Agent
Preset in `agent/`. Settings > Companion selects that Preset; its provider, explicit
model, instructions and capabilities are edited in Node Preset Editor. The bundled
`Companion` Preset is shared by regular conversations and recovery. Identity, session
state and the local working directory remain on the Companion node. Preset changes
are loaded on the next turn; missing/invalid Presets or models fail explicitly.
Recovery snapshots the resolved model settings and overrides the execution directory
and capabilities for a standalone local repair. It does not alter the selected Preset.

After the repair turn exits, the launcher reruns its build phase and verifies
readiness again. The model does not launch another build or restart itself. Up to
three repair turns are allowed; persistent startup failure or a failed repair
process exits with an error and retains the evidence. A model response saying
"fixed" is not treated as successful startup.

Evidence is retained in UTF-8 under `.runtime/`:

- `restart-worker-<pid>.log`: restart handoff, readiness and final failure evidence.
- `startup-<run>.log` / `restart-build-<pid>.log`: all build attempts and repair output.
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
