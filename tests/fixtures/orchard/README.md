# Orchard qualification patch

Apply `deterministic-interceptors.patch` to OrchardCMS/OrchardCore revision
`04467a3438d4255627c1a478598a1585b3ff2947` before the qualification runs.
The upstream interceptor generator calls `Guid.NewGuid()` when naming generated
classes. The patch derives those names from Roslyn's interceptor location data,
so unchanged inputs retain unchanged generated identifiers. This is an explicit
upstream source change, not a rewrite performed by the production adapter.

The Release/Production qualification uses the standard pinned SDK Razor source
generator. Its embedded generated source contains build-worker paths, and its
tag-helper identifiers depend on generated text offsets. DLL/PDB bytes can
therefore differ between clean builds at different paths. Cross-worker cache
recovery must preserve the producer's bytes and run without its source checkout;
byte equality with a separate raw Razor compilation is not an acceptance claim.

Development hot reload and physical-source Razor reload are outside this scope.
