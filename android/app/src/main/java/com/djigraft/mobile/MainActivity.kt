package com.djigraft.mobile

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.StatFs
import android.provider.OpenableColumns
import android.text.format.Formatter
import android.view.LayoutInflater
import android.view.View
import android.widget.TextView
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.documentfile.provider.DocumentFile
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.djigraft.mobile.databinding.ActivityMainBinding
import com.djigraft.mobile.databinding.ItemInputBinding
import com.djigraft.mobile.databinding.ItemResultBinding
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private val inputs = mutableListOf<InputItem>()
    private var reference: InputItem? = null
    private var outputTreeUri: Uri? = null
    private var probeJob: Job? = null
    private var converting = false

    private val prefs by lazy {
        getSharedPreferences("djigraft_settings", MODE_PRIVATE)
    }

    private val pickReference = registerForActivityResult(
        ActivityResultContracts.OpenDocument(),
    ) { uri ->
        uri?.let { onReferencePicked(it) }
    }

    private val pickInputs = registerForActivityResult(
        ActivityResultContracts.OpenMultipleDocuments(),
    ) { uris ->
        onInputsPicked(uris)
    }

    private val pickOutput = registerForActivityResult(
        ActivityResultContracts.OpenDocumentTree(),
    ) { uri ->
        uri?.let { onOutputPicked(it) }
    }

    private val notificationPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) {
        ConversionManager.pendingJob?.let { spec -> launchService(spec) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { view, insets ->
            val bars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars() or
                    WindowInsetsCompat.Type.displayCutout(),
            )
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }

        setupSlider()
        restoreSettings()
        renderInputs()
        bindClicks()
        collectState()
    }

    override fun onDestroy() {
        probeJob?.cancel()
        super.onDestroy()
    }

    private fun setupSlider() {
        binding.sliderCrf.apply {
            valueFrom = 16f
            valueTo = 32f
            stepSize = 1f
            value = prefs.getInt("crf", 23).coerceIn(16, 32).toFloat()
            addOnChangeListener { _, value, _ ->
                val crf = value.toInt().coerceIn(16, 32)
                updateCrfLabel(crf)
                prefs.edit().putInt("crf", crf).apply()
            }
        }
        updateCrfLabel(binding.sliderCrf.value.toInt())
    }

    private fun bindClicks() {
        binding.btnPickRef.setOnClickListener {
            pickReference.launch(arrayOf("video/*"))
        }
        binding.btnPickInputs.setOnClickListener {
            pickInputs.launch(arrayOf("video/*"))
        }
        binding.btnClearInputs.setOnClickListener {
            inputs.clear()
            renderInputs()
        }
        binding.btnPickOutput.setOnClickListener {
            pickOutput.launch(null)
        }
        binding.btnResetOutput.setOnClickListener {
            outputTreeUri = null
            prefs.edit().remove("outputTreeUri").apply()
            updateOutputLabel()
        }
        binding.btnStart.setOnClickListener {
            validateAndStart()
        }
        binding.btnCancel.setOnClickListener {
            confirmCancel()
        }
    }

    private fun collectState() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                ConversionManager.state.collect { state ->
                    renderState(state)
                }
            }
        }
    }

    private fun onReferencePicked(uri: Uri) {
        takeReadPermission(uri)
        val item = queryItem(uri)
        reference = item
        binding.txtRef.text = item.name
        binding.txtRefInfo.visibility = View.GONE
        prefs.edit()
            .putString("refUri", uri.toString())
            .putString("refName", item.name)
            .apply()
        probeReference(item)
    }

    private fun probeReference(item: InputItem) {
        probeJob?.cancel()
        probeJob = lifecycleScope.launch {
            val summary = withContext(Dispatchers.IO) {
                readMetadataSummary(item.uri)
            }
            if (reference?.uri == item.uri) {
                binding.txtRefInfo.text = summary
                binding.txtRefInfo.visibility = View.VISIBLE
            }
        }
    }

    private fun readMetadataSummary(uri: Uri): String {
        val retriever = MediaMetadataRetriever()
        return try {
            retriever.setDataSource(this, uri)
            val width = retriever
                .extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)
                ?.toIntOrNull()
            val height = retriever
                .extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)
                ?.toIntOrNull()
            val rotation = retriever
                .extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_ROTATION)
                ?.toIntOrNull()
                ?: 0
            val duration = retriever
                .extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                ?.toLongOrNull()
                ?: 0L
            val hasAudio = retriever
                .extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_AUDIO) == "yes"
            val displayWidth = if (rotation == 90 || rotation == 270) height else width
            val displayHeight = if (rotation == 90 || rotation == 270) width else height
            buildString {
                if (displayWidth != null && displayHeight != null) {
                    append("参考规格：${displayWidth}×${displayHeight}")
                } else {
                    append("已选择参考文件")
                }
                if (duration > 0) append(" · ${formatDuration(duration)}")
                append(if (hasAudio) " · 有音轨" else " · 无音轨（可能无法转换）")
            }
        } catch (_: Throwable) {
            "已选择参考文件，转换时会重新读取参数"
        } finally {
            retriever.release()
        }
    }

    private fun onInputsPicked(uris: List<Uri>) {
        val existing = inputs.mapTo(mutableSetOf()) { it.uri.toString() }
        uris.forEach { uri ->
            if (existing.add(uri.toString())) {
                takeReadPermission(uri)
                inputs += queryItem(uri)
            }
        }
        inputs.sortBy { naturalKey(it.name) }
        renderInputs()
    }

    private fun renderInputs() {
        binding.listInputs.removeAllViews()
        val inflater = LayoutInflater.from(this)
        inputs.forEach { item ->
            val row = ItemInputBinding.inflate(inflater, binding.listInputs, false)
            row.txtInputName.text = item.name
            row.txtInputMeta.text = formatSize(item.size)
            row.btnRemoveInput.setOnClickListener {
                inputs.remove(item)
                renderInputs()
            }
            binding.listInputs.addView(row.root)
        }
        binding.txtInputCount.text = if (inputs.isEmpty()) {
            getString(R.string.inputs_empty)
        } else {
            val total = inputs.sumOf { it.size }
            "已选择 ${inputs.size} 个视频 · 共 ${formatSize(total)}"
        }
        binding.btnClearInputs.isEnabled = inputs.isNotEmpty()
    }

    private fun onOutputPicked(uri: Uri) {
        val document = DocumentFile.fromTreeUri(this, uri)
        if (document == null || !document.canWrite()) {
            Toast.makeText(this, "这个文件夹不可写，请换一个", Toast.LENGTH_LONG).show()
            return
        }
        runCatching {
            contentResolver.takePersistableUriPermission(
                uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION or
                    Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
            )
        }
        outputTreeUri = uri
        prefs.edit().putString("outputTreeUri", uri.toString()).apply()
        updateOutputLabel()
    }

    private fun updateOutputLabel() {
        val uri = outputTreeUri
        binding.txtOutput.text = if (uri == null) {
            getString(R.string.output_default)
        } else {
            val name = DocumentFile.fromTreeUri(this, uri)?.name
                ?: uri.lastPathSegment
                ?: "已选择"
            getString(R.string.output_selected, name)
        }
    }

    private fun restoreSettings() {
        binding.editPrefix.setText(prefs.getString("prefix", "DJI_"))
        binding.editStart.setText(prefs.getString("start", "0900"))
        binding.editMaxBitrate.setText(prefs.getString("maxBitrate", ""))

        val output = prefs.getString("outputTreeUri", null)
        if (output != null) {
            outputTreeUri = Uri.parse(output)
        }
        updateOutputLabel()

        val refUri = prefs.getString("refUri", null)
        if (refUri != null) {
            val item = InputItem(
                uri = Uri.parse(refUri),
                name = prefs.getString("refName", "参考视频.mp4") ?: "参考视频.mp4",
                size = 0L,
            )
            reference = item
            binding.txtRef.text = item.name
            probeReference(item)
        }
    }

    private fun validateAndStart() {
        if (converting) return
        val ref = reference
        if (ref == null) {
            toast("请先选择参考文件")
            return
        }
        if (inputs.isEmpty()) {
            toast("请至少添加一个要导入的视频")
            return
        }

        var prefix = binding.editPrefix.text?.toString()?.trim().orEmpty()
        if (prefix.isEmpty()) prefix = "DJI_"
        prefix = prefix.replace(Regex("[\\\\/:*?\"<>|\\s]"), "_").take(40)
        if (prefix.isEmpty()) prefix = "DJI_"
        binding.editPrefix.setText(prefix)

        val start = binding.editStart.text?.toString()?.trim()?.toIntOrNull()
        if (start == null || start < 0 || start > 999_999) {
            toast("起始编号请输入 0 到 999999 之间的数字")
            return
        }

        val crf = binding.sliderCrf.value.toInt().coerceIn(16, 32)
        val maxBitrateText = binding.editMaxBitrate.text?.toString()?.trim().orEmpty()
        val maxBitrate = if (maxBitrateText.isEmpty()) {
            null
        } else {
            val mbps = maxBitrateText.toDoubleOrNull()
            if (mbps == null || mbps <= 0 || mbps > 300) {
                toast("峰值码率请输入 0 到 300 之间的数字（Mbps）")
                return
            }
            (mbps * 1_000_000.0).toLong()
        }

        prefs.edit()
            .putString("prefix", prefix)
            .putString("start", start.toString().padStart(4, '0'))
            .putString("maxBitrate", maxBitrateText)
            .putInt("crf", crf)
            .apply()

        val spec = JobSpec(
            reference = ref,
            inputs = inputs.toList(),
            prefix = prefix,
            startNumber = start,
            crf = crf,
            maxBitrateBps = maxBitrate,
            outputTreeUri = outputTreeUri,
        )

        val inputsBytes = inputs.sumOf { it.size }
        val estimated = ref.size + inputsBytes * 3L + 150L * 1024 * 1024
        val work = ConversionManager.workDir.apply { mkdirs() }
        val available = runCatching {
            StatFs(work.absolutePath).availableBytes
        }.getOrDefault(Long.MAX_VALUE)
        if (available > 0 && available < estimated) {
            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.space_warning_title)
                .setMessage(
                    getString(
                        R.string.space_warning_message,
                        formatSize(estimated),
                        formatSize(available),
                    ),
                )
                .setPositiveButton(R.string.continue_anyway) { _, _ ->
                    startJob(spec)
                }
                .setNegativeButton(android.R.string.cancel, null)
                .show()
        } else {
            startJob(spec)
        }
    }

    private fun startJob(spec: JobSpec) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            ConversionManager.pendingJob = spec
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
            return
        }
        launchService(spec)
    }

    private fun launchService(spec: JobSpec) {
        ConversionManager.pendingJob = spec
        converting = true
        binding.btnStart.isEnabled = false
        binding.resultCard.visibility = View.GONE
        try {
            val intent = Intent(this, ConversionService::class.java)
                .setAction(ConversionService.ACTION_START)
            ContextCompat.startForegroundService(this, intent)
        } catch (t: Throwable) {
            converting = false
            binding.btnStart.isEnabled = true
            toast("无法启动转换服务：${t.message}")
        }
    }

    private fun renderState(state: ConversionState) {
        when (state) {
            ConversionState.Idle -> {
                converting = false
                binding.progressBox.visibility = View.GONE
                binding.btnStart.isEnabled = true
            }

            is ConversionState.Preparing -> {
                converting = true
                showProgress(indeterminate = true)
                binding.txtProgress.text = "准备中"
                binding.txtStatus.text = state.message
            }

            is ConversionState.Running -> {
                converting = true
                showProgress(indeterminate = false)
                binding.progressBar.progress = state.overallPercent
                binding.txtProgress.text =
                    "${state.overallPercent}% · ${state.fileIndex}/${state.total}"
                binding.txtStatus.text = buildString {
                    append(state.stage.label)
                    append("：")
                    append(state.fileName)
                    if (state.detail.isNotBlank()) {
                        append("\n")
                        append(state.detail)
                    }
                }
            }

            is ConversionState.Finished -> {
                finishUi()
                renderResults(state.results, state.errors)
            }

            is ConversionState.Failed -> {
                finishUi()
                renderResults(state.results, listOf(state.message))
            }

            is ConversionState.Cancelled -> {
                finishUi()
                if (state.results.isNotEmpty()) {
                    renderResults(state.results, emptyList())
                }
                toast(getString(R.string.cancelled_toast))
            }
        }
    }

    private fun showProgress(indeterminate: Boolean) {
        binding.progressBox.visibility = View.VISIBLE
        binding.progressBar.isIndeterminate = indeterminate
        binding.btnStart.isEnabled = false
        binding.btnCancel.visibility = View.VISIBLE
    }

    private fun finishUi() {
        converting = false
        binding.progressBox.visibility = View.GONE
        binding.progressBar.isIndeterminate = false
        binding.btnStart.isEnabled = true
    }

    private fun renderResults(results: List<ResultItem>, errors: List<String>) {
        binding.listResults.removeAllViews()
        val inflater = LayoutInflater.from(this)
        results.forEach { result ->
            val row = ItemResultBinding.inflate(inflater, binding.listResults, false)
            row.txtResultName.text = result.name
            row.txtResultMeta.text =
                "${formatSize(result.size)} · 来自 ${result.sourceName}"
            row.btnOpenResult.setOnClickListener { openResult(result.uri) }
            row.btnShareResult.setOnClickListener { shareResult(result.uri) }
            binding.listResults.addView(row.root)
        }
        errors.forEach { message ->
            val errorView = TextView(this).apply {
                text = "失败：$message"
                setTextColor(ContextCompat.getColor(this@MainActivity, android.R.color.holo_red_dark))
                textSize = 13f
                setPadding(0, 8, 0, 8)
            }
            binding.listResults.addView(errorView)
        }
        binding.resultCard.visibility =
            if (results.isEmpty() && errors.isEmpty()) View.GONE else View.VISIBLE
    }

    private fun openResult(uri: Uri) {
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "video/mp4")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        try {
            startActivity(intent)
        } catch (_: ActivityNotFoundException) {
            toast("没有可播放这个视频的应用")
        }
    }

    private fun shareResult(uri: Uri) {
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "video/mp4"
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        startActivity(Intent.createChooser(intent, getString(R.string.share)))
    }

    private fun confirmCancel() {
        if (!converting) return
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.cancel_confirm_title)
            .setMessage(R.string.cancel_confirm_message)
            .setPositiveButton(R.string.cancel_confirm_yes) { _, _ ->
                ConversionManager.cancel()
            }
            .setNegativeButton(R.string.cancel_confirm_no, null)
            .show()
    }

    private fun updateCrfLabel(value: Int) {
        binding.txtCrf.text = getString(R.string.crf_label, value)
    }

    private fun queryItem(uri: Uri): InputItem {
        var name = uri.lastPathSegment?.substringAfterLast('/') ?: "video.mp4"
        var size = 0L
        runCatching {
            contentResolver.query(
                uri,
                arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE),
                null,
                null,
                null,
            )?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (nameIndex >= 0) {
                        name = cursor.getString(nameIndex) ?: name
                    }
                    val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                    if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) {
                        size = cursor.getLong(sizeIndex)
                    }
                }
            }
        }
        return InputItem(uri, name, size)
    }

    private fun takeReadPermission(uri: Uri) {
        runCatching {
            contentResolver.takePersistableUriPermission(
                uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION,
            )
        }
    }

    private fun naturalKey(name: String): String =
        Regex("(\\d+)").replace(name.lowercase(Locale.US)) {
            it.value.padStart(12, '0')
        }

    private fun formatSize(bytes: Long): String =
        if (bytes > 0) Formatter.formatFileSize(this, bytes) else "大小未知"

    private fun formatDuration(ms: Long): String {
        val totalSeconds = (ms / 1000).coerceAtLeast(0)
        val minutes = totalSeconds / 60
        val seconds = totalSeconds % 60
        return String.format(Locale.US, "%02d:%02d", minutes, seconds)
    }

    private fun toast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }
}
