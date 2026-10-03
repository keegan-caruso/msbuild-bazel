"""Shared provider contracts."""

MSBuildPackageInfo = provider("Locked package extraction and dependency closure.", fields = ["id", "version", "directory", "rows", "files", "archives", "validations"])
MSBuildPackageLockInfo = provider("Pinned NuGet package inventory.", fields = ["rows", "files", "archives", "validations"])
MSBuildLayoutInfo = provider("A composed artifact tree with explicit destinations.", fields = ["directory"])
MSBuildRuntimeInfo = provider("Runtime host and its complete declared tree.", fields = ["directory", "entry_point", "launch_mode", "runtime_identifier", "version", "environment", "files"])
MSBuildToolInfo = provider("Complete build-time layout in the execution configuration.", fields = ["directory", "entry_point", "files"])
MSBuildBindingInfo = provider("Declared task property bound to a tool artifact.", fields = ["tool", "property_name"])
MSBuildTestToolInfo = provider("An explicit entry point or adapter directory in a locked package.", fields = ["directory", "path", "files"])
