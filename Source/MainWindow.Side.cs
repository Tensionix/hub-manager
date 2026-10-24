using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Controls.Templates;
using Avalonia.Interactivity;
using Avalonia.Layout;
using Avalonia.Platform.Storage;
using AudionHubManager.Core;

namespace AudionHubManager;

/// <summary>
/// The column of projects at the left of every section. A click on a project makes it the one the Git commands go to; a
/// tick marks it for what is done to several at once, ALL and CLEAR mark them all or none. The badge says marked | all.
/// To the right of the badge - the root of the projects, the folder they lie in: chosen in the folder panel of ПРОЕКТЫ
/// and kept for this machine (hub_cli storage --projects-root, config\storage_layout.local.json).
/// </summary>
public partial class MainWindow
{
    /// <summary>The ids of the projects ticked in the column.</summary>
    readonly HashSet<string> _markedProjects = new(StringComparer.Ordinal);
    ListBox? _sideList;
    TextBlock? _sideBadge;
    Button? _rootButton;
    /// <summary>The count of changes on the row of each project, by its id: the one in sight is told after every reading.</summary>
    readonly Dictionary<string, (Border Pill, TextBlock Text)> _sidePills = new(StringComparer.Ordinal);
    string _sideIds = "";
    bool _sideFilling;

    const string SideColumns = "22,*,Auto";

