# Submissions Module

## Responsibility
User submissions, admin review workflow.

## Public API
- Submission create/review/approve/reject

## Domain Model
- Submission, SubmissionReview

## Database Tables
- submissions, submission_reviews

## Dependencies
- platform/db
- modules/catalog (via contracts)

## Current Migration Status
Code in `services/submissions.py`, `routers/submissions.py`. To be moved in Phase 3.
