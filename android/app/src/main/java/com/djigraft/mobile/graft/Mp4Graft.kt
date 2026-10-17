package com.djigraft.mobile.graft

import java.io.BufferedOutputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.min

/**
 * Kotlin port of the desktop project's dji_graft.py.
 *
 * The re-encoded samples are copied into the reference file's container
 * structure. Video/audio sample tables come from the re-encoded file, while
 * track headers (tkhd/mdhd/hdlr), media headers (vmhd/smhd/dinf) and udta/meta
 * data come from the reference file. Chunk offsets are rebuilt for the new
 * mdat layout.
 */
object Mp4Graft {
    private const val COPY_BUFFER = 1024 * 1024
    private const val MAX_META_BYTES = 64L * 1024 * 1024
    private const val U32_MAX = 0xFFFF_FFFFL

    fun graft(
        refFile: File,
        reencodedFile: File,
        outputFile: File,
        onProgress: (copied: Long, total: Long) -> Unit = { _, _ -> },
    ) {
        try {
            RandomAccessFile(refFile, "r").use { ref ->
                RandomAccessFile(reencodedFile, "r").use { re ->
                    val refTop = readBoxesFromFile(ref)
                    val ftyp = refTop.firstOrNull { it.type == "ftyp" }
                        ?: fail("参考文件缺少 ftyp box")
                    val wide = refTop.firstOrNull { it.type == "wide" }
                    val mdat = refTop.firstOrNull { it.type == "mdat" }
                        ?: fail("参考文件缺少 mdat box")
                    val moov = refTop.firstOrNull { it.type == "moov" }
                        ?: fail("参考文件缺少 moov box")

                    val prefix = readFull(ref, ftyp) +
                        (wide?.let { readFull(ref, it) } ?: ByteArray(0))
                    val moovChildren = readBoxes(readPayload(ref, moov))
                    val mvhd = moovChildren.firstOrNull { it.type == "mvhd" }
                        ?: fail("参考文件 moov 里缺少 mvhd")
                    val udta = moovChildren.firstOrNull { it.type == "udta" }?.full
                        ?: ByteArray(0)
                    val refTraks = moovChildren
                        .filter { it.type == "trak" }
                        .map { parseTrak(it) }
                    val videoO = refTraks.firstOrNull { it.handlerType == "vide" }
                        ?: fail("参考文件里没找到 video 轨道")
                    val audioO = refTraks.firstOrNull { it.handlerType == "soun" }
                        ?: fail("参考文件里没找到 audio 轨道")
                    val metaO = refTraks.firstOrNull { it.handlerType == "meta" }

                    val metaSize = metaO?.let { metaSampleSize(it) } ?: 0L
                    if (metaSize > MAX_META_BYTES) {
                        fail("参考文件的 meta 轨道过大（$metaSize 字节），未支持")
                    }
                    val metaBytes = if (metaSize > 0) {
                        readBytes(ref, mdat.payloadStart, metaSize)
                    } else {
                        ByteArray(0)
                    }

                    val reTop = readBoxesFromFile(re)
                    val reMoov = reTop.firstOrNull { it.type == "moov" }
                        ?: fail("转码后文件缺少 moov box")
                    val reTraks = readBoxes(readPayload(re, reMoov))
                        .filter { it.type == "trak" }
                        .map { parseTrak(it) }
                    val videoR = reTraks.firstOrNull { it.handlerType == "vide" }
                        ?: fail("转码后文件缺少 video 轨道")
                    val audioR = reTraks.firstOrNull { it.handlerType == "soun" }
                        ?: fail("转码后文件缺少 audio 轨道（输入视频可能没有音轨）")

                    val videoChunks = computeChunkRanges(videoR.stblChildren, "video")
                    val audioChunks = computeChunkRanges(audioR.stblChildren, "audio")
                    if (videoChunks.isEmpty() || audioChunks.isEmpty()) {
                        fail("转码后文件没有可复制的音视频分块")
                    }

                    val tagged = ArrayList<TaggedChunk>(
                        videoChunks.size + audioChunks.size,
                    )
                    videoChunks.forEachIndexed { index, chunk ->
                        tagged += TaggedChunk(chunk.offset, chunk.size, 'v', index)
                    }
                    audioChunks.forEachIndexed { index, chunk ->
                        tagged += TaggedChunk(chunk.offset, chunk.size, 'a', index)
                    }
                    tagged.sortBy { it.offset }

                    val (vTimescale, vDuration) = readMdhdTimescaleDuration(videoR.mdhd.full)
                    val (aTimescale, aDuration) = readMdhdTimescaleDuration(audioR.mdhd.full)
                    if (vTimescale <= 0 || aTimescale <= 0) {
                        fail("转码后文件的时间刻度无效")
                    }
                    val movieTimescale = readMovieTimescale(mvhd.full)
                    if (movieTimescale <= 0) fail("参考文件的 mvhd 时间刻度无效")

                    val videoDurationMovie = Math.round(
                        vDuration.toDouble() * movieTimescale / vTimescale,
                    )
                    val audioDurationMovie = Math.round(
                        aDuration.toDouble() * movieTimescale / aTimescale,
                    )
                    val overallDuration = maxOf(videoDurationMovie, audioDurationMovie)

                    val newVideoOffsets = LongArray(videoChunks.size)
                    val newAudioOffsets = LongArray(audioChunks.size)
                    val chunkBytes = tagged.sumOf { it.size }
                    val mdatPayloadSize = metaSize + chunkBytes
                    val mdatTotalSize = 8L + mdatPayloadSize
                    val mdatHeaderSize = if (mdatTotalSize < 0x1_0000_0000L) 8 else 16
                    var cursor = prefix.size.toLong() + mdatHeaderSize + metaSize

                    tagged.forEach { chunk ->
                        if (chunk.kind == 'v') {
                            newVideoOffsets[chunk.index] = cursor
                        } else {
                            newAudioOffsets[chunk.index] = cursor
                        }
                        cursor += chunk.size
                    }

                    val videoStco = buildChunkOffsets(
                        originalType = when {
                            videoR.stblChildren.containsKey("co64") -> "co64"
                            else -> "stco"
                        },
                        offsets = newVideoOffsets,
                    )
                    val audioStco = buildChunkOffsets(
                        originalType = when {
                            audioR.stblChildren.containsKey("co64") -> "co64"
                            else -> "stco"
                        },
                        offsets = newAudioOffsets,
                    )

                    val videoStbl = buildStbl(videoR.stblChildren, videoStco, true)
                    val audioStbl = buildStbl(audioR.stblChildren, audioStco, false)
                    val videoMinf = buildMinf(videoO, videoStbl, true)
                    val audioMinf = buildMinf(audioO, audioStbl, false)
                    val videoMdia = buildBox(
                        "mdia",
                        patchMdhd(videoO.mdhd, vDuration) +
                            videoO.hdlr.full +
                            videoMinf,
                    )
                    val audioMdia = buildBox(
                        "mdia",
                        patchMdhd(audioO.mdhd, aDuration) +
                            audioO.hdlr.full +
                            audioMinf,
                    )

                    val videoTrak = buildBox(
                        "trak",
                        patchTkhd(videoO.tkhd, videoDurationMovie) +
                            (videoO.edts?.let { patchElst(it, overallDuration) }
                                ?: ByteArray(0)) +
                            videoMdia,
                    )
                    val audioTrak = buildBox(
                        "trak",
                        patchTkhd(audioO.tkhd, audioDurationMovie) + audioMdia,
                    )
                    val metaTrak = metaO?.trak?.full ?: ByteArray(0)
                    val moovFull = buildBox(
                        "moov",
                        patchMvhd(mvhd, overallDuration) +
                            udta +
                            videoTrak +
                            audioTrak +
                            metaTrak,
                    )

                    BufferedOutputStream(FileOutputStream(outputFile), COPY_BUFFER).use { out ->
                        out.write(prefix)
                        writeMdatHeader(out, mdatTotalSize, mdatPayloadSize)
                        if (metaBytes.isNotEmpty()) out.write(metaBytes)

                        val buffer = ByteArray(COPY_BUFFER)
                        var copied = 0L
                        var lastReported = 0L
                        onProgress(0L, chunkBytes)
                        tagged.forEach { chunk ->
                            re.seek(chunk.offset)
                            var remaining = chunk.size
                            while (remaining > 0) {
                                val wanted = min(buffer.size.toLong(), remaining).toInt()
                                val read = re.read(buffer, 0, wanted)
                                if (read <= 0) {
                                    fail("读取转码文件时提前结束（还差 $remaining 字节）")
                                }
                                out.write(buffer, 0, read)
                                remaining -= read
                                copied += read
                            }
                            if (copied - lastReported >= 4L * 1024 * 1024 ||
                                copied == chunkBytes
                            ) {
                                onProgress(copied, chunkBytes)
                                lastReported = copied
                            }
                        }
                        out.write(moovFull)
                        out.flush()
                        onProgress(chunkBytes, chunkBytes)
                    }
                }
            }
        } catch (t: Throwable) {
            outputFile.delete()
            throw t
        }
    }

