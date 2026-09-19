# Automation Module

## Responsibility

Automation rules, the suggestion engine, parser candidates, and parser
evaluation. This module provides AI-assisted and rule-based automation for
catalog metadata: it generates metadata suggestions for review, manages
parser candidates (proposed parsing rules for resource names), and evaluates
parser candidates against a test corpus. All automation output is advisory;
a human editor approves before anything applies to the catalog.

Core duties:
- Suggestion generation (AI or rule-based) for catalog metadata.
- Suggestion review lifecycle (pending, accepted, rejected, applied).
- Parser candidate CRUD and batch processing.
- Parser evaluation against a test corpus.
- Automation rule definition and execution.

## Public API

- `generate_suggestions(entry_id, strategy)` - produce metadata suggestions.
- `review_suggestion(suggestion_id, decision)` - editor accepts/rejects.
- `create_parser_candidate(candidate)` - propose a parsing rule.
- `evaluate_parser(candidate_id, corpus)` - score against test data.
- `run_batch(batch_id)` - process a batch of candidates or suggestions.

Exports live in `contracts/public.py`.

## Domain Model

- SuggestionRule (id, kind, condition, action, enabled)
- ReviewSuggestion (id, entry_id, field, proposed_value, status, source)
- ParserCandidate (id, pattern, description, status, score)
- ParserCandidateBatch (id, candidate_ids, status, started_at, completed_at)
- AutomationRule (id, trigger, action, enabled, last_run_at)

## Database Tables

- `catalog_suggestions` - AI/rule-generated metadata suggestions.
- `parser_candidates` - proposed parsing rules.
- `parser_candidate_batches` - batch processing records.
- `review_suggestions` - suggestion review queue.
- Automation rule tables managed here (see migrations).

Note: `catalog_suggestions` is currently in the catalog table family but
semantically belongs to automation; it will be reassigned during migration.

## Dependencies

- platform/db
- platform/tasks (for batch processing and AI generation jobs)
- modules/catalog (via contracts) - to read entries and apply approved changes.
- modules/resources (via contracts) - persistence-neutral parser input lookup.
- plugins/ai (optional, env-gated) - for AI-powered suggestion generation.

## Events/Tasks

- Enqueues `generate_suggestions`, `evaluate_parser`, `run_batch` tasks.
- Emits `automation.suggestion_generated`, `automation.parser_evaluated`.
- On suggestion acceptance, emits `catalog.metadata_changed` via catalog.
- Batch processing is task-driven with lease and retry.

## Security

- Suggestions are never auto-applied; an editor must approve.
- AI generation uses the plugins/ai adapter; API keys are in platform/settings,
  never in module code.
- Parser evaluation corpus is read-only; candidates cannot modify it.
- Batch processing runs with system scope; lease owner is a worker.
- AI prompt and response are logged for audit but not user PII.

## Failure Modes

- AI provider unavailable: suggestion task retries; if exhausted, the
  suggestion is marked `generation_failed` and the editor can retry.
- Parser candidate produces no matches: score 0; candidate stays in review.
- Batch partial failure: failed items marked; batch continues; summary report.
- Suggestion for deleted entry: marked `entry_gone`; cleaned up lazily.

## Tests

- `tests/unit/` - parser pattern matching, suggestion scoring, batch logic.
- `tests/contract/` - public API stability.
- Target coverage: generation, review lifecycle, parser evaluation, batch.

## Do Not

- Do not auto-apply suggestions; always require editor approval.
- Do not put AI API keys in module code; use platform/settings.
- Do not depend on modules/search or modules/shares.
- Do not run batch processing inline; always via tasks.

## Current Migration Status

The parser subdomain is now module-owned. `ParserCandidateTask` lives in
`infrastructure/models.py`, the deterministic resource-name parser lives in
`domain/resource_name_parser.py`, and parser candidate execution reads indexed
resource metadata only through the Resources public contract. Historical
`cloudsite.models.ParserCandidateTask` and
`cloudsite.services.resource_name_parser` paths remain compatibility facades.

Parser-candidate seeding now reads frozen sync runs/changes through the Indexing
public contract; it no longer imports shared Resource/Sync ORM.

The remaining shared-core debt is intentionally limited to suggestion
generation/review. Those three debt IDs are the next Automation migration
slice; suggestion apply must move through Catalog contracts rather than
importing Catalog ORM or legacy services directly.