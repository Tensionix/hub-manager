using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;

namespace AudionHubManager.Core;

/// <summary>
/// --self-test: the window was put together (Program.SelfTest); here the parts that need no screen are checked - the
/// console command answers, the canon reads and every operation of it has its words in both languages, every sign the
/// code names is in Icons.cs, the colours of Git are in the theme; with --just-built, the number of the executable is
/// the number of config\version.json. What was checked goes to --to "&lt;file&gt;" for the build to read.
/// </summary>
public static class SelfTest
{
    public static string ReportFile { get; set; } = "";
    public static bool JustBuilt { get; set; }

    public static void Write(string line)
    {
        if (ReportFile.Length == 0) return;
        try { File.AppendAllText(ReportFile, line + Environment.NewLine); } catch { }
    }

    public static bool Run()
    {
        var failed = new List<string>();
        void Check(bool ok, string what)
        {
            Write((ok ? "[OK] " : "[FAIL] ") + what);
            if (!ok) failed.Add(what);
        }
        Check(Hub.Ready, "the console command can be called: " + (Hub.Ready ? Paths.DoorScript : Hub.Trouble));
        if (Hub.Ready)
        {
            // Waited on the pool, not here: this thread is the window's, and the answer would wait for it for ever.
            var trouble = System.Threading.Tasks.Task.Run(Canon.Load).GetAwaiter().GetResult();
            Check(trouble.Length == 0 && Canon.All.Count >= 50, $"the canon of Git reads: {Canon.All.Count} operations {trouble}");
            foreach (var entry in Canon.All)
                Check(entry.WhatRu.Length > 0 && entry.WhatEn.Length > 0 && entry.Display.Length > 0, "the words of " + entry.Id);
            var version = System.Threading.Tasks.Task.Run(() => Hub.Ask("version")).GetAwaiter().GetResult();
            Check(version.Ok, "hub_cli version answers");
        }
        // A typed command asks what its button asks, whatever the order of its flags (TypedCommand).
        foreach (var (shell, line, danger, id) in new (string, string, bool, string?)[]
        {
            ("git", "reset --soft HEAD~1", true, "reset_soft"), ("git", "commit --amend -m x", true, "amend"),
            ("git", "git reset -q --hard HEAD", true, "reset_hard"), ("git", "-C repo reset --hard", true, "reset_hard"),
            ("git", "restore README.md", true, "restore"), ("git", "push -f origin main", true, null), ("git", "clean -fd", true, null),
            ("git", "branch -D topic", true, null), ("git", "stash drop", true, null), ("git", "rebase -i HEAD~3", true, "rebase"),
            ("pwsh", "cd repo; git commit --amend -m x", true, "amend"), ("cmd", "git status && git reset --hard", true, "reset_hard"),
            ("git", "status", false, null), ("git", "restore --staged README.md", false, null), ("git", "reset -- README.md", false, null),
            ("git", "push -u origin main", false, null), ("git", "branch -d topic", false, null), ("git", "commit -m x", false, null),
            ("git", "clean -nd", false, null), ("git", "log --oneline", false, null),
        })
        {
            var costs = TypedCommand.GitCalls(shell, line).Select(TypedCommand.Cost).Where(c => c.Danger).ToList();
            Check(danger ? costs.Count == 1 && costs[0].CanonId == id : costs.Count == 0, $"the line asks for \"{line}\" ({shell}): {(danger ? "yes" : "no")}");
        }
        foreach (var key in new[] { "GitStaged", "GitModified", "GitNew", "GitDeleted", "GitConflict", "GitRenamed", "GitOut", "LaneA", "DiffAddBg", "LogExplain" })
            Check(Avalonia.Application.Current?.TryGetResource(key, Avalonia.Styling.ThemeVariant.Dark, out _) == true, "the theme has " + key);
        if (JustBuilt)
        {
            var built = Assembly.GetEntryAssembly()?.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? "";
            var plus = built.IndexOf('+');
            if (plus >= 0) built = built[..plus];
            Check(built == Paths.Version, $"the executable carries the number of config\\version.json: {built} / {Paths.Version}");
        }
        Write(failed.Count == 0 ? "[OK] all checks passed" : $"[FAIL] {failed.Count} failed");
        return failed.Count == 0;
    }
}
