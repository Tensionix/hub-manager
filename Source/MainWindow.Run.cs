using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Threading;
using AudionHubManager.Core;
using AudionHubManager.Views;

namespace AudionHubManager;

/// <summary>
/// A run: one command at a time - a Git operation of the canon, a command of the console door, a command typed in the
/// line. In the terminal a run is a block: its name, the command exactly as typed, a line of plain words under it
/// (ОБЪЯСНЯТЬ), what the command said in its own colours, and how it ended. Several steps of one press - a commit and
/// then its tag - run one after another, and a step that failed stops the rest.
/// </summary>
public partial class MainWindow
{
    /// <summary>One step of a run.</summary>
    sealed class Step
    {
        public string Name { get; init; } = "";
        public Launch Launch { get; init; } = new();
        /// <summary>The command as a person types it: "git add -- README.md", "hub_cli.cmd mirror plan demo".</summary>
        public string Shown { get; init; } = "";
        public string What { get; init; } = "";
        public string Undo { get; init; } = "";
        /// <summary>The output is the JSON of the door: kept, not printed, and given to <see cref="Read"/> at the end.</summary>
        public bool Quiet { get; init; }
        public Action<int, string>? Read { get; init; }
        public Action<int>? Done { get; init; }
        /// <summary>Where the step acts, when it is not the layer in sight: a project of КОММИТ ОТМЕЧЕННЫХ.</summary>
        public string Where { get; init; } = "";
    }

    string _runName = "";
    DateTime _started;
    readonly DispatcherTimer _clock = new() { Interval = TimeSpan.FromSeconds(1) };
    readonly Queue<Step> _steps = new();
    Step? _step;
    readonly StringBuilder _quiet = new();
    bool _asking;
    /// <summary>The controls that start something: off while a command goes (MainWindow.Build.cs registers them).</summary>
    readonly List<Control> _starters = new();

    /// <summary>The variables a git of a button runs with: its colours and no prompt - the command shown stays the command typed.</summary>
    static Dictionary<string, string> GitEnv() => new()
    {
        ["GIT_CONFIG_COUNT"] = "2",
        ["GIT_CONFIG_KEY_0"] = "color.ui",
        ["GIT_CONFIG_VALUE_0"] = "always",
        ["GIT_CONFIG_KEY_1"] = "core.quotepath",
        ["GIT_CONFIG_VALUE_1"] = "false",
        ["GIT_TERMINAL_PROMPT"] = "0",
        // Nothing here can show an editor: a command that wants one (an interactive rebase typed in the line) takes what it has.
        ["GIT_EDITOR"] = "true",
        ["GIT_SEQUENCE_EDITOR"] = "true",
    };

    /// <summary>A launch of a program of the canon - git, ssh, gh, glab - in the root of the layer.</summary>
    static Launch ProgramLaunch(IReadOnlyList<string> argv, string folder, string stdin = "")
    {
        var launch = new Launch { Exe = argv[0] == "git" ? Git.Exe : argv[0], Folder = folder, Env = GitEnv(), MarkErrors = false, Stdin = stdin };
        launch.Args.AddRange(argv.Skip(1));
        return launch;
    }

    void ApplyBusy()
    {
        bool free = !_runner.Running && !_asking;
        foreach (var control in _starters) control.IsEnabled = free;
        StopButton.IsVisible = _runner.Running;
        CommandRunButton.IsEnabled = true;
    }

    /// <summary>
    /// A press of an operation of the canon: the command is put together from the table and the values the page gives,
    /// asked about when it may lose work, and run in the repository of the layer. A template - a command the page
    /// cannot finish by itself - goes into the command line with its places marked.
    /// </summary>
    async void RunCanon(string id, Dictionary<string, object>? values = null, Action<int>? done = null, string? name = null)
    {
        if (Canon.Find(id) is not { } entry) { SetStatus(Lang.F("Операции {0} нет в каноне программы.", id)); return; }
        if (ActiveRoot() is not { } root) return;
        List<string> argv;
        try { argv = entry.Argv(values ?? new()); }
        catch (KeyError) { SetStatus(Lang.F("{0}: не хватает значения - выберите файл, коммит или ветку.", entry.Display)); return; }
        if (entry.Mode == "template") { PutTemplate(entry, argv); return; }
        if (entry.Risk == "danger" && !await Confirm(entry, argv)) return;
        RunSteps(GitStep(entry, argv, root, done, name));
    }