    private class Box(
        val type: String,
        val full: ByteArray,
        val headerSize: Int,
    ) {
        val payload: ByteArray by lazy {
            full.copyOfRange(headerSize.coerceAtMost(full.size), full.size)
        }
    }

    private class FileBox(
        val type: String,
        val start: Long,
        val size: Long,
        val headerSize: Int,
    ) {
        val payloadStart: Long get() = start + headerSize
        val payloadEnd: Long get() = start + size
    }

    private class TrakInfo(
        val trak: Box,
        val tkhd: Box,
        val edts: Box?,
        val hdlr: Box,
        val mdhd: Box,
        val minfChildren: Map<String, Box>,
        val stblChildren: Map<String, Box>,
        val handlerType: String,
    )

    private data class ChunkRange(val offset: Long, val size: Long)

    private data class TaggedChunk(
        val offset: Long,
        val size: Long,
        val kind: Char,
        val index: Int,
    )

    private data class StscEntry(
        val firstChunk: Int,
        val samplesPerChunk: Int,
        val sampleDescriptionIndex: Int,
    )

    private data class StszInfo(
        val sampleSize: Long,
        val sizes: LongArray?,
    ) {
        val count: Int
            get() = sizes?.size ?: error("stsz 使用固定 sample size，未记录数量")
    }

