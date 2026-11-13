plugins {
    id("com.android.application")
}
android {
    namespace = "com.goreecloud.changelogs"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.goreecloud.changelogs"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0-dev"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
