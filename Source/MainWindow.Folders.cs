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
using Avalonia.Media;
using AudionHubManager.Core;
using AudionHubManager.Views;

namespace AudionHubManager;

/// <summary>
/// ПРОЕКТЫ: the folder panel - the folders of this machine in the manner of the file panel of ИЗМЕНЕНИЯ, in place of the
/// system dialog. Each folder says what it is to the registry (the SOURCE, the GIT COPY or the DOCS of a project) and to
/// Git (a repository of its own). The folder chosen in it fills a field of the record, is searched for projects, takes a
/// clone: the row under the cursor, or with ".." under it the folder looked at.
/// </summary>
public partial class MainWindow
{
    sealed class FolderRow
    {
        public string Path = "", Name = "", Layer = "", Project = "";
        public bool Up, Drive, Git;
        public DateTime? Modified;
    }

    /// <summary>The folder the panel looks at, "" - the disks of the machine; null until the page is first built.</summary>
    string? _foldersAt;
    /// <summary>The folder under the cursor, kept so the panel finds it again when it is drawn anew.</summary>
    string _foldersPick = "", _foldersQuick = "";
    /// <summary>The roots of the storage the console command names: where the projects, the GIT COPIES and DOCS lie.</summary>
    List<(string Name, string Path, string Tip)>? _places;
    ListBox? _folderList;
    TextBlock? _folderCrumbs, _folderStatus;
    WrapPanel? _placeRow;

    // The date takes "yesterday 23:10" whole: the English words are the longer ones.
    const string FolderColumns = "24,*,84,112";

    Control BuildFolders()
    {
        _foldersAt ??= StartFolder();
        _placeRow = new WrapPanel();
        ShowPlaces();
        var quick = Field("найти", _foldersQuick, 100, "Сузить список: остаются только папки с этим текстом в имени. Esc - снять.", "folders_quick");
        quick.Height = quick.MinHeight = 24;
        quick.TextChanged += (_, _) => { _foldersQuick = quick.Text ?? ""; ShowFolders(); };
        quick.KeyDown += (_, e) => { if (e.Key == Key.Escape) { quick.Text = ""; _folderList?.Focus(); e.Handled = true; } };
        var up = new Button { Classes = { "tool" }, Content = Sign("corner-left-up"), Margin = new Thickness(4, 0, 0, 0) };
        ToolTip.SetTip(up, Lang.T("Наверх - в папку выше (Backspace)."));
        Avalonia.Automation.AutomationProperties.SetAutomationId(up, "folders_up");
        up.Click += (_, _) => FoldersUp();
        var refresh = new Button { Classes = { "tool" }, Content = Sign("refresh-cw"), Margin = new Thickness(4, 0, 0, 0) };
        ToolTip.SetTip(refresh, Lang.T("Перечитать папку."));
        refresh.Click += (_, _) => ShowFolders();
        var head = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto,Auto,Auto"), Margin = new Thickness(8, 7, 8, 6) };
        head.Children.Add(_placeRow);
        Grid.SetColumn(quick, 1); head.Children.Add(quick);
        Grid.SetColumn(up, 2); head.Children.Add(up);
        Grid.SetColumn(refresh, 3); head.Children.Add(refresh);

        _folderCrumbs = new TextBlock { Classes = { "caption" } };
        var keys = new TextBlock { Classes = { "caption" }, Text = Lang.T("Enter - в папку, Backspace - наверх"), Margin = new Thickness(10, 0, 0, 0) };
        DockPanel.SetDock(keys, Dock.Right);
        var crumbs = new DockPanel { Margin = new Thickness(10, 0, 10, 4), Children = { keys, new FadeBox(_folderCrumbs) } };
        _folderList = Rows("folders");
        _folderList.ItemTemplate = new FuncDataTemplate<FolderRow>((row, _) => row is null ? new Panel() : FolderView(row), supportsRecycling: false);
        _folderList.SelectionChanged += (_, _) =>
        {
            if (_folderList.SelectedItem is FolderRow row) _foldersPick = row.Up ? "" : row.Path;
            ShowFolderStatus();
        };
        _folderList.DoubleTapped += (_, _) => FoldersOpen();
        _folderList.KeyDown += (_, e) =>
        {
            if (e.Key == Key.Enter) { FoldersOpen(); e.Handled = true; }
            else if (e.Key == Key.Back) { FoldersUp(); e.Handled = true; }
        };
        _folderStatus = new TextBlock { Classes = { "status" } };

        var body = new DockPanel();
        var heads = Heads(FolderColumns, "", "ПАПКА", "ЧТО", "ДАТА");
        foreach (var top in new Control[] { head, new Border { Classes = { "hsep" }, Padding = new Thickness(0) }, crumbs, heads })
        {
            DockPanel.SetDock(top, Dock.Top);
            body.Children.Add(top);
        }
        var status = new FadeBox(_folderStatus) { Margin = new Thickness(10, 5, 10, 6) };
        DockPanel.SetDock(status, Dock.Bottom);
        body.Children.Add(status);
        body.Children.Add(_folderList);
        ShowFolders();
        if (_places is null) _ = LoadPlaces();
        return new Border { Classes = { "pane" }, Child = body };
    }