    private fun readBoxesFromFile(f: RandomAccessFile): List<FileBox> {
        val result = ArrayList<FileBox>()
        val end = f.length()
        var pos = 0L
        while (pos + 8 <= end) {
            f.seek(pos)
            val header = ByteArray(8)
            f.readFully(header)
            val size32 = u32(header, 0)
            val type = String(header, 4, 4, Charsets.ISO_8859_1)
            var headerSize = 8
            var size = size32
            if (size32 == 1L) {
                val extra = ByteArray(8)
                f.readFully(extra)
                size = u64(extra, 0)
                headerSize = 16
            } else if (size32 == 0L) {
                size = end - pos
            }
            if (size < headerSize || pos + size > end) {
                fail(
                    "box '$type' 大小异常（偏移 $pos，大小 $size，文件 $end 字节）",
                )
            }
            result += FileBox(type, pos, size, headerSize)
            pos += size
        }
        return result
    }

    private fun readBoxes(buf: ByteArray): List<Box> {
        val result = ArrayList<Box>()
        var pos = 0
        while (pos + 8 <= buf.size) {
            val size32 = u32(buf, pos)
            val type = String(buf, pos + 4, 4, Charsets.ISO_8859_1)
            var headerSize = 8
            var size = size32
            if (size32 == 1L) {
                if (pos + 16 > buf.size) break
                size = u64(buf, pos + 8)
                headerSize = 16
            } else if (size32 == 0L) {
                size = (buf.size - pos).toLong()
            }
            if (size < headerSize || pos + size > buf.size) {
                fail(
                    "box '$type' 大小异常（字节缓冲偏移 $pos，大小 $size，缓冲 ${buf.size} 字节）",
                )
            }
            val end = (pos + size).toInt()
            result += Box(type, buf.copyOfRange(pos, end), headerSize)
            pos = end
        }
        return result
    }

