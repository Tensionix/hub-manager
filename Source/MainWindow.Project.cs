using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using AudionHubManager.Core;
using Ellipse = Avalonia.Controls.Shapes.Ellipse;

namespace AudionHubManager;

/// <summary>
/// The project and its layers. The registry is the engine's (hub_projects.json in the root of the projects), read through the console command;
/// the layer - ИСХОДНИК, GIT-КОПИЯ, DOCS - says which repository every Git command goes to, and the window tells
/// apart a folder that is a repository of its own, one that lies inside another repository, and one that is no
/// repository at all. The state of the repository is read after every command and when the window comes back to the
/// front, and drives the counts of the sections, the flow of the three places and the next step in the state row.
/// </summary>
public partial class MainWindow
{
    sealed class ProjectItem
    {
        public string Id = "", Title = "", Source = "", Mirror = "", Docs = "", Profile = "", Branch = "main";
        public Dictionary<string, (bool Exists, string Repo, string Parent)> Layers = new();
        /// <summary>The title as the window shows it: the lessons of the lab are named by the program, in both languages.</summary>
        public string Name => Lang.T(Title);
        public string Folder(string layer) => layer switch { "mirror" => Mirror, "docs" => Docs, _ => Source };
    }

    readonly List<ProjectItem> _projects = new();
    ProjectItem? _project;
    GitState? _state;
    /// <summary>"own", "parent", "none", "missing" - what the folder of the layer is to Git.</summary>
    string _repoKind = "missing", _repoTop = "";
    /// <summary>The state of each layer, for the chips of the layers: branch, ahead, behind.</summary>
    readonly Dictionary<string, GitState?> _layerStates = new();
    JsonObject? _tools;

    void WireProject()
    {
        OpenFolderButton.Click += (_, _) => { if (LayerFolder() is { Length: > 0 } folder) OpenFolder(folder); };
        OpenCodeButton.Click += (_, _) => OpenInCode(LayerFolder());
        OpenTerminalButton.Click += (_, _) => OpenTerminal();
    }

    async Task StartUp()
    {
        if (!Hub.Ready)
        {
            ShowNote(Hub.Trouble);
            SetStatus("Консольная команда программы недоступна.");
            return;
        }
        SetStatus("Читаю канон Git и реестр проектов…");
        var trouble = await Canon.Load();
        if (trouble.Length > 0)
        {
            ShowNote(Lang.F("Консольная команда не отдала канон Git: {0}", trouble));
            SetStatus("Канон Git не прочитан.");
            return;
        }
        await LoadProjects();
        BuildSections();
        BuildSide();
        ShowProject();
        ShowSection();
        await RefreshState();
        SetStatus("Готово.");
        _ = LoadTools();
        // The first lesson of every start: what git says of the repository, with the words under it.
        if (ActiveRoot(true) is not null && Program.ShotFolder.Length == 0) RunCanon("status");
    }

    void ShowNote(string text)
    {
        PageNote.Text = Lang.T(text);
        PageNote.IsVisible = true;
    }

    // ------------------------------------------------------------ the registry

    async Task LoadProjects()
    {
        var answer = await Hub.Ask("projects", "list");
        _projects.Clear();
        if (answer.Json?["projects"] is JsonArray items)
            foreach (var node in items.OfType<JsonObject>())
            {
                var item = new ProjectItem
                {
                    Id = node["id"]?.ToString() ?? "",
                    Title = node["title"]?.ToString() ?? "",
                    Source = node["source_path"]?.ToString() ?? "",
                    Mirror = node["projection_path"]?.ToString() ?? "",
                    Docs = node["docs_path"]?.ToString() ?? "",
                    Profile = node["profile"]?.ToString() ?? "",
                    Branch = node["default_branch"]?.ToString() ?? "main",
                };
                if (node["layers"] is JsonObject layers)
                    foreach (var (layer, value) in layers)
                        if (value is JsonObject l)
                            item.Layers[layer] = (l["exists"]?.GetValue<bool>() == true, l["repo"]?.ToString() ?? "none", l["parent"]?.ToString() ?? "");
                _projects.Add(item);
            }
        var active = answer.Json?["active_project_id"]?.ToString() ?? "";
        _registryFile = answer.Json?["config"]?.ToString() ?? "";
        _project = _projects.FirstOrDefault(p => p.Id == (_project?.Id ?? active)) ?? _projects.FirstOrDefault(p => p.Id == active) ?? _projects.FirstOrDefault();
        if (answer.Json?["load_error"]?.ToString() is { Length: > 0 } error) AppendLines(new[] { "[GUI] " + error });
        if (!answer.Said) AppendLines(new[] { "[ERR] " + Lang.F("реестр проектов не прочитан: {0}", answer.Error) });
    }