    /// <summary>Where the panel opens: the folder the SOURCE of the active project lies in, with that SOURCE under the cursor.</summary>
    string StartFolder()
    {
        if (_project?.Source is { Length: > 0 } source)
            try
            {
                var folder = new DirectoryInfo(source);
                if (folder.Exists && folder.Parent is { } parent)
                {
                    _foldersPick = folder.FullName;
                    return parent.FullName;
                }
            }
            catch { }
        return "";
    }

    async Task LoadPlaces()
    {
        var answer = await Hub.Ask("storage");
        var places = new List<(string, string, string)>();
        if (answer.Json?["result"]?["roots"]?["full_projects_root"] is JsonObject projectsRoot)
        {
            _rootPath = projectsRoot["path"]?.ToString() ?? "";
            _rootShipped = projectsRoot["shipped"]?.ToString() ?? "";
            _rootChosenHere = projectsRoot["chosen_here"]?.GetValue<bool>() == true;
            ShowRootTip();
        }
        if (answer.Json?["result"]?["roots"] is JsonObject roots)
            foreach (var (key, tip) in new[]
            {
                ("full_projects_root", "Где лежат живые проекты - их ИСХОДНИКИ."),
                ("hub_data_root", "GIT-КОПИИ проектов: чистые зеркала для истории и сервера."),
                ("docs_root", "Слой DOCS: документы проектов для чтения."),
            })
                if (roots[key] is JsonObject root && root["exists"]?.GetValue<bool>() == true && root["path"]?.ToString() is { Length: > 0 } path)
                    places.Add((System.IO.Path.GetFileName(path.TrimEnd('\\')) is { Length: > 0 } name ? name : path, path, tip));
        _places = places;
        ShowPlaces();
    }

    /// <summary>The row of places over the panel: the disks, then the roots of the storage; the one looked at lit.</summary>
    void ShowPlaces()
    {
        if (_placeRow is null) return;
        _placeRow.Children.Clear();
        void Place(string name, string path, string tip)
        {
            var chip = Chip(name, Same(_foldersAt ?? "", path), () => FoldersGo(path, ""));
            chip.Margin = new Thickness(0, 0, 4, 2);
            ToolTip.SetTip(chip, Lang.T(tip) + (path.Length > 0 ? "\n" + path : ""));
            _placeRow.Children.Add(chip);
        }
        Place("ДИСКИ", "", "Диски этой машины.");
        foreach (var (name, path, tip) in _places ?? new()) Place(name, path, tip);
    }

    /// <summary>The rows of the folder looked at: "..", then its folders by name; at the top, the disks.</summary>
    void ShowFolders()
    {
        if (_folderList is null) return;
        var at = _foldersAt ?? "";
        var rows = new List<FolderRow>();
        var trouble = "";
        if (at.Length == 0)
            foreach (var drive in DriveInfo.GetDrives())
            {
                var row = new FolderRow { Path = drive.RootDirectory.FullName, Name = drive.Name.TrimEnd('\\'), Drive = true };
                try
                {
                    if (drive.IsReady)
                    {
                        row.Modified = drive.RootDirectory.LastWriteTime;
                        if (drive.VolumeLabel.Length > 0) row.Name += "  " + drive.VolumeLabel;
                    }
                }
                catch { }
                rows.Add(row);
            }
        else
        {
            rows.Add(new FolderRow { Name = "..", Up = true });
            try
            {
                // Hidden and system folders stay out, as in Explorer: the recycle bin, System Volume Information. .git is
                // the inside of a repository, never a folder of a project - the file panel of ИЗМЕНЕНИЯ leaves it out too.
                var options = new EnumerationOptions { IgnoreInaccessible = true };
                foreach (var dir in new DirectoryInfo(at).EnumerateDirectories("*", options).OrderBy(d => d.Name, StringComparer.OrdinalIgnoreCase))
                {
                    if (dir.Name == ".git") continue;
                    if (_foldersQuick.Length > 0 && !dir.Name.Contains(_foldersQuick, StringComparison.OrdinalIgnoreCase)) continue;
                    var row = new FolderRow { Path = dir.FullName, Name = dir.Name };
                    try { row.Modified = dir.LastWriteTime; } catch { }
                    Known(row);
                    rows.Add(row);
                }
            }
            catch (Exception ex) { trouble = ex.Message; }
        }
        var pick = _foldersPick;
        _folderList.ItemsSource = rows;
        _folderList.SelectedItem = rows.FirstOrDefault(r => !r.Up && Same(r.Path, pick)) ?? rows.FirstOrDefault();
        _folderCrumbs!.Text = at.Length == 0 ? Lang.T("Диски этой машины") : at;
        ShowFolderStatus(trouble);
    }