    private fun readPayload(f: RandomAccessFile, box: FileBox): ByteArray =
        readBytes(f, box.payloadStart, box.payloadEnd - box.payloadStart)

    private fun readFull(f: RandomAccessFile, box: FileBox): ByteArray =
        readBytes(f, box.start, box.size)

    private fun readBytes(f: RandomAccessFile, start: Long, size: Long): ByteArray {
        if (size < 0 || size > Int.MAX_VALUE) {
            fail("box 太大，无法读入内存（$size 字节）")
        }
        val data = ByteArray(size.toInt())
        f.seek(start)
        f.readFully(data)
        return data
    }

    private fun parseTrak(trak: Box): TrakInfo {
        val children = readBoxes(trak.payload)
        val tkhd = children.firstOrNull { it.type == "tkhd" }
            ?: fail("trak 里缺少 tkhd")
        val edts = children.firstOrNull { it.type == "edts" }
        val mdia = children.firstOrNull { it.type == "mdia" }
            ?: fail("trak 里缺少 mdia")
        val mediaChildren = readBoxes(mdia.payload)
        val hdlr = mediaChildren.firstOrNull { it.type == "hdlr" }
            ?: fail("mdia 里缺少 hdlr")
        val mdhd = mediaChildren.firstOrNull { it.type == "mdhd" }
            ?: fail("mdia 里缺少 mdhd")
        val minf = mediaChildren.firstOrNull { it.type == "minf" }
            ?: fail("mdia 里缺少 minf")
        val minfChildren = readBoxes(minf.payload)
        val stbl = minfChildren.firstOrNull { it.type == "stbl" }
            ?: fail("minf 里缺少 stbl")
        val handlerType = if (hdlr.payload.size >= 12) {
            String(hdlr.payload, 8, 4, Charsets.ISO_8859_1)
        } else {
            ""
        }
        return TrakInfo(
            trak = trak,
            tkhd = tkhd,
            edts = edts,
            hdlr = hdlr,
            mdhd = mdhd,
            minfChildren = minfChildren.associateBy { it.type },
            stblChildren = readBoxes(stbl.payload).associateBy { it.type },
            handlerType = handlerType,
        )
    }

    private fun metaSampleSize(trak: TrakInfo): Long {
        val stsz = trak.stblChildren["stsz"] ?: return 0L
        val info = parseStsz(stsz.payload)
        return if (info.sampleSize != 0L) {
            info.sampleSize * (info.sizes?.size ?: parseSampleCount(stsz.payload))
        } else {
            info.sizes?.sum() ?: 0L
        }
    }

    private fun parseSampleCount(payload: ByteArray): Int {
        if (payload.size < 12) fail("stsz box 太短")
        val count = i32(payload, 8)
        if (count < 0) fail("stsz sample 数量无效")
        return count
    }

