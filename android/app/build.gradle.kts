plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

val releaseStoreFile = providers.gradleProperty("releaseStoreFile").orNull
val releaseStorePassword = providers.gradleProperty("releaseStorePassword").orNull
val releaseKeyAlias = providers.gradleProperty("releaseKeyAlias").orNull
val releaseKeyPassword = providers.gradleProperty("releaseKeyPassword").orNull
val releaseSigningValues = listOf(
    releaseStoreFile,
    releaseStorePassword,
    releaseKeyAlias,
    releaseKeyPassword,
)
val hasReleaseSigning = releaseSigningValues.all { !it.isNullOrBlank() }

android {
    namespace = "io.github.ssh555.financialbeancount"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.ssh555.financialbeancount"
        minSdk = 24
        targetSdk = 35
        versionCode = providers.gradleProperty("appVersionCode").orNull?.toInt() ?: 1
        versionName = providers.gradleProperty("appVersionName").orNull ?: "0.2.0"
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    signingConfigs {
        create("release") {
            if (hasReleaseSigning) {
                storeFile = file(requireNotNull(releaseStoreFile))
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    buildTypes {
        getByName("release") {
            signingConfig = signingConfigs.getByName("release")
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

}

tasks.register("verifyReleaseSigning") {
    doLast {
        check(hasReleaseSigning) {
            "Release signing properties are required; unsigned Android release builds are forbidden"
        }
        check(file(requireNotNull(releaseStoreFile)).isFile) {
            "Release keystore does not exist"
        }
    }
}

tasks.matching { it.name == "packageRelease" }.configureEach {
    dependsOn("verifyReleaseSigning")
}

chaquopy {
    defaultConfig {
        version = "3.12"
    }
    sourceSets.getByName("main") {
        srcDir(layout.buildDirectory.dir("generated/python"))
    }
}

val syncPythonCore by tasks.registering(Sync::class) {
    from(rootProject.projectDir.parentFile.resolve("beancount_dedup"))
    into(layout.buildDirectory.dir("generated/python/beancount_dedup"))
    exclude("__pycache__/**")
}

tasks.named("preBuild").configure {
    dependsOn(syncPythonCore)
}
tasks.matching { it.name.endsWith("PythonSources") }.configureEach {
    dependsOn(syncPythonCore)
}

dependencies {
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("androidx.documentfile:documentfile:1.1.0")
    implementation("androidx.recyclerview:recyclerview:1.4.0")
    implementation("com.google.android.material:material:1.12.0")
}
