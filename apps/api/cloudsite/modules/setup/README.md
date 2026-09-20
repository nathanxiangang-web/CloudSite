# Setup module

The Setup module owns the first-run wizard progress state and coordinates the five active setup steps: connect, scope, preset, brand, and publish. Legacy samples/preview progress is normalized for existing installations but is no longer exposed as product workflow. It deliberately does not own provider connection/root mapping data, presentation configuration, or site settings.

Those writes are performed through their owner boundaries:

- Providers contract: AList connection and root visibility/order.
- Presentation contract: preset selection and theme updates.
- Site helpers: site/brand text compatibility edge.
- Platform settings: setup completion marker.
- Platform observability: workflow audit events.

cloudsite.models.SetupWizardState remains a compatibility re-export while the migration is partial.