    private fun computeChunkRanges(
        stblChildren: Map<String, Box>,
        kind: String,
    ): List<ChunkRange> {
        val offsetBox = stblChildren["co64"] ?: stblChildren["stco"]
            ?: fail("$kind 轨道里没有找到 stco/co64 分块偏移表")
        val offsets = parseChunkOffsets(
            offsetBox.payload,
            is64 = offsetBox.type == "co64",
        )
        val stscBox = stblChildren["stsc"]
            ?: fail("$kind 轨道里没有找到 stsc")
        val stszBox = stblChildren["stsz"]
            ?: fail("$kind 轨道里没有找到 stsz")
        val stsc = parseStsc(stscBox.payload)
        val stsz = parseStsz(stszBox.payload)
        val sampleCount = if (stsz.sampleSize != 0L) {
            parseSampleCount(stszBox.payload)
        } else {
            stsz.sizes?.size ?: 0
        }
        if (offsets.isEmpty()) fail("$kind 轨道的分块偏移表为空")
        if (sampleCount <= 0) fail("$kind 轨道没有 sample")

        val samplesPerChunk = IntArray(offsets.size)
        stsc.forEachIndexed { index, entry ->
            val nextFirst = if (index + 1 < stsc.size) {
                stsc[index + 1].firstChunk
            } else {
                offsets.size + 1
            }
            if (entry.samplesPerChunk <= 0) {
                fail("$kind 轨道的 stsc 条目无效")
            }
            for (chunk in entry.firstChunk until nextFirst) {
                if (chunk in 1..offsets.size) {
                    samplesPerChunk[chunk - 1] = entry.samplesPerChunk
                }
            }
        }
        if (samplesPerChunk.any { it <= 0 }) {
            fail("$kind 轨道的 stsc 没有覆盖全部分块")
        }

        val ranges = ArrayList<ChunkRange>(offsets.size)
        var sampleIndex = 0
        offsets.forEachIndexed { chunkIndex, chunkOffset ->
            val perChunk = samplesPerChunk[chunkIndex]
            if (sampleIndex + perChunk > sampleCount) {
                fail("$kind 轨道的 stsc/stsz sample 数量不匹配")
            }
            var chunkSize = 0L
            repeat(perChunk) {
                chunkSize += if (stsz.sampleSize != 0L) {
                    stsz.sampleSize
                } else {
                    stsz.sizes!![sampleIndex]
                }
                sampleIndex++
            }
            ranges += ChunkRange(chunkOffset, chunkSize)
        }
        if (sampleIndex != sampleCount) {
            fail(
                "$kind 轨道 sample 数量不匹配：stsc 覆盖 $sampleIndex 个，" +
                    "stsz 记录 $sampleCount 个",
            )
        }
        return ranges
    }

    private fun parseChunkOffsets(payload: ByteArray, is64: Boolean): LongArray {
        if (payload.size < 8) fail("stco/co64 box 太短")
        val count = i32(payload, 4)
        if (count < 0) fail("stco/co64 条目数量无效")
        val entrySize = if (is64) 8 else 4
        if (8L + count.toLong() * entrySize > payload.size) {
            fail("stco/co64 条目超出 box 长度")
        }
        val bb = ByteBuffer.wrap(payload).order(ByteOrder.BIG_ENDIAN)
        bb.position(8)
        return LongArray(count) {
            if (is64) bb.long else bb.int.toLong() and U32_MAX
        }
    }

    private fun parseStsc(payload: ByteArray): List<StscEntry> {
        if (payload.size < 8) fail("stsc box 太短")
        val count = i32(payload, 4)
        if (count < 0 || 8L + count.toLong() * 12 > payload.size) {
            fail("stsc 条目数量无效")
        }
        val bb = ByteBuffer.wrap(payload).order(ByteOrder.BIG_ENDIAN)
        bb.position(8)
        return List(count) {
            StscEntry(
                firstChunk = bb.int,
                samplesPerChunk = bb.int,
                sampleDescriptionIndex = bb.int,
            )
        }
    }

    private fun parseStsz(payload: ByteArray): StszInfo {
        if (payload.size < 12) fail("stsz box 太短")
        val sampleSize = i32(payload, 4).toLong() and U32_MAX
        val count = i32(payload, 8)
        if (count < 0) fail("stsz sample 数量无效")
        if (sampleSize != 0L) {
            return StszInfo(sampleSize, null)
        }
        if (12L + count.toLong() * 4 > payload.size) {
            fail("stsz sample 尺寸表超出 box 长度")
        }
        val bb = ByteBuffer.wrap(payload).order(ByteOrder.BIG_ENDIAN)
        bb.position(12)
        return StszInfo(
            sampleSize = 0L,
            sizes = LongArray(count) { bb.int.toLong() and U32_MAX },
        )
    }

    private fun readMdhdTimescaleDuration(mdhdFull: ByteArray): Pair<Long, Long> {
        val p = payloadOf(mdhdFull)
        if (p.size < 20) fail("mdhd box 太短")
        val version = p[0].toInt() and 0xFF
        return if (version == 1) {
            if (p.size < 32) fail("mdhd version 1 box 太短")
            u32(p, 20) to u64(p, 24)
        } else {
            u32(p, 12) to u32(p, 16)
        }
    }

