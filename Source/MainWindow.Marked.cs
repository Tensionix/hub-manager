using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Threading;
using AudionHubManager.Core;

namespace AudionHubManager;

/// <summary>
/// КОММИТ ОТМЕЧЕННЫХ: a checkpoint of every project ticked in the column, one after another, by the procedure of SKILL.md -
/// the mirror SOURCE → GIT COPY, its check by BLAKE3, the secrets of the GIT COPY, the profile over the changed paths, add,
/// commit with one subject for all. Every command goes to the terminal as a button would run it. A project where a step
/// says no stops there, named with why, and the next one goes on; a GIT COPY with nothing new is no error.
/// </summary>
public partial class MainWindow
{
    TextBox? _markedSubject;
    Button? _markedCommit;
    int _markedDone, _markedClean, _markedStopped;
    /// <summary>The chain goes - between its steps too, when the runner is free; СТОП ends it, not only the step in work.</summary>
    bool _marking, _markedHalt;

    Control BuildMarkedCommit()
    {
        _markedSubject = Field("тема коммита отмеченных", "", tip: "Тема коммита - одна для всех отмеченных проектов: что сделано и зачем.", id: "marked_subject");
        _markedSubject.KeyDown += (_, e) => { if (e.Key == Avalonia.Input.Key.Enter) { CommitMarked(); e.Handled = true; } };
        _markedCommit = Op("КОММИТ ОТМЕЧЕННЫХ", CommitMarked,
            "Контрольная точка каждого отмеченного проекта в его GIT-КОПИИ: зеркало ИСХОДНИК → GIT-КОПИЯ, сверка BLAKE3, проверка секретов, проверка профилем, add и commit с этой темой. Проект, где шаг говорит «нет», останавливается, остальные идут дальше.",
            "local", cls: "fill", id: "marked_commit", sm: true);
        _markedCommit.HorizontalAlignment = HorizontalAlignment.Stretch;
        var block = new StackPanel { Spacing = 6, Margin = new Thickness(8, 6, 8, 8), Children = { _markedSubject, _markedCommit } };
        return new Border { Classes = { "hsep" }, Padding = new Thickness(0), Child = block };
    }

    void CommitMarked()
    {
        if (_runner.Running || _asking || _marking) return;
        var marked = _projects.Where(p => _markedProjects.Contains(p.Id)).ToList();
        if (marked.Count == 0) { SetStatus("Отметьте проекты в колонке слева."); return; }
        var subject = (_markedSubject?.Text ?? "").Trim();
        if (subject.Length == 0) { SetStatus("Напишите тему коммита отмеченных."); _markedSubject?.Focus(); return; }
        _markedDone = _markedClean = _markedStopped = 0;
        _marking = true;
        _markedHalt = false;
        AppendLines(new[] { "", "[GUI] " + Lang.F("Коммит отмеченных ({0}): контрольная точка каждого в его GIT-КОПИИ.", marked.Count) });
        CheckpointNext(new Queue<ProjectItem>(marked), subject);
    }

    /// <summary>The next step of the chain goes when the run before it is told whole: the runner then is free, its queue final.</summary>
    static void Then(Action next) => Dispatcher.UIThread.Post(next);

    /// <summary>The answer of the console command as JSON; one that does not read is none.</summary>
    static JsonObject? JsonOf(string json)
    {
        try { return JsonNode.Parse(json) as JsonObject; } catch { return null; }
    }

    /// <summary>The numbers a step of the console command answered, a line in the terminal: what the checkpoint saw.</summary>
    Action<int, string> Tell(params string[] keys) => (_, json) =>
    {
        var root = JsonOf(json);
        if ((root?["result"]?["summary"] ?? root?["summary"]) is not JsonObject s) return;
        var line = string.Join(" · ", keys.Where(k => s[k] is not null).Select(k => k + " " + s[k]));
        if (line.Length > 0) AppendLines(new[] { "[GUI] " + line });
    };

