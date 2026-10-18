from pythonforandroid.recipe import RustCompiledComponentsRecipe


class PydanticcoreRecipe(RustCompiledComponentsRecipe):
    version = "2.41.4"
    url = "https://github.com/pydantic/pydantic-core/archive/refs/tags/v{version}.tar.gz"
    site_packages_name = "pydantic_core"

    def get_recipe_env(self, arch, **kwargs):
        env = super().get_recipe_env(arch, **kwargs)
        ndk_api = getattr(self.ctx, "ndk_api", 24) or 24
        env["ANDROID_API_LEVEL"] = str(ndk_api)
        env["ANDROID_MINAPI"] = str(ndk_api)
        return env


recipe = PydanticcoreRecipe()
