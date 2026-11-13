# GoreeCloud Changelogs — Android self-hosted preview

The default launcher now uses `HostedActivity`, a **development-only** native HTTPS account-login and read-only history viewer. Enter the HTTPS origin of the Changelogs server on your owned VPS or eventual local server, then sign in with the administrator account bootstrapped on that server. No embedded hostname, development token, account password, analytics service, WebView, persistent credentials, TLS certificate bypass or redirect-following behavior is present. Tokens remain in app memory and are cleared when the user signs out, the server rejects an existing session with HTTP 401, or the Activity is destroyed. Session expiry also clears cached changelog cards, username and product filters from the visible app; a new login is required.

The old loopback-only `MainActivity` source remains as an unlaunched compatibility preview. The default launcher does not require USB or `adb reverse` if a reviewed HTTPS gateway and the central service are available. It is deliberately **not** a stable/signed Android release, nor proof of a deployed identity service. A real-device sign-in, login failure, certificate rejection, rotation/revocation, accessibility and privacy test remains required.

The app clears credentials immediately on sign-out and attempts authenticated HTTPS revocation. If offline, it explicitly reports that server revocation is unconfirmed; the token expires within 12 hours. Avoid signing in on an untrusted device.

Build locally with Android Studio or Gradle `gradle --project-dir android-app :app:assembleDebug`. Minimum API 26, target SDK 35, Java 17. The manifest disallows backup and global cleartext access.
