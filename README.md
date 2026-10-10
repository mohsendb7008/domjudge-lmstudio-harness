# DOMjudge open contest harness

This bundle contains 11 individual NCPC 2025 problem imports, public problem prompts, reference solutions, and a Python harness. It connects LM Studio, OpenAI, or Claude to your DOMjudge server and saves resumable contest results. Python 3.10 or newer is sufficient; no pip packages are required.

## 1. Fix the upload error

The original problemset archive exceeds Git's 25M `post_max_size`. Extract **instagraph.7z** in imports folder. In the DOMjudge jury interface, import **one ZIP from `imports/` at a time**, starting with `arithmeticadaptation.zip`. The largest individual import is approximately 35 MB, comfortably below the DOMServer limit. The packages have their problem files at the ZIP root.

Create a contest, add the problems, enable submissions and judging, and set a contest window that covers the experiment. Create a team and linked **team user** named `llm-qwen`, and assign the team to the contest. Create a separate team/user for each additional model, such as `llm-gemma`, `llm-openai`, or `llm-claude`. The judgehost account is for the daemon; use team accounts for the harness. Confirm that your judgehost is active.

The supplied source archive has no official numeric per-problem time limit. DOMjudge 9's importer defaults a missing time limit to 10 seconds; that is an importer default, not an NCPC contest setting. Review time, memory, output and language limits. Calibrate them using the supplied reference solutions before collecting results, and freeze them across models. Inspect each reference verdict; an internal error or a rejected reference solution means the contest is not ready. Calibration submissions are separate from the harness's LLM results.

## 2. Install and load a model

Start with **Qwen2.5-Coder-7B-Instruct, GGUF Q4_K_M**, subject to available memory. For a second family, try **Gemma 3 4B IT, GGUF Q4_K_M**. They differ in size: this initial comparison is of practical local configurations, rather than equal-sized architectures. Start LM Studio's local server on port **1234**. The supplied config uses manual loading: keep Qwen and Gemma loaded before running both. Its model `context_length` values are 32768, but with `auto_load_models: false` you must configure the actual context size in LM Studio. If you switch to automatic loading, the runner passes that value to the native loader. Adjust `context_length` and `max_tokens` to your model and available memory. Download each local model before the batch; automatic loading does not download models.

## 3. Configure and check the connection

Open a terminal **inside the `domjudge-lmstudio-harness` folder**. The commands below work with `python`; use `python3` on systems where that is the installed command.

```text
python harness.py doctor --model qwen
```

Enter the `llm-qwen` team's password privately when asked. Alternatively, set the model's `password_env` (for example, `DOMJUDGE_PASSWORD_QWEN`) in that terminal; credentials are not saved in result files. `DOMJUDGE_USER` overrides the configured username, so leave it unset when switching between configured team users.

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

## 4. Run an unattended contest

After checking imports and references, configure each model you want to run: set `enabled` to `true`, its exact `identifier`, and its DOMjudge team. The supplied config enables Qwen (`qwen2.5-coder-7b-instruct`) and Gemma (`gemma-3-4b-it`); the cloud examples remain disabled. Set all enabled teams' password environment variables before starting so the batch needs no later prompts. For a single-model pilot, `--model LABEL` explicitly selects that model even if disabled.

```text
python harness.py run
```

The supplied config runs Qwen and Gemma concurrently, with **three rounds and up to three attempts per problem per round**. Each model chooses a problem and completes round 1, then round 2, then round 3 before choosing another problem. Acceptance immediately skips all remaining attempts and rounds for that model/problem. A problem solved by one model remains available to other models. Completion means every problem is accepted or has exhausted all configured rounds; acceptance of every problem is not guaranteed. `repetitions` supports 1-100 rounds, and `attempts` supports 1-10 attempts per round.

Each problem/round starts a fresh conversation. Failed attempts within that conversation receive the statement, latest response, and latest DOMjudge verdict. The full conversation audit remains on disk, while inference sends only the latest repair exchange to avoid accumulating ten large solutions in the context window. The requested local seed varies by round; seeds do not guarantee reproducibility across backends or hardware. Generation, submission, and verdict feedback stay sequential within each model; different model workers overlap. Runtime depends on model speed, response budgets, retries, and the judge queue; no fixed few-hour completion time is guaranteed.

