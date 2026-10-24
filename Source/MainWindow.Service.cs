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
using AudionHubManager.Core;

namespace AudionHubManager;

/// <summary>
/// ОБСЛУЖИВАНИЕ: the checks - secrets and heavy files, the mirror against the project, the roots of the storage, the
/// engine of hashes; a backup of the whole history in one file; the health of the repository; the settings of Git; the
/// reports the checks left in logs\&lt;project&gt;. What the last secrets check found is a table: what, where, and
/// whether it would go into Git.
/// </summary>
public partial class MainWindow
{
    ListBox? _findings, _reports;
    StackPanel? _checks;
    JsonObject? _safety;

    Control BuildService()
    {
        var page = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,*") };
        page.Children.Add(new TextBlock { Classes = { "pagetitle" }, Text = Upper(Lang.T("ОБСЛУЖИВАНИЕ")), Margin = new Thickness(0, 0, 0, 10) });
        var top = new Grid { ColumnDefinitions = new ColumnDefinitions("*,10,*"), RowDefinitions = new RowDefinitions("Auto,10,Auto"), Margin = new Thickness(0, 0, 0, 10) };
        _checks = new StackPanel { Spacing = 4 };
        top.Children.Add(Block("ПРОВЕРКИ", "GitRenamed", _checks));
        var backup = new StackPanel { Spacing = 8, Children =
        {
            Text("Вся история ветки и теги одним файлом - на флешку или в облако, без сервера. Поднимается командой git clone ‹файл›.", "note"),
            OpCanon("bundle", "git bundle create", BundleValues, sm: true),
        } };
        var b = Block("РЕЗЕРВ", "LogExplain", backup);
        Grid.SetColumn(b, 2);
        top.Children.Add(b);
        var health = new WrapPanel();
        foreach (var x in new Control[] { OpCanon("fsck", "git fsck --full", () => null, sm: true), OpCanon("gc", "git gc", () => null, sm: true), OpCanon("clean_preview", "что лишнее (clean -nd)", () => null, sm: true) })
        { x.Margin = new Thickness(0, 0, 6, 6); health.Children.Add(x); }
        var h = Block("ЗДОРОВЬЕ РЕПОЗИТОРИЯ", "GitStaged", health);
        Grid.SetRow(h, 2);
        top.Children.Add(h);
        var config = new WrapPanel();
        foreach (var x in new Control[]
        {
            OpCanon("config_user", "кто подписывает коммиты", () => null, sm: true),
            OpCanon("config_list", "все настройки", () => null, sm: true),
            OpCanon("root", "корень репозитория", () => null, sm: true),
            Op("git init", Init, Canon.Get("init").Tip(), "local", sm: true, id: "op_init", command: Canon.Get("init").Short),
        }) { x.Margin = new Thickness(0, 0, 6, 6); config.Children.Add(x); }
        var c = Block("НАСТРОЙКИ GIT", "CrumbInk", config);
        Grid.SetRow(c, 2); Grid.SetColumn(c, 2);
        top.Children.Add(c);
        Grid.SetRow(top, 1);
        page.Children.Add(top);

        var lists = new Grid { ColumnDefinitions = new ColumnDefinitions("*,10,*") };
        _findings = Rows("findings");
        _findings.ItemTemplate = new FuncDataTemplate<JsonObject>((f, _) => f is null ? new Panel() : FindingView(f), supportsRecycling: false);
        var findingsBody = new DockPanel();
        var fh = Heads("*,150,100", Lang.T("ПРОВЕРКА СЕКРЕТОВ · НАЙДЕНО"), Lang.T("ЧТО"), Lang.T("В GIT?"));
        DockPanel.SetDock(fh, Dock.Top);
        findingsBody.Children.Add(fh);
        findingsBody.Children.Add(_findings);
        lists.Children.Add(new Border { Classes = { "pane" }, Child = findingsBody });
        _reports = Rows("reports");
        _reports.ItemTemplate = new FuncDataTemplate<FileInfo>((f, _) => f is null ? new Panel() : ReportView(f), supportsRecycling: false);
        _reports.DoubleTapped += (_, _) => { if (_reports.SelectedItem is FileInfo f) OpenInCode(f.FullName); };
        var reportsBody = new DockPanel();
        var rh = Heads("*,120", Lang.T("ОТЧЁТЫ") + (_project is null ? "" : " · logs\\" + _project.Id), Lang.T("КОГДА"));
        DockPanel.SetDock(rh, Dock.Top);
        reportsBody.Children.Add(rh);
        reportsBody.Children.Add(_reports);
        var reports = new Border { Classes = { "pane" }, Child = reportsBody };
        Grid.SetColumn(reports, 2);
        lists.Children.Add(reports);
        Grid.SetRow(lists, 2);
        page.Children.Add(lists);

        SetOps(
            Op("секреты", () => Check("safety"), "Ищет похожие на секреты файлы, ключи и токены в тексте, тяжёлые бинарники - в слое ИСХОДНИК или GIT-КОПИЯ.", "read", "F2", id: "check_safety"),
            Op("сверка", () => MirrorRun("verify"), "Сверяет ИСХОДНИК и GIT-КОПИЮ по хэшам BLAKE3.", "read", id: "check_verify"),
            Op("хранилище", () => Check("storage"), "Проверяет корни: программа, GIT-КОПИИ, DOCS, проекты - и что роли не перепутаны.", "read", id: "check_storage"),
            Op("BLAKE3", () => Check("blake3"), "Настоящий ли BLAKE3 стоит или запасной SHA-256.", "read", id: "check_blake3"),
            null,
            Grow(new Border()),
            Op("открыть logs", () => OpenFolder(_project is null ? Paths.ProgramLogs : Path.Combine(Paths.ProgramLogs, _project.Id)), "Папка отчётов проекта.", "read", id: "open_logs"));
        _keys[Key.F2] = () => Check("safety");
        return page;
    }