    async Task SelectProject(ProjectItem project)
    {
        if (_runner.Running) { SetStatus("Идёт команда: проект сменится, когда она закончится."); return; }
        _project = project;
        _selected = "";
        _marked.Clear();
        _commit = null;
        await Hub.Ask("projects", "active", project.Id);
        ShowProject();
        ShowSection();
        await RefreshState();
    }

    // ------------------------------------------------------------ the layers

    static string LayerName(string layer) => layer switch { "mirror" => "GIT-КОПИЯ", "docs" => "DOCS", _ => "ИСХОДНИК" };

    string LayerWord() => Lang.T(LayerName(_settings.Layer)) + (_project is null ? "" : " · " + _project.Name);

    string LayerFolder() => _project?.Folder(_settings.Layer) ?? "";

    /// <summary>
    /// The root the Git commands of the layer run in, or null with the reason in the state row: no folder, a folder
    /// that is no repository yet, a folder inside another repository (a command there would act on that one).
    /// </summary>
    string? ActiveRoot(bool quiet = false)
    {
        string? why = _project is null ? "Проект не выбран: ПРОЕКТЫ → реестр."
            : _repoKind == "missing" ? Lang.F("Папки слоя нет: {0}. Укажите её в ПРОЕКТЫ → ЗАПИСЬ.", LayerFolder())
            : _repoKind == "none" ? "Слой ещё не репозиторий: ОБСЛУЖИВАНИЕ → git init, или учебная лаборатория в ПРОЕКТАХ."
            : _repoKind == "parent" ? Lang.F("Папка слоя лежит внутри другого репозитория ({0}): команды пошли бы туда. Сделайте git init в ОБСЛУЖИВАНИИ.", _repoTop)
            : null;
        if (why is null) return LayerFolder();
        if (!quiet) SetStatus(why);
        return null;
    }

    void ShowProject()
    {
        ShowSide();
        LayerRow.Children.Clear();
        foreach (var layer in new[] { "source", "mirror", "docs" })
        {
            if (layer == "mirror")
                LayerRow.Children.Add(new StackPanel
                {
                    Orientation = Orientation.Horizontal, Spacing = 3, Margin = new Thickness(4, 0), VerticalAlignment = VerticalAlignment.Center,
                    Children = { new TextBlock { Classes = { "arrowword" }, Text = "MIRROR" }, Sign("arrow-right", "CrumbInk") },
                });
            if (layer == "docs") LayerRow.Children.Add(VSep());
            LayerRow.Children.Add(LayerChip(layer));
        }
        LayerPath.Text = LayerFolder();
        ToolTip.SetTip(LayerPath, LayerFolder());
    }