    void BuildSide()
    {
        SideHost.Children.Clear();
        _sideIds = "";
        _sideBadge = new TextBlock();
        var badge = new Border { Classes = { "pill" }, Child = _sideBadge, Margin = new Thickness(8, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center };
        ToolTip.SetTip(badge, Lang.T("Отмечено | всего проектов в реестре."));
        _rootButton = new Button { Classes = { "tool" }, Content = Sign("folder-open"), Margin = new Thickness(6, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center };
        Avalonia.Automation.AutomationProperties.SetAutomationId(_rootButton, "projects_root");
        _rootButton.Click += (_, _) => OpenRootMenu();
        ShowRootTip();
        var fold = new Button { Classes = { "tool" }, Content = Sign("chevron-left"), VerticalAlignment = VerticalAlignment.Center };
        ToolTip.SetTip(fold, Lang.T("Свернуть колонку проектов: странице - вся ширина."));
        Avalonia.Automation.AutomationProperties.SetAutomationId(fold, "side_fold");
        fold.Click += (_, _) => OpenSide(false);
        var head = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,Auto,Auto,*,Auto"), Margin = new Thickness(10, 8, 6, 6) };
        head.Children.Add(Text("ПРОЕКТЫ", "cardtitle"));
        Grid.SetColumn(badge, 1); head.Children.Add(badge);
        Grid.SetColumn(_rootButton, 2); head.Children.Add(_rootButton);
        Grid.SetColumn(fold, 4); head.Children.Add(fold);

        var all = Chip("ALL", false, () => { foreach (var p in _projects) _markedProjects.Add(p.Id); ShowSide(true); }, "Отметить все проекты.");
        var clear = Chip("CLEAR", false, () => { _markedProjects.Clear(); ShowSide(true); }, "Снять все отметки.");
        all.Margin = new Thickness(0, 0, 4, 0);
        all.Click += (_, _) => all.IsChecked = false;
        clear.Click += (_, _) => clear.IsChecked = false;
        var marks = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(10, 0, 8, 6), Children = { all, clear } };

        _sideList = Rows("side_projects");
        _sideList.ItemTemplate = new FuncDataTemplate<ProjectItem>((p, _) => p is null ? new Panel() : SideRow(p), supportsRecycling: false);
        _sideList.SelectionChanged += (_, _) =>
        {
            if (_sideFilling || _sideList.SelectedItem is not ProjectItem p || p.Id == _project?.Id) return;
            // Over the page the column has done its work once a project is chosen.
            if (_sideOver) OpenSide(false);
            _ = SelectProject(p);
        };
        foreach (var top in new Control[] { head, marks, new Border { Classes = { "hsep" }, Padding = new Thickness(0) } })
        {
            DockPanel.SetDock(top, Dock.Top);
            SideHost.Children.Add(top);
        }
        var commit = BuildMarkedCommit();
        DockPanel.SetDock(commit, Dock.Bottom);
        SideHost.Children.Add(commit);
        SideHost.Children.Add(_sideList);

        ShowSideMode();
        ShowSide();
        if (_places is null) _ = LoadPlaces();
    }

    // ------------------------------------------------------------ beside the page or over it

    /// <summary>A narrow window: the column opened over the page for a moment, not kept in the settings.</summary>
    bool _sideOverOpen;
    /// <summary>The column is open over the page now.</summary>
    bool _sideOver;

    /// <summary>
    /// The owner, 25.10.2026: folded, the page stands 20 px from the edge with a chevron in them - no strip; and the column
    /// "slides out over the page, and moves it aside only from some width of the window". From <see cref="Settings.SideRoom"/>
    /// on the column stands beside the page, open or folded as the settings keep it; below, it is folded and opens over
    /// the page until a project is chosen, the chevron folds it, Esc or a click past it.
    /// </summary>
    void ShowSideMode()
    {
        bool wide = ClientSize.Width >= Settings.SideRoom;
        if (wide) _sideOverOpen = false;
        bool open = wide ? !_settings.SideFolded : _sideOverOpen;
        _sideOver = open && !wide;
        SideGap.IsVisible = !open || _sideOver;
        SideFrame.IsVisible = open;
        Grid.SetColumnSpan(SideFrame, _sideOver ? 2 : 1);
        SideFrame.ZIndex = _sideOver ? 10 : 0;
        SideFrame.Margin = _sideOver ? new Thickness(0) : new Thickness(0, 0, 8, 0);
        // No BoxShadow: a picture of the window (-Shot) drew the column under a shadow half as large again and past its
        // frame (25.10.2026); its own frame and ground part it from the page.
    }

    /// <summary>The chevrons: in a wide window the choice is kept; in a narrow one the column only opens over the page.</summary>
    void OpenSide(bool open)
    {
        if (ClientSize.Width >= Settings.SideRoom)
        {
            _settings.SideFolded = !open;
            _settings.Save();
        }
        else _sideOverOpen = open;
        ShowSideMode();
    }

    void WireSide()
    {
        SideOpenButton.Click += (_, _) => OpenSide(true);
        // The width decides the mode as the window is pulled, not only at the start.
        SizeChanged += (_, _) => ShowSideMode();
        // A press past the column over the page folds it; the press goes on to what it was meant for.
        LeftZone.AddHandler(PointerPressedEvent, (_, e) =>
        {
            if (!_sideOver) return;
            var at = e.GetPosition(SideFrame);
            if (at.X < 0 || at.Y < 0 || at.X > SideFrame.Bounds.Width || at.Y > SideFrame.Bounds.Height) OpenSide(false);
        }, RoutingStrategies.Tunnel);
    }

    /// <summary>The rows anew when the registry changed (or when asked), otherwise only the project chosen and the badge.</summary>
    void ShowSide(bool rebuild = false)
    {
        if (_sideList is null) return;
        var ids = string.Join("|", _projects.Select(p => p.Id + "=" + p.Name));
        _markedProjects.IntersectWith(_projects.Select(p => p.Id));
        _sideFilling = true;
        try
        {
            if (rebuild || ids != _sideIds)
            {
                _sideIds = ids;
                _sidePills.Clear();
                _sideList.ItemsSource = _projects.ToList();
            }
            _sideList.SelectedItem = _projects.FirstOrDefault(p => p.Id == _project?.Id);
        }
        finally { _sideFilling = false; }
        _sideBadge!.Text = $"{_markedProjects.Count} | {_projects.Count}";
        ShowSideCount();
    }

    Control SideRow(ProjectItem p)
    {
        var tick = new CheckBox { IsChecked = _markedProjects.Contains(p.Id), MinWidth = 0, Padding = new Thickness(0), VerticalAlignment = VerticalAlignment.Center };
        ToolTip.SetTip(tick, Lang.T("Отметить проект: отмеченные идут в общую работу над несколькими."));
        tick.IsCheckedChanged += (_, _) =>
        {
            if (tick.IsChecked == true) _markedProjects.Add(p.Id); else _markedProjects.Remove(p.Id);
            if (_sideBadge is not null) _sideBadge.Text = $"{_markedProjects.Count} | {_projects.Count}";
        };
        var name = Cell(p.Name);
        name.Classes.Add("side");
        var count = new TextBlock();
        var pill = new Border { Classes = { "pill", "mod" }, Child = count, Margin = new Thickness(6, 0, 0, 0), IsVisible = false, VerticalAlignment = VerticalAlignment.Center };
        _sidePills[p.Id] = (pill, count);
        if (_batchStatus.TryGetValue(p.Id, out var b) && int.TryParse(b["files"]?.ToString(), out var files) && files > 0)
        {
            count.Text = files.ToString();
            pill.IsVisible = true;
        }
        var grid = Cells(SideColumns, tick, name, pill);
        grid.MinHeight = 24;
        grid.Margin = new Thickness(8, 0, 8, 0);
        ToolTip.SetTip(grid, p.Name + "\n" + p.Source);
        return grid;
    }

    /// <summary>The count of changes of the project in sight, on its row: what the last reading of its repository found.</summary>
    void ShowSideCount()
    {
        if (_project is null || !_sidePills.TryGetValue(_project.Id, out var row)) return;
        int changes = _state?.Files.Count ?? 0;
        row.Text.Text = changes.ToString();
        row.Pill.IsVisible = changes > 0;
    }

    // ------------------------------------------------------------ the root of the projects

    string _rootPath = "", _rootShipped = "", _registryFile = "";
    bool _rootChosenHere;

    void ShowRootTip()
    {
        if (_rootButton is null) return;
        ToolTip.SetTip(_rootButton, Lang.T("Корень проектов - папка, где лежат живые проекты: на неё смотрят панель папок и поиск проектов, в ней лежит реестр hub_projects.json - у каждого корня свой. Нажмите, чтобы сменить.")
            + (_rootPath.Length > 0 ? "\n" + _rootPath : ""));
    }

    void OpenRootMenu()
    {
        if (_rootButton is null) return;
        var menu = new MenuFlyout { Placement = PlacementMode.BottomEdgeAlignedLeft };
        menu.Items.Add(new MenuItem { Header = Lang.F("Корень проектов: {0}", _rootPath.Length > 0 ? _rootPath : "-"), IsEnabled = false });
        menu.Items.Add(new Separator());
        var picked = _settings.Section == "projects" ? PickedFolder() : null;
        if (picked is not null && !Same(picked, _rootPath))
        {
            var make = new MenuItem { Header = Lang.F("Сделать корнем: {0}", picked) };
            make.Click += (_, _) => SetProjectsRoot(picked);
            menu.Items.Add(make);
        }
        else
        {
            var choose = new MenuItem { Header = Lang.T("Выбрать в панели папок…") };
            choose.Click += (_, _) =>
            {
                if (_settings.Section != "projects") SelectSection("projects");
                if (_rootPath.Length > 0) FoldersGo(new DirectoryInfo(_rootPath).Parent?.FullName ?? "", _rootPath);
                SetStatus("Выберите папку в панели слева и снова нажмите на папку у проектов: «Сделать корнем».");
            };
            menu.Items.Add(choose);
        }
        if (_rootChosenHere)
        {
            var back = new MenuItem { Header = Lang.F("Вернуть корень по умолчанию: {0}", _rootShipped) };
            back.Click += (_, _) => SetProjectsRoot(null);
            menu.Items.Add(back);
        }
        // The registry lies in the root: another root, another registry. It goes out to a file and comes in from one.
        menu.Items.Add(new Separator());
        menu.Items.Add(new MenuItem { Header = Lang.F("Реестр: {0}", _registryFile.Length > 0 ? _registryFile : "-"), IsEnabled = false });
        var import = new MenuItem { Header = Lang.T("Импорт реестра из файла…") };
        import.Click += async (_, _) =>
        {
            var files = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
            {
                Title = Lang.T("Реестр проектов для импорта"), AllowMultiple = false,
                FileTypeFilter = new[] { new FilePickerFileType("JSON") { Patterns = new[] { "*.json" } } },
            });
            if (files.Count == 0 || files[0].TryGetLocalPath() is not { } file) return;
            RunSteps(HubStep("импорт реестра", new[] { "projects", "import", file },
                "Проекты из файла - в реестр корня: их пути читаются от места файла и пишутся от корня; проекты, что в реестре уже есть, остаются как есть.",
                (code, json) =>
                {
                    if (code != 0) return;
                    if (JsonOf(json) is { } said)
                        AppendLines(new[] { "[GUI] " + Lang.F("Импорт реестра: добавлено {0}, уже были {1}.", (said["added"] as JsonArray)?.Count ?? 0, said["skipped"]?.ToString() ?? "0") });
                    Then(() => _ = ReloadRegistry());
                }));
        };
        menu.Items.Add(import);
        var export = new MenuItem { Header = Lang.T("Экспорт реестра в файл…") };
        export.Click += async (_, _) =>
        {
            var file = await StorageProvider.SaveFilePickerAsync(new FilePickerSaveOptions
            {
                Title = Lang.T("Куда сохранить реестр проектов"), SuggestedFileName = "hub_projects-export.json", DefaultExtension = "json",
            });
            if (file?.TryGetLocalPath() is not { } path) return;
            RunSteps(HubStep("экспорт реестра", new[] { "projects", "export", path },
                "Реестр корня - в файл, каждый путь полностью: он читается одинаково, куда бы файл ни уехал.", (code, json) =>
                {
                    if (code == 0 && JsonOf(json) is { } said)
                        AppendLines(new[] { "[GUI] " + Lang.F("Экспорт реестра: проектов {0} → {1}", said["projects"]?.ToString() ?? "0", said["file"]?.ToString() ?? path) });
                }));
        };
        menu.Items.Add(export);
        menu.ShowAt(_rootButton);
    }

