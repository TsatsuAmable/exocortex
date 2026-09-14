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

CREATE TABLE IF NOT EXISTS attention_control_intents (
  attention_id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL UNIQUE REFERENCES control_intents(id),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attention_control_intents_intent
  ON attention_control_intents(intent_id);
