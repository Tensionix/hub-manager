using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Templates;
using Avalonia.Input;
using Avalonia.Layout;
using AudionHubManager.Core;

namespace AudionHubManager;

/// <summary>
/// ВЕТКИ: the local branches with their pairs on the server and how far each is ahead or behind, the branches of the
/// remotes, the tags, the drawer of put-aside edits. The branch chosen has its card: how it stands against the current
/// one and what can be done with it. A merge or a cherry-pick stopped half way is shown over everything, with the way out.
/// </summary>
public partial class MainWindow
{
    List<string> _remoteNames = new();
    string _branchPick = "";
    ListBox? _branchList;
    StackPanel? _branchCard;
    Border? _underway;
    TextBox? _newBranch, _stashMessage;

    sealed class BranchRow
    {
        public string Head = "", Kind = "", Name = "", Line = "", Note = "", NoteKind = "";
        public int Ahead, Behind;
        public bool Current, Merged;
        public GitRef? Ref;
    }

    Control BuildBranches()
    {
        var page = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,*") };
        var head = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto"), Margin = new Thickness(0, 0, 0, 10) };
        head.Children.Add(new TextBlock { Classes = { "pagetitle" }, Text = Upper(Lang.T("ВЕТКИ")) });
        var tools = new StackPanel { Orientation = Orientation.Horizontal };
        tools.Children.Add(OpCanon("branches", "git branch -vv", () => null, cls: "quiet", sm: true));
        tools.Children.Add(OpCanon("stash_list", "git stash list", () => null, cls: "quiet", sm: true));
        Grid.SetColumn(tools, 2);
        head.Children.Add(tools);
        page.Children.Add(head);
        _underway = new Border { IsVisible = false, Margin = new Thickness(0, 0, 0, 10) };
        Grid.SetRow(_underway, 1);
        page.Children.Add(_underway);

        var split = new Grid { ColumnDefinitions = new ColumnDefinitions("*,10,*") };
        Grid.SetRow(split, 2);
        page.Children.Add(split);
        _branchList = Rows("branches");
        _branchList.ItemTemplate = new FuncDataTemplate<BranchRow>((row, _) => row is null ? new Panel() : BranchView(row), supportsRecycling: false);
        _branchList.SelectionChanged += (_, _) =>
        {
            if (_branchList.SelectedItem is BranchRow row && row.Head.Length == 0) { _branchPick = row.Kind + ":" + row.Name; ShowBranchCard(row); }
        };
        _branchList.DoubleTapped += (_, _) => { if (_branchList.SelectedItem is BranchRow { Kind: "local", Current: false } row) RunCanon("switch", new() { ["branch"] = row.Name }); };
        split.Children.Add(new Border { Classes = { "pane" }, Child = _branchList });
        _branchCard = new StackPanel { Spacing = 10 };
        var card = new ScrollViewer { Content = _branchCard };
        Grid.SetColumn(card, 2);
        split.Children.Add(card);

        _newBranch = Grow(Field("имя новой ветки: feature/что-то", "", tip: "Имя ветки: латиница, цифры, дефисы, «/» для группы - feature/report, fix/encoding.", id: "branch_new"));
        _stashMessage = Grow(Field("что откладываете", "", tip: "Пара слов о правках, которые откладываются: по ним их потом узнают в списке.", id: "stash_message"));
        SetOps(
            _newBranch,
            OpCanon("switch_new", "создать и перейти", () => NewBranchValues(), "F7", "quiet"),
            OpCanon("switch_back", "назад", () => null),
            null,
            _stashMessage,
            OpCanon("stash_push", "отложить", () => StashValues()),
            OpCanon("stash_pop", "достать", () => null));
        _keys[Key.F7] = () => RunCanon("switch_new", NewBranchValues());
        return page;
    }

    Dictionary<string, object>? NewBranchValues()
    {
        var name = (_newBranch?.Text ?? "").Trim();
        if (name.Length == 0) { SetStatus("Впишите имя новой ветки внизу."); return null; }
        return new() { ["new_branch"] = name };
    }

