using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json.Nodes;
using System.Threading.Tasks;

namespace AudionHubManager.Core;

/// <summary>What the console command answered: its JSON, its exit code, and the command as a person would type it.</summary>
public sealed record HubAnswer(int Code, JsonObject? Json, string Error, string Line)
{
    public bool Ok => Code == 0 && Json is not null;
    /// <summary>The command ran and said a result that is not good (a mirror that differs, a blocked path) - not a failure of the call.</summary>
    public bool Said => Json is not null && Code is 0 or 1;
    public string Text(string key) => Json?[key]?.GetValue<object>()?.ToString() ?? "";
}

/// <summary>
/// The console command of the program, hub_cli.cmd - system_core\cli.py on the Python of the program. The window
/// asks it everything that is Hub Manager's own (the registry, the profile, the mirror, the checks, Forgejo, the
/// lab) and nothing else. Quiet questions - the registry at the start, the profile check of paths - are asked
/// here; what a person pressed runs through the runner and is shown in the terminal (MainWindow.Run.cs).
/// </summary>
public static class Hub
{
    public const int ExitDone = 0, ExitBad = 1, ExitUsage = 2;

    /// <summary>Why the command cannot be called; "" when it can.</summary>
    public static string Trouble =>
        Paths.Python.Length == 0 ? Lang.F("нет Python программы: {0} - соберите окружение (builder_main.cmd)", Path.Combine(Paths.Root, "runtime", "python.exe"))
        : !File.Exists(Paths.DoorScript) ? Lang.F("нет консольной команды: {0}", Paths.DoorScript)
        : "";

    public static bool Ready => Trouble.Length == 0;

    /// <summary>The line a person types for the same thing: hub_cli.cmd and the arguments, quoted where they need it.</summary>
    public static string Line(IEnumerable<string> args) => Paths.DoorName + " " + string.Join(" ", args.Select(Quote));

    public static string Quote(string arg) => arg.Length == 0 ? "\"\"" : arg.IndexOfAny(new[] { ' ', '\t', '"', '&', '|', '<', '>', '^' }) >= 0 ? "\"" + arg.Replace("\"", "\\\"") + "\"" : arg;

    /// <summary>The start of a run of the command: the Python of the program on cli.py, unbuffered, in UTF-8.</summary>
    public static Launch Launch(IEnumerable<string> args)
    {
        var launch = new Launch { Exe = Paths.Python, Folder = Paths.Root };
        launch.Args.Add("-u");
        launch.Args.Add(Paths.DoorScript);
        launch.Args.AddRange(args);
        return launch;
    }

    /// <summary>
    /// Asks the command and reads its one JSON document. The input carries what must not or cannot be an argument: a
    /// token, which goes nowhere else, or the paths of check-paths, too many for one command line.
    /// </summary>
    public static async Task<HubAnswer> Ask(IReadOnlyList<string> args, string? stdin = null, int seconds = 120)
    {
        var line = Line(args);
        if (!Ready) return new HubAnswer(-1, null, Trouble, line);
        var info = new ProcessStartInfo(Paths.Python)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true,
            WorkingDirectory = Paths.Root,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
            // The input is read in UTF-8 (PYTHONUTF8 below): the paths of check-paths --stdin may be Cyrillic.
            StandardInputEncoding = new UTF8Encoding(false),
        };
        info.ArgumentList.Add("-u");
        info.ArgumentList.Add(Paths.DoorScript);
        foreach (var arg in args) info.ArgumentList.Add(arg);
        info.Environment["PYTHONUTF8"] = "1";
        info.Environment["PYTHONIOENCODING"] = "utf-8";
        info.Environment["GIT_TERMINAL_PROMPT"] = "0";
        try
        {
            using var process = Process.Start(info)!;
            ChildJob.Hold(process);
            try
            {
                if (stdin is not null) await process.StandardInput.WriteLineAsync(stdin);
                process.StandardInput.Close();
            }
            catch { }
            var output = process.StandardOutput.ReadToEndAsync();
            var error = process.StandardError.ReadToEndAsync();
            var ended = process.WaitForExitAsync();
            if (await Task.WhenAny(ended, Task.Delay(TimeSpan.FromSeconds(seconds))) != ended)
            {
                try { process.Kill(entireProcessTree: true); } catch { }
                return new HubAnswer(-1, null, Lang.F("консольная команда не ответила за {0} с", seconds), line);
            }
            var text = await output;
            JsonObject? json = null;
            try { json = JsonNode.Parse(text) as JsonObject; } catch { }
            var said = json?["error"]?.ToString() ?? "";
            var err = (await error).Trim();
            return new HubAnswer(process.ExitCode, json, said.Length > 0 ? said : json is null ? (err.Length > 0 ? err : text.Trim()) : "", line);
        }
        catch (Exception ex)
        {
            return new HubAnswer(-1, null, ex.Message, line);
        }
    }

    public static Task<HubAnswer> Ask(params string[] args) => Ask((IReadOnlyList<string>)args);
}
