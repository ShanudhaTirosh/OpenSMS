# Native code

`tailscale.h` and `LICENSE.libtailscale` are copied unmodified from
https://github.com/tailscale/libtailscale at commit `d1dc45d039edb7759ecbee6ba2aea0c4bca884b8`
(BSD 3-Clause). The header is the contract that `app/services/tsNative.py` binds to; a test compares every declared
function and its argument count, and CI compares the file with the pinned checkout so it cannot drift silently.

`libtailscale.so` itself is **not** committed. `tools/build_libtailscale.py` builds it for `arm64-v8a` and `armeabi-v7a` in CI
(Go + the Android NDK) into `app/native/<abi>/`, and only then enables `android.add_libs_*` in the build spec.