    private fun readMovieTimescale(mvhdFull: ByteArray): Long {
        val p = payloadOf(mvhdFull)
        if (p.size < 20) fail("mvhd box 太短")
        val version = p[0].toInt() and 0xFF
        return if (version == 1) u32(p, 20) else u32(p, 12)
    }

    private fun patchTkhd(tkhd: Box, duration: Long): ByteArray {
        val p = tkhd.payload.copyOf()
        val version = p[0].toInt() and 0xFF
        if (version == 1) {
            putU64(p, 28, duration)
        } else {
            putU32(p, 20, duration)
        }
        return buildBox("tkhd", p)
    }

    private fun patchMdhd(mdhd: Box, duration: Long): ByteArray {
        val p = mdhd.payload.copyOf()
        val version = p[0].toInt() and 0xFF
        if (version == 1) {
            putU64(p, 24, duration)
        } else {
            putU32(p, 16, duration)
        }
        return buildBox("mdhd", p)
    }

    private fun patchMvhd(mvhd: Box, duration: Long): ByteArray {
        val p = mvhd.payload.copyOf()
        val version = p[0].toInt() and 0xFF
        if (version == 1) {
            putU64(p, 24, duration)
        } else {
            putU32(p, 16, duration)
        }
        return buildBox("mvhd", p)
    }

    private fun patchElst(edts: Box, duration: Long): ByteArray {
        val elst = readBoxes(edts.payload).firstOrNull { it.type == "elst" }
            ?: return edts.full
        val p = elst.payload.copyOf()
        if (p.size < 12) return edts.full
        val version = p[0].toInt() and 0xFF
        if (version == 1) {
            putU64(p, 8, duration)
        } else {
            putU32(p, 8, duration)
        }
        return buildBox("edts", buildBox("elst", p))
    }

    private fun buildStbl(
        children: Map<String, Box>,
        chunkOffsets: ByteArray,
        video: Boolean,
    ): ByteArray {
        val stsd = children["stsd"] ?: fail("转码文件 stbl 缺少 stsd")
        val stts = children["stts"] ?: fail("转码文件 stbl 缺少 stts")
        val stsc = children["stsc"] ?: fail("转码文件 stbl 缺少 stsc")
        val stsz = children["stsz"] ?: fail("转码文件 stbl 缺少 stsz")

        val out = ByteArrayOutputStream()
        out.write(stsd.full)
        out.write(stts.full)
        if (video) {
            children["ctts"]?.let { out.write(it.full) }
        }
        out.write(stsc.full)
        out.write(stsz.full)
        out.write(chunkOffsets)
        if (video) {
            children["stss"]?.let { out.write(it.full) }
        }
        return buildBox("stbl", out.toByteArray())
    }

    private fun buildMinf(refTrak: TrakInfo, stbl: ByteArray, video: Boolean): ByteArray {
        val mediaHeaderType = if (video) "vmhd" else "smhd"
        val mediaHeader = refTrak.minfChildren[mediaHeaderType]
            ?: fail("参考文件 $mediaHeaderType 缺失")
        val dinf = refTrak.minfChildren["dinf"]
            ?: fail("参考文件 dinf 缺失")
        return buildBox("minf", mediaHeader.full + dinf.full + stbl)
    }

    private fun buildChunkOffsets(originalType: String, offsets: LongArray): ByteArray {
        val force64 = originalType == "co64" || offsets.any { it > U32_MAX }
        val type = if (force64) "co64" else "stco"
        val entrySize = if (force64) 8 else 4
        val bb = ByteBuffer.allocate(8 + offsets.size * entrySize)
            .order(ByteOrder.BIG_ENDIAN)
        bb.putInt(0)
        bb.putInt(offsets.size)
        offsets.forEach { offset ->
            if (force64) bb.putLong(offset) else bb.putInt(offset.toInt())
        }
        return buildBox(type, bb.array())
    }

