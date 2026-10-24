using System.Collections.Generic;
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
/// ЗЕРКАЛО: the clean Git copy of the project. The profile says by its rules what a Git copy holds - code, documents,
/// configs - and what never - runtime, logs, builds, secrets. The plan says what the mirror would copy, update and
/// remove; it writes nothing. ПРИМЕНИТЬ writes the plan into the Git copy (the project itself is never written to,
/// .git is protected); the BLAKE3 check compares the two. Then the Git copy is committed like any repository.
/// </summary>
public partial class MainWindow
{
    StackPanel? _profileBox;
    Grid? _planTiles;
    ListBox? _planList;
    CheckBox? _dryRun;
    JsonObject? _plan;

    Control BuildMirror()
    {
        var page = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,Auto,*") };
        var head = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, Margin = new Thickness(0, 0, 0, 10), Children =
        {
            new TextBlock { Classes = { "pagetitle" }, Text = Upper(Lang.T("ЗЕРКАЛО")) },
            new TextBlock { Classes = { "caption" }, Text = "→ " + Lang.T("ИСХОДНИК в GIT-КОПИЮ") },
        } };
        page.Children.Add(head);
        _profileBox = new StackPanel { Spacing = 8 };
        _dryRun = new CheckBox { Classes = { "tick" }, Content = Lang.T("сухой прогон"), IsChecked = true };
        ToolTip.SetTip(_dryRun, Lang.T("ПРИМЕНИТЬ только покажет, что сделал бы, и ничего не запишет. Снимите, чтобы записать."));
        var profile = Block("ПРОФИЛЬ", "Quasar", _profileBox, _dryRun);
        profile.Margin = new Thickness(0, 0, 0, 10);
        Grid.SetRow(profile, 1);
        page.Children.Add(profile);
        _planTiles = new Grid { ColumnDefinitions = new ColumnDefinitions("*,8,*,8,*,8,*,8,*"), Margin = new Thickness(0, 0, 0, 10) };
        Grid.SetRow(_planTiles, 2);
        page.Children.Add(_planTiles);
        _planList = Rows("plan");
        _planList.ItemTemplate = new FuncDataTemplate<PlanRow>((row, _) => row is null ? new Panel() : PlanView(row), supportsRecycling: false);
        var listBody = new DockPanel();
        var heads = Heads("110,*,220", Lang.T("ДЕЙСТВИЕ"), Lang.T("ПУТЬ"), Lang.T("ПОЧЕМУ"));
        DockPanel.SetDock(heads, Dock.Top);
        listBody.Children.Add(heads);
        listBody.Children.Add(_planList);
        var list = new Border { Classes = { "pane" }, Child = listBody };
        Grid.SetRow(list, 3);
        page.Children.Add(list);
        ShowPlan();

