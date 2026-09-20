# CloudSite Limitations

CloudSite is designed primarily for self-hosted resource libraries backed by AList or compatible providers. The stable `v1.0.0` line and the `v2.0.0-alpha.x` development line share several architectural boundaries that operators should understand.

## Generic AList is not a true delta provider

Generic AList synchronization relies on verification of remote state rather than a provider-native change journal. CloudSite only treats a provider as delta-capable when the adapter explicitly declares that capability.

## Browser playback does not support every codec

CloudSite does not transcode media into universally compatible formats. Browser playback still depends on the browser, operating system, codec and storage/provider behavior. MP4 with H.264/AAC remains the most broadly compatible target.

## Direct delivery may expose the destination URL

CloudSite normally authorizes a request and redirects the client to an AList/provider-native URL instead of proxying large file bodies. As a result, temporary destination URLs may be visible to the browser or client.

## Not every move or copy can be identified perfectly

Stable resource identity resolution is intentionally conservative. When provider metadata is insufficient and a rename/move match is ambiguous, CloudSite prefers creating or retaining separate identities rather than incorrectly merging unrelated resources.

## Some folder identity remains path-sensitive

Resource identities are designed to remain stable where reliable evidence exists, but folder/navigation identity may still depend on paths. CloudSite does not guarantee that every folder URL remains permanent after arbitrary upstream reorganizations.

## SQLite has write-concurrency limits

Current deployments use SQLite for the self-hosted workload. WAL mode and bounded write patterns work well for the intended single-instance deployment, but SQLite is not intended for very high concurrent write volume or multi-node database access.

## Background processing is still evolving in the 2.0 alpha line

The 2.0 prerelease line is adding richer automation, AI-assisted workflows and other background operations while the long-term task/worker architecture continues to evolve. Operators should treat prerelease background workflows as experimental until 2.0 reaches stable status.

## Large libraries depend on provider behavior

Indexing speed and verification cost are influenced by upstream listing latency, pagination quality, rate limits and provider capabilities. CloudSite can reduce unnecessary requests, but it cannot provide a true incremental feed when the upstream provider does not expose one.

## Features intentionally outside the current core

CloudSite does not aim to be a general-purpose object-storage gateway or media-transcoding cluster. Large-file transfer remains the responsibility of AList/storage providers, and distributed multi-node deployment is not the default operating model.

For stable compatibility guarantees, see [Public contracts](contracts.md). For prerelease direction, see the [Roadmap](ROADMAP.md).
