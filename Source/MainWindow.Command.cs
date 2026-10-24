using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Layout;
using AudionHubManager.Core;
using AudionHubManager.Views;

namespace AudionHubManager;

/// <summary>
/// The command line under the terminal: a command of git - with or without the word git - the PowerShell of the
/// program (App\AudionPs.exe) or CMD, run in the root of the repository of the layer. Its lines come into the terminal
/// in their colours, its run is a run like any other - STOP ends it. A command of the canon that a page cannot finish
/// by itself comes here with its places marked. A command that can lose work is asked about first, whoever typed it.
/// The history and the pinned commands are kept in config\terminal_commands.json (the shape of Audion Media Tools).
/// </summary>
public partial class MainWindow
{
    CommandHistory _commands = null!;
    readonly Queue<(string Shell, string Command, string Folder)> _queued = new();
    int _recall = -1;
    string _typed = "";

    const string PsStart = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n$OutputEncoding = [System.Text.Encoding]::UTF8\n"
                           + "try { $PSStyle.OutputRendering = 'ANSI' } catch {}\n";

    void WireCommand()
    {
        var file = Paths.Released ? Path.Combine(Paths.Config, "terminal_commands.json") : Path.Combine(Paths.Runtime, "terminal_commands.json");
        _commands = new CommandHistory(file);
        if (_commands.Shell is not ("git" or "pwsh" or "cmd")) _commands.Shell = "git";
        CommandBox.Text = _commands.Last;
        PixelGrid.Field(CommandBox);
        MarkShell();
        ShellGit.Click += (_, _) => SetShell("git");
        ShellPs.Click += (_, _) => SetShell("pwsh");
        ShellCmd.Click += (_, _) => SetShell("cmd");
        CommandRunButton.Click += (_, _) => SendCommand();
        CommandBox.KeyDown += (_, e) =>
        {
            if (e.Key == Key.Enter) { SendCommand(); e.Handled = true; }
            else if (e.Key == Key.Up) { Recall(1); e.Handled = true; }
            else if (e.Key == Key.Down) { Recall(-1); e.Handled = true; }
            else if (e.Key == Key.Escape) { TemplateNote.IsVisible = false; }
        };
        WireCommandHistory();
    }

    void SetShell(string shell)
    {
        _commands.Shell = shell;
        _commands.Save();
        MarkShell();
    }

    void MarkShell()
    {
        ShellGit.IsChecked = _commands.Shell == "git";
        ShellPs.IsChecked = _commands.Shell == "pwsh";
        ShellCmd.IsChecked = _commands.Shell == "cmd";
        CommandBox.PlaceholderText = Lang.T(_commands.Shell switch
        {
            "cmd" => "команда CMD",
            "pwsh" => "команда PowerShell",
            _ => "команда git: log --oneline, switch -c имя …",
        });
    }

    void Put(string command)
    {
        CommandBox.Text = command;
        CommandBox.CaretIndex = command.Length;
        CommandBox.Focus();
    }

    void Recall(int step)
    {
        var known = _commands.History;
        if (known.Count == 0) return;
        if (_recall < 0) _typed = CommandBox.Text ?? "";
        _recall = Math.Clamp(_recall + step, -1, known.Count - 1);
        Put(_recall < 0 ? _typed : known[_recall]);
    }

    /// <summary>
    /// A command of the canon the page cannot finish - an interactive rebase, a range - goes into the line with its
    /// places marked ‹так›, and the note over the line says what to put there.
    /// </summary>
    void PutTemplate(CanonEntry entry, List<string> argv)
    {
        SetShell("git");
        var text = Canon.Show(argv);
        Put(text.StartsWith("git ", StringComparison.Ordinal) ? text : text);
        TemplateText.Text = Lang.F("Шаблон: {0}", entry.What) + (entry.Places.Count > 0 ? " " + Lang.F("Проверьте и поправьте: {0}. Enter - выполнить.", string.Join(", ", entry.Places)) : "");
        TemplateNote.IsVisible = true;
    }