    ToggleButton LayerChip(string layer)
    {
        var face = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 7 };
        face.Children.Add(Sign(layer switch { "mirror" => "folder-git", "docs" => "book-open-text", _ => "folder-code" }));
        face.Children.Add(new TextBlock { Text = Lang.T(LayerName(layer)), FontWeight = FontWeight.Bold, VerticalAlignment = VerticalAlignment.Center });
        if (_layerStates.TryGetValue(layer, out var state) && state is not null && layer != "docs")
        {
            face.Children.Add(Sign("git-branch", "CrumbInk"));
            face.Children.Add(new TextBlock { Classes = { "caption" }, Text = state.Detached ? "HEAD" : state.Branch });
            if (state.Ahead > 0) face.Children.Add(new TextBlock { Text = "↑" + state.Ahead }.Ink(TextBlock.ForegroundProperty, "GitStaged"));
            if (state.Behind > 0) face.Children.Add(new TextBlock { Text = "↓" + state.Behind }.Ink(TextBlock.ForegroundProperty, "GitNew"));
            int dirty = state.Files.Count;
            if (dirty > 0) face.Children.Add(new Ellipse { Width = 6, Height = 6, VerticalAlignment = VerticalAlignment.Center }.Ink(Avalonia.Controls.Shapes.Shape.FillProperty, "GitModified"));
        }
        else if (_project is not null && _project.Layers.TryGetValue(layer, out var known) && (!known.Exists || known.Repo != "own"))
            face.Children.Add(new TextBlock { Classes = { "caption" }, Text = Lang.T(!known.Exists ? "нет папки" : known.Repo == "parent" ? "внутри чужого" : "без git") });
        var chip = new ToggleButton { Classes = { "switch", "layer" }, Content = face, IsChecked = _settings.Layer == layer };
        Avalonia.Automation.AutomationProperties.SetAutomationId(chip, "layer_" + layer);
        ToolTip.SetTip(chip, Lang.T(layer switch
        {
            "mirror" => "GIT-КОПИЯ - чистое зеркало проекта: только то, что пропускает профиль (код, документы, конфиги без секретов). Свой .git - чистая история для GitHub. Git-команды пойдут сюда.",
            "docs" => "DOCS - слой для чтения: Markdown и тексты для Obsidian, LogSeq или просто папки.",
            _ => "ИСХОДНИК - живой проект целиком, источник истины, свой .git. Git-команды пойдут сюда.",
        }) + "\n" + (_project?.Folder(layer) is { Length: > 0 } folder ? folder : Lang.T("папка не задана")));
        chip.Click += (_, _) => _ = SelectLayer(layer);
        return chip;
    }

    async Task SelectLayer(string layer)
    {
        if (_runner.Running) { SetStatus("Идёт команда: слой сменится, когда она закончится."); ShowProject(); return; }
        _settings.Layer = layer;
        _settings.Save();
        _selected = "";
        _marked.Clear();
        _commit = null;
        ShowProject();
        ShowSection();
        await RefreshState();
    }

    // ------------------------------------------------------------ the state of the repository

    DispatcherTimer? _refreshTimer;
    bool _refreshing, _refreshAgain;

    /// <summary>The state is read again a little later: several reasons in a row make one reading.</summary>
    void RefreshSoon(int milliseconds = 400)
    {
        if (_project is null || !Canon.Loaded) return;
        _refreshTimer?.Stop();
        _refreshTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(Math.Max(1, milliseconds)) };
        _refreshTimer.Tick += (_, _) => { _refreshTimer?.Stop(); _ = RefreshState(); };
        _refreshTimer.Start();
    }

    async Task RefreshState()
    {
        if (_refreshing) { _refreshAgain = true; return; }
        _refreshing = true;
        try
        {
            do
            {
                _refreshAgain = false;
                var folder = LayerFolder();
                (_repoKind, _repoTop) = folder.Length == 0 ? ("missing", "") : await Git.Kind(folder);
                _state = _repoKind == "own" ? await Git.Status(folder) : null;
                _remoteNames = _repoKind == "own" ? (await Git.Remotes(folder)).Select(r => r.Name).ToList() : new();
                // The chips of the other layers show their branch and distance too.
                foreach (var layer in new[] { "source", "mirror" })
                {
                    if (layer == _settings.Layer) { _layerStates[layer] = _state; continue; }
                    var other = _project?.Folder(layer) ?? "";
                    _layerStates[layer] = other.Length > 0 && (await Git.Kind(other)).Kind == "own" ? await Git.Status(other) : null;
                }
                ShowProject();
                ShowCounts();
                ShowCoach();
                await UpdateSection();
            }
            while (_refreshAgain);
        }
        finally { _refreshing = false; }
    }

    /// <summary>The counts on the sections and on the project: what waits in each mode.</summary>
    void ShowCounts()
    {
        int changes = _state?.Files.Count ?? 0;
        SetBadge("changes", changes > 0 ? changes.ToString() : "", "mod");
        SetBadge("sync", _state is { Ahead: > 0 } ? "↑" + _state.Ahead : _state is { Behind: > 0 } ? "↓" + _state.Behind : "", "info");
        SetBadge("branches", _state is { Underway.Length: > 0 } ? "!" : "", "bad");
        ShowSideCount();
    }

    /// <summary>The next step in plain words, by what the repository holds now.</summary>
    void ShowCoach()
    {
        string coach;
        var s = _state;
        if (_project is null) coach = "Выберите проект или создайте учебную лабораторию: ПРОЕКТЫ.";
        else if (_repoKind == "missing") coach = "Папки слоя нет: укажите её в ПРОЕКТЫ → ЗАПИСЬ.";
        else if (_repoKind is "none" or "parent") coach = "Это ещё не репозиторий: ОБСЛУЖИВАНИЕ → git init. Потренироваться - ПРОЕКТЫ → УЧЕБНАЯ ЛАБОРАТОРИЯ.";
        else if (s is null) coach = "Git не ответил: подробности - git status в терминале.";
        else if (s.Underway == "merge" && s.ConflictCount > 0) coach = Lang.F("Идёт слияние, конфликтов: {0}. Поправьте файлы с буквой U, F5 - в индекс, затем КОММИТ. Или ВЕТКИ → git merge --abort.", s.ConflictCount);
        else if (s.Underway.Length > 0) coach = Lang.F("Идёт {0}: доведите его коммитом или прервите - ВЕТКИ → «если застряли».", s.Underway);
        else if (s.ConflictCount > 0) coach = Lang.F("Конфликтов: {0}. Поправьте файлы с буквой U и положите их в индекс (F5).", s.ConflictCount);
        else if (s.StagedCount > 0) coach = Lang.F("В индексе {0}: напишите тему внизу и нажмите КОММИТ (Ctrl+Enter).", s.StagedCount);
        else if (s.ChangedCount + s.NewCount > 0) coach = Lang.F("Изменено {0}, новых {1}: отметьте файлы пробелом и нажмите F5 - в индекс.", s.ChangedCount, s.NewCount);
        else if (s.NoCommits) coach = "Репозиторий пуст: создайте файл, положите в индекс (F5) и сделайте первый коммит.";
        else if (s.Ahead > 0 && s.Behind > 0) coach = Lang.F("Ветка разошлась с сервером: у вас {0}, там {1}. Сначала ВЕТКИ → слияние, потом PUSH.", s.Ahead, s.Behind);
        else if (s.Ahead > 0) coach = Lang.F("Ветка впереди сервера на {0}: СИНХРОНИЗАЦИЯ → PUSH.", s.Ahead);
        else if (s.Behind > 0) coach = Lang.F("На сервере новых коммитов: {0}. СИНХРОНИЗАЦИЯ → pull.", s.Behind);
        else if (s.Upstream.Length == 0 && !s.Detached) coach = "У ветки нет пары на сервере: ВЕТКИ → push -u, или СИНХРОНИЗАЦИЯ → новый remote.";
        else coach = "Всё закоммичено и отправлено. Можно работать дальше.";
        CoachText.Text = Lang.T(coach);
        ToolTip.SetTip(CoachRow, CoachText.Text);
    }

    // ------------------------------------------------------------ the tools of this machine

    /// <summary>git, gh, glab, BLAKE3, VS Code: what the console command found on this machine, as chips of the header.</summary>
    async Task LoadTools()
    {
        var answer = await Hub.Ask("tools");
        _tools = answer.Json;
        ShowTools();
    }

    void ShowTools()
    {
        ToolRow.Children.Clear();
        if (_tools is null) return;
        foreach (var (key, mark, title) in new[] { ("git", "git", "git"), ("gh", "github", "gh"), ("glab", "gitlab", "glab"), ("blake3", "", "BLAKE3"), ("vscode", "vscodium", "VS Code") })
        {
            var tool = _tools[key] as JsonObject;
            bool found = tool?["found"]?.GetValue<bool>() == true;
            var version = System.Text.RegularExpressions.Regex.Replace(tool?["version"]?.ToString() ?? "", @"\.windows\.\d+$", "");
            var face = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6 };
            face.Children.Add(new Ellipse { Width = 7, Height = 7, VerticalAlignment = VerticalAlignment.Center }.Ink(Avalonia.Controls.Shapes.Shape.FillProperty, found ? "DotOk" : "DotIdle"));
            if (mark.Length > 0 && Icons.Mark(mark, 12) is { } brand) face.Children.Add(brand);
            face.Children.Add(new TextBlock { Classes = { "caption" }, Text = found ? (version.Length > 0 && key != "vscode" ? title + " " + version : title) : title + " —" });
            var chip = new Border { Classes = { "fact" }, Child = face };
            ToolTip.SetTip(chip, found ? (tool?["path"]?.ToString() ?? title) : Lang.F("{0} не найден на этой машине.", title));
            ToolRow.Children.Add(chip);
        }
    }

    void OpenInCode(string folder)
    {
        if (folder.Length == 0 || !Directory.Exists(folder)) { SetStatus("Папки слоя нет."); return; }
        var command = (_tools?["vscode"] as JsonObject)?["path"]?.ToString() ?? "";
        try
        {
            // code.cmd is a batch file: started through cmd without a window, as VS Code itself is started from a console.
            Process.Start(new ProcessStartInfo("cmd.exe")
            {
                ArgumentList = { "/d", "/c", command.Length > 0 ? command : "code", folder }, UseShellExecute = false, CreateNoWindow = true,
            });
        }
        catch (Exception ex) { SetStatus(Lang.F("VS Code не открылся: {0}", ex.Message)); }
    }

    /// <summary>A terminal of Windows in the root of the layer, with git status already said.</summary>
    void OpenTerminal(string command = "git status --short --branch")
    {
        var folder = LayerFolder();
        if (folder.Length == 0 || !Directory.Exists(folder)) { SetStatus("Папки слоя нет."); return; }
        try
        {
            Process.Start(new ProcessStartInfo("cmd.exe")
            {
                Arguments = "/k \"chcp 65001 >nul & " + command + "\"",
                WorkingDirectory = folder,
                UseShellExecute = true,
            });
        }
        catch (Exception ex) { SetStatus(Lang.F("Терминал не открылся: {0}", ex.Message)); }
    }
}
