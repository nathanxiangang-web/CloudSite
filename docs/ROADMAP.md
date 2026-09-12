# CloudSite Roadmap

This roadmap tracks planned development phases. Items are committed when they pass full test suites and meet the acceptance criteria defined in the product development handbook.

## Completed

### v1.0 — Baseline (2024)

- AList-powered portal with browse, search, preview, share, download
- User accounts, admin console, Docker Compose deployment
- SQLite + FastAPI backend, Next.js frontend

### v1.1 — Resourceization

- C1: Catalog entry/version/asset model
- C2: Content detection and metadata extraction
- C3: Release channels and asset schema
- C4: Multi-platform asset matching
- D1: Search index rebuild and projection
- D2: Faceted filtering and sort
- B1: Site branding and home page
- B2: Publication scope and visibility
- A1: Automation rule engine
- A2: Batch organize and review
- M1–M6: Migration, identity, sync, diagnostics, health check, backup

### v1.3 — Automated Operations

- A1: Automation rule parsing and execution
- A2: Batch organize and review workflows
- A3: Optional AI content completion (provider config, draft generation, budget tracking, review workflow)
- A4: Content quality detection and maintenance to-do queue

## In Progress

### v1.2 — Website & Adoption

- G1: Open-source adoption experience (templates, demo data, contribution guides, issue/PR templates, roadmap)
- G2: Value measurement before scaling (baseline metrics, event tracking, retention controls)

## Planned

### v1.5 — Team Collaboration

- T1: Multi-user roles and permissions (owner, editor, reviewer, viewer)
- T2: Delivery packages (curated bundles with export/import, cross-instance portability)

### v2.0 — Open Ecosystem

- X1: Plugin marketplace (third-party content detectors, preview handlers, automation rules)
- X2: Open API (stable public API for external integrations, webhook delivery)
- X3: Federated search (cross-instance resource discovery, shared index protocol)

## Maintenance

Performance optimization, bug fixes, and dependency updates are ongoing across all phases. Infrastructure changes require demonstrated bottlenecks before scaling out.

---

This roadmap is a proposal, not a commitment. Priorities may shift based on adoption feedback and resource availability. See [CloudSite未来产品开发手册.md](../开发文档/CloudSite未来产品开发手册.md) for detailed module specifications and acceptance criteria.