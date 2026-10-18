"""
OpenSMS - Python-for-Android Patch Helper
Ensures that Rust/Maturin builds (like pydantic-core) receive the correct
ANDROID_API_LEVEL and ANDROID_MINAPI during cross-compilation.
"""
import os
import sys


def patch_p4a(p4a_dir: str):
    recipe_path = os.path.join(p4a_dir, "pythonforandroid", "recipe.py")
    archs_path = os.path.join(p4a_dir, "pythonforandroid", "archs.py")

    if os.path.exists(recipe_path):
        with open(recipe_path, "r", encoding="utf-8") as f:
            content = f.read()
        target = 'env["CARGO_BUILD_TARGET"] = build_target'
        if target in content and 'env["ANDROID_API_LEVEL"]' not in content:
            replacement = (
                'env["CARGO_BUILD_TARGET"] = build_target\n'
                '        env["ANDROID_API_LEVEL"] = str(self.ctx.ndk_api)\n'
                '        env["ANDROID_MINAPI"] = str(self.ctx.ndk_api)'
            )
            content = content.replace(target, replacement)
            with open(recipe_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"[patch_p4a] Patched {recipe_path} with ANDROID_API_LEVEL.")
        else:
            print(f"[patch_p4a] {recipe_path} already patched or target not found.")

    if os.path.exists(archs_path):
        with open(archs_path, "r", encoding="utf-8") as f:
            content = f.read()
        target = "if 'HOME' in environ:\n            env['HOME'] = environ['HOME']"
        if target in content and 'ANDROID_API_LEVEL' not in content:
            replacement = (
                "if 'HOME' in environ:\n            env['HOME'] = environ['HOME']\n"
                "        for var_name in ['ANDROID_API_LEVEL', 'ANDROID_MINAPI', 'ANDROIDAPI', 'ANDROIDMINAPI']:\n"
                "            if var_name in environ:\n"
                "                env[var_name] = environ[var_name]"
            )
            content = content.replace(target, replacement)
            with open(archs_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"[patch_p4a] Patched {archs_path} with ANDROID_API_LEVEL propagation.")
        else:
            print(f"[patch_p4a] {archs_path} already patched or target not found.")


if __name__ == "__main__":
    target_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join("app", ".buildozer", "android", "platform", "python-for-android")
    patch_p4a(target_dir)