    /// <summary>The words of a shell that lose files, whoever typed them: the line asks before it runs them.</summary>
    static readonly Regex Dangerous = new(@"\b(rm\s+-r|rmdir\s+/s|del\s+/s|Remove-Item\b.*-Recurse)",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    async void SendCommand()
    {
        var text = (CommandBox.Text ?? "").Trim();
        if (text.Length == 0) { SetStatus("Введите команду."); return; }
        if (_commands.Shell == "pwsh" && Paths.Ps.Length == 0)
        {
            AppendLines(new[] { "[GUI] " + Lang.T("нет PowerShell программы: App\\AudionPs.exe не собран (install\\Build-App.cmd)") });
            return;
        }
        var folder = ActiveRoot(true) ?? (Directory.Exists(LayerFolder()) ? LayerFolder() : Paths.Root);
        // A typed git command asks what its button would ask: the policy of the canon, not a pattern of words.
        bool asked = false;
        foreach (var argv in TypedCommand.GitCalls(_commands.Shell, text))
        {
            var (danger, id) = TypedCommand.Cost(argv);
            if (!danger) continue;
            asked = true;
            var go = id is not null && Canon.Find(id) is { } entry ? await Confirm(entry, argv) : await ConfirmLoss(argv);
            if (!go) return;
        }
        if (!asked && _commands.Shell != "git" && Dangerous.IsMatch(text))
        {
            _asking = true;
            ApplyBusy();
            bool go;
            try
            {
                go = await AskDialog.YesNo(this, "Опасная команда",
                    text + "\n" + Lang.T("Эта команда может стереть незакоммиченную работу или переписать историю, которую видят другие.") + "\n" + Lang.F("Папка: {0}", folder), "burn");
            }
            finally { _asking = false; ApplyBusy(); }
            if (!go) return;
        }
        TemplateNote.IsVisible = false;
        _commands.Ran(text);
        _commands.Last = "";
        _commands.Save();
        _recall = -1;
        CommandBox.Text = "";
        if (_runner.Running)
        {
            _queued.Enqueue((_commands.Shell, text, folder));
            SetStatus(Lang.F("Команда в очереди ({0}): пойдёт, когда закончится текущая.", _queued.Count));
            return;
        }
        StartCommand(_commands.Shell, text, folder);
    }

    void StartCommand(string shell, string text, string folder)
    {
        Launch launch;
        string shown;
        if (shell == "git")
        {
            var argv = SplitArgs(text);
            if (argv.Count == 0) return;
            if (argv[0] != "git") argv.Insert(0, "git");
            launch = ProgramLaunch(argv, folder);
            shown = Canon.Show(argv);
        }
        else if (shell == "cmd")
        {
            launch = new Launch { Exe = "cmd.exe", Line = "/d /s /c \"chcp 65001 >nul & cmd /d /s /c \"" + text + "\"\"", Folder = folder, Env = GitEnv() };
            shown = text;
        }
        else
        {
            launch = new Launch { Exe = Paths.Ps, Args = { "-NoLogo", "-NoProfile", "-Command", PsStart + text }, Folder = folder, Env = GitEnv() };
            shown = text;
        }
        // A command that names an operation of the canon gets its words under it, as a button would.
        var known = shell == "git" ? Canon.All.FirstOrDefault(c => c.Args.Count > 1 && c.Args[0] == "git" && shown.StartsWith(string.Join(" ", c.Args.TakeWhile(a => !a.Contains('{')).Take(3)), StringComparison.Ordinal)) : null;
        RunSteps(new Step
        {
            Name = shell switch { "git" => "git", "cmd" => "CMD", _ => "PS" } + " · " + Lang.T("строка"),
            Launch = launch,
            Shown = shown,
            What = known?.What ?? "",
            Undo = known?.Undo ?? "",
        });
    }

    static List<string> SplitArgs(string text) => TypedCommand.Split(text);

    void NextCommand()
    {
        if (_queued.Count == 0 || _runner.Running) return;
        var (shell, text, folder) = _queued.Dequeue();
        StartCommand(shell, text, folder);
    }

    void KeepCommand()
    {
        _queued.Clear();
        if (_commands is null) return;
        _commands.Last = (CommandBox.Text ?? "").Trim();
        _commands.Save();
    }

    void WireCommandHistory()
    {
        var search = new TextBox { Classes = { "masks" }, PlaceholderText = Lang.T("поиск по списку"), MinHeight = 24, Height = 24, Padding = new Thickness(8, 0), VerticalContentAlignment = VerticalAlignment.Center };
        PixelGrid.Field(search);
        var rows = new StackPanel { Spacing = 2 };
        var panel = new StackPanel
        {
            Children = { search, new ScrollViewer { Content = rows, MaxHeight = 380, Margin = new Thickness(0, 6, 0, 0), HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled } },
        };
        var flyout = new Flyout { Content = panel, Placement = PlacementMode.TopEdgeAlignedRight };
        CommandHistoryButton.Flyout = flyout;

        void Fill()
        {
            rows.Children.Clear();
            var words = (search.Text ?? "").Split(' ', StringSplitOptions.RemoveEmptyEntries);
            foreach (var command in _commands.Listed())
            {
                if (words.Any(word => !command.Contains(word, StringComparison.OrdinalIgnoreCase))) continue;
                bool pinned = _commands.IsPinned(command);
                var pin = new Button { Classes = { "tool" }, Content = Icons.Sign("pin"), Margin = new Thickness(0, 0, 4, 0) };
                pin.Classes.Set("on", pinned);
                ToolTip.SetTip(pin, Lang.T(pinned ? "Снять закрепление." : "Закрепить: стоит первым в списке."));
                pin.Click += (_, _) => { _commands.TogglePin(command); Fill(); };
                var take = new Button
                {
                    Classes = { "crumb" }, Content = new TextBlock { Text = command, TextTrimming = Avalonia.Media.TextTrimming.CharacterEllipsis },
                    HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Left,
                };
                ToolTip.SetTip(take, command);
                take.Click += (_, _) => { flyout.Hide(); Put(command); };
                var forget = new Button { Classes = { "tool" }, Content = Icons.Sign("x"), Margin = new Thickness(4, 0, 0, 0) };
                ToolTip.SetTip(forget, Lang.T("Убрать из истории."));
                forget.Click += (_, _) => { _commands.Forget(command); Fill(); };
                var line = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto"), Children = { pin } };
                Grid.SetColumn(take, 1);
                Grid.SetColumn(forget, 2);
                line.Children.Add(take);
                line.Children.Add(forget);
                rows.Children.Add(line);
            }
            if (rows.Children.Count == 0)
                rows.Children.Add(new TextBlock { Classes = { "note" }, Text = Lang.T(_commands.Listed().Any() ? "ничего не найдено" : "История команд пуста."), Margin = new Thickness(4, 2) });
        }
        search.TextChanged += (_, _) => Fill();
        flyout.Opening += (_, _) =>
        {
            panel.Width = Math.Max((CommandBox.Parent as Control)?.Bounds.Width - 18 ?? 420, 420);
            Fill();
        };
        flyout.Opened += (_, _) => search.Focus();
    }
}
