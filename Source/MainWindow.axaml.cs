using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Documents;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using AudionHubManager.Core;
using AudionHubManager.Views;

namespace AudionHubManager;

/// <summary>
/// The window of Audion Hub Manager. Git it runs itself, and every command a button runs is shown whole in the
/// terminal with a line of plain words under it - the program is a way to learn Git as much as to use it. Hub
/// Manager's own work (the registry, the mirror, the checks, Forgejo, the lab) goes through the console command,
/// hub_cli.cmd. The operations of Git and their words are the canon of the engine (Core\Canon.cs).
/// </summary>
public partial class MainWindow : Window
{
    readonly Settings _settings;
    readonly Runner _runner = new();

    public MainWindow()
    {
        // The theme is the application's: set before the markup is read, so the window comes up in it.
        _settings = Settings.Load();
        Lang.Set(_settings.LanguageInUse);
        if (Application.Current is { } app) app.RequestedThemeVariant = App.Variant(_settings.Look);
        InitializeComponent();
        if (_settings.Width >= MinWidth && _settings.Height >= MinHeight)
        {
            Width = _settings.Width;
            Height = _settings.Height;
        }
        // The terminal was 470 wide before the column of projects came; a width saved at that default was nobody's
        // choice, and it takes the new one (400) - a width dragged by hand stays.
        if (_settings.JournalWidth == 470) _settings.JournalWidth = 400;
        if (_settings.JournalWidth >= RightZone.MinWidth)
            Zones.ColumnDefinitions[2].Width = new GridLength(Math.Min(_settings.JournalWidth, Math.Max(RightZone.MinWidth, Width - LeftZone.MinWidth - 60)));
        Classes.Set("vault", _settings.Look == "vault");
        App.SetFonts(_settings.UiFont, _settings.LogFont);
        App.SetSizes(_settings.UiShift, _settings.LogSize);
        // Words and signs on whole pixels of this screen, whatever its scale.
        PixelGrid.Apply(RenderScaling);
        ScalingChanged += (_, _) => PixelGrid.Apply(RenderScaling);

        var version = Paths.Version;
        Title = version is null ? "Audion Hub Manager" : "Audion Hub Manager v" + version;
        VersionText.Text = (version is null ? "version unknown" : "v" + version) + " • " + DateTime.Now.Year;

        _runner.Output += OnOutput;
        _runner.Finished += OnFinished;
        Guard.Told = message =>
        {
            AppendLines(new[] { "[GUI ERROR] " + message });
            SetStatus("Ошибка окна записана в logs.");
        };

        Wire();
        WireProject();
        WireSide();
        WireCommand();
        BuildLegend();
        // A pass of a check (-Shot) and a walk of the built window (AUDION_WALK=1) are not for a person: the window
        // stands off every screen, takes no focus and has no button on the taskbar.
        bool offScreen = Program.Walk || (Program.ShotFolder.Length > 0 && Environment.GetEnvironmentVariable("AUDION_SHOT_ON_SCREEN") != "1");
        if (offScreen)
        {
            ShowInTaskbar = false;
            ShowActivated = false;
            WindowStartupLocation = WindowStartupLocation.Manual;
            Position = OffScreen;
        }
        MarkTheme();
        MarkLanguage();
        ExplainButton.IsChecked = _settings.Explain;
        // What the markup holds is written in Russian: walked once, into the language in use.
        Lang.Walk(this);
        Closing += OnClosing;
        // Back from VS Code or Explorer: the state of the repository may have changed under the window.
        Activated += (_, _) => RefreshSoon();
        Opened += async (_, _) =>
        {
            // A place set before the window is shown is not kept: set again once it is open.
            if (offScreen) Position = OffScreen;
            await StartUp();
            if (Program.ShotFolder.Length > 0) await TakeShots(Program.ShotFolder);
        };
    }

    /// <summary>Where a window of a check stands: off every screen. Not -32000 - Windows reads that as "minimised".</summary>
    static readonly PixelPoint OffScreen = new(-30000, -30000);

    // ------------------------------------------------------------ the look

