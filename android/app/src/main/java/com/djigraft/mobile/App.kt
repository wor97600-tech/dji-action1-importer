package com.djigraft.mobile

import android.app.Application

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        ConversionManager.init(this)
    }
}
