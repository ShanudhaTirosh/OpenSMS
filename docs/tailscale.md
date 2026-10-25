# Tailscale with OpenSMS

## Architecture (and why)
OpenSMS is an Android app that runs its HTTP API **on the phone**. Android lets only one VPN be active, and the
official Tailscale app owns that VPN slot. So OpenSMS uses the **official Tailscale app as the data path** and
only **observes** it:

| OpenSMS does | OpenSMS does not |
|---|---|
| Detect the phone's Tailscale address (a VPN network carrying `100.64.0.0/10` or `fd7a:115c:a1e0::/48`) | Join a tailnet itself, enrol the device, or toggle the tunnel |
| Show state, diagnostics and the endpoint other devices should call | Store, accept or send any Tailscale auth key / API key |
| Let you restrict the API to the tailnet ("listening mode") | Change routes, DNS, firewall rules or the default VPN |
| Open the Tailscale app (or its store page) | Show a peer list (would need a Tailscale API credential on the phone; deliberately not done) |

Versions before this change had an in-app "connect" box that accepted a key or any `100.x.y.z` and reported
"connected" without any tunnel existing. That was removed; a stored key from an older version is deleted on
first start.

## Setup
1. Install the Tailscale app, sign in, connect.
2. Open OpenSMS -> **Mesh**. State should read **Tailscale: connected** with an address like `100.101.2.3`.
3. From another device on your tailnet call `http://100.101.2.3:9292/sms/` with your API key.
4. Optional: set **API listening mode** to **Tailscale only**.

## States
| State | Meaning |
|---|---|
| connected | A VPN network on this phone carries a tailnet address |
| other VPN | A VPN is active but has no tailnet address (Android allows one VPN: it may have replaced Tailscale) |
| not connected | No tailnet address found |
| status unavailable | The OS could not be asked (e.g. permission missing) |

"Connecting" is not shown: without Tailscale's local API there is no reliable signal for it. The **Refresh** button
also runs a TCP self-probe of `address:port`; it shows whether *something on this phone* answers, **not** that a
remote device can reach it (ACLs, the other device's own connection and the phone's power-saving can still block it).

## Listening modes
| Mode | Binds to | Notes |
|---|---|---|
| All networks (default, unchanged) | `0.0.0.0` | Wi-Fi/LAN traffic carries the API token unencrypted |
| Tailscale only | the phone's tailnet IPv4 address | **Fails closed**: if Tailscale is not connected the server does not start and never falls back to other networks. It retries every 10 s, so it starts by itself once Tailscale connects |
| This phone | `127.0.0.1` | Nothing else can reach the API, including over Tailscale |

Switching to a restrictive mode asks for confirmation. **Recovery** if you locked yourself out: open OpenSMS on the
phone and choose *All networks* again; the setting never depends on remote access.

## Security notes
- Tailscale encrypts the tunnel (WireGuard); the API key is still required for every call.
- Use Tailscale ACLs to limit which tailnet devices may reach the phone on the API port.
- Disable Android battery optimisation for both apps, or the OS may stop the tunnel or the gateway.

## Troubleshooting
| Symptom | Check |
|---|---|
| "not connected" but the Tailscale app is on | Another VPN may be active; reopen Tailscale. If Android hides the VPN network, see the device test plan |
| "connected", remote call times out | Server started? Mode compatible (not *This phone*)? Tailscale ACLs? Remote device connected? |
| Server shows an error in *Tailscale only* | Connect Tailscale; the message is `Tailscale-only mode is on but no Tailscale IPv4 address was found` |
| An address `100.64-127.x.y` is reported but you are not on Tailscale | Carriers use the same range (CGNAT). OpenSMS ignores such addresses unless they are on a VPN network; the diagnostics line says so |

## Status of this feature
Unit-tested on Linux (status decision table, bind resolution, fail-closed service logic, real sockets) and rendered
in a headless Kivy/KivyMD session. **Not yet verified on a phone:** the Android `ConnectivityManager` VPN-network query
(`get_vpn_networks`, needs the new `ACCESS_NETWORK_STATE` permission) and the explicit launcher intent for the
Tailscale app. See `docs/device-test-plan.md`, section 4.

## Not implemented (alternatives considered)
- **Embedded Tailscale (`tsnet` / `libtailscale`)** so OpenSMS needs no Tailscale app: not proven for python-for-android
  (Go+NDK cross-build, size, Android network-enumeration limits, API 24 floor). Needs an explicit spike.
- **Tailscale API (peer list)**: would require a credential on the phone; only worth it with a short-lived, narrowly
  scoped token held in memory.
