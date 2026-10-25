package org.opensms.gateway;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.os.Build;

/**
 * Receives the result of a PackageInstaller session. Needed because the user-confirmation screen must be
 * started from the Intent the system hands back (STATUS_PENDING_USER_ACTION).
 */
public class InstallResultReceiver extends BroadcastReceiver {
    private static volatile InstallResultListener listener;

    public static void setListener(InstallResultListener l) {
        listener = l;
    }

    @Override
    @SuppressWarnings({"deprecation", "unchecked"})
    public void onReceive(Context context, Intent intent) {
        InstallResultListener l = listener;
        if (l == null || intent == null) {
            return;
        }
        try {
            int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
            String message = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
            Intent confirm = null;
            if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
                if (Build.VERSION.SDK_INT >= 33) {
                    confirm = intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent.class);
                } else {
                    confirm = (Intent) intent.getParcelableExtra(Intent.EXTRA_INTENT);
                }
            }
            l.onResult(status, message, confirm);
        } catch (Throwable ignored) {
            // never crash the process from a receiver
        }
    }
}
