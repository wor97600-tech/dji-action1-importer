package com.djigraft.mobile

import java.io.File
import java.util.Locale

object FfmpegCommand {
    fun transcode(
        input: File,
        output: File,
        targets: RefTargets,
        inputHasAudio: Boolean,
        crf: Int,
        maxBitrate: Long?,
    ): String {
        val videoBitrate = (maxBitrate ?: targets.videoBitrate).coerceAtLeast(1_000_000L)
        val audioBitrate = maxOf(targets.audioBitrate, 128_000L)
        val channels = targets.channels.coerceIn(1, 8)
        val channelLayout = when (channels) {
            1 -> "mono"
            6 -> "5.1"
            else -> "stereo"
        }
        val level = String.format(Locale.US, "%.1f", targets.level / 10.0)
        val x264Params = "ref=1:bframes=0:b-adapt=0:scenecut=0:cabac=1:aud=0"

        return buildString {
            append("-y -i ").append(quote(input.absolutePath))
            if (!inputHasAudio) {
                append(" -f lavfi -i anullsrc=channel_layout=")
                    .append(channelLayout)
                    .append(":sample_rate=")
                    .append(targets.sampleRate)
            }
            append(" -map 0:v:0")
            if (inputHasAudio) {
                append(" -map 0:a:0?")
            } else {
                append(" -map 1:a:0")
            }
            append(" -sn -dn")
            append(" -vf \"scale=")
                .append(targets.width)
                .append(':')
                .append(targets.height)
                .append(":flags=lanczos,fps=")
                .append(targets.fps)
                .append(",format=yuv420p\"")
            append(" -c:v libx264 -preset fast -profile:v high -level ")
                .append(level)
                .append(" -tag:v avc1 -x264-params ")
                .append(x264Params)
                .append(" -bsf:v filter_units=remove_types=6 -pix_fmt yuv420p")
            append(" -crf ").append(crf)
                .append(" -maxrate ").append(videoBitrate)
                .append(" -bufsize ").append(videoBitrate * 2L)
            append(" -c:a aac -ar ").append(targets.sampleRate)
                .append(" -ac ").append(channels)
                .append(" -b:a ").append(audioBitrate)
            if (!inputHasAudio) {
                append(" -shortest")
            }
            append(" -movflags +faststart ")
            append(quote(output.absolutePath))
        }
    }

    private fun quote(path: String): String = "\"" + path.replace("\"", "\\\"") + "\""
}
