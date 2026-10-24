using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace AudionHubManager.Core;

/// <summary>What git answered to a question of the window.</summary>
public sealed record GitAnswer(int Code, string Out, string Err)
{
    public bool Ok => Code == 0;
}

/// <summary>One file of `git status`: where it stands in the three places of Git.</summary>
public sealed class GitFile
{
    public string Path { get; init; } = "";
    /// <summary>The path before a rename, or "".</summary>
    public string From { get; init; } = "";
    /// <summary>The letter of the index and of the working folder, as porcelain gives them ('.' - nothing).</summary>
    public char Index { get; init; } = '.';
    public char Work { get; init; } = '.';
    public bool Untracked { get; init; }
    public bool Conflict { get; init; }
    public int Added { get; set; } = -1;
    public int Removed { get; set; } = -1;

    public bool Staged => !Untracked && !Conflict && Index != '.';
    public bool Unstaged => Untracked || (!Conflict && Work != '.');

    /// <summary>The one letter the panel shows: U conflict, ? new, then the working folder, then the index.</summary>
    public char Letter => Conflict ? 'U' : Untracked ? '?' : Work != '.' ? Work : Index;
}

/// <summary>The state of a repository: its branch, its distance from the server, its files.</summary>
public sealed class GitState
{
    public string Root { get; init; } = "";
    public string Branch { get; set; } = "";
    public string Head { get; set; } = "";
    public string Upstream { get; set; } = "";
    public int Ahead { get; set; }
    public int Behind { get; set; }
    public bool Detached { get; set; }
    public bool NoCommits { get; set; }
    public List<GitFile> Files { get; } = new();
    /// <summary>"merge", "cherry-pick", "revert", "rebase" while one goes; "" otherwise.</summary>
    public string Underway { get; set; } = "";

    public int StagedCount => Files.Count(f => f.Staged);
    public int ChangedCount => Files.Count(f => !f.Untracked && !f.Conflict && f.Work != '.');
    public int NewCount => Files.Count(f => f.Untracked);
    public int ConflictCount => Files.Count(f => f.Conflict);
}

/// <summary>One commit of the history, with what the graph needs.</summary>
public sealed class GitCommit
{
    public string Hash { get; init; } = "";
    public string[] Parents { get; init; } = Array.Empty<string>();
    public string Refs { get; init; } = "";
    public string Author { get; init; } = "";
    public string Mail { get; init; } = "";
    public DateTime When { get; init; }
    public string Subject { get; init; } = "";
    public string Short => Hash.Length > 7 ? Hash[..7] : Hash;
    /// <summary>The lane of the graph the commit stands in, and the lanes that pass its row (Views\GraphView.cs).</summary>
    public int Lane { get; set; }
}

/// <summary>A branch, local or of a remote, or a tag.</summary>
public sealed class GitRef
{
    public string Kind { get; init; } = "";      // "local", "remote", "tag"
    public string Name { get; init; } = "";
    public string Upstream { get; init; } = "";
    public string Track { get; init; } = "";     // "[ahead 2, behind 1]", "[gone]" or ""
    public string Hash { get; init; } = "";
    public DateTime When { get; init; }
    public string Subject { get; init; } = "";
    public int Ahead { get; set; }
    public int Behind { get; set; }
}

/// <summary>
/// The questions the window asks git to draw itself: the state, the history, the branches, the remotes. They are not
/// the lesson and do not go into the terminal; what a button runs does (MainWindow.Run.cs). The answers are read in
/// machine forms - porcelain, -z, fields cut by control characters - never parsed from the words git says to people.
/// </summary>
public static class Git
{
    public static string Exe { get; set; } = "git";

    /// <summary>Asks git, in the root of a repository. A git that does not start, or does not answer in time, is a failed answer.</summary>
    public static async Task<GitAnswer> Ask(string root, params string[] args)
    {
        var info = new ProcessStartInfo(Exe)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true,
            WorkingDirectory = root,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        // Paths as they are, never as \320\260 escapes; no pager, no prompt for a password.
        foreach (var arg in new[] { "-c", "core.quotepath=false", "--no-pager" }.Concat(args)) info.ArgumentList.Add(arg);
        info.Environment["GIT_TERMINAL_PROMPT"] = "0";
        info.Environment["GIT_OPTIONAL_LOCKS"] = "0";
        info.Environment["LC_ALL"] = "C";
        try
        {
            using var process = Process.Start(info)!;
            try { process.StandardInput.Close(); } catch { }
            var output = process.StandardOutput.ReadToEndAsync();
            var error = process.StandardError.ReadToEndAsync();
            var ended = process.WaitForExitAsync();
            if (await Task.WhenAny(ended, Task.Delay(TimeSpan.FromSeconds(30))) != ended)
            {
                try { process.Kill(entireProcessTree: true); } catch { }
                return new GitAnswer(-1, "", "git did not answer in 30 s");
            }
            return new GitAnswer(process.ExitCode, await output, await error);
        }
        catch (Exception ex)
        {
            return new GitAnswer(-1, "", ex.Message);
        }
    }

