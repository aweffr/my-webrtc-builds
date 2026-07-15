plugins {
    id("com.android.application")
}

android {
    namespace = "dev.aweffr.webrtcsmoke"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.aweffr.webrtcsmoke"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"

        ndk {
            abiFilters += "arm64-v8a"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation(files("libs/webrtc-m150-android-arm64-v8a.aar"))
}