    void Wire()
    {
        LangRu.Click += (_, _) => SetLanguage("ru");
        LangEn.Click += (_, _) => SetLanguage("en");
        ThemeVault.Click += (_, _) => SetTheme("vault");
        ThemeDark.Click += (_, _) => SetTheme("dark");
        ThemeCode.Click += (_, _) => SetTheme("codedark");
        ThemeLight.Click += (_, _) => SetTheme("light");
        ExplainButton.Click += (_, _) =>
        {
            _settings.Explain = ExplainButton.IsChecked == true;
            _settings.Save();
            SetStatus(_settings.Explain ? "Под каждой командой - что она сделала и как её отменить." : "Пояснения под командами выключены.");
        };
        StopButton.Click += (_, _) => StopRun();
        CopyLogButton.Click += (_, _) => CopyLog();
        ClearLogButton.Click += (_, _) => ClearLog();
        WideLogButton.Click += (_, _) => ToggleWide();
        LogsButton.Click += (_, _) => OpenFolder(Paths.ProgramLogs);
        _clock.Tick += (_, _) => ShowClock();
        TitleButton.Click += (_, _) => ToggleSheet("about");
        SheetSettings.Click += (_, _) => ToggleSheet("settings");
        SheetAbout.Click += (_, _) => ToggleSheet("about");
        SheetClose.Click += (_, _) => ToggleSheet(_sheet);
        KeyDown += OnKey;
    }

    void MarkLanguage()
    {
        LangRu.IsChecked = Lang.Code == "ru";
        LangEn.IsChecked = Lang.Code != "ru";
    }

    void SetLanguage(string code)
    {
        if (Lang.Code != code)
        {
            Lang.Set(code);
            _settings.Lang = code;
            _settings.Save();
            // What code wrote is written again in the new language; what the markup holds is walked.
            BuildSections();
            BuildLegend();
            ShowTools();
            ShowProject();
            ShowSection();
            Lang.Walk(this);
            FillSheet();
        }
        MarkLanguage();
    }

    void SetTheme(string look)
    {
        _settings.Look = look;
        _settings.Save();
        if (Application.Current is { } app) app.RequestedThemeVariant = App.Variant(look);
        Classes.Set("vault", look == "vault");
        MarkTheme();
        // The lines of the terminal and the pages built in code took their brushes from the old theme.
        Dispatcher.UIThread.Post(() => { Recolour(); ShowTools(); ShowSection(); }, DispatcherPriority.Background);
        FillSheet();
    }

    void MarkTheme()
    {
        ThemeVault.IsChecked = _settings.Look == "vault";
        ThemeDark.IsChecked = _settings.Look == "dark";
        ThemeCode.IsChecked = _settings.Look == "codedark";
        ThemeLight.IsChecked = _settings.Look == "light";
        ThemeButton.IsChecked = false;
    }

    static string Upper(string text) => text.ToUpper(CultureInfo.CurrentCulture);

    /// <summary>The status line: written in Russian by whoever speaks, shown in the language of the window.</summary>
    void SetStatus(string text) => StatusText.Text = Lang.T(text);