    /// <summary>What a folder is to the registry - a layer of a project - or to Git: a repository of its own.</summary>
    void Known(FolderRow row)
    {
        foreach (var p in _projects)
            foreach (var layer in new[] { "source", "mirror", "docs" })
                if (p.Folder(layer) is { Length: > 0 } folder && Same(folder, row.Path))
                {
                    row.Layer = layer;
                    row.Project = p.Name;
                    return;
                }
        row.Git = Directory.Exists(System.IO.Path.Combine(row.Path, ".git")) || File.Exists(System.IO.Path.Combine(row.Path, ".git"));
    }

    static bool Same(string a, string b) => string.Equals(a.TrimEnd('\\', '/'), b.TrimEnd('\\', '/'), StringComparison.OrdinalIgnoreCase);

    static string LayerIcon(string layer) => layer switch { "mirror" => "folder-git", "docs" => "book-open-text", _ => "folder-code" };

    Control FolderView(FolderRow row)
    {
        var (icon, ink) = row.Up ? ("corner-left-up", "CrumbInk") : row.Drive ? ("hard-drive", "CrumbInk")
            : row.Layer.Length > 0 ? (LayerIcon(row.Layer), "Quasar") : row.Git ? ("folder-git-2", "GitModified") : ("folder", "CrumbInk");
        var name = Cell(row.Name, bold: row.Layer.Length > 0 || row.Drive);
        Control? what = row.Layer.Length > 0 ? Pill(LayerName(row.Layer), "ok") : row.Git ? Pill("git", "info") : null;
        var grid = Cells(FolderColumns, Sign(icon, ink), name, what, Cell(row.Modified is { } m ? When(m) : "", quiet: true));
        grid.MinHeight = 25;
        if (!row.Up)
            ToolTip.SetTip(grid, row.Path
                + (row.Layer.Length > 0 ? "\n" + Lang.F("Проект реестра: {0}", row.Project) + " · " + Lang.T(LayerName(row.Layer))
                : row.Git ? "\n" + Lang.T("Свой репозиторий Git; в реестре его нет - «найти в папке» внесёт его.") : ""));
        return grid;
    }

    void ShowFolderStatus(string trouble = "")
    {
        if (_folderStatus is null) return;
        if (trouble.Length > 0) { _folderStatus.Text = Lang.F("Папка не читается: {0}", trouble); return; }
        var count = (_folderList?.ItemsSource as List<FolderRow>)?.Count(r => !r.Up) ?? 0;
        _folderStatus.Text = ((_foldersAt ?? "").Length == 0 ? Lang.F("дисков: {0}", count) : Lang.F("папок: {0}", count))
            + (PickedFolder() is { } picked ? " · " + Lang.F("выбрана: {0}", picked) : "");
        ToolTip.SetTip(_folderStatus, _folderStatus.Text);
    }

    /// <summary>The folder chosen in the panel: the row under the cursor, or with ".." under it the folder looked at.</summary>
    string? PickedFolder() =>
        _folderList?.SelectedItem is FolderRow { Up: false } row ? row.Path : _foldersAt is { Length: > 0 } at ? at : null;

    void FoldersGo(string folder, string pick)
    {
        _foldersAt = folder;
        _foldersPick = pick;
        ShowPlaces();
        ShowFolders();
        _folderList?.Focus();
    }

    void FoldersOpen()
    {
        if (_folderList?.SelectedItem is not FolderRow row) return;
        if (row.Up) FoldersUp();
        else FoldersGo(row.Path, "");
    }

    /// <summary>One folder up, with the folder left under the cursor; above the root of a disk - the disks.</summary>
    void FoldersUp()
    {
        if (_foldersAt is not { Length: > 0 } at) return;
        string parent = "";
        try { parent = new DirectoryInfo(at).Parent?.FullName ?? ""; } catch { }
        FoldersGo(parent, at);
    }
}
