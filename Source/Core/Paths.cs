using System;
using System.IO;
using System.Text.RegularExpressions;

namespace AudionHubManager.Core;

/// <summary>
/// Where the program lies and what it reads. The window is App\AudionHubManager.exe of a release; a
/// Debug build lies deep under Source\ and finds the program by the console command it must call.
/// Nothing here names a drive.
/// </summary>
public static class Paths
{
    /// <summary>The root of the program: the folder that holds system_core\, config\ and App\.</summary>
    public static string Root { get; } = FindRoot();

    /// <summary>True when the window runs from App\ of the program - a release, or the working copy after a build of the window.</summary>
    public static bool Released { get; } =
        string.Equals(Path.GetFullPath(AppContext.BaseDirectory).TrimEnd('\\'), Path.Combine(Root, "App"), StringComparison.OrdinalIgnoreCase);

    static string FindRoot()
    {
        var folder = new DirectoryInfo(AppContext.BaseDirectory);
        for (var at = folder; at is not null; at = at.Parent)
            if (File.Exists(Path.Combine(at.FullName, "system_core", "cli.py"))) return at.FullName;
        return folder.Parent?.FullName ?? folder.FullName;
    }

    public static string Config => Path.Combine(Root, "config");

    /// <summary>The console command: the wrapper a person types, and the script the window starts itself.</summary>
    public static string DoorName => "hub_cli.cmd";
    public static string Door => Path.Combine(Root, DoorName);
    public static string DoorScript => Path.Combine(Root, "system_core", "cli.py");

    /// <summary>
    /// The PowerShell 7 the program carries, App\AudionPs.exe (Source\Ps): the command line under the journal runs on
    /// it, never on a PowerShell of the machine. "" when App\ is not built yet. A Debug window beside its own build finds
    /// it in App\ of the program as well.
    /// </summary>
    public static string Ps
    {
        get
        {
            foreach (var folder in new[] { AppContext.BaseDirectory, Path.Combine(Root, "App") })
            {
                var path = Path.Combine(folder, "AudionPs.exe");
                if (File.Exists(path)) return path;
            }
            return "";
        }
    }

    /// <summary>The Python of the project; "" when the environment is not built.</summary>
    public static string Python
    {
        get
        {
            foreach (var candidate in new[] { @"runtime\python.exe", @"runtime\python\python.exe" })
            {
                var path = Path.Combine(Root, candidate);
                if (File.Exists(path)) return path;
            }
            return "";
        }
    }

    /// <summary>
    /// What the window keeps for itself between a press and a run - the values of a run, its
    /// outcome, the stop signal - and its own logs. A release keeps them in ._runtime and logs of
    /// the program. A Debug copy keeps them beside itself: a check of the window must not write
    /// over the files a window at work is using.
    /// </summary>
    public static string Runtime => Released ? Path.Combine(Root, "._runtime") : Path.Combine(AppContext.BaseDirectory, "._runtime");
    public static string Logs => Released ? Path.Combine(Root, "logs") : Path.Combine(AppContext.BaseDirectory, "logs");

    /// <summary>The logs folder the buttons open is the program's own, in a release and in a check alike.</summary>
    public static string ProgramLogs => Path.Combine(Root, "logs");

    /// <summary>A path inside the program as a person reads it: from the root of the program.</summary>
    public static string Short(string path)
    {
        try
        {
            var full = Path.GetFullPath(path);
            var root = Root.TrimEnd('\\') + "\\";
            return full.StartsWith(root, StringComparison.OrdinalIgnoreCase) ? full[root.Length..] : full;
        }
        catch { return path; }
    }

    /// <summary>The version of config\version.json, or null when it does not read as one.</summary>
    public static string? Version
    {
        get
        {
            try
            {
                var match = Regex.Match(File.ReadAllText(Path.Combine(Config, "version.json")), "\"version\"\\s*:\\s*\"([^\"]+)\"");
                var candidate = match.Success ? match.Groups[1].Value : "";
                return Regex.IsMatch(candidate, @"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$") ? candidate : null;
            }
            catch { return null; }
        }
    }
}