    /// <summary>The legend of the dots of risk over the terminal: what a dot on a button means.</summary>
    void BuildLegend()
    {
        RiskLegend.Children.Clear();
        foreach (var (risk, word) in new[] { ("read", "читает"), ("local", "меняет"), ("net", "сеть"), ("danger", "опасно") })
        {
            var dot = new Avalonia.Controls.Shapes.Ellipse { Classes = { "risk" } }.Ink(Avalonia.Controls.Shapes.Shape.FillProperty, Canon.RiskInk(risk));
            var text = new TextBlock { Classes = { "arrowword" }, Text = Lang.T(word) };
            var item = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 5, Children = { dot, text } };
            ToolTip.SetTip(item, Lang.T(Canon.RiskWords(risk)));
            RiskLegend.Children.Add(item);
        }
    }

    void OpenFolder(string folder)
    {
        try
        {
            Directory.CreateDirectory(folder);
            Process.Start(new ProcessStartInfo("explorer.exe") { ArgumentList = { folder }, UseShellExecute = false });
        }
        catch (Exception ex) { SetStatus(Lang.F("Папка не открылась: {0}", ex.Message)); }
    }

    // ------------------------------------------------------------ the terminal

    /// <summary>The text of the terminal since it was last cleared: the copy button gives all of it, up to a limit.</summary>
    readonly StringBuilder _logAll = new();
    const int LogAllLimit = 16_000_000;

    /// <summary>
    /// The panel keeps the last lines of a run and not all of them. It is pages of text one under
    /// another: a text is laid out whole at every line added to it, so new lines go into the last
    /// page while it has room, a full page is never touched again, and the oldest pages leave whole.
    /// </summary>
    const int LogLimit = 5000;
    const int PageLines = 100;
    readonly List<int> _pageLines = new();
    readonly List<int> _pageRuns = new();
    readonly List<(Run Run, Hue Hue)> _logRuns = new();
    int _logShown;
    bool _scrollPosted;
    /// <summary>The colours of the command that runs: what a line opened is in force on the next.</summary>
    readonly Ansi _ansi = new();

    /// <summary>
    /// Lines into the terminal. A line a command told is written in the colours its writer gave it and in no other
    /// (Core\Ansi.cs) - git's own colours; a line of the window itself - what was run, the words under it, how it
    /// ended - in the tone of what it says (Core\LogTones.cs).
    /// </summary>
    void AppendLines(IReadOnlyList<string> lines, bool told = false)
    {
        if (lines.Count == 0) return;
        // The panel follows the new lines while its reader is at the end, and stays where it is
        // when he has gone up to read: asked before the lines are added.
        bool follow = _scrollPosted || LogScroll.Offset.Y + LogScroll.Viewport.Height >= LogScroll.Extent.Height - 40;

        var read = new List<(string Text, Hue Hue)>[lines.Count];
        for (int i = 0; i < lines.Count; i++)
        {
            string plain = lines[i];
            if (told) read[i] = _ansi.Read(lines[i], out plain);
            else
            {
                read[i] = new List<(string, Hue)>();
                var tone = LogTones.Of(plain);
                // The bounds of a run and the command itself stand out in bold.
                bool bold = plain.StartsWith("===== ", StringComparison.Ordinal) || tone == LogTone.Command;
                if (plain.Length > 0) read[i].Add((plain, new Hue(LogTones.Key(tone), null, bold, false)));
            }
            _logAll.Append(plain).Append("\r\n");
        }
        // What the window says itself goes to the file of the day too, with its time.
        if (!told) KeepLines(lines);
        if (_logAll.Length > LogAllLimit)
        {
            int cut = LogAllLimit / 4;
            while (cut < _logAll.Length && _logAll[cut - 1] != '\n') cut++;
            _logAll.Remove(0, cut);
        }

        int at = Math.Max(0, lines.Count - LogLimit);
        _logShown += lines.Count - at;
        var pages = LogPages.Children;
        while (at < lines.Count)
        {
            if (_pageLines.Count == 0 || _pageLines[^1] >= PageLines)
            {
                pages.Add(new Controls.LogPage { TextWrapping = TextWrapping.Wrap });
                _pageLines.Add(0);
                _pageRuns.Add(0);
            }
            int held = _pageLines[^1], take = Math.Min(PageLines - held, lines.Count - at);
            // Pieces that stand together and are written the same way are one run.
            var added = new List<Inline>();
            var piece = new StringBuilder();
            var kind = new Hue("LogPlain", null, false, false);
            void Close()
            {
                if (piece.Length == 0) return;
                var run = new Run(piece.ToString()) { Foreground = Ansi.Brush(kind) };
                if (kind.Bold) run.FontWeight = FontWeight.Bold;
                if (kind.Underline) run.TextDecorations = TextDecorations.Underline;
                added.Add(run);
                _logRuns.Add((run, kind));
                piece.Clear();
            }
            for (int i = 0; i < take; i++)
            {
                if (held + i > 0) piece.Append('\n');
                foreach (var (text, hue) in read[at + i])
                {
                    if (hue != kind) Close();
                    kind = hue;
                    piece.Append(text);
                }
            }
            Close();
            var page = (Controls.LogPage)pages[^1];
            (page.Inlines ??= new InlineCollection()).AddRange(added);
            _pageLines[^1] = held + take;
            _pageRuns[^1] += added.Count;
            at += take;
        }

        int gone = 0, lost = 0;
        while (gone < _pageLines.Count - 1 && _logShown - _pageLines[gone] >= LogLimit)
        {
            _logShown -= _pageLines[gone];
            lost += _pageRuns[gone++];
        }
        if (gone > 0)
        {
            pages.RemoveRange(0, gone);
            _pageLines.RemoveRange(0, gone);
            _pageRuns.RemoveRange(0, gone);
            _logRuns.RemoveRange(0, lost);
        }

        if (!follow || _scrollPosted) return;
        _scrollPosted = true;
        Dispatcher.UIThread.Post(() =>
        {
            _scrollPosted = false;
            LogScroll.ScrollToEnd();
        }, DispatcherPriority.Background);
    }

    /// <summary>The file of the day of the window: logs\gui-DATE.log.</summary>
    static string DayLog => Path.Combine(Paths.Logs, $"gui-{DateTime.Now:yyyyMMdd}.log");

    static void KeepLines(IReadOnlyList<string> lines)
    {
        var stamp = DateTime.Now.ToString("HH:mm:ss");
        var text = new StringBuilder();
        foreach (var line in lines.SelectMany(line => line.Split('\n')).Select(line => line.TrimEnd('\r')))
            if (line.Length > 0) text.Append(stamp).Append("  ").Append(line).Append("\r\n");
        if (text.Length == 0) return;
        try
        {
            Directory.CreateDirectory(Paths.Logs);
            File.AppendAllText(DayLog, text.ToString(), new UTF8Encoding(false));
        }
        catch { }
    }

    void ClearLog()
    {
        LogPages.Children.Clear();
        _pageLines.Clear();
        _pageRuns.Clear();
        _logRuns.Clear();
        _logAll.Clear();
        _logShown = 0;
        if (!_runner.Running) _ansi.Reset();
    }

    /// <summary>After a change of the theme the lines already written keep their meaning and take the new colours.</summary>
    void Recolour()
    {
        foreach (var (run, hue) in _logRuns)
            if (hue.Own is null) run.Foreground = App.Ink(hue.Key);
    }

    async void CopyLog()
    {
        if (_logAll.Length == 0 || Clipboard is not { } clipboard) return;
        try
        {
            await Avalonia.Input.Platform.ClipboardExtensions.SetTextAsync(clipboard, _logAll.ToString());
            Toast.Show(this, Lang.T("Терминал скопирован."));
        }
        catch (Exception ex) { SetStatus(Lang.F("Буфер обмена не принял текст: {0}", ex.Message)); }
    }

    bool _wide;
    double _journalWidth = 470;

    /// <summary>The terminal over the whole window - the page steps aside - and back to the width it had.</summary>
    void ToggleWide()
    {
        if (!_wide) _journalWidth = RightZone.Bounds.Width;
        _wide = !_wide;
        LeftZone.IsVisible = !_wide;
        Zones.ColumnDefinitions[0].Width = _wide ? new GridLength(0) : GridLength.Star;
        Zones.ColumnDefinitions[2].Width = _wide ? GridLength.Star : new GridLength(_journalWidth);
        if (WideLogButton.Content is Avalonia.Controls.Shapes.Path sign) sign.Data = Icons.Glyph(_wide ? "minimize-2" : "maximize-2");
    }

    // ------------------------------------------------------------ the end of the window

    void SaveWindow()
    {
        if (WindowState == WindowState.Normal)
        {
            _settings.Width = Width;
            _settings.Height = Height;
        }
        _settings.JournalWidth = Math.Round(_wide ? _journalWidth : RightZone.Bounds.Width);
        _settings.Save();
    }
}
