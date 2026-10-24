using System;
using System.Collections.Generic;
using System.Linq;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using AudionHubManager.Core;

namespace AudionHubManager.Views;

/// <summary>What one row of the graph draws: the lanes over the commit and under it, and how they meet at its dot.</summary>
public sealed class GraphRow
{
    /// <summary>The lane of the commit's dot.</summary>
    public int Node;
    /// <summary>The lanes the row's upper half carries, and the lane each one ends at: its own, or the dot when it comes into the commit.</summary>
    public List<(int From, int To)> Top { get; } = new();
    /// <summary>The lanes of the lower half: from the dot to a parent's lane, or a lane passing by.</summary>
    public List<(int From, int To)> Bottom { get; } = new();
    public int Width;
    public bool Head;
    public bool Merge;
}

/// <summary>
/// Lays the history out in lanes, the way every graph of Git is drawn: a commit takes the lane that waits for it; its
/// first parent takes the lane after it, the others new lanes; lanes that waited for the same commit meet at its dot.
/// </summary>
public static class GraphLayout
{
    public static List<GraphRow> Lay(IReadOnlyList<GitCommit> commits, string head)
    {
        var rows = new List<GraphRow>(commits.Count);
        var lanes = new List<string?>();
        foreach (var commit in commits)
        {
            var row = new GraphRow { Head = commit.Hash == head, Merge = commit.Parents.Length > 1 };
            var waiting = Enumerable.Range(0, lanes.Count).Where(i => lanes[i] == commit.Hash).ToList();
            int node = waiting.Count > 0 ? waiting[0] : Free(lanes);
            if (node == lanes.Count) lanes.Add(null);
            row.Node = node;
            for (int i = 0; i < lanes.Count; i++)
            {
                if (lanes[i] is null) continue;
                row.Top.Add((i, waiting.Contains(i) ? node : i));
            }
            foreach (var i in waiting.Skip(1)) lanes[i] = null;
            lanes[node] = commit.Parents.Length > 0 ? commit.Parents[0] : null;
            var fromNode = new List<int>();
            if (commit.Parents.Length > 0) fromNode.Add(node);
            foreach (var parent in commit.Parents.Skip(1))
            {
                int at = lanes.IndexOf(parent);
                if (at < 0)
                {
                    at = Free(lanes, node + 1);
                    if (at == lanes.Count) lanes.Add(parent); else lanes[at] = parent;
                }
                fromNode.Add(at);
            }
            for (int i = 0; i < lanes.Count; i++)
            {
                if (lanes[i] is null) continue;
                if (fromNode.Contains(i)) row.Bottom.Add((node, i));
                else row.Bottom.Add((i, i));
            }
            // The lanes that end free at the right are dropped: the graph stays as narrow as it is.
            while (lanes.Count > 0 && lanes[^1] is null) lanes.RemoveAt(lanes.Count - 1);
            row.Width = Math.Max(node + 1, Math.Max(row.Top.Select(t => Math.Max(t.From, t.To) + 1).DefaultIfEmpty(0).Max(), row.Bottom.Select(b => Math.Max(b.From, b.To) + 1).DefaultIfEmpty(0).Max()));
            rows.Add(row);
        }
        return rows;
    }

    static int Free(List<string?> lanes, int from = 0)
    {
        for (int i = from; i < lanes.Count; i++) if (lanes[i] is null) return i;
        return lanes.Count;
    }
}

/// <summary>
/// One row of the graph: lines of the lanes in their colours, curves where lanes meet a commit, and the dot of the
/// commit - a ring for HEAD, a double dot for a merge.
/// </summary>
public sealed class GraphCell : Control
{
    public const double Lane = 14, Pad = 9;
    readonly GraphRow _row;

    public GraphCell(GraphRow row, int width)
    {
        _row = row;
        Width = Pad * 2 + Math.Max(1, width) * Lane;
        Height = 28;
        ClipToBounds = false;
    }

    static readonly string[] Inks = { "LaneA", "LaneB", "LaneC", "LaneD", "LaneE", "LaneF" };

    static IBrush Ink(int lane) => App.Ink(Inks[lane % Inks.Length]);

    static double X(int lane) => Pad + lane * Lane + Lane / 2;

    public override void Render(DrawingContext context)
    {
        double h = Bounds.Height, mid = h / 2;
        foreach (var (from, to) in _row.Top) Line(context, from, to, 0, mid, to == _row.Node && from != to ? from : from);
        foreach (var (from, to) in _row.Bottom) Line(context, from, to, mid, h, from == _row.Node && from != to ? to : from);
        var center = new Point(X(_row.Node), mid);
        var ink = Ink(_row.Node);
        if (_row.Head)
        {
            context.DrawEllipse(App.Ink("ListBg"), new Pen(ink, 2.6), center, 5.5, 5.5);
        }
        else
        {
            context.DrawEllipse(ink, null, center, 4.6, 4.6);
            if (_row.Merge) context.DrawEllipse(App.Ink("ListBg"), null, center, 1.8, 1.8);
        }
    }

    static void Line(DrawingContext context, int from, int to, double y1, double y2, int colourLane)
    {
        var pen = new Pen(Ink(colourLane), 1.8, lineCap: PenLineCap.Round);
        double x1 = X(from), x2 = X(to);
        if (Math.Abs(x1 - x2) < 0.1) { context.DrawLine(pen, new Point(x1, y1), new Point(x2, y2)); return; }
        var geometry = new StreamGeometry();
        using (var g = geometry.Open())
        {
            g.BeginFigure(new Point(x1, y1), false);
            double my = (y1 + y2) / 2;
            g.CubicBezierTo(new Point(x1, my), new Point(x2, my), new Point(x2, y2));
            g.EndFigure(false);
        }
        context.DrawGeometry(null, pen, geometry);
    }
}
