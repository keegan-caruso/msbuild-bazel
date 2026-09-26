using System;
using Hello;

if (Message.Text() != "Hello from MSBuild and Bazel")
{
    Console.Error.WriteLine("Unexpected library message: " + Message.Text());
    return 1;
}
return 0;