        SetOps(
            Op("план", () => MirrorRun("plan"), "Строит план ИСХОДНИК → GIT-КОПИЯ по профилю: что скопировать, обновить, удалить. Ничего не пишет. Отчёт - в logs\\<проект>.", "read", "F2", id: "mirror_plan"),
            Op("сверить BLAKE3", () => MirrorRun("verify"), "Сверяет ИСХОДНИК и GIT-КОПИЮ по хэшам BLAKE3: совпадает ли копия с проектом. Ничего не пишет.", "read", id: "mirror_verify"),
            null,
            Grow(new TextBlock { Classes = { "caption" }, Text = Lang.T("после - переключитесь на GIT-КОПИЮ и закоммитьте её"), HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 10, 0) }),
            Op("ПРИМЕНИТЬ", () => MirrorRun("apply"), "Выполняет план: копирует разрешённые профилем файлы в GIT-КОПИЮ, обновляет изменённые, убирает лишние. ИСХОДНИК не меняется, .git защищён. С галочкой «сухой прогон» только показывает.", "local", cls: "fill", id: "mirror_apply"));
        _keys[Key.F2] = () => MirrorRun("plan");
        return page;
    }

    async Task UpdateMirror()
    {
        if (_profileBox is null || _project is null) return;
        var answer = await Hub.Ask("profile", _project.Id);
        _profileBox.Children.Clear();
        if (answer.Json?["profile"] is not JsonObject p) { _profileBox.Children.Add(Text(answer.Error.Length > 0 ? answer.Error : "Профиль не прочитан.", "note")); return; }
        var title = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, Children =
        {
            new TextBlock { Text = p["id"]?.ToString() ?? "", FontWeight = FontWeight.Bold, VerticalAlignment = VerticalAlignment.Center },
            Pill(Lang.F("сравнение: {0}", p["compare_mode"]?.ToString() ?? ""), "info"),
            Pill(p["mirror"]?.GetValue<bool>() == true ? "точное зеркало: лишнее удаляется" : "только добавляет", ""),
        } };
        _profileBox.Children.Add(title);
        var rules = new WrapPanel();
        void Rule(string text, bool take)
        {
            var b = Pill(text, take ? "ok" : "");
            b.Margin = new Thickness(0, 0, 5, 5);
            if (!take && b.Child is TextBlock t) t.TextDecorations = TextDecorations.Strikethrough;
            ToolTip.SetTip(b, Lang.T(take ? "Пропускает: такие файлы идут в GIT-КОПИЮ и в коммит." : "Не пропускает: такие файлы и папки не идут никуда."));
            rules.Children.Add(b);
        }
        foreach (var g in (p["include_globs"] as JsonArray ?? new()).Take(18)) Rule(g!.ToString(), true);
        foreach (var g in (p["hide_dirs"] as JsonArray ?? new()).Concat(p["forbidden_dirs"] as JsonArray ?? new()).Select(x => x!.ToString() + "/").Distinct().Take(10)) Rule(g, false);
        foreach (var g in (p["exclude_globs"] as JsonArray ?? new()).Take(12)) Rule(g!.ToString(), false);
        _profileBox.Children.Add(rules);
        _profileBox.Children.Add(Text(Lang.F("ИСХОДНИК: {0}\nGIT-КОПИЯ: {1}", _project.Source, _project.Mirror), "caption"));
    }

    void MirrorRun(string action)
    {
        if (_project is null) return;
        var args = new List<string> { "mirror", action, _project.Id };
        if (action == "apply") args.Add(_dryRun?.IsChecked == false ? "--apply" : "--dry-run");
        var what = action switch
        {
            "plan" => "Строит план ИСХОДНИК → GIT-КОПИЯ по профилю. Ничего не пишет.",
            "verify" => "Сверяет ИСХОДНИК и GIT-КОПИЮ по хэшам BLAKE3.",
            _ => _dryRun?.IsChecked == false ? "Пишет план в GIT-КОПИЮ: копирует, обновляет, убирает лишнее. ИСХОДНИК не меняется." : "Сухой прогон: показывает, что записал бы, и ничего не пишет.",
        };
        RunSteps(HubStep("mirror " + action, args, what, (code, json) =>
        {
            JsonObject? root = null;
            try { root = JsonNode.Parse(json) as JsonObject; } catch { }
            var result = root?["result"] as JsonObject;
            var summary = result?["summary"] as JsonObject;
            if (summary is not null) AppendLines(new[] { Summary(action, summary) });
            if (root?["report"]?.ToString() is { Length: > 0 } report) AppendLines(new[] { "[GUI] " + Lang.F("отчёт: {0}", Paths.Short(report)) });
            if (root?["error"]?.ToString() is { Length: > 0 } error) AppendLines(new[] { "[ERR] " + error });
            if (action == "plan" && result is not null) { _plan = result; ShowPlan(); }
            if (action == "apply" && _dryRun?.IsChecked == false && code == 0) { _plan = null; ShowPlan(); RefreshSoon(); }
        }));
    }

    static string Summary(string action, JsonObject s)
    {
        string N(string key) => s[key]?.ToString() ?? "0";
        return action == "verify"
            ? Lang.F("совпадает {0} · изменено {1} · нет в копии {2} · лишних {3} · ошибок {4}", N("same"), N("changed"), N("missing"), N("extra"), N("errors"))
            : Lang.F("скопировать {0} · обновить {1} · удалить {2} · без изменений {3} · вне профиля {4} · спрятано .gitignore {5}", N("copy"), N("touch"), N("delete"), N("same"), Skipped(s), Hidden(s));
    }

    /// <summary>What the project's own .gitignore hid from the mirror: its word, standing over the profile.</summary>
    static string Hidden(JsonObject? s) => s?["source_scan"] is JsonObject scan ? scan["skipped_by_gitignore"]?.ToString() ?? "0" : "—";

    /// <summary>What the profile kept out of the project: by its list, by its exclusions, by size.</summary>
    static string Skipped(JsonObject? s)
    {
        if (s?["source_scan"] is not JsonObject scan) return "—";
        int n(string key) => int.TryParse(scan[key]?.ToString(), out var v) ? v : 0;
        return (n("skipped_by_include") + n("skipped_by_exclude") + n("skipped_by_size")).ToString();
    }

    sealed record PlanRow(string Action, string Path, string Why);

    void ShowPlan()
    {
        if (_planTiles is null || _planList is null) return;
        _planTiles.Children.Clear();
        var s = _plan?["summary"] as JsonObject;
        int col = 0;
        foreach (var (key, word, ink) in new[] { ("copy", "НОВЫХ", "GitStaged"), ("touch", "ОБНОВИТЬ", "GitModified"), ("delete", "УДАЛИТЬ ЛИШНИХ", "BurnInk"), ("same", "БЕЗ ИЗМЕНЕНИЙ", "TextMain"), ("skipped", "ВНЕ ПРОФИЛЯ", "CrumbInk") })
        {
            var value = key == "skipped" ? Skipped(s) : s?[key]?.ToString() ?? "—";
            var number = new TextBlock { Classes = { "bignum" }, Text = value }.Ink(TextBlock.ForegroundProperty, ink);
            var tile = new Border { Classes = { "pane" }, Padding = new Thickness(12, 8), Child = new StackPanel { Children = { number, Text(word, "colhead") } } };
            Grid.SetColumn(tile, col);
            col += 2;
            _planTiles.Children.Add(tile);
        }
        var rows = new List<PlanRow>();
        if (_plan?["items"] is JsonArray items)
            foreach (var item in items.OfType<JsonObject>().Take(3000))
            {
                var action = item["action"]?.ToString() ?? "";
                if (action == "same") continue;
                rows.Add(new PlanRow(action, item["rel_path"]?.ToString() ?? item["path"]?.ToString() ?? "", item["reason"]?.ToString() ?? ""));
            }
        _planList.ItemsSource = rows.Count > 0 ? rows : new List<PlanRow> { new("", _plan is null ? Lang.T("Нажмите «план» (F2): здесь будет, что зеркало скопирует, обновит и удалит.") : Lang.T("Копия совпадает с проектом: делать нечего."), "") };
    }

    Control PlanView(PlanRow row)
    {
        if (row.Action.Length == 0) return new TextBlock { Classes = { "note" }, Text = row.Path, Margin = new Thickness(10, 8) };
        var (word, kind) = row.Action switch
        {
            "copy" => ("НОВЫЙ", "ok"), "touch" or "update" => ("ОБНОВИТЬ", "mod"), "delete" => ("УДАЛИТЬ", "bad"), _ => (row.Action.ToUpperInvariant(), ""),
        };
        var grid = Cells("110,*,220", Pill(word, kind), Cell(row.Path), Cell(row.Why, quiet: true));
        grid.MinHeight = 26;
        return grid;
    }
}
