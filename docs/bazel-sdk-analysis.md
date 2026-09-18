# SDK declaration investigation

The existing native rules already share the `@dotnet//:files` depset between
build and test. `local_dotnet_sdk` creates one repository BUILD file containing
one glob/filegroup; both native rules consume that provider. The separate
`dotnet` executable label selects the entry executable; it does not enumerate
the SDK again.

The retained integrity-streaming execution logs contain 4,906 distinct SDK/import
file inputs (669,469,503 bytes) in each build and test action. There are no repeated
SDK paths within an action. The diamond build has 4,962 total inputs; Serilog has
5,811 build inputs and 5,359 test inputs. These are source-file dependencies,
not thousands of compilations. Unchanged recovery performs zero compilations.

The build and test actions have different isolated filesystems and must each
receive their declared tools. Sharing a mutable sandbox, referring directly to
an undeclared SDK directory, or dropping files based on the last observed reads
would weaken the current contract. A generated tree artifact could represent the
SDK with fewer configured targets, but would require another staging action and
complete declared source inputs to produce that tree; it does not establish a
free reduction in total work on a fresh consumer.

No SDK representation change is selected. The trace has one SDK package load;
its measured cost is much smaller than the total interval before the first build
action. That interval also includes Bazel initialization, dependency processing
and action setup and must not be labeled pure SDK analysis. The companion
`analysis_profile.py` records package-load count/time, distinct input counts and
a canonical digest of SDK paths and payload digests, asserting build/test equality.
Final repeated measurements are linked from `bazel-materialization.md`.
