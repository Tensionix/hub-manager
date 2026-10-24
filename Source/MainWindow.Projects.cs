using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Templates;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using AudionHubManager.Core;

namespace AudionHubManager;

/// <summary>
/// ПРОЕКТЫ: the registry of the engine (hub_projects.json in the root of the projects) as a table - every project with its layers, and after
/// «статус всех» its branch, how dirty it is and how far ahead. The record of the project chosen: its three folders,
/// its profile, its branch. The batches over every project. The Git lab: ten repositories in known states to learn on,
/// built again with one button and put into the registry. On the left - the folder panel (MainWindow.Folders.cs): the
/// folders of the record, of a search for projects and of a clone are chosen there.
/// </summary>
public partial class MainWindow
{
    ListBox? _projectList;
    StackPanel? _record;
    TextBox? _cloneUrl;
    readonly Dictionary<string, JsonObject> _batchStatus = new();

    Control BuildProjects()
    {
        var split = new Grid { ColumnDefinitions = new ColumnDefinitions("380,10,*") };
        split.Children.Add(BuildFolders());
        var page = new Grid { RowDefinitions = new RowDefinitions("Auto,*,Auto") };
        Grid.SetColumn(page, 2);
        split.Children.Add(page);
        page.Children.Add(new TextBlock { Classes = { "pagetitle" }, Text = Upper(Lang.T("ПРОЕКТЫ")) + "  → " + Lang.T("РЕЕСТР"), Margin = new Thickness(0, 0, 0, 10) });
        _projectList = Rows("projects");
        _projectList.ItemTemplate = new FuncDataTemplate<ProjectItem>((p, _) => p is null ? new Panel() : ProjectView(p), supportsRecycling: false);
        _projectList.SelectionChanged += (_, _) => { if (_projectList.SelectedItem is ProjectItem p) ShowRecord(p); };
        _projectList.DoubleTapped += (_, _) => { if (_projectList.SelectedItem is ProjectItem p) _ = SelectProject(p).ContinueWith(_ => Avalonia.Threading.Dispatcher.UIThread.Post(() => SelectSection("changes"))); };
        var body = new DockPanel();
        var heads = Heads(ProjectColumns, "", Lang.T("ПРОЕКТ"), Lang.T("ВЕТКА"), Lang.T("СОСТОЯНИЕ"), "↑", Lang.T("GIT-КОПИЯ"), Lang.T("СЛОИ"));
        DockPanel.SetDock(heads, Dock.Top);
        body.Children.Add(heads);
        body.Children.Add(_projectList);
        var table = new Border { Classes = { "pane" }, Child = body, Margin = new Thickness(0, 0, 0, 10) };
        Grid.SetRow(table, 1);
        page.Children.Add(table);
        var two = new Grid { ColumnDefinitions = new ColumnDefinitions("*,10,*") };
        _record = new StackPanel();
        two.Children.Add(_record);
        var lab = BuildLab();
        Grid.SetColumn(lab, 2);
        two.Children.Add(lab);
        Grid.SetRow(two, 2);
        page.Children.Add(two);

        _cloneUrl = Grow(Field("адрес репозитория для клона", "", tip: "Адрес репозитория: git@github.com:owner/repo.git или https://... Клон ляжет в папку, выбранную в панели слева, и станет проектом реестра.", id: "clone_url"));
        SetOps(
            Op("статус всех", () => Batch("status"), "git status по всем проектам реестра - там, где живёт история: в GIT-КОПИИ, если в ней свой .git, иначе в ИСХОДНИКЕ. Чисто, изменено, ошибки - в таблицу и в терминал.", "read", "F2", id: "batch_status"),
            Op("планы зеркал", () => Batch("mirror-plan"), "План зеркала для каждого проекта: сколько скопировать, обновить, удалить.", "read", id: "batch_plan"),
            Op("секреты", () => Batch("safety"), "Проверка секретов и тяжёлых файлов во всех проектах.", "read", id: "batch_safety"),
            Op("сверка", () => Batch("verify"), "Сверка ИСХОДНИКА и GIT-КОПИИ всех проектов по BLAKE3.", "read", id: "batch_verify"),
            null,
            Op("найти в папке", () => _ = ScanFolder(), "Находит проекты в папке, выбранной в панели слева, и в её вложенных папках и дописывает их в реестр. Папки не трогает.", "local", id: "projects_scan"),
            _cloneUrl,
            Op("клонировать", () => _ = Clone(), Canon.Get("clone").Tip(), "net", id: "projects_clone"),
            null,
            Op("workspace", () => Hubbed("workspace", new[] { "workspace" }, "Общий .code-workspace для VS Code со всеми проектами реестра."), "Общий .code-workspace для VS Code со всеми проектами реестра.", "local", id: "projects_workspace"),
            Op("почистить реестр", () => _ = CleanRegistry(), "Убирает из реестра записи без папки ИСХОДНИКА и дубли. Сами папки не удаляет. Перед записью покажет, что уйдёт.", "local", cls: "burn", id: "projects_clean"));
        _keys[Key.F2] = () => Batch("status");
        return split;
    }

