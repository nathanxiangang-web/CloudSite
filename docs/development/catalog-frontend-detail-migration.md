# Catalog Frontend Migration — M6b

M6b migrates the public Catalog detail slice into the feature boundary.

Owned after this slice:
- /catalog list view;
- /catalog/[entryId] detail view;
- public release picker;
- public asset filtering/download form;
- public detail DTOs/helpers/API calls;
- list and detail CSS modules.

The route only resolves the entryId and injects the legacy follow control.
Follow/subscription remains intentionally deferred to M6c.

Catalog detail-specific rules are removed from app/globals.css and the
globals.css ratchet is lowered to 149456 bytes.

Still legacy:
- components/catalog/CatalogFollowButton.tsx;
- aggregate search integration;
- admin Catalog CRUD/editor;
- legacy src/lib/catalog* for those remaining consumers.
