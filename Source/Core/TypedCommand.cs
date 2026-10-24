using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace AudionHubManager.Core;

/// <summary>
/// A command typed in the line of the terminal: its words, its calls of git, and what each can cost. A typed command
/// asks what its button would ask - the policy of the canon, whatever the order of the flags - so the line keeps the
/// guarantees of the buttons (the audit of 24.10.2026 found reset --soft, commit --amend and reset -q --hard going
/// without a question).
/// </summary>
public static class TypedCommand
{
    /// <summary>The words of a command line as a shell would split them: by spaces, "quoted parts" whole.</summary>
    public static List<string> Split(string text)
    {
        var args = new List<string>();
        var current = new StringBuilder();
        bool quoted = false, any = false;
        foreach (var ch in text)
        {
            if (ch == '"') { quoted = !quoted; any = true; continue; }
            if (char.IsWhiteSpace(ch) && !quoted)
            {
                if (any) { args.Add(current.ToString()); current.Clear(); any = false; }
                continue;
            }
            current.Append(ch);
            any = true;
        }
        if (any) args.Add(current.ToString());
        return args;
    }

    /// <summary>The calls of git in a typed line: the line itself in the mode GIT, every "git ..." between ; &amp;&amp; | in PS and CMD.</summary>
    public static IEnumerable<List<string>> GitCalls(string shell, string text)
    {
        if (shell == "git")
        {
            var argv = Split(text);
            if (argv.Count > 0 && argv[0] != "git") argv.Insert(0, "git");
            if (argv.Count > 0) yield return argv;
            yield break;
        }
        foreach (var part in Regex.Split(text, @"&&|\|\||[;|\r\n]"))
        {
            var argv = Split(part.Trim());
            if (argv.Count > 0 && (argv[0].Equals("git", StringComparison.OrdinalIgnoreCase) || argv[0].EndsWith("git.exe", StringComparison.OrdinalIgnoreCase)))
            {
                argv[0] = "git";
                yield return argv;
            }
        }
    }

    /// <summary>
    /// What a typed git command can cost, whatever the order of its flags: a variant of a dangerous operation of the canon
    /// (its id: the button's own question, a reset --hard asks for the word RESET), another way to lose work (null, the
    /// general question), or nothing.
    /// </summary>
    public static (bool Danger, string? CanonId) Cost(List<string> argv)
    {
        int at = 1;
        while (at < argv.Count && argv[at].StartsWith('-'))
            at += argv[at] is "-C" or "-c" ? 2 : 1;  // git -C <folder> -c <key=value> --no-pager ...
        if (at >= argv.Count) return (false, null);
        var sub = argv[at].ToLowerInvariant();
        var rest = argv.Skip(at + 1).ToList();
        bool Has(params string[] flags) => rest.Any(a => flags.Any(f => a == f || a.StartsWith(f + "=", StringComparison.Ordinal)));
        bool Short(char letter) => rest.Any(a => a.Length > 1 && a[0] == '-' && a[1] != '-' && a.IndexOf(letter, 1) > 0);
        var plain = rest.TakeWhile(a => a != "--").Where(a => !a.StartsWith('-')).ToList();
        return sub switch
        {
            "reset" when Has("--hard") => (true, "reset_hard"),
            "reset" when Has("--soft") => (true, "reset_soft"),
            "reset" when Has("--mixed", "--merge", "--keep") || plain.Any(a => a.Contains('~') || a.Contains('^') || a.StartsWith("HEAD", StringComparison.Ordinal) || Regex.IsMatch(a, "^[0-9a-f]{7,40}$")) => (true, null),
            "commit" when Has("--amend") => (true, "amend"),
            "restore" when !Has("--staged") && !Short('S') || Has("--worktree") || Short('W') => (true, "restore"),
            "checkout" when rest.Contains("--") || rest.Contains(".") || Has("--force") || Short('f') => (true, null),
            "switch" when Has("--discard-changes", "--force") || Short('f') => (true, null),
            "clean" when Has("--force") || Short('f') => (true, null),
            "push" when Has("--force", "--force-with-lease", "--force-if-includes", "--delete", "--mirror", "--prune") || Short('f') || Short('d')
                || rest.Any(a => a.StartsWith('+') || a.StartsWith(':')) => (true, null),
            "branch" when Short('D') || Short('M') || Short('C') || (Has("--delete") || Short('d')) && (Has("--force") || Short('f')) => (true, null),
            "stash" when rest.FirstOrDefault() is "drop" or "clear" => (true, null),
            "rebase" when !Has("--abort", "--continue") => (true, "rebase"),
            "filter-branch" or "filter-repo" => (true, null),
            "reflog" when rest.FirstOrDefault() is "expire" or "delete" => (true, null),
            "gc" when Has("--prune") => (true, null),
            "update-ref" when Short('d') => (true, null),
            "rm" when !Has("--cached") => (true, null),
            "tag" when Has("--delete", "--force") || Short('d') || Short('f') => (true, null),
            _ => (false, null),
        };
    }
}