    void CheckpointNext(Queue<ProjectItem> queue, string subject)
    {
        if (queue.Count == 0 || _markedHalt)
        {
            var said = Lang.F("Коммит отмеченных: сделано {0}, без изменений {1}, остановлено {2}.", _markedDone, _markedClean, _markedStopped);
            if (_markedHalt && queue.Count > 0) said += " " + Lang.F("СТОП: не начаты {0}.", string.Join(", ", queue.Select(q => q.Name)));
            AppendLines(new[] { "[GUI] " + said });
            SetStatus(said);
            if (_markedStopped == 0 && !_markedHalt && _markedSubject is not null) _markedSubject.Text = "";
            _marking = _markedHalt = false;
            RefreshSoon(0);
            return;
        }
        var p = queue.Dequeue();
        void Next() => CheckpointNext(queue, subject);
        void Stop(string why)
        {
            _markedStopped++;
            AppendLines(new[] { "[ERR] " + p.Name + ": " + why });
            Next();
        }
        // The history of the project lives in its GIT COPY; one without a repository of its own has no history to add to yet.
        if (!p.Layers.TryGetValue("mirror", out var copy) || !copy.Exists || copy.Repo != "own")
        {
            Stop(Lang.T("у GIT-КОПИИ нет своего репозитория - первый коммит делают по шагам, в разделе ЗЕРКАЛО и ИЗМЕНЕНИЯ."));
            return;
        }
        AppendLines(new[] { "", "[GUI] " + Lang.F("{0} - контрольная точка", p.Name) });
        // The head of every step names the project it acts on, not the one in sight.
        var where = Lang.T(LayerName("mirror")) + " · " + p.Name;
        RunSteps(HubStep("mirror apply", new[] { "mirror", "apply", p.Id, "--apply" },
            "Зеркало: ИСХОДНИК → GIT-КОПИЯ по профилю проекта.", Tell("copied", "deleted", "errors"),
            code => Then(() =>
            {
                if (code != 0) { Stop(Lang.T("зеркало не записалось - подробности выше.")); return; }
                RunSteps(HubStep("mirror verify", new[] { "mirror", "verify", p.Id },
                    "Сверка ИСХОДНИКА и GIT-КОПИИ по BLAKE3.", Tell("same", "changed", "missing", "extra"),
                    verified => Then(() =>
                    {
                        if (verified != 0) { Stop(Lang.T("GIT-КОПИЯ не сошлась с ИСХОДНИКОМ.")); return; }
                        RunSteps(HubStep("safety", new[] { "safety", p.Id, "--layer", "mirror" },
                            "Проверка секретов и тяжёлых файлов GIT-КОПИИ.", Tell("blockers", "warnings", "errors"),
                            clean => Then(() =>
                            {
                                if (clean != 0) { Stop(Lang.T("проверка секретов нашла блокирующее или не прочитала файл - отчёт в logs.")); return; }
                                _ = AddAndCommit(p, subject, where, Next, Stop);
                            }), where));
                    }), where));
            }), where));
    }

    async Task AddAndCommit(ProjectItem p, string subject, string where, Action next, Action<string> stop)
    {
        // A fault here is told and the chain goes on: a chain that died silently would leave the button off for good.
        try { await AddAndCommitWithin(p, subject, where, next, stop); }
        catch (Exception ex) { stop(ex.Message); }
    }

    async Task AddAndCommitWithin(ProjectItem p, string subject, string where, Action next, Action<string> stop)
    {
        var folder = p.Mirror;
        var state = await Git.Status(folder);
        if (state is null) { stop(Lang.T("git не прочитал GIT-КОПИЮ.")); return; }
        var paths = state.Files.Select(f => f.Path).Distinct().ToList();
        if (paths.Count == 0)
        {
            _markedClean++;
            AppendLines(new[] { "[OK] " + p.Name + ": " + Lang.T("в GIT-КОПИИ нечего коммитить.") });
            next();
            return;
        }
        // The profile over what is there; a path gone from the disk is a deletion to stage and goes as it is.
        var existing = paths.Where(x => File.Exists(Path.Combine(folder, x)) || Directory.Exists(Path.Combine(folder, x))).ToList();
        if (existing.Count > 0)
        {
            var answer = await Hub.Ask(new[] { "check-paths", p.Id, "--layer", "mirror", "--stdin" }, string.Join("\n", existing));
            if (answer.Json?["allowed"] is not JsonArray allowedList || answer.Json?["blocked"] is not JsonArray)
            {
                stop(Lang.F("проверка профилем не состоялась: {0}", answer.Error.Length > 0 ? answer.Error : answer.Line));
                return;
            }
            var allowed = allowedList.Select(n => n?.ToString() ?? "").ToHashSet(StringComparer.OrdinalIgnoreCase);
            var refused = existing.Where(x => !allowed.Contains(x)).ToList();
            if (refused.Count > 0)
            {
                stop(Lang.F("профиль не пропускает {0}: {1}", refused.Count, string.Join(", ", refused.Take(5))));
                return;
            }
        }
        var add = Canon.Get("add");
        var commit = Canon.Get("commit");
        RunSteps(GitStep(add, add.Argv(new() { ["paths"] = paths }), folder, added => Then(() =>
        {
            if (added != 0) { stop(Lang.T("add не прошёл - подробности выше.")); return; }
            RunSteps(GitStep(commit, commit.Argv(new() { ["message"] = subject }), folder, committed => Then(() =>
            {
                if (committed != 0) { stop(Lang.T("commit не прошёл - подробности выше.")); return; }
                _markedDone++;
                next();
            }), where: where));
        }), where: where));
    }
}