    Dictionary<string, object>? StashValues()
    {
        var message = (_stashMessage?.Text ?? "").Trim();
        return new() { ["message"] = message.Length > 0 ? message : Lang.T("отложено") + " " + DateTime.Now.ToString("dd.MM HH:mm") };
    }

    List<BranchRow> _branchRows = new();
    List<GitRef> _refs = new();

    async Task UpdateBranches()
    {
        if (_branchList is null) return;
        if (ActiveRoot(true) is not { } root) { _branchList.ItemsSource = null; ShowUnderway(); return; }
        _refs = await Git.Refs(root);
        var merged = await Git.Merged(root);
        var stashes = await Git.Stashes(root);
        var current = _state?.Branch ?? "";
        var rows = new List<BranchRow>();
        void Head(string text) => rows.Add(new BranchRow { Head = Lang.T(text) });
        var locals = _refs.Where(r => r.Kind == "local").ToList();
        Head("ЛОКАЛЬНЫЕ");
        foreach (var r in locals.OrderByDescending(r => r.Name == current).ThenBy(r => r.Name))
        {
            var row = new BranchRow { Kind = "local", Name = r.Name, Ref = r, Current = r.Name == current, Ahead = r.Ahead, Behind = r.Behind, Merged = merged.Contains(r.Name) && r.Name != current };
            row.Line = r.Upstream.Length > 0 ? "→ " + r.Upstream + (r.Track == "[gone]" ? " " + Lang.T("(удалена на сервере)") : "") : Lang.T("без пары на сервере");
            if (row.Merged) { row.Note = "слита в текущую"; row.NoteKind = "ok"; }
            rows.Add(row);
        }
        var remotes = _refs.Where(r => r.Kind == "remote").ToList();
        if (remotes.Count > 0)
        {
            Head("НА СЕРВЕРЕ");
            foreach (var r in remotes.OrderBy(r => r.Name)) rows.Add(new BranchRow { Kind = "remote", Name = r.Name, Ref = r, Line = When(r.When) });
        }
        var tags = _refs.Where(r => r.Kind == "tag").ToList();
        if (tags.Count > 0)
        {
            Head("ТЕГИ");
            foreach (var r in tags.Take(60)) rows.Add(new BranchRow { Kind = "tag", Name = r.Name, Ref = r, Line = r.Hash });
        }
        if (stashes.Count > 0)
        {
            Head("ОТЛОЖЕНО (STASH)");
            foreach (var (name, message, when) in stashes) rows.Add(new BranchRow { Kind = "stash", Name = name, Line = message + " · " + When(when) });
        }
        _branchRows = rows;
        _branchList.ItemsSource = rows;
        var again = rows.FirstOrDefault(r => r.Kind + ":" + r.Name == _branchPick) ?? rows.FirstOrDefault(r => r.Current) ?? rows.FirstOrDefault(r => r.Head.Length == 0);
        if (again is not null) _branchList.SelectedItem = again;
        else ShowBranchCard(null);
        ShowUnderway();
    }

