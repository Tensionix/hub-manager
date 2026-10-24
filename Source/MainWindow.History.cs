using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Controls.Templates;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using AudionHubManager.Core;
using AudionHubManager.Views;

namespace AudionHubManager;

/// <summary>
/// ИСТОРИЯ: the graph of every branch - where they parted and where they met - with the branches, the tags and HEAD on
/// their commits; the history of one file; the tags; the reflog, where even a "lost" commit is found. The commit chosen
/// shows its files and what can be done with it, sorted by what it costs: what changes nothing, what adds a new commit
/// on top, what rewrites history.
/// </summary>
public partial class MainWindow
{
    /// <summary>The commit chosen in the graph (its full hash), the file whose history is shown, the view of the page.</summary>
    string? _commit;
    string _historyFile = "";
    string _historyView = "graph";
    bool _historyAll = true;
    string _historyFind = "";

    ListBox? _commits;
    StackPanel? _commitDetails;
    StackPanel? _historyTabs;
    TextBox? _refField;
    List<GitCommit> _log = new();

    Control BuildHistory()
    {
        if (_historyFile.Length > 0) _historyView = "file";
        var head = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto,Auto"), Margin = new Thickness(0, 0, 0, 10) };
        _historyTabs = new StackPanel { Orientation = Orientation.Horizontal };
        head.Children.Add(_historyTabs);
        var scope = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 8, 0) };
        foreach (var (all, word, tip) in new[] { (true, "ВСЕ ВЕТКИ", "Граф всех веток: локальных и с сервера."), (false, "ТЕКУЩАЯ", "Только история текущей ветки.") })
            scope.Children.Add(Chip(word, _historyAll == all, () => { _historyAll = all; ShowSection(); _ = UpdateHistory(); }, tip));
        Grid.SetColumn(scope, 2);
        head.Children.Add(scope);
        var find = Field("искать в сообщениях", _historyFind, 190, "Оставить коммиты, в сообщении, авторе или хэше которых есть этот текст.", "history_find");
        find.TextChanged += (_, _) => { _historyFind = find.Text ?? ""; ShowCommits(); };
        Grid.SetColumn(find, 3);
        head.Children.Add(find);
        MarkHistoryTabs();

        // The commit chosen takes 330: beside the column of projects the messages need the rest.
        var split = new Grid { ColumnDefinitions = new ColumnDefinitions("*,10,330") };
        _commits = Rows("commits");
        _commits.ItemTemplate = new FuncDataTemplate<CommitRow>((row, _) => row is null ? new Panel() : CommitView(row), supportsRecycling: false);
        _commits.SelectionChanged += (_, _) => { if (_commits.SelectedItem is CommitRow row) { _commit = row.Commit.Hash; _ = ShowCommit(row.Commit); } };
        var listBody = new DockPanel();
        var heads = Heads("74,*,90,112,58", Lang.T("ГРАФ"), Lang.T("СООБЩЕНИЕ"), Lang.T("АВТОР"), Lang.T("КОГДА"), Lang.T("ХЭШ"));
        DockPanel.SetDock(heads, Dock.Top);
        listBody.Children.Add(heads);
        listBody.Children.Add(_commits);
        split.Children.Add(new Border { Classes = { "pane" }, Child = listBody });
        _commitDetails = new StackPanel { Spacing = 9, Margin = new Thickness(12, 10) };
        var details = new Border { Classes = { "pane" }, Child = new ScrollViewer { Content = _commitDetails } };
        Grid.SetColumn(details, 2);
        split.Children.Add(details);

        var page = new Grid { RowDefinitions = new RowDefinitions("Auto,*") };
        page.Children.Add(head);
        Grid.SetRow(split, 1);
        page.Children.Add(split);

        _refField = Grow(Field("имя ветки или тега для выбранного коммита", "", tip: "Имя для «ветка отсюда» и «тег здесь»: ветка - feature/имя, тег - projection-v0.1.2.", id: "history_ref"));
        SetOps(
            OpCanon("show", "показать", () => CommitValues(), "F3"),
            OpCanon("log", "лента", () => null),
            OpCanon("reflog", "reflog", () => null),
            null,
            _refField,
            OpCanon("branch_at", "ветка отсюда", () => RefValues("new_branch"), cls: "quiet"),
            OpCanon("tag_at", "тег здесь", () => RefValues("tag"), cls: "quiet"),
            null,
            OpCanon("revert", "revert", () => CommitValues()));
        _keys[Key.F3] = () => RunCanon("show", CommitValues());
        return page;
    }

    void MarkHistoryTabs()
    {
        if (_historyTabs is null) return;
        _historyTabs.Children.Clear();
        _historyTabs.Children.Add(new TextBlock { Classes = { "pagetitle" }, Text = Upper(Lang.T("ИСТОРИЯ")), Margin = new Thickness(0, 0, 14, 0) });
        var views = new List<(string, string, string)> { ("graph", "ГРАФ", "Граф коммитов всех веток.") };
        if (_historyFile.Length > 0) views.Add(("file", Lang.T("ФАЙЛ") + " " + System.IO.Path.GetFileName(_historyFile), Canon.Get("log_file").Tip()));
        views.Add(("tags", "ТЕГИ", Canon.Get("tags").Tip()));
        views.Add(("reflog", "REFLOG", Canon.Get("reflog").Tip()));
        foreach (var (view, word, tip) in views)
        {
            var tab = new ToggleButton { Classes = { "switch" }, Content = Lang.T(word), IsChecked = _historyView == view, Margin = new Thickness(0, 0, 4, 0) };
            ToolTip.SetTip(tab, Lang.T(tip));
            Avalonia.Automation.AutomationProperties.SetAutomationId(tab, "history_" + view);
            tab.Click += (_, _) => { _historyView = view; MarkHistoryTabs(); _ = UpdateHistory(); };
            _historyTabs.Children.Add(tab);
        }
    }

    sealed class CommitRow
    {
        public GitCommit Commit = new();
        public GraphRow? Graph;
        public int Width;
    }

    List<CommitRow> _commitRows = new();

    async Task UpdateHistory()
    {
        if (_commits is null) return;
        if (ActiveRoot(true) is not { } root) { _commits.ItemsSource = null; ShowCommitNote(); return; }
        _log = _historyView switch
        {
            "file" when _historyFile.Length > 0 => await FileLog(root, _historyFile),
            "reflog" => await Reflog(root),
            "tags" => await TagLog(root),
            _ => await Git.Log(root, 400, _historyAll),
        };
        ShowCommits();
    }

    static async Task<List<GitCommit>> FileLog(string root, string path)
    {
        var answer = await Git.Ask(root, "log", "--follow", "-n", "200", "--format=%H%x1f%P%x1f%D%x1f%an%x1f%ae%x1f%at%x1f%s%x1e", "--", path);
        return ParseLog(answer.Out);
    }

    static async Task<List<GitCommit>> Reflog(string root)
    {
        var answer = await Git.Ask(root, "reflog", "-n", "200", "--format=%H%x1f%P%x1f%gd · %gs%x1f%an%x1f%ae%x1f%ct%x1f%s%x1e");
        return ParseLog(answer.Out);
    }

    static async Task<List<GitCommit>> TagLog(string root)
    {
        var answer = await Git.Ask(root, "log", "--no-walk", "--tags", "--date-order", "--format=%H%x1f%P%x1f%D%x1f%an%x1f%ae%x1f%at%x1f%s%x1e");
        return ParseLog(answer.Out);
    }

    static List<GitCommit> ParseLog(string text)
    {
        var list = new List<GitCommit>();
        foreach (var raw in text.Split('\x1e'))
        {
            var f = raw.Trim('\n', '\r').Split('\x1f');
            if (f.Length < 7) continue;
            long.TryParse(f[5], out var stamp);
            list.Add(new GitCommit
            {
                Hash = f[0], Parents = f[1].Split(' ', StringSplitOptions.RemoveEmptyEntries), Refs = f[2], Author = f[3], Mail = f[4],
                When = DateTimeOffset.FromUnixTimeSeconds(stamp).LocalDateTime, Subject = f[6],
            });
        }
        return list;
    }

    void ShowCommits()
    {
        if (_commits is null) return;
        var visible = _log.Where(c => _historyFind.Length == 0 || c.Subject.Contains(_historyFind, StringComparison.OrdinalIgnoreCase)
            || c.Author.Contains(_historyFind, StringComparison.OrdinalIgnoreCase) || c.Hash.StartsWith(_historyFind, StringComparison.OrdinalIgnoreCase)).ToList();
        // The graph is drawn only over the whole history: a filtered list or the reflog has no lanes to keep.
        bool graph = _historyView == "graph" && _historyFind.Length == 0;
        var lay = graph ? GraphLayout.Lay(visible, _state?.Head ?? "") : null;
        int width = lay?.Select(r => r.Width).DefaultIfEmpty(1).Max() ?? 0;
        _commitRows = visible.Select((c, i) => new CommitRow { Commit = c, Graph = lay?[i], Width = Math.Min(width, 12) }).ToList();
        _commits.ItemsSource = _commitRows;
        var again = _commitRows.FirstOrDefault(r => r.Commit.Hash == _commit) ?? _commitRows.FirstOrDefault();
        if (again is not null) _commits.SelectedItem = again;
        else ShowCommitNote();
    }

    Control CommitView(CommitRow row)
    {
        var c = row.Commit;
        // The lanes stand in a column of their own; a history wider than five lanes is cut at its right edge, not pushed into the messages.
        Control graph = row.Graph is { } g ? new Border { ClipToBounds = true, Child = new GraphCell(g, row.Width) } : new Border { Width = 8 };
        // The names first, then the message - which fades out before the author, never under him; names too long for the
        // column fade with it, not cut off in the middle of a letter.
        var refs = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 5, VerticalAlignment = VerticalAlignment.Center };
        foreach (var (kind, name) in Decorations(c.Refs)) refs.Children.Add(RefChip(kind, name));
        var subject = Cell(c.Subject);
        subject.Margin = new Thickness(refs.Children.Count > 0 ? 5 : 0, 0, 0, 0);
        var message = new FadeBox(new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center, Children = { refs, subject } })
        {
            Margin = new Thickness(0, 0, 10, 0),
        };
        // The hash is seven letters: 58 holds it; the date "yesterday 23:23" whole in 112 - the rest is the message's.
        var grid = Cells(row.Graph is null ? "8,*,90,112,58" : "74,*,90,112,58", graph, message, Cell(c.Author, quiet: true), Cell(When(c.When), quiet: true), Cell(c.Short, "CrumbInk"));
        grid.Margin = new Thickness(8, 0, 8, 0);
        grid.MinHeight = 28;
        ToolTip.SetTip(grid, c.Subject + "\n" + c.Author + " · " + c.When.ToString("dd.MM.yyyy HH:mm") + "\n" + c.Hash);
        return grid;
    }

    /// <summary>The names on a commit (%D): HEAD → branch, branches, branches of a remote, tags.</summary>
    IEnumerable<(string Kind, string Name)> Decorations(string refs)
    {
        if (_historyView == "reflog") { if (refs.Length > 0) yield return ("reflog", refs); yield break; }
        foreach (var part in refs.Split(", ", StringSplitOptions.RemoveEmptyEntries))
        {
            if (part.StartsWith("HEAD -> ")) yield return ("head", "HEAD → " + part[8..]);
            else if (part == "HEAD") yield return ("head", "HEAD");
            else if (part.StartsWith("tag: ")) yield return ("tag", part[5..]);
            else if (part.Contains('/') && !part.StartsWith("feature/") && !part.StartsWith("fix/") && IsRemoteRef(part)) yield return ("remote", part);
            else yield return ("local", part);
        }
    }

    bool IsRemoteRef(string name) => _remoteNames.Any(r => name.StartsWith(r + "/", StringComparison.Ordinal));

    static Border RefChip(string kind, string name)
    {
        var (ink, icon) = kind switch
        {
            "head" => ("FillInk", "git-commit-vertical"),
            "tag" => ("AmberInk", "tag"),
            "remote" => ("GitRenamed", "cloud-download"),
            "reflog" => ("LogExplain", "history"),
            _ => ("Quasar", "git-branch"),
        };
        var text = new TextBlock { Text = name, FontSize = App.SizeOf("FontFine", 9.5), VerticalAlignment = VerticalAlignment.Center }.Ink(TextBlock.ForegroundProperty, ink);
        var chip = new Border
        {
            CornerRadius = new CornerRadius(5), BorderThickness = new Thickness(1), Padding = new Thickness(5, 0), Height = 19, VerticalAlignment = VerticalAlignment.Center,
            Child = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 4, Children = { Sign(icon, ink), text } },
        };
        if (kind == "head") chip.Ink(Border.BackgroundProperty, "FillRun").Ink(Border.BorderBrushProperty, "FillRun");
        else
        {
            var brush = App.Ink(ink) as ISolidColorBrush;
            chip.BorderBrush = brush is null ? null : new SolidColorBrush(brush.Color, 0.45 * App.RimKeeps);
            chip.Background = brush is null ? null : new SolidColorBrush(brush.Color, 0.1);
        }
        return chip;
    }

    void ShowCommitNote()
    {
        if (_commitDetails is null) return;
        _commitDetails.Children.Clear();
        _commitDetails.Children.Add(Note(_repoKind == "own" ? "Коммитов ещё нет: сделайте первый в разделе ИЗМЕНЕНИЯ." : "Здесь будет выбранный коммит: его файлы и что с ним можно сделать."));
    }

    int _commitAsk;

    async Task ShowCommit(GitCommit c)
    {
        if (_commitDetails is null || ActiveRoot(true) is not { } root) return;
        int ask = ++_commitAsk;
        var files = await Git.CommitFiles(root, c.Hash);
        if (ask != _commitAsk) return;
        var d = _commitDetails;
        d.Children.Clear();
        var hash = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto") };
        hash.Children.Add(RefChip("local", c.Short));
        var copy = new Button { Classes = { "tool" }, Content = Sign("copy") };
        ToolTip.SetTip(copy, Lang.T("Скопировать полный хэш коммита."));
        copy.Click += async (_, _) =>
        {
            if (Clipboard is { } clip) await Avalonia.Input.Platform.ClipboardExtensions.SetTextAsync(clip, c.Hash);
            Toast.Show(this, Lang.F("Хэш скопирован: {0}", c.Short));
        };
        Grid.SetColumn(copy, 2);
        hash.Children.Add(copy);
        d.Children.Add(hash);
        d.Children.Add(new TextBlock { Text = c.Subject, FontWeight = FontWeight.Bold, TextWrapping = TextWrapping.Wrap });
        var facts = new Grid { ColumnDefinitions = new ColumnDefinitions("84,*"), RowDefinitions = new RowDefinitions("Auto,Auto,Auto") };
        void Fact(int r, string name, string value)
        {
            var n = Text(name, "caption"); Grid.SetRow(n, r); facts.Children.Add(n);
            var v = new TextBlock { Text = value, TextWrapping = TextWrapping.Wrap, FontSize = App.SizeOf("FontPanel", 12) }; Grid.SetRow(v, r); Grid.SetColumn(v, 1); facts.Children.Add(v);
        }
        Fact(0, "автор", $"{c.Author} <{c.Mail}>");
        Fact(1, "когда", c.When.ToString("dd.MM.yyyy HH:mm"));
        Fact(2, "родители", c.Parents.Length == 0 ? Lang.T("нет - это первый коммит") : string.Join(", ", c.Parents.Select(p => p[..Math.Min(7, p.Length)])) + (c.Parents.Length > 1 ? "  · " + Lang.T("слияние") : ""));
        d.Children.Add(facts);
        d.Children.Add(Text(Lang.F("ФАЙЛЫ КОММИТА · {0}", files.Count), "blocktitle"));
        var list = new StackPanel { Spacing = 2 };
        foreach (var (letter, path, add, del) in files.Take(200))
        {
            var lines = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 5 };
            if (add > 0) lines.Children.Add(Cell("+" + add, "GitStaged"));
            if (del > 0) lines.Children.Add(Cell("−" + del, "GitDeleted"));
            var row = Cells("24,*,Auto", Letter(letter, true), Cell(path), lines);
            row.Margin = new Thickness(0);
            ToolTip.SetTip(row, path);
            list.Children.Add(row);
        }
        d.Children.Add(list);
        var values = new Dictionary<string, object> { ["commit"] = c.Hash };
        Panel Group(string title, string ink, params Control[] buttons)
        {
            var wrap = new WrapPanel { Orientation = Orientation.Horizontal };
            foreach (var b in buttons) { b.Margin = new Thickness(0, 0, 6, 6); wrap.Children.Add(b); }
            return new StackPanel { Spacing = 5, Children = { Text(title, "blocktitle").Ink(TextBlock.ForegroundProperty, ink), wrap } };
        }
        d.Children.Add(Group("НИЧЕГО НЕ МЕНЯЕТ", "TextMuted",
            OpCanon("show", "показать", () => values, sm: true)));
        d.Children.Add(Group("НОВЫЙ КОММИТ ПОВЕРХ", "TextMuted",
            OpCanon("revert", "revert", () => values, sm: true),
            OpCanon("cherry_pick", "cherry-pick в текущую", () => values, sm: true)));
        bool isHead = c.Hash == _state?.Head;
        var rewrite = new List<Control>();
        if (isHead) rewrite.Add(OpCanon("reset_soft", "убрать последний (soft)", () => new(), sm: true));
        rewrite.Add(OpCanon("reset_hard", "сбросить сюда (hard)", () => values, sm: true));
        d.Children.Add(Group("ПЕРЕПИСЫВАЕТ ИСТОРИЮ", "BurnInk", rewrite.ToArray()));
        ApplyBusy();
    }

    Dictionary<string, object>? CommitValues() => _commit is null ? null : new() { ["commit"] = _commit };

    Dictionary<string, object>? RefValues(string place)
    {
        var name = (_refField?.Text ?? "").Trim();
        if (name.Length == 0 || _commit is null) { SetStatus("Выберите коммит и впишите имя внизу."); return null; }
        return new() { ["commit"] = _commit, [place] = name, ["message"] = name };
    }
}
