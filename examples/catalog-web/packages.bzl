"""Closed package set for net10.0; these package assets have no dependencies."""

load("@rules_msbuild//msbuild:defs.bzl", "msbuild_nuget_package", "msbuild_package_lock")

def catalog_packages():
    msbuild_nuget_package(
        name = "newtonsoft",
        package_id = "Newtonsoft.Json",
        version = "13.0.3",
        archive = "@newtonsoft//file",
        archive_sha256 = "872fc189e638ab1056555b03aaa38f68bcb54286e221aa646eb1129babf63c77",
        content_hash = "mbJSvHfRxfX3tR/U6n1WU+mWHXswYc+SB/hkOpx8yZZe68hNZGfymJu0cjsaJEkVzCMqePiU6LdIyogqfIn7kg==",
    )
    msbuild_nuget_package(
        name = "humanizer",
        package_id = "Humanizer.Core",
        version = "2.14.1",
        archive = "@humanizer//file",
        archive_sha256 = "117be88dd74fbbef492a0386f4d4908144df5aad51a4e630eda7710cf28327aa",
        content_hash = "yzqGU/HKNLZ9Uvr6kvSc3wYV/S5O/IvklIUW5WF7MuivGLY8wS5IZnLPkt7D1KW8Et2Enl0I3Lzg2vGWM24Xsw==",
    )
    msbuild_package_lock(name = "packages", packages = [":newtonsoft", ":humanizer"])
