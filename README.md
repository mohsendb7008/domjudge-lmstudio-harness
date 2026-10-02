# DOMjudge 9 + LM Studio starter

This bundle contains 11 individual NCPC 2025 problem imports, public problem prompts, reference solutions, and a Python harness. It connects your local LM Studio server to your local DOMjudge server and saves actual experiment results. Python 3.10 or newer is sufficient; no pip packages are required.

## 1. Fix the upload error

The original problemset archive exceeds Git's 25M `post_max_size`. Extract **instagraph.7z** in imports folder. In the DOMjudge jury interface, import **one ZIP from `imports/` at a time**, starting with `arithmeticadaptation.zip`. The largest individual import is approximately 35 MB, comfortably below the DOMServer limit. The packages have their problem files at the ZIP root.

Create a contest, add the problems, enable submissions and judging, and set a contest window that covers the experiment. Create a team and linked **team user** named `llm-qwen`, and assign the team to the contest. Create a separate team/user `llm-gemma` when you add that model. The judgehost account is for the daemon; use team accounts for the harness. Confirm that your judgehost is active.

The supplied source archive has no official numeric per-problem time limit. DOMjudge 9's importer defaults a missing time limit to 10 seconds; that is an importer default, not an NCPC contest setting. Review time, memory, output and language limits. Calibrate them using the supplied reference solutions before collecting results, and freeze them across models. Inspect each reference verdict; an internal error or a rejected reference solution means the contest is not ready. Calibration submissions are separate from the harness's LLM results.

## 2. Install and load a model

Start with **Qwen2.5-Coder-7B-Instruct, GGUF Q4_K_M**, subject to available memory. For a second family, try **Gemma 3 4B IT, GGUF Q4_K_M**. They differ in size: this initial comparison is of practical local configurations, rather than equal-sized architectures. Load only the model you are evaluating and start LM Studio's local server on port **1234**. An 8192-token context is a starting setting for these short prompts and the 4096-token response budget.

## 3. Configure and check the connection

Open a terminal **inside the extracted `domjudge-lmstudio-starter` folder**. The commands below work with `python`; use `python3` on systems where that is the installed command.

```text
python harness.py doctor --model qwen
```

Enter the `llm-qwen` team's password privately when asked. Alternatively, set `DOMJUDGE_PASSWORD` in that terminal; credentials are not saved in result files. `DOMJUDGE_USER` overrides the configured username, so leave it unset when switching between configured team users.

Edit `config.json` with the contest ID, enabled C++ language ID, and Qwen's LM Studio model ID printed by `doctor`. Ensure the selected DOMjudge C++ compilation command uses C++17. Run `doctor` again to inspect the team's contest account and problem IDs. The starter assumes problem IDs match the imported external IDs; if your installation returns other IDs, update each `judge_id` to the value displayed. Keep all other settings unchanged for the pilot.

Default endpoints, when running the harness on the same computer:

| Service | Endpoint |
| --- | --- |
| DOMjudge | `http://localhost:8080/api/v4` |
| LM Studio | `http://localhost:1234/v1` |

Submit one known reference solution to check the judge:

```text
python harness.py submit-file --model qwen --problem arithmeticadaptation --file reference_solutions/arithmeticadaptation.cpp
```

An **AC** is the expected outcome. Then run a single LLM pilot:

```text
python harness.py run --model qwen --problem arithmeticadaptation --repeat 1
```

## 4. Run the experiment

After checking imports and references for all problems:

```text
python harness.py run --model qwen
```

The default configuration evaluates 11 problems with three repetitions per model, up to three attempts per repetition. Each repetition starts a fresh conversation. An accepted solution ends that repetition. After a rejected solution the model receives only the verdict, such as WA or CE, and its prior response. The harness generates and judges sequentially.

After the Qwen batch, load Gemma in LM Studio, set its exact identifier and notes in `config.json`, and use the separate Gemma team:

```text
python harness.py doctor --model gemma
python harness.py run --model gemma
```

Keep the same problems, limits, decoding settings and feedback policy. The requested seed is varied by repetition; a seed request does not guarantee reproducibility across model backends or hardware. No model loading automation is included.

## 5. Results and interpretation

`results/` contains raw generation requests/responses, generated source, submission IDs, final judgement objects and resumable state. The exports are:

