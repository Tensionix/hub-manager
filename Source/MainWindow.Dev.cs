using System;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.LogicalTree;
using Avalonia.Media.Imaging;

namespace AudionHubManager;

/// <summary>
/// -Shot "&lt;folder&gt;": the window opens off the screen, takes a picture of every section and closes. Nothing is run;
/// the pictures are drawn from the window itself, not from the screen - no mouse, no window of the owner touched.
/// AUDION_SHOT_PROJECT names the project to show, AUDION_SHOT_SECTIONS the sections ("changes,history").
///
/// A Debug build walks a script instead when AUDION_WALK_STEPS is set: steps cut by ';' - project:ID, section:ID,
/// layer:ID, select:PATH, mark:PATH, markgroup:GROUP (as the marking menu), pick:TEXT (a commit by its message),
/// branch:NAME, type:ID=TEXT, press:ID (a button
/// by its automation id - the button is clicked, not the method behind it), key:F5, answer:yes|no, wait, shot:NAME;
/// the folder panel of ПРОЕКТЫ: folder:PATH (the panel goes where PATH lies, PATH under the cursor; empty - the disks),
/// folderopen (Enter on the row under the cursor), folderup (Backspace).
/// The text of the terminal is written to terminal.txt at the end: what ran, exactly, and what git said.
/// </summary>
public partial class MainWindow
{
    async Task TakeShots(string folder)
    {
        Directory.CreateDirectory(folder);
        try
        {
            if (Environment.GetEnvironmentVariable("AUDION_SHOT_PROJECT") is { Length: > 0 } id && _projects.FirstOrDefault(p => p.Id == id) is { } project)
                await SelectProject(project);
#if DEBUG
            if (Environment.GetEnvironmentVariable("AUDION_WALK_STEPS") is { Length: > 0 } steps)
            {
                await Walk(folder, steps);
                Close();
                return;
            }
#endif
            var sections = (Environment.GetEnvironmentVariable("AUDION_SHOT_SECTIONS") ?? "changes,history,branches,sync,mirror,projects,service").Split(',', StringSplitOptions.RemoveEmptyEntries);
            int n = 0;
            foreach (var section in sections)
            {
                SelectSection(section);
                await UpdateSection();
                await Task.Delay(700);
                Save(Path.Combine(folder, $"{++n:00}-{section}.png"));
            }
            if (Environment.GetEnvironmentVariable("AUDION_SHOT_SHEETS") == "1")
            {
                ToggleSheet("about");
                await Task.Delay(400);
                Save(Path.Combine(folder, $"{++n:00}-about.png"));
                ToggleSheet("settings");
                await Task.Delay(400);
                Save(Path.Combine(folder, $"{++n:00}-settings.png"));
            }
        }
        catch (Exception ex) { File.WriteAllText(Path.Combine(folder, "error.txt"), ex.ToString()); }
        Close();
    }

#if DEBUG
    async Task Walk(string folder, string script)
    {
        var said = new System.Text.StringBuilder();
        foreach (var raw in script.Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var cut = raw.IndexOf(':');
            var verb = cut < 0 ? raw : raw[..cut];
            var arg = cut < 0 ? "" : raw[(cut + 1)..];
            said.AppendLine("> " + raw);
            try
            {
                switch (verb)
                {
                    case "project":
                        if (_projects.FirstOrDefault(p => p.Id == arg) is { } project) await SelectProject(project);
                        break;
                    case "section": SelectSection(arg); await UpdateSection(); break;
                    case "layer": await SelectLayer(arg); break;
                    case "select":
                        if (_files is not null && _rows.FirstOrDefault(r => r.Path == arg || r.Key == arg) is { } row) _files.SelectedItem = row;
                        break;
                    case "mark": _marked.Add(arg); ShowFiles(); break;
                    case "tick": _markedProjects.Add(arg); ShowSide(true); break;
                    // What the menu of the root does: a flyout item is not pressed by press:. An empty folder gives the default back.
                    case "root": SetProjectsRoot(arg.Length == 0 ? null : arg); break;
                    case "markgroup":
                        // What the marking menu does ("mark every new"): a flyout item is not pressed by press:.
                        foreach (var r in VisibleRows().Where(r => r.Head.Length == 0 && !r.Up && !r.IsDir && r.Group == arg)) _marked.Add(r.Path);
                        ShowFiles();
                        break;
                    case "pick":
                        if (_commits is not null && _commitRows.FirstOrDefault(r => r.Commit.Subject.Contains(arg, StringComparison.Ordinal)) is { } c) _commits.SelectedItem = c;
                        break;
                    case "branch":
                        if (_branchList is not null && _branchRows.FirstOrDefault(r => r.Name == arg) is { } b) _branchList.SelectedItem = b;
                        break;
                    case "folder": FoldersGo(arg.Length == 0 ? "" : new DirectoryInfo(arg).Parent?.FullName ?? "", arg); break;
                    case "folderopen": FoldersOpen(); break;
                    case "folderup": FoldersUp(); break;
                    case "type":
                        var eq = arg.IndexOf('=');
                        if (Find(arg[..eq]) is TextBox box) box.Text = arg[(eq + 1)..];
                        else said.AppendLine("  no text box " + arg[..eq]);
                        break;
                    case "press":
                        if (Find(arg) is Button button) button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                        else said.AppendLine("  no button " + arg);
                        break;
                    case "key":
                        if (Enum.TryParse<Avalonia.Input.Key>(arg, out var key) && _keys.TryGetValue(key, out var action)) action();
                        break;
                    case "answer":
                        var yes = arg == "yes";
                        Views.AskDialog.DevAnswer = (title, message, _) => { said.AppendLine($"  asked: {title} | {message.Replace('\n', ' ')} -> {(yes ? "yes" : "no")}"); return yes; };
                        break;
                    case "wait":
                        await Task.Delay(300);
                        for (int i = 0; i < 600 && (_runner.Running || _steps.Count > 0 || _refreshing || _marking); i++) await Task.Delay(100);
                        await Task.Delay(900);
                        break;
                    case "shot": Save(Path.Combine(folder, arg + ".png")); break;
                }
            }
            catch (Exception ex) { said.AppendLine("  error: " + ex.Message); }
            await Task.Delay(150);
        }
        File.WriteAllText(Path.Combine(folder, "walk.txt"), said.ToString());
        File.WriteAllText(Path.Combine(folder, "terminal.txt"), _logAll.ToString());
    }

    Control? Find(string id) => this.GetLogicalDescendants().OfType<Control>()
        .FirstOrDefault(c => Avalonia.Automation.AutomationProperties.GetAutomationId(c) == id && c.IsEffectivelyVisible);
#endif

    void Save(string file)
    {
        double scale = RenderScaling;
        var size = new Avalonia.PixelSize((int)(Bounds.Width * scale), (int)(Bounds.Height * scale));
        using var bitmap = new RenderTargetBitmap(size, new Avalonia.Vector(96 * scale, 96 * scale));
        bitmap.Render(this);
        using var picture = File.Create(file);
        bitmap.Save(picture, new PngBitmapEncoderOptions());
    }
}
