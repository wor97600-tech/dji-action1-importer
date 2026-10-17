package com.djigraft.mobile

import com.djigraft.mobile.graft.Mp4Graft
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.security.MessageDigest

class Mp4GraftTest {
    private lateinit var work: File
    private lateinit var repoRoot: File

    @Before
    fun setUp() {
        work = File(System.getProperty("java.io.tmpdir"), "djigraft-test-${System.nanoTime()}")
        work.mkdirs()
        repoRoot = generateSequence(File(".").canonicalFile) { it.parentFile }
            .firstOrNull { File(it, "dji_graft.py").isFile }
            ?: File("../../").canonicalFile
    }

    @Test
    fun graftMatchesDesktopImplementation() {
        assumeTrue("ffmpeg is required for this test", hasCommand("ffmpeg"))

        val reference = File(work, "reference.mp4")
        val input = File(work, "input.mp4")
        val reencoded = File(work, "reencoded.mp4")
        val expected = File(work, "expected.mp4")
        val actual = File(work, "actual.mp4")

        run(
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            reference.absolutePath,
        )
        run(
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100",
            "-t", "2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            input.absolutePath,
        )
        run(
            "ffmpeg", "-y", "-i", input.absolutePath,
            "-vf", "scale=320:240:flags=lanczos,fps=30,format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-profile:v", "high",
            "-level", "3.0", "-tag:v", "avc1",
            "-x264-params", "ref=1:bframes=0:b-adapt=0:scenecut=0:cabac=1:aud=0",
            "-bsf:v", "filter_units=remove_types=6", "-pix_fmt", "yuv420p",
            "-crf", "23", "-maxrate", "3000000", "-bufsize", "6000000",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k",
            "-movflags", "+faststart",
            reencoded.absolutePath,
        )

        val python = sequenceOf(
            System.getenv("DJIGRAFT_PYTHON"),
            "python3",
            "python",
        ).filterNotNull().firstOrNull { hasCommand(it) }
        if (python != null && File(repoRoot, "dji_graft.py").isFile) {
            val script = """
                import sys
                sys.path.insert(0, sys.argv[1])
                from dji_graft import graft
                graft(sys.argv[2], sys.argv[3], sys.argv[4])
            """.trimIndent()
            run(
                python, "-c", script,
                repoRoot.absolutePath,
                reference.absolutePath,
                reencoded.absolutePath,
                expected.absolutePath,
            )
        }

        Mp4Graft.graft(reference, reencoded, actual)
        assertTrue("Kotlin graft produced no output", actual.length() > 1024)

        if (expected.isFile) {
            assertEquals(
                "Kotlin graft must be byte-identical to dji_graft.py",
                sha256(expected),
                sha256(actual),
            )
        }

        val probe = run(
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            actual.absolutePath,
        )
        assertTrue("output should contain a video stream", probe.contains("video"))
        assertTrue("output should contain an audio stream", probe.contains("audio"))

        run(
            "ffmpeg", "-v", "error", "-i", actual.absolutePath,
            "-f", "null", "-",
        )
    }

    private fun hasCommand(command: String): Boolean =
        runCatching {
            val executable = command.substringAfterLast('/').substringAfterLast('\\')
            val versionArg = if (executable.startsWith("python")) "--version" else "-version"
            val process = ProcessBuilder(command, versionArg)
                .redirectErrorStream(true)
                .start()
            process.inputStream.use { it.readBytes() }
            process.waitFor() == 0
        }.getOrDefault(false)

    private fun run(vararg command: String): String {
        val process = ProcessBuilder(*command)
            .redirectErrorStream(true)
            .start()
        val output = process.inputStream.use { it.readBytes().toString(Charsets.UTF_8) }
        val code = process.waitFor()
        check(code == 0) {
            "Command failed ($code): ${command.joinToString(" ")}\n$output"
        }
        return output
    }

    private fun sha256(file: File): String =
        MessageDigest.getInstance("SHA-256")
            .digest(file.readBytes())
            .joinToString("") { "%02x".format(it) }
}
