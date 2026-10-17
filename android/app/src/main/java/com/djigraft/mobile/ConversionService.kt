package com.djigraft.mobile

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

class ConversionService : LifecycleService() {
    companion object {
        const val ACTION_START = "com.djigraft.mobile.action.START"
        const val ACTION_CANCEL = "com.djigraft.mobile.action.CANCEL"
        private const val CHANNEL_ID = "conversion"
        private const val NOTIFICATION_ID = 1001
    }

    private var finishHandled = false
    private var jobStarted = false

    override fun onCreate() {
        super.onCreate()
        createChannel()
        lifecycleScope.launch {
            ConversionManager.state.collectLatest { state ->
                updateNotification(state)
                if (jobStarted &&
                    (state is ConversionState.Finished ||
                    state is ConversionState.Failed ||
                    state is ConversionState.Cancelled)
                ) {
                    if (!finishHandled) {
                        finishHandled = true
                        stopForeground(STOP_FOREGROUND_DETACH)
                        stopSelf()
                    }
                }
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        when (intent?.action) {
            ACTION_START -> {
                jobStarted = true
                startForeground(
                    NOTIFICATION_ID,
                    buildNotification(
                        ConversionState.Preparing(
                            getString(R.string.notification_preparing),
                        ),
                    ),
                )
                ConversionManager.pendingJob?.let { ConversionManager.start(it) }
            }

            ACTION_CANCEL -> ConversionManager.cancel()
        }
        return START_NOT_STICKY
    }

    private fun updateNotification(state: ConversionState) {
        if (state is ConversionState.Idle) return
        val manager = NotificationManagerCompat.from(this)
        runCatching {
            manager.notify(NOTIFICATION_ID, buildNotification(state))
        }
    }

    private fun buildNotification(state: ConversionState): Notification {
        val builder = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(getString(R.string.notification_title))
            .setContentIntent(mainActivityIntent())
            .setOnlyAlertOnce(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)

        when (state) {
            is ConversionState.Preparing -> {
                builder.setContentText(state.message)
                    .setProgress(0, 0, true)
                    .setOngoing(true)
            }

            is ConversionState.Running -> {
                builder.setContentText(
                    "${state.fileIndex}/${state.total} · ${state.stage.label} · ${state.fileName}",
                )
                    .setSubText("${state.overallPercent}%")
                    .setProgress(100, state.overallPercent, false)
                    .setOngoing(true)
                    .addAction(0, getString(R.string.cancel), cancelServiceIntent())
            }

            is ConversionState.Finished -> {
                val text = getString(R.string.notification_finished) +
                    "（${state.results.size} 个文件" +
                    if (state.errors.isNotEmpty()) "，${state.errors.size} 个失败）" else "）"
                builder.setContentText(text)
                    .setOngoing(false)
                    .setAutoCancel(true)
            }

            is ConversionState.Failed -> {
                builder.setContentText(state.message.take(120))
                    .setOngoing(false)
                    .setAutoCancel(true)
            }

            is ConversionState.Cancelled -> {
                builder.setContentText(getString(R.string.notification_cancelled))
                    .setOngoing(false)
                    .setAutoCancel(true)
            }

            ConversionState.Idle -> Unit
        }
        return builder.build()
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)
            val channel = NotificationChannel(
                CHANNEL_ID,
                getString(R.string.notification_channel),
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = getString(R.string.app_name)
                setShowBadge(false)
            }
            manager.createNotificationChannel(channel)
        }
    }

    private fun mainActivityIntent(): PendingIntent =
        PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

    private fun cancelServiceIntent(): PendingIntent =
        PendingIntent.getService(
            this,
            1,
            Intent(this, ConversionService::class.java).setAction(ACTION_CANCEL),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
}