    /// <summary>The registry read anew - after another root or an import: the column, the project, the page.</summary>
    async System.Threading.Tasks.Task ReloadRegistry()
    {
        await LoadProjects();
        ShowProject();
        ShowSection();
        await RefreshState();
    }

    void SetProjectsRoot(string? folder) => RunSteps(HubStep("корень проектов",
        folder is null ? new[] { "storage", "--reset-projects-root" } : new[] { "storage", "--projects-root", folder },
        "Корень проектов этой машины: на него смотрят панель папок и поиск проектов, в нём - его реестр hub_projects.json. Пишется в config\\storage_layout.local.json - в git и в выпуск не идёт.",
        (code, json) => Then(async () =>
        {
            if (code != 0) return;
            // The root is changed; what of its projects the layout does not hold is told, as a line under the run.
            if (JsonOf(json)?["result"]?["off_layout"] is JsonObject off)
            {
                static string Ids(JsonNode? list) => list is JsonArray a ? string.Join(", ", a.Select(n => n?.ToString())) : "";
                var lines = new List<string>();
                if (Ids(off["source"]) is { Length: > 0 } source) lines.Add("[GUI] " + Lang.F("нет папки ИСХОДНИКА: {0}", source));
                if (Ids(off["projection"]) is { Length: > 0 } copies) lines.Add("[GUI] " + Lang.F("GIT-КОПИЯ не в корне GIT-КОПИЙ: {0}", copies));
                if (Ids(off["docs"]) is { Length: > 0 } docs) lines.Add("[GUI] " + Lang.F("DOCS не в корне DOCS: {0}", docs));
                if (lines.Count > 0) AppendLines(lines);
            }
            // Another root - another registry: the column shows the projects of the new root.
            _places = null;
            await LoadPlaces();
            await ReloadRegistry();
            if (_settings.Section == "projects" && _rootPath.Length > 0) FoldersGo(_rootPath, "");
        })));
}
