"""Shared provider contracts."""

MSBuildRestoreInfo = provider("Qualified SDK restore metadata shared by matching projects.", fields = ["file", "framework", "configuration", "executable"])
MSBuildPackageInfo = provider("Locked package extraction and dependency closure.", fields = ["id", "version", "directory", "rows", "files"])
MSBuildPackageLockInfo = provider("Explicit per-project resolved package set.", fields = ["rows", "files"])
MSBuildAssemblyInfo = provider("Reference assembly and separate runtime dependency closure.", fields = ["project", "framework", "reference_framework", "restore_key", "configuration", "properties", "assembly", "output_mode", "identity", "reference", "references", "runtime_references", "runtime", "runtimes", "packages", "package_files", "compile_packages", "runtime_data", "runtime_packages", "target_output", "export_targets", "framework_references", "restore_project", "restore_projects"])
MSBuildItemsInfo = provider("Explicit MSBuild items with declared files and metadata.", fields = ["items", "files", "target_items"])
MSBuildLayoutInfo = provider("A composed artifact tree with explicit destinations.", fields = ["directory"])
MSBuildRuntimeInfo = provider("Runtime host and its complete declared tree.", fields = ["directory", "entry_point", "launch_mode", "runtime_identifier", "version", "environment", "files"])
MSBuildReferencePackInfo = provider("Explicit compile-only framework assemblies.", fields = ["references"])
MSBuildToolInfo = provider("Build-time implementation closure in the execution configuration.", fields = ["project", "entry_point", "directories", "packages", "data", "files", "native", "properties", "layout_prefix"])
MSBuildBindingInfo = provider("Declared task property bound to a tool artifact.", fields = ["tool", "property_name"])
MSBuildTestToolInfo = provider("An explicit entry point or adapter directory in a locked package.", fields = ["directory", "path", "files"])
MSBuildProjectOutputInfo = provider("Selected project assembly consumed as an MSBuild content item.", fields = ["assembly", "item_type", "metadata", "artifact"])
