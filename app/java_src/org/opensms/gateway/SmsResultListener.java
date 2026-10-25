package org.opensms.gateway;

/** Implemented from Python (pyjnius) to receive SMS sent/delivery results. */
public interface SmsResultListener {
    /**
     * @param action     the broadcast action (sent or delivered)
     * @param msgId      OpenSMS message id
     * @param part       zero-based part index
     * @param resultCode BroadcastReceiver result code (Activity.RESULT_OK == -1 means success)
     * @param tpStatus   TP-Status from the delivery report PDU, or -1 when not available
     */
    void onResult(String action, String msgId, int part, int resultCode, int tpStatus);
}
