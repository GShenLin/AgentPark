# Cloud frontend deployment on Windows startup

`build_and_run.bat` calls `deploy_frontend.py` once after a successful WebUI build,
before continuing Python dependency updates and local server startup. This uses
the existing Workbench login and the same ECS instance configured in
`tls_workbench.py`. It does not require or store another password.

Deployment is optional for local startup. A missing CLI, failed login/upload,
unavailable cloud host or installer failure produces a warning and continues the
launcher. The Workbench commands share a 90-second deadline and cannot prompt on
stdin. Startup repair attempts do not retry deployment in the same launch.

The current deployed frontend remains backed up before a changed release. Assets
are installed before `index.html`, with earlier fingerprinted assets retained for
open pages. Identical builds do not create another backup. Concurrent installers
cannot interleave their writes. The cloud service and local server are not
restarted by this deployment helper.

The deployment transcript is `.runtime/frontend-deploy/latest.log`; each release
directory contains its archive and, after success, `receipt.json`. Launcher
warnings also appear in its existing startup log.

To publish an already-built frontend independently:

```powershell
python deploy/peer-network/deploy_frontend.py
```

The standalone helper returns a nonzero exit code on failure. The batch launcher
explicitly treats that result as a warning, not a startup failure.

公开仓库中的云主机实例 ID 是占位符。部署前在 `tls_workbench.py` 配置自己的实例，并登录对应 Workbench 账号。
