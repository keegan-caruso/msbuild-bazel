public static class SharedValue {
#if RED
public static string Text => "red:" + CommonValue.Text;
#else
public static string Text => "blue:" + CommonValue.Text;
#endif
}
