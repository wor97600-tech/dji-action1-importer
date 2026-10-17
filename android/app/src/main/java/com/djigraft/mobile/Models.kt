package com.djigraft.mobile

import android.net.Uri

data class InputItem(
    val uri: Uri,
    val name: String,
    val size: Long,
)

data class JobSpec(
    val reference: InputItem,
    val inputs: List<InputItem>,
    val prefix: String,
    val startNumber: Int,
    val crf: Int,
    val maxBitrateBps: Long?,
    val outputTreeUri: Uri?,
)

data class ResultItem(
    val name: String,
    val uri: Uri,
    val size: Long,
    val sourceName: String,
)

enum class Stage(val label: String) {
    PREPARE("准备"),
    COPY("导入视频"),
    PROBE("读取参数"),
    TRANSCODE("转码"),
    GRAFT("移植容器"),
    EXPORT("保存文件"),
}

sealed interface ConversionState {
    data object Idle : ConversionState

    data class Preparing(val message: String) : ConversionState

    data class Running(
        val fileIndex: Int,
        val total: Int,
        val fileName: String,
        val stage: Stage,
        val filePercent: Int,
        val overallPercent: Int,
        val detail: String = "",
    ) : ConversionState

    data class Finished(
        val results: List<ResultItem>,
        val errors: List<String>,
    ) : ConversionState

    data class Failed(
        val message: String,
        val results: List<ResultItem> = emptyList(),
    ) : ConversionState

    data class Cancelled(
        val results: List<ResultItem> = emptyList(),
    ) : ConversionState
}
