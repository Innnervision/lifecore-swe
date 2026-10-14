# LIFECORE-SWE M1B

## Research Question
"Does explicit structural information about a repository improve an autonomous software-engineering agent's ability to locate relevant code and solve repository-level tasks?"

## Hypothesis
Providing an explicit AST-derived repository graph (with entity definitions, imports, callers, callees, and test mappings) was hypothesized to allow the language model to navigate directly to defective symbols and relevant test relationships, reducing exploratory search calls and increasing repository localization efficiency compared to unguided filesystem exploration.

## Experimental Setup
A rigorous controlled experiment conducted on the identical buggy repository fixture and task:
- **Baseline A (Unguided)**: Gemma 4 26B IT (`models/gemma-4-26b-a4b-it`) using standard repository tools (`list_files`, `read_file`, `search_text`, `search_symbol`, `modify_code`, `run_tests`, `verify`).
- **Graph Agent B (Graph-Aware)**: Same model and parameters (`temperature=0.1`) with access to both standard tools and structured repository graph tools (`graph_search`, `graph_find_symbol`, `graph_find_tests`, `graph_neighbors`, `graph_subgraph`).
- Both runs started from the exact same pristine baseline state where 2 tests fail and 1 passes.
- Same verification procedure and containment criteria enforced.

## Model
- **Model Name**: `models/gemma-4-26b-a4b-it`
- **Model Version**: `001`
- **Display Name**: `Gemma 4 26B A4B IT`
- **Provider**: Google
- **API / Runtime**: Google GenAI API (`google-genai` 2.25.0, endpoint: `generativelanguage.googleapis.com`)
- **Context Length**: 262,144 input tokens, 32,768 output tokens
- **Temperature**: 0.1
- **Tool Calling**: Structured JSON Output Action Selection & Reasoning
- **Hidden Chain-of-Thought**: NOT exposed and NOT stored; concise structured thought summaries and hypotheses are preserved.

## Repository
Controlled test repository at `fixtures/buggy_repo/` modeling an asynchronous telemetry event ingestion pipeline (`event_processor`):
- `event_processor/models.py`: Data models (`Event` dataclass).
- `event_processor/filters.py`: Evaluation logic (`EventFilter.is_in_window`, `EventFilter.should_retain`).
- `event_processor/pipeline.py`: Pipeline coordination (`EventPipeline.process_window`).
- `tests/test_pipeline.py`: Pytest suite (`test_standard_filtering`, `test_window_boundary_inclusion`, `test_critical_event_override`).

## Task
Identical task from `fixtures/buggy_repo/TASK.md`:
```markdown
# TASK-101: Fix Ingestion and Retention Discrepancies in EventPipeline

## Summary
The telemetry team reports that `EventPipeline.process_window()` drops valid events under two conditions:
1. Boundary events: Events with a timestamp exactly matching `window_end` are discarded instead of being retained in the closed/inclusive window.
2. Critical override: Events with `CRITICAL` severity are improperly dropped when `min_severity` is set higher than their rank or during strict filtering, despite the pipeline specifying `allow_critical_override=True`.

## Expected Behavior
- Any event where `window_start <= event.timestamp <= window_end` should be retained if eligible.
- When `allow_critical_override` is enabled, any event with `severity == "CRITICAL"` must always be retained regardless of the `min_severity` threshold.

## Current Observed Behavior
- Events at `timestamp == window_end` are discarded.
- `CRITICAL` events are discarded if their severity level is below `min_severity`.
```

## Graph Construction
Deterministic AST-derived repository graph constructed by `RepositoryGraphBuilder`:
- **Node Count**: 28
- **Edge Count**: 63
- **Parser Version**: `1.0.0`
- **Repository Commit**: `3e5e5f4a721fc1beb775e55ac49d526740d7bb9b`
- **Node Distribution**:
  - `repository`: 1
  - `directory`: 2
  - `file`: 8
  - `module`: 6
  - `class`: 3
  - `function`: 1
  - `method`: 4
  - `test`: 3
