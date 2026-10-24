using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.VisualTree;

namespace AudionHubManager.Views;

/// <summary>
/// The words of the one-line controls of the window on whole pixels of the screen, with as many empty rows above them as under them.
///
/// Why: at 125% (at any scale but 100% and 200%) a point of the layout is not a whole number of pixels. The layout puts every control on a
/// whole pixel, but not what is inside a line: a word is drawn from its baseline, which Skia puts on a whole pixel of its own, and an icon of
/// 13 points is a picture of 16.25 pixels. A word does not fill its line either: the capitals of JetBrains Mono take ten rows of a line of
/// seventeen. So "centred" by the layout meant a row up in one control and a row down in another, and the icon and the word of one button apart.
///
/// What is done, for the scale of the screen and the font size as they are now (both are read, nothing is a constant):
/// 1. The rows the letters really take are found by drawing them once (<see cref="Rows"/>): the capitals of a caption, or the body of small
///    letters (the height of "х", without the tops of "б" and the tails of "р") for a caption of small letters only.
/// 2. One-line controls get heights in whole pixels such that the rows left around their capitals are an even number (<see cref="Apply"/>:
///    the resources LineButton, LineSmall, LineChip, LineField of the styles) - so a word can stand exactly in the middle.
/// 3. The text and the placeholder of a one-line field are moved by whole pixels to the middle of the field (<see cref="Field"/>).
/// Only render offsets and sizes of pictures change: the layout of the pages stays as it was.
/// </summary>
public static class PixelGrid
{
    // ------------------------------------------------------------ the heights of one-line controls

    /// <summary>The scale of the screen the window is on (1.25 at 125%).</summary>
    public static double Scale { get; private set; } = 1;

    /// <summary>
    /// Chooses the heights of one-line controls in whole pixels of this screen, so that the rows left around their capitals are even. Called
    /// when the window is made, when it goes to a screen of another scale and after the step of the font.
    /// </summary>
    public static void Apply(double scale)
    {
        if (Application.Current is not { } app || scale <= 0) return;
        Scale = scale;
        var family = app.TryGetResource("FontUi", null, out var f) && f is FontFamily ff ? ff : FontFamily.Default;
        double Size(string key, double fallback) => app.TryGetResource(key, null, out var v) && v is double d ? d : fallback;
        app.Resources["LineButton"] = Height(26, new Font(family, FontWeight.SemiBold, Size("FontButton", 10.5)), scale);
        app.Resources["LineSmall"] = Height(24, new Font(family, FontWeight.SemiBold, Size("FontSwitch", 10.5)), scale);
        app.Resources["LineChip"] = Height(24, new Font(family, FontWeight.Normal, Size("FontSwitch", 10.5)), scale);
        app.Resources["LineField"] = Height(24, new Font(family, FontWeight.Normal, Size("FontPanel", 12)), scale);
        app.Resources["LineKey"] = Height(22, new Font(family, FontWeight.SemiBold, Size("FontBase", 13)), scale);
    }

    /// <summary>The height closest above the design one, in whole pixels, with an even number of rows left around the capitals.</summary>
    static double Height(double points, Font font, double scale)
    {
        var caps = Rows(font, scale, Band.Capitals);
        var pixels = (int)Math.Round(points * scale, MidpointRounding.AwayFromZero);
        if ((pixels - caps.Count) % 2 != 0) pixels++;
        return pixels / scale;
    }

    // ------------------------------------------------------------ the rows letters take

    enum Band { Capitals, Small }

    readonly record struct Font(FontFamily Family, FontWeight Weight, double Size, FontStyle Style = FontStyle.Normal, FontStretch Stretch = FontStretch.Normal);

    /// <summary>A run of rows, from the top one to the bottom one.</summary>
    readonly record struct Span(int Top, int Bottom)
    {
        public int Count => Bottom - Top + 1;
    }

    static readonly Dictionary<(string, FontWeight, double, FontStyle, FontStretch, double, Band), Span> Probes = new();

