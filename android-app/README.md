# GoreeCloud Changelogs — Android Reader (Development)

A **native Android Java/SDK app** for viewing changelogs from the GoreeCloud Changelogs local API. No WebView, SDK analytics, account sync, token storage, or third-party runtime dependencies are used.

## Build

Open `android-app/` in Android Studio with a trusted Gradle 8.9 installation, Android SDK Platform 35, and JDK 17. The project uses Android Gradle Plugin 8.7.3, with compile/target SDK 35 and min SDK 26. A Gradle wrapper binary is deliberately not committed; generate/configure a trusted Gradle wrapper if your environment requires one. No Android build or device run is claimed until verified separately.

## Connect to the loopback server

On a developer machine with Android Debug Bridge installed and a connected authorized Android device or emulator:

```sh
export GOREE_CHANGELOGS_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
goree-changelogs serve --port 8765
adb reverse tcp:8765 tcp:8765
```

Open the app, paste the **same token** (use a secure local transfer), then tap **Connect / Refresh**. The token remains only in volatile process memory and is cleared on session reset or Activity destruction. The app contacts only `http://127.0.0.1:8765`; network security configuration denies cleartext outside that loopback exception. The app does not connect to the host directly over Wi-Fi or mobile data, and Android's localhost is not the host's localhost without the `adb reverse` mapping.

The current app retrieves at most 40 records per refresh, with optional product and literal search filters. It is deliberately **read-only**. The CLI remains responsible for creating, editing, and deleting entries.

## Limitations and release gates

- Debug/development source only; Android APK build, emulator/physical-device behavior, Accessibility testing and signed release are **not verified**.
- HTTP uses a loopback-only development exception. No LAN exposure, remote tunnel, certificate bypass, or public deployment is authorized.
- Never log/share the API token; do not commit passwords or database exports.
- Before broader use, add GoreeCloud Identity authentication, scoped authorization, HTTPS/private mesh transport, independent security/privacy review, accessible design review, stable pagination and Android build/device CI.
- See the root README for the backend's production-readiness gates.
