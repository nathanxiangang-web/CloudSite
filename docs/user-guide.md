# CloudSite 1.0.0 User Guide

## Register and sign in

1. Select **Register** in the site header if registration is enabled.
2. Choose a username containing 2-16 letters, numbers, underscores, or hyphens.
3. Set a password and sign in.

The administrator may disable new registrations. Existing accounts can continue to sign in unless they are disabled or deleted.

## Browse and search

- Use the home-page search field to find resources by name or path.
- Filter results by software, image, video, document, or general file.
- Browse category pages and nested folders.
- Open a resource to view metadata, preview support, download controls, and sharing actions.
- Use curated collections to browse resources grouped across folders and content types.

## Favorites and history

- Add or remove a favorite from the resource page.
- Review favorites and browsing history from the account area.
- Remove individual history records or clear the complete history.

Favorites refer to stable resource IDs. A reliably detected rename or move keeps the favorite valid.

## Video playback

CloudSite uses the browser's native media decoder. MP4 with H.264 video and AAC audio is the primary supported format. Some MKV, AVI, HEVC, or provider-specific formats may not play in the browser; use the download option when decoding fails.

Playback progress is saved for signed-in users and can be resumed from the account area.

## Download

Select **Download** on a resource page. CloudSite validates access and returns an HTTP 302 redirect to an AList-native download entry; it does not stream the file body.

The default protection allows five successful download starts per client IP in a sliding 60-second window. A sixth attempt must wait for the returned retry period.

## Share

- Create a share from a resource page.
- Choose a fixed lifetime or a permanent share.
- Use either a four-digit access code or direct-download mode where available.
- Review, copy, update, reset, cancel, or delete your shares under **My shares**.

Share pages are accessible without a CloudSite account, but their scope, expiry, access code, and download limit are enforced by the server.

## Submit a resource suggestion

Signed-in users can open `/submit` to generate a standardized email for the administrator's configured submission address. CloudSite does not accept uploads, connect to SMTP, or grant public users write access to AList.
