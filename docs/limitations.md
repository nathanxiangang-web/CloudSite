# CloudSite 1.0.0 Limitations

CloudSite 1.0.0 is stable within the following explicit boundaries.

## Generic AList is not a delta provider

Generic AList uses Rolling Full Verification. CloudSite does not describe it as true incremental synchronization. A provider must explicitly declare delta capability before the delta strategy can be selected.

## Browser playback does not support every codec

CloudSite does not transcode, generate HLS, or proxy media bodies. MP4 with H.264/AAC is the primary browser target. Compatibility with MKV, AVI, HEVC, and other formats depends on the browser and operating system.

## Folder identifiers may be path-derived

Resources use stable random IDs, and reliable rename or move operations preserve those IDs. Folder IDs may still depend on paths, so CloudSite does not guarantee that every folder URL remains unchanged forever.

## AList destination URLs are not fully hidden

HTTP 302 downloads and binary previews may expose a temporary AList URL in the browser. Hiding the final destination would require proxying file bodies, which is outside the 1.0.0 architecture.

## Generic AList cannot identify every move or copy

Stable identity resolution is conservative. Ambiguous matches receive a new resource ID rather than risking an incorrect merge.

## SQLite has concurrency limits

CloudSite uses SQLite in WAL mode with a busy timeout and automatic checkpoints. This is appropriate for the intended self-hosted workload but not for extremely high concurrent write volume.

## Features not included in 1.0.0

- Redis, PostgreSQL, or Celery infrastructure
- FFmpeg transcoding or HLS generation
- User file uploads
- Paid plans or membership tiers
- Comments or community features
- Complex ACL management
- AI recommendations or OCR indexing
- Large-scale distributed deployment