    Control BranchView(BranchRow row)
    {
        if (row.Head.Length > 0) return new TextBlock { Classes = { "grouphead" }, Text = row.Head, Margin = new Thickness(10, 9, 8, 3) };
        var (icon, ink) = row.Kind switch
        {
            "remote" => ("cloud-download", "GitRenamed"),
            "tag" => ("tag", "AmberInk"),
            "stash" => ("archive", "LogExplain"),
            _ => ("git-branch", row.Current ? "GitStaged" : "CrumbInk"),
        };
        var name = Cell(row.Name, row.Current ? "GitStaged" : null, bold: row.Current);
        var ab = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 5, VerticalAlignment = VerticalAlignment.Center };
        if (row.Ahead > 0) ab.Children.Add(Cell("↑" + row.Ahead, "GitStaged"));
        if (row.Behind > 0) ab.Children.Add(Cell("↓" + row.Behind, "GitNew"));
        if (row.Note.Length > 0) ab.Children.Add(Pill(row.Note, row.NoteKind));
        if (row.Current) ab.Children.Add(Pill("текущая", "ok"));
        var grid = Cells("22,Auto,*,Auto", Sign(icon, ink), name, Cell("  " + row.Line, quiet: true), ab);
        grid.MinHeight = 28;
        grid.Margin = new Thickness(10, 0, 8, 0);
        return grid;
    }

    void ShowBranchCard(BranchRow? row)
    {
        if (_branchCard is null) return;
        _branchCard.Children.Clear();
        if (row is null) { _branchCard.Children.Add(Note("Выберите ветку слева.")); return; }
        var current = _state?.Branch ?? "";
        var body = new StackPanel { Spacing = 8 };
        var name = row.Name;
        if (row.Kind == "local")
        {
            if (row.Ref is { Upstream.Length: > 0 } r)
            {
                body.Children.Add(Text(Lang.F("{0} против {1}", name, r.Upstream), "caption"));
                body.Children.Add(Bar(row.Ahead, row.Behind));
                body.Children.Add(Text(row.Ahead + row.Behind == 0 ? "Совпадает с парой на сервере." : row.Behind == 0
                    ? Lang.F("Коммитов только у вас: {0}. Можно отправлять без слияния.", row.Ahead)
                    : row.Ahead == 0 ? Lang.F("На сервере новых: {0}. Заберите их: pull.", row.Behind)
                    : Lang.F("Ветки разошлись: у вас {0}, на сервере {1}. Нужно слияние.", row.Ahead, row.Behind), "note"));
            }
            else body.Children.Add(Text("У ветки нет пары на сервере: push -u отправит её и свяжет с парой.", "note"));
            var actions = new WrapPanel();
            void Add(Control b) { b.Margin = new Thickness(0, 0, 6, 6); actions.Children.Add(b); }
            var v = new Dictionary<string, object> { ["branch"] = name };
            if (!row.Current)
            {
                Add(OpCanon("switch", "перейти", () => v, sm: true));
                Add(OpCanon("merge", Lang.F("влить в {0}", current), () => v, sm: true));
                Add(OpCanon("compare", "сравнить с текущей", () => v, sm: true));
                Add(OpCanon("branch_delete", "удалить", () => v, sm: true, cls: "burn"));
            }
            var (remote, _) = Upstream();
            Add(OpCanon("push_upstream", "push -u", () => new() { ["remote"] = remote, ["branch"] = name }, sm: true));
            body.Children.Add(actions);
            _branchCard.Children.Add(Block(Lang.T("ВЕТКА") + " " + name, row.Current ? "GitStaged" : "Quasar", body, row.Current ? Pill("текущая", "ok") : null));
        }
        else if (row.Kind == "remote")
        {
            body.Children.Add(Text(Lang.F("Ветка на сервере, последний коммит: {0}", row.Ref?.Subject ?? ""), "note"));
            var actions = new WrapPanel();
            var v = new Dictionary<string, object> { ["branch"] = name };
            foreach (var b in new Control[] { OpCanon("compare", "сравнить с текущей", () => v, sm: true), OpCanon("merge", "влить в текущую", () => v, sm: true) })
            { b.Margin = new Thickness(0, 0, 6, 6); actions.Children.Add(b); }
            body.Children.Add(actions);
            body.Children.Add(Text("Чтобы работать в ней: впишите внизу её имя без remote (feature/x) и нажмите «создать и перейти» - Git свяжет её с этой.", "note"));
            _branchCard.Children.Add(Block(Lang.T("НА СЕРВЕРЕ") + " " + name, "GitRenamed", body));
        }
        else if (row.Kind == "tag")
        {
            body.Children.Add(Text(row.Ref?.Subject ?? "", "note"));
            _branchCard.Children.Add(Block(Lang.T("ТЕГ") + " " + name, "AmberInk", body));
        }
        else
        {
            body.Children.Add(Text(row.Line, "note"));
            body.Children.Add(Text("«Ящик» для правок, которые мешают перейти на другую ветку. Достать - последнее отложенное возвращается в рабочую папку.", "note"));
            var pop = OpCanon("stash_pop", "достать последнее", () => null, sm: true);
            body.Children.Add(pop);
            _branchCard.Children.Add(Block(Lang.T("ОТЛОЖЕНО") + " " + name, "LogExplain", body));
        }
        var stuck = new WrapPanel();
        foreach (var b in new Control[] { OpCanon("merge_abort", "git merge --abort", () => null, sm: true), OpCanon("cherry_pick_abort", "git cherry-pick --abort", () => null, sm: true), OpCanon("rebase", "rebase -i", () => new() { ["range"] = "HEAD~3" }, sm: true) })
        { b.Margin = new Thickness(0, 0, 6, 6); stuck.Children.Add(b); }
        _branchCard.Children.Add(Block("ЕСЛИ ЗАСТРЯЛИ", "BurnInk", new StackPanel { Spacing = 6, Children = { Text("Слияние или перенос коммита остановились на конфликте - прервать и вернуть как было. rebase -i - переписать цепочку своих коммитов (только неотправленных).", "note"), stuck } }));
        ApplyBusy();
    }

    /// <summary>A bar of how two branches stand: green - only here, blue - only there.</summary>
    static Control Bar(int ahead, int behind)
    {
        int total = Math.Max(1, ahead + behind);
        var grid = new Grid { Height = 6, ColumnDefinitions = new ColumnDefinitions($"{Math.Max(ahead, 0)}*,{Math.Max(behind, 0)}*,{(ahead + behind == 0 ? 1 : 0)}*") };
        var a = new Border { CornerRadius = new CornerRadius(3, 0, 0, 3) }.Ink(Border.BackgroundProperty, "GitStaged");
        var b = new Border { CornerRadius = new CornerRadius(0, 3, 3, 0) }.Ink(Border.BackgroundProperty, "GitNew");
        var c = new Border { CornerRadius = new CornerRadius(3) }.Ink(Border.BackgroundProperty, "SwitchBg");
        Grid.SetColumn(b, 1); Grid.SetColumn(c, 2);
        grid.Children.Add(a); grid.Children.Add(b); grid.Children.Add(c);
        ToolTip.SetTip(grid, Lang.F("только здесь: {0} · только там: {1}", ahead, behind));
        _ = total;
        return grid;
    }

    /// <summary>A merge, a cherry-pick, a revert or a rebase stopped half way: over the lists, in Burn Orange, with the way out.</summary>
    void ShowUnderway()
    {
        if (_underway is null) return;
        var what = _state?.Underway ?? "";
        _underway.IsVisible = what.Length > 0;
        if (what.Length == 0) return;
        var abort = what switch { "merge" => "merge_abort", "cherry-pick" => "cherry_pick_abort", _ => "" };
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto"), Margin = new Thickness(10, 7) };
        row.Children.Add(Sign("git-merge-conflict", "BurnInk"));
        var words = Text(Lang.F("Идёт {0}: конфликтов {1}. Поправьте файлы с буквой U, положите в индекс (F5) и сделайте коммит - или прервите.", what, _state?.ConflictCount ?? 0), "note");
        words.Margin = new Thickness(10, 0);
        Grid.SetColumn(words, 1);
        row.Children.Add(words);
        if (abort.Length > 0) { var b = OpCanon(abort, "прервать", () => null, sm: true, cls: "burn"); Grid.SetColumn(b, 2); row.Children.Add(b); }
        _underway.Child = row;
        _underway.CornerRadius = new CornerRadius(8);
        _underway.BorderThickness = new Thickness(1);
        _underway.Ink(Border.BorderBrushProperty, "WarnBorder").Ink(Border.BackgroundProperty, "WarnBg");
    }
}