    // The name takes what is left; the branch, the state and the rest keep their widths beside the folder panel.
    const string ProjectColumns = "26,*,88,84,32,84,62";

    async Task UpdateProjects()
    {
        if (_projectList is null) return;
        // The panel marks the folders of the registry: after a search, a removal or a saved record they are others.
        ShowFolders();
        _projectList.ItemsSource = _projects.ToList();
        var pick = _projects.FirstOrDefault(p => p.Id == _project?.Id) ?? _projects.FirstOrDefault();
        if (pick is not null) _projectList.SelectedItem = pick;
        else ShowRecord(null);
        await Task.CompletedTask;
    }

    Control ProjectView(ProjectItem p)
    {
        _batchStatus.TryGetValue(p.Id, out var b);
        var layers = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 5, VerticalAlignment = VerticalAlignment.Center };
        foreach (var (layer, icon) in new[] { ("source", "folder-code"), ("mirror", "folder-git"), ("docs", "book-open-text") })
        {
            p.Layers.TryGetValue(layer, out var l);
            var sign = Sign(icon, !l.Exists ? "CrumbInk" : l.Repo == "own" ? "Quasar" : "GitModified");
            ToolTip.SetTip(sign, Lang.T(LayerName(layer)) + ": " + (!l.Exists ? Lang.T("нет папки") : l.Repo == "own" ? Lang.T("репозиторий") : l.Repo == "parent" ? Lang.T("внутри чужого репозитория") : Lang.T("без git")));
            layers.Children.Add(sign);
        }
        Control state = b is null ? Cell("—", quiet: true)
            : b["error"] is not null ? Pill("ошибка", "bad")
            : b["repo"]?.ToString() == "none" ? Pill("без git")
            : int.TryParse(b["files"]?.ToString(), out var files) && files > 0 ? Pill(Lang.F("{0} изм.", files), "mod") : Pill("чисто", "ok");
        if (b?["error"] is { } err) ToolTip.SetTip(state, err.ToString());
        else if (b?["inside"]?.ToString() is { Length: > 0 } inside) ToolTip.SetTip(state, Lang.F("Своего репозитория нет: папка лежит внутри {0}.", inside));
        p.Layers.TryGetValue("mirror", out var m);
        var name = Cell(p.Name, bold: p.Id == _project?.Id);
        var branch = Cell(b?["branch"]?.ToString() ?? "", quiet: true);
        var grid = Cells(ProjectColumns,
            Sign("folder-git-2", p.Id == _project?.Id ? "Quasar" : "CrumbInk"),
            name,
            branch,
            state,
            Cell(b?["ahead"]?.ToString() is { Length: > 0 } a && a != "0" ? "↑" + a : "", "GitStaged"),
            Pill(m.Exists ? "на месте" : "нет", m.Exists ? "ok" : ""),
            layers);
        grid.MinHeight = 30;
        ToolTip.SetTip(grid, p.Source);
        return grid;
    }

    TextBox? _recSource, _recMirror, _recDocs, _recBranch;

    void ShowRecord(ProjectItem? p)
    {
        if (_record is null) return;
        _record.Children.Clear();
        if (p is null) { _record.Children.Add(Block("ЗАПИСЬ", "Quasar", Note("Реестр пуст: найдите проекты в папке или создайте учебную лабораторию."))); return; }
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("92,*,Auto"), RowDefinitions = new RowDefinitions("Auto,6,Auto,6,Auto,6,Auto,10,Auto") };
        TextBox Row(int r, string name, string value, string tip)
        {
            var label = Text(name, "colhead");
            Grid.SetRow(label, r);
            grid.Children.Add(label);
            var box = Field("", value, double.NaN, tip);
            Grid.SetRow(box, r); Grid.SetColumn(box, 1);
            grid.Children.Add(box);
            var pick = new Button { Classes = { "tool" }, Content = Sign("folder-input"), Margin = new Thickness(6, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center };
            ToolTip.SetTip(pick, Lang.T("Взять папку, выбранную в панели слева. Запишет её кнопка «сохранить»."));
            Avalonia.Automation.AutomationProperties.SetAutomationId(pick, "record_pick_" + r switch { 0 => "source", 2 => "mirror", _ => "docs" });
            pick.Click += (_, _) =>
            {
                if (PickedFolder() is { } folder) box.Text = folder;
                else SetStatus("Выберите папку в панели слева.");
            };
            Grid.SetRow(pick, r); Grid.SetColumn(pick, 2);
            grid.Children.Add(pick);
            return box;
        }
        _recSource = Row(0, "ИСХОДНИК", p.Source, "Папка живого проекта целиком - источник истины.");
        _recMirror = Row(2, "GIT-КОПИЯ", p.Mirror, "Папка чистого зеркала проекта: сюда зеркало копирует то, что пропускает профиль.");
        _recDocs = Row(4, "DOCS", p.Docs, "Папка документов для чтения (необязательно).");
        _recBranch = Field("main", p.Branch, 120, "Ветка по умолчанию: её берут pull и push, пока у ветки нет пары.");
        var branchLabel = Text("ВЕТКА", "colhead");
        Grid.SetRow(branchLabel, 6); grid.Children.Add(branchLabel);
        Grid.SetRow(_recBranch, 6); Grid.SetColumn(_recBranch, 1); _recBranch.HorizontalAlignment = HorizontalAlignment.Left; grid.Children.Add(_recBranch);
        var save = Op("сохранить", () => _ = SaveRecord(p), "Записать папки и ветку в реестр корня проектов (hub_projects.json). Пути внутри корня пишутся относительными: папки переезжают вместе с ним.", "local", sm: true, cls: "quiet", id: "record_save");
        var remove = Op("убрать из реестра", () => _ = RemoveRecord(p), "Убрать запись из реестра корня проектов (hub_projects.json). Сами папки - ИСХОДНИК, GIT-КОПИЯ, DOCS - не трогаются.", "local", sm: true, cls: "quiet", id: "record_remove");
        // Under the fields, not in the head of the block: beside the folder panel the head has room for the name alone.
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, HorizontalAlignment = HorizontalAlignment.Right, Children = { remove, save } };
        Grid.SetRow(buttons, 8); Grid.SetColumnSpan(buttons, 3); grid.Children.Add(buttons);
        _record.Children.Add(Block(Lang.T("ЗАПИСЬ") + " · " + p.Name, "Quasar", grid));
        ApplyBusy();
    }

    async Task SaveRecord(ProjectItem p)
    {
        var answer = await Hub.Ask("projects", "set", p.Id, "--source", _recSource?.Text ?? "", "--mirror", _recMirror?.Text ?? "",
            "--docs", _recDocs?.Text ?? "", "--branch", _recBranch?.Text ?? "main");
        AppendLines(new[] { "", "› " + answer.Line, answer.Ok ? "[OK] " + Lang.T("запись сохранена") : "[ERR] " + answer.Error });
        await LoadProjects();
        ShowProject();
        await UpdateProjects();
        RefreshSoon(0);
    }

    Control BuildLab()
    {
        var words = Text("Десять учебных репозиториев в examples\\lab: первый коммит, индекс, ветки и слияние, конфликт, отставание от «сервера» в папке, отложенное, теги версий, «потерянный» коммит, откат, пара ИСХОДНИК + GIT-КОПИЯ. Ломайте смело: кнопка строит их заново - те же коммиты, те же хэши - и вносит в реестр.", "note");
        var build = Op("создать заново", () => RunSteps(HubStep("лаборатория", new[] { "lab", "create", "--replace", "--register" },
            "Строит десять учебных репозиториев заново (прежние - в Корзину) и вносит их в реестр.", (code, json) =>
            {
                JsonObject? root = null;
                try { root = JsonNode.Parse(json) as JsonObject; } catch { }
                if (root?["repos"] is JsonObject repos) AppendLines(new[] { "[OK] " + string.Join("  ", repos.Select(r => r.Key)) });
                if (root?["error"]?.ToString() is { Length: > 0 } error) AppendLines(new[] { "[ERR] " + error });
                _ = LoadProjects().ContinueWith(_ => Avalonia.Threading.Dispatcher.UIThread.Post(() => { ShowProject(); _ = UpdateProjects(); }));
            })), "Строит учебные репозитории examples\\lab заново и вносит их в реестр. Прежние уходят в Корзину.", "local", sm: true, cls: "quiet", id: "lab_create");
        var open = Op("открыть LAB.md", () => OpenInCode(Path.Combine(Paths.Root, "examples", "lab", "LAB.md")), "Что в каждом репозитории и что в нём попробовать.", "read", sm: true);
        return Block("УЧЕБНАЯ ЛАБОРАТОРИЯ", "AmberInk", new StackPanel { Spacing = 8, Children = { words, new WrapPanel { Children = { open } } } }, build);
    }

    void Batch(string action)
    {
        var what = action switch
        {
            "status" => "git status по всем проектам реестра - в GIT-КОПИИ, где есть её .git, иначе в ИСХОДНИКЕ.",
            "mirror-plan" => "План зеркала для каждого проекта.",
            "safety" => "Проверка секретов и тяжёлых файлов во всех проектах.",
            _ => "Сверка ИСХОДНИКА и GIT-КОПИИ всех проектов.",
        };
        RunSteps(HubStep("batch " + action, new[] { "batch", action }, what, (code, json) =>
        {
            JsonObject? root = null;
            try { root = JsonNode.Parse(json) as JsonObject; } catch { }
            if (root?["summary"] is JsonObject s) AppendLines(new[] { "[GUI] " + string.Join(" · ", s.Select(kv => kv.Key + " " + kv.Value)) });
            if (root?["results"] is JsonArray results)
                foreach (var r in results.OfType<JsonObject>())
                {
                    var id = r["project_id"]?.ToString() ?? "";
                    if (action == "status") _batchStatus[id] = r;
                    var error = r["error"]?.ToString();
                    AppendLines(new[] { (error is null ? "  " : "[ERR] ") + Lang.T(r["title"]?.ToString() ?? id) + ": " +(error ?? (r["summary"] is JsonObject rs ? string.Join(", ", rs.Where(kv => kv.Value is JsonValue).Take(6).Select(kv => kv.Key + " " + kv.Value)) : r["repo"]?.ToString() == "none" ? Lang.T(LayerName(r["layer"]?.ToString() ?? "source")) + " · " + Lang.T("без git") : Lang.F("{0} · {1} · {2} изм. · ↑{3} ↓{4}", Lang.T(LayerName(r["layer"]?.ToString() ?? "source")), r["branch"]?.ToString() ?? "", r["files"]?.ToString() ?? "", r["ahead"]?.ToString() ?? "", r["behind"]?.ToString() ?? ""))) });
                }
            if (root?["report"]?.ToString() is { Length: > 0 } report) AppendLines(new[] { "[GUI] " + Lang.F("отчёт: {0}", Paths.Short(report)) });
            // The column of projects shows the count of changes of each project the batch read.
            if (action == "status") ShowSide(true);
            _ = UpdateProjects();
        }));
    }

    void Hubbed(string name, string[] args, string what) => RunSteps(HubStep(name, args, what, (code, json) =>
    {
        JsonObject? root = null;
        try { root = JsonNode.Parse(json) as JsonObject; } catch { }
        if (root?["workspace"]?.ToString() is { Length: > 0 } file) AppendLines(new[] { "[OK] " + Paths.Short(file) });
        if (root?["error"]?.ToString() is { Length: > 0 } error) AppendLines(new[] { "[ERR] " + error });
    }));

    async Task ScanFolder()
    {
        if (PickedFolder() is not { } folder) { SetStatus("Выберите папку в панели слева."); return; }
        _asking = true;
        ApplyBusy();
        bool go;
        try { go = await Views.AskDialog.YesNo(this, "Найти проекты в папке?", Lang.F("Папка: {0}", folder) + "\n\n" + Lang.T("Папка, которая сама проект, заводит себя; общая папка - проекты в своих вложенных. Найденные допишутся в реестр, сами папки не трогаются."), "run"); }
        finally { _asking = false; ApplyBusy(); }
        if (!go) return;
        RunSteps(HubStep("найти проекты", new[] { "projects", "scan", folder, "--import" }, "Находит проекты во вложенных папках и дописывает их в реестр. Папки не трогает.", (code, json) =>
        {
            JsonObject? root = null;
            try { root = JsonNode.Parse(json) as JsonObject; } catch { }
            if (root?["summary"] is JsonObject s) AppendLines(new[] { "[OK] " + Lang.F("найдено {0}, добавлено {1}, уже были {2}", s["candidates"], s["imported"], s["skipped"]) });
            if (root?["error"]?.ToString() is { Length: > 0 } error) AppendLines(new[] { "[ERR] " + error });
            _ = LoadProjects().ContinueWith(_ => Avalonia.Threading.Dispatcher.UIThread.Post(() => _ = UpdateProjects()));
        }));
    }

    async Task Clone()
    {
        var url = (_cloneUrl?.Text ?? "").Trim();
        if (url.Length == 0) { SetStatus("Впишите адрес репозитория внизу."); return; }
        if (PickedFolder() is not { } parent) { SetStatus("Выберите папку в панели слева."); return; }
        var name = url.TrimEnd('/').Split('/', ':').Last();
        if (name.EndsWith(".git", StringComparison.OrdinalIgnoreCase)) name = name[..^4];
        _asking = true;
        ApplyBusy();
        bool go;
        try { go = await Views.AskDialog.YesNo(this, "Клонировать репозиторий?", Lang.F("Адрес: {0}", url) + "\n" + Lang.F("Куда: {0}", Path.Combine(parent, name)) + "\n\n" + Lang.T("Клон станет проектом реестра."), "run"); }
        finally { _asking = false; ApplyBusy(); }
        if (!go) return;
        var entry = Canon.Get("clone");
        var argv = entry.Argv(new() { ["url"] = url, ["dest"] = name });
        RunSteps(GitStep(entry, argv, parent, code =>
        {
            if (code != 0) return;
            var target = Path.Combine(parent, name);
            RunSteps(HubStep("в реестр", new[] { "projects", "scan", target, "--import", "--depth", "0" }, "Вносит склонированный проект в реестр.", (_, _) =>
                _ = LoadProjects().ContinueWith(_ => Avalonia.Threading.Dispatcher.UIThread.Post(() => _ = UpdateProjects()))));
        }));
    }

    async Task RemoveRecord(ProjectItem p)
    {
        _asking = true;
        ApplyBusy();
        bool go;
        try { go = await Views.AskDialog.YesNo(this, "Убрать из реестра?", p.Name + "\n" + p.Source + "\n\n" + Lang.T("Сами папки не трогаются."), "burn"); }
        finally { _asking = false; ApplyBusy(); }
        if (!go) return;
        Hubbed("убрать из реестра", new[] { "projects", "remove", p.Id }, "Убирает запись из реестра; папки не трогаются.");
        RunSteps(HubStep("реестр", new[] { "projects", "list", "--fast" }, "", (_, _) =>
            _ = LoadProjects().ContinueWith(_ => Avalonia.Threading.Dispatcher.UIThread.Post(() => { ShowProject(); _ = UpdateProjects(); }))));
    }

    async Task CleanRegistry()
    {
        var preview = await Hub.Ask("projects", "clean", "--dry-run");
        if (!preview.Ok) { AppendLines(new[] { "[ERR] " + preview.Error }); return; }
        var removed = (preview.Json?["removed"] as JsonArray ?? new()).OfType<JsonObject>().Select(r => Lang.T(r["title"]?.ToString() ?? "") + " - " + r["reason"]).ToList();
        if (removed.Count == 0) { SetStatus("В реестре нечего чистить: у всех записей есть папки, дублей нет."); return; }
        _asking = true;
        ApplyBusy();
        bool go;
        try { go = await Views.AskDialog.YesNo(this, "Почистить реестр?", Lang.F("Уйдут записи ({0}):", removed.Count) + "\n" + string.Join("\n", removed.Take(12)) + "\n\n" + Lang.T("Сами папки не трогаются."), "burn"); }
        finally { _asking = false; ApplyBusy(); }
        if (!go) return;
        Hubbed("почистить реестр", new[] { "projects", "clean" }, "Убирает из реестра записи без папок и дубли.");
        RunSteps(HubStep("реестр", new[] { "projects", "list", "--fast" }, "", (_, _) =>
            _ = LoadProjects().ContinueWith(_ => Avalonia.Threading.Dispatcher.UIThread.Post(() => { ShowProject(); _ = UpdateProjects(); }))));
    }
}