    /// <summary>Is this folder a repository of its own: "own", "parent" (inside someone else's), "none".</summary>
    public static async Task<(string Kind, string Top)> Kind(string folder)
    {
        if (!Directory.Exists(folder)) return ("missing", "");
        if (Directory.Exists(Path.Combine(folder, ".git")) || File.Exists(Path.Combine(folder, ".git"))) return ("own", folder);
        var answer = await Ask(folder, "rev-parse", "--show-toplevel");
        return answer.Ok && answer.Out.Trim().Length > 0 ? ("parent", Path.GetFullPath(answer.Out.Trim())) : ("none", "");
    }

    /// <summary>`git status --porcelain=v2 --branch -z --untracked-files=all`, with the lines added and removed of every file.</summary>
    public static async Task<GitState?> Status(string root)
    {
        var answer = await Ask(root, "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all");
        if (!answer.Ok) return null;
        var state = new GitState { Root = root };
        var parts = answer.Out.Split('\0');
        for (int i = 0; i < parts.Length; i++)
        {
            var line = parts[i];
            if (line.Length == 0) continue;
            if (line.StartsWith("# branch.oid ", StringComparison.Ordinal))
            {
                state.Head = line[13..];
                state.NoCommits = state.Head == "(initial)";
            }
            else if (line.StartsWith("# branch.head ", StringComparison.Ordinal))
            {
                state.Branch = line[14..];
                state.Detached = state.Branch == "(detached)";
            }
            else if (line.StartsWith("# branch.upstream ", StringComparison.Ordinal)) state.Upstream = line[18..];
            else if (line.StartsWith("# branch.ab ", StringComparison.Ordinal))
            {
                var ab = line[12..].Split(' ');
                if (ab.Length == 2)
                {
                    int.TryParse(ab[0].TrimStart('+'), out var ahead);
                    int.TryParse(ab[1].TrimStart('-'), out var behind);
                    state.Ahead = ahead;
                    state.Behind = behind;
                }
            }
            else if (line[0] == '1' || line[0] == '2')
            {
                // 1 XY sub mH mI mW hH hI path / 2 XY sub mH mI mW hH hI Xscore path \0 origPath
                var fields = line.Split(' ', line[0] == '1' ? 9 : 10);
                var path = fields[^1];
                var from = line[0] == '2' && i + 1 < parts.Length ? parts[++i] : "";
                state.Files.Add(new GitFile { Path = path, From = from, Index = fields[1][0], Work = fields[1][1] });
            }
            else if (line[0] == 'u')
            {
                var fields = line.Split(' ', 11);
                state.Files.Add(new GitFile { Path = fields[^1], Index = fields[1][0], Work = fields[1][1], Conflict = true });
            }
            else if (line[0] == '?') state.Files.Add(new GitFile { Path = line[2..], Untracked = true });
        }
        state.Underway = Underway(root);
        await CountLines(root, state);
        return state;
    }

    /// <summary>The lines each file adds and removes: in the index and in the working folder together.</summary>
    static async Task CountLines(string root, GitState state)
    {
        if (state.Files.Count == 0 || state.Files.Count > 2000) return;
        var counts = new Dictionary<string, (int Add, int Del)>(StringComparer.Ordinal);
        foreach (var args in new[] { new[] { "diff", "--numstat", "-z" }, new[] { "diff", "--cached", "--numstat", "-z" } })
        {
            var answer = await Ask(root, args);
            if (!answer.Ok) continue;
            var parts = answer.Out.Split('\0');
            for (int i = 0; i < parts.Length; i++)
            {
                var fields = parts[i].Split('\t');
                if (fields.Length < 3) continue;
                // A rename comes as "add del " then the old and the new path in the next two parts.
                var path = fields[2].Length > 0 ? fields[2] : (i + 2 < parts.Length ? parts[i += 2] : "");
                int.TryParse(fields[0], out var add);
                int.TryParse(fields[1], out var del);
                counts.TryGetValue(path, out var known);
                counts[path] = (known.Add + add, known.Del + del);
            }
        }
        foreach (var file in state.Files)
        {
            if (counts.TryGetValue(file.Path, out var c)) { file.Added = c.Add; file.Removed = c.Del; }
            else if (file.Untracked) { file.Added = CountTextLines(Path.Combine(root, file.Path)); file.Removed = 0; }
        }
    }

