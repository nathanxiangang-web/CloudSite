# CloudSite 1.0.0 FAQ

## Why does a video fail to play?

CloudSite uses the browser's native decoder and does not transcode media. MP4 with H.264/AAC is the primary compatibility target. Unsupported codecs or containers, including some HEVC, MKV, and AVI files, should be downloaded and opened in a compatible local player.

## Why does a download redirect to AList?

That is the intended 1.0.0 architecture. CloudSite validates access and returns HTTP 302 to an AList-native entry. It does not proxy file bodies, so the final transfer is handled by AList and the storage provider.

## Why is a resource missing from search?

Possible causes include:

1. Its content root is disabled.
2. Its status is `missing` after confirmation across independent synchronization cycles.
3. The FTS update for the current window has not completed.
4. A `.cloudsite` ignore rule excludes the path.

## Why was my account signed out?

The session may have expired or been revoked. Disabling or deleting a user, resetting a password, or changing the password invalidates existing sessions.

## Why does the current drive show only “Drive”?

CloudSite shows a neutral fallback when storage metadata cannot be read. Check the saved AList connection, account permissions, base path, and encryption key. If the encryption key changed after credentials were saved, save the AList password again or restore the matching key.

## Can `index.db` be deleted?

It is rebuildable, but deletion should still be deliberate and preceded by a backup. CloudSite enters `INDEX_RECOVERY` and rebuilds the content index while preserving the authoritative state in `state.db`.

## Can `state.db` be deleted?

No. It contains the instance identity, users, sessions, encrypted credentials, settings, collections, shares, and stable resource identities. Restore it from a verified backup if it is damaged or lost.

## What is the default download limit?

The default client-IP limit is five successful download starts in a sliding 60-second window. The sixth request must wait for the server-provided retry period. Shares also enforce their own configured download limits.

## Is generic AList synchronization incremental?

No. CloudSite 1.0.0 uses Rolling Full Verification for generic AList. Only a provider that explicitly declares delta capability may use a delta strategy.

## Why is only one collection visible?

The home page displays up to the configured collection limit. Visibility, active status, and backend sort value are managed in the administration console. Zero-resource collections may remain visible and show their real count.
