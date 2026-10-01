# AgentPark Remote for Linux x86-64

This package contains the standalone Remote executable. Python does not need to be installed.
Built on glibc 2.32: use an x86-64 glibc Linux distribution with glibc 2.32 or newer
(for example Ubuntu 22.04/24.04 or Debian 12). Alpine/musl and ARM64 are not supported by this artifact.

## Install system tools

Remote uses the system `curl`, `rg` (ripgrep), and POSIX shell.
Ubuntu/Debian:

```sh
sudo apt-get update
sudo apt-get install -y curl ca-certificates ripgrep
```

## Run on a server without a desktop

Extract the tar.gz, open its folder and run:

```sh
chmod +x AgentParkRemote
./AgentParkRemote --headless --server 203.0.113.10 --workspace /absolute/path/to/project
```

The workspace must already exist. Replace the server with your AgentPark IP/address.
Remote first probes port 8788, then uses the same host's HTTPS authentication center.
Approve first admission at the center. In AgentPark, select this device through
Settings -> Device interconnection or the node's LinkToRemote action.
The node's WorkingPath must be an absolute Linux path on this Remote machine.
Use Ctrl+C to stop. Disconnection does not automatically run work on another device.

## Run with a desktop

```sh
./AgentParkRemote
```

This opens the same connection settings window as the Windows version. An X11 display
(or XWayland) and its normal desktop libraries are required. Tcl/Tk is included.
Remote directory selection is displayed in the initiating AgentPark browser and reads
the Linux filesystem remotely. It works on headless servers without an X11 display.

Settings, identity and logs are stored at `$XDG_CONFIG_HOME/AgentParkRemote`, or
`~/.config/AgentParkRemote` when XDG_CONFIG_HOME is unset. `--state-directory` overrides this.
Keep the identity directory across upgrades to preserve node bindings.

## Rebuild

Build on Linux with Python 3.11, Tk, binutils, curl and ripgrep installed:

```sh
python3.11 -m venv .runtime/remote-linux-venv
.runtime/remote-linux-venv/bin/pip install -r deploy/remote-worker/requirements.txt
.runtime/remote-linux-venv/bin/python deploy/remote-worker/build_linux.py
```

Output: `dist/AgentParkRemote-linux-x86_64.tar.gz` and its SHA256 file.
The executable inherits the build host's glibc minimum; building on a newer
distribution changes that minimum. macOS and ARM64 require their own build environments.
