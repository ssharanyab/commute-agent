import java.util.Properties

plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

/**
 * Maps SDK key resolution (never logged):
 * 1) android/local.properties → GOOGLE_MAPS_API_KEY  (preferred for local Android)
 * 2) process env GOOGLE_MAPS_API_KEY
 * 3) repo-root .env GOOGLE_MAPS_API_KEY (gitignored; optional convenience)
 */
fun loadGoogleMapsApiKey(): String {
    val localProperties = Properties()
    val localPropertiesFile = rootProject.file("local.properties")
    if (localPropertiesFile.exists()) {
        localPropertiesFile.inputStream().use { localProperties.load(it) }
    }
    val fromLocal = localProperties.getProperty("GOOGLE_MAPS_API_KEY")?.trim().orEmpty()
    if (fromLocal.isNotEmpty()) return fromLocal

    val fromEnv = System.getenv("GOOGLE_MAPS_API_KEY")?.trim().orEmpty()
    if (fromEnv.isNotEmpty()) return fromEnv

    // android/ → src/app/ → commute-agent/
    val repoEnv = rootProject.projectDir.parentFile?.parentFile?.resolve(".env")
    if (repoEnv != null && repoEnv.isFile) {
        for (raw in repoEnv.readLines()) {
            val line = raw.trim()
            if (line.isEmpty() || line.startsWith("#") || !line.contains("=")) continue
            val idx = line.indexOf('=')
            val key = line.substring(0, idx).trim()
            if (key != "GOOGLE_MAPS_API_KEY") continue
            var value = line.substring(idx + 1).trim()
            if ((value.startsWith("\"") && value.endsWith("\"")) ||
                (value.startsWith("'") && value.endsWith("'"))
            ) {
                value = value.substring(1, value.length - 1)
            }
            if (value.isNotEmpty()) return value
        }
    }
    return ""
}

val mapsApiKey: String = loadGoogleMapsApiKey()
if (mapsApiKey.isEmpty()) {
    logger.warn(
        "GOOGLE_MAPS_API_KEY is empty. GoogleMap tiles will not render on Android. " +
            "Add to android/local.properties: GOOGLE_MAPS_API_KEY=your_key " +
            "(Maps SDK for Android must be enabled for this key)."
    )
} else {
    logger.lifecycle(
        "GOOGLE_MAPS_API_KEY loaded for Android Maps SDK (length=${mapsApiKey.length}; value not printed)."
    )
}

android {
    namespace = "com.patchamomma.commute_agent"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_11.toString()
    }

    defaultConfig {
        applicationId = "com.patchamomma.commute_agent"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        // Injected into AndroidManifest.xml as ${GOOGLE_MAPS_API_KEY}
        manifestPlaceholders["GOOGLE_MAPS_API_KEY"] = mapsApiKey
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

flutter {
    source = "../.."
}
