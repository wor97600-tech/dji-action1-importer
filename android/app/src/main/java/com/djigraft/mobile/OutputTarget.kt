package com.djigraft.mobile

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.core.content.FileProvider
import androidx.documentfile.provider.DocumentFile
import java.io.File
import java.io.FileOutputStream
import java.io.OutputStream

class OutputHandle(
    val uri: Uri,
    val name: String,
    val stream: OutputStream,
    private val onFinalize: () -> Unit,
    private val onAbort: () -> Unit,
) {
    fun closeSuccess() {
        stream.flush()
        stream.close()
        onFinalize()
    }

    fun abort() {
        runCatching { stream.close() }
        runCatching { onAbort() }
    }
}

interface OutputTarget {
    fun exists(name: String): Boolean
    fun open(name: String): OutputHandle
}

object OutputTargetFactory {
    fun create(context: Context, treeUri: Uri?): OutputTarget {
        if (treeUri != null) {
            val tree = DocumentFile.fromTreeUri(context, treeUri)
                ?: error("无法访问所选择的输出文件夹")
            return SafOutputTarget(context, tree)
        }
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            MediaStoreOutputTarget(context)
        } else {
            LegacyOutputTarget(context)
        }
    }
}

private class SafOutputTarget(
    private val context: Context,
    private val tree: DocumentFile,
) : OutputTarget {
    override fun exists(name: String): Boolean = tree.findFile(name) != null

    override fun open(name: String): OutputHandle {
        val document = tree.createFile("video/mp4", name)
            ?: error("无法在输出文件夹里创建文件")
        val uri = document.uri
        val stream = context.contentResolver.openOutputStream(uri, "w")
            ?: error("无法写入输出文件")
        return OutputHandle(
            uri = uri,
            name = document.name ?: name,
            stream = stream,
            onFinalize = {},
            onAbort = { document.delete() },
        )
    }
}

private class MediaStoreOutputTarget(
    private val context: Context,
) : OutputTarget {
    private val resolver = context.contentResolver
    private val relativePath = Environment.DIRECTORY_DOWNLOADS + "/DJIGraft/"

    override fun exists(name: String): Boolean {
        val projection = arrayOf(MediaStore.MediaColumns._ID)
        val selection =
            "${MediaStore.MediaColumns.RELATIVE_PATH}=? AND ${MediaStore.MediaColumns.DISPLAY_NAME}=?"
        resolver.query(
            MediaStore.Downloads.EXTERNAL_CONTENT_URI,
            projection,
            selection,
            arrayOf(relativePath, name),
            null,
        )?.use { cursor ->
            return cursor.moveToFirst()
        }
        return false
    }

    override fun open(name: String): OutputHandle {
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, name)
            put(MediaStore.MediaColumns.MIME_TYPE, "video/mp4")
            put(MediaStore.MediaColumns.RELATIVE_PATH, relativePath)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI
        val uri = resolver.insert(collection, values)
            ?: error("无法在 Downloads/DJIGraft 里创建文件")
        val stream = resolver.openOutputStream(uri, "w")
        if (stream == null) {
            resolver.delete(uri, null, null)
            error("无法写入 Downloads/DJIGraft")
        }
        return OutputHandle(
            uri = uri,
            name = name,
            stream = stream,
            onFinalize = {
                val done = ContentValues().apply {
                    put(MediaStore.MediaColumns.IS_PENDING, 0)
                }
                resolver.update(uri, done, null, null)
            },
            onAbort = { resolver.delete(uri, null, null) },
        )
    }
}

private class LegacyOutputTarget(
    private val context: Context,
) : OutputTarget {
    private val directory = File(
        context.getExternalFilesDir(Environment.DIRECTORY_MOVIES) ?: context.filesDir,
        "DJIGraft",
    ).apply { mkdirs() }

    override fun exists(name: String): Boolean = File(directory, name).exists()

    override fun open(name: String): OutputHandle {
        val file = File(directory, name)
        val uri = FileProvider.getUriForFile(
            context,
            "${context.packageName}.fileprovider",
            file,
        )
        return OutputHandle(
            uri = uri,
            name = name,
            stream = FileOutputStream(file),
            onFinalize = {},
            onAbort = { file.delete() },
        )
    }
}
