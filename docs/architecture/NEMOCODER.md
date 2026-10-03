# NemoCoder architecture and operating model

## Placement

NemoCoder is an Exocortex cognitive-fabric component. Nemosyne is its first apprenticeship target.

```text
                         GOMS
              provenance / lineage / evidence
                           |
                           v
Nemosyne Git/PRs -> Corpus Miner -> Admission -> Task Registry
                                      |             |
                                      v             v
                                  Training Set   Secret Eval
                                      |             |
                                      v             |
                               Trainer Backend      |
                                      |             |
                                      v             v
                               Candidate Model -> Evaluator
                                      |             |
                                      +----> Promotion Gate
                                                |
                                     reject <---+---> incumbent
                                                        |
                                                        v
                                                   Ollama/API
                                                        |
                                            Router / Hermes / OpenCode
```

## Controller

The apprenticeship controller is deterministic orchestration around replaceable models. Its state machine is:

`PREFLIGHT -> MINE -> ADMIT -> REBUILD -> BASELINE -> TRAIN -> EVAL -> PROMOTE_OR_REJECT -> DIAGNOSE -> REPEAT`.

Long operations persist checkpoints so an hourly supervisor can resume rather than restart them.

## Runtime state

Local non-Git runtime state belongs under an Exocortex state root, not inside source repositories. Record:
- schema version;
- current programme phase;
- incumbent/candidate model IDs;
- current experiment and task;
- lease owner/heartbeat;
- process PID plus last meaningful artifact timestamp;
- retry/circuit-breaker state;
- model/data/eval hashes;
- last user-report timestamp.

Git stores schemas, code, recipes and compact evidence. Large model artifacts stay outside Git and are referenced by digest.

## Hourly supervisor contract

Each invocation:
1. acquire the singleton NemoCoder lease;
2. refresh Exocortex and read this architecture plus the programme plan;
3. inspect host/resource health and previous durable state;
4. verify target-repository access without mutating its canonical checkout;
5. resume the interrupted safe step, or select exactly one next dependency;
6. perform one bounded tranche or launch/supervise one long-running job;
7. require an artifact/heartbeat, not merely a live PID;
8. verify the tranche;
9. persist state and evidence;
10. update/open a focused PR only when source changes are ready;
11. release the lease.

If no useful work is eligible, record `ABSTAIN_NO_ELIGIBLE_WORK` rather than inventing tasks.

## Long-running job supervision

- One heavy training job at a time on the 16 GB Mac.
- One heavy evaluation job at a time unless measurements later permit more.
- PID existence is insufficient. A job must advance a progress counter, checkpoint or output artifact within its deadline.
- Three repeats of the same normalized failure trip a circuit breaker and force diagnosis or an alternate backend/model.
- Recovery begins from durable stage state.
- Resource monitors may pause/terminate jobs that create unsafe memory pressure, swap growth or thermal load.

## Target repository isolation

For Nemosyne:
- fetch the required immutable commit;
- create a disposable worktree in the NemoCoder sandbox root;
- execute the task there;
- capture diff, tests and metrics;
- destroy the worktree after artifact capture.

Candidate patches produced for evaluation never enter Nemosyne main or an active implementation branch.

Current-project assistance is a later earned permission and still uses normal Nemosyne ownership/PR/review rules.

## Corpus and holdout isolation

The corpus worker can read admitted training sources but cannot read secret expected outputs.

The evaluator can read the secret benchmark but cannot add it to training data.

The trainer receives a materialized training manifest only.

A promotion record binds:
`base model + training manifest hash + trainer config hash + checkpoint hash + eval manifest hash + results`.

## Difficulty and scaffolding

The task registry stores both difficulty and assistance level. A model does not receive extra hints during evaluation merely because it is struggling.

Promotion unlocks harder tasks. Regression relocks levels when replay evidence falls below gates.

## Model backends

### Serving
Primary: Ollama local endpoint.

### Training
Backend interface:
- MLX-LM or other Apple-Silicon-native adapter training where model support/resource measurements are adequate;
- Transformers/TRL/PEFT-compatible path for portable training;
- optional external GPU executor when explicitly authorised.

### Model candidates
GPT-OSS-20B is the first inference baseline. Gemma 4 compact variants are valid fine-tuning candidates. The controller may introduce another open model only after recording why it is likely to improve the current bottleneck.

## Interface

NemoCoder exposes a stable request contract independent of model family:

```json
{
  "taskClass": "repair|test|review|archaeology|ci",
  "repository": "owner/repo",
  "baseRef": "immutable-sha",
  "instruction": "...",
  "constraints": {"allowedPaths": [], "timeBudgetSec": 0},
  "requiredCapabilityLevel": "L0-L11"
}
```

Response contains:
- model/checkpoint ID;
- capability level;
- outcome `COMPLETE|ABSTAIN|BLOCKED`;
- patch/artifact reference;
- verification commands/results;
- escalation reason when applicable.

Hermes/OpenCode integration uses this contract instead of depending on one model's native prompt format.

## Connection tooling

Required connectors:
- Git/GitHub read adapter for mining and immutable reconstruction;
- local Git worktree manager;
- Ollama health/chat/model import adapter;
- trainer backend adapter;
- process/resource monitor;
- Exocortex model-router registration;
- GOMS evidence/lineage writer;
- Hermes/OpenCode request adapter.

Credentials remain in existing Exocortex secret/authority mechanisms and are never copied into model training material.

## Evaluation authority

Executable graders outrank model self-assessment:
- compiler/typecheck;
- project test suites;
- hidden tests/falsifiers;
- diff/path constraints;
- static authority rules;
- secret scan;
- resource/time envelope.

LLM review may annotate ambiguity but cannot convert failed executable evidence into a pass.

## Periodic reporting

The hourly controller records local progress every run but only surfaces a user-facing update on a material transition or approximately six-hour cadence.

The report is deliberately compact:
`phase | incumbent | latest score/result | artifact | next action | blocker`.

## Bootstrap scheduler

The ChatGPT hourly task is the bootstrap supervisor. Exocortex also stores a reconstructible scheduled-intent definition.

Once the Exocortex-native scheduler/controller is verified to execute the same singleton lease, exactly one scheduler becomes the active trigger. Do not allow two independent hourly workers to mutate the same NemoCoder state.