    /// <summary>
    /// The rows the letters take when a line of this font is drawn with its top on a whole pixel: capitals ("НН") or the body of small
    /// letters ("хх"). Found on a picture drawn once for a font and a scale; a row counts when it is at least a third lit.
    /// </summary>
    static Span Rows(Font font, double scale, Band band)
    {
        var key = (font.Family.Name, font.Weight, font.Size, font.Style, font.Stretch, scale, band);
        if (Probes.TryGetValue(key, out var known)) return known;
        var found = new Span(0, 0);
        try
        {
            var sample = new TextBlock
            {
                Text = band == Band.Capitals ? "НН" : "хх", FontFamily = font.Family, FontWeight = font.Weight, FontSize = font.Size,
                FontStyle = font.Style, FontStretch = font.Stretch, Foreground = Brushes.White,
            };
            var root = new Border { Background = Brushes.Black, Child = sample };
            root.Measure(Size.Infinity);
            root.Arrange(new Rect(root.DesiredSize));
            var w = Math.Max(1, (int)Math.Ceiling(root.DesiredSize.Width * scale));
            var h = Math.Max(1, (int)Math.Ceiling(root.DesiredSize.Height * scale));
            using var bitmap = new RenderTargetBitmap(new PixelSize(w, h), new Vector(96 * scale, 96 * scale));
            bitmap.Render(root);
            var stride = w * 4;
            var buffer = Marshal.AllocHGlobal(stride * h);
            try
            {
                bitmap.CopyPixels(new PixelRect(0, 0, w, h), buffer, stride * h, stride);
                var pixels = new byte[stride * h];
                Marshal.Copy(buffer, pixels, 0, pixels.Length);
                int top = -1, bottom = -1;
                for (var y = 0; y < h; y++)
                {
                    var lit = false;
                    for (var x = 0; x < w && !lit; x++) lit = pixels[y * stride + x * 4 + 1] >= 85;   // the green channel: white on black
                    if (!lit) continue;
                    if (top < 0) top = y;
                    bottom = y;
                }
                if (top >= 0) found = new Span(top, bottom);
            }
            finally { Marshal.FreeHGlobal(buffer); }
        }
        catch { }
        return Probes[key] = found;
    }

    static Font FontOf(Control c) => new(
        c.GetValue(TextBlock.FontFamilyProperty), c.GetValue(TextBlock.FontWeightProperty), c.GetValue(TextBlock.FontSizeProperty),
        c.GetValue(TextBlock.FontStyleProperty), c.GetValue(TextBlock.FontStretchProperty));

    /// <summary>A caption of small letters only ("a", a placeholder) is centred by their body; anything with a capital or a digit, by the capitals.</summary>
    static Band BandOf(string? text)
    {
        bool upper = false, lower = false;
        foreach (var c in text ?? "") { if (char.IsUpper(c) || char.IsDigit(c)) upper = true; else if (char.IsLower(c)) lower = true; }
        return lower && !upper ? Band.Small : Band.Capitals;
    }

    /// <summary>A one-line text field: its text and its placeholder stand in the middle of the field.</summary>
    public static void Field(TextBox box) =>
        box.TemplateApplied += (_, e) =>
        {
            foreach (var part in new[] { "PART_TextPresenter", "PART_Watermark" })
                if (e.NameScope.Find<Control>(part) is { } text)
                    new Watch(box, text, () => string.IsNullOrEmpty(box.PlaceholderText) ? Band.Capitals : BandOf(box.PlaceholderText));
        };

    // ------------------------------------------------------------ placing

    sealed class Watch
    {
        readonly Control _host;
        readonly Control _word;
        readonly Func<Band> _band;

        public Watch(Control host, Control word, Func<Band> band)
        {
            _host = host; _word = word; _band = band;
            host.LayoutUpdated += (_, _) => Update();
        }

        void Update()
        {
            if (!_host.IsEffectivelyVisible) return;
            Place();
        }

        void Place()
        {
            if (TopLevel.GetTopLevel(_host) is not { } top) return;
            var scale = top.RenderScaling;
            var hostPixels = (int)Math.Round(_host.Bounds.Height * scale);
            if (hostPixels <= 0) return;
            if (!_word.IsVisible || _word.Bounds.Height <= 0) return;
            var y = TopIn(_word, _host);
            if (double.IsNaN(y)) return;
            var font = FontOf(_word);
            var band = Rows(font, scale, _band());
            var origin = (int)Math.Round(y * scale);
            var shift = 0;
            // A word of one line alone: one that wrapped stands where the layout put it - centred by its
            // first line it went down by half a line, and its second line was cut by its control.
            if (OneLine(_word, font))
            {
                var above = origin + band.Top;
                var under = hostPixels - 1 - (origin + band.Bottom);
                // when the rows cannot be shared evenly the spare one stays above: a word a row low is less seen than one a row high
                shift = (int)Math.Ceiling((under - above) / 2.0);
            }
            Shift(_word, shift, scale);
        }

        /// <summary>A word of one line: a text that wraps is left as it is.</summary>
        static bool OneLine(Control word, Font font) => word is not TextBlock tb || tb.TextWrapping == TextWrapping.NoWrap || tb.Bounds.Height < font.Size * 2;

        /// <summary>The top of a control inside the host by the layout alone (the offsets set here are render offsets and are not in it).</summary>
        static double TopIn(Control c, Control host)
        {
            double y = 0;
            for (Visual? v = c; v != null && v != host; v = v.GetVisualParent())
            {
                if (v is not Control control) return double.NaN;
                y += control.Bounds.Y;
                if (v.GetVisualParent() == null) return double.NaN;
            }
            return y;
        }

        static void Shift(Control c, int pixels, double scale)
        {
            if (pixels == 0) { if (c.RenderTransform != null) c.RenderTransform = null; return; }
            var points = pixels / scale;
            if (c.RenderTransform is TranslateTransform t && Math.Abs(t.Y - points) < 1e-6 && t.X == 0) return;
            c.RenderTransform = new TranslateTransform(0, points);
        }
    }
}
