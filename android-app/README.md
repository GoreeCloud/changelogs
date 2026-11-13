# GoreeCloud Changelogs — Android Reader (Development)

A **native Android Java/SDK app** for viewing changelogs from the GoreeCloud Changelogs local API. No WebView, SDK analytics, account sync, token storage, or third-party runtime dependencies are used.

## Build

Open `android-app/` in Android Studio with a trusted Gradle 8.9 installation, Android SDK Platform 35, and JDK 17. The project uses Android Gradle Plugin 8.7.3, with compile/target SDK 35 and min SDK 26. A Gradle wrapper binary is deliberately not committed; generate/configure a trusted Gradle wrapper if your environment requires one. The GitHub Actions Android debug build succeeded using Gradle 8.9, Android SDK 35 and JDK 17 ([verification run](https://github.com/GoreeCloud/changelogs/actions/runs/43399191557)); this does not establish emulator or physical-device behavior.

## Connect to the loopback server

On a developer machine with Android Debug Bridge installed and a connected authorized Android device or emulator:

```sh
export GOREE_CHANGELOGS_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
goree-changelogs serve --port 8765
adb reverse tcp:8765 tcp:8765
```

Open the app, paste the **same token** (use a secure local transfer), then tap **Connect / Refresh**. The token remains only in volatile process memory and is cleared on session reset or Activity destruction. The app contacts only `http://127.0.0.1:8765`; network security configuration denies cleartext outside that loopback exception. The app does not connect to the host directly over Wi-Fi or mobile data, and Android's localhost is not the host's localhost without the `adb reverse` mapping.

The current app retrieves up to 40 records per page, with a **Load more** control for bounded pagination (maximum API offset 1,000,000), plus optional product and literal search filters. Request and session generations suppress stale network responses after session reset or later refresh; the bearer token is excluded from activity view-state saving and Android autofill. HTTP redirects are refused to avoid forwarding authorization outside the fixed loopback endpoint. It is deliberately **read-only**. The CLI remains responsible for creating, editing, and deleting entries.

## Limitations and release gates

- Debug/development source only. Hosted CI compiled the Android debug APK; emulator/physical-device behavior, accessibility testing, and a signed release are **not verified**.
- HTTP uses a loopback-only development exception. No LAN exposure, remote tunnel, certificate bypass, or public deployment is authorized.
- Never log/share the API token; do not commit passwords or database exports.
- Before broader use, add GoreeCloud Identity authentication, scoped authorization, HTTPS/private mesh transport, independent security/privacy review, accessible design review, Android build/device CI and an independent session/privacy regression run on an authorized device.
- See the root README for the backend's production-readiness gates.
