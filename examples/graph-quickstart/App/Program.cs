using System;
using Hello;

Console.WriteLine(Message.Text());
return Message.Text() == "Hello from MSBuild and Bazel" ? 0 : 1;
