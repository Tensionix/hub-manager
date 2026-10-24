using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json.Nodes;
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
using Ellipse = Avalonia.Controls.Shapes.Ellipse;

namespace AudionHubManager;

/// <summary>
/// ИЗМЕНЕНИЯ: what differs from the last commit and how to save it. Over the page - the flow of the three places of Git
/// (the working folder, the index, the history) and the server, with their counts: the idea of Git a person meets every
/// day. On the left - the file panel in the manner of Sync Tools: the files by their stage, or the folders of the layer;
/// Space and Insert mark files, as in Total Commander, and the marked ones go into the index or into a commit of their
/// own. On the right - the difference of the file chosen and the commit being put together. Under the page - F2, F5,
/// F6, F8, the subject of the commit and КОММИТ.
/// </summary>
public partial class MainWindow
{
    sealed class FileRow
    {
        public string Key = "", Path = "", Group = "", Head = "", OutReason = "";
        public char Letter;
        public bool Staged, IsDir, Up, Out;
        public int Add = -1, Del = -1;
        public long Size = -1;
        public DateTime? Modified;
    }

    /// <summary>The chosen file (its key - group and path) and the marked ones (paths).</summary>
    string _selected = "";
    readonly HashSet<string> _marked = new(StringComparer.Ordinal);
    /// <summary>"all", "work", "index": the flow of the three places narrows the panel to one place.</summary>
    string _stageFilter = "all";
    /// <summary>The folder of the layer the panel shows in the mode of all files, relative to its root.</summary>
    string _browse = "";
    string _diffMode = "work";
    string _quick = "";
    readonly Dictionary<string, string> _outOfProfile = new(StringComparer.Ordinal);

    // The controls of the page, kept while it is in sight.
    ListBox? _files;
    TextBlock? _panelStatus, _crumbs;
    Grid? _flow;
    Panel? _diffBody;
    StackPanel? _diffHead;
    TextBox? _subject, _scope, _series, _version;
    CheckBox? _tagBox, _onlyMarked, _amend;
    StackPanel? _typeRow;
    TextBlock? _preview, _guard;
    StackPanel? _modeRow;

    static readonly string[] CommitTypes = { "docs", "code", "fix", "ui", "test", "chore", "audit" };

    Control BuildChanges()
    {
        var page = new Grid { RowDefinitions = new RowDefinitions("Auto,*") };
        _flow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto,*,Auto,*,Auto,*"), Margin = new Thickness(0, 0, 0, 10) };
        page.Children.Add(_flow);
        // The file panel takes 380: beside the column of projects the difference and the block КОММИТ need the rest.
        var split = new Grid { ColumnDefinitions = new ColumnDefinitions("380,10,*") };
        Grid.SetRow(split, 1);
        page.Children.Add(split);
        split.Children.Add(BuildPanel());
        var right = new Grid { RowDefinitions = new RowDefinitions("*,Auto") };
        Grid.SetColumn(right, 2);
        split.Children.Add(right);
        right.Children.Add(BuildDiff());
        var composer = BuildComposer();
        Grid.SetRow(composer, 1);
        right.Children.Add(composer);

        // The bar: what is done every day, in the order it is done.
        _subject = Grow(Field("тема коммита - что и зачем", "", tip: "Тема коммита: что сделано и зачем, коротко. Тип, область и версия - в блоке КОММИТ над этой строкой; сообщение целиком - там же, в рамке.", id: "commit_subject"));
        _subject.TextChanged += (_, _) => ShowPreview();
        _subject.KeyDown += (_, e) => { if (e.Key == Key.Enter && e.KeyModifiers.HasFlag(KeyModifiers.Control)) { Commit(); e.Handled = true; } };
        SetOps(
            Op("обновить", () => RunCanon("status"), Canon.Get("status").Tip(), "read", "F2", id: "op_refresh", command: Canon.Get("status").Short),
            Op("в индекс", Stage, Canon.Get("add").Tip() + "\n" + Lang.T("Берёт отмеченные файлы, а без отметок - выбранный. Файлы вне профиля не берёт."), "local", "F5", id: "op_stage", command: Canon.Get("add").Short),
            Op("из индекса", Unstage, Canon.Get("unstage").Tip(), "local", "F6", id: "op_unstage", command: Canon.Get("unstage").Short),
            Op("вернуть", Restore, Canon.Get("restore").Tip(), "danger", "F8", "burn", "op_restore", command: Canon.Get("restore").Short),
            null,
            _subject,
            Op("КОММИТ", Commit, Canon.Get("commit").Tip() + "\n" + Lang.T("Перед коммитом окно проверит файлы индекса профилем проекта."), "local", "Ctrl+⏎", "fill", "op_commit", command: Canon.Get("commit").Short),
            null,
            OpCanon("push", "push", PushValues));
        _keys[Key.F2] = () => RunCanon("status");
        _keys[Key.F5] = Stage;
        _keys[Key.F6] = Unstage;
        _keys[Key.F8] = Restore;
        _ctrlEnter = Commit;
        ShowFlow();
        return page;
    }

    // ------------------------------------------------------------ the flow of the three places

    void ShowFlow()
    {
        if (_flow is null) return;
        _flow.Children.Clear();
        var s = _state;
        void Add(Control control, int column) { Grid.SetColumn(control, column); _flow.Children.Add(control); }
        Add(Stage("work", "folder-pen", "GitModified", "РАБОЧАЯ ПАПКА",
            s is null ? "-" : Lang.F("{0} изменено · {1} новых", s.ChangedCount, s.NewCount),
            "Рабочая папка: файлы, как они лежат на диске. Изменения здесь Git видит, но в коммит они пойдут только через индекс. Нажмите - панель покажет только их."), 0);
        Add(FlowArrow("add", "git add", "в индекс"), 1);
        Add(Stage("index", "inbox", "GitStaged", "ИНДЕКС",
            s is null ? "-" : Lang.F("{0} к коммиту", s.StagedCount),
            "Индекс (staging): «стол перед коммитом». Сюда кладут то, что войдёт в следующий коммит, - можно собрать коммит из части правок. Нажмите - только файлы индекса."), 2);
        Add(FlowArrow("commit", "git commit", "в историю"), 3);
        Add(Stage("history", "git-commit-vertical", "Quasar", "ИСТОРИЯ",
            s is null ? "-" : s.NoCommits ? Lang.T("коммитов ещё нет") : (s.Detached ? "HEAD" : s.Branch) + (s.Head.Length >= 7 ? " · " + s.Head[..7] : ""),
            "Локальная история: коммиты на этом компьютере. Нажмите - раздел ИСТОРИЯ."), 4);
        Add(FlowArrow("push", "git push", "на сервер"), 5);
        var remote = s?.Upstream is { Length: > 0 } up ? up.Split('/')[0] : "";
        Add(Stage("server", "cloud-upload", "GitRenamed", remote.Length > 0 ? remote.ToUpperInvariant() : "СЕРВЕР",
            s is null || remote.Length == 0 ? Lang.T("нет пары на сервере") : s.Ahead + s.Behind == 0 ? Lang.T("всё отправлено") : Lang.F("↑{0} не отправлено · ↓{1} новых", s.Ahead, s.Behind),
            "Сервер (remote): GitHub, GitLab, Forgejo. Нажмите - раздел СИНХРОНИЗАЦИЯ."), 6);
    }

