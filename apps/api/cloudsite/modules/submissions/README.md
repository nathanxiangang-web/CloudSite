# Submissions Module

## Responsibility

User submissions and the admin review workflow. A submission is a user
proposal to add or correct a catalog entry (e.g., suggest metadata, report a
bad link, propose a new resource). Admins review submissions, approve or
reject them, and on approval the submission applies its proposed change to the
catalog. This module owns the submission lifecycle and review state machine.

Core duties:
- Submission creation (user proposes a change).
- Submission list and detail (user and admin views).
- Admin review: approve, reject, request changes.
- Apply approved submission to the catalog.
- Track review history and reviewer assignment.

## Public API

- `create_submission(user_id, target, proposal)` - new submission.
- `list_submissions(filter, page)` - user's or admin's queue.
- `get_submission(submission_id)` - detail with review history.
- `review_submission(submission_id, decision, note)` - admin action.
- `apply_submission(submission_id)` - apply approved change to catalog.

Exports live in `contracts/public.py`.

## Domain Model

- Submission (id, user_id, target_kind, target_id, proposal, status, created_at)
- SubmissionReview (submission_id, reviewer_id, decision, note, at)
- SubmissionProposal (kind, fields) - the proposed change payload.
- SubmissionStatus (draft, submitted, in_review, approved, rejected, applied)

## Database Tables

- `submissions` - submission records with proposal payload.
- `submission_reviews` - review history per submission.

Review history is append-only; a submission may have multiple reviews if
changes are requested and resubmitted.

## Dependencies

- platform/db
- modules/catalog (via contracts) - to apply approved changes.
- modules/notifications (via contracts) - to notify user of review outcome.
- modules/users (via contracts) - to resolve submitter and reviewer.

## Events/Tasks

- Emits `submission.created`, `submission.reviewed`, `submission.applied`.
- On approval, apply_submission may enqueue a catalog update task.
- User notification on review outcome via notifications module.

## Security

- A user can only view and withdraw their own submissions.
- Review requires admin or editor role; reviewer is recorded.
- Proposal payload is validated against the target's schema before apply.
- Apply is idempotent; a double-apply does not duplicate the catalog change.

## Failure Modes

- Target deleted before review: submission marked `target_gone`; admin closes.
- Apply fails (catalog validation): submission stays `approved`, apply retried
  via task; admin notified of the apply failure.
- Concurrent review by two admins: first review wins; second gets a conflict.
- Proposal schema mismatch: rejected at create time with validation errors.

## Tests

- `tests/unit/` - status machine transitions, proposal validation.
- `tests/contract/` - public API stability.
- Target coverage: create, review lifecycle, apply idempotency, permissions.

## Do Not

- Do not apply a submission without admin approval.
- Do not let users review their own submissions.
- Do not store catalog data in submissions; reference by ID and store the diff.
- Do not bypass the status machine; transitions are validated.

## Current Migration Status

Code is currently in `services/submissions.py` and `routers/submissions.py`.
These move to `modules/submissions/` in Phase 3. The module skeleton exists
with empty layers. The review workflow state machine will be formalized in the
domain layer during migration.