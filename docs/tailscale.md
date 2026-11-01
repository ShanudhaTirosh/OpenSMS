# Tailscale with OpenSMS

## Two ways to use Tailscale with OpenSMS

| | **Built-in Tailscale** (experimental) | **Tailscale app** (the original way) |
|---|---|---|
| What it is | The app joins your tailnet **itself**, inside the background service, using Tailscale's embeddable library | The official Tailscale app owns the phone's VPN; OpenSMS only observes it |
| Needs the Tailscale app on the phone | **No** | Yes |
| VPN permission / full-device VPN | **None** (app-only networking, no routes or DNS changed) | Yes (the Tailscale app's VPN) |
| Credential | An **auth key** (`tskey-auth-...`) or an **API access token** (`tskey-api-...`, used once to create a single-use key); never stored | You sign in inside the Tailscale app |
| Reachable from | Any device on your tailnet, at the phone's own tailnet address | Same |
| Status | **Experimental**: built from Tailscale's `libtailscale` in CI; never run on a phone yet | Supported; Android detection device-untested |

They can coexist: the built-in node is a separate device in your tailnet with its own address.

## Built-in Tailscale (experimental)

```
other tailnet device --WireGuard--> [phone: built-in node :PORT] --> 127.0.0.1:PORT (the OpenSMS API, key required)
```
1. Mesh screen > **Built-in Tailscale**. Paste an **auth key** (Tailscale admin console > Settings > Keys > *Generate auth key*;
   choose single-use, pre-approved, short expiry) **or an API access token** (*Generate access token*): the token is used once to
   create a single-use auth key valid for 10 minutes and is not kept. Optionally set a device name and, for Headscale, a control server URL.
2. Tap **Connect**. State goes *connecting* -> **connected**, showing the device name, its tailnet address, and the **other devices on
   your tailnet** (online first).
3. From any tailnet device: `http://<that address>:9292/sms/` with your API key. **Copy Remote URL** uses the built-in address.
4. After the first connection the node's identity is stored in the app's private storage, so a restart or reboot needs **no key**:
   the saved choice (*connected*) is restored by the background service. **Disconnect** keeps the identity; **Forget** deletes it
   (also remove the device in the Tailscale admin console).

What it is **not**: not a VPN (other apps on the phone are unaffected), not an exit node or subnet router, and MagicDNS names are
resolved by Tailscale for *incoming* connections only. "Tailscale only" listening mode simply means "loopback only" while the built-in
node is connected, because all tailnet traffic arrives through the node's forwarder.

### Credentials and safety
- The key is handed from the app to the service through a private one-shot file (mode `0600`), overwritten with zeros and deleted as
  soon as it is read. It never appears in `request.json`, status files, logs or the diagnostics report (key-shaped text is redacted
  everywhere, including the engine log).
- An API token is only used to call `https://api.tailscale.com/api/v2/tailnet/-/keys` once. Prefer a short-lived token with only the
  permission to create auth keys.
- The node's private identity lives in `config/tsnet/` (app-private, excluded from backups). Anyone who can copy it can impersonate the device
  until you remove it in the admin console.
- **Crash guard:** if the background service ends unexpectedly while the engine is active three times within 30 minutes, the engine
  stays off until you press Connect, so a native crash can never become a restart loop.
- Use Tailscale ACLs to limit which devices may reach the phone, and keep API keys scoped (`sms:write`, `sms:read`).

### Why it is experimental
The engine is Tailscale's own `libtailscale` compiled with Go and the Android NDK by the CI workflows (`tools/build_libtailscale.py`;
pinned commit, header compared with `app/native/tailscale.h`). What has and has not been verified:
- Verified here: the Python binding against the real header, the controller, forwarder, key handling and service integration against a faithful stand-in
  of the C library (including 3 MB simultaneous transfers and the whole connect / resume / forget lifecycle), on Python 3.11 and 3.12.
- Verified by CI **only once it runs on your repository**: the real library on Linux against Tailscale's own test control server
  (`tests/test_ts_real_lib.py`, job *native-tailscale*).
- **Not verified**: that the Go library builds for Android in your CI, loads on your phone, and works with Android's networking restrictions
  (Android 11+ limits network-interface enumeration, which Tailscale's engine uses for path discovery; it may connect only through relays, with
  higher latency). `docs/device-test-plan.md` section 8 lists the checks.
- Cost: roughly 15-30 MB more APK size per ABI and some extra memory in the service.
- If the engine is missing from a build, the card says so and everything else works unchanged.

## Using the Tailscale app instead (original way)
OpenSMS is an Android app that runs its HTTP API **on the phone**. Android lets only one VPN be active, and the
official Tailscale app owns that VPN slot. In this mode OpenSMS uses the **official Tailscale app as the data path** and
only **observes** it:

| OpenSMS does | OpenSMS does not |
|---|---|
| Detect the phone's Tailscale address (a VPN network carrying `100.64.0.0/10` or `fd7a:115c:a1e0::/48`) | Join a tailnet itself, enrol the device, or toggle the tunnel (use the built-in node for that) |
| Show state, diagnostics and the endpoint other devices should call | Store, accept or send any Tailscale key in this mode |
| Let you restrict the API to the tailnet ("listening mode") | Change routes, DNS, firewall rules or the default VPN |
| Open the Tailscale app (or its store page) | Show a peer list in this mode (the built-in node shows one) |

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

## Not implemented
- **Tailscale API peer list in the Tailscale-app mode**: would need a credential on the phone; the built-in node already lists peers.
- **Exit node / subnet routing / Funnel** through the built-in node: out of scope.
