# ADR-005: Provider Capabilities

Date: 2026-09-17
Status: Accepted
Supersedes: none

## Context

CloudSite connects to AList instances as storage providers. Different AList
deployments and storage backends support different features: some support
range requests and streaming, some support thumbnails, some support delta
list, some only support full list. The legacy code assumes a single provider
shape and branches on provider type ad-hoc, causing:

- Preview code peppered with `if provider_kind == "xxx"` branches.
- Download logic that assumes streaming but fails on non-streaming backends.
- No way to add a new provider without editing multiple service files.
- Capability assumptions spread across resources, delivery, and indexing.

## Decision

Introduce a `ProviderCapability` model in `modules/providers/` that is probed
on connection and exposed via contracts:

```text
ProviderCapability:
  supports_stream       - range request / streaming download
  supports_preview      - thumbnail / preview generation
  supports_delta        - incremental list with cursor
  supports_list_recursive - recursive list in one call
  max_page_size         - list page size limit
  preview_kinds         - which preview types are available
```

Capabilities are probed on connect (a capability check routine per provider
kind) and cached in `provider_sync_state` / a capability cache. They are
re-probed on provider upgrade or manual refresh.

All consumers (resources, delivery, indexing) query capabilities via
`contracts/public.py` and degrade gracefully when a capability is absent:
- No stream: delivery falls back to full download.
- No preview: resources return a null preview; client falls back to download.
- No delta: indexing falls back to full scan for that provider.

## Alternatives Considered

1. **Static config per provider** - rejected: operators misconfigure; probing
   detects actual support and adapts to provider upgrades automatically.
2. **Assume max capability, fail at runtime** - rejected: causes poor UX with
   runtime errors on unsupported operations; graceful degradation is better.
3. **Per-provider subclasses with method presence as capability** - rejected:
   couples capability to code structure; a config/data model is more flexible
   and lets us add providers without code changes.
4. **No capability model, keep ad-hoc branches** - rejected: the branching is
   already spreading and is the problem we are solving.

## Consequences

- Positive: adding a provider is data + a capability probe, not code edits
  across modules.
- Positive: graceful degradation improves UX on limited backends.
- Positive: capability is a single source of truth; no scattered branches.
- Negative: capability probe adds a step on connect; mitigated by caching.
- Negative: a provider may lie about support (claims stream, lacks range);
  probe must test actual behavior, not just advertised metadata.
- Neutral: capability re-probe on upgrade is manual or version-triggered, not
  continuous.

## References

- modules/providers/README.md
- ADR-001 (modular monolith; providers is a leaf domain)
- docs/contracts.md (provider capability contract)