plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "io.github.ssh555.financialbeancount"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.ssh555.financialbeancount"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "0.2.0"
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildFeatures {
        buildConfig = true
    }

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

dependencies {
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("androidx.webkit:webkit:1.13.0")
}
