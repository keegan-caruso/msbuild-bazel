# Action identity hardening experiment

Implemented on macOS ARM64; see [findings](action-identity-findings.md).
The following contract was written before implementation.

Before general graph export, measure perturbations beyond C# source edits.
`probe_bazel.py --identity-probe` will extend the existing sandbox/cache matrix:

| Perturbation | Required execution | Observable evidence |
| --- | --- | --- |
| Imported Shared target | Shared + App | Generated Shared value changes |
| Declared Shared data file | Shared + App | Generated Shared value changes |
| Declared build environment | Shared + App | Generated Shared value changes |
| Ambient parent environment | Neither | Output unchanged |
| App restore metadata | App only | Output unchanged; cache key changes |
| Host identity file | Shared + App | Output unchanged; cache key changes |

The copied fixture will import a target that generates C# from a declared data
file and an explicitly supplied environment value. Its generated file belongs
in obj, not in the original fixture or exported source inputs. The input file
must be absent from the App action, which consumes Shared's artifact/result
bundle. This remains a hand-specified two-project contract.

The action must declare the Python executable, core shared library when present,
and standard-library files as tool inputs and use isolated Python startup without
site customization. Invoke Python directly rather than relying on a host shell.
Include explicit host/platform facts in an input file. Disable remote execution
and remote-cache use until the complete native dependency closure is supported.
An SDK tree is already declared. Native libraries outside Python/SDK, package
assets and contents, and deterministic output staging remain separate work.
