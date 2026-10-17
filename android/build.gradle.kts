import java.net.URL
import java.security.MessageDigest
import java.util.zip.ZipInputStream

plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
}

/*
 * FFmpegKitNext is source-only upstream. This community build contains the
 * arm64-v8a / armeabi-v7a native libraries with libx264 enabled.
 *
 * Keeping the 50 MB archive out of git keeps the repository light. The task
 * below downloads and verifies the exact build once, into android/libs, which
 * is used as a local Maven repository.
 */
val ffmpegKitVersion = "9.0.0"
val ffmpegKitZipUrl =
    "https://github.com/XiaoHao560/ffmpeg-kit-next/releases/download/v9.0.0/ffmpeg-kit-next-maven.zip"
val ffmpegKitZipSha256 =
    "80a59a3a4072b53cc9f1f010ecdcdbec9270358f86c62185b066786c51740d13"
val localMavenDir = layout.projectDirectory.dir("libs")

tasks.register("prepareFfmpegKit") {
    group = "build setup"
    description = "Downloads the GPL FFmpegKitNext Maven archive used by the app."
    outputs.dir(localMavenDir)

    doLast {
        val target = localMavenDir
            .dir("com/arthenica/ffmpeg-kit-next/$ffmpegKitVersion")
            .file("ffmpeg-kit-next-$ffmpegKitVersion.aar")
            .asFile
        if (target.isFile && target.length() > 1_000_000L) {
            logger.lifecycle("FFmpegKitNext already present: ${target.absolutePath}")
            return@doLast
        }

        val archive = File(temporaryDir, "ffmpeg-kit-next-maven.zip")
        logger.lifecycle("Downloading FFmpegKitNext $ffmpegKitVersion ...")
        URL(ffmpegKitZipUrl).openStream().use { input ->
            archive.outputStream().use { output -> input.copyTo(output) }
        }

        val digest = MessageDigest.getInstance("SHA-256")
            .digest(archive.readBytes())
            .joinToString("") { "%02x".format(it) }
        check(digest == ffmpegKitZipSha256) {
            "FFmpegKitNext download checksum mismatch: expected $ffmpegKitZipSha256, got $digest"
        }

        val root = localMavenDir.asFile
        ZipInputStream(archive.inputStream().buffered()).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: break
                val out = File(root, entry.name)
                check(out.canonicalPath.startsWith(root.canonicalPath + File.separator)) {
                    "Unsafe zip entry: ${entry.name}"
                }
                if (entry.isDirectory) {
                    out.mkdirs()
                } else {
                    out.parentFile?.mkdirs()
                    out.outputStream().use { zip.copyTo(it) }
                }
                zip.closeEntry()
            }
        }
        logger.lifecycle("FFmpegKitNext ready: ${target.absolutePath}")
    }
}
