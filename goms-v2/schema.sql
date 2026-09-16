PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS entities (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  project TEXT,
  status TEXT,
  confidence REAL,
  source TEXT,
  source_hash TEXT,
  tags TEXT NOT NULL DEFAULT '[]',
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relations (
  src TEXT NOT NULL REFERENCES entities(id),
  rel TEXT NOT NULL,
  dst TEXT NOT NULL REFERENCES entities(id),
  evidence TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (src, rel, dst)
);
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
  id UNINDEXED, type, title, summary, project, tags,
  content='entities', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS entities_ai AFTER INSERT ON entities BEGIN
  INSERT INTO entities_fts(rowid,id,type,title,summary,project,tags)
  VALUES(new.rowid,new.id,new.type,new.title,new.summary,new.project,new.tags);
END;
CREATE TRIGGER IF NOT EXISTS entities_ad AFTER DELETE ON entities BEGIN
  INSERT INTO entities_fts(entities_fts,rowid,id,type,title,summary,project,tags)
  VALUES('delete',old.rowid,old.id,old.type,old.title,old.summary,old.project,old.tags);
END;
CREATE TRIGGER IF NOT EXISTS entities_au AFTER UPDATE ON entities BEGIN
  INSERT INTO entities_fts(entities_fts,rowid,id,type,title,summary,project,tags)
  VALUES('delete',old.rowid,old.id,old.type,old.title,old.summary,old.project,old.tags);
  INSERT INTO entities_fts(rowid,id,type,title,summary,project,tags)
  VALUES(new.rowid,new.id,new.type,new.title,new.summary,new.project,new.tags);
END;

CREATE INDEX IF NOT EXISTS idx_entities_project_type ON entities(project,type);
CREATE INDEX IF NOT EXISTS idx_rel_src ON relations(src);
CREATE INDEX IF NOT EXISTS idx_rel_dst ON relations(dst);

CREATE TABLE IF NOT EXISTS branches (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  project TEXT,
  status TEXT NOT NULL,
  objective TEXT NOT NULL DEFAULT '',
  last_result TEXT NOT NULL DEFAULT '',
  unresolved TEXT NOT NULL DEFAULT '[]',
  next_action TEXT NOT NULL DEFAULT '',
  blocker TEXT NOT NULL DEFAULT '',
  parent_branch TEXT REFERENCES branches(id),
  worker TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
  id TEXT PRIMARY KEY,
  branch_id TEXT NOT NULL REFERENCES branches(id),
  status TEXT NOT NULL,
  summary TEXT NOT NULL,
  unresolved TEXT NOT NULL DEFAULT '[]',
  next_action TEXT NOT NULL DEFAULT '',
  blocker TEXT NOT NULL DEFAULT '',
  provenance TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_branches_status ON branches(status,updated_at);
CREATE INDEX IF NOT EXISTS idx_checkpoints_branch ON checkpoints(branch_id,created_at);

CREATE TABLE IF NOT EXISTS commitment_candidates (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  project TEXT,
  status TEXT NOT NULL DEFAULT 'CANDIDATE',
  meaningfulness REAL NOT NULL,
  leverage REAL NOT NULL,
  evidence REAL NOT NULL,
  reversibility REAL NOT NULL,
  human_attention_minutes REAL NOT NULL DEFAULT 0,
  opportunity_cost REAL NOT NULL DEFAULT 0,
  human_judgment_required INTEGER NOT NULL DEFAULT 0,
  risk_class TEXT NOT NULL DEFAULT 'low',
  score REAL,
  rationale TEXT NOT NULL DEFAULT '',
  source_entity_id TEXT REFERENCES entities(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_commitment_status_score
ON commitment_candidates(status, score DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS commitment_outcomes (
  id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES commitment_candidates(id),
  valuable INTEGER NOT NULL,
  durable_artefact TEXT,
  human_attention_minutes REAL NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_commitment_outcomes_candidate
ON commitment_outcomes(candidate_id, created_at);

CREATE TABLE IF NOT EXISTS semantic_assertions (
  id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  predicate TEXT NOT NULL,
  object_id TEXT,
  literal_value TEXT,
  confidence REAL NOT NULL DEFAULT 1.0,
  epistemic_status TEXT NOT NULL DEFAULT 'explicit',
  valid_from TEXT,
  valid_to TEXT,
  source_entity_id TEXT,
  source_ref TEXT,
  supersedes TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_semantic_subject_pred ON semantic_assertions(subject_id,predicate);
CREATE INDEX IF NOT EXISTS idx_semantic_object ON semantic_assertions(object_id);
CREATE INDEX IF NOT EXISTS idx_semantic_source ON semantic_assertions(source_entity_id);

CREATE TABLE IF NOT EXISTS ontology_terms (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  parent_id TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  version INTEGER NOT NULL DEFAULT 1,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ontology_term_name ON ontology_terms(kind,canonical_name);

CREATE TABLE IF NOT EXISTS ontology_proposals (
  id TEXT PRIMARY KEY,
  proposal_type TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  parent_term_id TEXT,
  evidence_count INTEGER NOT NULL DEFAULT 0,
  confidence REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'candidate',
  rationale TEXT NOT NULL DEFAULT '',
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ontology_proposal_name
ON ontology_proposals(proposal_type, canonical_name);

CREATE TABLE IF NOT EXISTS semantic_embeddings (
  target_kind TEXT NOT NULL,
  target_id TEXT NOT NULL,
  model TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,
  dimensions INTEGER NOT NULL,
  vector_blob BLOB NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (target_kind,target_id,model)
);
CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_target
ON semantic_embeddings(target_kind,target_id);

CREATE TABLE IF NOT EXISTS resources (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  spec TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT '{}',
  generation INTEGER NOT NULL DEFAULT 1,
  observed_generation INTEGER NOT NULL DEFAULT 0,
  controller TEXT,
  authority TEXT NOT NULL DEFAULT 'system',
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_resources_kind_name ON resources(kind,name);

CREATE TABLE IF NOT EXISTS resource_conditions (
  resource_id TEXT NOT NULL REFERENCES resources(id),
  condition_type TEXT NOT NULL,
  status TEXT NOT NULL,
  reason TEXT,
  message TEXT,
  severity TEXT NOT NULL DEFAULT 'info',
  observed_at TEXT NOT NULL,
  PRIMARY KEY(resource_id,condition_type)
);

CREATE TABLE IF NOT EXISTS attention_items (
  id TEXT PRIMARY KEY,
  resource_id TEXT,
  category TEXT NOT NULL,
  severity TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open',
  suggested_actions TEXT NOT NULL DEFAULT '[]',
  source TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agalmic_reconciliations (
  task_id TEXT PRIMARY KEY,
  task_state TEXT NOT NULL,
  scarcity_type TEXT,
  scarcity_entity_id TEXT,
  capability_entity_id TEXT,
  confidence REAL NOT NULL DEFAULT 0,
  rationale TEXT NOT NULL DEFAULT '',
  proposed_action TEXT NOT NULL DEFAULT '',
  adjacent_possible TEXT,
  observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agalmic_recon_state ON agalmic_reconciliations(task_state,scarcity_type);
CREATE TABLE IF NOT EXISTS guardian_runs (
  id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  model TEXT,
  status TEXT NOT NULL,
  packet_sha256 TEXT,
  proposal_count INTEGER NOT NULL DEFAULT 0,
  metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS guardian_proposals (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES guardian_runs(id),
  category TEXT NOT NULL,
  severity TEXT NOT NULL,
  title TEXT NOT NULL,
  rationale TEXT NOT NULL,
  evidence_refs TEXT NOT NULL DEFAULT '[]',
  proposed_change TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'candidate',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS governor_reconciliations (
  resource_id TEXT PRIMARY KEY REFERENCES resources(id),
  disposition TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  attempt_count INTEGER NOT NULL DEFAULT 0,
  last_action TEXT,
  last_result TEXT NOT NULL DEFAULT '{}',
  observed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS governor_actions (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES resources(id),
  generation INTEGER NOT NULL DEFAULT 0,
  action TEXT NOT NULL,
  status TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  result TEXT NOT NULL DEFAULT '{}',
  started_at TEXT NOT NULL,
  completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_governor_actions_resource
  ON governor_actions(resource_id,started_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_governor_action_attempt
  ON governor_actions(resource_id,generation,action,attempt);
CREATE TABLE IF NOT EXISTS manfred_commands (
  idempotency_key TEXT PRIMARY KEY,
  command_type TEXT NOT NULL,
  target_id TEXT,
  payload TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL,
  result TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_manfred_commands_status
  ON manfred_commands(status,updated_at);
CREATE TABLE IF NOT EXISTS control_intents (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  priority TEXT NOT NULL DEFAULT 'P2',
  risk_tier TEXT NOT NULL DEFAULT 'normal',
  execution_policy TEXT NOT NULL DEFAULT 'HUMAN_ONLY',
  source TEXT,
  source_ref TEXT,
  provenance TEXT NOT NULL DEFAULT '{}',
  evidence_refs TEXT NOT NULL DEFAULT '[]',
  recommended_action TEXT NOT NULL DEFAULT '{}',
  alternatives TEXT NOT NULL DEFAULT '[]',
  decision_required INTEGER NOT NULL DEFAULT 1,
  origin_conversation_id TEXT,
  origin_conversation_url TEXT,
  execution_conversation_id TEXT,
  execution_conversation_url TEXT,
  verification_policy TEXT NOT NULL DEFAULT '{}',
  outcome TEXT NOT NULL DEFAULT '{}',
  acknowledged_at TEXT,
  resolved_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_control_intents_status
  ON control_intents(status, priority, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_control_intents_source
  ON control_intents(source, source_ref);
CREATE TABLE IF NOT EXISTS control_intent_events (
  id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL REFERENCES control_intents(id),
  event_type TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT,
  actor TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_control_intent_events_intent
  ON control_intent_events(intent_id, created_at);

CREATE TABLE IF NOT EXISTS control_intent_execution_attempts (
  id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL UNIQUE REFERENCES control_intents(id),
  action_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  status TEXT NOT NULL,
  result TEXT NOT NULL DEFAULT '{}',
  started_at TEXT NOT NULL,
  completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_control_intent_execution_attempts_status
  ON control_intent_execution_attempts(status, started_at);

CREATE TABLE IF NOT EXISTS attention_control_intents (
  attention_id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL UNIQUE REFERENCES control_intents(id),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attention_control_intents_intent
  ON attention_control_intents(intent_id);

CREATE TABLE IF NOT EXISTS alerts (
  id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL REFERENCES control_intents(id),
  dedupe_key TEXT NOT NULL,
  severity TEXT NOT NULL,
  state TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  policy TEXT NOT NULL DEFAULT '{}',
  escalation_count INTEGER NOT NULL DEFAULT 0,
  last_escalated_at TEXT,
  next_escalation_at TEXT,
  expires_at TEXT,
  raised_at TEXT NOT NULL,
  delivered_at TEXT,
  seen_at TEXT,
  acknowledged_at TEXT,
  resolved_at TEXT,
  resolution_reason TEXT,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_active_dedupe
  ON alerts(dedupe_key) WHERE state <> 'RESOLVED';
CREATE INDEX IF NOT EXISTS idx_alerts_state_severity
  ON alerts(state,severity,updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_intent
  ON alerts(intent_id,state,updated_at DESC);

-- Streaming distillation queue contract (reconciled from deployed P0)
CREATE TABLE IF NOT EXISTS distillation_adjudications (
  candidate_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  canonicalizable INTEGER NOT NULL,
  confidence REAL NOT NULL,
  rationale TEXT NOT NULL,
  adjudicator TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS distillation_artifacts(
  id TEXT PRIMARY KEY,
  source_entity_id TEXT,
  source_ref TEXT,
  content_sha256 TEXT NOT NULL,
  byte_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'ingested',
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS distillation_candidates(id TEXT PRIMARY KEY,run_id TEXT,kind TEXT,subject TEXT,predicate TEXT,object TEXT,literal TEXT,confidence REAL,evidence_ids TEXT,status TEXT DEFAULT 'candidate',created_at TEXT, segment_id text, source_entity_id text, extractor_model text, metadata text not null default '{}');
CREATE TABLE IF NOT EXISTS distillation_claim_candidates(
  work_id TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(work_id,candidate_id)
);
CREATE TABLE IF NOT EXISTS distillation_claim_work(
  id TEXT PRIMARY KEY,
  segment_id TEXT NOT NULL,
  extractor TEXT,
  raw_record TEXT,
  parsed_record TEXT,
  validation_status TEXT NOT NULL DEFAULT 'pending',
  salvage_state TEXT NOT NULL DEFAULT 'none',
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  candidate_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
, parent_work_id text, route_stage text, model_cost real);
CREATE TABLE IF NOT EXISTS distillation_evidence_state (
  evidence_id TEXT PRIMARY KEY,
  last_run_id TEXT,
  status TEXT NOT NULL,
  processed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS distillation_gold (
  candidate_id TEXT PRIMARY KEY,
  expected_status TEXT NOT NULL,
  canonicalizable INTEGER NOT NULL,
  rationale TEXT NOT NULL,
  labeled_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS distillation_graphshape_review_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_id TEXT NOT NULL,
  reviewer_model TEXT NOT NULL,
  verdict TEXT NOT NULL,
  rationale TEXT,
  subject_title TEXT,subject_type TEXT,predicate TEXT,
  object_title TEXT,object_type TEXT,literal TEXT,
  reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS distillation_graphshape_reviews(
      candidate_id TEXT PRIMARY KEY, verdict TEXT NOT NULL, rationale TEXT,
      subject_title TEXT,subject_type TEXT,predicate TEXT,
      object_title TEXT,object_type TEXT,literal TEXT,
      reviewer_model TEXT,reviewed_at TEXT);
CREATE TABLE IF NOT EXISTS distillation_metrics(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  observed_at TEXT NOT NULL,
  window_seconds INTEGER NOT NULL,
  segments_total INTEGER NOT NULL DEFAULT 0,
  segments_done INTEGER NOT NULL DEFAULT 0,
  claims_total INTEGER NOT NULL DEFAULT 0,
  claims_valid INTEGER NOT NULL DEFAULT 0,
  claims_quarantined INTEGER NOT NULL DEFAULT 0,
  retries INTEGER NOT NULL DEFAULT 0,
  salvage_success INTEGER NOT NULL DEFAULT 0,
  provenance_complete INTEGER NOT NULL DEFAULT 0,
  governor_backlog INTEGER NOT NULL DEFAULT 0,
  promotion_backlog INTEGER NOT NULL DEFAULT 0,
  metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS distillation_temporal_authority (
  candidate_id TEXT PRIMARY KEY,
  temporal_mode TEXT NOT NULL,
  observed_at TEXT,
  auto_eligible INTEGER NOT NULL,
  reasons TEXT NOT NULL DEFAULT '[]',
  checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS distillation_promotion_gate(
      candidate_id TEXT PRIMARY KEY, decision TEXT NOT NULL, score REAL NOT NULL,
      reasons TEXT NOT NULL DEFAULT '[]', subject_resolution TEXT,
      object_resolution TEXT, contradiction_count INTEGER NOT NULL DEFAULT 0,
      checked_at TEXT NOT NULL, gate_fingerprint TEXT);
CREATE TABLE IF NOT EXISTS distillation_review_adjudications(
      candidate_id TEXT NOT NULL,gate_fingerprint TEXT NOT NULL,gate_checked_at TEXT NOT NULL,
      action TEXT NOT NULL,reason TEXT NOT NULL,before_state TEXT NOT NULL DEFAULT '{}',
      after_state TEXT NOT NULL DEFAULT '{}',adjudicated_at TEXT NOT NULL,
      PRIMARY KEY(candidate_id,gate_fingerprint));
CREATE INDEX IF NOT EXISTS idx_dist_review_adjudications_action
ON distillation_review_adjudications(action,adjudicated_at);
CREATE TABLE IF NOT EXISTS distillation_ready(
      candidate_id TEXT PRIMARY KEY,status TEXT NOT NULL,confidence REAL NOT NULL,
      reason TEXT NOT NULL,ready_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS distillation_reconciliation_proposals(
      candidate_id TEXT PRIMARY KEY, canonical_kind TEXT,
      subject_mode TEXT,subject_id TEXT,subject_type TEXT,subject_title TEXT,
      predicate TEXT,object_mode TEXT,object_id TEXT,object_type TEXT,
      object_title TEXT,literal TEXT,confidence REAL,rationale TEXT,
      status TEXT DEFAULT 'candidate',created_at TEXT);
CREATE TRIGGER IF NOT EXISTS distillation_review_proposal_fingerprint_dirty
AFTER UPDATE OF canonical_kind,subject_mode,subject_id,subject_type,subject_title,
                predicate,object_mode,object_id,object_type,object_title,literal,confidence,rationale
ON distillation_reconciliation_proposals
BEGIN
  UPDATE distillation_promotion_gate SET gate_fingerprint=NULL WHERE candidate_id=NEW.candidate_id;
END;
CREATE TABLE IF NOT EXISTS distillation_resolutions(
      candidate_id TEXT PRIMARY KEY,subject_entity_id TEXT,object_entity_id TEXT,
      create_subject INTEGER NOT NULL DEFAULT 0,create_object INTEGER NOT NULL DEFAULT 0,
      confidence REAL NOT NULL,rationale TEXT NOT NULL,resolver TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distillation_runs(id TEXT PRIMARY KEY,started_at TEXT,completed_at TEXT,status TEXT,evidence_count INTEGER DEFAULT 0,item_count INTEGER DEFAULT 0,metadata TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS distillation_salvage_events(
  id TEXT PRIMARY KEY,
  work_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  action TEXT NOT NULL,
  outcome TEXT NOT NULL,
  model TEXT,
  detail TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS distillation_segments(
  id TEXT PRIMARY KEY,
  artifact_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  start_offset INTEGER,
  end_offset INTEGER,
  content_sha256 TEXT NOT NULL,
  content TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL, priority integer not null default 0, lease_owner text, lease_until text, last_model text,
  UNIQUE(artifact_id,ordinal)
);
CREATE TABLE IF NOT EXISTS distillation_validations(
      candidate_id TEXT PRIMARY KEY,validator_model TEXT,verdict TEXT,
      validated_kind TEXT,durability TEXT,confidence REAL,rationale TEXT,
      validated_at TEXT);
CREATE INDEX IF NOT EXISTS idx_claim_candidates_candidate ON distillation_claim_candidates(candidate_id);
CREATE INDEX IF NOT EXISTS idx_claim_work_state ON distillation_claim_work(validation_status,salvage_state);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dist_artifact_sha ON distillation_artifacts(content_sha256);
CREATE INDEX IF NOT EXISTS idx_dist_segments_lease on distillation_segments(status,priority desc,lease_until);
CREATE INDEX IF NOT EXISTS idx_dist_segments_status ON distillation_segments(status,updated_at);
CREATE INDEX IF NOT EXISTS idx_graphshape_history_candidate
ON distillation_graphshape_review_history(candidate_id,reviewed_at);