    private fun buildBox(type: String, payload: ByteArray): ByteArray {
        val typeBytes = type.toByteArray(Charsets.ISO_8859_1)
        require(typeBytes.size == 4) { "box type must be 4 bytes" }
        val total = 8L + payload.size
        val out = ByteArrayOutputStream(8 + payload.size)
        if (total < 0x1_0000_0000L) {
            val header = ByteBuffer.allocate(8).order(ByteOrder.BIG_ENDIAN)
            header.putInt(total.toInt())
            header.put(typeBytes)
            out.write(header.array())
        } else {
            val header = ByteBuffer.allocate(16).order(ByteOrder.BIG_ENDIAN)
            header.putInt(1)
            header.put(typeBytes)
            header.putLong(total + 8)
            out.write(header.array())
        }
        out.write(payload)
        return out.toByteArray()
    }

    private fun writeMdatHeader(
        out: BufferedOutputStream,
        totalWith8ByteHeader: Long,
        payloadSize: Long,
    ) {
        val header = if (totalWith8ByteHeader < 0x1_0000_0000L) {
            ByteBuffer.allocate(8).order(ByteOrder.BIG_ENDIAN)
                .putInt(totalWith8ByteHeader.toInt())
                .put("mdat".toByteArray(Charsets.ISO_8859_1))
                .array()
        } else {
            ByteBuffer.allocate(16).order(ByteOrder.BIG_ENDIAN)
                .putInt(1)
                .put("mdat".toByteArray(Charsets.ISO_8859_1))
                .putLong(16L + payloadSize)
                .array()
        }
        out.write(header)
    }

    private fun payloadOf(fullBox: ByteArray): ByteArray {
        if (fullBox.size < 8) fail("box 太短")
        val size32 = u32(fullBox, 0)
        val headerSize = if (size32 == 1L) 16 else 8
        if (fullBox.size < headerSize) fail("box 头部不完整")
        return fullBox.copyOfRange(headerSize, fullBox.size)
    }

    private fun u32(b: ByteArray, offset: Int): Long {
        if (offset + 4 > b.size) fail("读取 u32 越界")
        return ((b[offset].toLong() and 0xFF) shl 24) or
            ((b[offset + 1].toLong() and 0xFF) shl 16) or
            ((b[offset + 2].toLong() and 0xFF) shl 8) or
            (b[offset + 3].toLong() and 0xFF)
    }

    private fun i32(b: ByteArray, offset: Int): Int {
        if (offset + 4 > b.size) fail("读取 i32 越界")
        return ((b[offset].toInt() and 0xFF) shl 24) or
            ((b[offset + 1].toInt() and 0xFF) shl 16) or
            ((b[offset + 2].toInt() and 0xFF) shl 8) or
            (b[offset + 3].toInt() and 0xFF)
    }

    private fun u64(b: ByteArray, offset: Int): Long {
        if (offset + 8 > b.size) fail("读取 u64 越界")
        return (u32(b, offset) shl 32) or u32(b, offset + 4)
    }

    private fun putU32(b: ByteArray, offset: Int, value: Long) {
        if (offset + 4 > b.size) fail("写入 u32 越界")
        val v = value.coerceIn(0L, U32_MAX).toInt()
        b[offset] = (v ushr 24).toByte()
        b[offset + 1] = (v ushr 16).toByte()
        b[offset + 2] = (v ushr 8).toByte()
        b[offset + 3] = v.toByte()
    }

    private fun putU64(b: ByteArray, offset: Int, value: Long) {
        if (offset + 8 > b.size) fail("写入 u64 越界")
        val v = value.coerceAtLeast(0L)
        b[offset] = (v ushr 56).toByte()
        b[offset + 1] = (v ushr 48).toByte()
        b[offset + 2] = (v ushr 40).toByte()
        b[offset + 3] = (v ushr 32).toByte()
        b[offset + 4] = (v ushr 24).toByte()
        b[offset + 5] = (v ushr 16).toByte()
        b[offset + 6] = (v ushr 8).toByte()
        b[offset + 7] = v.toByte()
    }

    private fun fail(message: String): Nothing =
        throw IllegalStateException("移植容器失败：$message")
}
