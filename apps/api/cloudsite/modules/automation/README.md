# Automation Module

## Responsibility
Automation rules, suggestion engine, parser candidates, parser evaluation.

## Public API
- Suggestion generate/review, parser candidate CRUD, batch processing

## Domain Model
- SuggestionRule, ParserCandidate, ParserCandidateBatch, ReviewSuggestion

## Database Tables
- parser_candidates, parser_candidate_batches, review_suggestions

## Dependencies
- platform/db
- platform/tasks
- modules/catalog (via contracts)

## Current Migration Status
Code in `services/suggestion_*.py`, `services/parser_candidate*.py`. To be moved in Phase 3.
