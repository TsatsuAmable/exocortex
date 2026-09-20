# Data and Control Flows

## Human intent

```text
human message
  -> GSV Aineko reconstructs context
  -> GOMS/context + live capability inspection
  -> choose cognitive route if needed
  -> choose authorised execution route
  -> act/delegate
  -> supervise/recover
  -> verify observed result
  -> persist durable result
  -> compact human report
```

The human is not used as a message bus between components.

## Mechanical host task

```text
intent
  -> capability graph
  -> authority check
  -> preferred route selector
  -> Remote Commander / local machine route
  -> verification
  -> audit + GOMS checkpoint
```

If the first route fails, the selector attempts another healthy authorised route before escalation.

## Cognitive delegation

```text
task
  -> mcp__goms__model_route
  -> hard eligibility filters
  -> lifecycle + qualification
  -> evidence/cost/latency ranking
  -> provider/model
  -> worker execution
  -> verifier
  -> routing evidence back to durable state
```

Model choice does not change authority.

## GOMS distillation