    static int CountTextLines(string file)
    {
        try
        {
            var info = new FileInfo(file);
            if (!info.Exists || info.Length > 2_000_000) return -1;
            var bytes = File.ReadAllBytes(file);
            if (Array.IndexOf(bytes, (byte)0) >= 0) return -1;
            int lines = bytes.Count(b => b == (byte)'\n');
            return bytes.Length > 0 && bytes[^1] != (byte)'\n' ? lines + 1 : lines;
        }
        catch { return -1; }
    }

    /// <summary>A merge, a cherry-pick, a revert or a rebase stopped half way: read from the files git leaves in .git.</summary>
    public static string Underway(string root)
    {
        var dir = Path.Combine(root, ".git");
        if (File.Exists(dir))
        {
            // A worktree or a submodule: ".git" is a file naming the real folder.
            var text = File.ReadAllText(dir).Trim();
            if (text.StartsWith("gitdir:", StringComparison.Ordinal)) dir = Path.GetFullPath(Path.Combine(root, text[7..].Trim()));
        }
        if (Directory.Exists(Path.Combine(dir, "rebase-merge")) || Directory.Exists(Path.Combine(dir, "rebase-apply"))) return "rebase";
        if (File.Exists(Path.Combine(dir, "MERGE_HEAD"))) return "merge";
        if (File.Exists(Path.Combine(dir, "CHERRY_PICK_HEAD"))) return "cherry-pick";
        if (File.Exists(Path.Combine(dir, "REVERT_HEAD"))) return "revert";
        return "";
    }

    const char Field = '\x1f', Record = '\x1e';

    /// <summary>The history of every branch, newest first, as the graph draws it.</summary>
    public static async Task<List<GitCommit>> Log(string root, int count = 300, bool all = true)
    {
        var args = new List<string> { "log", "--date-order", "-n", count.ToString(), "--format=%H%x1f%P%x1f%D%x1f%an%x1f%ae%x1f%at%x1f%s%x1e" };
        if (all) args.Insert(1, "--all");
        var answer = await Ask(root, args.ToArray());
        var list = new List<GitCommit>();
        if (!answer.Ok) return list;
        foreach (var raw in answer.Out.Split(Record))
        {
            var fields = raw.Trim('\n', '\r').Split(Field);
            if (fields.Length < 7) continue;
            long.TryParse(fields[5], out var stamp);
            list.Add(new GitCommit
            {
                Hash = fields[0],
                Parents = fields[1].Split(' ', StringSplitOptions.RemoveEmptyEntries),
                Refs = fields[2],
                Author = fields[3],
                Mail = fields[4],
                When = DateTimeOffset.FromUnixTimeSeconds(stamp).LocalDateTime,
                Subject = fields[6],
            });
        }
        return list;
    }

    /// <summary>The files a commit changed, with their lines: `git show --numstat`.</summary>
    public static async Task<List<(char Letter, string Path, int Add, int Del)>> CommitFiles(string root, string hash)
    {
        var list = new List<(char, string, int, int)>();
        // A merge is shown against its first parent: what the merge brought into the branch.
        var status = await Ask(root, "show", "--format=", "--name-status", "-z", "--no-renames", "--diff-merges=first-parent", hash);
        var stat = await Ask(root, "show", "--format=", "--numstat", "-z", "--no-renames", "--diff-merges=first-parent", hash);
        var counts = new Dictionary<string, (int, int)>(StringComparer.Ordinal);
        foreach (var part in stat.Out.Split('\0'))
        {
            var fields = part.Trim('\n').Split('\t');
            if (fields.Length < 3) continue;
            int.TryParse(fields[0], out var add);
            int.TryParse(fields[1], out var del);
            counts[fields[2]] = (add, del);
        }
        var parts = status.Out.Split('\0');
        for (int i = 0; i + 1 < parts.Length; i += 2)
        {
            var letter = parts[i].Trim('\n');
            if (letter.Length == 0) continue;
            var path = parts[i + 1];
            counts.TryGetValue(path, out var c);
            list.Add((letter[0], path, c.Item1, c.Item2));
        }
        return list;
    }