    Step GitStep(CanonEntry entry, List<string> argv, string root, Action<int>? done = null, string? name = null, string where = "")
    {
        // Thousands of paths go through the input of git, not its command line (Canon.Fit).
        var (fitted, stdin, _) = Canon.Fit(argv);
        return new()
        {
            Name = name ?? entry.Display.Split(' ').Take(argv[0] == "git" ? 2 : 1).Aggregate((a, b) => a + " " + b),
            Launch = ProgramLaunch(fitted, root, stdin),
            Shown = Canon.Brief(argv),
            What = entry.What,
            Undo = entry.Undo,
            Done = done,
            Where = where,
        };
    }

    /// <summary>A command of the door through the runner: its JSON is read at the end, a summary goes to the terminal.</summary>
    Step HubStep(string name, IReadOnlyList<string> args, string what, Action<int, string> read, Action<int>? done = null, string where = "") => new()
    {
        Name = name,
        Launch = Hub.Launch(args),
        Shown = Hub.Line(args),
        What = what,
        Quiet = true,
        Read = read,
        Done = done,
        Where = where,
    };

    /// <summary>
    /// A question before a command that can lose work: the command exactly, what it does, what is at stake now, how to
    /// undo it. A reset --hard is confirmed by typing RESET.
    /// </summary>
    Task<bool> Confirm(CanonEntry entry, List<string> argv) => Confirm(argv, entry.What, entry.Undo, entry.Tags.Contains("typed"));

    /// <summary>The same question for a command the canon has no entry of: what it can cost, and what is at stake now.</summary>
    Task<bool> ConfirmLoss(List<string> argv) =>
        Confirm(argv, Lang.T("Эта команда может стереть незакоммиченную работу или переписать историю, которую видят другие."), "", false);

    async Task<bool> Confirm(List<string> argv, string what, string undo, bool typedWord)
    {
        var stake = new StringBuilder();
        stake.Append(Canon.Brief(argv)).Append('\n').Append(what);
        if (_state is { } state && (state.StagedCount + state.ChangedCount + state.NewCount) > 0)
            stake.Append('\n').Append(Lang.F("Сейчас не закоммичено: в индексе {0}, изменено {1}, новых {2}.", state.StagedCount, state.ChangedCount, state.NewCount));
        if (undo.Length > 0) stake.Append('\n').Append(undo);
        _asking = true;
        ApplyBusy();
        try
        {
            bool typed = typedWord && _settings.TypedConfirm;
            return typed
                ? await AskDialog.Typed(this, Lang.T("Опасная команда"), stake.ToString(), "RESET")
                : await AskDialog.YesNo(this, Lang.T("Опасная команда"), stake.ToString(), "burn");
        }
        finally
        {
            _asking = false;
            ApplyBusy();
        }
    }

    /// <summary>Runs the steps one after another; a run that goes already takes them after itself.</summary>
    void RunSteps(params Step[] steps)
    {
        foreach (var step in steps) _steps.Enqueue(step);
        if (!_runner.Running) NextStep();
    }

    void NextStep()
    {
        if (_runner.Running || _steps.Count == 0) return;
        var step = _steps.Dequeue();
        _step = step;
        _runName = step.Name;
        _started = DateTime.Now;
        _quiet.Clear();
        _ansi.Reset();
        // What the run says is read in the terminal: a sheet over it steps aside.
        if (_sheet.Length > 0) ToggleSheet(_sheet);
        var head = new List<string> { "", $"===== {_runName} · {(step.Where.Length > 0 ? step.Where : LayerWord())} =====",(step.Launch.Exe == Paths.Python ? "› " : "$ ") + step.Shown };
        if (_settings.Explain && step.What.Length > 0)
        {
            // The words of the canon come in the language already; those of a step of the console command are Russian.
            head.Add("  ↳ " + Lang.T(step.What));
            if (step.Undo.Length > 0 && step.Undo != "—") head.Add("  ↳ " + Lang.T(step.Undo));
        }
        AppendLines(head);
        if (_runner.Start(step.Launch) is { } failed)
        {
            AppendLines(new[] { "[ERR] " + Lang.F("не запустилось: {0}", failed) });
            SetStatus("Не запустилось: причина в терминале.");
            _steps.Clear();
            _step = null;
            return;
        }
        SetStatus(_runName);
        ShowClock();
        _clock.Start();
        ActivityText.Text = _runName + "…";
        ActivityDot.Classes.Set("pulse", true);
        ActivityRow.IsVisible = true;
        ApplyBusy();
    }

