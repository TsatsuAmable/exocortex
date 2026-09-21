# Durable Agentic Delivery Controller — Work Reference Architecture

## Problem

Coding assistants reduce implementation time but often leave a human supervising the long tail: CI, review comments, retries, merge policy, staging, release approval, production verification and rollback. The design target is that supervision scarcity, not “more generated code.”

## Principle

Separate **cognition** from **transaction authority**.

- A durable controller owns job state, idempotency, budgets, audit events and policy gates.
- GitHub/CI/CD remain authoritative for source, checks, reviews and deployments.
- An LLM or agent framework supplies bounded reasoning at specific transitions.
- Waiting is event/poll driven and consumes no inference.
- Production authority is granted by policy and evidence, never by model confidence.

## Reference flow

```text
objective / ticket / issue
        |
        v
 durable job controller
        |
        +--> planner / implementation cognition
        |
        +--> isolated workspace + deterministic tests
        |
        +--> pull request
                  |
                  v
             CI / review
                  |
          event or polling wake-up
                  |
          diagnose / remediate loop
                  |
                  v
              merge gate
                  |
                  v
               staging
                  |
           verification gate
                  |
                  v
             production
                  |
           verify / rollback
```

## Model boundary

The controller should depend on a narrow provider contract, not a particular LLM. Google ADK can host the cognitive agents while the actual models are Gemini, Claude, a LiteLLM-backed provider, Ollama/local models, or another supported runtime. The orchestration state machine should remain portable even if the agent framework itself is later replaced.

## Minimal data contract

Each job records:

- immutable objective and acceptance criteria;
- repository/base revision;
- current state and allowed authority level;
- branch/PR/deployment identifiers;
- external observations (checks, reviews, deployment health);
- reasoning/tool invocation provenance;
- retry/compute/cost budgets;
- approval decisions;
- terminal outcome and rollback information.

## Recommended autonomy ladder

| Level | Authority |
|---|---|
| 0 | Observe and recommend |
| 1 | Create branch and PR |
| 2 | Repair PR until deterministic checks pass |
| 3 | Merge policy-approved low-risk work |
| 4 | Deploy and verify staging |
| 5 | Request production promotion |
| 6 | Auto-promote evidence-qualified low-risk classes |
| 7 | Auto-rollback on deterministic production failure |

Start at Level 0–2. Increase authority by change class only after telemetry establishes an acceptable intervention, escaped-defect and rollback rate.

## Event-driven delivery supervision

GitHub webhooks are the primary trigger for PR supervision. Authenticated, deduplicated events wake the durable controller immediately. Periodic polling remains only a low-frequency reconciliation/watchdog path for missed events and recovery, never the primary control loop.

## Security boundary

Do not expose unrestricted shell/root/cloud credentials to the reasoning model. Give it typed tools such as `run_test(profile)`, `create_pr()`, `get_checks()`, `request_deployment()` and `rollback(deployment_id)`. The controller validates every requested transition against policy before executing it.

## Evaluation

Measure whether the system actually increases delivery capacity:

- human interventions per completed change;
- elapsed time from patch to terminal outcome;
- CI repair iterations;
- first-pass success rate;
- escaped defects and rollbacks;
- cost per completed change;
- percentage of waiting time requiring no human attention;
- model/provider sensitivity for the same task class.

The project succeeds only if those measurements improve. Otherwise it is orchestration theatre.