    /// <summary>Local and remote branches and tags.</summary>
    public static async Task<List<GitRef>> Refs(string root)
    {
        var answer = await Ask(root, "for-each-ref", "--sort=-committerdate",
            "--format=%(refname)%1f%(refname:short)%1f%(upstream:short)%1f%(upstream:track)%1f%(objectname:short)%1f%(committerdate:unix)%1f%(contents:subject)%1e",
            "refs/heads", "refs/remotes", "refs/tags");
        var list = new List<GitRef>();
        if (!answer.Ok) return list;
        foreach (var raw in answer.Out.Split(Record))
        {
            var f = raw.Trim('\n', '\r').Split(Field);
            if (f.Length < 7) continue;
            if (f[0].EndsWith("/HEAD", StringComparison.Ordinal)) continue;
            long.TryParse(f[5], out var stamp);
            var kind = f[0].StartsWith("refs/heads/") ? "local" : f[0].StartsWith("refs/remotes/") ? "remote" : "tag";
            var item = new GitRef { Kind = kind, Name = f[1], Upstream = f[2], Track = f[3], Hash = f[4], When = DateTimeOffset.FromUnixTimeSeconds(stamp).LocalDateTime, Subject = f[6] };
            foreach (var piece in f[3].Trim('[', ']').Split(',', StringSplitOptions.TrimEntries))
            {
                if (piece.StartsWith("ahead ") && int.TryParse(piece[6..], out var a)) item.Ahead = a;
                if (piece.StartsWith("behind ") && int.TryParse(piece[7..], out var b)) item.Behind = b;
            }
            list.Add(item);
        }
        return list;
    }

    /// <summary>The branches already merged into the current one.</summary>
    public static async Task<HashSet<string>> Merged(string root)
    {
        var answer = await Ask(root, "branch", "--merged", "--format=%(refname:short)");
        return answer.Ok ? answer.Out.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToHashSet() : new();
    }

    /// <summary>The drawer of put-aside edits: name, message, time.</summary>
    public static async Task<List<(string Name, string Message, DateTime When)>> Stashes(string root)
    {
        var answer = await Ask(root, "stash", "list", "--format=%gd%x1f%s%x1f%ct");
        var list = new List<(string, string, DateTime)>();
        if (!answer.Ok) return list;
        foreach (var line in answer.Out.Split('\n', StringSplitOptions.RemoveEmptyEntries))
        {
            var f = line.Split(Field);
            if (f.Length < 3) continue;
            long.TryParse(f[2], out var stamp);
            list.Add((f[0], f[1], DateTimeOffset.FromUnixTimeSeconds(stamp).LocalDateTime));
        }
        return list;
    }

    /// <summary>The remotes of the repository with their fetch and push addresses.</summary>
    public static async Task<List<(string Name, string Fetch, string Push)>> Remotes(string root)
    {
        var answer = await Ask(root, "remote", "-v");
        var map = new Dictionary<string, (string Fetch, string Push)>();
        var order = new List<string>();
        if (answer.Ok)
            foreach (var line in answer.Out.Split('\n', StringSplitOptions.RemoveEmptyEntries))
            {
                var f = line.Split('\t');
                if (f.Length < 2) continue;
                var url = f[1].Replace(" (fetch)", "").Replace(" (push)", "");
                if (!map.ContainsKey(f[0])) { map[f[0]] = ("", ""); order.Add(f[0]); }
                var known = map[f[0]];
                map[f[0]] = f[1].EndsWith("(push)") ? (known.Fetch, known.Push.Length > 0 ? known.Push + " " + url : url) : (url, known.Push);
            }
        return order.Select(name => (name, map[name].Fetch, map[name].Push)).ToList();
    }

    /// <summary>How far the current branch is from a branch of a remote: ahead, behind; null - no such branch there.</summary>
    public static async Task<(int Ahead, int Behind)?> Distance(string root, string other)
    {
        var answer = await Ask(root, "rev-list", "--left-right", "--count", "HEAD..." + other);
        if (!answer.Ok) return null;
        var f = answer.Out.Trim().Split('\t', ' ');
        return f.Length == 2 && int.TryParse(f[0], out var a) && int.TryParse(f[1], out var b) ? (a, b) : null;
    }

    /// <summary>The difference of one file, as text: against the index, of the index, or against HEAD.</summary>
    public static Task<GitAnswer> Diff(string root, string path, string mode) => mode switch
    {
        "cached" => Ask(root, "diff", "--cached", "--", path),
        "head" => Ask(root, "diff", "HEAD", "--", path),
        _ => Ask(root, "diff", "--", path),
    };

    /// <summary>The text of one file in a commit (`git show HASH:path`).</summary>
    public static Task<GitAnswer> Show(string root, string spec) => Ask(root, "show", spec);
}
