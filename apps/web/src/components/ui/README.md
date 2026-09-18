# Shared UI Primitives

This directory is for business-agnostic presentational primitives.

Files here must never import from src/features. If a component knows about
catalog, search, downloads, users, submissions, or another business capability,
it belongs in that feature instead.