`parallel_models` limits concurrent model workers; `lmstudio_parallel_models` limits simultaneous local model sessions per LM Studio server. Both are `2` in the supplied config. Cloud workers can overlap local work. Set either limit to `1` to reduce memory pressure; models sharing the exact same local instance are serialized even if the limit is higher. You can override the overall limit with `python harness.py run --parallel-models 1`. Credentials are collected and judge IDs validated in the main thread before workers start. A provider/judging failure stops that model, lets other models finish, exports all saved results, and exits with an error; rerunning resumes the failed model's existing problem/round.

For two local models on one server, load both with enough RAM/VRAM for their actual context sizes. If using JIT loading, turn off **Only Keep Last JIT Loaded Model / Auto-Evict**, which otherwise retains only one JIT-loaded model. LM Studio may still queue requests or share GPU resources, so overlapping requests do not guarantee a speedup. See [LM Studio Auto-Evict documentation](https://lmstudio.ai/docs/developer/core/ttl-and-auto-evict).

Ctrl+C asks workers to stop at safe boundaries. An in-flight HTTP request can take up to its configured timeout to return; submission IDs and source are saved before workers exit, and exports are written only after all workers have stopped. Pending or uncertain submissions keep the same recovery rules below.

Choose the selection policy in `config.json`:

| `problem_selection` | Behavior |
| --- | --- |
| `model` | The active model reads the remaining public statements and chooses the easiest problem for itself. This adds one inference request per chosen problem, outside the solution-attempt budget. |
| `easiest` (supplied config) | Choose the lowest numeric per-problem `difficulty`, without a selector inference. Unknown difficulty sorts last; ties use configuration order. |
| `configured` | Choose the first remaining problem in configuration order. |

The supplied numeric difficulty order is your chosen heuristic, not an official ranking. Missing difficulty defaults to `null`. An invalid or truncated model selection falls back to configured difficulty/order. Selection requests receive only slugs, names, difficulty, and public statement text. Hints, reference code, hidden tests, and judge import metadata are excluded. Ensure the selector's context fits all statements; use `easiest` or `configured` to avoid that context cost. Increase `selection_max_tokens` for models that spend output tokens on reasoning.

### Hints from round two onward

The starter config now includes a one-paragraph algorithm hint for each of the 11 NCPC 2025 problems under `hidden_hints`. Read [NCPC_2025_HINTS.md](NCPC_2025_HINTS.md) for the approaches, pitfalls, and C++17 language advice. These are strong outlines checked against the supplied public statements and reference approaches. Use a new `output_directory` to enable or change them after a contest has started; clearing the mapping and per-problem hints disables hint assistance.

Customize a problem's `hidden_hint` in `config.json`, or edit the top-level mapping:

```json
"hidden_hints": {
  "bohemianbookshelf": "Your private algorithmic hint for this problem."
}
```

A nonempty per-problem hint takes precedence over the mapping. The hint is appended to the solving prompt **in round 2 and every later round**. It never enters round-1 solving prompts or any problem-selection prompt. Empty hints are allowed. Each hinted round starts fresh with the statement and hint, without previous-round conversation history. The supplied hints describe public algorithmic approaches, not hidden judge tests. Hinted-round request/state files contain the hint once it has been used; “hidden” refers to withholding it from earlier model prompts, not encryption of configuration or result files.

### Providers and API keys

| `provider` | Model identifier | Key environment variable |
| --- | --- | --- |
| `lmstudio` | Exact downloaded LM Studio model ID | `LMSTUDIO_API_KEY` if server authentication is enabled |
| `openai` | Exact OpenAI API model ID | `OPENAI_API_KEY` |
| `anthropic` | Exact Claude API model ID | `ANTHROPIC_API_KEY` |

The sample config includes disabled `openai` and `claude` entries. Replace their identifier placeholders, create their DOMjudge teams, supply the API keys and team passwords, and enable them. Use provider API keys for these calls. `api_key_env` and `api_base` allow a model-specific key environment variable and endpoint. Keys travel in HTTP headers and are not written to request, response, or state files. Never place literal API keys in configuration. Cloud inference and selection requests use your provider account's API quota.

LM Studio uses its OpenAI-compatible Chat Completions endpoint, OpenAI uses Chat Completions with `max_completion_tokens`, and Claude uses its native Messages endpoint. Global `temperature`, `top_p`, and `seed` apply to LM Studio. Cloud defaults omit these parameters because support depends on the chosen model. Optional per-model cloud settings include `temperature`/`top_p` where supported; OpenAI supports `reasoning_effort`, and Claude supports `thinking`/`output_config`. Record and verify settings for your selected model; reasoning may consume the output budget. For Claude with an explicit thinking budget, selector output budgets are raised when needed to leave room beyond the thinking tokens. Cloud keys are checked before the batch; model availability is validated by the provider on inference.

`auto_load_models: true` loads each active local model through LM Studio's native `/api/v1/models/load`, uses its returned instance ID for inference, and unloads it after that model's entire problem sequence, including ordinary failure/interrupt cleanup. This requires an LM Studio server supporting the native v1 management API. Configure `lmstudio_management_api` separately if the server is remote. Start with other manually loaded models unloaded so they do not consume the batch's memory budget. For older servers or manual loading, set `auto_load_models` to `false`; each requested model must then be available through `/v1/models`.

Transient inference errors (rate limiting, temporary server errors, and connection failures) use bounded retries with exponential backoff. `generation_retries` defaults to 3. Retry calls do not consume extra solution attempts, though a provider might charge a generation whose response was lost. DOMjudge submissions are never blindly retried after an ambiguous outcome.

You can narrow or stage the same contest:

```text
python harness.py run --model qwen --problem arithmeticadaptation --repeat 1
python harness.py run --model qwen
python harness.py run --model claude --repeat 1
```

`--repeat N` runs only that round and requires all earlier rounds of the selected unsolved problems to be finished. Omit `--repeat` to complete all rounds of one problem before moving on. Settings, hints, prompts, and judge metadata are frozen once a contest starts; use a new output directory to change them. The two worker-limit settings can be adjusted on resume and are recorded in `contest.json` under `executions`. Older `contest.json` files used round-first scheduling and require a fresh `output_directory`; the runner does not mix those results with this schedule. The supplied directory is `results-contest2`; if it already contains a legacy contest, use a new name such as `results-contest3`.

## 5. Results and interpretation

`results-contest2/` (or your configured output directory) contains raw generation requests/responses, generated source, submission IDs, final judgement objects and resumable state. The exports are:

| File | Contents |
| --- | --- |
| `attempts.csv` | Verdict, generation duration, API token counts when returned, polling wait and reported verdict runtime per attempt |
| `runs.csv` | Completion status, first-attempt acceptance, final acceptance, attempts used and summed generation duration |
| `summary.json` | Maximum possible/started/completed run counts and descriptive run-level acceptance rates by model |
| `scoreboard.json` | Unique solved problems per model, solves without hints, remaining/exhausted problems, and contest completion |
| `contest.json` | Persisted problem/round order, model completion/errors, configuration fingerprints, and worker limits for each execution |

Exports refresh when a run command exits, including ordinary errors and Ctrl+C. Export existing states at any time with `python harness.py export`. Incomplete runs remain explicitly incomplete; they are not reported as completed failures. Format errors and truncated responses consume an attempt without submitting code.

Use `scoreboard.json` for contest-level solved counts. `configured_runs` is an upper bound: accepted problems skip later rounds, so a finished contest can have fewer completed runs. Run-level rates are descriptive and depend on which unsolved problems reach round 2; compare unique solved problems and unassisted solves across models. First-attempt acceptance, acceptance within the configured attempt budget, and hinted-round acceptance are different metrics. Verdict feedback makes these attempts dependent; this is not an independent-sample pass@10 estimate. Successful-run generation duration can favor models that solve only easier problems: compare shared solved problems too.

Generation duration is measured client-side and includes server overhead. Token counts are whatever the provider returns; Claude input/output counts are normalized for CSV exports. Selector calls are stored under each model's `selections` folder and excluded from solution-attempt counts and generation-duration aggregates. Polling wait includes queueing and network/poll delays; it is not solution execution time. DOMjudge 9's `max_run_time` is the maximum runtime among runs responsible for the final verdict; the export names this `judge_max_runtime_for_verdict_s`. This team API runner does not collect peak memory or compiler diagnostics: memory cells remain empty, and feedback is verdict-only. No experiment numbers have been generated on your actual installation yet.

The prompt files contain original LaTeX statement text and public samples. Illustrations are omitted. This is a **text-only NCPC evaluation**; review any illustration-dependent problem before deciding which problems to include. Difficulty numbers in config are your heuristic ordering. Hidden tests and accepted references never enter model prompts. Algorithm hints enter solving prompts only from round 2 onward. `reference_solutions/` and the import archives are for judge calibration only. DOMjudge executes generated solutions; the harness does not execute them on the host.

## 6. Resume and troubleshoot

Test the model separately from DOMjudge and the contest prompts:

```text
python harness.py probe-model --model gemma
```

Use your configured model label. This makes one short inference request with the configured loading mode and API credentials; it does not ask for a DOMjudge password, submit code, or change saved contest state. Cloud probes use the API and incur normal usage charges. A successful probe confirms a small request works; it does not guarantee enough context or memory for contest prompts.

Inference HTTP errors now include the provider's structured error message/code, with configured credentials redacted and output bounded. Raw error bodies and DOMjudge error details are not printed. For LM Studio's generic **Channel Error**, inspect the LM Studio server log (or `lms log stream`) for the underlying model/runtime error. Record the LM Studio version and exact model ID. If the short probe also fails, first check the same model in LM Studio's own chat, its runtime, and its prompt template.

If a probe succeeds but the run stops during **problem selection**, the selector request contains every remaining public statement. A context or memory error may require a larger loaded context or a smaller request. To test the smaller request, set `problem_selection` to `easiest`, reduce `max_tokens` to `4096` (including a per-model override if present), and choose a fresh `output_directory`, such as `results-gemma-pilot`. Then run a single problem:

```text
python harness.py run --model gemma --problem arithmeticadaptation --repeat 1
```

With manual loading (`auto_load_models: false`), configure the actual context size in LM Studio; the harness's model `context_length` applies only to automatic loading. `easiest` uses configured numeric difficulty and falls back to config order when difficulty is unknown. This bypasses model-based selection. It is a diagnostic experiment, not a guaranteed fix for a runtime or template failure.

For cloud HTTP 429 errors, distinguish rate limits from quota/credit/spend-limit errors in the displayed provider message. Known quota and billing error codes stop immediately; transient errors still retry inference only. Never put a key in `api_key_env`: that field is an environment variable name such as `OPENAI_API_KEY`.

Rerun the identical command to resume. Finished runs and accepted problems are skipped, and pending submissions are polled using their existing IDs. Changes to a run's prompt, model configuration, protocol settings or exposed judge metadata require a new `output_directory` to avoid mixing experiments.

If the process loses contact **during submission**, the state may be `SUBMITTING`: the server may have accepted the submission without the client receiving its ID. The harness stops instead of submitting a duplicate. Inspect the DOMjudge jury submission list. If that submission exists, download its source from the jury UI, then attach it:

```text
python harness.py attach-submission --state results-contest/qwen/arithmeticadaptation/repeat-01/state.json --submission-id THE_ID --source-file downloaded-main.cpp
```

This checks team/problem/language metadata and compares the supplied downloaded source with the saved attempt. The standard team API does not permit fetching submission source automatically. Select the correct submission in the UI before attaching, then rerun `run`. Use the configured output directory in the state path (the supplied config uses `results-contest2`).

If you have confirmed in DOMjudge that **no submission was created**, back up that `state.json`, change only the latest attempt's `status` from `SUBMITTING` to `GENERATED`, and rerun. Never do this while the original submission could still be processing.

For HTTP errors, check team credentials, contest membership/window and IDs. For a judging timeout, check judgehost activity and the submission's status; rerun to continue polling. CE receives verdict-only feedback. A truncated generation is an experiment failure under the chosen budget; change that budget only for a separately recorded experiment.

## Verification and sources

The included tests use local mock HTTP services to check contest ordering, per-model solved tracking, hint isolation, attempt limits, provider request formats/authentication, model loading, inference retries, submission packaging, verdict feedback, resume behavior, pending judgements, uncertain submissions and exports. They do not prove your Docker instance is configured correctly. Run them with:

```text
python -m unittest discover -s tests -v
```

- [DOMjudge 9 problem format](https://www.domjudge.org/docs/manual/9.0/problem-format.html)
- [DOMjudge 9 setup](https://www.domjudge.org/docs/manual/9.0/config-basic.html)
- [DOMjudge 9.0.0 submission API source](https://github.com/DOMjudge/domjudge/blob/9.0.0/webapp/src/Controller/API/SubmissionController.php)
- [DOMjudge 9.0.0 problem importer](https://github.com/DOMjudge/domjudge/blob/9.0.0/webapp/src/Service/ImportProblemService.php)
- [LM Studio OpenAI-compatible API](https://lmstudio.ai/docs/developer/openai-compat)
- [LM Studio model loading](https://lmstudio.ai/docs/developer/rest/load)
- [LM Studio model unloading](https://lmstudio.ai/docs/developer/rest/unload)
- [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
- [Claude Messages API](https://platform.claude.com/docs/en/api/messages/create)

`prepare_imports.py` records how these imports were produced from your uploaded archive. It uses only Python's standard library and can regenerate them using `python prepare_imports.py PATH_TO_ORIGINAL_ZIP --output NEW_FOLDER`.

