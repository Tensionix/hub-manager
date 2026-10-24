using System;
using System.Diagnostics;
using System.IO;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using AudionHubManager.Core;

namespace AudionHubManager;

/// <summary>
/// SETTINGS and ABOUT: sheets in place of the page and the terminal, the state row stays in sight. SETTINGS - the
/// sizes of the texts, the question before what cannot be undone, where the window keeps its files. ABOUT - what the
/// program is, its version, its folders and its licence.
/// </summary>
public partial class MainWindow
{
    string _sheet = "";

    void ToggleSheet(string sheet)
    {
        _sheet = _sheet == sheet ? "" : sheet;
        SheetHost.IsVisible = _sheet.Length > 0;
        Zones.IsVisible = _sheet.Length == 0;
        SheetSettings.IsChecked = _sheet == "settings";
        SheetAbout.IsChecked = _sheet == "about";
        TitleButton.Classes.Set("on", _sheet == "about");
        FillSheet();
    }

    void FillSheet()
    {
        SheetBody.Children.Clear();
        if (_sheet == "settings") FillSettings();
        else if (_sheet == "about") FillAbout();
        Lang.Walk(SheetBody);
    }

    void FillSettings()
    {
        SheetBody.Children.Add(new TextBlock { Classes = { "pagetitle" }, Text = "SETTINGS", Margin = new Thickness(0, 0, 0, 10) });
        var sizes = new StackPanel { Spacing = 8 };
        var shift = new StackPanel { Orientation = Orientation.Horizontal };
        foreach (var (value, word) in new[] { (-1.0, "мельче"), (0.0, "как обычно"), (1.0, "крупнее"), (2.0, "ещё крупнее") })
            shift.Children.Add(Chip(word, Math.Abs(_settings.UiShift - value) < 0.01, () => { _settings.UiShift = value; _settings.Save(); App.SetSizes(_settings.UiShift, _settings.LogSize); FillSheet(); }));
        var log = new StackPanel { Orientation = Orientation.Horizontal };
        foreach (var value in new[] { 9.5, 10.5, 11.5, 12.5 })
            log.Children.Add(Chip(value.ToString("0.#", Lang.Culture),Math.Abs(_settings.LogSize - value) < 0.01, () => { _settings.LogSize = value; _settings.Save(); App.SetSizes(_settings.UiShift, _settings.LogSize); FillSheet(); }));
        sizes.Children.Add(Pair("текст окна", shift));
        sizes.Children.Add(Pair("текст терминала", log));
        SheetBody.Children.Add(Block("РАЗМЕРЫ", "Quasar", sizes));

        var safety = new StackPanel { Spacing = 6 };
        var typed = new CheckBox { Classes = { "tick" }, Content = Lang.T("reset --hard подтверждать вводом слова RESET"), IsChecked = _settings.TypedConfirm };
        typed.IsCheckedChanged += (_, _) => { _settings.TypedConfirm = typed.IsChecked == true; _settings.Save(); };
        var explain = new CheckBox { Classes = { "tick" }, Content = Lang.T("под каждой командой - что она сделала и как её отменить (ОБЪЯСНЯТЬ)"), IsChecked = _settings.Explain };
        explain.IsCheckedChanged += (_, _) => { _settings.Explain = explain.IsChecked == true; ExplainButton.IsChecked = _settings.Explain; _settings.Save(); };
        safety.Children.Add(typed);
        safety.Children.Add(explain);
        safety.Children.Add(Text("Опасные команды - вернуть файл, сбросить ветку, переписать последний коммит - окно всегда спрашивает: с командой целиком, тем, что сейчас не закоммичено, и способом отмены.", "note"));
        SheetBody.Children.Add(Block("ОСТОРОЖНОСТЬ И ОБУЧЕНИЕ", "BurnInk", safety));

        var files = new StackPanel { Spacing = 4 };
        files.Children.Add(Pair("настройки окна", Text(Settings.FilePath, "caption")));
        files.Children.Add(Pair("реестр проектов", Text(_registryFile.Length > 0 ? _registryFile : "-", "caption")));
        files.Children.Add(Pair("профили зеркала", Text(Path.Combine(Paths.Config, "projection_profiles.json"), "caption")));
        files.Children.Add(Pair("журнал окна и отчёты", Text(Paths.ProgramLogs, "caption")));
        files.Children.Add(Pair("консольная команда", Text(Paths.Door, "caption")));
        SheetBody.Children.Add(Block("ФАЙЛЫ", "CrumbInk", files));
    }

