package org.opensms.gateway;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.telephony.SmsMessage;

/**
 * Forwards SmsManager sent/delivery broadcasts to a Python listener.
 * python-for-android's generic receiver cannot expose getResultCode(), which is the only way to
 * learn whether the radio accepted the message, hence this small class.
 */
public class SmsResultReceiver extends BroadcastReceiver {
    private static volatile SmsResultListener listener;

    public static void setListener(SmsResultListener l) {
        listener = l;
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        SmsResultListener l = listener;
        if (l == null || intent == null) {
            return;
        }
        int tpStatus = -1;
        try {
            byte[] pdu = intent.getByteArrayExtra("pdu");
            if (pdu != null) {
                SmsMessage m = SmsMessage.createFromPdu(pdu, intent.getStringExtra("format"));
                if (m != null) {
                    tpStatus = m.getStatus();
                }
            }
        } catch (Throwable ignored) {
            // leave tpStatus at -1: the delivery state stays unconfirmed
        }
        try {
            l.onResult(intent.getAction(), intent.getStringExtra("msg_id"),
                    intent.getIntExtra("part", 0), getResultCode(), tpStatus);
        } catch (Throwable ignored) {
            // never crash the process from a receiver
        }
    }
}
