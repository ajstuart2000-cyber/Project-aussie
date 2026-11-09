# Project Aussie

An offline Australian street driving game built with HTML and Three.js and packaged as an Android WebView app (package `com.barrarun.game`).

- `www/` is the game source; `www/index.html` is the source of truth.
- `android/` is the Gradle project. The build copies the whole `www/` folder into `android/app/src/main/assets/` automatically (`syncGameAssets`, run before every variant), so don't edit that folder by hand; it's generated and gitignored. The build fails if `www/index.html` or a required game asset is missing, and after packaging it checks the APK contains them.
- Build: from `android/`, run `gradle assembleDebug` (Gradle 8.7, JDK 17, Android SDK 34 via `ANDROID_HOME` or `local.properties`).
- Installable APKs are attached to the GitHub Releases.
