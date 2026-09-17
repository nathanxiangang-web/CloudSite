# AI Context Pack: API Contract Map

Purpose: map API endpoint groups to their owning module so an AI agent knows
which module to touch for a given endpoint. All routers are thin (Rule 2):
parse, check perms, call service, return.

## Endpoint Groups by Module

### users module
| Prefix | Endpoints | Auth |
|--------|-----------|------|
| /api/auth | login, logout, register, refresh | public/session |
| /api/users | profile, update, delete | session |
| /api/admin/auth | admin login, logout | public/admin session |
| /api/admin/users | list, update role, delete | admin session |

### providers module
| Prefix | Endpoints | Auth |
|--------|-----------|------|
| /api/admin/providers | connection CRUD, test, capability refresh | admin |
| /api/admin/content-roots | mapping CRUD | admin |

### resources module
| Prefix | Endpoints | Auth |
|--------|-----------|------|
| /api/folders | browse, tree | session/share |
| /api/resources | detail, list | session/share |
| /p/{resource_id} | preview redirect (302) | session/share |
| /d/{resource_id} | download redirect (302) | session/share |

### indexing module
| Prefix | Endpoints | Auth |
|--------|-----------|------|
| /api/admin/indexing | scan trigger, status, snapshot list | admin |

### search module
| Prefix | Endpoints | Auth |
|--------|-----------|------|
| /api/search | full-text search, suggestions | session |
| /api/admin/search | rebuild, recover, status | admin |

### catalog module
| Prefix | Endpoints | Auth |
|--------|-----------|------|
| /api/catalog | entry list, detail, releases | session |
| /api/catalog/{id}/follow | follow, unfollow | session |
| /api/admin/catalog | entry CRUD, metadata, publish, tags, relations | admin/editor |

### collections module
| Prefix | Endpoints | Auth |
|--------|-----------|------|
| /api/collections | CRUD, items, topics | session |
| /api/collections/seed | generate seed | session |

### shares module
| Prefix | Endpoints | Auth |
|--------|-----------|------|
| /api/shares | create, list, revoke | session |
| /s/{token} | share page, validate | public |
| /s/{token}/d/{resource_id} | share download redirect (302) | public (token) |

### submissions module
| Prefix | Endpoints | Auth |
|--------|-----------|------|
| /api/submissions | create, list own, withdraw | session |
| /api/admin/submissions | list queue, review, apply | admin/editor |

### notifications module
| Prefix | Endpoints | Auth |
|--------|-----------|------|
| /api/notifications | list, mark read, channel config | session |

### automation module
| Prefix | Endpoints | Auth |
|--------|-----------|------|
| /api/admin/automation | rules CRUD, run | admin |
| /api/admin/suggestions | list, review, apply | admin/editor |
| /api/admin/parser-candidates | CRUD, evaluate, batch | admin |

### delivery module
| Prefix | Endpoints | Auth |
|--------|-----------|------|
| (internal) | prepare, track, diagnostics | session |
| Download redirects may flow through delivery after resources prepares | session/share |

## Transfer Semantics (302 Redirects)

CloudSite never proxies file bodies. These endpoints return 302:

| Entry | Module | Behavior |
|-------|--------|----------|
| /d/{resource_id} | resources/delivery | authorize, resolve, 302 to AList |
| /p/{resource_id} | resources | authorize, resolve preview, 302 |
| /s/{token}/d... | shares | validate scope, resolve ID, 302 |

## Router Rules

1. Routers only: parse request, check permissions, call service, return.
2. No multi-step SQL in routers.
3. No cross-module transaction assembly in routers.
4. No session.commit() in routers (use unit of work in service).
5. No provider calls directly in routers (use service).
6. Routers are registered in app/api.py.

## Auth Model

- User sessions: opaque token, server-side in user_sessions.
- Admin sessions: separate, shorter TTL, in admin_sessions.
- Share tokens: HMAC-signed, stateless, validated by shares module.
- Permission checks call users.contracts.has_permission(user, scope, action).

## Response Conventions

- Errors use typed exception classes mapped by platform/http exception
  handlers to consistent JSON error envelopes.
- Pagination uses cursor or offset with total counts.
- All responses are JSON except 302 redirects (no body).