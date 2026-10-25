package org.opensms.gateway;

import android.content.Intent;

/** Implemented from Python (pyjnius) to receive PackageInstaller session results. */
public interface InstallResultListener {
    /**
     * @param status        PackageInstaller.STATUS_* value
     * @param message       optional human-readable detail from the system (may be null)
     * @param confirmIntent when status is STATUS_PENDING_USER_ACTION: the system screen to start; otherwise null
     */
    void onResult(int status, String message, Intent confirmIntent);
}
