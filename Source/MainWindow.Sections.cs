using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Media;
using AudionHubManager.Core;

namespace AudionHubManager;

/// <summary>
/// The sections - the modes of the window. Each builds its page (what is looked at) and its bar of frequent operations
/// under the page (what is done most), and is told again when the repository changes.
/// </summary>
public partial class MainWindow
{
    static readonly (string Id, string Icon, string Name, string Line, string Tip)[] SectionList =
    {
        ("changes", "file-diff", "ИЗМЕНЕНИЯ", "Что поменялось и как сохранить",
            "Что изменилось в слое и как это сохранить: файлы по стадиям, разница, сборка коммита."),
        ("history", "git-graph", "ИСТОРИЯ", "Граф коммитов, откат, теги",
            "Граф коммитов всех веток, коммит с его файлами, откат, теги, reflog."),
        ("branches", "git-branch", "ВЕТКИ", "Параллельная работа и слияние",
            "Ветки, сравнение, слияние, отложенные правки (stash), выход из застрявшего слияния."),
        ("sync", "cloud-sync", "СИНХРОНИЗАЦИЯ", "GitHub, GitLab, Forgejo",
            "Remote: GitHub, GitLab, Codeberg, Forgejo, Gitea. Fetch, pull, push, адреса, вход."),
        ("mirror", "layers", "ЗЕРКАЛО", "Чистая копия проекта для Git",
            "Чистая GIT-КОПИЯ проекта по профилю: план, применение, сверка BLAKE3."),
        ("projects", "folders", "ПРОЕКТЫ", "Реестр, сводка, лаборатория",
            "Все проекты реестра одним взглядом, пакетные проверки, учебная лаборатория Git."),
        ("service", "stethoscope", "ОБСЛУЖИВАНИЕ", "Проверки, резерв, здоровье",
            "Проверка секретов, сверка, резерв bundle, здоровье репозитория, настройки Git, инструменты машины."),
    };

    readonly Dictionary<string, (Border Badge, TextBlock Text)> _badges = new();

    void BuildSections()
    {
        SectionRow.Children.Clear();
        SectionRow.ColumnDefinitions.Clear();
        _badges.Clear();
        foreach (var (id, icon, name, line, tip) in SectionList)
        {
            var head = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 7, HorizontalAlignment = HorizontalAlignment.Center };
            head.Children.Add(Icons.Sign(icon));
            head.Children.Add(new TextBlock { Classes = { "sectionname" }, Text = Upper(Lang.T(name)) });
            var face = new StackPanel { VerticalAlignment = VerticalAlignment.Center, Children = { head } };
            face.Children.Add(new TextBlock { Classes = { "hint" }, Text = Lang.T(line), TextTrimming = TextTrimming.CharacterEllipsis });
            var badgeText = new TextBlock();
            var badge = new Border { Classes = { "pill" }, Child = badgeText, HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(0, 4, 6, 0), IsVisible = false, IsHitTestVisible = false };
            _badges[id] = (badge, badgeText);
            var tab = new ToggleButton { Classes = { "switch", "section" }, Tag = id, Content = face, HorizontalAlignment = HorizontalAlignment.Stretch, MinHeight = 48 };
            Avalonia.Automation.AutomationProperties.SetAutomationId(tab, "section_" + id);
            ToolTip.SetTip(tab, Lang.T(name) + "\n" + Lang.T(tip));
            tab.Click += (_, _) => SelectSection(id);
            var cell = new Panel { Children = { tab, badge } };
            if (SectionRow.ColumnDefinitions.Count > 0) SectionRow.ColumnDefinitions.Add(new ColumnDefinition(new GridLength(7)));
            SectionRow.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
            Grid.SetColumn(cell, SectionRow.ColumnDefinitions.Count - 1);
            SectionRow.Children.Add(cell);
        }
        MarkSection();
        ShowCounts();
    }

    void MarkSection()
    {
        foreach (var cell in SectionRow.Children.OfType<Panel>())
            if (cell.Children.OfType<ToggleButton>().FirstOrDefault() is { } tab) tab.IsChecked = (string?)tab.Tag == _settings.Section;
    }

    void SetBadge(string id, string text, string kind)
    {
        if (!_badges.TryGetValue(id, out var badge)) return;
        badge.Badge.IsVisible = text.Length > 0;
        badge.Text.Text = text;
        foreach (var name in new[] { "ok", "mod", "bad", "info", "vi" }) badge.Badge.Classes.Set(name, name == kind);
    }

    void SelectSection(string id)
    {
        if (_sheet.Length > 0) ToggleSheet(_sheet);
        _settings.Section = id;
        _settings.Save();
        ShowSection();
        _ = UpdateSection();
    }

    /// <summary>Builds the page and the bar of the section in sight, anew.</summary>
    void ShowSection()
    {
        MarkSection();
        _keys.Clear();
        _ctrlEnter = null;
        _starters.Clear();
        // The column of projects outlives the page: its КОММИТ ОТМЕЧЕННЫХ stays among the buttons a run turns off.
        if (_markedCommit is not null) _starters.Add(_markedCommit);
        PageHost.Children.Clear();
        PageNote.IsVisible = false;
        if (!Canon.Loaded) return;
        Control page = _settings.Section switch
        {
            "history" => BuildHistory(),
            "branches" => BuildBranches(),
            "sync" => BuildSync(),
            "mirror" => BuildMirror(),
            "projects" => BuildProjects(),
            "service" => BuildService(),
            _ => BuildChanges(),
        };
        PageHost.Children.Add(page);
        var (_, _, name, _, _) = SectionList.First(s => s.Id == _settings.Section);
        CrumbText.Text = Upper(Lang.T(name)) + (_project is null ? "" : " · " + _project.Name);
        Lang.Walk(PageHost);
        ApplyBusy();
    }

    /// <summary>The page in sight takes the state of the repository as it is now.</summary>
    Task UpdateSection() => _settings.Section switch
    {
        "history" => UpdateHistory(),
        "branches" => UpdateBranches(),
        "sync" => UpdateSync(),
        "mirror" => UpdateMirror(),
        "projects" => UpdateProjects(),
        "service" => UpdateService(),
        _ => UpdateChanges(),
    };
}