    Dictionary<string, object>? BundleValues()
    {
        var folder = Path.Combine(Paths.Root, "backup");
        try { Directory.CreateDirectory(folder); } catch { }
        var name = (_project?.Id ?? "repo") + "-" + DateTime.Now.ToString("yyyyMMdd-HHmm") + ".bundle";
        var (_, branch) = Upstream();
        return new() { ["bundle"] = Path.Combine(folder, name), ["branch"] = _state?.Branch is { Length: > 0 } b && !(_state?.Detached ?? false) ? b : branch };
    }

    /// <summary>git init in the folder of the layer - the one command that runs where there is no repository yet.</summary>
    void Init()
    {
        var folder = LayerFolder();
        if (folder.Length == 0) { SetStatus("Папка слоя не задана: ПРОЕКТЫ → ЗАПИСЬ."); return; }
        if (_repoKind == "own") { SetStatus("Здесь уже репозиторий."); return; }
        try { Directory.CreateDirectory(folder); } catch { }
        // The first branch is the project's branch of the registry, not whatever Git of this machine would name it.
        var entry = Canon.Get("init");
        RunSteps(GitStep(entry, entry.Argv(new() { ["branch"] = _project?.Branch is { Length: > 0 } branch ? branch : "main" }), folder));
    }

    void Check(string what)
    {
        if (_project is null && what == "safety") return;
        var layer = _settings.Layer == "mirror" ? "mirror" : "source";
        string[] args = what switch
        {
            "safety" => new[] { "safety", _project!.Id, "--layer", layer },
            "storage" => new[] { "storage" },
            _ => new[] { "blake3" },
        };
        var words = what switch
        {
            "safety" => "Ищет секреты и тяжёлые файлы в слое: имена вроде .env и *.pem, ключи и токены в тексте, бинарники больше 25 МБ.",
            "storage" => "Проверяет корни хранилища: программа, GIT-КОПИИ, DOCS, проекты.",
            _ => "Проверяет движок хэшей: BLAKE3 или запасной SHA-256.",
        };
        RunSteps(HubStep(what, args, words, (code, json) =>
        {
            JsonObject? root = null;
            try { root = JsonNode.Parse(json) as JsonObject; } catch { }
            var result = root?["result"] as JsonObject;
            if (what == "safety" && result is not null)
            {
                _safety = result;
                var s = result["summary"] as JsonObject;
                AppendLines(new[] { (code == 0 ? "[OK] " : "[ERR] ") + Lang.F("находок {0}: блокирующих {1}, предупреждений {2}", s?["findings"], s?["blockers"], s?["warnings"]) });
                ShowFindings();
            }
            else if (result is not null) AppendLines(new[] { (code == 0 ? "[OK] " : "[ERR] ") + string.Join(" · ", result.Where(kv => kv.Value is JsonValue).Take(6).Select(kv => kv.Key + " " + kv.Value)) });
            if (root?["report"]?.ToString() is { Length: > 0 } report) AppendLines(new[] { "[GUI] " + Lang.F("отчёт: {0}", Paths.Short(report)) });
            if (root?["error"]?.ToString() is { Length: > 0 } error) AppendLines(new[] { "[ERR] " + error });
            ShowReports();
        }));
    }