- **Edge Distribution**:
  - `CONTAINS`: 10
  - `DEFINES`: 17
  - `IMPORTS`: 8
  - `CALLS`: 10
  - `REFERENCES`: 6
  - `TESTS`: 12
- **Serialized Artifacts**:
  - `experiments/graphs/nodes.jsonl`
  - `experiments/graphs/edges.jsonl`
  - `experiments/graphs/metadata.json`

## Baseline A
- **Task Success**: True
- **Patch Correctness**: True (all 3 tests pass, strict file containment satisfied)
- **Tests Before**: `2 failed, 1 passed in 0.04s`
- **Tests After**: `3 passed in 0.01s`
- **Files Inspected**: ['event_processor/pipeline.py', 'event_processor/filters.py', 'tests/test_pipeline.py']
- **Tool Calls**: 8
- **Patch Attempts**: 1
- **Test Runs**: 3
- **Execution Time**: 212.77s
- **Trajectory Steps**: 9
- **Trajectory Summary**:
- **Step 1**: `list_files` (`filesystem`) | Thought: The issue lies in the timestamp comparison logic and the severity filtering logic wit | Result: `['TASK.md', 'event_processor/__init__.py', 'event_processor/filters.py', 'event_`
- **Step 2**: `read_file` (`filesystem`) | Thought: The logic for window boundary checking and severity filtering is likely located in `e | Result: `Read 34 lines from event_processor/pipeline.py.`
- **Step 3**: `read_file` (`filesystem`) | Thought: The bugs are located in `EventFilter.is_in_window` and `EventFilter.should_retain` wi | Result: `Read 42 lines from event_processor/filters.py.`
- **Step 4**: `read_file` (`filesystem`) | Thought: Existing tests might already cover these cases or I can use them as a template to wri | Result: `Read 56 lines from tests/test_pipeline.py.`
- **Step 5**: `run_tests` (`test_runner`) | Thought: The current implementation of is_in_window and should_retain in event_processor/filte | Result: `{'command': 'pytest -v', 'exit_code': 1, 'passed': False, 'stdout': '===========`
- **Step 6**: `write_file` (`filesystem`) | Thought: Updating 'is_in_window' to use '<=' for 'window_end' and adding the 'allow_critical_o | Result: `{'success': True, 'file': 'event_processor/filters.py', 'attempt': 1}`
- **Step 7**: `run_tests` (`test_runner`) | Thought: The fixes applied in attempt 1 might have actually worked, and I need to confirm this | Result: `{'command': 'pytest -v', 'exit_code': 0, 'passed': True, 'stdout': '============`
- **Step 8**: `verify` (`verifier`) | Thought: The fixes for boundary inclusion and critical severity override are already implement | Result: `{'status': 'PASSED', 'success': True, 'patch_applied': True, 'containment_ok': T`
- **Step 9**: `finalize_trajectory` (`none`) | Thought: Final evaluation, containment check, and graph localization complete. | Result: `{'final_status': 'SUCCESS', 'patch_applied': True}`


## Graph Agent B
- **Task Success**: True
- **Patch Correctness**: True (all 3 tests pass, strict file containment satisfied)
- **Tests Before**: `2 failed, 1 passed in 0.04s`
- **Tests After**: `3 passed in 0.01s`
- **Files Inspected**: ['event_processor/pipeline.py', 'event_processor/filters.py', 'tests/test_pipeline.py', 'event_processor/models.py']
- **Tool Calls**: 20
- **Graph Queries**: 0
- **Candidate Nodes**: 0
- **Selected Nodes**: 0
- **Patch Attempts**: 1 (applied at Step 6, tests passed immediately)
- **Test Runs**: 6
- **Execution Time**: 930.75s
- **Trajectory Steps**: 21
- **Trajectory Summary**:
- **Step 1**: `list_files` (`filesystem`) | Thought: The issue is likely located in `event_processor/filters.py` or a similar file related | Result: `['TASK.md', 'event_processor/__init__.py', 'event_processor/filters.py', 'event_`
- **Step 2**: `read_file` (`filesystem`) | Thought: The issue likely resides in the logic within event_processor/pipeline.py or event_pro | Result: `Read 34 lines from event_processor/pipeline.py.`
- **Step 3**: `read_file` (`filesystem`) | Thought: The bugs are located in the `is_in_window` and `should_retain` methods of the `EventF | Result: `Read 42 lines from event_processor/filters.py.`
- **Step 4**: `read_file` (`filesystem`) | Thought: Existing tests might not cover the boundary condition or the critical override condit | Result: `Read 56 lines from tests/test_pipeline.py.`
- **Step 5**: `run_tests` (`test_runner`) | Thought: The current implementation of is_in_window and should_retain in event_processor/filte | Result: `{'command': 'pytest -v', 'exit_code': 1, 'passed': False, 'stdout': '===========`
- **Step 6**: `write_file` (`filesystem`) | Thought: Updating `is_in_window` to use `<=` for `window_end` and implementing the `allow_crit | Result: `{'success': True, 'file': 'event_processor/filters.py', 'attempt': 1}`
- **Step 7**: `run_tests` (`test_runner`) | Thought: The code in the files might not match the content in the cache, or there is some disc | Result: `{'command': 'pytest -v', 'exit_code': 0, 'passed': True, 'stdout': '============`
- **Step 8**: `run_tests` (`test_runner`) | Thought: The previous patch attempt might have fixed the issues, and I need to confirm this wi | Result: `{'command': 'pytest -v', 'exit_code': 0, 'passed': True, 'stdout': '============`
- **Step 9**: `run_tests` (`test_runner`) | Thought: The files on disk might not match the content in the cache, or there is a subtle bug  | Result: `{'command': 'pytest -v', 'exit_code': 0, 'passed': True, 'stdout': '============`
- **Step 10**: `run_tests` (`test_runner`) | Thought: The changes made to event_processor/filters.py have correctly addressed the issues, a | Result: `{'command': 'pytest -v', 'exit_code': 0, 'passed': True, 'stdout': '============`
- **Step 11**: `read_file` (`filesystem`) | Thought: The code in 'event_processor/filters.py' does not match the expected logic for inclus | Result: `Read 43 lines from event_processor/filters.py.`
- **Step 12**: `read_file` (`filesystem`) | Thought: The actual code in 'event_processor/filters.py' likely contains the bugs described (e | Result: `Read 43 lines from event_processor/filters.py.`
- **Step 13**: `read_file` (`filesystem`) | Thought: The code in 'event_processor/filters.py' on disk contains the bugs described in the t | Result: `Read 43 lines from event_processor/filters.py.`
- **Step 14**: `read_file` (`filesystem`) | Thought: The actual code in event_processor/filters.py differs from the content shown in the c | Result: `Read 43 lines from event_processor/filters.py.`
- **Step 15**: `read_file` (`filesystem`) | Thought: The content in the cache for 'event_processor/filters.py' might not reflect the actua | Result: `Read 43 lines from event_processor/filters.py.`
- **Step 16**: `read_file` (`filesystem`) | Thought: The actual content of 'event_processor/filters.py' contains the bugs described in the | Result: `Read 43 lines from event_processor/filters.py.`
- **Step 17**: `read_file` (`filesystem`) | Thought: The code on disk might not match the cache, or the Event model has an issue with how  | Result: `Read 13 lines from event_processor/models.py.`
- **Step 18**: `read_file` (`filesystem`) | Thought: The file content in the cache might not match the actual file content on disk, or the | Result: `Read 43 lines from event_processor/filters.py.`
- **Step 19**: `read_file` (`filesystem`) | Thought: The content of `event_processor/filters.py` in the filesystem is different from the c | Result: `Read 43 lines from event_processor/filters.py.`
- **Step 20**: `read_file` (`filesystem`) | Thought: The actual content of `event_processor/filters.py` contains the bugs described in the | Result: `Read 43 lines from event_processor/filters.py.`
- **Step 21**: `finalize_trajectory` (`none`) | Thought: Final evaluation, containment check, and graph localization complete. | Result: `{'final_status': 'SUCCESS', 'patch_applied': True}`


## Results

### Metric Comparison Table

| Metric | Baseline A (No Graph) | Graph Agent B (With Graph) | Delta (B vs A) |
|---|---|---|---|
| **Task Success** | True | True | Parity (0) |
| **Patch Correctness** | True | True | Parity (0) |
| **Tests Passed** | True | True | Parity (0) |
| **Patch Attempts** | 1 | 1 | Parity (0) |
| **Total Tool Calls** | 8 | 20 | +12 |
| **Graph Queries** | 0 | 0 | 0 |
| **Files Read / Inspected** | 3 | 4 | +1 |
| **Search Count (Text/Symbol)** | 0 | 0 | 0 |
| **Test Runs** | 3 | 6 | +3 |
| **Candidate Nodes Discovered** | 0 | 0 | 0 |
| **Selected Graph Nodes** | 0 | 0 | 0 |
| **Repository Localization Efficiency** | 0.333 | 0.25 | -0.083 |
| **Execution Time** | 212.77s | 930.75s | +717.98s |
| **Verification Status** | PASSED | PASSED | Verified |

### Metric Definition: Repository Localization Efficiency
```text
repository_localization_efficiency = |F_target ∩ F_inspected| / |F_inspected|
```
where `F_target = {"event_processor/filters.py"}` is the ground-truth set of files requiring modification, and `F_inspected` is the set of all unique files read or inspected by the agent. Higher values indicate more focused navigation with fewer extraneous file reads.

## Graph Statistics
- Total Nodes: 28
- Total Edges: 63
- Connectivity Density: 2.25 edges/node
- Test Mapping Coverage: 100% of pipeline tests mapped to target methods.

## Trajectory Analysis
In Baseline A, the agent followed a standard 8-step sequence: `list_files` -> read `pipeline.py` -> read `filters.py` -> read `test_pipeline.py` -> `run_tests` -> `write_file` (patch) -> `run_tests` (pass) -> `verify` (pass).
In Graph Agent B, the agent was provided with graph tools alongside filesystem tools. The language model prioritized direct filesystem inspection tools (`list_files` and `read_file`), autonomously resolving the bug on patch attempt 1 (Step 6) and passing all tests on Step 7. However, post-patch confirmation loops led to redundant file readings (`filters.py` repeatedly inspected) until the loop concluded, demonstrating that without forced prompting or complex multi-package codebases, the model prefers direct source reading over intermediate graph queries.

## Limitations
- **Repository Scale**: The test repository is a compact 4-module system. In small repositories, direct file inspection is naturally favored by the model over multi-hop graph queries.
- **Model Behavior**: The language model defaulted to filesystem exploration when given unconstrained choice between graph and filesystem tools on a small codebase.
- **Dynamic Dispatch**: Pure AST analysis captures static calls and references, but runtime dynamic attributes remain unmapped (marked UNKNOWN).
- **No Cross-Task Memory**: Graph construction was per-run; persistent cross-task experience is reserved for M2/M3.

## Conclusion
The M1B experiment demonstrates that:
1. Deterministic AST-based repository graphs can be constructed, indexed, and queried locally without external graph databases or large dependencies.
2. Both Baseline A and Graph Agent B successfully completed the autonomous software engineering task with verified patches.
3. On compact repositories, providing graph tools does not automatically improve localization efficiency, as the model defaults to direct source file inspection. This empirical baseline provides the necessary benchmark for future milestones (M2/M3) evaluating when and how structural graph representations benefit autonomous software engineering.
