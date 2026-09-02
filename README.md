# scripts/

## What runs when

**Nothing here runs per pipeline.** The pipeline executes exactly one
of these — `gdrive_sync.py`, after a deploy. Everything else is a
library it imports, or a tool a person runs deliberately.

| run this | when |
| --- | --- |
| `python3 scripts/cleo_kpis.py` | CLEO's KPI pipeline. |
| `python3 scripts/commit_all.py` | Commit all four repos. Run periodically; it refuses to commit anything that looks like a secret. |
| `python3 scripts/convert_docs_to_pdf.py` | Turn product markdown into PDFs. |
| `python3 scripts/create_remotes.py` | Give a repo a GitHub remote. Still needed — ducorn and scripts have no upstream. |
| `python3 scripts/delete_run.py` | Remove a pipeline run completely — process, rows, checkpoints. For a run you want gone, not resumed. |
| `python3 scripts/doctor.py` | Is this machine healthy? Run before a pipeline, after any change, and first when something breaks. |
| `python3 scripts/ducorn_digest.py` | The daily digest, from real agent activity. |
| `python3 scripts/ducorn_proxy.py` | The model router on :4001. Runs as a launchd service. |
| `python3 scripts/echo_support.py` | ECHO's support triage. |
| `python3 scripts/gdrive_sync.py` | Markdown to PDF into Drive. The pipeline runs this itself after a deploy — the only script it invokes. |
| `python3 scripts/install_playwright.py` | Put a browser where the UI gate can reach it. |
| `python3 scripts/litellm_budget.py` | Create or cap a per-agent LiteLLM key. |
| `python3 scripts/migrate.py` | Apply pending database migrations. Bare = apply; --status to look first. |
| `python3 scripts/reorganize_drive.py` | Move existing Drive PDFs into the derived folder layout. |
| `python3 scripts/slack_bot.py` | The approval path. Runs as a launchd service. |
| `python3 scripts/start_litellm.py` | Starts LiteLLM on :4000. |
| `python3 scripts/tidy_scripts.py` | This. Keeps scripts/ readable as things accumulate. |
| `python3 scripts/vendor_web_guidelines.py` | Re-vendor the interface guidelines the design review reads. |

## What to run when something is wrong

| run this | what it proves |
| --- | --- |
| `python3 scripts/prove_db_contracts.py` | Code and schema agree on every status value. |
| `python3 scripts/prove_deploy.py` | 31 checks over the deploy path — interpreter, service plan, config, smoke test, plist. |
| `python3 scripts/prove_ui_gate.py` | The UI gate really does reject a UI with no tests. |
| `python3 scripts/test_ducorn_proxy.py` | The router, against a fake LiteLLM. No network. |
| `python3 scripts/test_regressions_sept1.py` | The failures of 31 Aug – 1 Sept, kept honest. |
| `python3 scripts/test_screenshot.py` | The screenshot tool, against a real browser. |
| `python3 scripts/test_voice_ai.py` | Voice AI performance. |
| `python3 scripts/test_writer_done.py` | The writer tool ends a task instead of looping. |
| `python3 scripts/test_writer_escapes.py` | The writer-tool escape check. |
| `python3 scripts/verify_design_wiring.py` | The design wiring, without running a pipeline. |

### The short version

```
python3 scripts/doctor.py          # before a pipeline, and when anything breaks
python3 scripts/commit_all.py -m "..." --apply
```

`doctor.py` prints the command that fixes every check it fails. That is the
intended entry point for someone who does not know this machine.

## Libraries

Imported, never run: `bootstrap_python.py`, `drive_routing.py`, `ducorn_classifier.py`, `ducorn_db.py`, `ducorn_env.py`, `product_paths.py`.

## applied/

Spent patches. Each edited a file once, guards itself, and now exits
immediately. Kept for the reasoning in their docstrings — see
`applied/MANIFEST.md`. Not a toolkit.

## _backups/

Timestamped copies written by patches before they edited a file. Git holds
every one of these versions already; the folder is safe to delete once you
trust the commits.
