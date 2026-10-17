package com.djigraft.mobile

import com.arthenica.ffmpegkit.FFprobeKit
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale

data class RefTargets(
    val width: Int,
    val height: Int,
    val fps: String,
    val level: Int,
    val sampleRate: Int,
    val channels: Int,
    val videoBitrate: Long,
    val audioBitrate: Long,
    val videoCodec: String,
    val durationMs: Long,
)

data class InputMediaInfo(
    val hasVideo: Boolean,
    val hasAudio: Boolean,
    val durationMs: Long,
)

object MediaProbe {
    fun readReference(path: String): RefTargets {
        val json = probeJson(path)
        val streams = json.optJSONArray("streams") ?: JSONArray()
        val video = firstStream(streams, "video")
            ?: error("参考文件里没有视频轨道，结构可能不是 DJI 原生 MP4")
        val audio = firstStream(streams, "audio")
            ?: error("参考文件里没有音轨。请选择一段相机自己拍摄、带声音的 MP4")
        val format = json.optJSONObject("format")

        val width = video.optInt("width", 0)
        val height = video.optInt("height", 0)
        if (width <= 0 || height <= 0) {
            error("无法读取参考文件的分辨率")
        }

        val fps = video.optString("r_frame_rate")
            .ifBlank { video.optString("avg_frame_rate") }
            .ifBlank { "30000/1001" }
        val level = video.optInt("level", 50).coerceIn(10, 62)
        val videoBitrate = firstPositiveLong(
            video.optString("bit_rate"),
            format?.optString("bit_rate"),
        ) ?: 35_000_000L
        val audioBitrate = firstPositiveLong(audio.optString("bit_rate")) ?: 192_000L
        val sampleRate = audio.optInt("sample_rate", 48_000).coerceIn(8_000, 192_000)
        val channels = audio.optInt("channels", 2).coerceIn(1, 8)
        val durationMs = durationMs(json, video)

        return RefTargets(
            width = width,
            height = height,
            fps = fps,
            level = level,
            sampleRate = sampleRate,
            channels = channels,
            videoBitrate = videoBitrate,
            audioBitrate = audioBitrate,
            videoCodec = video.optString("codec_name"),
            durationMs = durationMs,
        )
    }

    fun readInput(path: String): InputMediaInfo {
        val json = probeJson(path)
        val streams = json.optJSONArray("streams") ?: JSONArray()
        val video = firstStream(streams, "video")
        val audio = firstStream(streams, "audio")
        if (video == null) {
            error("输入文件里没有视频轨道")
        }
        return InputMediaInfo(
            hasVideo = true,
            hasAudio = audio != null,
            durationMs = durationMs(json, video),
        )
    }

    fun prettyFps(fps: String): String {
        val parts = fps.split("/")
        if (parts.size == 2) {
            val num = parts[0].toDoubleOrNull()
            val den = parts[1].toDoubleOrNull()
            if (num != null && den != null && den > 0) {
                val value = num / den
                return if (value % 1.0 == 0.0) {
                    String.format(Locale.US, "%.0f fps", value)
                } else {
                    String.format(Locale.US, "%.2f fps", value)
                }
            }
        }
        return "$fps fps"
    }

    private fun probeJson(path: String): JSONObject {
        val command = "-v error -show_format -show_streams -of json $path"
        val session = FFprobeKit.execute(command)
        if (session.getReturnCode()?.isValueSuccess() != true) {
            val tail = session.getOutput().orEmpty().takeLast(1800)
            error("读取视频参数失败：${tail.ifBlank { "ffprobe 返回错误" }}")
        }
        val output = session.getOutput()?.takeIf { it.isNotBlank() }
            ?: error("ffprobe 没有返回参数")
        return runCatching { JSONObject(output) }
            .getOrElse { error("无法解析视频参数：${it.message}") }
    }

    private fun firstStream(streams: JSONArray, type: String): JSONObject? {
        for (i in 0 until streams.length()) {
            val stream = streams.optJSONObject(i) ?: continue
            if (stream.optString("codec_type") == type) return stream
        }
        return null
    }

    private fun durationMs(json: JSONObject, video: JSONObject?): Long {
        val formatDuration = json.optJSONObject("format")
            ?.optString("duration")
            ?.toDoubleOrNull()
        val streamDuration = video?.optString("duration")?.toDoubleOrNull()
        val seconds = formatDuration ?: streamDuration ?: 0.0
        return if (seconds > 0) (seconds * 1000).toLong() else 0L
    }

    private fun firstPositiveLong(vararg values: String?): Long? {
        for (value in values) {
            val parsed = value?.toLongOrNull() ?: continue
            if (parsed > 0) return parsed
        }
        return null
    }
}
