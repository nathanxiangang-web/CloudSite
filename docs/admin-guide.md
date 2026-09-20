# CloudSite 1.0.0 Administrator Guide

## Initial setup

1. Start CloudSite with a one-time `CLOUDSITE_SETUP_TOKEN`.
2. Open the administration console and save the AList connection.
3. Create enabled content roots for the AList directories that should be published.
4. Run the initial synchronization and verify folder and resource counts.
5. Remove the setup token from `.env` and restart CloudSite.

## AList connection

- Use a dedicated account with the minimum required permissions.
- Credentials are encrypted in `state.db`.
- Keep `CLOUDSITE_MASTER_KEY`, or its `CLOUDSITE_SECRET_KEY` fallback, stable for the life of the saved credentials.
- Use the connection test and download diagnostics before starting a full synchronization.

Changing the encryption key makes previously saved credentials unreadable. If that occurs, restore the matching key or save the AList password again.

## Content roots

Each content root maps one AList directory to a content type. Disabled roots are excluded from public browse, search, resource detail, download, preview, and collection output.

Removing a root mapping does not immediately erase indexed rows, but those rows are no longer published through the public API.

## Synchronization

- The initial synchronization performs a complete scan of enabled roots.
- After the initial index is valid, generic AList uses a 24-hour rolling verification cycle divided into four 6-hour windows.
- Missing objects require confirmation in two independent cycles.
- Suspicious large-scale path churn fails closed with zero-write scope protection.
- A manual path synchronization scans only the selected parent directory and does not replace the rolling verification schedule.

Review cycle state, pending work, upstream errors, and recent runs before manually retrying a failed window.

## Users

Administrators can create, rename, enable, disable, reset, and soft-delete users. Disabling, deleting, or resetting a password revokes the user's sessions. Deleted usernames remain reserved.

Passwords use Argon2id hashes and are never returned by the API or displayed in the administration console.

## Collections

Collections can group resources across folders and content types. Configure the name, cover, visibility, status, and backend sort value. Home-page order follows the backend sort value, and counts include only currently active resources.

## Shares

Administrators can inspect, create, update, cancel, restore, and delete shares. Four-digit access codes are stored as HMAC hashes, not plaintext. Share tickets are short-lived and limited to the selected share scope.

## Site settings

Site settings control the site name, home-page title and description, registration, submission address, GitHub URL, default share duration, and the desktop share-page image.

## Backup and recovery

```bash
bash scripts/backup.sh
bash scripts/verify-backup.sh cloudsite-backup-YYYYMMDD-HHMMSS.tar.gz
```

A complete backup includes consistent SQLite snapshots, `.env`, and site assets. Store backups on another disk or host and protect them as sensitive files.

See [Deployment, upgrade, and backup](deployment-upgrade-backup.md) and [Recovery guide](recovery-guide.md).

## Diagnostics

- `/api/health` reports service status and the 1.0.0 version.
- Download diagnostics validate the AList redirect path.
- The system page reports provider capability and synchronization strategy.
- Security and administration logs should be retained longer than ordinary runtime logs.