    ToggleButton Stage(string id, string icon, string ink, string name, string line, string tip)
    {
        var mark = new Border { Classes = { "stageicon" }, Child = Sign(icon, ink) };
        var words = new StackPanel { VerticalAlignment = VerticalAlignment.Center, Children = { Text(name, "stagename"), new TextBlock { Classes = { "stageline" }, Text = line } } };
        var card = new ToggleButton
        {
            Classes = { "switch", "stage" }, IsChecked = _stageFilter == id,
            Content = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10, Children = { mark, words } },
        };
        Avalonia.Automation.AutomationProperties.SetAutomationId(card, "stage_" + id);
        ToolTip.SetTip(card, Lang.T(tip));
        card.Click += (_, _) =>
        {
            if (id == "history") { SelectSection("history"); return; }
            if (id == "server") { SelectSection("sync"); return; }
            _stageFilter = _stageFilter == id ? "all" : id;
            if (_settings.PanelMode != "changes") { _settings.PanelMode = "changes"; _settings.Save(); MarkMode(); }
            ShowFlow();
            ShowFiles();
        };
        return card;
    }

    Control FlowArrow(string canonId, string command, string word)
    {
        var line = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Center, Children =
        {
            new Border { Width = 38, Height = 1, VerticalAlignment = VerticalAlignment.Center }.Ink(Border.BackgroundProperty, "CrumbInk"),
            Sign("chevron-right", "CrumbInk"),
        } };
        var panel = new StackPanel { Margin = new Thickness(6, 0), VerticalAlignment = VerticalAlignment.Center, Spacing = 1, Children =
        {
            new TextBlock { Classes = { "flowcmd" }, Text = command }, line, new TextBlock { Classes = { "arrowword" }, Text = Lang.T(word), HorizontalAlignment = HorizontalAlignment.Center },
        } };
        if (Canon.Find(canonId) is { } entry) ToolTip.SetTip(panel, entry.Tip());
        return panel;
    }

    // ------------------------------------------------------------ the file panel

    Control BuildPanel()
    {
        _modeRow = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 0 };
        MarkMode();
        var quick = Field("найти (F)", _quick, 120, "Сузить список: остаются только пути с этим текстом. Esc - снять.", "panel_quick");
        quick.Height = quick.MinHeight = 24;
        quick.TextChanged += (_, _) => { _quick = quick.Text ?? ""; ShowFiles(); };
        quick.KeyDown += (_, e) => { if (e.Key == Key.Escape) { quick.Text = ""; _files?.Focus(); e.Handled = true; } };
        var masks = new Button { Classes = { "tool" }, Content = Sign("list-checks"), Margin = new Thickness(4, 0, 0, 0) };
        ToolTip.SetTip(masks, Lang.T("Отметить по выбору: все изменённые, все новые, все в индексе, по маске; или снять все отметки."));
        masks.Flyout = MaskMenu();
        var refresh = new Button { Classes = { "tool" }, Content = Sign("refresh-cw"), Margin = new Thickness(4, 0, 0, 0) };
        ToolTip.SetTip(refresh, Lang.T("Перечитать состояние репозитория (без записи в терминал)."));
        refresh.Click += (_, _) => RefreshSoon(0);
        var head = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto,Auto,Auto"), Margin = new Thickness(8, 7, 8, 6) };
        head.Children.Add(_modeRow);
        Grid.SetColumn(quick, 2); head.Children.Add(quick);
        Grid.SetColumn(masks, 3); head.Children.Add(masks);
        Grid.SetColumn(refresh, 4); head.Children.Add(refresh);

        _crumbs = new TextBlock { Classes = { "caption" } };
        _files = Rows("files");
        _files.ItemTemplate = new FuncDataTemplate<FileRow>((row, _) => row is null ? new Panel() : FileView(row), supportsRecycling: false);
        _files.SelectionChanged += (_, _) =>
        {
            if (_files.SelectedItem is FileRow row && !row.Up && row.Head.Length == 0) { _selected = row.Key; _ = ShowDiff(row); }
        };
        _files.DoubleTapped += (_, _) => OpenRow();
        _files.KeyDown += OnPanelKey;
        _panelStatus = new TextBlock { Classes = { "status" } };

        var body = new DockPanel();
        var heads = Heads("20,24,*,70,64", "", "", Lang.T("ИМЯ"), "±", Lang.T("РАЗМЕР"));
        foreach (var top in new Control[] { head, new Border { Classes = { "hsep" }, Padding = new Thickness(0) }, new FadeBox(_crumbs) { Margin = new Thickness(10, 0, 10, 4) }, heads })
        {
            DockPanel.SetDock(top, Dock.Top);
            body.Children.Add(top);
        }
        var status = new FadeBox(_panelStatus) { Margin = new Thickness(10, 5, 10, 6) };
        DockPanel.SetDock(status, Dock.Bottom);
        body.Children.Add(status);
        body.Children.Add(_files);
        return new Border { Classes = { "pane" }, Child = body };
    }

    void MarkMode()
    {
        if (_modeRow is null) return;
        _modeRow.Children.Clear();
        foreach (var (mode, word, tip) in new[]
        {
            ("changes", "ИЗМЕНЕНИЯ", "Только то, что отличается от последнего коммита, по стадиям: конфликты, в индексе, изменены, новые."),
            ("all", "ВСЕ ФАЙЛЫ", "Папки слоя целиком, с буквой Git у каждого изменённого файла. Enter - в папку, Backspace - наверх."),
        })
        {
            var button = new ToggleButton { Classes = { "switch" }, Content = Lang.T(word), IsChecked = _settings.PanelMode == mode, Margin = new Thickness(0, 0, 4, 0) };
            ToolTip.SetTip(button, Lang.T(tip));
            Avalonia.Automation.AutomationProperties.SetAutomationId(button, "panel_" + mode);
            button.Click += (_, _) =>
            {
                _settings.PanelMode = mode;
                _settings.Save();
                _stageFilter = "all";
                MarkMode();
                ShowFlow();
                ShowFiles();
            };
            _modeRow.Children.Add(button);
        }
    }

    MenuFlyout MaskMenu()
    {
        var menu = new MenuFlyout { Placement = PlacementMode.BottomEdgeAlignedRight };
        void Item(string word, Func<FileRow, bool> pick)
        {
            var item = new MenuItem { Header = Lang.T(word) };
            item.Click += (_, _) =>
            {
                foreach (var row in VisibleRows().Where(r => r.Head.Length == 0 && !r.Up && !r.IsDir && pick(r))) _marked.Add(row.Path);
                ShowFiles();
            };
            menu.Items.Add(item);
        }
        Item("Отметить все изменённые", r => r.Group == "changed");
        Item("Отметить все новые", r => r.Group == "new");
        Item("Отметить все в индексе", r => r.Group == "staged");
        Item("Отметить всё видимое", _ => true);
        Item("Отметить *.md", r => r.Path.EndsWith(".md", StringComparison.OrdinalIgnoreCase));
        menu.Items.Add(new Separator());
        var clear = new MenuItem { Header = Lang.T("Снять все отметки") };
        clear.Click += (_, _) => { _marked.Clear(); ShowFiles(); };
        menu.Items.Add(clear);
        return menu;
    }

    List<FileRow> _rows = new();

    IEnumerable<FileRow> VisibleRows() => _rows;

    /// <summary>The rows of the panel from the state of the repository: by stage, or the folder being looked at.</summary>
    void ShowFiles()
    {
        if (_files is null) return;
        var rows = new List<FileRow>();
        var s = _state;
        if (_settings.PanelMode == "changes")
        {
            if (s is not null)
            {
                void Group(string group, string head, IEnumerable<GitFile> files, Func<GitFile, char> letter, bool staged)
                {
                    var list = files.Where(f => _quick.Length == 0 || f.Path.Contains(_quick, StringComparison.OrdinalIgnoreCase)).ToList();
                    if (list.Count == 0) return;
                    rows.Add(new FileRow { Key = "#" + group, Head = Lang.T(head) + "  " + list.Count, Group = group });
                    foreach (var f in list.OrderBy(f => f.Path, StringComparer.OrdinalIgnoreCase))
                    {
                        var path = f.Path;
                        var row = new FileRow { Key = group + ":" + path, Path = path, Group = group, Letter = letter(f), Staged = staged, Add = f.Added, Del = f.Removed };
                        try { var info = new FileInfo(System.IO.Path.Combine(s.Root, path)); if (info.Exists) { row.Size = info.Length; row.Modified = info.LastWriteTime; } } catch { }
                        if (_outOfProfile.TryGetValue(path, out var reason)) { row.Out = true; row.OutReason = reason; }
                        rows.Add(row);
                    }
                }
                if (_stageFilter == "all") Group("conflict", "КОНФЛИКТЫ — поправьте и положите в индекс", s.Files.Where(f => f.Conflict), _ => 'U', false);
                if (_stageFilter is "all" or "index") Group("staged", "В ИНДЕКСЕ — войдёт в коммит", s.Files.Where(f => f.Staged), f => f.Index, true);
                if (_stageFilter is "all" or "work")
                {
                    Group("changed", "ИЗМЕНЕНЫ — ещё не в индексе", s.Files.Where(f => !f.Untracked && !f.Conflict && f.Work != '.'), f => f.Work, false);
                    Group("new", "НОВЫЕ — Git их ещё не знает", s.Files.Where(f => f.Untracked), _ => '?', false);
                }
            }
            _crumbs!.Text = Lang.T(LayerName(_settings.Layer)) + " › " + (_project?.Name ?? "") + " › " + Lang.T(_stageFilter switch
            {
                "work" => "только рабочая папка", "index" => "только индекс", _ => "только изменения",
            });
        }
        else rows.AddRange(BrowseRows());
        _rows = rows;
        var keep = _selected;
        _files.ItemsSource = rows;
        var again = rows.FirstOrDefault(r => r.Key == keep) ?? rows.FirstOrDefault(r => r.Head.Length == 0 && !r.Up);
        if (again is not null) _files.SelectedItem = again;
        else ShowNoDiff();
        int total = s?.Files.Count ?? 0;
        _panelStatus!.Text = (s is null ? Lang.T("нет репозитория") : Lang.F("изменений: {0}", total))
            + (_marked.Count > 0 ? " · " + Lang.F("отмечено {0}", _marked.Count) : "")
            + (_outOfProfile.Count > 0 ? " · " + Lang.F("вне профиля {0}", _outOfProfile.Count) : "")
            + "  ·  " + Lang.T("пробел, Insert - отметить");
    }

    /// <summary>The folder being looked at in the mode of all files: "..", the folders, then the files, each with its letter of Git.</summary>
    List<FileRow> BrowseRows()
    {
        var rows = new List<FileRow>();
        var root = LayerFolder();
        _crumbs!.Text = Lang.T(LayerName(_settings.Layer)) + " › " + (_project?.Name ?? "") + (_browse.Length > 0 ? " › " + _browse.Replace('/', '›') : "");
        if (root.Length == 0 || !Directory.Exists(root)) return rows;
        var folder = _browse.Length > 0 ? System.IO.Path.Combine(root, _browse) : root;
        if (!Directory.Exists(folder)) { _browse = ""; folder = root; }
        var letters = new Dictionary<string, (char Letter, bool Staged)>(StringComparer.OrdinalIgnoreCase);
        foreach (var f in _state?.Files ?? new())
        {
            letters[f.Path] = (f.Letter, f.Staged && !f.Unstaged);
            // A folder carries the letter of what changed inside it.
            var parts = f.Path.Split('/');
            for (int i = 1; i < parts.Length; i++) letters.TryAdd(string.Join('/', parts.Take(i)), ('M', false));
        }
        if (_browse.Length > 0) rows.Add(new FileRow { Key = "..", Path = "..", Up = true, IsDir = true });
        try
        {
            var dirs = Directory.EnumerateDirectories(folder).Select(d => new DirectoryInfo(d)).Where(d => d.Name != ".git").OrderBy(d => d.Name, StringComparer.OrdinalIgnoreCase);
            var files = Directory.EnumerateFiles(folder).Select(f => new FileInfo(f)).OrderBy(f => f.Name, StringComparer.OrdinalIgnoreCase);
            foreach (var d in dirs)
            {
                var rel = (_browse.Length > 0 ? _browse + "/" : "") + d.Name;
                if (_quick.Length > 0 && !d.Name.Contains(_quick, StringComparison.OrdinalIgnoreCase)) continue;
                var row = new FileRow { Key = "dir:" + rel, Path = rel, IsDir = true, Modified = d.LastWriteTime };
                if (letters.TryGetValue(rel, out var l)) row.Letter = l.Letter;
                rows.Add(row);
            }
            foreach (var f in files)
            {
                var rel = (_browse.Length > 0 ? _browse + "/" : "") + f.Name;
                if (_quick.Length > 0 && !f.Name.Contains(_quick, StringComparison.OrdinalIgnoreCase)) continue;
                var row = new FileRow { Key = "file:" + rel, Path = rel, Size = f.Length, Modified = f.LastWriteTime };
                if (letters.TryGetValue(rel, out var l)) { row.Letter = l.Letter; row.Staged = l.Staged; row.Group = l.Letter == '?' ? "new" : l.Staged ? "staged" : "changed"; }
                rows.Add(row);
            }
        }
        catch (Exception ex) { SetStatus(Lang.F("Папка не читается: {0}", ex.Message)); }
        return rows;
    }

    Control FileView(FileRow row)
    {
        if (row.Head.Length > 0)
            return new TextBlock { Classes = { "grouphead" }, Text = row.Head, Margin = new Thickness(8, 8, 8, 3) };
        var mark = row.IsDir ? (Control)Sign("folder", "GitModified") : new Ellipse { Width = 7, Height = 7, IsVisible = _marked.Contains(row.Path), HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center }
            .Ink(Avalonia.Controls.Shapes.Shape.FillProperty, "Tangerine");
        Control? letter = row.Letter != '\0' ? Letter(row.Out ? '-' : row.Letter, row.Staged) : null;
        var nameInk = row.Out ? "GitOut" : row.Letter == '\0' ? null : LetterInk(row.Letter, row.Staged);
        // The name takes its column and no more: a long path fades out at its end (the whole of it is in the tip of the row),
        // not over the columns beside it.
        var name = new DockPanel { VerticalAlignment = VerticalAlignment.Center };
        var nameText = Cell(row.Up ? ".." : _settings.PanelMode == "all" ? System.IO.Path.GetFileName(row.Path) : row.Path, nameInk);
        if (row.Letter == 'D') nameText.TextDecorations = TextDecorations.Strikethrough;
        if (row.IsDir) nameText.FontWeight = FontWeight.SemiBold;
        if (row.Out)
        {
            var pill = Pill("вне профиля");
            pill.Margin = new Thickness(6, 0, 0, 0);
            DockPanel.SetDock(pill, Dock.Right);
            name.Children.Add(pill);
        }
        name.Children.Add(new FadeBox(nameText) { VerticalAlignment = VerticalAlignment.Center });
        var lines = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 5, VerticalAlignment = VerticalAlignment.Center };
        if (row.Add > 0) lines.Children.Add(Cell("+" + row.Add, "GitStaged"));
        if (row.Del > 0) lines.Children.Add(Cell("−" + row.Del, "GitDeleted"));
        var size = Cell(row.Size >= 0 ? Size(row.Size) : "", quiet: true);
        var grid = Cells("20,24,*,70,64", mark, letter, name, lines, size);
        grid.MinHeight = 25;
        if (row.Out) ToolTip.SetTip(grid, Lang.F("Вне профиля ({0}): в GIT-КОПИЮ и в коммит через Hub Manager этот файл не попадёт. Так в Git не уходят сборки, логи и секреты.", row.OutReason));
        else if (row.Path.Length > 0) ToolTip.SetTip(grid, row.Path + (row.Modified is { } m ? "\n" + m.ToString("dd.MM.yyyy HH:mm") : ""));
        return grid;
    }

    static string Size(long bytes) => bytes < 1024 ? bytes + Lang.T(" Б") : bytes < 1024 * 1024 ? (bytes / 1024.0).ToString("0.#", Lang.Culture) + Lang.T(" КБ") : (bytes / 1048576.0).ToString("0.#", Lang.Culture) + Lang.T(" МБ");

    void OnPanelKey(object? sender, KeyEventArgs e)
    {
        if (_files?.SelectedItem is not FileRow row) return;
        if (e.Key is Key.Space or Key.Insert)
        {
            if (row.Head.Length == 0 && !row.Up && !row.IsDir)
            {
                if (!_marked.Remove(row.Path)) _marked.Add(row.Path);
                int at = _files.SelectedIndex;
                ShowFiles();
                _files.SelectedIndex = e.Key == Key.Insert ? Math.Min(at + 1, _rows.Count - 1) : at;
            }
            e.Handled = true;
        }
        else if (e.Key == Key.Enter) { OpenRow(); e.Handled = true; }
        else if (e.Key == Key.Back && _settings.PanelMode == "all" && _browse.Length > 0) { GoUp(); e.Handled = true; }
    }

    void OpenRow()
    {
        if (_files?.SelectedItem is not FileRow row) return;
        if (row.Up) { GoUp(); return; }
        if (row.IsDir && _settings.PanelMode == "all") { _browse = row.Path; _selected = ""; ShowFiles(); return; }
        if (!row.IsDir) OpenInCode(System.IO.Path.Combine(LayerFolder(), row.Path));
    }

    void GoUp()
    {
        var cut = _browse.LastIndexOf('/');
        _selected = "dir:" + _browse;
        _browse = cut > 0 ? _browse[..cut] : "";
        ShowFiles();
    }

    // ------------------------------------------------------------ the difference

    Control BuildDiff()
    {
        _diffHead = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, Margin = new Thickness(10, 7, 8, 6), VerticalAlignment = VerticalAlignment.Center };
        _diffBody = new Panel();
        var body = new DockPanel();
        var top = new Border { Classes = { "hsep" }, BorderThickness = new Thickness(0, 0, 0, 1), Padding = new Thickness(0), Child = _diffHead };
        DockPanel.SetDock(top, Dock.Top);
        body.Children.Add(top);
        body.Children.Add(_diffBody);
        return new Border { Classes = { "pane" }, Child = body, Margin = new Thickness(0, 0, 0, 10) };
    }

    void ShowNoDiff()
    {
        if (_diffHead is null || _diffBody is null) return;
        _diffHead.Children.Clear();
        _diffHead.Children.Add(Text("РАЗНИЦА", "blocktitle"));
        _diffBody.Children.Clear();
        _diffBody.Children.Add(Note(_state is null ? "Здесь будет разница выбранного файла." : _state.Files.Count == 0
            ? "Изменений нет: рабочая папка совпадает с последним коммитом."
            : "Выберите файл слева - здесь будет его разница: что добавлено (зелёным) и что убрано."));
    }

    int _diffAsk;

    async Task ShowDiff(FileRow row)
    {
        if (_diffHead is null || _diffBody is null || ActiveRoot(true) is not { } root) return;
        int ask = ++_diffAsk;
        var mode = row.Group switch { "staged" => "cached", "new" => "new", _ when _settings.PanelMode == "all" && row.Letter == '\0' => "file", _ => _diffMode == "head" ? "head" : "work" };
        if (row.Group == "staged" && _diffMode == "head") mode = "head";
        string text;
        if (mode is "new" or "file")
        {
            text = ReadText(System.IO.Path.Combine(root, row.Path));
        }
        else
        {
            var answer = await Git.Diff(root, row.Path, mode);
            text = answer.Ok ? answer.Out : answer.Err;
        }
        if (ask != _diffAsk) return;
        _diffHead.Children.Clear();
        _diffHead.Children.Add(Sign("file-text"));
        _diffHead.Children.Add(new TextBlock { Text = System.IO.Path.GetFileName(row.Path), FontWeight = FontWeight.Bold, VerticalAlignment = VerticalAlignment.Center });
        if (row.Letter != '\0') _diffHead.Children.Add(Letter(row.Letter, row.Staged));
        if (row.Add > 0) _diffHead.Children.Add(Cell("+" + row.Add, "GitStaged"));
        if (row.Del > 0) _diffHead.Children.Add(Cell("−" + row.Del, "GitDeleted"));
        if (row.Group is "changed" or "staged" or "conflict")
        {
            var seg = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(10, 0, 0, 0) };
            foreach (var (m, word, id) in new[] { ("work", "НЕ В ИНДЕКСЕ", "diff"), ("cached", "В ИНДЕКСЕ", "diff_cached"), ("head", "ПРОТИВ HEAD", "diff_head") })
            {
                var on = mode == m;
                var b = new ToggleButton { Classes = { "switch" }, Content = Lang.T(word), IsChecked = on, Margin = new Thickness(0, 0, 3, 0) };
                if (Canon.Find(id) is { } entry) ToolTip.SetTip(b, entry.Tip(Canon.Show(entry.Argv(new() { ["path"] = row.Path }))));
                b.Click += (_, _) =>
                {
                    _diffMode = m;
                    var target = row;
                    if (m == "cached" && row.Group != "staged") target = _rows.FirstOrDefault(r => r.Group == "staged" && r.Path == row.Path) ?? row;
                    if (m == "work" && row.Group == "staged") target = _rows.FirstOrDefault(r => r.Group == "changed" && r.Path == row.Path) ?? row;
                    if (target != row && _files is not null) _files.SelectedItem = target;
                    else _ = ShowDiff(row);
                };
                seg.Children.Add(b);
            }
            _diffHead.Children.Add(seg);
        }
        var tools = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(6, 0, 0, 0) };
        var blame = new Button { Classes = { "tool" }, Content = Sign("scan-search") };
        ToolTip.SetTip(blame, Canon.Get("blame").Tip());
        blame.Click += (_, _) => RunCanon("blame", new() { ["path"] = row.Path });
        var history = new Button { Classes = { "tool" }, Content = Sign("history") };
        ToolTip.SetTip(history, Lang.T("История этого файла: какие коммиты его меняли - раздел ИСТОРИЯ."));
        history.Click += (_, _) => { _historyFile = row.Path; SelectSection("history"); };
        var code = new Button { Classes = { "tool" }, Content = Sign("file-text") };
        ToolTip.SetTip(code, Lang.T("Открыть файл в VS Code."));
        code.Click += (_, _) => OpenInCode(System.IO.Path.Combine(root, row.Path));
        tools.Children.Add(blame);
        tools.Children.Add(history);
        tools.Children.Add(code);
        _diffHead.Children.Add(tools);
        _diffBody.Children.Clear();
        _diffBody.Children.Add(DiffView(text, mode is "new" or "file", mode == "file"));
    }

    static string ReadText(string file)
    {
        try
        {
            var info = new FileInfo(file);
            if (!info.Exists) return "";
            if (info.Length > 1_000_000) return "\0big";
            var bytes = File.ReadAllBytes(file);
            if (Array.IndexOf(bytes, (byte)0) >= 0) return "\0binary";
            return Encoding.UTF8.GetString(bytes);
        }
        catch (Exception ex) { return "\0" + ex.Message; }
    }

    sealed record DiffLine(string Kind, string Old, string New, string Text);

    /// <summary>
    /// A difference as it is read: the numbers of the old and the new line, the line itself on the ground of what
    /// happened to it - added green, removed coral, the head of a hunk in the sea colour. A whole new file is all added;
    /// a file looked at in the mode of all files is shown as it is.
    /// </summary>
    static Control DiffView(string text, bool whole, bool plain)
    {
        if (text.StartsWith('\0'))
            return Note(text == "\0binary" ? "Двоичный файл: его разница не показывается." : text == "\0big" ? "Файл больше мегабайта: откройте его в VS Code." : text[1..]);
        var lines = new List<DiffLine>();
        if (whole)
        {
            int n = 0;
            foreach (var line in text.Replace("\r\n", "\n").Split('\n').Take(4000))
            {
                n++;
                lines.Add(new DiffLine(plain ? "" : "add", "", n.ToString(), line));
            }
        }
        else
        {
            int oldNo = 0, newNo = 0;
            foreach (var raw in text.Replace("\r\n", "\n").Split('\n').Take(6000))
            {
                if (raw.StartsWith("diff --git") || raw.StartsWith("index ") || raw.StartsWith("--- ") || raw.StartsWith("+++ ") || raw.StartsWith("new file") || raw.StartsWith("deleted file") || raw.StartsWith("similarity") || raw.StartsWith("rename ")) continue;
                if (raw.StartsWith("@@"))
                {
                    var m = System.Text.RegularExpressions.Regex.Match(raw, @"@@ -(\d+)(?:,\d+)? \+(\d+)");
                    if (m.Success) { oldNo = int.Parse(m.Groups[1].Value); newNo = int.Parse(m.Groups[2].Value); }
                    lines.Add(new DiffLine("hunk", "", "", raw));
                }
                else if (raw.StartsWith('+')) lines.Add(new DiffLine("add", "", (newNo++).ToString(), raw[1..]));
                else if (raw.StartsWith('-')) lines.Add(new DiffLine("del", (oldNo++).ToString(), "", raw[1..]));
                else if (raw.StartsWith('\\')) lines.Add(new DiffLine("hunk", "", "", raw));
                else if (raw.Length > 0 || newNo > 0) lines.Add(new DiffLine("", (oldNo++).ToString(), (newNo++).ToString(), raw.Length > 0 ? raw[1..] : ""));
            }
            while (lines.Count > 0 && lines[^1].Kind == "" && lines[^1].Text.Length == 0) lines.RemoveAt(lines.Count - 1);
            if (lines.Count == 0) return Note("Разницы нет: этот вид сравнения пуст (возможно, изменения целиком в другом месте - в индексе или в рабочей папке).");
        }
        var list = new ItemsControl
        {
            ItemsSource = lines,
            ItemsPanel = new FuncTemplate<Panel?>(() => new VirtualizingStackPanel()),
            ItemTemplate = new FuncDataTemplate<DiffLine>((line, _) =>
            {
                if (line is null) return new Panel();
                var row = new Grid { ColumnDefinitions = new ColumnDefinitions("40,40,16,*") };
                if (line.Kind == "add") row.Ink(Panel.BackgroundProperty, "DiffAddBg");
                else if (line.Kind == "del") row.Ink(Panel.BackgroundProperty, "DiffDelBg");
                else if (line.Kind == "hunk") row.Ink(Panel.BackgroundProperty, "DiffHunkBg");
                TextBlock T(string t, int col, string ink, TextAlignment align = TextAlignment.Left)
                {
                    var b = new TextBlock { Text = t, TextAlignment = align, Classes = { "mono" }, Margin = new Thickness(col < 2 ? 0 : 4, 1, col < 2 ? 8 : 0, 1) }.Ink(TextBlock.ForegroundProperty, ink);
                    Grid.SetColumn(b, col);
                    row.Children.Add(b);
                    return b;
                }
                T(line.Old, 0, "CrumbInk", TextAlignment.Right);
                T(line.New, 1, "CrumbInk", TextAlignment.Right);
                T(line.Kind == "add" ? "+" : line.Kind == "del" ? "−" : "", 2, line.Kind == "add" ? "GitStaged" : "GitDeleted");
                var body = T(line.Text, 3, line.Kind == "hunk" ? "LogExplain" : "TextMain");
                body.TextWrapping = TextWrapping.NoWrap;
                return row;
            }),
        };
        list.Ink(TextBlock.FontSizeProperty, "FontLog");
        var scroll = new ScrollViewer { Content = list, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto };
        return scroll;
    }

    // ------------------------------------------------------------ the commit

    Control BuildComposer()
    {
        _typeRow = new StackPanel { Orientation = Orientation.Horizontal };
        MarkTypes();
        _scope = Field("область", _settings.CommitScope, 110, "Область коммита (scope): часть проекта - readme, mirror, ui. Можно пусто.", "commit_scope");
        _scope.Height = _scope.MinHeight = 24;
        _scope.TextChanged += (_, _) => { _settings.CommitScope = _scope.Text ?? ""; ShowPreview(); };
        var row1 = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, Children = { Text("ТИП", "colhead"), _typeRow, VSep(18), Text("ОБЛАСТЬ", "colhead"), _scope } };
        _series = Field("серия", _settings.VersionSeries, 110, "Серия версий: начало имени тега (projection-v0.1.2). Пусто - без версии в сообщении.", "version_series");
        _version = Field("v0.1.0", "", 80, "Номер версии этого коммита. Окно предлагает следующий по тегам серии.", "version_value");
        foreach (var box in new[] { _series, _version }) box.Height = box.MinHeight = 24;
        _series.TextChanged += (_, _) => { _settings.VersionSeries = _series.Text ?? ""; ShowPreview(); };
        _version.TextChanged += (_, _) => ShowPreview();
        var bumps = new StackPanel { Orientation = Orientation.Horizontal };
        foreach (var bump in new[] { "patch", "minor", "major" })
        {
            var b = Chip(bump, _settings.VersionBump == bump, () => { _settings.VersionBump = bump; _settings.Save(); _ = NextVersion(); },
                "Какую часть версии поднять: patch - исправление (0.1.1 → 0.1.2), minor - новое умение (0.1 → 0.2), major - несовместимое (0 → 1).");
            bumps.Children.Add(b);
        }
        _tagBox = new CheckBox { Classes = { "tick" }, Content = Lang.T("поставить тег") };
        ToolTip.SetTip(_tagBox, Canon.Get("tag").Tip());
        _tagBox.IsCheckedChanged += (_, _) => ShowPreview();
        var row2 = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, Children = { Text("ВЕРСИЯ", "colhead"), _series, _version, bumps, _tagBox } };
        _onlyMarked = new CheckBox { Classes = { "tick" }, Content = Lang.T("только отмеченные") };
        ToolTip.SetTip(_onlyMarked, Canon.Get("commit_only").Tip());
        _amend = new CheckBox { Classes = { "tick" }, Content = Lang.T("исправить прошлый (--amend)") };
        ToolTip.SetTip(_amend, Canon.Get("amend").Tip());
        _guard = new TextBlock { Classes = { "status" }, VerticalAlignment = VerticalAlignment.Center, TextTrimming = TextTrimming.CharacterEllipsis };
        var row3 = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,Auto,*") };
        row3.Children.Add(_onlyMarked);
        Grid.SetColumn(_amend, 1); row3.Children.Add(_amend);
        Grid.SetColumn(_guard, 2); row3.Children.Add(_guard);
        _preview = new TextBlock { Classes = { "mono" }, TextWrapping = TextWrapping.Wrap, VerticalAlignment = VerticalAlignment.Center };
        var preview = new Border { Classes = { "preview" }, Child = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, Children = { Sign("message-square-text", "CrumbInk"), _preview } } };
        ToolTip.SetTip(preview, Lang.T("Сообщение коммита, как оно будет записано: тип(область): серия версия - тема. Тема - в строке под страницей."));
        var body = new StackPanel { Spacing = 7, Children = { row1, row2, row3, preview } };
        _ = NextVersion();
        ShowPreview();
        return Block("КОММИТ", "Quasar", body);
    }

    void MarkTypes()
    {
        if (_typeRow is null) return;
        _typeRow.Children.Clear();
        foreach (var type in CommitTypes)
            _typeRow.Children.Add(Chip(type, _settings.CommitType == type, () => { _settings.CommitType = type; _settings.Save(); MarkTypes(); ShowPreview(); },
                type switch
                {
                    "docs" => "docs - документы, тексты", "code" => "code - код, новое умение", "fix" => "fix - исправление ошибки",
                    "ui" => "ui - вид окна", "test" => "test - проверки", "chore" => "chore - уборка, сборка, зависимости", _ => "audit - разбор и проверка",
                }));
    }

    string CommitMessage()
    {
        var subject = (_subject?.Text ?? "").Trim();
        var scope = (_scope?.Text ?? "").Trim();
        var series = (_series?.Text ?? "").Trim();
        var version = (_version?.Text ?? "").Trim();
        var head = _settings.CommitType + (scope.Length > 0 ? $"({scope})" : "") + ": ";
        var mark = series.Length > 0 && version.Length > 0 ? series + " " + version + " - " : version.Length > 0 ? version + " - " : "";
        return head + mark + subject;
    }

    string TagName()
    {
        var series = (_series?.Text ?? "").Trim().ToLowerInvariant();
        var version = (_version?.Text ?? "").Trim();
        if (!version.StartsWith('v')) version = "v" + version;
        series = System.Text.RegularExpressions.Regex.Replace(series, "[^a-z0-9._-]+", "-").Trim('-', '.', '_');
        return (series.Length > 0 ? series : "checkpoint") + "-" + version;
    }

    void ShowPreview()
    {
        if (_preview is null) return;
        _preview.Text = CommitMessage() + (_tagBox?.IsChecked == true ? "   🏷 " + TagName() : "");
        _settings.Save();
    }

    async Task NextVersion()
    {
        if (_version is null || ActiveRoot(true) is not { } root) return;
        var answer = await Hub.Ask("next-version", "--repo", root, "--series", _settings.VersionSeries.Length > 0 ? _settings.VersionSeries : "projection", "--bump", _settings.VersionBump);
        if (answer.Ok && _version is not null) _version.Text = answer.Text("version");
        ShowPreview();
    }

    // ------------------------------------------------------------ the operations

    /// <summary>The paths an operation takes: the marked ones of the groups it takes from, or the file chosen.</summary>
    List<string> Picked(params string[] groups)
    {
        var picked = _rows.Where(r => r.Head.Length == 0 && !r.Up && !r.IsDir && _marked.Contains(r.Path) && (groups.Length == 0 || groups.Contains(r.Group))).Select(r => r.Path).Distinct().ToList();
        if (picked.Count == 0 && _files?.SelectedItem is FileRow row && row.Head.Length == 0 && !row.Up && !row.IsDir && (groups.Length == 0 || groups.Contains(row.Group)))
            picked.Add(row.Path);
        return picked;
    }

    /// <summary>F5: into the index - only what the profile of the project lets in.</summary>
    async void Stage()
    {
        var paths = Picked("changed", "new", "conflict");
        if (paths.Count == 0) { SetStatus("Отметьте файлы пробелом или выберите файл из ИЗМЕНЁННЫХ или НОВЫХ."); return; }
        var allowed = await AllowedByProfile(paths);
        if (allowed is null) return;
        if (allowed.Count == 0) { SetStatus("Все выбранные файлы вне профиля: в индекс они не идут."); return; }
        _marked.ExceptWith(allowed);
        RunCanon("add", new() { ["paths"] = allowed });
    }

    void Unstage()
    {
        var paths = Picked("staged");
        if (paths.Count == 0) { SetStatus("Выберите или отметьте файлы из группы В ИНДЕКСЕ."); return; }
        _marked.ExceptWith(paths);
        // Before the first commit there is no HEAD to take the files back to: git rm --cached, as git itself advises.
        RunCanon(_state?.NoCommits == true ? "unstage_new" : "unstage", new() { ["paths"] = paths });
    }

    void Restore()
    {
        var paths = Picked("changed");
        if (paths.Count == 0) { SetStatus("Вернуть можно изменённый файл: выберите его в группе ИЗМЕНЕНЫ."); return; }
        _marked.ExceptWith(paths);
        RunCanon("restore", new() { ["paths"] = paths });
    }

    /// <summary>
    /// The paths the profile of the project lets into a commit, asked of the console command; a path it does not let in
    /// is named with its reason, and the person decides whether the rest goes. Null - the person said no, or the check
    /// did not take place: no answer is no permission.
    /// </summary>
    async Task<List<string>?> AllowedByProfile(List<string> paths)
    {
        if (_project is null || _settings.Layer == "docs") return paths;
        var existing = paths.Where(p => File.Exists(System.IO.Path.Combine(LayerFolder(), p)) || Directory.Exists(System.IO.Path.Combine(LayerFolder(), p))).ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (existing.Count == 0) return paths;
        // The paths go on the input, a line each: the first commit of a big project does not fit one command line.
        var answer = await Hub.Ask(new[] { "check-paths", _project.Id, "--layer", _settings.Layer, "--stdin" }, string.Join("\n", existing));
        // A profile that does not read, a console command that failed or did not answer, a JSON without its lists: the
        // action stops and says why. Taking every file then is how a .env once went into a commit.
        if (answer.Json?["allowed"] is not JsonArray allowedList || answer.Json?["blocked"] is not JsonArray blocked)
        {
            AppendLines(new[] { "[ERR] " + Lang.F("Проверка профилем не состоялась - файлы не взяты: {0}", answer.Error.Length > 0 ? answer.Error : answer.Line) });
            SetStatus("Проверка профилем не состоялась: подробности в терминале.");
            return null;
        }
        // The answer itself is the permission: a file goes only when check-paths named it allowed. A path gone from the disk
        // is a deletion to stage - there is nothing to read, and it goes as it is.
        var allowedSet = allowedList.Select(n => n?.ToString() ?? "").ToHashSet(StringComparer.OrdinalIgnoreCase);
        var allowed = paths.Where(p => !existing.Contains(p) || allowedSet.Contains(p)).ToList();
        var refused = existing.Where(p => !allowedSet.Contains(p)).OrderBy(p => p, StringComparer.OrdinalIgnoreCase).ToList();
        if (refused.Count == 0) return allowed;
        var why = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var b in blocked.OfType<JsonObject>()) why.TryAdd(b["path"]?.ToString() ?? "", b["reason"]?.ToString() ?? "");
        foreach (var n in answer.Json?["ignored"] as JsonArray ?? new()) why.TryAdd(n?.ToString() ?? "", ".gitignore");
        var reasons = string.Join("\n", refused.Take(10).Select(p => $"{p}  ({(why.TryGetValue(p, out var w) ? w : "?")})"));
        _asking = true;
        ApplyBusy();
        try
        {
            var go = await AskDialog.YesNo(this, Lang.T("Файлы вне профиля"),
                Lang.F("Профиль проекта ({0}) не пропускает в коммит: {1}.", _project.Profile, refused.Count) + "\n" + reasons + "\n\n"
                + (allowed.Count > 0 ? Lang.F("Взять остальные ({0})?", allowed.Count) : Lang.T("Взять нечего.")), "run");
            return go ? allowed : null;
        }
        finally { _asking = false; ApplyBusy(); }
    }

    /// <summary>
    /// КОММИТ: the message from its parts, the files checked by the profile, then the commit - of the index, of the
    /// marked files alone, or the last one rewritten - and its tag when asked.
    /// </summary>
    async void Commit()
    {
        if (_runner.Running || _asking) return;
        if (ActiveRoot() is not { } root) return;
        var subject = (_subject?.Text ?? "").Trim();
        if (subject.Length == 0) { SetStatus("Напишите тему коммита в строке под страницей."); _subject?.Focus(); return; }
        bool only = _onlyMarked?.IsChecked == true, amend = _amend?.IsChecked == true;
        var paths = only ? Picked() : (_state?.Files.Where(f => f.Staged).Select(f => f.Path).ToList() ?? new());
        if (!amend && paths.Count == 0)
        {
            SetStatus(only ? "Отметьте файлы пробелом: в коммит пойдут только они." : "Индекс пуст: положите файлы в индекс (F5) или отметьте их и включите «только отмеченные».");
            return;
        }
        if (paths.Count > 0)
        {
            var allowed = await AllowedByProfile(paths);
            if (allowed is null) return;
            if (allowed.Count < paths.Count)
            {
                if (!only) { SetStatus("В индексе есть файлы вне профиля: снимите их (F6) и повторите."); return; }
                paths = allowed;
            }
        }
        var message = CommitMessage();
        var id = amend ? "amend" : only ? "commit_only" : "commit";
        var values = new Dictionary<string, object> { ["message"] = message, ["paths"] = paths };
        bool tag = _tagBox?.IsChecked == true && (_version?.Text ?? "").Trim().Length > 0;
        var tagName = TagName();
        RunCanon(id, values, code =>
        {
            if (code != 0) return;
            if (_subject is not null) _subject.Text = "";
            _marked.ExceptWith(paths);
            if (tag) RunCanon("tag", new() { ["tag"] = tagName, ["message"] = message });
            _ = NextVersion();
        });
    }

    Dictionary<string, object>? PullValues()
    {
        if (_state is null) return null;
        var (remote, branch) = Upstream();
        return new() { ["remote"] = remote, ["branch"] = branch };
    }

    /// <summary>
    /// push: the current local branch into its pair on the server. When the names differ - topic following origin/main -
    /// the command names both, topic:main: a bare "main" is the LOCAL main, and the work of topic stayed on the machine
    /// while PUSH reported success.
    /// </summary>
    Dictionary<string, object>? PushValues()
    {
        if (_state is null) return null;
        var (remote, pair) = Upstream();
        var local = _state.Branch is { Length: > 0 } b && !_state.Detached ? b : pair;
        return new() { ["remote"] = remote, ["branch"] = local == pair ? local : local + ":" + pair };
    }

    /// <summary>The remote and the branch of the pair on the server; origin and the current branch when there is no pair yet.</summary>
    (string Remote, string Branch) Upstream()
    {
        var s = _state;
        if (s is { Upstream.Length: > 0 } && s.Upstream.IndexOf('/') is var cut and > 0) return (s.Upstream[..cut], s.Upstream[(cut + 1)..]);
        return ("origin", s?.Branch is { Length: > 0 } b && !s.Detached ? b : _project?.Branch ?? "main");
    }

    async Task UpdateChanges()
    {
        await CheckProfile();
        ShowFlow();
        ShowFiles();
    }

    /// <summary>Which changed files the profile of the project keeps out: the panel greys them and says why.</summary>
    async Task CheckProfile()
    {
        _outOfProfile.Clear();
        if (_project is null || _state is null || _settings.Layer == "docs") return;
        var paths = _state.Files.Where(f => f.Letter != 'D').Select(f => f.Path).ToList();
        if (paths.Count == 0) return;
        var answer = await Hub.Ask(new[] { "check-paths", _project.Id, "--layer", _settings.Layer, "--stdin" }, string.Join("\n", paths));
        if (answer.Json?["blocked"] is JsonArray blocked)
            foreach (var b in blocked.OfType<JsonObject>())
                if (b["path"]?.ToString() is { Length: > 0 } path) _outOfProfile[path] = b["reason"]?.ToString() ?? "";
    }
}
