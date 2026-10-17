package com.djigraft.mobile

import android.content.Context
import android.net.Uri
import android.os.SystemClock
import android.text.format.Formatter
import com.arthenica.ffmpegkit.FFmpegKit
import com.arthenica.ffmpegkit.FFmpegSession
import com.arthenica.ffmpegkit.FFmpegSessionCompleteCallback
import com.arthenica.ffmpegkit.Log
import com.arthenica.ffmpegkit.LogCallback
import com.arthenica.ffmpegkit.Statistics
import com.arthenica.ffmpegkit.StatisticsCallback
import com.djigraft.mobile.graft.Mp4Graft
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.io.File
import java.io.FileOutputStream
import java.util.Locale
import kotlin.coroutines.cancellation.CancellationException

object ConversionManager {
    private lateinit var appContext: Context
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val _state = MutableStateFlow<ConversionState>(ConversionState.Idle)
    private var activeJob: Job? = null

    val state: StateFlow<ConversionState> = _state.asStateFlow()

    @Volatile
    var pendingJob: JobSpec? = null

    val workDir: File
        get() = File(
            appContext.getExternalFilesDir(null) ?: appContext.filesDir,
            "work",
        )

    fun init(context: Context) {
        appContext = context.applicationContext
    }

    fun start(spec: JobSpec) {
        if (activeJob?.isActive == true) return
        pendingJob = null
        _state.value = ConversionState.Preparing("正在准备转换…")
        activeJob = scope.launch {
            runJob(spec)
        }
    }

    fun cancel() {
        activeJob?.cancel()
        FFmpegKit.cancel()
    }