    static Grid Pair(string name, Control value)
    {
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("200,*"), MinHeight = 26 };
        grid.Children.Add(Text(name, "fieldname"));
        Grid.SetColumn(value, 1);
        grid.Children.Add(value);
        return grid;
    }

    void OpenUrl(string url)
    {
        try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); }
        catch (Exception ex) { SetStatus(Lang.F("Ссылка не открылась: {0}", ex.Message)); }
    }

    void FillAbout()
    {
        var dark = _settings.Look != "light";
        try
        {
            // The approved logo of Audion Design (brands\audion\exports): "dark" is the one for a dark background.
            var logo = new Image
            {
                Source = new Bitmap(Avalonia.Platform.AssetLoader.Open(new Uri($"avares://AudionHubManager/Assets/brand/logo-{(dark ? "dark" : "light")}-1600.png"))),
                Height = 64, HorizontalAlignment = HorizontalAlignment.Left, Margin = new Thickness(0, 4, 0, 14),
            };
            SheetBody.Children.Add(logo);
        }
        catch { }
        SheetBody.Children.Add(new TextBlock { Classes = { "pagetitle" }, Text = "AUDION HUB MANAGER " + (Paths.Version is { } v ? "v" + v : "") });
        // The sites of the program, each with its sign: the marks of Audion and Tensionix from Audion Design
        // (brands\*\exports\mark-1024.png, made 64 px), the mark of GitHub from Simple Icons.
        var sites = new WrapPanel { Margin = new Thickness(0, 2, 0, 6) };
        void Site(string caption, string url, string tip, Control sign)
        {
            var button = new Button { Classes = { "small" }, Margin = new Thickness(0, 0, 6, 6), Content = new StackPanel
            {
                Orientation = Orientation.Horizontal, Spacing = 7, Children = { sign, new TextBlock { Text = caption, VerticalAlignment = VerticalAlignment.Center } },
            } };
            ToolTip.SetTip(button, Lang.T(tip) + "\n" + url);
            Avalonia.Automation.AutomationProperties.SetAutomationId(button, "site_" + caption.ToLowerInvariant());
            button.Click += (_, _) => OpenUrl(url);
            sites.Children.Add(button);
        }
        Control Brand(string file)
        {
            var image = new Image { Width = 14, Height = 14, VerticalAlignment = VerticalAlignment.Center };
            try { image.Source = new Bitmap(Avalonia.Platform.AssetLoader.Open(new Uri($"avares://AudionHubManager/Assets/brand/{file}"))); } catch { }
            RenderOptions.SetBitmapInterpolationMode(image, BitmapInterpolationMode.HighQuality);
            return image;
        }
        Site("TENSIONIX.COM", "https://tensionix.com/", "Сайт Tensionix - автора программы.", Brand("tensionix-mark-64.png"));
        Site("AUDION.DEV", "https://audion.dev/downloads/hub-manager", "Страница программы на сайте Audion: все версии и загрузки.", Brand("audion-mark-64.png"));
        Site("GITHUB", "https://github.com/Tensionix/hub-manager", "Репозиторий программы на GitHub: исходные тексты, релизы, обращения.", (Control?)Icons.Mark("github", 14) ?? Sign("folder-git"));
        Site("TENSIONIX.GITHUB.IO", "https://tensionix.github.io/projects/hub-manager/", "Страница программы на сайте Tensionix.", Brand("tensionix-mark-64.png"));
        SheetBody.Children.Add(sites);
        SheetBody.Children.Add(Text("Проект → чистая GIT-КОПИЯ → Git и сервер. Окно запускает настоящий git и показывает каждую команду целиком, с объяснением простыми словами: пользоваться и учиться одновременно. Свою работу - реестр, зеркало, проверки, Forgejo, учебную лабораторию - окно делает через консольную команду hub_cli.cmd: то же самое можно сделать без окна.", "note"));
        var facts = new StackPanel { Spacing = 4, Margin = new Thickness(0, 12, 0, 0) };
        facts.Children.Add(Pair("папка программы", Text(Paths.Root, "caption")));
        facts.Children.Add(Pair("консольная команда", Text(Paths.Door + "  (hub_cli.cmd --help)", "caption")));
        facts.Children.Add(Pair("канон Git", Text(Lang.F("{0} операций - system_core\\core\\git_canon.py", Canon.All.Count), "caption")));
        facts.Children.Add(Pair("учебная лаборатория", Text(Path.Combine(Paths.Root, "examples", "lab"), "caption")));
        facts.Children.Add(Pair("лицензия", Text("Apache-2.0 · LICENSE, licenses\\", "caption")));
        facts.Children.Add(Pair("значки", Text("Lucide (ISC), Simple Icons (CC0), JetBrains Mono (SIL OFL)", "caption")));
        SheetBody.Children.Add(facts);
    }
}