| File | Contents |
| --- | --- |
| `attempts.csv` | Verdict, generation duration, API token counts when returned, polling wait and reported verdict runtime per attempt |
| `runs.csv` | Completion status, first-attempt acceptance, final acceptance, attempts used and summed generation duration |
| `summary.json` | Configured/started/completed counts and descriptive acceptance rates by model |

Exports refresh when a run command exits, including ordinary errors and Ctrl+C. Export existing states at any time with `python harness.py export`. Incomplete runs remain explicitly incomplete; they are not reported as completed failures. Format errors and truncated responses consume an attempt without submitting code.

Use first-attempt acceptance and acceptance within three attempts as separate metrics. The latter includes verdict feedback and is **not** an independent-sample pass@3 estimate. Report exact solved counts, problem-level results and failures, not just percentages. Repetitions share the same problems, so do not treat 33 runs as 33 independent problems. Successful-run generation duration can favor models that solve only easier problems: compare shared solved problems too.

Generation duration is measured client-side and includes server overhead. Token counts are whatever LM Studio returns. Polling wait includes queueing and network/poll delays; it is not solution execution time. DOMjudge 9's `max_run_time` is the maximum runtime among runs responsible for the final verdict; the export names this `judge_max_runtime_for_verdict_s`. This team API runner does not collect peak memory or compiler diagnostics: memory cells remain empty, and feedback is verdict-only. No experiment numbers have been generated on your actual installation yet.

The prompt files contain original LaTeX statement text and public samples. Illustrations are omitted. This is a **text-only NCPC evaluation**; review any illustration-dependent problem before deciding which problems to include. Difficulty labels are not supplied. Hidden tests and accepted references never enter model prompts. `reference_solutions/` and the import archives are for judge calibration only. DOMjudge executes generated solutions; the harness does not execute them on the host.

## 6. Resume and troubleshoot

Rerun the identical command to resume. Finished repetitions are skipped, and pending submissions are polled using their existing IDs. Changes to a run's prompt, model configuration, protocol settings or exposed judge metadata require a new `output_directory` to avoid mixing experiments.

If the process loses contact **during submission**, the state may be `SUBMITTING`: the server may have accepted the submission without the client receiving its ID. The harness stops instead of submitting a duplicate. Inspect the DOMjudge jury submission list. If that submission exists, download its source from the jury UI, then attach it:

```text
python harness.py attach-submission --state results/qwen/arithmeticadaptation/repeat-01/state.json --submission-id THE_ID --source-file downloaded-main.cpp
```

This checks team/problem/language metadata and compares the supplied downloaded source with the saved attempt. The standard team API does not permit fetching submission source automatically. Select the correct submission in the UI before attaching, then rerun `run`.

If you have confirmed in DOMjudge that **no submission was created**, back up that `state.json`, change only the latest attempt's `status` from `SUBMITTING` to `GENERATED`, and rerun. Never do this while the original submission could still be processing.

For HTTP errors, check team credentials, contest membership/window and IDs. For a judging timeout, check judgehost activity and the submission's status; rerun to continue polling. CE receives verdict-only feedback. A truncated generation is an experiment failure under the chosen budget; change that budget only for a separately recorded experiment.

## Verification and sources

The included tests use local mock HTTP services to check submission packaging, verdict feedback, resume behavior, pending judgements, uncertain submissions and export counts. They do not prove your Docker instance is configured correctly. Run them with:

```text
python -m unittest discover -s tests -v
```

- [DOMjudge 9 problem format](https://www.domjudge.org/docs/manual/9.0/problem-format.html)
- [DOMjudge 9 setup](https://www.domjudge.org/docs/manual/9.0/config-basic.html)
- [DOMjudge 9.0.0 submission API source](https://github.com/DOMjudge/domjudge/blob/9.0.0/webapp/src/Controller/API/SubmissionController.php)
- [DOMjudge 9.0.0 problem importer](https://github.com/DOMjudge/domjudge/blob/9.0.0/webapp/src/Service/ImportProblemService.php)
- [LM Studio OpenAI-compatible API](https://lmstudio.ai/docs/developer/openai-compat)

`prepare_imports.py` records how these imports were produced from your uploaded archive. It uses only Python's standard library and can regenerate them using `python prepare_imports.py PATH_TO_ORIGINAL_ZIP --output NEW_FOLDER`.