    private suspend fun runJob(spec: JobSpec) {
        val results = mutableListOf<ResultItem>()
        val errors = mutableListOf<String>()
        var referenceFile: File? = null

        try {
            _state.value = ConversionState.Preparing("正在准备临时目录…")
            cleanWorkDir()
            val ref = File(workDir, "reference.mp4")
            referenceFile = ref
            _state.value = ConversionState.Preparing("正在导入参考文件…")
            copyUriToFile(spec.reference.uri, ref, spec.reference.size) { copied, total ->
                _state.value = ConversionState.Preparing(
                    "正在导入参考文件 ${formatBytes(copied)} / ${formatBytes(total)}",
                )
            }

            _state.value = ConversionState.Preparing("正在读取参考文件参数…")
            val targets = MediaProbe.readReference(ref.absolutePath)
            val outputTarget = OutputTargetFactory.create(appContext, spec.outputTreeUri)

            spec.inputs.forEachIndexed { index, input ->
                currentCoroutineContext().ensureActive()
                val inputFile = File(workDir, "input_$index.${safeExtension(input.name)}")
                val reencodedFile = File(workDir, "reencoded_$index.mp4")
                val outputFile = File(workDir, "output_$index.mp4")
                try {
                    convertOne(
                        index = index,
                        total = spec.inputs.size,
                        spec = spec,
                        input = input,
                        inputFile = inputFile,
                        reencodedFile = reencodedFile,
                        outputFile = outputFile,
                        referenceFile = ref,
                        targets = targets,
                        outputTarget = outputTarget,
                        results = results,
                    )
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (t: Throwable) {
                    errors += "${input.name}：${t.message ?: "未知错误"}"
                } finally {
                    inputFile.delete()
                    reencodedFile.delete()
                    outputFile.delete()
                }
            }

            when {
                results.isEmpty() && errors.isNotEmpty() -> {
                    _state.value = ConversionState.Failed(
                        "全部文件转换失败：\n" + errors.joinToString("\n"),
                        results,
                    )
                }

                else -> {
                    _state.value = ConversionState.Finished(results, errors)
                }
            }
        } catch (cancelled: CancellationException) {
            _state.value = ConversionState.Cancelled(results)
            throw cancelled
        } catch (t: Throwable) {
            _state.value = ConversionState.Failed(
                t.message ?: "转换失败",
                results,
            )
        } finally {
            referenceFile?.delete()
            cleanWorkDir()
            activeJob = null
        }
    }

    private suspend fun convertOne(
        index: Int,
        total: Int,
        spec: JobSpec,
        input: InputItem,
        inputFile: File,
        reencodedFile: File,
        outputFile: File,
        referenceFile: File,
        targets: RefTargets,
        outputTarget: OutputTarget,
        results: MutableList<ResultItem>,
    ) {
        report(
            index, total, input, Stage.COPY, 0.0,
            "正在导入视频",
        )
        copyUriToFile(input.uri, inputFile, input.size) { copied, known ->
            val fraction = if (known > 0) {
                (copied.toDouble() / known).coerceIn(0.0, 1.0)
            } else {
                0.0
            }
            report(
                index, total, input, Stage.COPY, fraction * 0.15,
                "已导入 ${formatBytes(copied)}" +
                    if (known > 0) " / ${formatBytes(known)}" else "",
            )
        }

        currentCoroutineContext().ensureActive()
        report(index, total, input, Stage.PROBE, 0.16, "正在读取视频参数")
        val inputInfo = MediaProbe.readInput(inputFile.absolutePath)
        val durationMs = inputInfo.durationMs.takeIf { it > 0 } ?: targets.durationMs

        report(
            index, total, input, Stage.TRANSCODE, 0.17,
            "正在转码为 ${targets.width}×${targets.height} · ${MediaProbe.prettyFps(targets.fps)}",
        )
        val command = FfmpegCommand.transcode(
            input = inputFile,
            output = reencodedFile,
            targets = targets,
            inputHasAudio = inputInfo.hasAudio,
            crf = spec.crf,
            maxBitrate = spec.maxBitrateBps,
        )
        runFfmpeg(command, durationMs) { percent, detail ->
            report(
                index, total, input, Stage.TRANSCODE,
                0.17 + 0.68 * (percent / 100.0),
                detail,
            )
        }
        if (!reencodedFile.isFile || reencodedFile.length() < 1024) {
            error("转码输出为空")
        }
        inputFile.delete()

        currentCoroutineContext().ensureActive()
        report(index, total, input, Stage.GRAFT, 0.85, "正在重建 DJI 容器结构")
        Mp4Graft.graft(referenceFile, reencodedFile, outputFile) { copied, graftTotal ->
            val fraction = if (graftTotal > 0) {
                (copied.toDouble() / graftTotal).coerceIn(0.0, 1.0)
            } else {
                0.0
            }
            report(
                index, total, input, Stage.GRAFT,
                0.85 + 0.10 * fraction,
                "已复制 ${formatBytes(copied)} / ${formatBytes(graftTotal)}",
            )
        }
        reencodedFile.delete()

        var number = spec.startNumber + index
        var outputName = fileName(spec.prefix, number)
        while (outputTarget.exists(outputName)) {
            number++
            outputName = fileName(spec.prefix, number)
        }

        currentCoroutineContext().ensureActive()
        report(index, total, input, Stage.EXPORT, 0.95, "正在保存 $outputName")
        val handle = outputTarget.open(outputName)
        try {
            val outputSize = outputFile.length()
            outputFile.inputStream().buffered(1024 * 1024).use { source ->
                val destination = handle.stream
                val buffer = ByteArray(1024 * 1024)
                var copied = 0L
                var lastReported = 0L
                while (true) {
                    currentCoroutineContext().ensureActive()
                    val read = source.read(buffer)
                    if (read < 0) break
                    destination.write(buffer, 0, read)
                    copied += read
                    if (copied - lastReported >= 4L * 1024 * 1024) {
                        val fraction = if (outputSize > 0) {
                            (copied.toDouble() / outputSize).coerceIn(0.0, 1.0)
                        } else {
                            0.0
                        }
                        report(
                            index, total, input, Stage.EXPORT,
                            0.95 + 0.05 * fraction,
                            "正在保存 ${formatBytes(copied)} / ${formatBytes(outputSize)}",
                        )
                        lastReported = copied
                    }
                }
                destination.flush()
            }
            handle.closeSuccess()
        } catch (t: Throwable) {
            handle.abort()
            throw t
        }

        results += ResultItem(
            name = handle.name,
            uri = handle.uri,
            size = outputFile.length(),
            sourceName = input.name,
        )
        outputFile.delete()
        report(index, total, input, Stage.EXPORT, 1.0, "已完成")
    }

    private fun report(
        index: Int,
        total: Int,
        input: InputItem,
        stage: Stage,
        fraction: Double,
        detail: String,
    ) {
        val safeFraction = fraction.coerceIn(0.0, 1.0)
        val overall = ((index + safeFraction) / total * 100.0)
            .toInt()
            .coerceIn(0, 100)
        _state.value = ConversionState.Running(
            fileIndex = index + 1,
            total = total,
            fileName = input.name,
            stage = stage,
            filePercent = (safeFraction * 100).toInt().coerceIn(0, 100),
            overallPercent = overall,
            detail = detail,
        )
    }

    private suspend fun copyUriToFile(
        uri: Uri,
        destination: File,
        knownSize: Long,
        onProgress: (copied: Long, total: Long) -> Unit,
    ) {
        val input = appContext.contentResolver.openInputStream(uri)
            ?: error("无法读取所选文件")
        input.use { source ->
            FileOutputStream(destination).use { output ->
                val buffer = ByteArray(1024 * 1024)
                var copied = 0L
                var lastReported = 0L
                while (true) {
                    currentCoroutineContext().ensureActive()
                    val read = source.read(buffer)
                    if (read < 0) break
                    output.write(buffer, 0, read)
                    copied += read
                    if (copied - lastReported >= 2L * 1024 * 1024 ||
                        (knownSize > 0 && copied >= knownSize)
                    ) {
                        onProgress(copied, knownSize)
                        lastReported = copied
                    }
                }
                output.flush()
                onProgress(copied, knownSize)
            }
        }
    }

    private suspend fun runFfmpeg(
        command: String,
        durationMs: Long,
        onProgress: (percent: Int, detail: String) -> Unit,
    ) {
        val deferred = CompletableDeferred<FFmpegSession>()
        var lastUpdate = 0L
        val statisticsCallback = object : StatisticsCallback {
            override fun apply(statistics: Statistics) {
                val now = SystemClock.elapsedRealtime()
                if (now - lastUpdate < 250L) return
                lastUpdate = now
                val percent = if (durationMs > 0) {
                    ((statistics.time.toDouble() / durationMs) * 100.0)
                        .toInt()
                        .coerceIn(0, 99)
                } else {
                    0
                }
                val speed = runCatching { statistics.speed }.getOrDefault(0.0)
                val detail = if (speed > 0) {
                    String.format(
                        Locale.US,
                        "%.2fx · 已处理 %s",
                        speed,
                        formatDuration(statistics.time.toLong()),
                    )
                } else {
                    "已处理 ${formatDuration(statistics.time.toLong())}"
                }
                onProgress(percent, detail)
            }
        }

        val session = FFmpegKit.executeAsync(
            command,
            object : FFmpegSessionCompleteCallback {
                override fun apply(session: FFmpegSession) {
                    deferred.complete(session)
                }
            },
            object : LogCallback {
                override fun apply(log: Log) = Unit
            },
            statisticsCallback,
        )

        try {
            val completed = deferred.await()
            if (completed.getReturnCode()?.isValueSuccess() != true) {
                val tail = completed.getOutput().orEmpty().trim().takeLast(2600)
                error(
                    "ffmpeg 转码失败" +
                        if (tail.isNotBlank()) {
                            "：\n$tail"
                        } else {
                            "（返回码 ${completed.getReturnCode()?.value}）"
                        },
                )
            }
            onProgress(100, "转码完成")
        } finally {
            if (!deferred.isCompleted) {
                FFmpegKit.cancel()
            }
        }
    }

    private fun cleanWorkDir() {
        runCatching {
            workDir.mkdirs()
            workDir.listFiles()?.forEach { it.deleteRecursively() }
        }
    }

    private fun fileName(prefix: String, number: Int): String {
        val width = maxOf(4, number.toString().length)
        return prefix + number.toString().padStart(width, '0') + ".MP4"
    }

    private fun safeExtension(name: String): String {
        val ext = name.substringAfterLast('.', "").lowercase(Locale.US)
        return if (ext in setOf("mp4", "mov", "mkv", "avi", "m4v", "ts", "wmv", "flv", "webm")) {
            ext
        } else {
            "mp4"
        }
    }

    private fun formatBytes(bytes: Long): String =
        Formatter.formatFileSize(appContext, bytes)

    private fun formatDuration(ms: Long): String {
        val totalSeconds = (ms / 1000).coerceAtLeast(0)
        val hours = totalSeconds / 3600
        val minutes = (totalSeconds % 3600) / 60
        val seconds = totalSeconds % 60
        return if (hours > 0) {
            String.format(Locale.US, "%d:%02d:%02d", hours, minutes, seconds)
        } else {
            String.format(Locale.US, "%02d:%02d", minutes, seconds)
        }
    }
}
