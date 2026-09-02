# Applied patches

Each of these edited a file once and is now inert — every one guards
itself and exits with "Already patched". They are kept because their
docstrings explain WHY the code is the way it is, which is the part
that does not survive in a diff.

Nothing here runs per pipeline. Nothing here needs running at all on a
machine that is already patched. To understand a decision, read one.

_Archived 2026-09-02._

| patch | what it did |
| --- | --- |
| `patch_agent_keys.py` | Make each agent spend against its own LiteLLM key. |
| `patch_agent_models.py` | Fix _get_agent_models(): the fifth hardcoded model list, and a live spend leak. |
| `patch_approval_routing.py` | Make approvals say what they release, instead of Slack guessing from prose. |
| `patch_atlas_failure.py` | Let ATLAS see the failure it is being asked about — and be the model you picked. |
| `patch_brief_model.py` | The brief wizard picks its model from the switcher, like everything else. |
| `patch_build_commit.py` | Stop printing "✅ Files committed to GitHub" when nothing was. |
| `patch_build_ui_tests.py` | Tell REX what gate 3 is going to ask for, from the gate's own definition. |
| `patch_checkpoint_prompt.py` | A cached skill result is only valid for the instructions that produced it. |
| `patch_combo_tests.py` | Make the four combination tests test the combinations. |
| `patch_dashboard_failure.py` | Show the operator why the run failed, beside the run that failed. |
| `patch_dashboard_health.py` | Put the health report where the operator already is. |
| `patch_deploy_env.py` | A product that ships a working default should deploy with it. |
| `patch_deploy_services.py` | A product may be more than one service. The deployer assumed otherwise. |
| `patch_deploy_venv.py` | Deploy the product with the interpreter it was built and tested against. |
| `patch_design_import.py` | Make generate_design.py importable, not just runnable. |
| `patch_design_node.py` | Wire the design skill into the pipeline. |
| `patch_design_shots.py` | Show the three designs at the gate instead of linking to them. |
| `patch_design_variants.py` | Make the design gate a real choice: viewable variants, one approval each, |
| `patch_detach_pipeline.py` | Stop API restarts from killing running pipelines. |
| `patch_display_names.py` | Resolve display names server-side, and stop the dashboard inventing its own. |
| `patch_doc_isolation.py` | A document belongs to exactly one product, and the API must say so. |
| `patch_doctor_proof.py` | Turn "these will not happen again" into output you can read. |
| `patch_doctor_prose.py` | Stop a check from failing because the fix is documented. |
| `patch_doctor_undefined.py` | Fix doctor.py's own NameError, and widen the check that failed to catch it. |
| `patch_force_convert.py` | Make --force actually reconvert, and stop counting skips as conversions. |
| `patch_gate2_pause.py` | Make gate_2 actually pause, and stop max_iter from crashing on Anthropic. |
| `patch_gdrive_routing.py` | Replace gdrive_sync.py's FOLDER_MAP with derived routing. |
| `patch_header_clean.py` | Declutter the DuCorn dashboard header: meta left, title center, clock right; |
| `patch_health_api.py` | Make the health report readable by something other than a terminal. |
| `patch_intel_panel.py` | Move DuCorn Intelligence sections into a right slide panel driven by a left icon rail. |
| `patch_jail_message.py` | Make the jail's refusal end the guessing instead of starting it. |
| `patch_kill_button.py` | Add a KILL button to the pipeline panel, and a log mode selector. |
| `patch_light_theme.py` | Full light-theme pass for the DuCorn dashboard. |
| `patch_light_theme2.py` | Second light-theme pass: close the remaining WCAG AA gaps found by audit. |
| `patch_lock_approve.py` | Remove the dead dashboard approval code and stop the approve endpoint |
| `patch_log_and_kill.py` | Make the live log show something, and add a way to stop a running pipeline. |
| `patch_pdf_cover.py` | Stop the running header and footer landing on the cover page. |
| `patch_pdf_pagination.py` | Make the PDF header and footer actually paginate, and the page number appear. |
| `patch_people_upsert.py` | Record a person the first time they are seen. |
| `patch_phase_choices.py` | Make --phase reachable for every node in the graph, by deriving it. |
| `patch_product_url.py` | Say where the product is. Nobody has ever been told. |
| `patch_qa_feedback.py` | Give REX the QA report, and stop the cache from throwing it away. |
| `patch_research_context.py` | Stop the stack inventory from being pasted into every PRD. |
| `patch_research_fix.py` | Fix node_research: the model it uses, the brief it ignores, and the loop. |
| `patch_resume_button.py` | Show RESUME when the RUN failed, not only when a SKILL failed. |
| `patch_resume_map.py` | Teach resume about the design phases, and stop it guessing when it cannot. |
| `patch_router_cap.py` | Bound how much a local model is allowed to say, so a loop cannot be endless. |
| `patch_router_timing.py` | The router waits five minutes for a stalled local model. The test has ten. |
| `patch_service_contract.py` | The product declares what it is. The deployer stops guessing. |
| `patch_shared_paths.py` | Make QA and deploy read the venv path from one place instead of two. |
| `patch_shot_token.py` | Two things the first paid run found. One is mine. |
| `patch_skill_guidelines.py` | Put the interface guidelines in front of the two skills that review interfaces. |
| `patch_skillrunner_re.py` | Import re at module level in skill_runner, and check nothing else has the bug. |
| `patch_status_contracts.py` | One place that says which statuses exist, so the schema can be checked against it. |
| `patch_sync_errors.py` | Print the PDF service's error instead of throwing it away. |
| `patch_test_brief.py` | Fix the seed brief I wrote an hour ago. It sent SAGE hunting for a file. |
| `patch_test_brief2.py` | Third revision of the fixture brief. This time it names nothing. |
| `patch_test_diagnostics.py` | Make the timing-out run leave evidence behind, and name the router. |
| `patch_tests_sept1.py` | Bring test_pipeline.py and test_integration.py back in line with the code. |
| `patch_theme_tokens.py` | Replace hardcoded theme colours with CSS custom properties. |
| `patch_theme_tokens2.py` | Tidy-up after tokenisation: drop leftover hardcoded light rules and give the |
| `patch_ui_ids.py` | The UI gate cannot see a single-quoted id, and passes when it sees nothing. |
| `patch_ui_test_venv.py` | Put the browser where the generated tests actually run. |
| `patch_writer_abort.py` | Break the write loop with a mechanism, because the message did not work. |
| `patch_writer_done.py` | Give the writer tool a way to say "you are finished". |
| `patch_writer_escapes.py` | Stop DuCornWriterTool writing JSON escape sequences into documents. |