    void OnOutput(IReadOnlyList<string> lines)
    {
        if (_step?.Quiet == true)
        {
            // The JSON of the door is not for reading: kept whole; a line of its error stream is shown at once.
            foreach (var line in lines)
            {
                if (line.StartsWith("[ERR] ", StringComparison.Ordinal)) AppendLines(new[] { line });
                else _quiet.AppendLine(line);
            }
            return;
        }
        AppendLines(lines, told: true);
    }

    void ShowClock()
    {
        var span = DateTime.Now - _started;
        ClockText.Text = span.TotalHours >= 1 ? span.ToString(@"h\:mm\:ss") : span.ToString(@"mm\:ss");
    }

    /// <summary>STOP: the command ends with everything it started (Core\ChildJob.cs); the steps after it do not run.</summary>
    void StopRun()
    {
        if (!_runner.Running) return;
        _steps.Clear();
        // A chain of КОММИТ ОТМЕЧЕННЫХ ends with the step: the projects after it are not begun (MainWindow.Marked.cs).
        if (_marking) _markedHalt = true;
        AppendLines(new[] { "[GUI] " + Lang.T("остановлено кнопкой СТОП") });
        _runner.Stop();
    }

    void OnFinished(int code, bool stopped)
    {
        _clock.Stop();
        ShowClock();
        ActivityDot.Classes.Set("pulse", false);
        ActivityRow.IsVisible = false;
        var step = _step;
        _step = null;
        _ansi.Reset();
        if (step?.Quiet == true)
        {
            try { step.Read?.Invoke(code, _quiet.ToString()); }
            catch (Exception ex) { AppendLines(new[] { "[GUI ERROR] " + ex.Message }); }
        }
        string word = stopped ? "STOPPED" : code == 0 ? "OK" : "FAILED";
        AppendLines(new[] { $"===== {word}: {_runName} · {ClockText.Text}{(code != 0 && !stopped ? " · exit " + code : "")} =====" });
        SetStatus(stopped ? Lang.F("Остановлено: {0}", _runName) : code == 0 ? Lang.F("Готово: {0}", _runName) : Lang.F("{0}: ошибка - подробности в терминале.", _runName));
        try { step?.Done?.Invoke(code); }
        catch (Exception ex) { AppendLines(new[] { "[GUI ERROR] " + ex.Message }); }
        // A step that failed or was stopped takes the rest of its press with it.
        if (stopped || code != 0) _steps.Clear();
        ApplyBusy();
        if (_closeAfterRun) { Close(); return; }
        if (_steps.Count > 0) { NextStep(); return; }
        NextCommand();
        // What a command changed is shown at once: the state, the panel, the counts of the sections.
        RefreshSoon(0);
    }

    // ------------------------------------------------------------ the end of the window

    bool _closeAfterRun, _closeAsking;

    /// <summary>
    /// The window closes. A command that goes is asked about - closing stops it; on a "yes" it is stopped and the
    /// window closes when it has ended. Windows shutting down is not asked.
    /// </summary>
    void OnClosing(object? sender, WindowClosingEventArgs e)
    {
        if (_runner.Running && e.CloseReason == WindowCloseReason.WindowClosing)
        {
            e.Cancel = true;
            if (!_closeAfterRun) AskToClose();
            return;
        }
        if (_runner.Running) _runner.StopForClose();
        KeepCommand();
        SaveWindow();
    }

    async void AskToClose()
    {
        if (_closeAsking) return;
        _closeAsking = true;
        try
        {
            var go = await AskDialog.YesNo(this, "Закрыть окно и остановить команду?",
                Lang.F("Идёт «{0}».", _runName) + "\n" + Lang.T("Команда будет остановлена вместе со всем, что она запустила."), "burn");
            if (!go) return;
            if (!_runner.Running) { Close(); return; }
            _closeAfterRun = true;
            StopRun();
        }
        finally { _closeAsking = false; }
    }
}
