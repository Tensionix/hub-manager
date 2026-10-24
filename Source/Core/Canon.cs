using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Threading.Tasks;

namespace AudionHubManager.Core;

/// <summary>
/// One Git operation of the canon: the command with its places, its risk, how it runs, and what it does and how to
/// undo it in plain words. The table is the engine's (system_core\core\git_canon.py), read once through
/// `hub_cli canon`: the window names no Git command of its own, and the tests of the engine run every one of these on
/// the lab.
/// </summary>
public sealed class CanonEntry
{
    public string Id { get; init; } = "";
    public List<string> Args { get; init; } = new();
    public string Display { get; init; } = "";
    /// <summary>The command as it is typed, without its places: "git restore --staged" - the caption of a button.</summary>
    public string Short { get; init; } = "";
    public List<string> Places { get; init; } = new();
    public string Risk { get; init; } = "read";
    public string Mode { get; init; } = "run";
    public string Section { get; init; } = "";
    public string WhatRu { get; init; } = "";
    public string UndoRu { get; init; } = "";
    public string WhatEn { get; init; } = "";
    public string UndoEn { get; init; } = "";
    public List<string> Tags { get; init; } = new();

    public string What => Lang.Code == "ru" ? WhatRu : WhatEn;
    public string Undo => Lang.Code == "ru" ? UndoRu : UndoEn;

    static readonly Regex Place = new(@"\{([a-z_]+)\}", RegexOptions.Compiled);

    /// <summary>
    /// The command with its places filled. A list goes in as several arguments where its place stands alone ({paths});
    /// a place without a value is an error - nothing is guessed.
    /// </summary>
    public List<string> Argv(Dictionary<string, object> values)
    {
        var argv = new List<string>();
        foreach (var arg in Args)
        {
            var whole = Place.Match(arg);
            if (whole.Success && whole.Length == arg.Length && values.TryGetValue(whole.Groups[1].Value, out var many) && many is IEnumerable<string> list)
            {
                argv.AddRange(list);
                continue;
            }
            argv.Add(Place.Replace(arg, m => values.TryGetValue(m.Groups[1].Value, out var v)
                ? v.ToString() ?? "" : throw new KeyError($"{Id}: no value for {{{m.Groups[1].Value}}}")));
        }
        return argv;
    }

    /// <summary>The command as the terminal prints it: an argument with a space in quotes.</summary>
    public static string Show(IEnumerable<string> argv) => string.Join(" ", argv.Select(arg =>
        arg.Length == 0 ? "\"\"" : arg.IndexOfAny(new[] { ' ', '\t', '&', '|', '<', '>' }) >= 0 || arg.Contains('"') ? "\"" + arg.Replace("\"", "\\\"") + "\"" : arg));

    /// <summary>The tooltip of a button of this operation: the command, the words, the risk, the way back.</summary>
    public string Tip(string? command = null)
    {
        var text = new StringBuilder();
        text.Append(command ?? Display).Append('\n').Append(What);
        text.Append('\n').Append(Lang.T(Canon.RiskWords(Risk)));
        if (Undo.Length > 0 && Undo != "—") text.Append('\n').Append(Undo);
        return text.ToString();
    }
}

public sealed class KeyError : Exception
{
    public KeyError(string message) : base(message) { }
}

public static class Canon
{
    static readonly Dictionary<string, CanonEntry> Table = new();

    public static bool Loaded => Table.Count > 0;

    public static IReadOnlyCollection<CanonEntry> All => Table.Values;

    /// <summary>A command as the terminal prints it: an argument with a space in quotes.</summary>
    public static string Show(IEnumerable<string> argv) => CanonEntry.Show(argv);

    /// <summary>Windows starts a program with a command line of at most 32767 characters; git_canon.ARGV_LIMIT is the same.</summary>
    public const int ArgvLimit = 24000;

    /// <summary>
    /// A git command whose paths after "--" would not fit into one command line - the first commit of a big project: the
    /// same command reading them from its input (--pathspec-from-file=- --pathspec-file-nul), and that input. A command
    /// that fits comes back as it is - the lesson is the command as typed (git_canon.fit).
    /// </summary>
    public static (List<string> Argv, string Stdin, int Paths) Fit(List<string> argv)
    {
        int cut = argv.IndexOf("--");
        if (argv.Count == 0 || argv[0] != "git" || cut < 0 || argv.Sum(a => a.Length + 3) <= ArgvLimit) return (argv, "", 0);
        var paths = argv.Skip(cut + 1).ToList();
        return (argv.Take(cut).Concat(new[] { "--pathspec-from-file=-", "--pathspec-file-nul" }).ToList(), string.Join("\0", paths) + "\0", paths.Count);
    }

    /// <summary>A command as the terminal prints it, its paths named by their number when they go through the input.</summary>
    public static string Brief(List<string> argv)
    {
        var (fitted, _, paths) = Fit(argv);
        return paths == 0 ? Show(argv) : Show(fitted) + "   " + Lang.F("‹путей на входе: {0}›", paths);
    }

    public static CanonEntry? Find(string id) => Table.TryGetValue(id, out var entry) ? entry : null;

    public static CanonEntry Get(string id) => Find(id) ?? throw new KeyError("no such operation in the canon: " + id);

    /// <summary>Reads the table from the console command once; the reason when it could not.</summary>
    public static async Task<string> Load()
    {
        var answer = await Hub.Ask("canon");
        if (!answer.Ok || answer.Json?["canon"] is not JsonArray items) return answer.Error.Length > 0 ? answer.Error : "no canon";
        Table.Clear();
        foreach (var node in items.OfType<JsonObject>())
        {
            var entry = new CanonEntry
            {
                Id = node["id"]!.ToString(),
                Args = node["args"]!.AsArray().Select(a => a!.ToString()).ToList(),
                Display = node["display"]?.ToString() ?? "",
                Short = node["short"]?.ToString() ?? "",
                Places = node["places"]?.AsArray().Select(a => a!.ToString()).ToList() ?? new(),
                Risk = node["risk"]?.ToString() ?? "read",
                Mode = node["mode"]?.ToString() ?? "run",
                Section = node["section"]?.ToString() ?? "",
                WhatRu = node["ru"]?["what"]?.ToString() ?? "",
                UndoRu = node["ru"]?["undo"]?.ToString() ?? "",
                WhatEn = node["en"]?["what"]?.ToString() ?? "",
                UndoEn = node["en"]?["undo"]?.ToString() ?? "",
                Tags = node["tags"]?.AsArray().Select(a => a!.ToString()).ToList() ?? new(),
            };
            Table[entry.Id] = entry;
        }
        return "";
    }

    /// <summary>The words of a risk, in Russian (shown through Lang.T).</summary>
    public static string RiskWords(string risk) => risk switch
    {
        "read" => "Только читает - ничего не меняет.",
        "local" => "Меняет этот репозиторий.",
        "net" => "Говорит с сервером.",
        "danger" => "Опасно: можно потерять работу - окно спросит.",
        _ => "",
    };

    /// <summary>The brush key of a risk: the dot on every Git button.</summary>
    public static string RiskInk(string risk) => risk switch
    {
        "local" => "Quasar",
        "net" => "GitRenamed",
        "danger" => "BurnInk",
        _ => "CrumbInk",
    };
}
