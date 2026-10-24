using System;
using System.Collections.Generic;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Controls.Shapes;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using AudionHubManager.Core;
using AudionHubManager.Views;

namespace AudionHubManager;

/// <summary>
/// The pieces every page is built of, in the look of the shell: a button of an operation with the dot of its risk and
/// its key, a field, a pill, a block with the stripe of its colour, the letter of a file. A page holds the state of a
/// repository, so it is built in code from these, not in markup.
/// </summary>
public partial class MainWindow
{
    /// <summary>The keys of the frequent operations of the mode in sight: F2, F5... and Ctrl+Enter.</summary>
    readonly Dictionary<Key, Action> _keys = new();
    Action? _ctrlEnter;

    void OnKey(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape && _sheet.Length > 0) { ToggleSheet(_sheet); e.Handled = true; return; }
        if (e.Key == Key.Escape && _sideOver) { OpenSide(false); e.Handled = true; return; }
        if (_sheet.Length > 0) return;
        if (e.Key == Key.Enter && e.KeyModifiers.HasFlag(KeyModifiers.Control) && _ctrlEnter is { } commit) { commit(); e.Handled = true; return; }
        if (e.KeyModifiers == KeyModifiers.None && _keys.TryGetValue(e.Key, out var action) && !(_runner.Running || _asking))
        {
            action();
            e.Handled = true;
        }
    }

    static TextBlock Text(string text, params string[] classes)
    {
        var block = new TextBlock { Text = Lang.T(text), VerticalAlignment = VerticalAlignment.Center };
        foreach (var name in classes) block.Classes.Add(name);
        return block;
    }

    static Path Sign(string icon, string? ink = null)
    {
        var sign = Icons.Sign(icon);
        if (ink is not null) sign.Ink(Shape.StrokeProperty, ink);
        return sign;
    }

    static Ellipse RiskDot(string risk) =>
        new Ellipse { Classes = { "risk" } }.Ink(Shape.FillProperty, Canon.RiskInk(risk));

    /// <summary>
    /// A button of an operation: the dot of its risk, its name, its key. It is off while a command goes. The tooltip is
    /// what it does in full - for an operation of the canon, the command, the words, the risk and the way back.
    /// </summary>
    Button Op(string name, Action click, string tip, string risk = "read", string? key = null, string cls = "", string? id = null, bool sm = false, string? command = null)
    {
        var face = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 7 };
        if (risk.Length > 0 && !cls.Contains("fill")) face.Children.Add(RiskDot(risk));
        var word = new TextBlock { Classes = { "opname" }, Text = Lang.T(name), VerticalAlignment = VerticalAlignment.Center };
        // The command as it is typed in a terminal (the owner, 24.10.2026: "I am used to add, status, init everywhere -
        // caption what the command is"): under the name on the bar, beside it on a small button; not when the name is it.
        // As it is said in the trade - add, status, restore --staged: "git" is the same on every button; the tooltip and
        // the terminal say the command whole. A caption that only repeats the name (pull / pull --ff-only) is not written.
        var shown = command is null ? "" : command.StartsWith("git ", StringComparison.Ordinal) ? command[4..] : command;
        if (shown.Length > 0 && !name.StartsWith(shown, StringComparison.OrdinalIgnoreCase) && !name.EndsWith(shown, StringComparison.OrdinalIgnoreCase)
            && !shown.StartsWith(name + " ", StringComparison.OrdinalIgnoreCase) && !shown.Equals(name, StringComparison.OrdinalIgnoreCase))
        {
            var said = new TextBlock { Classes = { "opcmd" }, Text = shown, VerticalAlignment = VerticalAlignment.Center };
            if (sm) { face.Children.Add(word); face.Children.Add(said); }
            else face.Children.Add(new StackPanel { VerticalAlignment = VerticalAlignment.Center, Children = { word, said } });
        }
        else face.Children.Add(word);
        if (key is not null) face.Children.Add(new Border { Classes = { "key" }, Child = new TextBlock { Text = key } });
        var button = new Button { Classes = { "op" }, Content = face };
        if (sm) button.Classes.Add("sm");
        foreach (var c in cls.Split(' ', StringSplitOptions.RemoveEmptyEntries)) button.Classes.Add(c);
        ToolTip.SetTip(button, Lang.T(tip));
        if (id is not null) Avalonia.Automation.AutomationProperties.SetAutomationId(button, id);
        button.Click += (_, _) => click();
        _starters.Add(button);
        button.IsEnabled = !_runner.Running && !_asking;
        return button;
    }

    /// <summary>A button of an operation of the canon; its values are asked at the press, from the page as it is then.</summary>
    Button OpCanon(string canonId, string name, Func<Dictionary<string, object>?> values, string? key = null, string cls = "", bool sm = false, Action<int>? done = null)
    {
        var entry = Canon.Find(canonId);
        var tip = entry?.Tip() ?? canonId;
        var button = Op(name, () => RunCanon(canonId, values(), done), tip, entry?.Risk ?? "read", key, cls, "op_" + canonId, sm, entry?.Short);
        if (entry?.Risk == "danger" && !cls.Contains("fill")) button.Classes.Add("burn");
        return button;
    }

    static TextBox Field(string placeholder, string text = "", double width = double.NaN, string? tip = null, string? id = null)
    {
        var box = new TextBox
        {
            Classes = { "masks" }, Text = text, PlaceholderText = Lang.T(placeholder), Height = 28, MinHeight = 28, Padding = new Thickness(8, 0),
            VerticalContentAlignment = VerticalAlignment.Center, VerticalAlignment = VerticalAlignment.Center, Width = width,
        };
        PixelGrid.Field(box);
        if (tip is not null) ToolTip.SetTip(box, Lang.T(tip));
        if (id is not null) Avalonia.Automation.AutomationProperties.SetAutomationId(box, id);
        return box;
    }

    static Border Pill(string text, string kind = "")
    {
        var pill = new Border { Classes = { "pill" }, Child = new TextBlock { Text = Lang.T(text) }, HorizontalAlignment = HorizontalAlignment.Left };
        if (kind.Length > 0) pill.Classes.Add(kind);
        return pill;
    }

    static Border VSep(double height = 20) => new() { Classes = { "vsep" }, Height = height, Margin = new Thickness(6, 0) };

    /// <summary>A block of a page: the stripe of its colour at the left, the name in the first line with its tools at the right.</summary>
    static Border Block(string title, string stripe, Control body, Control? right = null, Thickness? pad = null)
    {
        var head = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto"), Margin = new Thickness(0, 0, 0, 8), MinHeight = 22 };
        head.Children.Add(Text(title, "blocktitle"));
        if (right is not null) { Grid.SetColumn(right, 2); head.Children.Add(right); }
        // The stripe stands a few pixels further from the rim than it did (5 -> 9) and the text twice as far from the stripe
        // (6 -> 12) - the owner, 24.10.2026: "the marker is bright everywhere and the gap is very small", then "it was pressed
        // to the rim even more - the other way".
        var inner = new DockPanel { Margin = pad ?? new Thickness(24, 9, 11, 10) };
        DockPanel.SetDock(head, Dock.Top);
        inner.Children.Add(head);
        inner.Children.Add(body);
        var bar = new Border { Width = 3, CornerRadius = new CornerRadius(2), Margin = new Thickness(9, 9, 0, 9), HorizontalAlignment = HorizontalAlignment.Left, Opacity = 0.5 }
            .Ink(Border.BackgroundProperty, stripe);
        return new Border { Classes = { "pblock" }, Child = new Panel { Children = { bar, inner } } };
    }

    /// <summary>The colour of a letter of Git: in the index green, changed gold, new sea, deleted coral, conflict orange.</summary>
    static string LetterInk(char letter, bool staged = false) => letter switch
    {
        'U' => "GitConflict",
        '?' => "GitNew",
        'A' => "GitStaged",
        'D' => "GitDeleted",
        'R' or 'C' => "GitRenamed",
        '-' => "GitOut",
        _ => staged ? "GitStaged" : "GitModified",
    };

    static Border Letter(char letter, bool staged = false)
    {
        var ink = LetterInk(letter, staged);
        var text = new TextBlock { Text = letter.ToString() }.Ink(TextBlock.ForegroundProperty, ink);
        var chip = new Border { Classes = { "st" }, Child = text };
        chip.Background = App.Ink(ink) is ISolidColorBrush brush ? new SolidColorBrush(brush.Color, 0.16) : Brushes.Transparent;
        return chip;
    }

    /// <summary>A chip of a choice: a switch among its neighbours; the chosen one lit.</summary>
    static ToggleButton Chip(string text, bool on, Action click, string? tip = null)
    {
        var chip = new ToggleButton { Classes = { "switch", "chip" }, Content = Lang.T(text), IsChecked = on };
        if (tip is not null) ToolTip.SetTip(chip, Lang.T(tip));
        chip.Click += (_, _) => click();
        return chip;
    }

    /// <summary>
    /// The bar under the page: the frequent operations of the mode and their fields. A field marked to grow takes what
    /// is left; a null is a thin rule between groups.
    /// </summary>
    void SetOps(params Control?[] items)
    {
        OpsRow.Children.Clear();
        OpsRow.ColumnDefinitions.Clear();
        foreach (var item in items)
        {
            var control = item ?? VSep(22);
            bool grow = control is TextBox box && box.Tag as string == "grow" || control.Tag as string == "grow";
            // The least width of a growing field belongs to its column, not to the field: a field wider than what its column
            // got was drawn over the button before it (ПРОЕКТЫ: the address of a clone over "найти в папке").
            OpsRow.ColumnDefinitions.Add(grow ? new ColumnDefinition(GridLength.Star) { MinWidth = 140 } : new ColumnDefinition(GridLength.Auto));
            Grid.SetColumn(control, OpsRow.ColumnDefinitions.Count - 1);
            if (grow) control.Margin = new Thickness(0, 0, 6, 0);
            OpsRow.Children.Add(control);
        }
    }

    static T Grow<T>(T control) where T : Control
    {
        control.Tag = "grow";
        return control;
    }

    /// <summary>A list of rows in the look of the window: its own scroll, rows without a rim.</summary>
    static ListBox Rows(string id)
    {
        var list = new ListBox { Classes = { "rows" }, SelectionMode = SelectionMode.Single };
        ScrollViewer.SetHorizontalScrollBarVisibility(list, ScrollBarVisibility.Disabled);
        Avalonia.Automation.AutomationProperties.SetAutomationId(list, id);
        return list;
    }

    /// <summary>A row of cells over a list: the names of its columns.</summary>
    static Grid Heads(string columns, params string[] names)
    {
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions(columns), Margin = new Thickness(8, 6, 8, 4) };
        for (int i = 0; i < names.Length; i++)
        {
            var head = Text(names[i], "colhead");
            Grid.SetColumn(head, i);
            grid.Children.Add(head);
        }
        return grid;
    }

    /// <summary>A grid row of cells, as the heads lay them out. A text that does not fit its column fades out at its end.</summary>
    static Grid Cells(string columns, params Control?[] cells)
    {
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions(columns), Margin = new Thickness(8, 0), MinHeight = 26 };
        for (int i = 0; i < cells.Length; i++)
        {
            if (cells[i] is not { } cell) continue;
            if (cell is TextBlock text)
                cell = new FadeBox(text) { VerticalAlignment = text.VerticalAlignment, HorizontalAlignment = text.HorizontalAlignment };
            Grid.SetColumn(cell, i);
            grid.Children.Add(cell);
        }
        return grid;
    }

    static TextBlock Cell(string text, string? ink = null, bool quiet = false, bool bold = false)
    {
        var cell = new TextBlock { Classes = { "cell" }, Text = text };
        if (quiet) cell.Classes.Add("quiet");
        if (bold) cell.FontWeight = FontWeight.SemiBold;
        if (ink is not null) cell.Ink(TextBlock.ForegroundProperty, ink);
        return cell;
    }

    /// <summary>"сегодня 14:05", "вчера 23:10", "22.10 14:40", "22.10.2025".</summary>
    static string When(DateTime when)
    {
        var today = DateTime.Today;
        if (when.Date == today) return Lang.T("сегодня") + " " + when.ToString("HH:mm");
        if (when.Date == today.AddDays(-1)) return Lang.T("вчера") + " " + when.ToString("HH:mm");
        return when.Year == today.Year ? when.ToString("dd.MM HH:mm") : when.ToString("dd.MM.yyyy");
    }

    /// <summary>A note in place of a page that has nothing to show for a reason.</summary>
    static TextBlock Note(string text) => new()
    {
        Classes = { "note" }, Text = Lang.T(text), TextAlignment = TextAlignment.Center, TextWrapping = TextWrapping.Wrap,
        HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center, MaxWidth = 520, Margin = new Thickness(20),
    };
}
