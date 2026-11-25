System.Console.WriteLine("SOURCE_SDK_NATIVE_AOT_X64");
System.Console.WriteLine(System.Runtime.InteropServices.RuntimeInformation.ProcessArchitecture);
System.Console.WriteLine("DYNAMIC_CODE=" + System.Runtime.CompilerServices.RuntimeFeature.IsDynamicCodeSupported);
if (System.Runtime.CompilerServices.RuntimeFeature.IsDynamicCodeSupported) return 1;
return 0;
