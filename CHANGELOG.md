# Changelog

## v2.1 — Code Review Fixes & VESTA CLI Integration

### Bug Fixes
- **ssh_connect.py**: Fix interactive cd bug — use subprocess ssh for real terminal; add Ed25519Key auto-detection
- **project_manager.py**: Fix path prefix bug (d.replace -> startswith); Shell injection protection;
  OUTCAR Voluntary context switches check; early exit on find errors
- **vasp_check.py**: Fix int(ibrion_val) crash with try/except; narrow con*/ -> con[0-9]*/;
  extract hardcoded path to LOCAL_BASE constant
- **jobs_monitor.py**: Switch bjobs -l to bjobs -o structured output; fix path replace ->
  startswith; isalnum node prefix detection

### New Features
- **struct2ppt.py**: VESTA CLI a/b/c axis rendering with adaptive backoff (1.0s/1.5s/2.5s);
  POSCAR vs CONTCAR side-by-side comparison; no-stretch image sizing
- **Ionic step gate**: vasp_check remote-counts free energy TOTEN in OUTCAR,
  writes .ionic_steps; struct2ppt skips CONTCAR if <5 steps
- **Error status**: Detect "I REFUSE TO CONTINUE" in OUTCAR -> [X] error status

## v2.0 — Full VASP Workflow Automation

- project_manager.py: scan command with 12 prefix rules
- vasp_check.py: SSH convergence check, auto-status, download
- summary_report.py: PPT with per-project grouping
- struct2ppt.py: VESTA CLI rendering
- generate_report.py: unified entrypoint
- jobs_monitor.py: LSF monitoring + queue recommendation
- vesta_view.py: VESTA GUI launcher

## v1.0 — Initial Version

- Basic SSH connection
- Project/subtask CRUD
- VASP convergence check
- Basic status flow