    async Task UpdateService()
    {
        ShowChecks();
        ShowFindings();
        ShowReports();
        await Task.CompletedTask;
    }

    void ShowChecks()
    {
        if (_checks is null) return;
        _checks.Children.Clear();
        var s = _safety?["summary"] as JsonObject;
        void Line(string icon, string ink, string name, Control state)
        {
            var row = Cells("20,*,Auto", Sign(icon, ink), Cell(Lang.T(name)), state);
            row.Margin = new Thickness(0);
            _checks.Children.Add(row);
        }
        Line("shield-check", s is null ? "CrumbInk" : (int.TryParse(s["blockers"]?.ToString(), out var bl) && bl > 0) ? "BurnInk" : "GitStaged", "секреты и тяжёлые файлы",
            s is null ? Pill("не проверялось") : Pill(Lang.F("находок {0}", s["findings"]), int.TryParse(s["blockers"]?.ToString(), out var b2) && b2 > 0 ? "bad" : "ok"));
        Line("scan-search", "CrumbInk", "сверка зеркала BLAKE3", Pill("кнопка «сверка»"));
        Line("hard-drive", "CrumbInk", "корни хранилища", Pill("кнопка «хранилище»"));
        var blake = (_tools?["blake3"] as JsonObject)?["path"]?.ToString() ?? "";
        Line("cpu", blake == "blake3" ? "GitStaged" : "GitModified", "движок хэшей", Pill(blake.Length > 0 ? blake : "—", blake == "blake3" ? "ok" : "mod"));
    }

    void ShowFindings()
    {
        if (_findings is null) return;
        var list = (_safety?["findings"] as JsonArray ?? new()).OfType<JsonObject>().Take(500).ToList();
        _findings.ItemsSource = list.Count > 0 ? list : new List<JsonObject> { new() { ["empty"] = _safety is null ? Lang.T("Нажмите «секреты» (F2): здесь будет, что похоже на секрет или тяжёлый файл.") : Lang.T("Ничего похожего на секреты и тяжёлые файлы.") } };
    }

    Control FindingView(JsonObject f)
    {
        if (f["empty"] is { } empty) return new TextBlock { Classes = { "note" }, Text = empty.ToString(), Margin = new Thickness(10, 8) };
        var path = f["path"]?.ToString() ?? f["rel_path"]?.ToString() ?? "";
        var flags = string.Join(", ", (f["flags"] as JsonArray ?? new()).Select(x => x?.ToString()));
        var severity = f["severity"]?.ToString() ?? "";
        Control inGit = Pill("?", "");
        if (_project is not null)
        {
            // Would it go into Git: the profile of the project decides (the panel of changes asks the same).
            bool outOfProfile = _outOfProfile.ContainsKey(path) || flags.Contains("heavy") && !flags.Contains("secret");
            inGit = outOfProfile ? Pill("нет - вне профиля", "ok") : Pill(severity == "blocker" ? "да - уйдёт с push" : "проверьте", severity == "blocker" ? "bad" : "mod");
        }
        var grid = Cells("*,150,100", Cell(path), Pill(flags.Length > 0 ? flags : severity, severity == "blocker" ? "bad" : "mod"), inGit);
        grid.MinHeight = 28;
        ToolTip.SetTip(grid, path + "\n" + flags + (f["line"] is { } line ? "\n" + Lang.T("строка") + " " + line : ""));
        return grid;
    }

    void ShowReports()
    {
        if (_reports is null) return;
        var folder = _project is null ? Paths.ProgramLogs : Path.Combine(Paths.ProgramLogs, _project.Id);
        List<FileInfo> files = new();
        try { if (Directory.Exists(folder)) files = new DirectoryInfo(folder).GetFiles("*.json").OrderByDescending(f => f.LastWriteTime).Take(60).ToList(); } catch { }
        _reports.ItemsSource = files;
    }

    static Control ReportView(FileInfo f)
    {
        var grid = Cells("*,120", Cell(f.Name), Cell(When(f.LastWriteTime), quiet: true));
        grid.MinHeight = 26;
        ToolTip.SetTip(grid, f.FullName + "\n" + Lang.T("Двойной щелчок - открыть в VS Code."));
        return grid;
    }
}
